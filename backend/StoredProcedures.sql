/* ==========================================================================
   TRAVEL AGENCY Accounting — Stored Procedures (single consolidated file)
   --------------------------------------------------------------------------
   Architecture decision (2026-10-06): this app's backend is being migrated
   to a 100% Stored Procedure persistence layer - zero ORM looping. Every
   database operation views.py performs must go through a stored procedure
   here, called via backend/accounting/sp_client.py's exec_sp() wrapper.

   Conventions every procedure in this file follows:
     - Name format: dbo.sp_<ModuleName>
     - First parameter always @Action NVARCHAR(50) - one procedure per
       module, branching internally on this (SELECT / GET_BY_ID / SAVE /
       DELETE / LOOKUP / ...).
     - CREATE OR ALTER PROCEDURE - idempotent, safe to re-run this whole
       file against an existing database.
     - SET NOCOUNT ON; always, for performance.
     - Single Result Set Rule - exactly ONE populated result set per call,
       no stray blank/interim SELECTs.
     - INSERT/UPDATE/DELETE wrapped in BEGIN TRY/BEGIN TRAN/COMMIT TRAN and
       BEGIN CATCH/ROLLBACK TRAN/THROW (or a clean error row) - never a
       half-applied write.
     - company_id is this project's multi-tenant scoping key - included in
       every WHERE clause that touches a company-scoped table.
     - SAVE/INSERT actions return SELECT SCOPE_IDENTITY() AS id,
       'Success' AS status; (plus whatever row shape the caller needs).

   Run this whole file against the live database to (re)create every
   procedure below - safe to re-run any time (CREATE OR ALTER).
   ========================================================================== */

-- ==========================================================================
-- dbo.sp_LedgerGroup
-- Module   : Ledger_Groups (Chart of Accounts group tree)
-- Actions  : SELECT (list, flat), SAVE (create)
-- Replaces : views.ledger_groups_list / views.ledger_group_create's ORM code
-- ==========================================================================
CREATE OR ALTER PROCEDURE dbo.sp_LedgerGroup
    @Action           NVARCHAR(50),
    @CompanyId        INT            = NULL,
    @Name             NVARCHAR(100)  = NULL,
    @Code             NVARCHAR(20)   = NULL,
    @AccountType      NVARCHAR(20)   = NULL,
    @ParentId         INT            = NULL,
    @IsGroup          BIT            = NULL,
    @NameVariantsJson NVARCHAR(MAX)  = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'SELECT'
    BEGIN
        -- Flat list, same shape page-ledger-entry.js's renderGroupOptions()
        -- already expects - the frontend builds the tree client-side from
        -- (id, parent_id) pairs.
        SELECT
            id, name, code, account_type, parent_id, is_group, is_system
        FROM dbo.Ledger_Groups
        WHERE company_id = @CompanyId
        ORDER BY id;
        RETURN;
    END

    IF @Action = 'LEDGERS_BY_GROUP_NAMES'
    BEGIN
        -- Powers the "Load The Data's From Group X" dropdowns on Master
        -- Mapping / FOP Master - @NameVariantsJson is a JSON array of every
        -- spelling variant worth trying (plural/singular, "and" vs "&"),
        -- already computed by the caller (views.ledgers_by_group_name).
        -- Walks the WHOLE subtree under every matched top-level group,
        -- since ledgers usually sit under a CHILD group, not directly
        -- under it.
        ;WITH matched_groups AS (
            SELECT lg.id
            FROM dbo.Ledger_Groups lg
            INNER JOIN OPENJSON(@NameVariantsJson) WITH (v NVARCHAR(100) '$') j ON j.v = lg.name COLLATE Latin1_General_CI_AS
            WHERE lg.company_id = @CompanyId
            UNION ALL
            SELECT child.id
            FROM dbo.Ledger_Groups child
            INNER JOIN matched_groups mg ON child.parent_id = mg.id
            WHERE child.company_id = @CompanyId
        )
        SELECT l.id, COALESCE(NULLIF(l.alias_name, ''), l.name) AS name
        FROM dbo.Ledgers l
        WHERE l.company_id = @CompanyId AND l.group_id IN (SELECT id FROM matched_groups)
        ORDER BY name
        OPTION (MAXRECURSION 100);
        RETURN;
    END

    IF @Action = 'SAVE'
    BEGIN
        IF @CompanyId IS NULL OR @Name IS NULL OR @AccountType IS NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status,
                   'company_id, name and account_type are required.' AS error;
            RETURN;
        END

        BEGIN TRY
            BEGIN TRAN;

            INSERT INTO dbo.Ledger_Groups
                (company_id, name, code, account_type, parent_id, is_group, is_system, created_at, updated_at)
            VALUES
                (@CompanyId, @Name, @Code, @AccountType, @ParentId, ISNULL(@IsGroup, 1), 0, SYSUTCDATETIME(), SYSUTCDATETIME());

            DECLARE @NewId INT = SCOPE_IDENTITY();

            COMMIT TRAN;

            -- Returns the full saved row, same shape model_to_dict(group)
            -- produced for the caller.
            SELECT
                id, company_id, name, code, account_type, parent_id,
                is_group, is_system, created_at, updated_at,
                'Success' AS status
            FROM dbo.Ledger_Groups
            WHERE id = @NewId;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END
END
GO

-- ==========================================================================
-- dbo.sp_Ledger
-- Module   : Ledgers (leaf accounts - customers/suppliers/banks/GL heads)
-- Actions  : LIST, LIST_CUSTOMERS, LIST_SUPPLIERS, GET_BY_ID, SAVE, UPDATE,
--            DELETE, CHECK_AGENT_ID, CHECK_NAME
-- Replaces : views.ledger_create / ledger_delete / ledger_detail /
--            ledger_update / ledger_agent_id_available /
--            ledger_name_available / customers_list / suppliers_list
-- ==========================================================================
CREATE OR ALTER PROCEDURE dbo.sp_Ledger
    @Action                     NVARCHAR(50),
    @Id                         INT            = NULL,
    @CompanyId                  INT            = NULL,
    @Name                       NVARCHAR(150)  = NULL,
    @ParentId                   INT            = NULL,
    @OpeningBalance             DECIMAL(18,2)  = NULL,
    @OpeningBalanceType         NVARCHAR(10)   = NULL,
    @LedgerCategory             NVARCHAR(20)   = NULL,
    @BankAccountNo              NVARCHAR(40)   = NULL,
    @BankBranch                 NVARCHAR(100)  = NULL,
    @IfscCode                   NVARCHAR(15)   = NULL,
    @SwiftCode                  NVARCHAR(15)   = NULL,
    @AliasName                  NVARCHAR(100)  = NULL,
    @AddressLine1               NVARCHAR(150)  = NULL,
    @AddressLine2               NVARCHAR(150)  = NULL,
    @AgentId                    NVARCHAR(30)   = NULL,
    @MaintainBalanceBillWise    NVARCHAR(5)    = NULL,
    @PlaceOfSupply              NVARCHAR(60)   = NULL,
    @City                       NVARCHAR(60)   = NULL,
    @Pincode                    NVARCHAR(10)   = NULL,
    @StateName                  NVARCHAR(60)   = NULL,
    @GstNo                      NVARCHAR(20)   = NULL,
    @GstRegistrationType        NVARCHAR(20)   = NULL,
    @PanNo                      NVARCHAR(15)   = NULL,
    @Emirate                    NVARCHAR(30)   = NULL,
    @PoBoxNo                    NVARCHAR(20)   = NULL,
    @VatTrnNo                   NVARCHAR(20)   = NULL,
    @TradeLicenseNo             NVARCHAR(30)   = NULL,
    @TradeLicenseExpiry         DATE           = NULL,
    @CreditorType               NVARCHAR(30)   = NULL,
    @SupplierCode               NVARCHAR(30)   = NULL,
    @OfficeId                   NVARCHAR(30)   = NULL,
    @TaxCategory                NVARCHAR(10)   = NULL,
    @TaxType                    NVARCHAR(10)   = NULL,
    @GstApplicable              BIT            = NULL,
    @GstTaxType                 NVARCHAR(10)   = NULL,
    @GstPercentage              DECIMAL(5,2)   = NULL,
    @TdsApplicable              BIT            = NULL,
    @TdsPercentage              DECIMAL(5,2)   = NULL,
    @HsnCode                    NVARCHAR(15)   = NULL,
    @TcsApplicable              BIT            = NULL,
    @TcsPercentage              DECIMAL(5,2)   = NULL,
    @IsDefaultBank              BIT            = NULL,
    @ExcludeId                  INT            = NULL,
    @AgentIdProvided            BIT            = 0
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'LIST'
    BEGIN
        SELECT id, company_id, name, group_id AS parent_id, account_type, ledger_category,
               opening_balance,
               CASE WHEN opening_balance_type = 'Debit' THEN opening_balance ELSE -opening_balance END AS balance,
               opening_balance_type, agent_id, office_id, supplier_code, is_default_bank
        FROM dbo.Ledgers
        WHERE company_id = @CompanyId
        ORDER BY id;
        RETURN;
    END

    IF @Action = 'LIST_CUSTOMERS'
    BEGIN
        SELECT id, name,
               'LED-' + RIGHT('00000' + CAST(id AS NVARCHAR(10)), 5) AS code,
               COALESCE(gst_no, vat_trn_no) AS gst_no,
               COALESCE(
                   NULLIF(CONCAT_WS(', ', address_line1, address_line2, city, state_name, pincode), ''),
                   NULLIF(CONCAT_WS(', ', address_line1, address_line2, emirate, po_box_no), '')
               ) AS address,
               agent_id, state_name
        FROM dbo.Ledgers
        WHERE company_id = @CompanyId AND ledger_category = 'DEBTOR'
        ORDER BY id;
        RETURN;
    END

    IF @Action = 'LIST_SUPPLIERS'
    BEGIN
        SELECT id, name,
               COALESCE(supplier_code, 'LED-' + RIGHT('00000' + CAST(id AS NVARCHAR(10)), 5)) AS code,
               office_id
        FROM dbo.Ledgers
        WHERE company_id = @CompanyId AND ledger_category = 'CREDITOR'
        ORDER BY id;
        RETURN;
    END

    IF @Action = 'GET_BY_ID'
    BEGIN
        SELECT id, name, group_id AS parent_id, opening_balance,
               CASE WHEN opening_balance_type = 'Debit' THEN opening_balance ELSE -opening_balance END AS balance,
               opening_balance_type, ledger_category,
               bank_account_no, bank_branch, ifsc_code, swift_code,
               alias_name, address_line1, address_line2, agent_id, maintain_balance_bill_wise, place_of_supply,
               city, pincode, state_name, gst_no, gst_registration_type, pan_no,
               emirate, po_box_no, vat_trn_no, trade_license_no, trade_license_expiry,
               creditor_type, supplier_code, office_id,
               tax_category, tax_type,
               gst_applicable, gst_tax_type, gst_percentage,
               tds_applicable, tds_percentage, hsn_code,
               tcs_applicable, tcs_percentage, is_default_bank
        FROM dbo.Ledgers
        WHERE id = @Id AND company_id = @CompanyId;
        RETURN;
    END

    IF @Action = 'GET_BY_NAME'
    BEGIN
        -- Resolves a ledger by (company_id, name, ledger_category) - used
        -- by the Tickets/Reschedule write path to validate/resolve
        -- Customer (DEBTOR) / Supplier (CREDITOR) ledgers without an ORM
        -- query, and to grab state_name for the JV's same-state/different-
        -- state Output GST split.
        SELECT id, name, state_name, gst_percentage
        FROM dbo.Ledgers
        WHERE company_id = @CompanyId AND name = @Name AND ledger_category = @LedgerCategory;
        RETURN;
    END

    IF @Action = 'CHECK_AGENT_ID'
    BEGIN
        SELECT CAST(CASE WHEN EXISTS (
            SELECT 1 FROM dbo.Ledgers
            WHERE agent_id = @AgentId
              AND (@ExcludeId IS NULL OR id <> @ExcludeId)
        ) THEN 0 ELSE 1 END AS BIT) AS available;
        RETURN;
    END

    IF @Action = 'CHECK_NAME'
    BEGIN
        SELECT CAST(CASE WHEN EXISTS (
            SELECT 1 FROM dbo.Ledgers
            WHERE company_id = @CompanyId AND name = @Name
              AND (@ExcludeId IS NULL OR id <> @ExcludeId)
        ) THEN 0 ELSE 1 END AS BIT) AS available;
        RETURN;
    END

    IF @Action = 'SAVE'
    BEGIN
        IF @CompanyId IS NULL OR @Name IS NULL OR @ParentId IS NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'company_id, name and parent_id are required.' AS error;
            RETURN;
        END

        DECLARE @GroupAccountType NVARCHAR(20);
        SELECT @GroupAccountType = account_type FROM dbo.Ledger_Groups WHERE id = @ParentId AND company_id = @CompanyId;
        IF @GroupAccountType IS NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'That group doesn''t exist for this company.' AS error;
            RETURN;
        END

        IF EXISTS (SELECT 1 FROM dbo.Ledgers WHERE company_id = @CompanyId AND name = @Name)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'A ledger named "' + @Name + '" already exists.' AS error;
            RETURN;
        END
        IF @AgentId IS NOT NULL AND EXISTS (SELECT 1 FROM dbo.Ledgers WHERE agent_id = @AgentId)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Agent ID "' + @AgentId + '" is already used by another ledger.' AS error;
            RETURN;
        END

        BEGIN TRY
            BEGIN TRAN;

            INSERT INTO dbo.Ledgers
                (company_id, name, group_id, account_type, ledger_category, opening_balance, opening_balance_type,
                 bank_account_no, bank_branch, ifsc_code, swift_code,
                 alias_name, address_line1, address_line2, agent_id, maintain_balance_bill_wise, place_of_supply,
                 city, pincode, state_name, gst_no, gst_registration_type, pan_no,
                 emirate, po_box_no, vat_trn_no, trade_license_no, trade_license_expiry,
                 creditor_type, supplier_code, office_id,
                 tax_category, tax_type,
                 gst_applicable, gst_tax_type, gst_percentage,
                 tds_applicable, tds_percentage, hsn_code,
                 tcs_applicable, tcs_percentage, is_default_bank,
                 is_system, created_at, updated_at)
            VALUES
                (@CompanyId, @Name, @ParentId, @GroupAccountType, ISNULL(@LedgerCategory, 'OTHER'),
                 ISNULL(@OpeningBalance, 0), ISNULL(@OpeningBalanceType, 'Debit'),
                 @BankAccountNo, @BankBranch, @IfscCode, @SwiftCode,
                 @AliasName, @AddressLine1, @AddressLine2, @AgentId, @MaintainBalanceBillWise, @PlaceOfSupply,
                 @City, @Pincode, @StateName, @GstNo, @GstRegistrationType, @PanNo,
                 @Emirate, @PoBoxNo, @VatTrnNo, @TradeLicenseNo, @TradeLicenseExpiry,
                 @CreditorType, @SupplierCode, @OfficeId,
                 @TaxCategory, @TaxType,
                 ISNULL(@GstApplicable, 0), @GstTaxType, ISNULL(@GstPercentage, 0),
                 ISNULL(@TdsApplicable, 0), ISNULL(@TdsPercentage, 0), @HsnCode,
                 ISNULL(@TcsApplicable, 0), ISNULL(@TcsPercentage, 0), ISNULL(@IsDefaultBank, 0),
                 0, SYSUTCDATETIME(), SYSUTCDATETIME());

            DECLARE @NewId INT = SCOPE_IDENTITY();
            -- Only one Default Bank per company - this one replaces any other.
            IF @IsDefaultBank = 1
                UPDATE dbo.Ledgers SET is_default_bank = 0, updated_at = SYSUTCDATETIME()
                WHERE company_id = @CompanyId AND id <> @NewId AND is_default_bank = 1;
            COMMIT TRAN;

            SELECT id, name, group_id AS parent_id, 'Success' AS status
            FROM dbo.Ledgers WHERE id = @NewId;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END

    IF @Action = 'UPDATE'
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM dbo.Ledgers WHERE id = @Id AND company_id = @CompanyId)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Ledger not found.' AS error;
            RETURN;
        END
        IF @Name IS NOT NULL AND EXISTS (
            SELECT 1 FROM dbo.Ledgers WHERE company_id = @CompanyId AND name = @Name AND id <> @Id
        )
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'A ledger named "' + @Name + '" already exists.' AS error;
            RETURN;
        END
        IF @AgentId IS NOT NULL AND EXISTS (
            SELECT 1 FROM dbo.Ledgers WHERE agent_id = @AgentId AND id <> @Id
        )
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Agent ID "' + @AgentId + '" is already used by another ledger.' AS error;
            RETURN;
        END

        DECLARE @NewGroupAccountType NVARCHAR(20);
        IF @ParentId IS NOT NULL
        BEGIN
            SELECT @NewGroupAccountType = account_type FROM dbo.Ledger_Groups WHERE id = @ParentId AND company_id = @CompanyId;
            IF @NewGroupAccountType IS NULL
            BEGIN
                SELECT NULL AS id, 'Error' AS status, 'That group doesn''t exist for this company.' AS error;
                RETURN;
            END
        END

        BEGIN TRY
            BEGIN TRAN;

            UPDATE dbo.Ledgers
            SET name = ISNULL(@Name, name),
                group_id = ISNULL(@ParentId, group_id),
                account_type = ISNULL(@NewGroupAccountType, account_type),
                opening_balance = ISNULL(@OpeningBalance, opening_balance),
                opening_balance_type = ISNULL(@OpeningBalanceType, opening_balance_type),
                ledger_category = ISNULL(@LedgerCategory, ledger_category),
                bank_account_no = ISNULL(@BankAccountNo, bank_account_no),
                bank_branch = ISNULL(@BankBranch, bank_branch),
                ifsc_code = ISNULL(@IfscCode, ifsc_code),
                swift_code = ISNULL(@SwiftCode, swift_code),
                alias_name = ISNULL(@AliasName, alias_name),
                address_line1 = ISNULL(@AddressLine1, address_line1),
                address_line2 = ISNULL(@AddressLine2, address_line2),
                agent_id = CASE WHEN @AgentIdProvided = 1 THEN @AgentId ELSE agent_id END,
                maintain_balance_bill_wise = ISNULL(@MaintainBalanceBillWise, maintain_balance_bill_wise),
                place_of_supply = ISNULL(@PlaceOfSupply, place_of_supply),
                city = ISNULL(@City, city),
                pincode = ISNULL(@Pincode, pincode),
                state_name = ISNULL(@StateName, state_name),
                gst_no = ISNULL(@GstNo, gst_no),
                gst_registration_type = ISNULL(@GstRegistrationType, gst_registration_type),
                pan_no = ISNULL(@PanNo, pan_no),
                emirate = ISNULL(@Emirate, emirate),
                po_box_no = ISNULL(@PoBoxNo, po_box_no),
                vat_trn_no = ISNULL(@VatTrnNo, vat_trn_no),
                trade_license_no = ISNULL(@TradeLicenseNo, trade_license_no),
                trade_license_expiry = ISNULL(@TradeLicenseExpiry, trade_license_expiry),
                creditor_type = ISNULL(@CreditorType, creditor_type),
                supplier_code = ISNULL(@SupplierCode, supplier_code),
                office_id = ISNULL(@OfficeId, office_id),
                tax_category = ISNULL(@TaxCategory, tax_category),
                tax_type = ISNULL(@TaxType, tax_type),
                gst_applicable = ISNULL(@GstApplicable, gst_applicable),
                gst_tax_type = ISNULL(@GstTaxType, gst_tax_type),
                gst_percentage = ISNULL(@GstPercentage, gst_percentage),
                tds_applicable = ISNULL(@TdsApplicable, tds_applicable),
                tds_percentage = ISNULL(@TdsPercentage, tds_percentage),
                hsn_code = ISNULL(@HsnCode, hsn_code),
                tcs_applicable = ISNULL(@TcsApplicable, tcs_applicable),
                tcs_percentage = ISNULL(@TcsPercentage, tcs_percentage),
                is_default_bank = ISNULL(@IsDefaultBank, is_default_bank),
                updated_at = SYSUTCDATETIME()
            WHERE id = @Id AND company_id = @CompanyId;

            -- Only one Default Bank per company - this one replaces any other.
            IF @IsDefaultBank = 1
                UPDATE dbo.Ledgers SET is_default_bank = 0, updated_at = SYSUTCDATETIME()
                WHERE company_id = @CompanyId AND id <> @Id AND is_default_bank = 1;

            COMMIT TRAN;
            SELECT @Id AS id, 'Success' AS status;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END

    IF @Action = 'DELETE'
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM dbo.Ledgers WHERE id = @Id AND company_id = @CompanyId)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Ledger not found.' AS error;
            RETURN;
        END

        BEGIN TRY
            BEGIN TRAN;
            DELETE FROM dbo.Ledgers WHERE id = @Id AND company_id = @CompanyId;
            COMMIT TRAN;
            SELECT @Id AS id, 'Success' AS status;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            DECLARE @ErrName NVARCHAR(150) = (SELECT name FROM dbo.Ledgers WHERE id = @Id);
            IF ERROR_NUMBER() = 547  -- FK constraint violation (PROTECT equivalent)
                SELECT NULL AS id, 'Error' AS status, '"' + ISNULL(@ErrName, '') + '" is used by one or more tickets and can''t be deleted.' AS error;
            ELSE
                SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END
END
GO

-- ==========================================================================
-- Function : dbo.fn_CompanyFinancialYear(@CompanyId)
-- The company's current financial year (one row: fy_start, fy_end) - the top
-- bar's FY badge, and the range a voucher's date must fall in.
--   Year      = the one the company's LAST ENTRY (ticket JVs + manual
--               vouchers) falls in; today when nothing is posted yet.
--   Starts in = Company Master Financial Year From's month; none set ->
--               India (or blank country) April, anything else January.
-- ==========================================================================
CREATE OR ALTER FUNCTION dbo.fn_CompanyFinancialYear (@CompanyId INT)
RETURNS TABLE
AS
RETURN
    WITH b AS (
        SELECT ISNULL((SELECT MAX(d) FROM (
                    SELECT MAX(jv.voucher_date) AS d FROM dbo.JournalVoucher jv WHERE jv.company_id = cm.id
                    UNION ALL
                    SELECT MAX(v.voucher_date) FROM dbo.Vouchers v WHERE v.company_id = cm.id) x),
                   CAST(GETDATE() AS DATE)) AS last_entry,
               CASE WHEN cm.financial_year_from IS NOT NULL THEN MONTH(cm.financial_year_from)
                    WHEN LOWER(LTRIM(RTRIM(ISNULL(cm.country, '')))) IN ('', 'india', 'in', 'bharat') THEN 4
                    ELSE 1 END AS start_month
        FROM dbo.CompanyMaster cm
        WHERE cm.id = @CompanyId
    ), s AS (
        SELECT last_entry, DATEFROMPARTS(YEAR(last_entry) - CASE WHEN MONTH(last_entry) < start_month THEN 1 ELSE 0 END, start_month, 1) AS fy_start
        FROM b
    )
    SELECT last_entry, fy_start, DATEADD(DAY, -1, DATEADD(YEAR, 1, fy_start)) AS fy_end FROM s;
GO

-- ==========================================================================
-- dbo.sp_CompanyMaster
-- Module   : CompanyMaster (one row per company/branch - also the
--            company_id every other table scopes its data by)
-- Actions  : LIST, GET_BY_ID, SAVE (upsert - may insert with an explicit
--            caller-supplied id), DELETE
-- Replaces : views.company_master_list / company_master_save /
--            company_master_delete's ORM code
-- ==========================================================================
CREATE OR ALTER PROCEDURE dbo.sp_CompanyMaster
    @Action                 NVARCHAR(50),
    @Id                     INT             = NULL,
    @CompanyName            NVARCHAR(200)   = NULL,
    @MailingName            NVARCHAR(200)   = NULL,
    @Address                NVARCHAR(MAX)   = NULL,
    @Country                NVARCHAR(100)   = NULL,
    @State                  NVARCHAR(100)   = NULL,
    @Pincode                NVARCHAR(6)     = NULL,
    @Telephone              NVARCHAR(20)    = NULL,
    @Mobile                 NVARCHAR(10)    = NULL,
    @Email                  NVARCHAR(200)   = NULL,
    @FinancialYearFrom      DATE            = NULL,
    @BooksBeginningFrom     DATE            = NULL,
    @GstRegType             NVARCHAR(20)    = NULL,
    @GstNo                  NVARCHAR(15)    = NULL,
    @PanNumber              NVARCHAR(10)    = NULL,
    @CinNumber              NVARCHAR(25)    = NULL,
    @TanNumber              NVARCHAR(15)    = NULL,
    @HsnSac                 NVARCHAR(20)    = NULL,
    @CurrencySymbol         NVARCHAR(5)     = NULL,
    @CurrencyName           NVARCHAR(50)    = NULL,
    @DecimalPlaces          SMALLINT        = NULL,
    @LogoBase64             NVARCHAR(MAX)   = NULL,
    @SealBase64             NVARCHAR(MAX)   = NULL,
    -- LIST only: which images to return - NULL = none (fast), 'logo', 'all'.
    @Images                 NVARCHAR(10)    = NULL,
    -- SET_INVOICE_TEMPLATE only: 'classic', 'payment' or 'proforma'.
    @InvoiceTemplate        NVARCHAR(20)    = NULL,
    @TermsConditions        NVARCHAR(MAX)   = NULL,
    @BankAccountHolder      NVARCHAR(100)   = NULL,
    @BankAccountNo          NVARCHAR(30)   = NULL,
    @BankIfsc               NVARCHAR(15)   = NULL,
    @BankSwift              NVARCHAR(15)   = NULL,
    @BankName               NVARCHAR(100)   = NULL,
    @BankBranch             NVARCHAR(100)   = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'LIST'
    BEGIN
        -- The logo/seal can be MBs of base64 - only sent when asked for.
        SELECT id, company_name, mailing_name, address, country, state, pincode, telephone, mobile, email,
               financial_year_from, books_beginning_from, gst_reg_type, gst_no, cin_number, tan_number, hsn_sac,
               created_at, updated_at, pan_number, currency_name, currency_symbol, decimal_places, invoice_template, terms_conditions,
               bank_account_holder, bank_account_no, bank_ifsc, bank_swift, bank_name, bank_branch,
               CASE WHEN @Images IN ('logo', 'all') THEN logo_base64 END AS logo_base64,
               CASE WHEN @Images = 'all' THEN seal_base64 END AS seal_base64,
               -- The company's current financial year (top bar's FY badge,
               -- voucher date range) - see dbo.fn_CompanyFinancialYear.
               fy.last_entry AS last_entry_date, fy.fy_start, fy.fy_end
        FROM dbo.CompanyMaster cm
        OUTER APPLY dbo.fn_CompanyFinancialYear(cm.id) fy
        WHERE @Id IS NULL OR id = @Id
        ORDER BY company_name;
        RETURN;
    END

    -- Company Master > Choose Invoice Template - the print layout for every
    -- Tax Invoice / Credit Note this company prints.
    IF @Action = 'SET_INVOICE_TEMPLATE'
    BEGIN
        IF @InvoiceTemplate NOT IN ('classic', 'payment', 'proforma')
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Unknown invoice template.' AS error;
            RETURN;
        END
        IF NOT EXISTS (SELECT 1 FROM dbo.CompanyMaster WHERE id = @Id)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Save the Company Master details first.' AS error;
            RETURN;
        END
        BEGIN TRY
            BEGIN TRAN;
            UPDATE dbo.CompanyMaster SET invoice_template = @InvoiceTemplate, updated_at = SYSUTCDATETIME() WHERE id = @Id;
            COMMIT TRAN;
            SELECT @Id AS id, @InvoiceTemplate AS invoice_template, 'Success' AS status;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END

    IF @Action = 'SAVE'
    BEGIN
        IF @CompanyName IS NULL OR LTRIM(RTRIM(@CompanyName)) = ''
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'company_name is required' AS error;
            RETURN;
        END

        IF EXISTS (SELECT 1 FROM dbo.CompanyMaster WHERE company_name = @CompanyName AND (@Id IS NULL OR id <> @Id))
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Company "' + @CompanyName + '" already exists.' AS error;
            RETURN;
        END

        SET @Country = ISNULL(NULLIF(@Country, ''), 'India');
        SET @GstRegType = ISNULL(NULLIF(@GstRegType, ''), 'Regular');
        SET @DecimalPlaces = ISNULL(@DecimalPlaces, 2);

        BEGIN TRY
            BEGIN TRAN;

            DECLARE @ResultId INT;
            DECLARE @WasCreated BIT = 0;

            IF @Id IS NOT NULL AND EXISTS (SELECT 1 FROM dbo.CompanyMaster WHERE id = @Id)
            BEGIN
                UPDATE dbo.CompanyMaster
                SET company_name = @CompanyName, mailing_name = @MailingName, address = @Address,
                    country = @Country, state = @State, pincode = @Pincode, telephone = @Telephone,
                    mobile = @Mobile, email = @Email, financial_year_from = @FinancialYearFrom,
                    books_beginning_from = @BooksBeginningFrom, gst_reg_type = @GstRegType, gst_no = @GstNo,
                    pan_number = @PanNumber, cin_number = @CinNumber, tan_number = @TanNumber, hsn_sac = @HsnSac,
                    currency_symbol = @CurrencySymbol, currency_name = @CurrencyName, decimal_places = @DecimalPlaces,
                    logo_base64 = @LogoBase64, seal_base64 = @SealBase64, terms_conditions = @TermsConditions,
                    bank_account_holder = @BankAccountHolder, bank_account_no = @BankAccountNo, bank_ifsc = @BankIfsc, bank_swift = @BankSwift, bank_name = @BankName, bank_branch = @BankBranch,
                    updated_at = SYSUTCDATETIME()
                WHERE id = @Id;
                SET @ResultId = @Id;
            END
            ELSE IF @Id IS NOT NULL
            BEGIN
                -- Caller supplied an id that doesn't exist yet - insert with
                -- that exact id (this table IS the company_id every other
                -- table scopes by, so the page always passes a specific id).
                SET IDENTITY_INSERT dbo.CompanyMaster ON;
                INSERT INTO dbo.CompanyMaster
                    (id, company_name, mailing_name, address, country, state, pincode, telephone, mobile, email,
                     financial_year_from, books_beginning_from, gst_reg_type, gst_no, pan_number, cin_number,
                     tan_number, hsn_sac, currency_symbol, currency_name, decimal_places, logo_base64, seal_base64,
                     terms_conditions, bank_account_holder, bank_account_no, bank_ifsc, bank_swift, bank_name, bank_branch, created_at, updated_at)
                VALUES
                    (@Id, @CompanyName, @MailingName, @Address, @Country, @State, @Pincode, @Telephone, @Mobile, @Email,
                     @FinancialYearFrom, @BooksBeginningFrom, @GstRegType, @GstNo, @PanNumber, @CinNumber,
                     @TanNumber, @HsnSac, @CurrencySymbol, @CurrencyName, @DecimalPlaces, @LogoBase64, @SealBase64,
                     @TermsConditions, @BankAccountHolder, @BankAccountNo, @BankIfsc, @BankSwift, @BankName, @BankBranch, SYSUTCDATETIME(), SYSUTCDATETIME());
                SET IDENTITY_INSERT dbo.CompanyMaster OFF;
                SET @ResultId = @Id;
                SET @WasCreated = 1;
            END
            ELSE
            BEGIN
                INSERT INTO dbo.CompanyMaster
                    (company_name, mailing_name, address, country, state, pincode, telephone, mobile, email,
                     financial_year_from, books_beginning_from, gst_reg_type, gst_no, pan_number, cin_number,
                     tan_number, hsn_sac, currency_symbol, currency_name, decimal_places, logo_base64, seal_base64,
                     terms_conditions, bank_account_holder, bank_account_no, bank_ifsc, bank_swift, bank_name, bank_branch, created_at, updated_at)
                VALUES
                    (@CompanyName, @MailingName, @Address, @Country, @State, @Pincode, @Telephone, @Mobile, @Email,
                     @FinancialYearFrom, @BooksBeginningFrom, @GstRegType, @GstNo, @PanNumber, @CinNumber,
                     @TanNumber, @HsnSac, @CurrencySymbol, @CurrencyName, @DecimalPlaces, @LogoBase64, @SealBase64,
                     @TermsConditions, @BankAccountHolder, @BankAccountNo, @BankIfsc, @BankSwift, @BankName, @BankBranch, SYSUTCDATETIME(), SYSUTCDATETIME());
                SET @ResultId = SCOPE_IDENTITY();
                SET @WasCreated = 1;
            END

            COMMIT TRAN;

            SELECT *, @WasCreated AS was_created, 'Success' AS status
            FROM dbo.CompanyMaster WHERE id = @ResultId;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            IF XACT_STATE() <> 0 SET IDENTITY_INSERT dbo.CompanyMaster OFF;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END

    IF @Action = 'DELETE'
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM dbo.CompanyMaster WHERE id = @Id)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Company not found.' AS error;
            RETURN;
        END

        BEGIN TRY
            BEGIN TRAN;
            DELETE FROM dbo.CompanyMaster WHERE id = @Id;
            COMMIT TRAN;
            SELECT @Id AS id, 'Success' AS status;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END
END
GO

-- ==========================================================================
-- dbo.sp_VoucherType
-- Module   : VoucherType (Masters > Voucher Type)
-- Actions  : LIST, SAVE (upsert by id), DELETE
-- Replaces : views.voucher_type_list / voucher_type_save /
--            voucher_type_delete's ORM code
-- ==========================================================================
CREATE OR ALTER PROCEDURE dbo.sp_VoucherType
    @Action                      NVARCHAR(50),
    @Id                          INT            = NULL,
    @CompanyId                   INT            = NULL,
    @Name                        NVARCHAR(100)  = NULL,
    @AliasName                   NVARCHAR(100)  = NULL,
    @VoucherCategory             NVARCHAR(20)   = NULL,
    @IsActive                    BIT            = NULL,
    @NumberMethod                NVARCHAR(30)   = NULL,
    @NumberingBehaviour          NVARCHAR(30)   = NULL,   -- Automatic only: Restart Numbers / Keep Original Numbers
    @AllowAdditionalNumbering    BIT            = NULL,
    @AllowEffectiveDates         BIT            = NULL,
    @AllowNarration              BIT            = NULL,
    @AnWidthOfInvoiceNumber      INT            = NULL,
    @AnPrefillWithZero           BIT            = NULL,
    @AnRestartApplicableFrom     DATE           = NULL,
    @AnRestartStartingNumber     INT            = NULL,
    @AnRestartPeriod             NVARCHAR(10)   = NULL,
    @AnPrefixDetails             NVARCHAR(20)   = NULL,
    @AnSuffixDetails             NVARCHAR(20)   = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'LIST'
    BEGIN
        IF @Id IS NOT NULL
            SELECT * FROM dbo.VoucherType WHERE id = @Id AND company_id = @CompanyId;
        ELSE
            SELECT * FROM dbo.VoucherType WHERE company_id = @CompanyId ORDER BY name;
        RETURN;
    END

    IF @Action = 'GET_BY_NAME'
    BEGIN
        -- views.voucher_type_next_number's lookup.
        SELECT * FROM dbo.VoucherType WHERE company_id = @CompanyId AND name = @Name;
        RETURN;
    END

    IF @Action = 'SAVE'
    BEGIN
        IF @CompanyId IS NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'company_id is required' AS error;
            RETURN;
        END
        IF @Name IS NULL OR LTRIM(RTRIM(@Name)) = ''
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Voucher Name is required.' AS error;
            RETURN;
        END
        IF EXISTS (
            SELECT 1 FROM dbo.VoucherType
            WHERE company_id = @CompanyId AND name = @Name AND (@Id IS NULL OR id <> @Id)
        )
        BEGIN
            SELECT NULL AS id, 'Error' AS status, '"' + @Name + '" already exists - Voucher Name must be unique.' AS error;
            RETURN;
        END
        IF @Id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dbo.VoucherType WHERE id = @Id AND company_id = @CompanyId)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Voucher Type ' + CAST(@Id AS NVARCHAR(10)) + ' not found.' AS error;
            RETURN;
        END

        SET @VoucherCategory = ISNULL(@VoucherCategory, 'Airline');
        SET @IsActive = ISNULL(@IsActive, 1);
        SET @NumberMethod = ISNULL(@NumberMethod, 'Automatic');
        -- "Numbering" applies to Automatic only (default Keep Original Numbers).
        SET @NumberingBehaviour = CASE WHEN @NumberMethod = 'Automatic'
                                       THEN ISNULL(NULLIF(@NumberingBehaviour, ''), 'Keep Original Numbers') END;
        IF @NumberingBehaviour IS NOT NULL AND @NumberingBehaviour NOT IN ('Restart Numbers', 'Keep Original Numbers')
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Numbering must be Restart Numbers or Keep Original Numbers.' AS error;
            RETURN;
        END
        SET @AllowAdditionalNumbering = ISNULL(@AllowAdditionalNumbering, 0);
        SET @AllowEffectiveDates = ISNULL(@AllowEffectiveDates, 0);
        SET @AllowNarration = ISNULL(@AllowNarration, 1);
        SET @AnPrefillWithZero = ISNULL(@AnPrefillWithZero, 0);
        SET @AnRestartPeriod = ISNULL(@AnRestartPeriod, 'None');

        BEGIN TRY
            BEGIN TRAN;

            DECLARE @ResultId INT;
            DECLARE @WasCreated BIT = 0;
            DECLARE @Renumbered INT = 0;
            -- The name its vouchers were saved under (before a rename).
            DECLARE @OldName NVARCHAR(100) = (SELECT name FROM dbo.VoucherType WHERE id = @Id AND company_id = @CompanyId);

            IF @Id IS NOT NULL
            BEGIN
                UPDATE dbo.VoucherType
                SET name = @Name, alias_name = @AliasName, voucher_category = @VoucherCategory,
                    is_active = @IsActive, number_method = @NumberMethod, numbering_behaviour = @NumberingBehaviour,
                    allow_additional_numbering = @AllowAdditionalNumbering,
                    allow_effective_dates = @AllowEffectiveDates, allow_narration = @AllowNarration,
                    an_width_of_invoice_number = @AnWidthOfInvoiceNumber,
                    an_prefill_with_zero = @AnPrefillWithZero,
                    an_restart_applicable_from = @AnRestartApplicableFrom,
                    an_restart_starting_number = @AnRestartStartingNumber,
                    an_restart_period = @AnRestartPeriod,
                    an_prefix_details = @AnPrefixDetails, an_suffix_details = @AnSuffixDetails
                WHERE id = @Id AND company_id = @CompanyId;
                SET @ResultId = @Id;

                -- Renamed -> the Voucher-screen vouchers saved under the old name
                -- follow it (they stay linked to this type and its own series).
                IF @OldName IS NOT NULL AND @OldName <> @Name
                    UPDATE dbo.Vouchers SET voucher_type_name = @Name, updated_at = SYSUTCDATETIME()
                    WHERE company_id = @CompanyId AND category = 'MANUAL' AND voucher_type_name = @OldName;

                -- Automatic + "Restart Numbers": renumber this type's existing
                -- Voucher-screen vouchers 1, 2, 3 ... in voucher-date order (ties
                -- by entry order), within its own series (plain numbers, no
                -- prefix). "Keep Original Numbers" / Manual / Override leave old
                -- numbers alone. Ticket invoice numbers are never touched. Two
                -- passes so the series' unique key never sees a duplicate mid-update.
                IF @NumberMethod = 'Automatic' AND @NumberingBehaviour = 'Restart Numbers'
                BEGIN
                    DECLARE @ToRenumber TABLE (id INT PRIMARY KEY, new_no NVARCHAR(30));
                    INSERT INTO @ToRenumber (id, new_no)
                    SELECT v.id,
                           CAST(ROW_NUMBER() OVER (PARTITION BY v.voucher_type ORDER BY v.voucher_date, v.id) AS NVARCHAR(10))
                    FROM dbo.Vouchers v
                    WHERE v.company_id = @CompanyId AND v.category = 'MANUAL' AND v.voucher_type_name = @Name;

                    UPDATE v SET voucher_no = 'TMPRN-' + CAST(v.id AS NVARCHAR(10))
                    FROM dbo.Vouchers v INNER JOIN @ToRenumber r ON r.id = v.id
                    WHERE v.voucher_no <> r.new_no;
                    SET @Renumbered = @@ROWCOUNT;

                    UPDATE v SET voucher_no = r.new_no, updated_at = SYSUTCDATETIME()
                    FROM dbo.Vouchers v INNER JOIN @ToRenumber r ON r.id = v.id
                    WHERE v.voucher_no LIKE 'TMPRN-%';
                END
            END
            ELSE
            BEGIN
                INSERT INTO dbo.VoucherType
                    (company_id, name, alias_name, voucher_category, is_active, number_method, numbering_behaviour,
                     allow_additional_numbering, allow_effective_dates, allow_narration,
                     an_width_of_invoice_number, an_prefill_with_zero, an_restart_applicable_from,
                     an_restart_starting_number, an_restart_period, an_prefix_details, an_suffix_details)
                VALUES
                    (@CompanyId, @Name, @AliasName, @VoucherCategory, @IsActive, @NumberMethod, @NumberingBehaviour,
                     @AllowAdditionalNumbering, @AllowEffectiveDates, @AllowNarration,
                     @AnWidthOfInvoiceNumber, @AnPrefillWithZero, @AnRestartApplicableFrom,
                     @AnRestartStartingNumber, @AnRestartPeriod, @AnPrefixDetails, @AnSuffixDetails);
                SET @ResultId = SCOPE_IDENTITY();
                SET @WasCreated = 1;
            END

            COMMIT TRAN;
            SELECT *, @WasCreated AS was_created, @Renumbered AS renumbered, 'Success' AS status FROM dbo.VoucherType WHERE id = @ResultId;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END

    IF @Action = 'DELETE'
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM dbo.VoucherType WHERE id = @Id AND company_id = @CompanyId)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Voucher Type not found.' AS error;
            RETURN;
        END

        BEGIN TRY
            BEGIN TRAN;
            DELETE FROM dbo.VoucherType WHERE id = @Id AND company_id = @CompanyId;
            COMMIT TRAN;
            SELECT @Id AS id, 'Success' AS status;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END
END
GO

-- ==========================================================================
-- dbo.sp_FOPMaster
-- Module   : FOPMaster (Masters > FOP Master - Own/Client Card registry)
-- Actions  : LIST, SAVE (upsert by id, or by (company_id,card_number)),
--            DELETE
-- Replaces : views.fop_master_list / fop_master_save /
--            fop_master_delete's ORM code
-- ==========================================================================
CREATE OR ALTER PROCEDURE dbo.sp_FOPMaster
    @Action                  NVARCHAR(50),
    @Id                      INT            = NULL,
    @CompanyId               INT            = NULL,
    @CardType                NVARCHAR(20)   = NULL,
    @CardNumber              NVARCHAR(40)   = NULL,
    @BankName                NVARCHAR(100)  = NULL,
    @CardMasterLedgerId      INT            = NULL,
    @IsActive                BIT            = NULL,
    -- SAVE (Own Card): the date the Card Master ledger applies from.
    @EffectiveFrom           DATE           = NULL,
    -- LIST / GET_BY_CARD_NUMBER: return the Card Master ledger IN FORCE on
    -- this date (a document's own date) instead of the latest one.
    @AsOfDate                DATE           = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'LIST'
    BEGIN
        -- With @AsOfDate: each card's Card Master ledger in force on that
        -- date (Effective From history, same rule as Ledger Mapping).
        SELECT f.id, f.card_type, f.card_number, f.bank_name,
               CASE WHEN @AsOfDate IS NOT NULL AND eff.card_master_ledger_id IS NOT NULL THEN eff.card_master_ledger_id ELSE f.card_master_ledger_id END AS card_master_ledger_id,
               CASE WHEN @AsOfDate IS NOT NULL AND eff.card_master_ledger_id IS NOT NULL THEN eff.card_master_ledger_name ELSE f.card_master_ledger_name END AS card_master_ledger_name,
               f.effective_from, f.is_active
        FROM dbo.FOPMaster f
        OUTER APPLY (
            SELECT TOP 1 h.card_master_ledger_id, h.card_master_ledger_name, h.effective_from
            FROM dbo.FOPMasterHistory h
            WHERE h.fop_master_id = f.id
            ORDER BY CASE WHEN h.effective_from <= @AsOfDate THEN 0 ELSE 1 END,
                     CASE WHEN h.effective_from <= @AsOfDate THEN h.effective_from END DESC,
                     h.effective_from ASC
        ) eff
        WHERE f.company_id = @CompanyId AND (@CardType IS NULL OR f.card_type = @CardType)
        ORDER BY f.card_type, f.card_number;
        RETURN;
    END

    IF @Action = 'GET_BY_CARD_NUMBER'
    BEGIN
        -- views._fop_payment_lines / _reschedule_fop_payment_lines's "Own
        -- Card -> that card's own GL ledger" lookup.
        -- With @AsOfDate (the document's own date): the ledger in force then.
        SELECT f.id,
               CASE WHEN @AsOfDate IS NOT NULL AND eff.card_master_ledger_id IS NOT NULL THEN eff.card_master_ledger_id ELSE f.card_master_ledger_id END AS card_master_ledger_id,
               CASE WHEN @AsOfDate IS NOT NULL AND eff.card_master_ledger_id IS NOT NULL THEN eff.card_master_ledger_name ELSE f.card_master_ledger_name END AS card_master_ledger_name
        FROM dbo.FOPMaster f
        OUTER APPLY (
            SELECT TOP 1 h.card_master_ledger_id, h.card_master_ledger_name, h.effective_from
            FROM dbo.FOPMasterHistory h
            WHERE h.fop_master_id = f.id
            ORDER BY CASE WHEN h.effective_from <= @AsOfDate THEN 0 ELSE 1 END,
                     CASE WHEN h.effective_from <= @AsOfDate THEN h.effective_from END DESC,
                     h.effective_from ASC
        ) eff
        WHERE f.company_id = @CompanyId AND f.card_number = @CardNumber;
        RETURN;
    END

    IF @Action = 'SAVE'
    BEGIN
        IF @CompanyId IS NULL OR @CardType IS NULL OR @CardNumber IS NULL OR LTRIM(RTRIM(@CardNumber)) = ''
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'company_id, card_type and card_number are required' AS error;
            RETURN;
        END
        IF @CardType = 'Own Card' AND @CardMasterLedgerId IS NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'card_master_ledger_id is required for Own Card' AS error;
            RETURN;
        END
        -- Same rule as Ledger Mapping: an Own Card's ledger needs its Effective From date.
        IF @CardType = 'Own Card' AND @EffectiveFrom IS NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Effective From date is required for the Card Master ledger.' AS error;
            RETURN;
        END

        DECLARE @LedgerName NVARCHAR(200) = NULL;
        IF @CardMasterLedgerId IS NOT NULL
        BEGIN
            SELECT @LedgerName = COALESCE(NULLIF(alias_name, ''), name) FROM dbo.Ledgers
            WHERE id = @CardMasterLedgerId AND company_id = @CompanyId;
            IF @LedgerName IS NULL
            BEGIN
                SELECT NULL AS id, 'Error' AS status,
                       'Ledger ' + CAST(@CardMasterLedgerId AS NVARCHAR(10)) + ' not found.' AS error;
                RETURN;
            END
        END

        IF EXISTS (
            SELECT 1 FROM dbo.FOPMaster
            WHERE company_id = @CompanyId AND card_number = @CardNumber AND (@Id IS NULL OR id <> @Id)
        )
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Card Number "' + @CardNumber + '" is already used.' AS error;
            RETURN;
        END
        IF @Id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dbo.FOPMaster WHERE id = @Id AND company_id = @CompanyId)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Card ' + CAST(@Id AS NVARCHAR(10)) + ' not found.' AS error;
            RETURN;
        END

        SET @IsActive = ISNULL(@IsActive, 1);

        BEGIN TRY
            BEGIN TRAN;

            DECLARE @ResultId INT;
            IF @Id IS NOT NULL
            BEGIN
                UPDATE dbo.FOPMaster
                SET card_type = @CardType, card_number = @CardNumber, bank_name = @BankName,
                    card_master_ledger_id = @CardMasterLedgerId, card_master_ledger_name = @LedgerName,
                    is_active = @IsActive
                WHERE id = @Id AND company_id = @CompanyId;
                SET @ResultId = @Id;
            END
            ELSE IF EXISTS (SELECT 1 FROM dbo.FOPMaster WHERE company_id = @CompanyId AND card_number = @CardNumber)
            BEGIN
                UPDATE dbo.FOPMaster
                SET card_type = @CardType, bank_name = @BankName,
                    card_master_ledger_id = @CardMasterLedgerId, card_master_ledger_name = @LedgerName,
                    is_active = @IsActive
                WHERE company_id = @CompanyId AND card_number = @CardNumber;
                SELECT @ResultId = id FROM dbo.FOPMaster WHERE company_id = @CompanyId AND card_number = @CardNumber;
            END
            ELSE
            BEGIN
                INSERT INTO dbo.FOPMaster
                    (company_id, card_type, card_number, bank_name, card_master_ledger_id, card_master_ledger_name, is_active)
                VALUES
                    (@CompanyId, @CardType, @CardNumber, @BankName, @CardMasterLedgerId, @LedgerName, @IsActive);
                SET @ResultId = SCOPE_IDENTITY();
            END

            -- Effective-date history (Own Card) - same rules as Ledger Mapping:
            -- the same date again corrects that entry, a new date adds one
            -- (older dates stay, so earlier documents keep their own ledger),
            -- and the card row always holds the LATEST entry.
            IF @CardType = 'Own Card' AND @CardMasterLedgerId IS NOT NULL
            BEGIN
                IF EXISTS (SELECT 1 FROM dbo.FOPMasterHistory WHERE fop_master_id = @ResultId AND effective_from = @EffectiveFrom)
                    UPDATE dbo.FOPMasterHistory
                    SET card_master_ledger_id = @CardMasterLedgerId, card_master_ledger_name = @LedgerName, updated_at = SYSUTCDATETIME()
                    WHERE fop_master_id = @ResultId AND effective_from = @EffectiveFrom;
                ELSE
                    INSERT INTO dbo.FOPMasterHistory
                        (company_id, fop_master_id, card_master_ledger_id, card_master_ledger_name, effective_from, created_at, updated_at)
                    VALUES (@CompanyId, @ResultId, @CardMasterLedgerId, @LedgerName, @EffectiveFrom, SYSUTCDATETIME(), SYSUTCDATETIME());
                UPDATE f
                SET card_master_ledger_id = h.card_master_ledger_id, card_master_ledger_name = h.card_master_ledger_name,
                    effective_from = h.effective_from
                FROM dbo.FOPMaster f
                CROSS APPLY (SELECT TOP 1 card_master_ledger_id, card_master_ledger_name, effective_from
                             FROM dbo.FOPMasterHistory WHERE fop_master_id = f.id ORDER BY effective_from DESC) h
                WHERE f.id = @ResultId;
            END

            COMMIT TRAN;
            SELECT id, card_type, card_number, bank_name, card_master_ledger_id, card_master_ledger_name,
                   effective_from, is_active, 'Success' AS status
            FROM dbo.FOPMaster WHERE id = @ResultId;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END

    IF @Action = 'DELETE'
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM dbo.FOPMaster WHERE id = @Id AND company_id = @CompanyId)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Card not found.' AS error;
            RETURN;
        END

        BEGIN TRY
            BEGIN TRAN;
            DELETE FROM dbo.FOPMasterHistory WHERE fop_master_id = @Id;
            DELETE FROM dbo.FOPMaster WHERE id = @Id AND company_id = @CompanyId;
            COMMIT TRAN;
            SELECT @Id AS id, 'Success' AS status;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END
END
GO

-- ==========================================================================
-- dbo.sp_PGMaster
-- Module   : PGMaster + PGMasterHistory (Masters > PG Master - Payment
--            Gateway registry with dated rate/ledger-mapping snapshots)
-- Actions  : LIST, SAVE (upsert + atomic history snapshot), DELETE,
--            HISTORY_LIST, EFFECTIVE_SNAPSHOT
-- Replaces : views.pg_master_list / pg_master_save / pg_master_delete /
--            _snapshot_pg_master_history / pg_master_history_list /
--            _pg_master_effective_snapshot's ORM code
-- ==========================================================================
CREATE OR ALTER PROCEDURE dbo.sp_PGMaster
    @Action                              NVARCHAR(50),
    @Id                                  INT            = NULL,
    @CompanyId                           INT            = NULL,
    @GatewayName                         NVARCHAR(100)  = NULL,
    @PaymentMasterLedgerId               INT            = NULL,
    @PgChargesMasterLedgerId             INT            = NULL,
    @PgChargesPercentage                 DECIMAL(5,2)   = NULL,
    @PgChargesPercentageEffectiveFrom    DATE           = NULL,
    @IsActive                            BIT            = NULL,
    @AsOfDate                            DATE           = NULL,
    @DocType                             NVARCHAR(20)   = NULL,   -- EFFECTIVE_SNAPSHOT: the document asking
    @DocId                               INT            = NULL    --   (its PGMasterPin wins - "Retain old ledgers")
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'LIST'
    BEGIN
        SELECT p.id, p.gateway_name,
               p.payment_master_ledger_id, p.payment_master_ledger_name,
               p.pg_charges_master_ledger_id, p.pg_charges_master_ledger_name,
               ISNULL(l.gst_percentage, 0) AS pg_charges_master_ledger_gst_percentage,
               p.pg_charges_percentage, p.pg_charges_percentage_effective_from, p.is_active
        FROM dbo.PGMaster p
        LEFT JOIN dbo.Ledgers l ON l.id = p.pg_charges_master_ledger_id
        WHERE p.company_id = @CompanyId
        ORDER BY p.gateway_name;
        RETURN;
    END

    IF @Action = 'HISTORY_LIST'
    BEGIN
        SELECT id, effective_from, payment_master_ledger_name, pg_charges_master_ledger_name, pg_charges_percentage
        FROM dbo.PGMasterHistory
        WHERE pg_master_id = @Id AND company_id = @CompanyId
        ORDER BY effective_from DESC;
        RETURN;
    END

    IF @Action = 'EFFECTIVE_SNAPSHOT'
    BEGIN
        DECLARE @GwId INT;
        SELECT @GwId = id FROM dbo.PGMaster WHERE company_id = @CompanyId AND gateway_name = @GatewayName;
        IF @GwId IS NULL
        BEGIN
            SELECT NULL AS payment_master_ledger_id, 'Error' AS status, 'Payment Gateway not found.' AS error;
            RETURN;
        END

        -- A saved document kept on its old PG settings by a back-dated change
        -- ("Retain old ledgers" - dbo.PGMasterPin).
        IF @DocId IS NOT NULL AND EXISTS (SELECT 1 FROM dbo.PGMasterPin
                                          WHERE company_id = @CompanyId AND doc_type = @DocType AND doc_id = @DocId
                                            AND gateway_name = @GatewayName)
        BEGIN
            SELECT pin.payment_master_ledger_id, pin.payment_master_ledger_name,
                   pin.pg_charges_master_ledger_id, pin.pg_charges_master_ledger_name,
                   ISNULL((SELECT gst_percentage FROM dbo.Ledgers WHERE id = pin.pg_charges_master_ledger_id), 0) AS pg_charges_master_ledger_gst_percentage,
                   ISNULL(pin.pg_charges_percentage, 0) AS pg_charges_percentage,
                   pin.effective_from, CAST(1 AS BIT) AS pinned, 'Success' AS status
            FROM dbo.PGMasterPin pin
            WHERE pin.company_id = @CompanyId AND pin.doc_type = @DocType AND pin.doc_id = @DocId AND pin.gateway_name = @GatewayName;
            RETURN;
        END

        DECLARE @HistId INT;
        IF @AsOfDate IS NOT NULL
            SELECT TOP 1 @HistId = id FROM dbo.PGMasterHistory
            WHERE pg_master_id = @GwId AND effective_from <= @AsOfDate
            ORDER BY effective_from DESC;

        IF @HistId IS NOT NULL
            SELECT h.payment_master_ledger_id, h.payment_master_ledger_name,
                   h.pg_charges_master_ledger_id, h.pg_charges_master_ledger_name,
                   ISNULL((SELECT gst_percentage FROM dbo.Ledgers WHERE id = h.pg_charges_master_ledger_id), 0) AS pg_charges_master_ledger_gst_percentage,
                   ISNULL(h.pg_charges_percentage, 0) AS pg_charges_percentage,
                   h.effective_from, 'Success' AS status
            FROM dbo.PGMasterHistory h WHERE h.id = @HistId;
        ELSE
            SELECT p.payment_master_ledger_id, p.payment_master_ledger_name,
                   p.pg_charges_master_ledger_id, p.pg_charges_master_ledger_name,
                   ISNULL(l.gst_percentage, 0) AS pg_charges_master_ledger_gst_percentage,
                   ISNULL(p.pg_charges_percentage, 0) AS pg_charges_percentage,
                   CAST(NULL AS DATE) AS effective_from, 'Success' AS status
            FROM dbo.PGMaster p
            LEFT JOIN dbo.Ledgers l ON l.id = p.pg_charges_master_ledger_id
            WHERE p.id = @GwId;
        RETURN;
    END

    IF @Action = 'SAVE'
    BEGIN
        IF @CompanyId IS NULL OR @GatewayName IS NULL OR LTRIM(RTRIM(@GatewayName)) = '' OR @PaymentMasterLedgerId IS NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'company_id, gateway_name and payment_master_ledger_id are required' AS error;
            RETURN;
        END
        IF @PgChargesPercentage IS NOT NULL AND (@PgChargesPercentage < 0 OR @PgChargesPercentage > 100)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'PG Charges Percentage must be between 0 and 100.' AS error;
            RETURN;
        END

        DECLARE @PayLedgerName NVARCHAR(200), @ChargesLedgerName NVARCHAR(200);
        SELECT @PayLedgerName = COALESCE(NULLIF(alias_name, ''), name) FROM dbo.Ledgers WHERE id = @PaymentMasterLedgerId AND company_id = @CompanyId;
        IF @PayLedgerName IS NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Ledger ' + CAST(@PaymentMasterLedgerId AS NVARCHAR(10)) + ' not found.' AS error;
            RETURN;
        END
        IF @PgChargesMasterLedgerId IS NOT NULL
        BEGIN
            SELECT @ChargesLedgerName = COALESCE(NULLIF(alias_name, ''), name) FROM dbo.Ledgers WHERE id = @PgChargesMasterLedgerId AND company_id = @CompanyId;
            IF @ChargesLedgerName IS NULL
            BEGIN
                SELECT NULL AS id, 'Error' AS status, 'Ledger ' + CAST(@PgChargesMasterLedgerId AS NVARCHAR(10)) + ' not found.' AS error;
                RETURN;
            END
        END

        IF EXISTS (
            SELECT 1 FROM dbo.PGMaster
            WHERE company_id = @CompanyId AND gateway_name = @GatewayName AND (@Id IS NULL OR id <> @Id)
        )
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Payment Gateway Name "' + @GatewayName + '" is already used.' AS error;
            RETURN;
        END
        IF @Id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dbo.PGMaster WHERE id = @Id AND company_id = @CompanyId)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Payment Gateway ' + CAST(@Id AS NVARCHAR(10)) + ' not found.' AS error;
            RETURN;
        END

        SET @IsActive = ISNULL(@IsActive, 1);

        BEGIN TRY
            BEGIN TRAN;

            DECLARE @ResultId INT;
            IF @Id IS NOT NULL
            BEGIN
                UPDATE dbo.PGMaster
                SET gateway_name = @GatewayName,
                    payment_master_ledger_id = @PaymentMasterLedgerId, payment_master_ledger_name = @PayLedgerName,
                    pg_charges_master_ledger_id = @PgChargesMasterLedgerId, pg_charges_master_ledger_name = @ChargesLedgerName,
                    pg_charges_percentage = @PgChargesPercentage,
                    pg_charges_percentage_effective_from = @PgChargesPercentageEffectiveFrom,
                    is_active = @IsActive, updated_at = SYSUTCDATETIME()
                WHERE id = @Id AND company_id = @CompanyId;
                SET @ResultId = @Id;
            END
            ELSE
            BEGIN
                INSERT INTO dbo.PGMaster
                    (company_id, gateway_name, payment_master_ledger_id, payment_master_ledger_name,
                     pg_charges_master_ledger_id, pg_charges_master_ledger_name, pg_charges_percentage,
                     pg_charges_percentage_effective_from, is_active, created_at, updated_at)
                VALUES
                    (@CompanyId, @GatewayName, @PaymentMasterLedgerId, @PayLedgerName,
                     @PgChargesMasterLedgerId, @ChargesLedgerName, @PgChargesPercentage,
                     @PgChargesPercentageEffectiveFrom, @IsActive, SYSUTCDATETIME(), SYSUTCDATETIME());
                SET @ResultId = SCOPE_IDENTITY();
            END

            -- Every save with an Effective From date also snapshots into
            -- PGMasterHistory, keyed by (pg_master_id, effective_from) -
            -- see PGMasterHistory's model docstring for why.
            IF @PgChargesPercentageEffectiveFrom IS NOT NULL
            BEGIN
                IF EXISTS (SELECT 1 FROM dbo.PGMasterHistory WHERE pg_master_id = @ResultId AND effective_from = @PgChargesPercentageEffectiveFrom)
                    UPDATE dbo.PGMasterHistory
                    SET company_id = @CompanyId, gateway_name = @GatewayName,
                        payment_master_ledger_id = @PaymentMasterLedgerId, payment_master_ledger_name = @PayLedgerName,
                        pg_charges_master_ledger_id = @PgChargesMasterLedgerId, pg_charges_master_ledger_name = @ChargesLedgerName,
                        pg_charges_percentage = @PgChargesPercentage
                    WHERE pg_master_id = @ResultId AND effective_from = @PgChargesPercentageEffectiveFrom;
                ELSE
                    INSERT INTO dbo.PGMasterHistory
                        (pg_master_id, company_id, gateway_name, payment_master_ledger_id, payment_master_ledger_name,
                         pg_charges_master_ledger_id, pg_charges_master_ledger_name, pg_charges_percentage,
                         effective_from, created_at)
                    VALUES
                        (@ResultId, @CompanyId, @GatewayName, @PaymentMasterLedgerId, @PayLedgerName,
                         @PgChargesMasterLedgerId, @ChargesLedgerName, @PgChargesPercentage,
                         @PgChargesPercentageEffectiveFrom, SYSUTCDATETIME());
            END

            COMMIT TRAN;

            SELECT p.id, p.gateway_name,
                   p.payment_master_ledger_id, p.payment_master_ledger_name,
                   p.pg_charges_master_ledger_id, p.pg_charges_master_ledger_name,
                   ISNULL(l.gst_percentage, 0) AS pg_charges_master_ledger_gst_percentage,
                   p.pg_charges_percentage, p.pg_charges_percentage_effective_from, p.is_active,
                   'Success' AS status
            FROM dbo.PGMaster p
            LEFT JOIN dbo.Ledgers l ON l.id = p.pg_charges_master_ledger_id
            WHERE p.id = @ResultId;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END

    IF @Action = 'DELETE'
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM dbo.PGMaster WHERE id = @Id AND company_id = @CompanyId)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Payment Gateway not found.' AS error;
            RETURN;
        END

        BEGIN TRY
            BEGIN TRAN;
            -- PGMasterHistory has no ON DELETE CASCADE at the DB level
            -- (Django's on_delete=CASCADE was only ever enforced at the ORM
            -- layer) - delete its snapshots first, same net effect.
            DELETE FROM dbo.PGMasterHistory WHERE pg_master_id = @Id;
            DELETE FROM dbo.PGMaster WHERE id = @Id AND company_id = @CompanyId;
            COMMIT TRAN;
            SELECT @Id AS id, 'Success' AS status;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END
END
GO

-- ==========================================================================
-- dbo.sp_SupplierCommissionRule
-- Module   : SupplierCommissionRules (Supplier Master commission rule grid)
-- Actions  : LIST, SAVE (insert-only - no unique key on this table), DELETE
-- Replaces : views.supplier_commission_rules_list /
--            supplier_commission_rule_create /
--            supplier_commission_rule_delete's ORM code
-- ==========================================================================
CREATE OR ALTER PROCEDURE dbo.sp_SupplierCommissionRule
    @Action            NVARCHAR(50),
    @Id                INT            = NULL,
    @CompanyId         INT            = NULL,
    @OfficeId          NVARCHAR(30)   = NULL,
    @SupplierName      NVARCHAR(200)  = NULL,
    @TravelType        NVARCHAR(20)   = NULL,
    @AirlineCategory   NVARCHAR(10)   = NULL,
    @Cabin             NVARCHAR(30)   = NULL,
    @FareType          NVARCHAR(60)   = NULL,
    @CommOn            NVARCHAR(20)   = NULL,
    @CalcType          NVARCHAR(12)   = NULL,
    @CalcPct           DECIMAL(14,2)  = NULL,
    @FlatAmt           DECIMAL(14,2)  = NULL,
    @ValidUpto         DATE           = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'LIST'
    BEGIN
        SELECT id, rule_type AS type, office_id, supplier_name, travel_type, airline_category,
               cabin, fare_type, comm_on, calc_type, calc_pct, flat_amt, valid_upto
        FROM dbo.SupplierCommissionRules
        WHERE company_id = @CompanyId AND (@OfficeId IS NULL OR office_id = @OfficeId)
        ORDER BY id DESC;
        RETURN;
    END

    IF @Action = 'SAVE'
    BEGIN
        IF @CompanyId IS NULL OR @OfficeId IS NULL OR LTRIM(RTRIM(@OfficeId)) = ''
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'company_id and office_id are required' AS error;
            RETURN;
        END

        BEGIN TRY
            BEGIN TRAN;

            INSERT INTO dbo.SupplierCommissionRules
                (company_id, rule_type, office_id, supplier_name, travel_type, airline_category,
                 cabin, fare_type, comm_on, calc_type, calc_pct, flat_amt, valid_upto, created_at, updated_at)
            VALUES
                (@CompanyId, 'Commission', @OfficeId, @SupplierName, @TravelType, @AirlineCategory,
                 @Cabin, @FareType, @CommOn, @CalcType, ISNULL(@CalcPct, 0), ISNULL(@FlatAmt, 0), @ValidUpto,
                 SYSUTCDATETIME(), SYSUTCDATETIME());

            DECLARE @NewId INT = SCOPE_IDENTITY();
            COMMIT TRAN;

            SELECT id, rule_type AS type, office_id, supplier_name, travel_type, airline_category,
                   cabin, fare_type, comm_on, calc_type, calc_pct, flat_amt, valid_upto, 'Success' AS status
            FROM dbo.SupplierCommissionRules WHERE id = @NewId;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END

    IF @Action = 'DELETE'
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM dbo.SupplierCommissionRules WHERE id = @Id AND company_id = @CompanyId)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Rule not found.' AS error;
            RETURN;
        END

        BEGIN TRY
            BEGIN TRAN;
            DELETE FROM dbo.SupplierCommissionRules WHERE id = @Id AND company_id = @CompanyId;
            COMMIT TRAN;
            SELECT @Id AS id, 'Success' AS status;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END
END
GO

-- ==========================================================================
-- dbo.sp_MasterMapping
-- Module   : MasterMapping (Masters > Master Mapping - per-product-type
--            accounting field -> ledger mapping)
-- Actions  : LIST, SAVE_ROW (upsert one row by (company_id,product_type,
--            field_name) - the page saves a whole category's rows as a
--            batch of these calls), DELETE
-- Replaces : views.master_mapping_list / master_mapping_save (per-row
--            upsert loop) / master_mapping_delete's ORM code
-- ==========================================================================
CREATE OR ALTER PROCEDURE dbo.sp_MasterMapping
    @Action              NVARCHAR(50),
    @Id                  INT            = NULL,
    @CompanyId           INT            = NULL,
    @ProductType         NVARCHAR(20)   = NULL,
    @MastersCategory     NVARCHAR(40)   = NULL,
    @MastersCategoryId   SMALLINT       = NULL,
    @FieldName           NVARCHAR(60)   = NULL,
    @LedgerId            INT            = NULL,
    @EffectiveFrom       DATE           = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'LIST'
    BEGIN
        SELECT m.id, m.product_type, m.masters_category, m.masters_category_id, m.field_name,
               m.ledger_id, m.ledger_name, ISNULL(l.gst_percentage, 0) AS ledger_gst_percentage,
               m.effective_from
        FROM dbo.MasterMapping m
        LEFT JOIN dbo.Ledgers l ON l.id = m.ledger_id
        WHERE m.company_id = @CompanyId
          AND (@ProductType IS NULL OR m.product_type = @ProductType)
          AND (@MastersCategory IS NULL OR m.masters_category = @MastersCategory)
        ORDER BY m.product_type, m.masters_category, m.id;
        RETURN;
    END

    IF @Action = 'HISTORY_LIST'
    BEGIN
        -- Every dated mapping (oldest first per field) + its ledger's GST % -
        -- what a document resolves its ledger from, by its own date
        -- (models.resolve_mapping: latest effective_from <= document date).
        SELECT h.product_type, h.masters_category, h.field_name, h.ledger_id, h.ledger_name,
               ISNULL(l.gst_percentage, 0) AS ledger_gst_percentage, h.effective_from
        FROM dbo.MasterMappingHistory h
        LEFT JOIN dbo.Ledgers l ON l.id = h.ledger_id
        WHERE h.company_id = @CompanyId
          AND (@ProductType IS NULL OR h.product_type = @ProductType)
          AND (@FieldName IS NULL OR h.field_name = @FieldName)
        ORDER BY h.product_type, h.field_name, h.effective_from;
        RETURN;
    END

    IF @Action = 'SAVE_ROW'
    BEGIN
        IF @CompanyId IS NULL OR @ProductType IS NULL OR @MastersCategory IS NULL
           OR @FieldName IS NULL OR @LedgerId IS NULL OR @EffectiveFrom IS NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'company_id, product_type, masters_category, field_name, ledger_id and effective_from are required' AS error;
            RETURN;
        END

        DECLARE @LedgerName NVARCHAR(200);
        SELECT @LedgerName = COALESCE(NULLIF(alias_name, ''), name) FROM dbo.Ledgers
        WHERE id = @LedgerId AND company_id = @CompanyId;
        IF @LedgerName IS NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Ledger ' + CAST(@LedgerId AS NVARCHAR(10)) + ' not found.' AS error;
            RETURN;
        END

        BEGIN TRY
            BEGIN TRAN;

            -- Effective-date history: this date's mapping (a second save on the
            -- same date corrects it; a new date adds a row - older dates stay,
            -- so earlier documents keep posting to their own ledger).
            IF EXISTS (SELECT 1 FROM dbo.MasterMappingHistory WHERE company_id = @CompanyId AND product_type = @ProductType
                       AND field_name = @FieldName AND effective_from = @EffectiveFrom)
                UPDATE dbo.MasterMappingHistory
                SET masters_category = @MastersCategory, ledger_id = @LedgerId, ledger_name = @LedgerName, updated_at = SYSUTCDATETIME()
                WHERE company_id = @CompanyId AND product_type = @ProductType AND field_name = @FieldName AND effective_from = @EffectiveFrom;
            ELSE
                INSERT INTO dbo.MasterMappingHistory
                    (company_id, product_type, masters_category, field_name, ledger_id, ledger_name, effective_from, created_at, updated_at)
                VALUES (@CompanyId, @ProductType, @MastersCategory, @FieldName, @LedgerId, @LedgerName, @EffectiveFrom, SYSUTCDATETIME(), SYSUTCDATETIME());

            -- The live MasterMapping row always holds the LATEST-effective
            -- mapping (a back-dated entry only adds history).
            DECLARE @LiveLedgerId INT, @LiveLedgerName NVARCHAR(200), @LiveEffective DATE, @LiveCategory NVARCHAR(40);
            SELECT TOP 1 @LiveLedgerId = ledger_id, @LiveLedgerName = ledger_name, @LiveEffective = effective_from, @LiveCategory = masters_category
            FROM dbo.MasterMappingHistory
            WHERE company_id = @CompanyId AND product_type = @ProductType AND field_name = @FieldName
            ORDER BY effective_from DESC;

            DECLARE @ResultId INT;
            IF EXISTS (SELECT 1 FROM dbo.MasterMapping WHERE company_id = @CompanyId AND product_type = @ProductType AND field_name = @FieldName)
            BEGIN
                UPDATE dbo.MasterMapping
                SET masters_category = @LiveCategory, masters_category_id = ISNULL(@MastersCategoryId, 0),
                    ledger_id = @LiveLedgerId, ledger_name = @LiveLedgerName, effective_from = @LiveEffective,
                    updated_at = SYSUTCDATETIME()
                WHERE company_id = @CompanyId AND product_type = @ProductType AND field_name = @FieldName;
                SELECT @ResultId = id FROM dbo.MasterMapping WHERE company_id = @CompanyId AND product_type = @ProductType AND field_name = @FieldName;
            END
            ELSE
            BEGIN
                INSERT INTO dbo.MasterMapping
                    (company_id, product_type, masters_category, masters_category_id, field_name, ledger_id, ledger_name, effective_from, created_at, updated_at)
                VALUES
                    (@CompanyId, @ProductType, @LiveCategory, ISNULL(@MastersCategoryId, 0), @FieldName, @LiveLedgerId, @LiveLedgerName, @LiveEffective, SYSUTCDATETIME(), SYSUTCDATETIME());
                SET @ResultId = SCOPE_IDENTITY();
            END

            COMMIT TRAN;

            SELECT m.id, m.product_type, m.masters_category, m.masters_category_id, m.field_name,
                   m.ledger_id, m.ledger_name, ISNULL(l.gst_percentage, 0) AS ledger_gst_percentage,
                   m.effective_from, 'Success' AS status
            FROM dbo.MasterMapping m
            LEFT JOIN dbo.Ledgers l ON l.id = m.ledger_id
            WHERE m.id = @ResultId;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END

    IF @Action = 'DELETE'
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM dbo.MasterMapping WHERE id = @Id AND company_id = @CompanyId)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Mapping not found.' AS error;
            RETURN;
        END

        BEGIN TRY
            BEGIN TRAN;
            -- Its effective-date history goes with it (like PG Master's).
            DELETE h FROM dbo.MasterMappingHistory h
            INNER JOIN dbo.MasterMapping m ON m.company_id = h.company_id AND m.product_type = h.product_type AND m.field_name = h.field_name
            WHERE m.id = @Id AND m.company_id = @CompanyId;
            DELETE FROM dbo.MasterMapping WHERE id = @Id AND company_id = @CompanyId;
            COMMIT TRAN;
            SELECT @Id AS id, 'Success' AS status;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END
END
GO

-- ==========================================================================
-- Function : dbo.fn_TicketChainLock(@CompanyId, @TicketId, @RescheduleId)
-- Whether a Booking (@TicketId) or a Reschedule (@RescheduleId) is locked
-- for editing because a later process in its chain is already built on it.
-- One row: locked (BIT) + message (NULL when free to edit).
--   Booking    - any Reschedule, Cancellation or SSR Updation of it.
--   Reschedule - a later Reschedule built on its passengers, an SSR
--                Updation sold on it, or a Cancellation of its booking.
-- Used by sp_Ticket / sp_RescheduleTicket SAVE (blocks the save) and the
-- ticket screen (Edit is refused up front with the same message).
-- ==========================================================================
CREATE OR ALTER FUNCTION dbo.fn_TicketChainLock (@CompanyId INT, @TicketId INT, @RescheduleId INT)
RETURNS TABLE
AS
RETURN
    WITH chain AS (
        -- Booking's own chain
        SELECT 'Reschedule' AS kind, r.invoice_number FROM dbo.Rescheduled_Al_Ticket r
        WHERE @TicketId IS NOT NULL AND r.company_id = @CompanyId AND r.original_ticket_id = @TicketId
        UNION ALL
        SELECT 'Cancellation', c.invoice_number FROM dbo.Cancellation_AL_Tickets c
        WHERE @TicketId IS NOT NULL AND c.company_id = @CompanyId AND c.original_ticket_id = @TicketId
        UNION ALL
        SELECT 'SSR Updation', s.invoice_number FROM dbo.SSR_AL_Tickets s
        WHERE @TicketId IS NOT NULL AND s.company_id = @CompanyId AND s.original_ticket_id = @TicketId
        UNION ALL
        -- Reschedule's own chain
        SELECT DISTINCT 'Reschedule', r2.invoice_number
        FROM dbo.Rescheduled_Al_TicketLines l2
        INNER JOIN dbo.Rescheduled_Al_Ticket r2 ON r2.id = l2.reschedule_ticket_id
        WHERE @RescheduleId IS NOT NULL AND r2.id <> @RescheduleId
          AND l2.based_on_reschedule_line_id IN (SELECT id FROM dbo.Rescheduled_Al_TicketLines WHERE reschedule_ticket_id = @RescheduleId)
        UNION ALL
        SELECT 'SSR Updation', s.invoice_number FROM dbo.SSR_AL_Tickets s
        WHERE @RescheduleId IS NOT NULL AND s.company_id = @CompanyId AND s.source_reschedule_ticket_id = @RescheduleId
        UNION ALL
        SELECT 'Cancellation', c.invoice_number FROM dbo.Cancellation_AL_Tickets c
        WHERE @RescheduleId IS NOT NULL AND c.company_id = @CompanyId
          AND c.original_ticket_id = (SELECT original_ticket_id FROM dbo.Rescheduled_Al_Ticket WHERE id = @RescheduleId)
        UNION ALL
        -- A direct Reschedule (no booking in the software) has no
        -- original_ticket_id - its Cancellation is found through the line.
        SELECT 'Cancellation', c.invoice_number
        FROM dbo.Cancellation_AL_TicketLines cl
        INNER JOIN dbo.Cancellation_AL_Tickets c ON c.id = cl.cancellation_ticket_id
        WHERE @RescheduleId IS NOT NULL
          AND cl.reschedule_line_id IN (SELECT id FROM dbo.Rescheduled_Al_TicketLines WHERE reschedule_ticket_id = @RescheduleId)
    ), listed AS (
        SELECT STRING_AGG(kind + ' ' + invoice_number, ', ') WITHIN GROUP (ORDER BY kind, invoice_number) AS used_in
        FROM (SELECT DISTINCT kind, invoice_number FROM chain) d
    )
    SELECT CAST(CASE WHEN used_in IS NULL THEN 0 ELSE 1 END AS BIT) AS locked,
           CASE WHEN used_in IS NULL THEN NULL
                ELSE 'This ' + CASE WHEN @RescheduleId IS NOT NULL THEN 'Reschedule' ELSE 'Booking' END
                     + ' cannot be edited - it is already used in ' + used_in
                     + '. A ticket that has a Reschedule, Cancellation or SSR Updation built on it is locked.'
           END AS message
    FROM listed;
GO

-- ==========================================================================
-- dbo.sp_Ticket
-- Module   : Tickets + TicketLines (Airline booking header + passengers)
-- Actions  : LIST (one row per line, flat, for tickets.html), GET_HEADER
--            and GET_LINES (one ticket's header, resp. its lines, each its
--            own single result set per the house Single Result Set Rule)
-- Notes    : Server-computed fields (computed_discount/computed_tds/
--            computed_gst/computed_supp_commission/computed_supp_tds/
--            computed_supp_gst) are reproduced here to exactly match
--            TicketLine's Python @property formulas in models.py - the
--            GST ones resolve each fee field own ledger GST% via
--            MasterMapping(product_type='Airline'), same as
--            _field_gst_pct_cache field_ledger_gst_pct() helper.
-- Replaces : views.tickets_list / views.ticket_detail read-only ORM code
--            (ticket_create/ticket_update - the write + JV-posting path -
--            are migrated separately via sp_Ticket's SAVE/UPDATE actions).
-- ==========================================================================
CREATE OR ALTER PROCEDURE dbo.sp_Ticket
    @Action                NVARCHAR(50),
    @AllowChainEdit       BIT             = 0,   -- Super Admin: edit even when chained (fn_TicketChainLock)
    @Id                    INT             = NULL,
    @CompanyId             INT             = NULL,
    @AsOfDate              DATE            = NULL,
    @FromDate              DATE            = NULL,
    @CustomerName          NVARCHAR(150)   = NULL,
    @SupplierName          NVARCHAR(150)   = NULL,
    @BranchName            NVARCHAR(100)   = NULL,
    @InvoiceNumber         NVARCHAR(20)    = NULL,
    @InvoiceDate           DATE            = NULL,
    @InvoiceType           NVARCHAR(100)   = NULL,
    @BookingMode           NVARCHAR(20)    = NULL,
    @BookingType           NVARCHAR(50)    = NULL,
    @BookingStatus         NVARCHAR(20)    = NULL,
    @TravelType            NVARCHAR(20)    = NULL,
    @UserName              NVARCHAR(100)   = NULL,
    @Currency              NVARCHAR(5)     = NULL,
    @Roe                   DECIMAL(10,4)   = NULL,
    @BookingGivenBy        NVARCHAR(25)    = NULL,
    @BookingReference      NVARCHAR(30)    = NULL,
    @BookingRefDate        DATE            = NULL,
    @AirlinePnr            NVARCHAR(13)    = NULL,
    @GdsPnr                NVARCHAR(13)    = NULL,
    @OfficeId              NVARCHAR(30)    = NULL,
    @PaymentMode           NVARCHAR(20)    = NULL,
    @PaymentGatewayRef     NVARCHAR(60)    = NULL,
    @AirlineCategory       NVARCHAR(5)     = NULL,
    @LinesJson             NVARCHAR(MAX)   = NULL,
    @JvNarration           NVARCHAR(250)   = NULL,
    @JvTotalDebit          DECIMAL(16,2)   = NULL,
    @JvTotalCredit         DECIMAL(16,2)   = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'LIST'
    BEGIN
        SELECT
            tl.id, t.id AS ticket_id,
            COALESCE(t.airline_pnr, t.gds_pnr, t.booking_reference) AS pnr,
            tl.ticket_no, tl.airline_name, tl.airline_code, tl.flight_no, tl.passenger_name, tl.pax_type,
            tl.sector, t.invoice_date AS issue_date, tl.travel_date,
            tl.basic_fare, tl.markup, tl.total_billed, tl.status,
            t.invoice_number, t.invoice_date, t.invoice_type, t.booking_mode, t.booking_type,
            t.booking_status, cust.name AS customer_name,
            t.travel_type, t.user_name, t.currency, t.roe, t.booking_given_by, t.payment_mode, tl.airline_category,
            t.booking_reference, t.booking_ref_date, t.airline_pnr, t.gds_pnr, supp.name AS supplier_name,
            tl.office_id, tl.fop, tl.card_number,
            tl.yq, tl.yr, tl.k3_tax, tl.tax_others, tl.seat, tl.meal, tl.baggage, tl.other_ssr,
            tl.disc_on, tl.disc_type, tl.disc_value, tl.tds_per,
            tl.addl_markup, tl.ssr_markup, tl.service_fee, tl.addl_service_fee, tl.ssr_service_fee, tl.gst_pct,
            tl.supp_comm_on, tl.supp_comm_type, tl.supp_comm_value, tl.supp_tds_per,
            tl.supp_markup, tl.supp_addl_markup, tl.supp_service_fee, tl.supp_addl_service_fee, tl.supp_ssr_markup, tl.supp_ssr_service_fee,
            (CASE tl.disc_type
                WHEN 'Percentage' THEN
                    (CASE tl.disc_on
                        WHEN 'Basic' THEN tl.basic_fare
                        WHEN 'Basic + YQ' THEN tl.basic_fare + tl.yq
                        WHEN 'Basic + YR' THEN tl.basic_fare + tl.yr
                        WHEN 'Basic + YQ + YR' THEN tl.basic_fare + tl.yq + tl.yr
                        WHEN 'Gross' THEN tl.basic_fare + tl.yq + tl.yr + tl.k3_tax + tl.tax_others + tl.seat + tl.meal + tl.baggage + tl.other_ssr
                        ELSE 0 END) * (tl.disc_value / 100)
                WHEN 'Flat' THEN tl.disc_value
                ELSE 0 END) AS computed_discount,
            (CASE tl.disc_type
                WHEN 'Percentage' THEN
                    (CASE tl.disc_on
                        WHEN 'Basic' THEN tl.basic_fare
                        WHEN 'Basic + YQ' THEN tl.basic_fare + tl.yq
                        WHEN 'Basic + YR' THEN tl.basic_fare + tl.yr
                        WHEN 'Basic + YQ + YR' THEN tl.basic_fare + tl.yq + tl.yr
                        WHEN 'Gross' THEN tl.basic_fare + tl.yq + tl.yr + tl.k3_tax + tl.tax_others + tl.seat + tl.meal + tl.baggage + tl.other_ssr
                        ELSE 0 END) * (tl.disc_value / 100)
                WHEN 'Flat' THEN tl.disc_value
                ELSE 0 END) * (tl.tds_per / 100) AS computed_tds,
            (tl.service_fee * ISNULL(l_svc.gst_percentage, 0) / 100
             + tl.addl_service_fee * ISNULL(l_addlsvc.gst_percentage, 0) / 100
             + tl.ssr_service_fee * ISNULL(l_ssrsvc.gst_percentage, 0) / 100) AS computed_gst,
            (CASE tl.supp_comm_type
                WHEN 'Percentage' THEN
                    (CASE tl.supp_comm_on
                        WHEN 'Basic' THEN tl.basic_fare
                        WHEN 'Basic + YQ' THEN tl.basic_fare + tl.yq
                        WHEN 'Basic + YR' THEN tl.basic_fare + tl.yr
                        WHEN 'Basic + YQ + YR' THEN tl.basic_fare + tl.yq + tl.yr
                        WHEN 'Gross' THEN tl.basic_fare + tl.yq + tl.yr + tl.k3_tax + tl.tax_others + tl.seat + tl.meal + tl.baggage + tl.other_ssr
                        ELSE 0 END) * (tl.supp_comm_value / 100)
                WHEN 'Flat' THEN tl.supp_comm_value
                ELSE 0 END) AS computed_supp_commission,
            (CASE tl.supp_comm_type
                WHEN 'Percentage' THEN
                    (CASE tl.supp_comm_on
                        WHEN 'Basic' THEN tl.basic_fare
                        WHEN 'Basic + YQ' THEN tl.basic_fare + tl.yq
                        WHEN 'Basic + YR' THEN tl.basic_fare + tl.yr
                        WHEN 'Basic + YQ + YR' THEN tl.basic_fare + tl.yq + tl.yr
                        WHEN 'Gross' THEN tl.basic_fare + tl.yq + tl.yr + tl.k3_tax + tl.tax_others + tl.seat + tl.meal + tl.baggage + tl.other_ssr
                        ELSE 0 END) * (tl.supp_comm_value / 100)
                WHEN 'Flat' THEN tl.supp_comm_value
                ELSE 0 END) * (tl.supp_tds_per / 100) AS computed_supp_tds,
            (tl.supp_service_fee * ISNULL(l_suppsvc.gst_percentage, 0) / 100
             + tl.supp_addl_service_fee * ISNULL(l_suppaddlsvc.gst_percentage, 0) / 100
             + tl.supp_ssr_service_fee * ISNULL(l_suppssrsvc.gst_percentage, 0) / 100) AS computed_supp_gst,
            tl.supp_gst_pct
        FROM dbo.AL_TicketLines tl
        INNER JOIN dbo.AL_Tickets t ON t.id = tl.ticket_id
        INNER JOIN dbo.Ledgers cust ON cust.id = t.customer_ledger_id
        LEFT JOIN dbo.Ledgers supp ON supp.id = tl.supplier_ledger_id
        LEFT JOIN dbo.MasterMapping mm_svc ON mm_svc.company_id = t.company_id AND mm_svc.product_type = 'Airline' AND mm_svc.field_name = 'Service Fee A/c'
        LEFT JOIN dbo.Ledgers l_svc ON l_svc.id = mm_svc.ledger_id
        LEFT JOIN dbo.MasterMapping mm_addlsvc ON mm_addlsvc.company_id = t.company_id AND mm_addlsvc.product_type = 'Airline' AND mm_addlsvc.field_name = 'Addl Service Fee A/c'
        LEFT JOIN dbo.Ledgers l_addlsvc ON l_addlsvc.id = mm_addlsvc.ledger_id
        LEFT JOIN dbo.MasterMapping mm_ssrsvc ON mm_ssrsvc.company_id = t.company_id AND mm_ssrsvc.product_type = 'Airline' AND mm_ssrsvc.field_name = 'SSR Service Fee A/c'
        LEFT JOIN dbo.Ledgers l_ssrsvc ON l_ssrsvc.id = mm_ssrsvc.ledger_id
        LEFT JOIN dbo.MasterMapping mm_suppsvc ON mm_suppsvc.company_id = t.company_id AND mm_suppsvc.product_type = 'Airline' AND mm_suppsvc.field_name = 'Supplier Service Fee A/c'
        LEFT JOIN dbo.Ledgers l_suppsvc ON l_suppsvc.id = mm_suppsvc.ledger_id
        LEFT JOIN dbo.MasterMapping mm_suppaddlsvc ON mm_suppaddlsvc.company_id = t.company_id AND mm_suppaddlsvc.product_type = 'Airline' AND mm_suppaddlsvc.field_name = 'Supplier Addl Service Fee A/c'
        LEFT JOIN dbo.Ledgers l_suppaddlsvc ON l_suppaddlsvc.id = mm_suppaddlsvc.ledger_id
        LEFT JOIN dbo.MasterMapping mm_suppssrsvc ON mm_suppssrsvc.company_id = t.company_id AND mm_suppssrsvc.product_type = 'Airline' AND mm_suppssrsvc.field_name = 'Supplier SSR Service Fee A/c'
        LEFT JOIN dbo.Ledgers l_suppssrsvc ON l_suppssrsvc.id = mm_suppssrsvc.ledger_id
        WHERE t.company_id = @CompanyId
        ORDER BY tl.id DESC;
        RETURN;
    END

    IF @Action = 'LIST_INVOICE_NUMBERS_BY_TYPE'
    BEGIN
        -- views.voucher_type_next_number's "every invoice number already
        -- used under this Invoice Type" read - combines Tickets,
        -- RescheduleAirlineTickets AND CancellationAirlineTickets (they share
        -- one numbering sequence per Invoice Type - without Cancellations
        -- here, a Credit Note type like Refunds Air never moved past its
        -- first number), optionally only from the voucher type's own Restart
        -- Applicable From date onward. The period-bucket filtering and
        -- prefix/suffix/zero-pad number parsing itself stays in Python.
        SELECT invoice_number, invoice_date FROM dbo.AL_Tickets
        WHERE company_id = @CompanyId AND invoice_type = @InvoiceType
          AND (@FromDate IS NULL OR invoice_date >= @FromDate)
        UNION ALL
        SELECT invoice_number, invoice_date FROM dbo.Rescheduled_Al_Ticket
        WHERE company_id = @CompanyId AND invoice_type = @InvoiceType
          AND (@FromDate IS NULL OR invoice_date >= @FromDate)
        UNION ALL
        SELECT invoice_number, invoice_date FROM dbo.Cancellation_AL_Tickets
        WHERE company_id = @CompanyId AND invoice_type = @InvoiceType
          AND (@FromDate IS NULL OR invoice_date >= @FromDate)
        UNION ALL
        -- SSR Updations share the same per-Invoice-Type sequence too.
        SELECT invoice_number, invoice_date FROM dbo.SSR_AL_Tickets
        WHERE company_id = @CompanyId AND invoice_type = @InvoiceType
          AND (@FromDate IS NULL OR invoice_date >= @FromDate)
        UNION ALL
        -- ... and Miscellaneous transactions.
        SELECT invoice_number, invoice_date FROM dbo.Misc_Transactions
        WHERE company_id = @CompanyId AND invoice_type = @InvoiceType
          AND (@FromDate IS NULL OR invoice_date >= @FromDate);
        RETURN;
    END

    IF @Action = 'LIST_FOR_BALANCE'
    BEGIN
        -- Raw (uncomputed) fields only, one row per TicketLine, plus every
        -- ticket-header field _compute_jv_lines/_fop_payment_lines/
        -- _pg_receipt_lines need - feeds views._ledger_balance_deltas'
        -- bulk rebuild of unsaved Ticket/TicketLine instances (the JV
        -- arithmetic itself still runs in Python, unchanged - this just
        -- replaces the ORM's .filter().prefetch_related() bulk read).
        SELECT
            t.id AS ticket_id, t.company_id, cust.id AS customer_id, cust.name AS customer_name, cust.state_name AS customer_state_name,
            t.booking_reference, t.airline_pnr, t.payment_mode, t.payment_gateway_ref, t.invoice_date, t.booking_ref_date, t.branch_name,
            t.office_id AS ticket_office_id, t.invoice_number, v.voucher_no,
            tl.id AS line_id, tl.airline_code, tl.airline_name, tl.airline_category, tl.flight_no, tl.ticket_no, tl.passenger_name, tl.pax_type,
            tl.sector, tl.travel_date, tl.cabin, tl.travel_class, tl.fare_type,
            tl.basic_fare, tl.yq, tl.yr, tl.k3_tax, tl.tax_others, tl.seat, tl.meal, tl.baggage, tl.other_ssr,
            tl.disc_on, tl.disc_type, tl.disc_value, tl.tds_per, tl.pg_charges, tl.pg_charges_percentage,
            tl.markup, tl.addl_markup, tl.ssr_markup, tl.service_fee, tl.addl_service_fee, tl.ssr_service_fee, tl.gst_pct,
            tl.status, tl.office_id, tl.fop, tl.card_number,
            tl.supp_comm_on, tl.supp_comm_type, tl.supp_comm_value, tl.supp_tds_per,
            tl.supp_markup, tl.supp_addl_markup, tl.supp_service_fee, tl.supp_addl_service_fee, tl.supp_ssr_markup, tl.supp_ssr_service_fee, tl.supp_gst_pct,
            tl.total_billed, tl.supplier_ledger_id, supp.name AS supplier_name
        FROM dbo.AL_Tickets t
        INNER JOIN dbo.Ledgers cust ON cust.id = t.customer_ledger_id
        INNER JOIN dbo.AL_TicketLines tl ON tl.ticket_id = t.id
        LEFT JOIN dbo.Ledgers supp ON supp.id = tl.supplier_ledger_id
        LEFT JOIN dbo.JournalVoucher v ON v.source_ticket_id = t.id
        WHERE t.company_id = @CompanyId
          AND (@AsOfDate IS NULL OR t.invoice_date <= @AsOfDate)
          AND (@FromDate IS NULL OR t.invoice_date >= @FromDate)
        ORDER BY t.id, tl.id;
        RETURN;
    END

    IF @Action = 'GET_HEADER'
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM dbo.AL_Tickets WHERE id = @Id AND company_id = @CompanyId)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Ticket not found.' AS error;
            RETURN;
        END

        SELECT t.id, t.invoice_number, t.invoice_date, t.invoice_type, t.booking_mode, t.booking_type,
               t.booking_status, cust.name AS customer_name, t.travel_type, t.user_name, t.currency, t.roe,
               t.booking_given_by, t.booking_reference, t.booking_ref_date, t.airline_pnr, t.gds_pnr,
               supp.name AS supplier_name, t.office_id, t.payment_mode, t.payment_gateway_ref,
               t.airline_category, t.branch_name, 'Success' AS status
        FROM dbo.AL_Tickets t
        INNER JOIN dbo.Ledgers cust ON cust.id = t.customer_ledger_id
        LEFT JOIN dbo.Ledgers supp ON supp.id = t.supplier_ledger_id
        WHERE t.id = @Id AND t.company_id = @CompanyId;
        RETURN;
    END

    IF @Action = 'GET_LINES'
    BEGIN
        SELECT tl.id, tl.rescheduled, tl.canceled,
               tl.airline_code, tl.airline_name, tl.airline_category, tl.flight_no, tl.ticket_no,
               tl.passenger_name, tl.pax_type, tl.sector, tl.travel_date, tl.cabin, tl.travel_class, tl.fare_type,
               tl.basic_fare, tl.yq, tl.yr, tl.k3_tax, tl.tax_others, tl.seat, tl.meal, tl.baggage, tl.other_ssr,
               tl.disc_on, tl.disc_type, tl.disc_value, tl.tds_per, tl.pg_charges, tl.pg_charges_percentage,
               tl.markup, tl.addl_markup, tl.ssr_markup, tl.service_fee, tl.addl_service_fee, tl.ssr_service_fee,
               tl.gst_pct, tl.total_billed, tl.status, tl.office_id, tl.fop, tl.card_number,
               tl.supp_comm_on, tl.supp_comm_type, tl.supp_comm_value, tl.supp_tds_per,
               tl.supp_markup, tl.supp_addl_markup, tl.supp_service_fee, tl.supp_addl_service_fee, tl.supp_ssr_markup, tl.supp_ssr_service_fee, tl.supp_gst_pct,
               ls.name AS supplier_name,
               (CASE tl.disc_type
                   WHEN 'Percentage' THEN
                       (CASE tl.disc_on
                           WHEN 'Basic' THEN tl.basic_fare
                           WHEN 'Basic + YQ' THEN tl.basic_fare + tl.yq
                           WHEN 'Basic + YR' THEN tl.basic_fare + tl.yr
                           WHEN 'Basic + YQ + YR' THEN tl.basic_fare + tl.yq + tl.yr
                           WHEN 'Gross' THEN tl.basic_fare + tl.yq + tl.yr + tl.k3_tax + tl.tax_others + tl.seat + tl.meal + tl.baggage + tl.other_ssr
                           ELSE 0 END) * (tl.disc_value / 100)
                   WHEN 'Flat' THEN tl.disc_value
                   ELSE 0 END) AS computed_discount,
               (CASE tl.disc_type
                   WHEN 'Percentage' THEN
                       (CASE tl.disc_on
                           WHEN 'Basic' THEN tl.basic_fare
                           WHEN 'Basic + YQ' THEN tl.basic_fare + tl.yq
                           WHEN 'Basic + YR' THEN tl.basic_fare + tl.yr
                           WHEN 'Basic + YQ + YR' THEN tl.basic_fare + tl.yq + tl.yr
                           WHEN 'Gross' THEN tl.basic_fare + tl.yq + tl.yr + tl.k3_tax + tl.tax_others + tl.seat + tl.meal + tl.baggage + tl.other_ssr
                           ELSE 0 END) * (tl.disc_value / 100)
                   WHEN 'Flat' THEN tl.disc_value
                   ELSE 0 END) * (tl.tds_per / 100) AS computed_tds,
               (tl.service_fee * ISNULL(l_svc.gst_percentage, 0) / 100
                + tl.addl_service_fee * ISNULL(l_addlsvc.gst_percentage, 0) / 100
                + tl.ssr_service_fee * ISNULL(l_ssrsvc.gst_percentage, 0) / 100) AS computed_gst,
               (CASE tl.supp_comm_type
                   WHEN 'Percentage' THEN
                       (CASE tl.supp_comm_on
                           WHEN 'Basic' THEN tl.basic_fare
                           WHEN 'Basic + YQ' THEN tl.basic_fare + tl.yq
                           WHEN 'Basic + YR' THEN tl.basic_fare + tl.yr
                           WHEN 'Basic + YQ + YR' THEN tl.basic_fare + tl.yq + tl.yr
                           WHEN 'Gross' THEN tl.basic_fare + tl.yq + tl.yr + tl.k3_tax + tl.tax_others + tl.seat + tl.meal + tl.baggage + tl.other_ssr
                           ELSE 0 END) * (tl.supp_comm_value / 100)
                   WHEN 'Flat' THEN tl.supp_comm_value
                   ELSE 0 END) AS computed_supp_commission,
               (CASE tl.supp_comm_type
                   WHEN 'Percentage' THEN
                       (CASE tl.supp_comm_on
                           WHEN 'Basic' THEN tl.basic_fare
                           WHEN 'Basic + YQ' THEN tl.basic_fare + tl.yq
                           WHEN 'Basic + YR' THEN tl.basic_fare + tl.yr
                           WHEN 'Basic + YQ + YR' THEN tl.basic_fare + tl.yq + tl.yr
                           WHEN 'Gross' THEN tl.basic_fare + tl.yq + tl.yr + tl.k3_tax + tl.tax_others + tl.seat + tl.meal + tl.baggage + tl.other_ssr
                           ELSE 0 END) * (tl.supp_comm_value / 100)
                   WHEN 'Flat' THEN tl.supp_comm_value
                   ELSE 0 END) * (tl.supp_tds_per / 100) AS computed_supp_tds,
               (tl.supp_service_fee * ISNULL(l_suppsvc.gst_percentage, 0) / 100
                + tl.supp_addl_service_fee * ISNULL(l_suppaddlsvc.gst_percentage, 0) / 100
             + tl.supp_ssr_service_fee * ISNULL(l_suppssrsvc.gst_percentage, 0) / 100) AS computed_supp_gst
        FROM dbo.AL_TicketLines tl
        INNER JOIN dbo.AL_Tickets t ON t.id = tl.ticket_id
        LEFT JOIN dbo.Ledgers ls ON ls.id = tl.supplier_ledger_id
        LEFT JOIN dbo.MasterMapping mm_svc ON mm_svc.company_id = t.company_id AND mm_svc.product_type = 'Airline' AND mm_svc.field_name = 'Service Fee A/c'
        LEFT JOIN dbo.Ledgers l_svc ON l_svc.id = mm_svc.ledger_id
        LEFT JOIN dbo.MasterMapping mm_addlsvc ON mm_addlsvc.company_id = t.company_id AND mm_addlsvc.product_type = 'Airline' AND mm_addlsvc.field_name = 'Addl Service Fee A/c'
        LEFT JOIN dbo.Ledgers l_addlsvc ON l_addlsvc.id = mm_addlsvc.ledger_id
        LEFT JOIN dbo.MasterMapping mm_ssrsvc ON mm_ssrsvc.company_id = t.company_id AND mm_ssrsvc.product_type = 'Airline' AND mm_ssrsvc.field_name = 'SSR Service Fee A/c'
        LEFT JOIN dbo.Ledgers l_ssrsvc ON l_ssrsvc.id = mm_ssrsvc.ledger_id
        LEFT JOIN dbo.MasterMapping mm_suppsvc ON mm_suppsvc.company_id = t.company_id AND mm_suppsvc.product_type = 'Airline' AND mm_suppsvc.field_name = 'Supplier Service Fee A/c'
        LEFT JOIN dbo.Ledgers l_suppsvc ON l_suppsvc.id = mm_suppsvc.ledger_id
        LEFT JOIN dbo.MasterMapping mm_suppaddlsvc ON mm_suppaddlsvc.company_id = t.company_id AND mm_suppaddlsvc.product_type = 'Airline' AND mm_suppaddlsvc.field_name = 'Supplier Addl Service Fee A/c'
        LEFT JOIN dbo.Ledgers l_suppaddlsvc ON l_suppaddlsvc.id = mm_suppaddlsvc.ledger_id
        LEFT JOIN dbo.MasterMapping mm_suppssrsvc ON mm_suppssrsvc.company_id = t.company_id AND mm_suppssrsvc.product_type = 'Airline' AND mm_suppssrsvc.field_name = 'Supplier SSR Service Fee A/c'
        LEFT JOIN dbo.Ledgers l_suppssrsvc ON l_suppssrsvc.id = mm_suppssrsvc.ledger_id
        WHERE tl.ticket_id = @Id
        ORDER BY tl.id;
        RETURN;
    END

    IF @Action = 'SAVE'
    BEGIN
        DECLARE @CustLedgerId INT, @SuppLedgerId INT;

        -- Editing a Booking / Reschedule that a later process (Reschedule,
        -- Cancellation, SSR Updation) is already built on is not allowed -
        -- see dbo.fn_TicketChainLock - except for a Super Admin
        -- (@AllowChainEdit = 1), whose changes then follow down the chain.
        IF @Id IS NOT NULL AND ISNULL(@AllowChainEdit, 0) = 0
        BEGIN
            DECLARE @ChainLockMsg NVARCHAR(MAX) = (SELECT message FROM dbo.fn_TicketChainLock(@CompanyId, @Id, NULL));
            IF @ChainLockMsg IS NOT NULL
            BEGIN
                SELECT NULL AS id, 'Error' AS status, @ChainLockMsg AS error;
                RETURN;
            END
        END
        SELECT @CustLedgerId = id FROM dbo.Ledgers WHERE company_id = @CompanyId AND name = @CustomerName AND ledger_category = 'DEBTOR';
        IF @CustLedgerId IS NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, '"' + ISNULL(@CustomerName, '') + '" is not a real customer ledger (Sundry Debtors).' AS error;
            RETURN;
        END
        IF @SupplierName IS NOT NULL
        BEGIN
            SELECT @SuppLedgerId = id FROM dbo.Ledgers WHERE company_id = @CompanyId AND name = @SupplierName AND ledger_category = 'CREDITOR';
            IF @SuppLedgerId IS NULL
            BEGIN
                SELECT NULL AS id, 'Error' AS status, '"' + @SupplierName + '" is not a real supplier ledger (Sundry Creditors).' AS error;
                RETURN;
            END
        END

        -- Invoice Number uniqueness - shared sequence with RescheduleAirlineTickets.
        IF EXISTS (SELECT 1 FROM dbo.AL_Tickets WHERE company_id = @CompanyId AND invoice_number = @InvoiceNumber AND (@Id IS NULL OR id <> @Id))
           OR EXISTS (SELECT 1 FROM dbo.Rescheduled_Al_Ticket WHERE company_id = @CompanyId AND invoice_number = @InvoiceNumber)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Invoice Number "' + @InvoiceNumber + '" already exists.' AS error;
            RETURN;
        END
        IF @BookingReference IS NOT NULL AND EXISTS (
            SELECT 1 FROM dbo.AL_Tickets WHERE company_id = @CompanyId AND booking_reference = @BookingReference AND (@Id IS NULL OR id <> @Id)
        )
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Booking Reference "' + @BookingReference + '" already exists.' AS error;
            RETURN;
        END

        -- Duplicate Ticket No within this submission.
        IF EXISTS (
            SELECT ticket_no FROM OPENJSON(@LinesJson) WITH (ticket_no NVARCHAR(30) '$.ticket_no')
            GROUP BY ticket_no HAVING COUNT(*) > 1
        )
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Duplicate Ticket Number within this submission.' AS error;
            RETURN;
        END

        -- Ticket No is globally unique across ALL tickets' lines (except this ticket's own existing lines, on update).
        DECLARE @DupTicketNo NVARCHAR(30);
        SELECT TOP 1 @DupTicketNo = tl.ticket_no
        FROM dbo.AL_TicketLines tl
        INNER JOIN OPENJSON(@LinesJson) WITH (ticket_no NVARCHAR(30) '$.ticket_no') j ON j.ticket_no = tl.ticket_no
        WHERE (@Id IS NULL OR tl.ticket_id <> @Id);
        IF @DupTicketNo IS NOT NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Ticket Number "' + @DupTicketNo + '" already exists.' AS error;
            RETURN;
        END

        -- Every line's own supplier_name (if given) must resolve to a real supplier ledger.
        DECLARE @BadSupplierName NVARCHAR(150), @BadSupplierTicketNo NVARCHAR(30);
        SELECT TOP 1 @BadSupplierName = j.supplier_name, @BadSupplierTicketNo = j.ticket_no
        FROM OPENJSON(@LinesJson) WITH (supplier_name NVARCHAR(150) '$.supplier_name', ticket_no NVARCHAR(30) '$.ticket_no') j
        WHERE j.supplier_name IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM dbo.Ledgers WHERE company_id = @CompanyId AND name = j.supplier_name AND ledger_category = 'CREDITOR'
        );
        IF @BadSupplierName IS NOT NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status,
                   '"' + @BadSupplierName + '" (Ticket No. ' + ISNULL(@BadSupplierTicketNo, '?') + ') is not a real supplier ledger (Sundry Creditors).' AS error;
            RETURN;
        END

        BEGIN TRY
            BEGIN TRAN;

            DECLARE @ResultId INT;
            DECLARE @WasCreated BIT = 0;

            IF @Id IS NOT NULL AND EXISTS (SELECT 1 FROM dbo.AL_Tickets WHERE id = @Id AND company_id = @CompanyId)
            BEGIN
                SET @ResultId = @Id;

                -- What this booking looked like before the edit - the copies
                -- its Reschedules / Cancellations / SSR Updations hold of it
                -- follow the change below (chain edits, Super Admin only).
                DECLARE @OldCust INT, @OldRef NVARCHAR(100), @OldPnr NVARCHAR(100), @OldGds NVARCHAR(100);
                SELECT @OldCust = customer_ledger_id, @OldRef = booking_reference, @OldPnr = airline_pnr, @OldGds = gds_pnr
                FROM dbo.AL_Tickets WHERE id = @Id;
                DECLARE @OldLines TABLE (id INT PRIMARY KEY, ticket_no NVARCHAR(30), passenger_name NVARCHAR(100), pax_type NVARCHAR(10));
                INSERT INTO @OldLines (id, ticket_no, passenger_name, pax_type)
                SELECT id, ticket_no, passenger_name, pax_type FROM dbo.AL_TicketLines WHERE ticket_id = @Id;

                UPDATE dbo.AL_Tickets
                SET customer_ledger_id = @CustLedgerId, supplier_ledger_id = @SuppLedgerId,
                    invoice_number = @InvoiceNumber, invoice_date = @InvoiceDate, invoice_type = @InvoiceType,
                    booking_mode = ISNULL(@BookingMode, booking_mode), booking_type = @BookingType, booking_status = @BookingStatus,
                    travel_type = @TravelType, user_name = @UserName, currency = ISNULL(@Currency, currency), roe = ISNULL(@Roe, roe),
                    booking_given_by = @BookingGivenBy, booking_reference = @BookingReference, booking_ref_date = @BookingRefDate,
                    airline_pnr = @AirlinePnr, gds_pnr = @GdsPnr, office_id = @OfficeId,
                    payment_mode = @PaymentMode, payment_gateway_ref = @PaymentGatewayRef, airline_category = @AirlineCategory,
                    branch_name = @BranchName
                WHERE id = @Id;

                -- Lines no longer present in this submission are dropped -
                -- but a line already referenced by a Reschedule
                -- (rescheduled = 1) is PROTECTed, same as the FK's own
                -- behaviour, just caught here with a clean message instead
                -- of a raw constraint error.
                DECLARE @ProtectedDropped NVARCHAR(MAX);
                SELECT @ProtectedDropped = STRING_AGG(tl.ticket_no, ', ') WITHIN GROUP (ORDER BY tl.ticket_no)
                FROM dbo.AL_TicketLines tl
                WHERE tl.ticket_id = @Id
                  AND (tl.rescheduled = 1
                       OR EXISTS (SELECT 1 FROM dbo.Rescheduled_Al_TicketLines x WHERE x.original_ticket_line_id = tl.id)
                       OR EXISTS (SELECT 1 FROM dbo.Cancellation_AL_TicketLines x WHERE x.original_ticket_line_id = tl.id)
                       OR EXISTS (SELECT 1 FROM dbo.SSR_AL_TicketLines x WHERE x.original_ticket_line_id = tl.id))
                  AND NOT EXISTS (
                      SELECT 1 FROM OPENJSON(@LinesJson) WITH (line_id INT '$.line_id', ticket_no NVARCHAR(30) '$.ticket_no') j
                      WHERE j.line_id = tl.id OR (j.line_id IS NULL AND j.ticket_no = tl.ticket_no)
                  );
                IF @ProtectedDropped IS NOT NULL
                BEGIN
                    ROLLBACK TRAN;
                    SELECT NULL AS id, 'Error' AS status,
                           'Ticket No. ' + @ProtectedDropped + ' has a Reschedule, Cancellation or SSR Updation built on it and cannot be removed from this ticket (change its details instead).' AS error;
                    RETURN;
                END

                DELETE tl
                FROM dbo.AL_TicketLines tl
                WHERE tl.ticket_id = @Id AND tl.rescheduled = 0
                  AND NOT EXISTS (SELECT 1 FROM dbo.Rescheduled_Al_TicketLines x WHERE x.original_ticket_line_id = tl.id)
                  AND NOT EXISTS (SELECT 1 FROM dbo.Cancellation_AL_TicketLines x WHERE x.original_ticket_line_id = tl.id)
                  AND NOT EXISTS (SELECT 1 FROM dbo.SSR_AL_TicketLines x WHERE x.original_ticket_line_id = tl.id)
                  AND NOT EXISTS (
                      SELECT 1 FROM OPENJSON(@LinesJson) WITH (line_id INT '$.line_id', ticket_no NVARCHAR(30) '$.ticket_no') j
                      WHERE j.line_id = tl.id OR (j.line_id IS NULL AND j.ticket_no = tl.ticket_no)
                  );

                -- Upsert each incoming line by its own id (a saved line), or
                -- by (ticket_id, ticket_no) for one sent without an id - so
                -- an edited Ticket No. updates the same line in place.
                MERGE dbo.AL_TicketLines AS tgt
                USING (
                    SELECT * FROM OPENJSON(@LinesJson) WITH (
                        line_id INT '$.line_id',
                        airline_code NVARCHAR(200) '$.airline_code', airline_name NVARCHAR(200) '$.airline_name',
                        airline_category NVARCHAR(5) '$.airline_category', flight_no NVARCHAR(200) '$.flight_no',
                        ticket_no NVARCHAR(30) '$.ticket_no', passenger_name NVARCHAR(50) '$.passenger_name',
                        pax_type NVARCHAR(10) '$.pax_type', sector NVARCHAR(200) '$.sector', travel_date NVARCHAR(200) '$.travel_date',
                        cabin NVARCHAR(200) '$.cabin', travel_class NVARCHAR(200) '$.travel_class', fare_type NVARCHAR(300) '$.fare_type',
                        basic_fare DECIMAL(14,2) '$.basic_fare', yq DECIMAL(14,2) '$.yq', yr DECIMAL(14,2) '$.yr',
                        k3_tax DECIMAL(14,2) '$.k3_tax', tax_others DECIMAL(14,2) '$.tax_others', seat DECIMAL(14,2) '$.seat',
                        meal DECIMAL(14,2) '$.meal', baggage DECIMAL(14,2) '$.baggage', other_ssr DECIMAL(14,2) '$.other_ssr',
                        disc_on NVARCHAR(20) '$.disc_on', disc_type NVARCHAR(12) '$.disc_type', disc_value DECIMAL(14,2) '$.disc_value',
                        tds_per DECIMAL(5,2) '$.tds_per', pg_charges DECIMAL(14,2) '$.pg_charges', pg_charges_percentage DECIMAL(5,2) '$.pg_charges_percentage',
                        markup DECIMAL(14,2) '$.markup', addl_markup DECIMAL(14,2) '$.addl_markup', ssr_markup DECIMAL(14,2) '$.ssr_markup',
                        service_fee DECIMAL(14,2) '$.service_fee', addl_service_fee DECIMAL(14,2) '$.addl_service_fee',
                        ssr_service_fee DECIMAL(14,2) '$.ssr_service_fee', gst_pct DECIMAL(5,2) '$.gst_pct', status NVARCHAR(15) '$.status',
                        office_id NVARCHAR(30) '$.office_id', fop NVARCHAR(20) '$.fop', card_number NVARCHAR(40) '$.card_number',
                        supp_comm_on NVARCHAR(20) '$.supp_comm_on', supp_comm_type NVARCHAR(12) '$.supp_comm_type',
                        supp_comm_value DECIMAL(14,2) '$.supp_comm_value', supp_tds_per DECIMAL(5,2) '$.supp_tds_per',
                        supp_markup DECIMAL(14,2) '$.supp_markup', supp_addl_markup DECIMAL(14,2) '$.supp_addl_markup',
                        supp_service_fee DECIMAL(14,2) '$.supp_service_fee', supp_addl_service_fee DECIMAL(14,2) '$.supp_addl_service_fee',
                        supp_ssr_markup DECIMAL(14,2) '$.supp_ssr_markup', supp_ssr_service_fee DECIMAL(14,2) '$.supp_ssr_service_fee',
                        supp_gst_pct DECIMAL(5,2) '$.supp_gst_pct', total_billed DECIMAL(14,2) '$.total_billed',
                        supplier_name NVARCHAR(150) '$.supplier_name'
                    )
                ) AS src
                ON tgt.ticket_id = @Id AND (tgt.id = src.line_id OR (src.line_id IS NULL AND tgt.ticket_no = src.ticket_no))
                WHEN MATCHED THEN UPDATE SET
                    ticket_no = src.ticket_no,
                    airline_code = src.airline_code, airline_name = src.airline_name, airline_category = src.airline_category,
                    flight_no = src.flight_no, passenger_name = src.passenger_name, pax_type = src.pax_type,
                    sector = src.sector, travel_date = src.travel_date, cabin = src.cabin, travel_class = src.travel_class,
                    fare_type = src.fare_type, basic_fare = src.basic_fare, yq = src.yq, yr = src.yr, k3_tax = src.k3_tax,
                    tax_others = src.tax_others, seat = src.seat, meal = src.meal, baggage = src.baggage, other_ssr = src.other_ssr,
                    disc_on = src.disc_on, disc_type = src.disc_type, disc_value = src.disc_value, tds_per = src.tds_per,
                    pg_charges = src.pg_charges, pg_charges_percentage = src.pg_charges_percentage,
                    markup = src.markup, addl_markup = src.addl_markup, ssr_markup = src.ssr_markup,
                    service_fee = src.service_fee, addl_service_fee = src.addl_service_fee, ssr_service_fee = src.ssr_service_fee,
                    gst_pct = src.gst_pct, status = ISNULL(src.status, tgt.status), office_id = src.office_id, fop = src.fop,
                    card_number = src.card_number, supp_comm_on = src.supp_comm_on, supp_comm_type = src.supp_comm_type,
                    supp_comm_value = src.supp_comm_value, supp_tds_per = src.supp_tds_per, supp_markup = src.supp_markup,
                    supp_addl_markup = src.supp_addl_markup, supp_service_fee = src.supp_service_fee,
                    supp_addl_service_fee = src.supp_addl_service_fee, supp_gst_pct = src.supp_gst_pct,
                    supp_ssr_markup = ISNULL(src.supp_ssr_markup, 0), supp_ssr_service_fee = ISNULL(src.supp_ssr_service_fee, 0),
                    total_billed = src.total_billed,
                    supplier_ledger_id = (SELECT id FROM dbo.Ledgers WHERE company_id = @CompanyId AND name = src.supplier_name AND ledger_category = 'CREDITOR'),
                    updated_at = SYSUTCDATETIME()
                WHEN NOT MATCHED THEN INSERT
                    (ticket_id, airline_code, airline_name, airline_category, flight_no, ticket_no, passenger_name, pax_type,
                     sector, travel_date, cabin, travel_class, fare_type, basic_fare, yq, yr, k3_tax, tax_others, seat, meal,
                     baggage, other_ssr, disc_on, disc_type, disc_value, tds_per, pg_charges, pg_charges_percentage,
                     markup, addl_markup, ssr_markup, service_fee, addl_service_fee, ssr_service_fee, gst_pct, status,
                     office_id, fop, card_number, supp_comm_on, supp_comm_type, supp_comm_value, supp_tds_per,
                     supp_markup, supp_addl_markup, supp_service_fee, supp_addl_service_fee, supp_ssr_markup, supp_ssr_service_fee, supp_gst_pct, total_billed,
                     supplier_ledger_id, rescheduled, created_at, updated_at)
                VALUES
                    (@Id, src.airline_code, src.airline_name, src.airline_category, src.flight_no, src.ticket_no, src.passenger_name, src.pax_type,
                     src.sector, src.travel_date, src.cabin, src.travel_class, src.fare_type, src.basic_fare, src.yq, src.yr, src.k3_tax, src.tax_others, src.seat, src.meal,
                     src.baggage, src.other_ssr, src.disc_on, src.disc_type, src.disc_value, src.tds_per, src.pg_charges, src.pg_charges_percentage,
                     src.markup, src.addl_markup, src.ssr_markup, src.service_fee, src.addl_service_fee, src.ssr_service_fee, src.gst_pct, ISNULL(src.status, 'ISSUED'),
                     src.office_id, src.fop, src.card_number, src.supp_comm_on, src.supp_comm_type, src.supp_comm_value, src.supp_tds_per,
                     src.supp_markup, src.supp_addl_markup, src.supp_service_fee, src.supp_addl_service_fee, ISNULL(src.supp_ssr_markup, 0), ISNULL(src.supp_ssr_service_fee, 0), src.supp_gst_pct, src.total_billed,
                     (SELECT id FROM dbo.Ledgers WHERE company_id = @CompanyId AND name = src.supplier_name AND ledger_category = 'CREDITOR'),
                     0, SYSUTCDATETIME(), SYSUTCDATETIME());

                -- Chain follow-through: the copies the Reschedules /
                -- Cancellations / SSR Updations of this booking hold of its
                -- customer, references and passenger details take the new
                -- value - only where they still hold the OLD one (a
                -- Reschedule's own re-issued Ticket No. / PNR stays its own).
                -- Amounts are never touched: each document keeps its own.
                UPDATE dbo.Rescheduled_Al_Ticket SET
                    customer_ledger_id = CASE WHEN customer_ledger_id = @OldCust THEN @CustLedgerId ELSE customer_ledger_id END,
                    booking_reference = CASE WHEN booking_reference = @OldRef THEN @BookingReference ELSE booking_reference END,
                    airline_pnr = CASE WHEN airline_pnr = @OldPnr THEN @AirlinePnr ELSE airline_pnr END,
                    gds_pnr = CASE WHEN gds_pnr = @OldGds THEN @GdsPnr ELSE gds_pnr END
                WHERE original_ticket_id = @Id;
                UPDATE dbo.Cancellation_AL_Tickets SET
                    customer_ledger_id = CASE WHEN customer_ledger_id = @OldCust THEN @CustLedgerId ELSE customer_ledger_id END,
                    airline_pnr = CASE WHEN airline_pnr = @OldPnr THEN @AirlinePnr ELSE airline_pnr END,
                    gds_pnr = CASE WHEN gds_pnr = @OldGds THEN @GdsPnr ELSE gds_pnr END
                WHERE original_ticket_id = @Id;
                UPDATE dbo.SSR_AL_Tickets SET
                    customer_ledger_id = CASE WHEN customer_ledger_id = @OldCust THEN @CustLedgerId ELSE customer_ledger_id END,
                    ssr_reference = CASE WHEN ssr_reference = @OldRef THEN @BookingReference ELSE ssr_reference END,
                    airline_pnr = CASE WHEN airline_pnr = @OldPnr THEN @AirlinePnr ELSE airline_pnr END,
                    gds_pnr = CASE WHEN gds_pnr = @OldGds THEN @GdsPnr ELSE gds_pnr END
                WHERE original_ticket_id = @Id;
                UPDATE x SET
                    ticket_no = CASE WHEN x.ticket_no = o.ticket_no THEN n.ticket_no ELSE x.ticket_no END,
                    passenger_name = CASE WHEN x.passenger_name = o.passenger_name THEN n.passenger_name ELSE x.passenger_name END,
                    pax_type = CASE WHEN x.pax_type = o.pax_type THEN n.pax_type ELSE x.pax_type END
                FROM dbo.Rescheduled_Al_TicketLines x
                INNER JOIN @OldLines o ON o.id = x.original_ticket_line_id
                INNER JOIN dbo.AL_TicketLines n ON n.id = o.id;
                UPDATE x SET
                    ticket_no = CASE WHEN x.ticket_no = o.ticket_no THEN n.ticket_no ELSE x.ticket_no END,
                    passenger_name = CASE WHEN x.passenger_name = o.passenger_name THEN n.passenger_name ELSE x.passenger_name END,
                    pax_type = CASE WHEN x.pax_type = o.pax_type THEN n.pax_type ELSE x.pax_type END
                FROM dbo.Cancellation_AL_TicketLines x
                INNER JOIN @OldLines o ON o.id = x.original_ticket_line_id
                INNER JOIN dbo.AL_TicketLines n ON n.id = o.id;
                UPDATE x SET
                    ticket_no = CASE WHEN x.ticket_no = o.ticket_no THEN n.ticket_no ELSE x.ticket_no END,
                    passenger_name = CASE WHEN x.passenger_name = o.passenger_name THEN n.passenger_name ELSE x.passenger_name END,
                    pax_type = CASE WHEN x.pax_type = o.pax_type THEN n.pax_type ELSE x.pax_type END
                FROM dbo.SSR_AL_TicketLines x
                INNER JOIN @OldLines o ON o.id = x.original_ticket_line_id
                INNER JOIN dbo.AL_TicketLines n ON n.id = o.id;

                -- Upsert this ticket's JournalVoucher in place (never a 2nd row for the same ticket).
                IF EXISTS (SELECT 1 FROM dbo.JournalVoucher WHERE source_ticket_id = @Id)
                    UPDATE dbo.JournalVoucher
                    SET branch_name = ISNULL(@BranchName, 'Chennai Branch'), voucher_date = @InvoiceDate,
                        narration = @JvNarration, total_debit = @JvTotalDebit, total_credit = @JvTotalCredit,
                        updated_at = SYSUTCDATETIME()
                    WHERE source_ticket_id = @Id;
                ELSE
                BEGIN
                    DECLARE @NextNumU INT = (SELECT ISNULL(MAX(TRY_CAST(SUBSTRING(voucher_no, 4, 20) AS INT)), 0) + 1 FROM dbo.JournalVoucher WHERE company_id = @CompanyId AND category = 'AIRLINE' AND voucher_no LIKE 'AL-%');
                    INSERT INTO dbo.JournalVoucher
                        (company_id, branch_name, voucher_type, voucher_date, narration, category, voucher_no,
                         source_ticket_id, total_debit, total_credit, lines_json, created_at, updated_at)
                    VALUES
                        (@CompanyId, ISNULL(@BranchName, 'Chennai Branch'), 'Tax Invoice', @InvoiceDate, @JvNarration, 'AIRLINE',
                         'AL-' + CAST(@NextNumU AS NVARCHAR(10)), @Id, @JvTotalDebit, @JvTotalCredit, '[]', SYSUTCDATETIME(), SYSUTCDATETIME());
                END
            END
            ELSE
            BEGIN
                INSERT INTO dbo.AL_Tickets
                    (company_id, branch_name, invoice_number, invoice_date, invoice_type, booking_mode, booking_type, booking_status,
                     customer_ledger_id, supplier_ledger_id, travel_type, user_name, currency, roe, booking_given_by,
                     booking_reference, booking_ref_date, airline_pnr, gds_pnr, office_id, payment_mode, payment_gateway_ref,
                     airline_category, created_at, updated_at)
                VALUES
                    (@CompanyId, @BranchName, @InvoiceNumber, @InvoiceDate, @InvoiceType, ISNULL(@BookingMode, 'Manual'), @BookingType, @BookingStatus,
                     @CustLedgerId, @SuppLedgerId, @TravelType, @UserName, ISNULL(@Currency, 'INR'), ISNULL(@Roe, 1), @BookingGivenBy,
                     @BookingReference, @BookingRefDate, @AirlinePnr, @GdsPnr, @OfficeId, @PaymentMode, @PaymentGatewayRef,
                     @AirlineCategory, SYSUTCDATETIME(), SYSUTCDATETIME());
                SET @ResultId = SCOPE_IDENTITY();
                SET @WasCreated = 1;

                INSERT INTO dbo.AL_TicketLines
                    (ticket_id, airline_code, airline_name, airline_category, flight_no, ticket_no, passenger_name, pax_type,
                     sector, travel_date, cabin, travel_class, fare_type, basic_fare, yq, yr, k3_tax, tax_others, seat, meal,
                     baggage, other_ssr, disc_on, disc_type, disc_value, tds_per, pg_charges, pg_charges_percentage,
                     markup, addl_markup, ssr_markup, service_fee, addl_service_fee, ssr_service_fee, gst_pct, status,
                     office_id, fop, card_number, supp_comm_on, supp_comm_type, supp_comm_value, supp_tds_per,
                     supp_markup, supp_addl_markup, supp_service_fee, supp_addl_service_fee, supp_ssr_markup, supp_ssr_service_fee, supp_gst_pct, total_billed,
                     supplier_ledger_id, rescheduled, created_at, updated_at)
                SELECT
                    @ResultId, j.airline_code, j.airline_name, j.airline_category, j.flight_no, j.ticket_no, j.passenger_name, j.pax_type,
                    j.sector, j.travel_date, j.cabin, j.travel_class, j.fare_type, j.basic_fare, j.yq, j.yr, j.k3_tax, j.tax_others, j.seat, j.meal,
                    j.baggage, j.other_ssr, j.disc_on, j.disc_type, j.disc_value, j.tds_per, j.pg_charges, j.pg_charges_percentage,
                    j.markup, j.addl_markup, j.ssr_markup, j.service_fee, j.addl_service_fee, j.ssr_service_fee, j.gst_pct, ISNULL(j.status, 'ISSUED'),
                    j.office_id, j.fop, j.card_number, j.supp_comm_on, j.supp_comm_type, j.supp_comm_value, j.supp_tds_per,
                    j.supp_markup, j.supp_addl_markup, j.supp_service_fee, j.supp_addl_service_fee, ISNULL(j.supp_ssr_markup, 0), ISNULL(j.supp_ssr_service_fee, 0), j.supp_gst_pct, j.total_billed,
                    (SELECT id FROM dbo.Ledgers WHERE company_id = @CompanyId AND name = j.supplier_name AND ledger_category = 'CREDITOR'),
                    0, SYSUTCDATETIME(), SYSUTCDATETIME()
                FROM OPENJSON(@LinesJson) WITH (
                    airline_code NVARCHAR(200) '$.airline_code', airline_name NVARCHAR(200) '$.airline_name',
                    airline_category NVARCHAR(5) '$.airline_category', flight_no NVARCHAR(200) '$.flight_no',
                    ticket_no NVARCHAR(30) '$.ticket_no', passenger_name NVARCHAR(50) '$.passenger_name',
                    pax_type NVARCHAR(10) '$.pax_type', sector NVARCHAR(200) '$.sector', travel_date NVARCHAR(200) '$.travel_date',
                    cabin NVARCHAR(200) '$.cabin', travel_class NVARCHAR(200) '$.travel_class', fare_type NVARCHAR(300) '$.fare_type',
                    basic_fare DECIMAL(14,2) '$.basic_fare', yq DECIMAL(14,2) '$.yq', yr DECIMAL(14,2) '$.yr',
                    k3_tax DECIMAL(14,2) '$.k3_tax', tax_others DECIMAL(14,2) '$.tax_others', seat DECIMAL(14,2) '$.seat',
                    meal DECIMAL(14,2) '$.meal', baggage DECIMAL(14,2) '$.baggage', other_ssr DECIMAL(14,2) '$.other_ssr',
                    disc_on NVARCHAR(20) '$.disc_on', disc_type NVARCHAR(12) '$.disc_type', disc_value DECIMAL(14,2) '$.disc_value',
                    tds_per DECIMAL(5,2) '$.tds_per', pg_charges DECIMAL(14,2) '$.pg_charges', pg_charges_percentage DECIMAL(5,2) '$.pg_charges_percentage',
                    markup DECIMAL(14,2) '$.markup', addl_markup DECIMAL(14,2) '$.addl_markup', ssr_markup DECIMAL(14,2) '$.ssr_markup',
                    service_fee DECIMAL(14,2) '$.service_fee', addl_service_fee DECIMAL(14,2) '$.addl_service_fee',
                    ssr_service_fee DECIMAL(14,2) '$.ssr_service_fee', gst_pct DECIMAL(5,2) '$.gst_pct', status NVARCHAR(15) '$.status',
                    office_id NVARCHAR(30) '$.office_id', fop NVARCHAR(20) '$.fop', card_number NVARCHAR(40) '$.card_number',
                    supp_comm_on NVARCHAR(20) '$.supp_comm_on', supp_comm_type NVARCHAR(12) '$.supp_comm_type',
                    supp_comm_value DECIMAL(14,2) '$.supp_comm_value', supp_tds_per DECIMAL(5,2) '$.supp_tds_per',
                    supp_markup DECIMAL(14,2) '$.supp_markup', supp_addl_markup DECIMAL(14,2) '$.supp_addl_markup',
                    supp_service_fee DECIMAL(14,2) '$.supp_service_fee', supp_addl_service_fee DECIMAL(14,2) '$.supp_addl_service_fee',
                        supp_ssr_markup DECIMAL(14,2) '$.supp_ssr_markup', supp_ssr_service_fee DECIMAL(14,2) '$.supp_ssr_service_fee',
                    supp_gst_pct DECIMAL(5,2) '$.supp_gst_pct', total_billed DECIMAL(14,2) '$.total_billed',
                    supplier_name NVARCHAR(150) '$.supplier_name'
                ) AS j;

                DECLARE @NextNumC INT = (SELECT ISNULL(MAX(TRY_CAST(SUBSTRING(voucher_no, 4, 20) AS INT)), 0) + 1 FROM dbo.JournalVoucher WHERE company_id = @CompanyId AND category = 'AIRLINE' AND voucher_no LIKE 'AL-%');
                INSERT INTO dbo.JournalVoucher
                    (company_id, branch_name, voucher_type, voucher_date, narration, category, voucher_no,
                     source_ticket_id, total_debit, total_credit, lines_json, created_at, updated_at)
                VALUES
                    (@CompanyId, ISNULL(@BranchName, 'Chennai Branch'), 'Tax Invoice', @InvoiceDate, @JvNarration, 'AIRLINE',
                     'AL-' + CAST(@NextNumC AS NVARCHAR(10)), @ResultId, @JvTotalDebit, @JvTotalCredit, '[]', SYSUTCDATETIME(), SYSUTCDATETIME());
            END

            COMMIT TRAN;

            DECLARE @LineIds NVARCHAR(MAX);
            SELECT @LineIds = STRING_AGG(CAST(id AS NVARCHAR(10)), ',') FROM dbo.AL_TicketLines WHERE ticket_id = @ResultId;

            SELECT @ResultId AS id, @LineIds AS line_ids,
                   v.id AS voucher_id, v.voucher_no,
                   @WasCreated AS was_created, 'Success' AS status
            FROM dbo.JournalVoucher v
            WHERE v.source_ticket_id = @ResultId;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END
END
GO

-- ==========================================================================
-- dbo.sp_RescheduleTicket
-- Module   : RescheduleAirlineTickets + RescheduleAirlineTicketLines
-- Actions  : LIST (one row per line, flat, same shape as sp_Ticket's LIST -
--            report-dsr-airline-booking.html merges both lists together)
-- Notes    : Same computed-field formulas as sp_Ticket (see its own
--            comment header) plus three reschedule-only stored fields
--            (agent_penalty, reschedule_penalty, supplier_penalty) that
--            have no TicketLines equivalent.
-- Replaces : views.reschedule_tickets_list's read-only ORM code (the
--            reschedule_ticket_create/update write + chain-resolution +
--            JV-posting path is migrated separately).
-- ==========================================================================
CREATE OR ALTER PROCEDURE dbo.sp_RescheduleTicket
    @Action                NVARCHAR(50),
    @AllowChainEdit        BIT             = 0,   -- Super Admin: edit even when chained (fn_TicketChainLock)
    @Id                    INT             = NULL,
    @CompanyId             INT             = NULL,
    @AsOfDate              DATE            = NULL,
    @FromDate              DATE            = NULL,
    @OriginalTicketId      INT             = NULL,
    @PairsJson             NVARCHAR(MAX)   = NULL,
    @CustomerName          NVARCHAR(150)   = NULL,
    @SupplierName          NVARCHAR(150)   = NULL,
    @BranchName            NVARCHAR(100)   = NULL,
    @InvoiceNumber         NVARCHAR(20)    = NULL,
    @InvoiceDate           DATE            = NULL,
    @InvoiceType           NVARCHAR(100)   = NULL,
    @BookingMode           NVARCHAR(20)    = NULL,
    @BookingType           NVARCHAR(50)    = NULL,
    @BookingStatus         NVARCHAR(20)    = NULL,
    @TravelType            NVARCHAR(20)    = NULL,
    @UserName              NVARCHAR(100)   = NULL,
    @Currency              NVARCHAR(5)     = NULL,
    @Roe                   DECIMAL(10,4)   = NULL,
    @BookingGivenBy        NVARCHAR(25)    = NULL,
    @BookingReference      NVARCHAR(30)    = NULL,
    @BookingRefDate        DATE            = NULL,
    @AirlinePnr            NVARCHAR(13)    = NULL,
    @GdsPnr                NVARCHAR(13)    = NULL,
    @OfficeId              NVARCHAR(30)    = NULL,
    @PaymentMode           NVARCHAR(20)    = NULL,
    @PaymentGatewayRef     NVARCHAR(60)    = NULL,
    @AirlineCategory       NVARCHAR(5)     = NULL,
    @LinesJson             NVARCHAR(MAX)   = NULL,
    @JvNarration           NVARCHAR(250)   = NULL,
    @JvTotalDebit          DECIMAL(16,2)   = NULL,
    @JvTotalCredit         DECIMAL(16,2)   = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'LIST_FOR_BALANCE'
    BEGIN
        -- Reschedule's own twin of sp_Ticket's LIST_FOR_BALANCE - raw
        -- (uncomputed) fields only, one row per RescheduleAirlineTicketLine,
        -- plus the penalty fields TicketLines has no equivalent for -
        -- feeds views._ledger_balance_deltas' bulk rebuild of unsaved
        -- RescheduleAirlineTicket/RescheduleAirlineTicketLine instances.
        SELECT
            rt.id AS reschedule_ticket_id, rt.company_id, cust.id AS customer_id, cust.name AS customer_name, cust.state_name AS customer_state_name,
            rt.booking_reference, rt.airline_pnr, rt.payment_mode, rt.payment_gateway_ref, rt.invoice_date, rt.booking_ref_date, rt.branch_name,
            rt.office_id AS ticket_office_id, rt.invoice_number, v.voucher_no,
            rl.id AS line_id, rl.airline_code, rl.airline_name, rl.airline_category, rl.flight_no, rl.ticket_no, rl.passenger_name, rl.pax_type,
            rl.sector, rl.travel_date, rl.cabin, rl.travel_class, rl.fare_type,
            rl.basic_fare, rl.yq, rl.yr, rl.k3_tax, rl.tax_others, rl.seat, rl.meal, rl.baggage, rl.other_ssr, rl.supplier_penalty,
            rl.disc_on, rl.disc_type, rl.disc_value, rl.tds_per, rl.pg_charges, rl.pg_charges_percentage,
            rl.markup, rl.addl_markup, rl.ssr_markup, rl.service_fee, rl.addl_service_fee, rl.ssr_service_fee, rl.gst_pct,
            rl.status, rl.office_id, rl.fop, rl.card_number,
            rl.supp_comm_on, rl.supp_comm_type, rl.supp_comm_value, rl.supp_tds_per,
            rl.supp_markup, rl.supp_addl_markup, rl.supp_service_fee, rl.supp_addl_service_fee, rl.supp_ssr_markup, rl.supp_ssr_service_fee, rl.supp_gst_pct,
            rl.agent_penalty, rl.reschedule_penalty,
            rl.total_billed, rl.supplier_ledger_id, supp.name AS supplier_name
        FROM dbo.Rescheduled_Al_Ticket rt
        INNER JOIN dbo.Ledgers cust ON cust.id = rt.customer_ledger_id
        INNER JOIN dbo.Rescheduled_Al_TicketLines rl ON rl.reschedule_ticket_id = rt.id
        LEFT JOIN dbo.Ledgers supp ON supp.id = rl.supplier_ledger_id
        LEFT JOIN dbo.JournalVoucher v ON v.source_reschedule_ticket_id = rt.id
        WHERE rt.company_id = @CompanyId
          AND (@AsOfDate IS NULL OR rt.invoice_date <= @AsOfDate)
          AND (@FromDate IS NULL OR rt.invoice_date >= @FromDate)
        ORDER BY rt.id, rl.id;
        RETURN;
    END

    IF @Action = 'GET_HEADER'
    BEGIN
        -- Minimal existence-check + current-value lookup for the update
        -- flow (original_ticket_id is immutable once set - the update
        -- endpoint never lets the body change it - and booking_reference/
        -- airline_pnr default to their current value when the body omits
        -- them, same as ticket_update's own merge-onto-current behaviour).
        SELECT id, original_ticket_id, booking_reference, airline_pnr
        FROM dbo.Rescheduled_Al_Ticket
        WHERE id = @Id AND company_id = @CompanyId;
        RETURN;
    END

    IF @Action = 'GET_LINE_KEYS'
    BEGIN
        -- The (original_ticket_line_id, based_on_reschedule_line_id) pair
        -- for every line CURRENTLY attached to this reschedule ticket -
        -- views.reschedule_ticket_update's own "a line already attached to
        -- THIS SAME reschedule ticket in the same configuration isn't a
        -- new conflict" skip-list.
        SELECT original_ticket_line_id, based_on_reschedule_line_id
        FROM dbo.Rescheduled_Al_TicketLines
        WHERE reschedule_ticket_id = @Id;
        RETURN;
    END

    IF @Action = 'RESOLVE_ORIGINAL_LINE_IDS'
    BEGIN
        -- views.cancellation_ticket_create's own resolution: given a batch
        -- of Rescheduled_Al_TicketLines ids (the Cancellation lookup
        -- screen matched a passenger whose live data currently lives on a
        -- reschedule, not the true original Ticket), returns each one's
        -- TRUE original AL_TicketLines id - same hop
        -- ticket_lookup_for_cancellation's own "matched_line =
        -- rline.original_ticket_line" already does for display purposes.
        SELECT src.reschedule_line_id, rl.original_ticket_line_id
        FROM OPENJSON(@PairsJson) WITH (reschedule_line_id INT '$.reschedule_line_id') src
        LEFT JOIN dbo.Rescheduled_Al_TicketLines rl ON rl.id = src.reschedule_line_id;
        RETURN;
    END

    IF @Action = 'RESOLVE_LINES'
    BEGIN
        -- Resolves each submitted line's chain info in ONE round trip:
        -- the real original TicketLine (must belong to @OriginalTicketId -
        -- a NULL original_id means it doesn't, same "doesn't belong to
        -- this ticket" case views.py already checked for), and, when
        -- reschedule_line_id is given (chaining off an ALREADY-rescheduled
        -- ticket), that previous reschedule's own line + its own ticket's
        -- booking_reference (parent_pnr source when chained).
        SELECT
            src.original_ticket_line_id,
            otl.id AS original_id, otl.ticket_no AS original_ticket_no, otl.rescheduled AS original_rescheduled,
            ot.booking_reference AS original_ticket_booking_reference,
            src.reschedule_line_id AS based_on_id,
            rtl.ticket_no AS based_on_ticket_no, rtl.rescheduled AS based_on_rescheduled,
            rt2.booking_reference AS based_on_booking_reference
        FROM OPENJSON(@PairsJson) WITH (
            original_ticket_line_id INT '$.original_ticket_line_id',
            reschedule_line_id INT '$.reschedule_line_id'
        ) src
        LEFT JOIN dbo.AL_TicketLines otl ON otl.id = src.original_ticket_line_id AND otl.ticket_id = @OriginalTicketId
        LEFT JOIN dbo.AL_Tickets ot ON ot.id = @OriginalTicketId
        LEFT JOIN dbo.Rescheduled_Al_TicketLines rtl ON rtl.id = src.reschedule_line_id
        LEFT JOIN dbo.Rescheduled_Al_Ticket rt2 ON rt2.id = rtl.reschedule_ticket_id;
        RETURN;
    END

    IF @Action = 'LIST'
    BEGIN
        SELECT
            rl.id, CAST(NULL AS INT) AS ticket_id, rt.id AS reschedule_ticket_id,
            COALESCE(rt.airline_pnr, rt.gds_pnr, rt.booking_reference) AS pnr,
            rl.ticket_no, rl.airline_name, rl.airline_code, rl.flight_no, rl.passenger_name, rl.pax_type,
            rl.sector, rt.invoice_date AS issue_date, rl.travel_date,
            rl.basic_fare, rl.markup, rl.total_billed, rl.status,
            rt.invoice_number, rt.invoice_date, rt.invoice_type, rt.booking_mode, rt.booking_type,
            rt.booking_status, cust.name AS customer_name,
            rt.travel_type, rt.user_name, rt.currency, rt.roe, rt.booking_given_by, rt.payment_mode, rl.airline_category,
            rt.booking_reference, rt.booking_ref_date, rt.airline_pnr, rt.gds_pnr, supp.name AS supplier_name,
            rl.office_id, rl.fop, rl.card_number,
            rl.yq, rl.yr, rl.k3_tax, rl.tax_others, rl.seat, rl.meal, rl.baggage, rl.other_ssr,
            rl.disc_on, rl.disc_type, rl.disc_value, rl.tds_per,
            rl.addl_markup, rl.ssr_markup, rl.service_fee, rl.addl_service_fee, rl.ssr_service_fee, rl.gst_pct,
            rl.supp_comm_on, rl.supp_comm_type, rl.supp_comm_value, rl.supp_tds_per,
            rl.supp_markup, rl.supp_addl_markup, rl.supp_service_fee, rl.supp_addl_service_fee, rl.supp_ssr_markup, rl.supp_ssr_service_fee,
            (CASE rl.disc_type
                WHEN 'Percentage' THEN
                    (CASE rl.disc_on
                        WHEN 'Basic' THEN rl.basic_fare
                        WHEN 'Basic + YQ' THEN rl.basic_fare + rl.yq
                        WHEN 'Basic + YR' THEN rl.basic_fare + rl.yr
                        WHEN 'Basic + YQ + YR' THEN rl.basic_fare + rl.yq + rl.yr
                        WHEN 'Gross' THEN rl.basic_fare + rl.yq + rl.yr + rl.k3_tax + rl.tax_others + rl.seat + rl.meal + rl.baggage + rl.other_ssr
                        ELSE 0 END) * (rl.disc_value / 100)
                WHEN 'Flat' THEN rl.disc_value
                ELSE 0 END) AS computed_discount,
            (CASE rl.disc_type
                WHEN 'Percentage' THEN
                    (CASE rl.disc_on
                        WHEN 'Basic' THEN rl.basic_fare
                        WHEN 'Basic + YQ' THEN rl.basic_fare + rl.yq
                        WHEN 'Basic + YR' THEN rl.basic_fare + rl.yr
                        WHEN 'Basic + YQ + YR' THEN rl.basic_fare + rl.yq + rl.yr
                        WHEN 'Gross' THEN rl.basic_fare + rl.yq + rl.yr + rl.k3_tax + rl.tax_others + rl.seat + rl.meal + rl.baggage + rl.other_ssr
                        ELSE 0 END) * (rl.disc_value / 100)
                WHEN 'Flat' THEN rl.disc_value
                ELSE 0 END) * (rl.tds_per / 100) AS computed_tds,
            (rl.service_fee * ISNULL(l_svc.gst_percentage, 0) / 100
             + rl.addl_service_fee * ISNULL(l_addlsvc.gst_percentage, 0) / 100
             + rl.ssr_service_fee * ISNULL(l_ssrsvc.gst_percentage, 0) / 100) AS computed_gst,
            (rl.supp_service_fee * ISNULL(l_suppsvc.gst_percentage, 0) / 100
             + rl.supp_addl_service_fee * ISNULL(l_suppaddlsvc.gst_percentage, 0) / 100
             + rl.supp_ssr_service_fee * ISNULL(l_suppssrsvc.gst_percentage, 0) / 100) AS computed_supp_gst,
            rl.agent_penalty, rl.reschedule_penalty, rl.supplier_penalty
        FROM dbo.Rescheduled_Al_TicketLines rl
        INNER JOIN dbo.Rescheduled_Al_Ticket rt ON rt.id = rl.reschedule_ticket_id
        INNER JOIN dbo.Ledgers cust ON cust.id = rt.customer_ledger_id
        LEFT JOIN dbo.Ledgers supp ON supp.id = rl.supplier_ledger_id
        LEFT JOIN dbo.MasterMapping mm_svc ON mm_svc.company_id = rt.company_id AND mm_svc.product_type = 'Airline' AND mm_svc.field_name = 'Service Fee A/c'
        LEFT JOIN dbo.Ledgers l_svc ON l_svc.id = mm_svc.ledger_id
        LEFT JOIN dbo.MasterMapping mm_addlsvc ON mm_addlsvc.company_id = rt.company_id AND mm_addlsvc.product_type = 'Airline' AND mm_addlsvc.field_name = 'Addl Service Fee A/c'
        LEFT JOIN dbo.Ledgers l_addlsvc ON l_addlsvc.id = mm_addlsvc.ledger_id
        LEFT JOIN dbo.MasterMapping mm_ssrsvc ON mm_ssrsvc.company_id = rt.company_id AND mm_ssrsvc.product_type = 'Airline' AND mm_ssrsvc.field_name = 'SSR Service Fee A/c'
        LEFT JOIN dbo.Ledgers l_ssrsvc ON l_ssrsvc.id = mm_ssrsvc.ledger_id
        LEFT JOIN dbo.MasterMapping mm_suppsvc ON mm_suppsvc.company_id = rt.company_id AND mm_suppsvc.product_type = 'Airline' AND mm_suppsvc.field_name = 'Supplier Service Fee A/c'
        LEFT JOIN dbo.Ledgers l_suppsvc ON l_suppsvc.id = mm_suppsvc.ledger_id
        LEFT JOIN dbo.MasterMapping mm_suppaddlsvc ON mm_suppaddlsvc.company_id = rt.company_id AND mm_suppaddlsvc.product_type = 'Airline' AND mm_suppaddlsvc.field_name = 'Supplier Addl Service Fee A/c'
        LEFT JOIN dbo.Ledgers l_suppaddlsvc ON l_suppaddlsvc.id = mm_suppaddlsvc.ledger_id
        LEFT JOIN dbo.MasterMapping mm_suppssrsvc ON mm_suppssrsvc.company_id = rt.company_id AND mm_suppssrsvc.product_type = 'Airline' AND mm_suppssrsvc.field_name = 'Supplier SSR Service Fee A/c'
        LEFT JOIN dbo.Ledgers l_suppssrsvc ON l_suppssrsvc.id = mm_suppssrsvc.ledger_id
        WHERE rt.company_id = @CompanyId
        ORDER BY rl.id DESC;
        RETURN;
    END
    IF @Action = 'SAVE'
    BEGIN
        DECLARE @CustLedgerId INT, @SuppLedgerId INT;

        -- Editing a Booking / Reschedule that a later process (Reschedule,
        -- Cancellation, SSR Updation) is already built on is not allowed -
        -- see dbo.fn_TicketChainLock - except for a Super Admin
        -- (@AllowChainEdit = 1), whose changes then follow down the chain.
        IF @Id IS NOT NULL AND ISNULL(@AllowChainEdit, 0) = 0
        BEGIN
            DECLARE @ChainLockMsg NVARCHAR(MAX) = (SELECT message FROM dbo.fn_TicketChainLock(@CompanyId, NULL, @Id));
            IF @ChainLockMsg IS NOT NULL
            BEGIN
                SELECT NULL AS id, 'Error' AS status, @ChainLockMsg AS error;
                RETURN;
            END
        END
        SELECT @CustLedgerId = id FROM dbo.Ledgers WHERE company_id = @CompanyId AND name = @CustomerName AND ledger_category = 'DEBTOR';
        IF @CustLedgerId IS NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, '"' + ISNULL(@CustomerName, '') + '" is not a real customer ledger (Sundry Debtors).' AS error;
            RETURN;
        END
        IF @SupplierName IS NOT NULL
        BEGIN
            SELECT @SuppLedgerId = id FROM dbo.Ledgers WHERE company_id = @CompanyId AND name = @SupplierName AND ledger_category = 'CREDITOR';
            IF @SuppLedgerId IS NULL
            BEGIN
                SELECT NULL AS id, 'Error' AS status, '"' + @SupplierName + '" is not a real supplier ledger (Sundry Creditors).' AS error;
                RETURN;
            END
        END

        IF @Id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dbo.Rescheduled_Al_Ticket WHERE id = @Id AND company_id = @CompanyId)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Reschedule ticket not found.' AS error;
            RETURN;
        END

        IF EXISTS (SELECT 1 FROM dbo.AL_Tickets WHERE company_id = @CompanyId AND invoice_number = @InvoiceNumber)
           OR EXISTS (SELECT 1 FROM dbo.Rescheduled_Al_Ticket WHERE company_id = @CompanyId AND invoice_number = @InvoiceNumber AND (@Id IS NULL OR id <> @Id))
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Invoice Number "' + @InvoiceNumber + '" already exists.' AS error;
            RETURN;
        END
        IF EXISTS (SELECT 1 FROM dbo.AL_Tickets WHERE company_id = @CompanyId AND booking_reference = @BookingReference)
           OR EXISTS (SELECT 1 FROM dbo.Rescheduled_Al_Ticket WHERE company_id = @CompanyId AND booking_reference = @BookingReference AND (@Id IS NULL OR id <> @Id))
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Rescheduled Ref "' + @BookingReference + '" already exists.' AS error;
            RETURN;
        END

        IF EXISTS (
            SELECT ticket_no FROM OPENJSON(@LinesJson) WITH (ticket_no NVARCHAR(30) '$.ticket_no')
            GROUP BY ticket_no HAVING COUNT(*) > 1
        )
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Duplicate Ticket Number within this submission.' AS error;
            RETURN;
        END

        DECLARE @DupTicketNo NVARCHAR(30);
        SELECT TOP 1 @DupTicketNo = x.ticket_no FROM (
            SELECT tl.ticket_no FROM dbo.AL_TicketLines tl
            INNER JOIN OPENJSON(@LinesJson) WITH (ticket_no NVARCHAR(30) '$.ticket_no') j ON j.ticket_no = tl.ticket_no
            UNION ALL
            SELECT rl.ticket_no FROM dbo.Rescheduled_Al_TicketLines rl
            INNER JOIN OPENJSON(@LinesJson) WITH (ticket_no NVARCHAR(30) '$.ticket_no') j ON j.ticket_no = rl.ticket_no
            WHERE (@Id IS NULL OR rl.reschedule_ticket_id <> @Id)
        ) x;
        IF @DupTicketNo IS NOT NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Ticket Number "' + @DupTicketNo + '" already exists.' AS error;
            RETURN;
        END

        -- Every line's own supplier_name (if given) must resolve to a real supplier ledger.
        DECLARE @BadSupplierName NVARCHAR(150), @BadSupplierTicketNo NVARCHAR(30);
        SELECT TOP 1 @BadSupplierName = j.supplier_name, @BadSupplierTicketNo = j.ticket_no
        FROM OPENJSON(@LinesJson) WITH (supplier_name NVARCHAR(150) '$.supplier_name', ticket_no NVARCHAR(30) '$.ticket_no') j
        WHERE j.supplier_name IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM dbo.Ledgers WHERE company_id = @CompanyId AND name = j.supplier_name AND ledger_category = 'CREDITOR'
        );
        IF @BadSupplierName IS NOT NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status,
                   '"' + @BadSupplierName + '" (Ticket No. ' + ISNULL(@BadSupplierTicketNo, '?') + ') is not a real supplier ledger (Sundry Creditors).' AS error;
            RETURN;
        END

        -- Authoritative, save-time re-check that every NEWLY-attached line's
        -- original/chain source is still reschedule-eligible (mirrors
        -- views.py's own pre-check, re-verified here against the live flags
        -- inside this same transaction).
        -- 2026-10-08 fix: this used to read the JSON path '$.reschedule_line_id',
        -- but _build_reschedule_lines (views.py) only ever writes the chain
        -- link under the key "based_on_reschedule_line_id" (matching the
        -- actual Rescheduled_Al_TicketLines column it gets inserted into a
        -- bit further down) - '$.reschedule_line_id' never existed in this
        -- payload, so OPENJSON always returned NULL for it, which silently
        -- forced EVERY line down the "(j.* IS NULL AND otl.rescheduled = 1)"
        -- branch - i.e. this ALWAYS checked the TRUE ORIGINAL line's own
        -- rescheduled flag, even for a legitimate 2nd+/chained reschedule
        -- correctly built on top of an intermediate reschedule line that
        -- itself was still eligible. A first-time reschedule (no chain yet)
        -- never hit this, since based_on_reschedule_line_id is genuinely
        -- NULL there too - only chaining (reschedule an already-rescheduled
        -- ticket again) ever exposed it, exactly the case reported.
        DECLARE @Conflicting NVARCHAR(MAX);
        SELECT @Conflicting = STRING_AGG(x.ticket_no, ', ') WITHIN GROUP (ORDER BY x.ticket_no)
        FROM (
            SELECT DISTINCT
                CASE WHEN j.based_on_reschedule_line_id IS NOT NULL THEN rtl.ticket_no ELSE otl.ticket_no END AS ticket_no
            FROM OPENJSON(@LinesJson) WITH (
                original_ticket_line_id INT '$.original_ticket_line_id',
                based_on_reschedule_line_id INT '$.based_on_reschedule_line_id'
            ) j
            LEFT JOIN dbo.AL_TicketLines otl ON otl.id = j.original_ticket_line_id
            LEFT JOIN dbo.Rescheduled_Al_TicketLines rtl ON rtl.id = j.based_on_reschedule_line_id
            WHERE NOT EXISTS (
                    -- a line already attached to THIS SAME reschedule ticket
                    -- (same original + same chain source) isn't a conflict -
                    -- only a line not already ours is.
                    SELECT 1 FROM dbo.Rescheduled_Al_TicketLines existing
                    WHERE existing.reschedule_ticket_id = @Id
                      AND existing.original_ticket_line_id = j.original_ticket_line_id
                      AND ISNULL(existing.based_on_reschedule_line_id, -1) = ISNULL(j.based_on_reschedule_line_id, -1)
                )
                AND (
                    (j.based_on_reschedule_line_id IS NOT NULL AND rtl.rescheduled = 1)
                    OR (j.based_on_reschedule_line_id IS NULL AND otl.rescheduled = 1)
                )
        ) x;
        IF @Conflicting IS NOT NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status,
                   'Ticket No. ' + @Conflicting + ' has already been rescheduled and cannot be rescheduled again.' AS error;
            RETURN;
        END

        DECLARE @CurrencyOrDefault NVARCHAR(5) = ISNULL(@Currency, 'INR');

        BEGIN TRY
            BEGIN TRAN;

            DECLARE @ResultId INT;
            DECLARE @WasCreated BIT = 0;
            DECLARE @OldOriginalIds TABLE (original_ticket_line_id INT, based_on_reschedule_line_id INT);

            IF @Id IS NOT NULL
            BEGIN
                SET @ResultId = @Id;

                INSERT INTO @OldOriginalIds (original_ticket_line_id, based_on_reschedule_line_id)
                SELECT original_ticket_line_id, based_on_reschedule_line_id FROM dbo.Rescheduled_Al_TicketLines WHERE reschedule_ticket_id = @Id;

                UPDATE dbo.Rescheduled_Al_Ticket
                SET customer_ledger_id = @CustLedgerId, supplier_ledger_id = @SuppLedgerId,
                    invoice_number = @InvoiceNumber, invoice_date = @InvoiceDate, invoice_type = @InvoiceType,
                    booking_mode = ISNULL(@BookingMode, booking_mode), booking_type = @BookingType, booking_status = @BookingStatus,
                    travel_type = @TravelType, user_name = @UserName, currency = @CurrencyOrDefault, roe = ISNULL(@Roe, roe),
                    booking_given_by = @BookingGivenBy, booking_reference = @BookingReference, booking_ref_date = @BookingRefDate,
                    airline_pnr = @AirlinePnr, gds_pnr = @GdsPnr, office_id = @OfficeId,
                    payment_mode = @PaymentMode, payment_gateway_ref = @PaymentGatewayRef, airline_category = @AirlineCategory,
                    branch_name = @BranchName
                WHERE id = @Id;

                -- A line dropped from this resubmission goes back to
                -- eligible (original TicketLine, and its chain source if
                -- chained) - it's no longer rescheduled by anything.
                UPDATE otl SET rescheduled = 0
                FROM dbo.AL_TicketLines otl
                INNER JOIN @OldOriginalIds old ON old.original_ticket_line_id = otl.id
                WHERE NOT EXISTS (
                    SELECT 1 FROM OPENJSON(@LinesJson) WITH (original_ticket_line_id INT '$.original_ticket_line_id') j
                    WHERE j.original_ticket_line_id = old.original_ticket_line_id
                );
                UPDATE rtl SET rescheduled = 0
                FROM dbo.Rescheduled_Al_TicketLines rtl
                INNER JOIN @OldOriginalIds old ON old.based_on_reschedule_line_id = rtl.id
                WHERE old.based_on_reschedule_line_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM OPENJSON(@LinesJson) WITH (original_ticket_line_id INT '$.original_ticket_line_id') j
                    WHERE j.original_ticket_line_id = old.original_ticket_line_id
                );

                -- What this reschedule looked like before the edit - the
                -- copies later Reschedules / SSR Updations / Cancellations hold
                -- of it follow the change below (chain edits, Super Admin only).
                DECLARE @OldRCust INT, @OldRRef NVARCHAR(100), @OldRPnr NVARCHAR(100), @OldRGds NVARCHAR(100), @ROrigTicketId INT;
                SELECT @OldRCust = customer_ledger_id, @OldRRef = booking_reference, @OldRPnr = airline_pnr, @OldRGds = gds_pnr,
                       @ROrigTicketId = original_ticket_id
                FROM dbo.Rescheduled_Al_Ticket WHERE id = @Id;
                DECLARE @OldRLines TABLE (id INT PRIMARY KEY, original_ticket_line_id INT, ticket_no NVARCHAR(30), passenger_name NVARCHAR(100), pax_type NVARCHAR(10));
                INSERT INTO @OldRLines (id, original_ticket_line_id, ticket_no, passenger_name, pax_type)
                SELECT id, original_ticket_line_id, ticket_no, passenger_name, pax_type FROM dbo.Rescheduled_Al_TicketLines WHERE reschedule_ticket_id = @Id;

                -- A passenger dropped from this reschedule that a later
                -- Reschedule / SSR Updation is built on can't be removed.
                DECLARE @RProtected NVARCHAR(MAX);
                SELECT @RProtected = STRING_AGG(o.ticket_no, ', ')
                FROM @OldRLines o
                WHERE NOT EXISTS (SELECT 1 FROM OPENJSON(@LinesJson) WITH (original_ticket_line_id INT '$.original_ticket_line_id', ticket_no NVARCHAR(30) '$.ticket_no') j
                                  WHERE j.original_ticket_line_id = o.original_ticket_line_id
                                     OR (j.original_ticket_line_id IS NULL AND o.original_ticket_line_id IS NULL AND j.ticket_no = o.ticket_no))
                  AND (EXISTS (SELECT 1 FROM dbo.Rescheduled_Al_TicketLines x WHERE x.based_on_reschedule_line_id = o.id)
                       OR EXISTS (SELECT 1 FROM dbo.SSR_AL_TicketLines x WHERE x.reschedule_line_id = o.id));
                IF @RProtected IS NOT NULL
                BEGIN
                    ROLLBACK TRAN;
                    SELECT NULL AS id, 'Error' AS status,
                           'Ticket No. ' + @RProtected + ' has a later Reschedule or SSR Updation built on it and cannot be removed from this reschedule (change its details instead).' AS error;
                    RETURN;
                END
                -- Lines no longer present are dropped; the rest are updated in
                -- place by the MERGE below (their ids never change).
                DELETE rtl FROM dbo.Rescheduled_Al_TicketLines rtl
                WHERE rtl.reschedule_ticket_id = @Id
                  AND NOT EXISTS (SELECT 1 FROM OPENJSON(@LinesJson) WITH (original_ticket_line_id INT '$.original_ticket_line_id', ticket_no NVARCHAR(30) '$.ticket_no') j
                                  WHERE j.original_ticket_line_id = rtl.original_ticket_line_id
                                     OR (j.original_ticket_line_id IS NULL AND rtl.original_ticket_line_id IS NULL AND j.ticket_no = rtl.ticket_no));
            END
            ELSE
            BEGIN
                INSERT INTO dbo.Rescheduled_Al_Ticket
                    (company_id, branch_name, original_ticket_id, invoice_number, invoice_date, invoice_type, booking_mode, booking_type, booking_status,
                     customer_ledger_id, supplier_ledger_id, travel_type, user_name, currency, roe, booking_given_by,
                     booking_reference, booking_ref_date, airline_pnr, gds_pnr, office_id, payment_mode, payment_gateway_ref,
                     airline_category, created_at, updated_at)
                VALUES
                    (@CompanyId, @BranchName, @OriginalTicketId, @InvoiceNumber, @InvoiceDate, @InvoiceType, ISNULL(@BookingMode, 'Manual'), @BookingType, @BookingStatus,
                     @CustLedgerId, @SuppLedgerId, @TravelType, @UserName, @CurrencyOrDefault, ISNULL(@Roe, 1), @BookingGivenBy,
                     @BookingReference, @BookingRefDate, @AirlinePnr, @GdsPnr, @OfficeId, @PaymentMode, @PaymentGatewayRef,
                     @AirlineCategory, SYSUTCDATETIME(), SYSUTCDATETIME());
                SET @ResultId = SCOPE_IDENTITY();
                SET @WasCreated = 1;
            END

            -- Upsert each line by its original booking passenger
            -- (original_ticket_line_id) - an edited line keeps its own id
            -- (and its "rescheduled" flag), so a later Reschedule / SSR
            -- Updation built on it stays attached. A direct Reschedule's line
            -- (no booking in the software - original_ticket_line_id NULL)
            -- is matched by its Ticket No. instead.
            MERGE dbo.Rescheduled_Al_TicketLines AS tgt
            USING (
                SELECT * FROM OPENJSON(@LinesJson) WITH (
                original_ticket_line_id INT '$.original_ticket_line_id', based_on_reschedule_line_id INT '$.based_on_reschedule_line_id',
                parent_pnr NVARCHAR(30) '$.parent_pnr',
                airline_code NVARCHAR(200) '$.airline_code', airline_name NVARCHAR(200) '$.airline_name',
                airline_category NVARCHAR(5) '$.airline_category', flight_no NVARCHAR(200) '$.flight_no',
                ticket_no NVARCHAR(30) '$.ticket_no', passenger_name NVARCHAR(50) '$.passenger_name',
                pax_type NVARCHAR(10) '$.pax_type', sector NVARCHAR(200) '$.sector', travel_date NVARCHAR(200) '$.travel_date',
                cabin NVARCHAR(200) '$.cabin', travel_class NVARCHAR(200) '$.travel_class', fare_type NVARCHAR(300) '$.fare_type',
                basic_fare DECIMAL(14,2) '$.basic_fare', yq DECIMAL(14,2) '$.yq', yr DECIMAL(14,2) '$.yr',
                k3_tax DECIMAL(14,2) '$.k3_tax', tax_others DECIMAL(14,2) '$.tax_others', seat DECIMAL(14,2) '$.seat',
                meal DECIMAL(14,2) '$.meal', baggage DECIMAL(14,2) '$.baggage', other_ssr DECIMAL(14,2) '$.other_ssr',
                supplier_penalty DECIMAL(14,2) '$.supplier_penalty',
                disc_on NVARCHAR(20) '$.disc_on', disc_type NVARCHAR(12) '$.disc_type', disc_value DECIMAL(14,2) '$.disc_value',
                tds_per DECIMAL(5,2) '$.tds_per', pg_charges DECIMAL(14,2) '$.pg_charges', pg_charges_percentage DECIMAL(5,2) '$.pg_charges_percentage',
                markup DECIMAL(14,2) '$.markup', addl_markup DECIMAL(14,2) '$.addl_markup', ssr_markup DECIMAL(14,2) '$.ssr_markup',
                service_fee DECIMAL(14,2) '$.service_fee', addl_service_fee DECIMAL(14,2) '$.addl_service_fee',
                ssr_service_fee DECIMAL(14,2) '$.ssr_service_fee', gst_pct DECIMAL(5,2) '$.gst_pct', status NVARCHAR(15) '$.status',
                office_id NVARCHAR(30) '$.office_id', fop NVARCHAR(20) '$.fop', card_number NVARCHAR(40) '$.card_number',
                supp_comm_on NVARCHAR(20) '$.supp_comm_on', supp_comm_type NVARCHAR(12) '$.supp_comm_type',
                supp_comm_value DECIMAL(14,2) '$.supp_comm_value', supp_tds_per DECIMAL(5,2) '$.supp_tds_per',
                supp_markup DECIMAL(14,2) '$.supp_markup', supp_addl_markup DECIMAL(14,2) '$.supp_addl_markup',
                supp_service_fee DECIMAL(14,2) '$.supp_service_fee', supp_addl_service_fee DECIMAL(14,2) '$.supp_addl_service_fee',
                supp_ssr_markup DECIMAL(14,2) '$.supp_ssr_markup', supp_ssr_service_fee DECIMAL(14,2) '$.supp_ssr_service_fee',
                supp_gst_pct DECIMAL(5,2) '$.supp_gst_pct', agent_penalty DECIMAL(14,2) '$.agent_penalty',
                reschedule_penalty DECIMAL(14,2) '$.reschedule_penalty', total_billed DECIMAL(14,2) '$.total_billed',
                supplier_name NVARCHAR(150) '$.supplier_name'
            )
            ) AS src
            ON tgt.reschedule_ticket_id = @ResultId
               AND (tgt.original_ticket_line_id = src.original_ticket_line_id
                    OR (tgt.original_ticket_line_id IS NULL AND src.original_ticket_line_id IS NULL AND tgt.ticket_no = src.ticket_no))
            WHEN MATCHED THEN UPDATE SET
                    based_on_reschedule_line_id = src.based_on_reschedule_line_id,
                    parent_pnr = src.parent_pnr,
                    airline_code = src.airline_code,
                    airline_name = src.airline_name,
                    airline_category = src.airline_category,
                    flight_no = src.flight_no,
                    ticket_no = src.ticket_no,
                    passenger_name = src.passenger_name,
                    pax_type = src.pax_type,
                    sector = src.sector,
                    travel_date = src.travel_date,
                    cabin = src.cabin,
                    travel_class = src.travel_class,
                    fare_type = src.fare_type,
                    basic_fare = src.basic_fare,
                    yq = src.yq,
                    yr = src.yr,
                    k3_tax = src.k3_tax,
                    tax_others = src.tax_others,
                    seat = src.seat,
                    meal = src.meal,
                    baggage = src.baggage,
                    other_ssr = src.other_ssr,
                    supplier_penalty = src.supplier_penalty,
                    disc_on = src.disc_on,
                    disc_type = src.disc_type,
                    disc_value = src.disc_value,
                    tds_per = src.tds_per,
                    pg_charges = src.pg_charges,
                    pg_charges_percentage = src.pg_charges_percentage,
                    markup = src.markup,
                    addl_markup = src.addl_markup,
                    ssr_markup = src.ssr_markup,
                    service_fee = src.service_fee,
                    addl_service_fee = src.addl_service_fee,
                    ssr_service_fee = src.ssr_service_fee,
                    gst_pct = src.gst_pct,
                    status = ISNULL(src.status, 'ISSUED'),
                    office_id = src.office_id,
                    fop = src.fop,
                    card_number = src.card_number,
                    supp_comm_on = src.supp_comm_on,
                    supp_comm_type = src.supp_comm_type,
                    supp_comm_value = src.supp_comm_value,
                    supp_tds_per = src.supp_tds_per,
                    supp_markup = src.supp_markup,
                    supp_addl_markup = src.supp_addl_markup,
                    supp_service_fee = src.supp_service_fee,
                    supp_addl_service_fee = src.supp_addl_service_fee,
                    supp_ssr_markup = ISNULL(src.supp_ssr_markup, 0),
                    supp_ssr_service_fee = ISNULL(src.supp_ssr_service_fee, 0),
                    supp_gst_pct = src.supp_gst_pct,
                    agent_penalty = src.agent_penalty,
                    reschedule_penalty = src.reschedule_penalty,
                    total_billed = src.total_billed,
                    supplier_ledger_id = (SELECT id FROM dbo.Ledgers WHERE company_id = @CompanyId AND name = src.supplier_name AND ledger_category = 'CREDITOR'),
                    updated_at = SYSUTCDATETIME()
            WHEN NOT MATCHED THEN INSERT
                (reschedule_ticket_id, original_ticket_line_id, based_on_reschedule_line_id, rescheduled, parent_pnr, airline_code, airline_name, airline_category, flight_no, ticket_no, passenger_name, pax_type, sector, travel_date, cabin, travel_class, fare_type, basic_fare, yq, yr, k3_tax, tax_others, seat, meal, baggage, other_ssr, supplier_penalty, disc_on, disc_type, disc_value, tds_per, pg_charges, pg_charges_percentage, markup, addl_markup, ssr_markup, service_fee, addl_service_fee, ssr_service_fee, gst_pct, status, office_id, fop, card_number, supp_comm_on, supp_comm_type, supp_comm_value, supp_tds_per, supp_markup, supp_addl_markup, supp_service_fee, supp_addl_service_fee, supp_ssr_markup, supp_ssr_service_fee, supp_gst_pct, agent_penalty, reschedule_penalty, total_billed, supplier_ledger_id, created_at, updated_at)
            VALUES
                (@ResultId, src.original_ticket_line_id, src.based_on_reschedule_line_id, 0, src.parent_pnr, src.airline_code, src.airline_name, src.airline_category, src.flight_no, src.ticket_no, src.passenger_name, src.pax_type, src.sector, src.travel_date, src.cabin, src.travel_class, src.fare_type, src.basic_fare, src.yq, src.yr, src.k3_tax, src.tax_others, src.seat, src.meal, src.baggage, src.other_ssr, src.supplier_penalty, src.disc_on, src.disc_type, src.disc_value, src.tds_per, src.pg_charges, src.pg_charges_percentage, src.markup, src.addl_markup, src.ssr_markup, src.service_fee, src.addl_service_fee, src.ssr_service_fee, src.gst_pct, ISNULL(src.status, 'ISSUED'), src.office_id, src.fop, src.card_number, src.supp_comm_on, src.supp_comm_type, src.supp_comm_value, src.supp_tds_per, src.supp_markup, src.supp_addl_markup, src.supp_service_fee, src.supp_addl_service_fee, ISNULL(src.supp_ssr_markup, 0), ISNULL(src.supp_ssr_service_fee, 0), src.supp_gst_pct, src.agent_penalty, src.reschedule_penalty, src.total_billed, (SELECT id FROM dbo.Ledgers WHERE company_id = @CompanyId AND name = src.supplier_name AND ledger_category = 'CREDITOR'), SYSUTCDATETIME(), SYSUTCDATETIME());

            -- Chain follow-through (edit only): copies of this reschedule's
            -- customer, references and passenger details held by a later
            -- Reschedule, an SSR Updation sold on it or a Cancellation of the
            -- booking take the new value - only where they still hold the
            -- OLD one. Amounts are never touched.
            IF @Id IS NOT NULL
            BEGIN
                UPDATE x SET
                    ticket_no = CASE WHEN x.ticket_no = o.ticket_no THEN n.ticket_no ELSE x.ticket_no END,
                    passenger_name = CASE WHEN x.passenger_name = o.passenger_name THEN n.passenger_name ELSE x.passenger_name END,
                    pax_type = CASE WHEN x.pax_type = o.pax_type THEN n.pax_type ELSE x.pax_type END
                FROM dbo.Rescheduled_Al_TicketLines x
                INNER JOIN @OldRLines o ON o.id = x.based_on_reschedule_line_id
                INNER JOIN dbo.Rescheduled_Al_TicketLines n ON n.id = o.id;
                UPDATE r SET
                    customer_ledger_id = CASE WHEN r.customer_ledger_id = @OldRCust THEN @CustLedgerId ELSE r.customer_ledger_id END,
                    booking_reference = CASE WHEN r.booking_reference = @OldRRef THEN @BookingReference ELSE r.booking_reference END,
                    airline_pnr = CASE WHEN r.airline_pnr = @OldRPnr THEN @AirlinePnr ELSE r.airline_pnr END,
                    gds_pnr = CASE WHEN r.gds_pnr = @OldRGds THEN @GdsPnr ELSE r.gds_pnr END
                FROM dbo.Rescheduled_Al_Ticket r
                WHERE r.id <> @Id AND EXISTS (
                    SELECT 1 FROM dbo.Rescheduled_Al_TicketLines x INNER JOIN @OldRLines o ON o.id = x.based_on_reschedule_line_id
                    WHERE x.reschedule_ticket_id = r.id);
                UPDATE dbo.SSR_AL_Tickets SET
                    customer_ledger_id = CASE WHEN customer_ledger_id = @OldRCust THEN @CustLedgerId ELSE customer_ledger_id END,
                    ssr_reference = CASE WHEN ssr_reference = @OldRRef THEN @BookingReference ELSE ssr_reference END,
                    airline_pnr = CASE WHEN airline_pnr = @OldRPnr THEN @AirlinePnr ELSE airline_pnr END,
                    gds_pnr = CASE WHEN gds_pnr = @OldRGds THEN @GdsPnr ELSE gds_pnr END
                WHERE source_reschedule_ticket_id = @Id;
                UPDATE x SET
                    ticket_no = CASE WHEN x.ticket_no = o.ticket_no THEN n.ticket_no ELSE x.ticket_no END,
                    passenger_name = CASE WHEN x.passenger_name = o.passenger_name THEN n.passenger_name ELSE x.passenger_name END,
                    pax_type = CASE WHEN x.pax_type = o.pax_type THEN n.pax_type ELSE x.pax_type END
                FROM dbo.SSR_AL_TicketLines x
                INNER JOIN @OldRLines o ON o.id = x.reschedule_line_id
                INNER JOIN dbo.Rescheduled_Al_TicketLines n ON n.id = o.id;
                UPDATE dbo.Cancellation_AL_Tickets SET
                    customer_ledger_id = CASE WHEN customer_ledger_id = @OldRCust THEN @CustLedgerId ELSE customer_ledger_id END,
                    airline_pnr = CASE WHEN airline_pnr = @OldRPnr THEN @AirlinePnr ELSE airline_pnr END,
                    gds_pnr = CASE WHEN gds_pnr = @OldRGds THEN @GdsPnr ELSE gds_pnr END
                WHERE original_ticket_id = @ROrigTicketId;
                UPDATE x SET
                    ticket_no = CASE WHEN x.ticket_no = o.ticket_no THEN n.ticket_no ELSE x.ticket_no END,
                    passenger_name = CASE WHEN x.passenger_name = o.passenger_name THEN n.passenger_name ELSE x.passenger_name END,
                    pax_type = CASE WHEN x.pax_type = o.pax_type THEN n.pax_type ELSE x.pax_type END
                FROM dbo.Cancellation_AL_TicketLines x
                INNER JOIN dbo.Cancellation_AL_Tickets c ON c.id = x.cancellation_ticket_id AND c.original_ticket_id = @ROrigTicketId
                INNER JOIN @OldRLines o ON o.original_ticket_line_id = x.original_ticket_line_id
                INNER JOIN dbo.Rescheduled_Al_TicketLines n ON n.id = o.id;
            END

            -- Every line actually (re-)used by this save is now ineligible
            -- for further rescheduling - both the original TicketLine and,
            -- if chained, the reschedule line it's based on.
            UPDATE otl SET rescheduled = 1
            FROM dbo.AL_TicketLines otl
            INNER JOIN OPENJSON(@LinesJson) WITH (original_ticket_line_id INT '$.original_ticket_line_id') j
                ON j.original_ticket_line_id = otl.id;
            UPDATE rtl SET rescheduled = 1
            FROM dbo.Rescheduled_Al_TicketLines rtl
            INNER JOIN OPENJSON(@LinesJson) WITH (based_on_reschedule_line_id INT '$.based_on_reschedule_line_id') j
                ON j.based_on_reschedule_line_id = rtl.id
            WHERE j.based_on_reschedule_line_id IS NOT NULL;

            IF EXISTS (SELECT 1 FROM dbo.JournalVoucher WHERE source_reschedule_ticket_id = @ResultId)
                UPDATE dbo.JournalVoucher
                SET branch_name = ISNULL(@BranchName, 'Chennai Branch'), voucher_date = @InvoiceDate,
                    narration = @JvNarration, total_debit = @JvTotalDebit, total_credit = @JvTotalCredit,
                    updated_at = SYSUTCDATETIME()
                WHERE source_reschedule_ticket_id = @ResultId;
            ELSE
            BEGIN
                DECLARE @NextNum INT = (SELECT ISNULL(MAX(TRY_CAST(SUBSTRING(voucher_no, 5, 20) AS INT)), 0) + 1 FROM dbo.JournalVoucher WHERE company_id = @CompanyId AND category = 'AIRLINE_RESCHEDULE' AND voucher_no LIKE 'ALR-%');
                INSERT INTO dbo.JournalVoucher
                    (company_id, branch_name, voucher_type, voucher_date, narration, category, voucher_no,
                     source_reschedule_ticket_id, total_debit, total_credit, lines_json, created_at, updated_at)
                VALUES
                    (@CompanyId, ISNULL(@BranchName, 'Chennai Branch'), 'Tax Invoice', @InvoiceDate, @JvNarration, 'AIRLINE_RESCHEDULE',
                     'ALR-' + CAST(@NextNum AS NVARCHAR(10)), @ResultId, @JvTotalDebit, @JvTotalCredit, '[]', SYSUTCDATETIME(), SYSUTCDATETIME());
            END

            COMMIT TRAN;

            DECLARE @LineIds NVARCHAR(MAX);
            SELECT @LineIds = STRING_AGG(CAST(id AS NVARCHAR(10)), ',') FROM dbo.Rescheduled_Al_TicketLines WHERE reschedule_ticket_id = @ResultId;

            SELECT @ResultId AS id, @LineIds AS line_ids,
                   v.id AS voucher_id, v.voucher_no,
                   @WasCreated AS was_created, 'Success' AS status
            FROM dbo.JournalVoucher v
            WHERE v.source_reschedule_ticket_id = @ResultId;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END
END
GO

-- ==========================================================================
-- dbo.sp_Voucher
-- Module   : Voucher (manual double-entry postings, voucher-entry.html -
--            never ticket-driven, see dbo.sp_Ticket's JournalVoucher rows
--            for that)
-- Actions  : LIST, GET_BY_ID, SAVE (upsert by id - also resolves + stores
--            each line's own ledger_name, and validates the lines balance)
-- Replaces : views.vouchers_list / voucher_detail / voucher_create /
--            voucher_update / _validate_and_resolve_voucher_body's ORM code
-- ==========================================================================
CREATE OR ALTER PROCEDURE dbo.sp_Voucher
    @Action        NVARCHAR(50),
    @Id            INT            = NULL,
    @CompanyId     INT            = NULL,
    @BranchName    NVARCHAR(100)  = NULL,
    @VoucherType   NVARCHAR(20)   = NULL,
    @VoucherTypeName NVARCHAR(100) = NULL,   -- Voucher Type master entry picked (NULL = a standard type)
    @ManualNo      NVARCHAR(30)   = NULL,   -- number typed on the screen (Manual / Automatic & Manual Override types)
    @VoucherDate   DATE           = NULL,
    @Narration     NVARCHAR(250)  = NULL,
    @LinesJson     NVARCHAR(MAX)  = NULL
AS
BEGIN
    SET NOCOUNT ON;

    -- Automatic voucher numbering - plain numbers 1, 2, 3 ... (no prefix),
    -- one series per voucher type: Journal, Payment, Receipt, Contra, Debit
    -- Note, Credit Note each count on their own (highest number of that
    -- series + 1). A Voucher Type master entry (e.g. "Test Receipt") has its
    -- OWN series, also from 1, separate from the standard one. Series key =
    -- voucher_type + voucher_type_name (the master entry's name; NULL for a
    -- standard type) - uq_voucher_company_series_no.
    DECLARE @MasterTypeId INT = NULL;
    IF @VoucherTypeName IS NOT NULL
        SELECT TOP 1 @MasterTypeId = id FROM dbo.VoucherType WHERE company_id = @CompanyId AND name = @VoucherTypeName;
    DECLARE @SeriesType NVARCHAR(20) = ISNULL(@VoucherType, 'Journal');
    DECLARE @SeriesName NVARCHAR(100) = CASE WHEN @MasterTypeId IS NOT NULL THEN @VoucherTypeName END;
    -- That master entry's Voucher Number Method (standard types: Automatic) -
    -- same rules as the ticket screens: Automatic = always the next number;
    -- Manual = the number typed (required); Automatic & Manual Override = the
    -- number typed (pre-filled with the next one, editable).
    DECLARE @NumberMethod NVARCHAR(30) = ISNULL((SELECT number_method FROM dbo.VoucherType WHERE id = @MasterTypeId), 'Automatic');
    SET @ManualNo = NULLIF(LTRIM(RTRIM(@ManualNo)), '');
    DECLARE @UseManualNo BIT = CASE WHEN @NumberMethod IN ('Manual', 'Automatic & Manual Override') AND @ManualNo IS NOT NULL THEN 1 ELSE 0 END;

    IF @Action = 'NEXT_NUMBER'
    BEGIN
        SELECT CAST(ISNULL(MAX(TRY_CAST(voucher_no AS INT)), 0) + 1 AS NVARCHAR(10)) AS next_number
        FROM dbo.Vouchers
        WHERE company_id = @CompanyId AND category = 'MANUAL' AND voucher_type = @SeriesType
          AND ISNULL(voucher_type_name, '') = ISNULL(@SeriesName, '');
        RETURN;
    END

    IF @Action = 'LIST'
    BEGIN
        SELECT id, voucher_no, branch_name, voucher_type, voucher_type_name, voucher_date, narration,
               total_debit, total_credit, lines_json
        FROM dbo.Vouchers
        WHERE company_id = @CompanyId
        ORDER BY voucher_date DESC, id DESC;
        RETURN;
    END

    IF @Action = 'GET_BY_ID'
    BEGIN
        SELECT id, voucher_no, branch_name, voucher_type, voucher_type_name, voucher_date, narration,
               total_debit, total_credit, lines_json
        FROM dbo.Vouchers
        WHERE id = @Id AND company_id = @CompanyId;
        RETURN;
    END

    IF @Action = 'SAVE'
    BEGIN
        IF @CompanyId IS NULL OR @VoucherDate IS NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'company_id, voucher_date, and at least 2 lines are required.' AS error;
            RETURN;
        END
        IF (SELECT COUNT(*) FROM OPENJSON(@LinesJson)) < 2
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'company_id, voucher_date, and at least 2 lines are required.' AS error;
            RETURN;
        END
        -- The date must fall in the company's current financial year (the
        -- FY badge) - nothing before its start or after its end.
        DECLARE @FyStart DATE, @FyEnd DATE;
        SELECT @FyStart = fy_start, @FyEnd = fy_end FROM dbo.fn_CompanyFinancialYear(@CompanyId);
        IF @FyStart IS NOT NULL AND (@VoucherDate < @FyStart OR @VoucherDate > @FyEnd)
        BEGIN
            SELECT NULL AS id, 'Error' AS status,
                   'Voucher Date ' + FORMAT(@VoucherDate, 'dd/MM/yyyy') + ' is outside the financial year '
                   + FORMAT(@FyStart, 'dd/MM/yyyy') + ' to ' + FORMAT(@FyEnd, 'dd/MM/yyyy') + '.' AS error;
            RETURN;
        END
        IF @Id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dbo.Vouchers WHERE id = @Id AND company_id = @CompanyId)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Voucher not found.' AS error;
            RETURN;
        END

        IF @NumberMethod = 'Manual' AND @ManualNo IS NULL AND @Id IS NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Voucher No. is required (this voucher type is numbered manually).' AS error;
            RETURN;
        END
        IF @UseManualNo = 1 AND CHARINDEX('-', @ManualNo) > 0
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Voucher No. cannot contain "-".' AS error;
            RETURN;
        END
        -- A typed number is unique inside this type's own series.
        DECLARE @ManualFullNo NVARCHAR(40) = CASE WHEN @UseManualNo = 1 THEN @ManualNo END;
        IF @UseManualNo = 1 AND EXISTS (SELECT 1 FROM dbo.Vouchers WHERE company_id = @CompanyId AND category = 'MANUAL'
                                         AND voucher_type = @SeriesType AND ISNULL(voucher_type_name, '') = ISNULL(@SeriesName, '')
                                         AND voucher_no = @ManualFullNo AND (@Id IS NULL OR id <> @Id))
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Voucher No. ' + @ManualNo + ' already exists for this voucher type.' AS error;
            RETURN;
        END

        DECLARE @TotalDebit DECIMAL(16,2), @TotalCredit DECIMAL(16,2);
        SELECT @TotalDebit = SUM(ISNULL(j.debit, 0)), @TotalCredit = SUM(ISNULL(j.credit, 0))
        FROM OPENJSON(@LinesJson) WITH (debit DECIMAL(16,2) '$.debit', credit DECIMAL(16,2) '$.credit') j;

        IF ROUND(ISNULL(@TotalDebit, 0), 2) <> ROUND(ISNULL(@TotalCredit, 0), 2)
        BEGIN
            SELECT NULL AS id, 'Error' AS status,
                   'Voucher is unbalanced: total debit ' + CAST(ROUND(ISNULL(@TotalDebit,0), 2) AS NVARCHAR(30)) + ' does not equal total credit ' + CAST(ROUND(ISNULL(@TotalCredit,0), 2) AS NVARCHAR(30)) + '.' AS error;
            RETURN;
        END
        IF ROUND(ISNULL(@TotalDebit, 0), 2) = 0
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Voucher total cannot be zero.' AS error;
            RETURN;
        END

        DECLARE @MissingLineNo INT, @BadLedgerLineNo INT;
        SELECT TOP 1 @MissingLineNo = j.rn
        FROM (SELECT CAST([key] AS INT) AS rn, TRY_CAST(JSON_VALUE([value], '$.ledger_id') AS INT) AS ledger_id FROM OPENJSON(@LinesJson)) j
        WHERE j.ledger_id IS NULL
        ORDER BY j.rn;
        IF @MissingLineNo IS NOT NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status,
                   'Line ' + CAST((@MissingLineNo + 1) AS NVARCHAR(10)) + ' is missing a ledger — check that all system ledgers exist.' AS error;
            RETURN;
        END

        SELECT TOP 1 @BadLedgerLineNo = j.rn
        FROM (SELECT CAST([key] AS INT) AS rn, TRY_CAST(JSON_VALUE([value], '$.ledger_id') AS INT) AS ledger_id FROM OPENJSON(@LinesJson)) j
        WHERE j.ledger_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dbo.Ledgers WHERE id = j.ledger_id)
        ORDER BY j.rn;
        IF @BadLedgerLineNo IS NOT NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status,
                   'Line ' + CAST((@BadLedgerLineNo + 1) AS NVARCHAR(10)) + ' references a ledger that doesn''t exist.' AS error;
            RETURN;
        END

        -- Resolved lines_json - same shape _validate_and_resolve_voucher_body
        -- builds (ledger_id, ledger_name, debit, credit), each ledger_name
        -- looked up fresh so a later ledger rename never goes stale here.
        DECLARE @ResolvedLinesJson NVARCHAR(MAX);
        SELECT @ResolvedLinesJson = (
            SELECT j.ledger_id, l.name AS ledger_name, ISNULL(j.debit, 0) AS debit, ISNULL(j.credit, 0) AS credit,
                   JSON_QUERY(j.bill_allocations) AS bill_allocations   -- bill-wise allocation (Against Invoice / New Invoice / On Account)
            FROM OPENJSON(@LinesJson) WITH (ledger_id INT '$.ledger_id', debit DECIMAL(16,2) '$.debit', credit DECIMAL(16,2) '$.credit',
                                            bill_allocations NVARCHAR(MAX) '$.bill_allocations' AS JSON) j
            INNER JOIN dbo.Ledgers l ON l.id = j.ledger_id
            FOR JSON PATH
        );

        BEGIN TRY
            BEGIN TRAN;

            DECLARE @ResultId INT;
            IF @Id IS NOT NULL
            BEGIN
                -- Moved to another series on edit (e.g. Receipt -> Payment) with
                -- automatic numbering: it takes that series' next number, so it
                -- never clashes with a number already used there.
                -- (Set in the same UPDATE as the type, so the row never sits in
                -- the old series with the new series' number.)
                DECLARE @MovedNo NVARCHAR(40) = NULL;
                IF @UseManualNo = 0 AND EXISTS (SELECT 1 FROM dbo.Vouchers WHERE id = @Id
                        AND (voucher_type <> @SeriesType OR ISNULL(voucher_type_name, '') <> ISNULL(@SeriesName, '')))
                    SET @MovedNo = CAST((SELECT ISNULL(MAX(TRY_CAST(v2.voucher_no AS INT)), 0) + 1 FROM dbo.Vouchers v2
                                         WHERE v2.company_id = @CompanyId AND v2.category = 'MANUAL' AND v2.voucher_type = @SeriesType
                                           AND ISNULL(v2.voucher_type_name, '') = ISNULL(@SeriesName, '')) AS NVARCHAR(10));
                UPDATE dbo.Vouchers
                SET voucher_no = ISNULL(@MovedNo, voucher_no),
                    branch_name = ISNULL(@BranchName, branch_name), voucher_type = ISNULL(@VoucherType, 'Journal'), voucher_type_name = @VoucherTypeName, voucher_date = @VoucherDate,
                    narration = @Narration, total_debit = @TotalDebit, total_credit = @TotalCredit, lines_json = @ResolvedLinesJson
                WHERE id = @Id;
                -- Manual / Override types may change the number on edit too.
                IF @UseManualNo = 1
                    UPDATE dbo.Vouchers SET voucher_no = @ManualFullNo WHERE id = @Id;
                SET @ResultId = @Id;
            END
            ELSE
            BEGIN
                -- Highest existing number of this type's series + 1 (not count + 1) -
                -- a deleted voucher leaves a gap, and count + 1 then reuses a live number.
                DECLARE @NextNum INT = (SELECT ISNULL(MAX(TRY_CAST(voucher_no AS INT)), 0) + 1
                    FROM dbo.Vouchers WHERE company_id = @CompanyId AND category = 'MANUAL' AND voucher_type = @SeriesType
                      AND ISNULL(voucher_type_name, '') = ISNULL(@SeriesName, ''));
                INSERT INTO dbo.Vouchers
                    (company_id, branch_name, voucher_type, voucher_type_name, voucher_date, narration, category, voucher_no,
                     total_debit, total_credit, lines_json, created_at, updated_at)
                VALUES
                    (@CompanyId, ISNULL(@BranchName, 'Chennai Branch'), ISNULL(@VoucherType, 'Journal'), @VoucherTypeName, @VoucherDate, @Narration, 'MANUAL',
                     CASE WHEN @UseManualNo = 1 THEN @ManualFullNo ELSE CAST(@NextNum AS NVARCHAR(10)) END,
                     @TotalDebit, @TotalCredit, @ResolvedLinesJson, SYSUTCDATETIME(), SYSUTCDATETIME());
                SET @ResultId = SCOPE_IDENTITY();
            END

            COMMIT TRAN;

            SELECT id, voucher_no, branch_name, voucher_type, voucher_type_name, voucher_date, narration,
                   total_debit, total_credit, lines_json, 'Success' AS status
            FROM dbo.Vouchers WHERE id = @ResultId;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END
END
GO

-- ==========================================================================
-- dbo.sp_CancellationTicket
-- Module   : Cancellation_AL_Tickets + Cancellation_Al_TicketLines
--            (Cancellation screen - ticket-entry.html?cancellation_new=1)
-- Actions  : LIST, GET_HEADER, GET_LINES (saved Cancellation view screen),
--            SAVE (create), UPDATE (edit the same fields that were
--            editable at creation)
-- JV       : since 2026-10-07 SAVE/UPDATE also post this cancellation's
--            OWN separate Journal Voucher (dbo.JournalVoucher,
--            category 'AIRLINE_CANCELLATION', ALC-1, ALC-2, ...,
--            source_cancellation_ticket_id) inside the same transaction as
--            the header/lines write. The JV line arithmetic (JV-1/JV-2/JV-3,
--            incl. the FOP leg) is computed in Python
--            (views._compute_cancellation_jv_lines/
--            _cancellation_fop_payment_lines) and only the totals +
--            narration are passed in here; both actions refuse to write
--            anything at all if those totals are missing or Debit <> Credit.
--            The original booking's own JournalVoucher is never touched.
-- Replaces : the (previously unwired) Cancel button's save flow in
--            page-ticket-entry.js / a new views.cancellation_ticket_create
-- ==========================================================================
CREATE OR ALTER PROCEDURE dbo.sp_CancellationTicket
    @Action                  NVARCHAR(50),
    @Id                      INT             = NULL,
    @CompanyId               INT             = NULL,
    @OriginalTicketId        INT             = NULL,
    @CustomerName            NVARCHAR(150)   = NULL,
    @SupplierName            NVARCHAR(150)   = NULL,
    @BranchName              NVARCHAR(100)   = NULL,
    @InvoiceNumber           NVARCHAR(20)    = NULL,
    @InvoiceDate             DATE            = NULL,
    @InvoiceType             NVARCHAR(100)   = NULL,
    @BookingMode             NVARCHAR(20)    = NULL,
    @BookingType             NVARCHAR(50)    = NULL,
    @BookingStatus           NVARCHAR(20)    = NULL,
    @TravelType              NVARCHAR(20)    = NULL,
    @UserName                NVARCHAR(100)   = NULL,
    @Currency                NVARCHAR(5)     = NULL,
    @Roe                     DECIMAL(10,4)   = NULL,
    @BookingGivenBy          NVARCHAR(25)    = NULL,
    @CancellationReference   NVARCHAR(30)    = NULL,
    @ParentPnr               NVARCHAR(30)    = NULL,   -- direct Cancellation: the Parent PNR as sent (no booking to link)
    @CancellationRefDate     DATE            = NULL,
    @AirlinePnr              NVARCHAR(13)    = NULL,
    @GdsPnr                  NVARCHAR(13)    = NULL,
    @OfficeId                NVARCHAR(30)    = NULL,
    @PaymentMode             NVARCHAR(20)    = NULL,
    @PaymentGatewayRef       NVARCHAR(60)    = NULL,
    @AirlineCategory         NVARCHAR(5)     = NULL,
    @LinesJson               NVARCHAR(MAX)   = NULL,
    @JvNarration             NVARCHAR(250)   = NULL,
    @JvTotalDebit            DECIMAL(16,2)   = NULL,
    @JvTotalCredit           DECIMAL(16,2)   = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'LIST'
    BEGIN
        -- One row per Cancellation_Al_TicketLines line, flat shape matching
        -- what the Find modal's generic results table already expects
        -- (same convention as sp_RescheduleTicket's own LIST action) - used
        -- so Cancellation's own "Find" popup can show only cancelled
        -- tickets instead of the full tickets list (2026-10-06).
        SELECT cl.id, ct.id AS cancellation_ticket_id,
               ct.invoice_number, ct.cancellation_reference AS booking_reference,
               ct.airline_pnr, ct.gds_pnr, cl.ticket_no, cl.passenger_name,
               cl.total_billed
        FROM dbo.Cancellation_Al_TicketLines cl
        INNER JOIN dbo.Cancellation_AL_Tickets ct ON ct.id = cl.cancellation_ticket_id
        WHERE ct.company_id = @CompanyId
        ORDER BY cl.id DESC;
        RETURN;
    END

    IF @Action = 'GET_HEADER'
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM dbo.Cancellation_AL_Tickets WHERE id = @Id AND company_id = @CompanyId)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Cancellation not found.' AS error;
            RETURN;
        END
        SELECT ct.id, ct.original_ticket_id, COALESCE(ct.parent_pnr, ot.booking_reference) AS parent_pnr,
               ct.invoice_number, ct.invoice_date, ct.invoice_type,
               ct.booking_mode, ct.booking_type, ct.booking_status, cust.name AS customer_name,
               ct.travel_type, ct.user_name, ct.currency, ct.roe, ct.booking_given_by,
               ct.cancellation_reference, ct.cancellation_ref_date, ct.airline_pnr, ct.gds_pnr,
               supp.name AS supplier_name, ct.office_id, ct.payment_mode, ct.payment_gateway_ref,
               ct.airline_category, ct.branch_name, ct.customer_ledger_id,
               jv.id AS voucher_id, jv.voucher_no, jv.total_debit AS jv_total_debit, jv.total_credit AS jv_total_credit,
               'Success' AS status
        FROM dbo.Cancellation_AL_Tickets ct
        INNER JOIN dbo.Ledgers cust ON cust.id = ct.customer_ledger_id
        LEFT JOIN dbo.Ledgers supp ON supp.id = ct.supplier_ledger_id
        LEFT JOIN dbo.JournalVoucher jv ON jv.source_cancellation_ticket_id = ct.id
        LEFT JOIN dbo.AL_Tickets ot ON ot.id = ct.original_ticket_id
        WHERE ct.id = @Id AND ct.company_id = @CompanyId;
        RETURN;
    END

    IF @Action = 'GET_LINES'
    BEGIN
        SELECT cl.id, cl.original_ticket_line_id, cl.reschedule_line_id, cl.airline_code, cl.airline_name, cl.airline_category,
               cl.flight_no, cl.ticket_no, cl.passenger_name, cl.pax_type, cl.sector, cl.travel_date,
               cl.cabin, cl.travel_class, cl.fare_type,
               cl.basic_fare, cl.yq, cl.yr, cl.k3_tax, cl.tax_others, cl.seat, cl.meal, cl.baggage, cl.other_ssr,
               cl.disc_on, cl.disc_type, cl.disc_value, cl.tds_per, cl.pg_charges, cl.pg_charges_percentage,
               cl.markup, cl.addl_markup, cl.ssr_markup, cl.service_fee, cl.addl_service_fee, cl.ssr_service_fee, cl.gst_pct,
               cl.supp_comm_on, cl.supp_comm_type, cl.supp_comm_value, cl.supp_tds_per,
               cl.supp_markup, cl.supp_addl_markup, cl.supp_service_fee, cl.supp_addl_service_fee, cl.supp_gst_pct,
               cl.supplier_penalty, cl.cancellation_penalty, cl.agent_penalty,
               cl.cust_markup_reversal, cl.cust_addl_markup_reversal, cl.cust_ssr_markup_reversal,
               cl.supp_markup_reversal, cl.supp_addl_markup_reversal, cl.supp_ssr_markup_reversal,
               cl.tds_amount_override, cl.supp_tds_amount_override,
               cl.total_billed, cl.status, cl.office_id, cl.fop, cl.card_number,
               cl.supplier_ledger_id, supp.name AS supplier_name
        FROM dbo.Cancellation_Al_TicketLines cl
        LEFT JOIN dbo.Ledgers supp ON supp.id = cl.supplier_ledger_id
        WHERE cl.cancellation_ticket_id = @Id
        ORDER BY cl.id;
        RETURN;
    END

    IF @Action = 'SAVE'
    BEGIN
        DECLARE @CustLedgerId INT, @SuppLedgerId INT;
        SELECT @CustLedgerId = id FROM dbo.Ledgers WHERE company_id = @CompanyId AND name = @CustomerName AND ledger_category = 'DEBTOR';
        IF @CustLedgerId IS NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, '"' + ISNULL(@CustomerName, '') + '" is not a real customer ledger (Sundry Debtors).' AS error;
            RETURN;
        END
        IF @SupplierName IS NOT NULL
        BEGIN
            SELECT @SuppLedgerId = id FROM dbo.Ledgers WHERE company_id = @CompanyId AND name = @SupplierName AND ledger_category = 'CREDITOR';
            IF @SuppLedgerId IS NULL
            BEGIN
                SELECT NULL AS id, 'Error' AS status, '"' + @SupplierName + '" is not a real supplier ledger (Sundry Creditors).' AS error;
                RETURN;
            END
        END

        -- @OriginalTicketId NULL = a direct Cancellation: the ticket was never
        -- booked in this software, only its Parent PNR (@ParentPnr) is kept.
        IF @OriginalTicketId IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM dbo.AL_Tickets WHERE id = @OriginalTicketId AND company_id = @CompanyId)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Original ticket not found.' AS error;
            RETURN;
        END

        IF EXISTS (SELECT 1 FROM dbo.Cancellation_AL_Tickets WHERE company_id = @CompanyId AND invoice_number = @InvoiceNumber)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Invoice Number "' + @InvoiceNumber + '" already exists.' AS error;
            RETURN;
        END
        IF EXISTS (SELECT 1 FROM dbo.Cancellation_AL_Tickets WHERE company_id = @CompanyId AND cancellation_reference = @CancellationReference)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Cancellation Reference "' + @CancellationReference + '" already exists.' AS error;
            RETURN;
        END

        IF EXISTS (
            SELECT ticket_no FROM OPENJSON(@LinesJson) WITH (ticket_no NVARCHAR(30) '$.ticket_no')
            GROUP BY ticket_no HAVING COUNT(*) > 1
        )
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Duplicate Ticket Number within this submission.' AS error;
            RETURN;
        END

        DECLARE @DupTicketNo NVARCHAR(30);
        SELECT TOP 1 @DupTicketNo = cl.ticket_no FROM dbo.Cancellation_Al_TicketLines cl
        INNER JOIN OPENJSON(@LinesJson) WITH (ticket_no NVARCHAR(30) '$.ticket_no') j ON j.ticket_no = cl.ticket_no;
        IF @DupTicketNo IS NOT NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Ticket Number "' + @DupTicketNo + '" already exists.' AS error;
            RETURN;
        END

        -- Every line must reference a real original TicketLine belonging
        -- to this original ticket, and not already cancelled (the table's
        -- own UNIQUE constraint on original_ticket_line_id would also
        -- catch this at INSERT time, but this gives a clean message first).
        DECLARE @BadOriginalTicketNo NVARCHAR(30);
        SELECT TOP 1 @BadOriginalTicketNo = j.ticket_no
        FROM OPENJSON(@LinesJson) WITH (original_ticket_line_id INT '$.original_ticket_line_id', ticket_no NVARCHAR(30) '$.ticket_no') j
        WHERE j.original_ticket_line_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM dbo.AL_TicketLines otl WHERE otl.id = j.original_ticket_line_id AND otl.ticket_id = @OriginalTicketId
        );
        IF @BadOriginalTicketNo IS NOT NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'One or more lines reference an original ticket line that doesn''t belong to this ticket.' AS error;
            RETURN;
        END

        -- Authoritative "already cancelled" check is the original line's
        -- own canceled flag (2026-10-06) - not just whether a
        -- Cancellation_Al_TicketLines row already references it, so this
        -- still catches a line flagged canceled by some other path too.
        -- The old existence check is kept alongside it (its own UNIQUE
        -- constraint on original_ticket_line_id would otherwise still
        -- raise a far less friendly raw constraint-violation error).
        DECLARE @AlreadyCancelled NVARCHAR(MAX);
        SELECT @AlreadyCancelled = STRING_AGG(otl.ticket_no, ', ') WITHIN GROUP (ORDER BY otl.ticket_no)
        FROM OPENJSON(@LinesJson) WITH (original_ticket_line_id INT '$.original_ticket_line_id') j
        INNER JOIN dbo.AL_TicketLines otl ON otl.id = j.original_ticket_line_id
        WHERE otl.canceled = 1
           OR EXISTS (SELECT 1 FROM dbo.Cancellation_Al_TicketLines existing WHERE existing.original_ticket_line_id = otl.id);
        IF @AlreadyCancelled IS NOT NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Ticket No. ' + @AlreadyCancelled + ' has already been cancelled.' AS error;
            RETURN;
        END

        -- Same check on the reschedule line itself, when this cancellation
        -- was raised against an already-rescheduled passenger
        -- (reschedule_line_id set) - a chained reschedule could otherwise
        -- be cancelled a second time via a different reschedule_line_id
        -- that still maps to the same true original line.
        DECLARE @AlreadyCancelledResched NVARCHAR(MAX);
        SELECT @AlreadyCancelledResched = STRING_AGG(rl.ticket_no, ', ') WITHIN GROUP (ORDER BY rl.ticket_no)
        FROM OPENJSON(@LinesJson) WITH (reschedule_line_id INT '$.reschedule_line_id') j
        INNER JOIN dbo.Rescheduled_Al_TicketLines rl ON rl.id = j.reschedule_line_id
        WHERE j.reschedule_line_id IS NOT NULL AND rl.canceled = 1;
        IF @AlreadyCancelledResched IS NOT NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Ticket No. ' + @AlreadyCancelledResched + ' has already been cancelled.' AS error;
            RETURN;
        END

        -- Cancellation Journal Voucher guard (2026-10-07) - defense in depth
        -- behind views.cancellation_ticket_create's own identical check:
        -- every saved Cancellation must carry a balanced JV, so nothing at
        -- all (header, lines, canceled flags, JV) is written otherwise.
        IF @JvTotalDebit IS NULL OR @JvTotalCredit IS NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Cancellation Journal Voucher totals are missing - nothing was saved.' AS error;
            RETURN;
        END
        IF ABS(@JvTotalDebit - @JvTotalCredit) > 0.01
        BEGIN
            SELECT NULL AS id, 'Error' AS status,
                   'Cancellation Journal Voucher does not balance (Debit ' + CAST(@JvTotalDebit AS NVARCHAR(30))
                   + ' <> Credit ' + CAST(@JvTotalCredit AS NVARCHAR(30)) + ') - nothing was saved.' AS error;
            RETURN;
        END

        BEGIN TRY
            BEGIN TRAN;

            INSERT INTO dbo.Cancellation_AL_Tickets
                (company_id, branch_name, original_ticket_id, parent_pnr, invoice_number, invoice_date, invoice_type, booking_mode, booking_type, booking_status,
                 customer_ledger_id, supplier_ledger_id, travel_type, user_name, currency, roe, booking_given_by,
                 cancellation_reference, cancellation_ref_date, airline_pnr, gds_pnr, office_id, payment_mode, payment_gateway_ref,
                 airline_category, created_at, updated_at)
            VALUES
                (@CompanyId, @BranchName, @OriginalTicketId, @ParentPnr, @InvoiceNumber, @InvoiceDate, @InvoiceType, ISNULL(@BookingMode, 'Manual'), @BookingType, @BookingStatus,
                 @CustLedgerId, @SuppLedgerId, @TravelType, @UserName, ISNULL(@Currency, 'INR'), ISNULL(@Roe, 1), @BookingGivenBy,
                 @CancellationReference, @CancellationRefDate, @AirlinePnr, @GdsPnr, @OfficeId, @PaymentMode, @PaymentGatewayRef,
                 @AirlineCategory, SYSUTCDATETIME(), SYSUTCDATETIME());
            DECLARE @ResultId INT = SCOPE_IDENTITY();

            INSERT INTO dbo.Cancellation_Al_TicketLines
                (cancellation_ticket_id, original_ticket_line_id, reschedule_line_id, airline_code, airline_name, airline_category, flight_no, ticket_no, passenger_name, pax_type,
                 sector, travel_date, cabin, travel_class, fare_type, basic_fare, yq, yr, k3_tax, tax_others, seat, meal,
                 baggage, other_ssr, disc_on, disc_type, disc_value, tds_per, pg_charges, pg_charges_percentage,
                 markup, addl_markup, ssr_markup, service_fee, addl_service_fee, ssr_service_fee, gst_pct, status,
                 office_id, fop, card_number, supp_comm_on, supp_comm_type, supp_comm_value, supp_tds_per,
                 supp_markup, supp_addl_markup, supp_service_fee, supp_addl_service_fee, supp_gst_pct,
                 supplier_penalty, cancellation_penalty, agent_penalty,
                 cust_markup_reversal, cust_addl_markup_reversal, cust_ssr_markup_reversal,
                 supp_markup_reversal, supp_addl_markup_reversal, supp_ssr_markup_reversal, total_billed,
                 tds_amount_override, supp_tds_amount_override,
                 supplier_ledger_id, created_at, updated_at)
            SELECT
                @ResultId, j.original_ticket_line_id, j.reschedule_line_id, j.airline_code, j.airline_name, j.airline_category, j.flight_no, j.ticket_no, j.passenger_name, j.pax_type,
                j.sector, j.travel_date, j.cabin, j.travel_class, j.fare_type, j.basic_fare, j.yq, j.yr, j.k3_tax, j.tax_others, j.seat, j.meal,
                j.baggage, j.other_ssr, j.disc_on, j.disc_type, j.disc_value, j.tds_per, j.pg_charges, j.pg_charges_percentage,
                j.markup, j.addl_markup, j.ssr_markup, j.service_fee, j.addl_service_fee, j.ssr_service_fee, j.gst_pct, ISNULL(j.status, 'ISSUED'),
                j.office_id, j.fop, j.card_number, j.supp_comm_on, j.supp_comm_type, j.supp_comm_value, j.supp_tds_per,
                j.supp_markup, j.supp_addl_markup, j.supp_service_fee, j.supp_addl_service_fee, j.supp_gst_pct,
                ISNULL(j.supplier_penalty, 0), ISNULL(j.cancellation_penalty, 0), ISNULL(j.agent_penalty, 0),
                ISNULL(j.cust_markup_reversal, 0), ISNULL(j.cust_addl_markup_reversal, 0), ISNULL(j.cust_ssr_markup_reversal, 0),
                ISNULL(j.supp_markup_reversal, 0), ISNULL(j.supp_addl_markup_reversal, 0), ISNULL(j.supp_ssr_markup_reversal, 0), j.total_billed,
                j.tds_amount_override, j.supp_tds_amount_override,
                (SELECT id FROM dbo.Ledgers WHERE company_id = @CompanyId AND name = j.supplier_name AND ledger_category = 'CREDITOR'),
                SYSUTCDATETIME(), SYSUTCDATETIME()
            FROM OPENJSON(@LinesJson) WITH (
                original_ticket_line_id INT '$.original_ticket_line_id',
                reschedule_line_id INT '$.reschedule_line_id',
                airline_code NVARCHAR(200) '$.airline_code', airline_name NVARCHAR(200) '$.airline_name',
                airline_category NVARCHAR(5) '$.airline_category', flight_no NVARCHAR(200) '$.flight_no',
                ticket_no NVARCHAR(30) '$.ticket_no', passenger_name NVARCHAR(50) '$.passenger_name',
                pax_type NVARCHAR(10) '$.pax_type', sector NVARCHAR(200) '$.sector', travel_date NVARCHAR(200) '$.travel_date',
                cabin NVARCHAR(200) '$.cabin', travel_class NVARCHAR(200) '$.travel_class', fare_type NVARCHAR(300) '$.fare_type',
                basic_fare DECIMAL(14,2) '$.basic_fare', yq DECIMAL(14,2) '$.yq', yr DECIMAL(14,2) '$.yr',
                k3_tax DECIMAL(14,2) '$.k3_tax', tax_others DECIMAL(14,2) '$.tax_others', seat DECIMAL(14,2) '$.seat',
                meal DECIMAL(14,2) '$.meal', baggage DECIMAL(14,2) '$.baggage', other_ssr DECIMAL(14,2) '$.other_ssr',
                disc_on NVARCHAR(20) '$.disc_on', disc_type NVARCHAR(12) '$.disc_type', disc_value DECIMAL(14,2) '$.disc_value',
                tds_per DECIMAL(5,2) '$.tds_per', pg_charges DECIMAL(14,2) '$.pg_charges', pg_charges_percentage DECIMAL(5,2) '$.pg_charges_percentage',
                markup DECIMAL(14,2) '$.markup', addl_markup DECIMAL(14,2) '$.addl_markup', ssr_markup DECIMAL(14,2) '$.ssr_markup',
                service_fee DECIMAL(14,2) '$.service_fee', addl_service_fee DECIMAL(14,2) '$.addl_service_fee',
                ssr_service_fee DECIMAL(14,2) '$.ssr_service_fee', gst_pct DECIMAL(5,2) '$.gst_pct', status NVARCHAR(15) '$.status',
                office_id NVARCHAR(30) '$.office_id', fop NVARCHAR(20) '$.fop', card_number NVARCHAR(40) '$.card_number',
                supp_comm_on NVARCHAR(20) '$.supp_comm_on', supp_comm_type NVARCHAR(12) '$.supp_comm_type',
                supp_comm_value DECIMAL(14,2) '$.supp_comm_value', supp_tds_per DECIMAL(5,2) '$.supp_tds_per',
                supp_markup DECIMAL(14,2) '$.supp_markup', supp_addl_markup DECIMAL(14,2) '$.supp_addl_markup',
                supp_service_fee DECIMAL(14,2) '$.supp_service_fee', supp_addl_service_fee DECIMAL(14,2) '$.supp_addl_service_fee',
                supp_gst_pct DECIMAL(5,2) '$.supp_gst_pct', total_billed DECIMAL(14,2) '$.total_billed',
                supplier_penalty DECIMAL(14,2) '$.supplier_penalty', cancellation_penalty DECIMAL(14,2) '$.cancellation_penalty',
                agent_penalty DECIMAL(14,2) '$.agent_penalty',
                cust_markup_reversal DECIMAL(14,2) '$.cust_markup_reversal',
                cust_addl_markup_reversal DECIMAL(14,2) '$.cust_addl_markup_reversal',
                cust_ssr_markup_reversal DECIMAL(14,2) '$.cust_ssr_markup_reversal',
                supp_markup_reversal DECIMAL(14,2) '$.supp_markup_reversal',
                supp_addl_markup_reversal DECIMAL(14,2) '$.supp_addl_markup_reversal',
                supp_ssr_markup_reversal DECIMAL(14,2) '$.supp_ssr_markup_reversal',
                tds_amount_override DECIMAL(14,2) '$.tds_amount_override',
                supp_tds_amount_override DECIMAL(14,2) '$.supp_tds_amount_override',
                supplier_name NVARCHAR(150) '$.supplier_name'
            ) AS j;

            -- Mark the ORIGINAL ticket line(s) cancelled - never deletes
            -- the row (record-keeping only), just flips the flag so it
            -- can't be cancelled again (checked above) and other screens
            -- can see its real status.
            UPDATE otl
            SET canceled = 1
            FROM dbo.AL_TicketLines otl
            INNER JOIN OPENJSON(@LinesJson) WITH (original_ticket_line_id INT '$.original_ticket_line_id') j
                ON j.original_ticket_line_id = otl.id;

            -- Also mark the specific RESCHEDULE line cancelled, when this
            -- cancellation was raised against an already-rescheduled
            -- passenger (reschedule_line_id set) - independent of the
            -- original line's own flag just set above.
            UPDATE rl
            SET canceled = 1
            FROM dbo.Rescheduled_Al_TicketLines rl
            INNER JOIN OPENJSON(@LinesJson) WITH (reschedule_line_id INT '$.reschedule_line_id') j
                ON j.reschedule_line_id = rl.id
            WHERE j.reschedule_line_id IS NOT NULL;

            -- This cancellation's OWN Journal Voucher (2026-10-07) - one row
            -- per Cancellation_AL_Tickets row (a brand-new @ResultId every
            -- SAVE, so never a 2nd JV for the same cancellation), saved
            -- against the cancellation via source_cancellation_ticket_id.
            -- Totals cover the Main JV + the FOP leg (JV-2/JV-3) together.
            -- Same numbering style as sp_Ticket's/sp_RescheduleTicket's own
            -- JV insert, separate ALC- sequence.
            DECLARE @NextNumCx INT = (SELECT ISNULL(MAX(TRY_CAST(SUBSTRING(voucher_no, 5, 20) AS INT)), 0) + 1 FROM dbo.JournalVoucher WHERE company_id = @CompanyId AND category = 'AIRLINE_CANCELLATION' AND voucher_no LIKE 'ALC-%');
            INSERT INTO dbo.JournalVoucher
                (company_id, branch_name, voucher_type, voucher_date, narration, category, voucher_no,
                 source_cancellation_ticket_id, total_debit, total_credit, lines_json, created_at, updated_at)
            VALUES
                (@CompanyId, ISNULL(@BranchName, 'Chennai Branch'), 'Tax Invoice', @InvoiceDate, @JvNarration, 'AIRLINE_CANCELLATION',
                 'ALC-' + CAST(@NextNumCx AS NVARCHAR(10)), @ResultId, @JvTotalDebit, @JvTotalCredit, '[]', SYSUTCDATETIME(), SYSUTCDATETIME());

            COMMIT TRAN;

            DECLARE @LineIds NVARCHAR(MAX);
            SELECT @LineIds = STRING_AGG(CAST(id AS NVARCHAR(10)), ',') FROM dbo.Cancellation_Al_TicketLines WHERE cancellation_ticket_id = @ResultId;

            SELECT @ResultId AS id, @LineIds AS line_ids,
                   v.id AS voucher_id, v.voucher_no, 'Success' AS status
            FROM dbo.JournalVoucher v
            WHERE v.source_cancellation_ticket_id = @ResultId;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END

    -- Edits an already-saved Cancellation (2026-10-06) - the SAME fields
    -- that were editable at creation time (header: Invoice Date/Type,
    -- User Name, Payment Mode/Gateway Ref, Cancellation Reference/Ref
    -- Date; lines: Base Fare & Tax Components, Customer Discount, Supplier
    -- Commission, Markup, Service Fee). Passengers/original ticket link
    -- are NOT re-resolved here - @LinesJson keys each line by its own
    -- already-saved Cancellation_Al_TicketLines id, not original_ticket_
    -- line_id, since nothing about which lines exist is changing.
    IF @Action = 'UPDATE'
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM dbo.Cancellation_AL_Tickets WHERE id = @Id AND company_id = @CompanyId)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Cancellation not found.' AS error;
            RETURN;
        END
        IF @InvoiceNumber IS NOT NULL AND EXISTS (
            SELECT 1 FROM dbo.Cancellation_AL_Tickets WHERE company_id = @CompanyId AND invoice_number = @InvoiceNumber AND id <> @Id
        )
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Invoice Number "' + @InvoiceNumber + '" already exists.' AS error;
            RETURN;
        END
        IF @CancellationReference IS NOT NULL AND EXISTS (
            SELECT 1 FROM dbo.Cancellation_AL_Tickets WHERE company_id = @CompanyId AND cancellation_reference = @CancellationReference AND id <> @Id
        )
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Cancellation Reference "' + @CancellationReference + '" already exists.' AS error;
            RETURN;
        END

        -- Same balanced-JV guard as SAVE (2026-10-07) - the edit is
        -- rejected outright (nothing written) if the recomputed
        -- Cancellation JV is missing or doesn't balance.
        IF @JvTotalDebit IS NULL OR @JvTotalCredit IS NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Cancellation Journal Voucher totals are missing - nothing was saved.' AS error;
            RETURN;
        END
        IF ABS(@JvTotalDebit - @JvTotalCredit) > 0.01
        BEGIN
            SELECT NULL AS id, 'Error' AS status,
                   'Cancellation Journal Voucher does not balance (Debit ' + CAST(@JvTotalDebit AS NVARCHAR(30))
                   + ' <> Credit ' + CAST(@JvTotalCredit AS NVARCHAR(30)) + ') - nothing was saved.' AS error;
            RETURN;
        END

        BEGIN TRY
            BEGIN TRAN;

            UPDATE dbo.Cancellation_AL_Tickets
            SET invoice_number = ISNULL(@InvoiceNumber, invoice_number),
                invoice_date = ISNULL(@InvoiceDate, invoice_date),
                invoice_type = @InvoiceType,
                user_name = @UserName,
                payment_mode = @PaymentMode,
                payment_gateway_ref = @PaymentGatewayRef,
                cancellation_reference = ISNULL(@CancellationReference, cancellation_reference),
                cancellation_ref_date = ISNULL(@CancellationRefDate, cancellation_ref_date),
                updated_at = SYSUTCDATETIME()
            WHERE id = @Id;

            UPDATE cl
            SET basic_fare = j.basic_fare, yq = j.yq, yr = j.yr, k3_tax = j.k3_tax, tax_others = j.tax_others,
                seat = j.seat, meal = j.meal, baggage = j.baggage, other_ssr = j.other_ssr,
                disc_on = j.disc_on, disc_type = j.disc_type, disc_value = j.disc_value, tds_per = j.tds_per,
                markup = j.markup, addl_markup = j.addl_markup, service_fee = j.service_fee, addl_service_fee = j.addl_service_fee,
                supp_comm_on = j.supp_comm_on, supp_comm_type = j.supp_comm_type, supp_comm_value = j.supp_comm_value, supp_tds_per = j.supp_tds_per,
                supp_markup = j.supp_markup, supp_addl_markup = j.supp_addl_markup,
                supp_service_fee = j.supp_service_fee, supp_addl_service_fee = j.supp_addl_service_fee,
                supplier_penalty = ISNULL(j.supplier_penalty, 0), cancellation_penalty = ISNULL(j.cancellation_penalty, 0),
                agent_penalty = ISNULL(j.agent_penalty, 0),
                cust_markup_reversal = ISNULL(j.cust_markup_reversal, 0),
                cust_addl_markup_reversal = ISNULL(j.cust_addl_markup_reversal, 0),
                cust_ssr_markup_reversal = ISNULL(j.cust_ssr_markup_reversal, 0),
                supp_markup_reversal = ISNULL(j.supp_markup_reversal, 0),
                supp_addl_markup_reversal = ISNULL(j.supp_addl_markup_reversal, 0),
                supp_ssr_markup_reversal = ISNULL(j.supp_ssr_markup_reversal, 0),
                updated_at = SYSUTCDATETIME()
            FROM dbo.Cancellation_Al_TicketLines cl
            INNER JOIN OPENJSON(@LinesJson) WITH (
                id INT '$.id',
                basic_fare DECIMAL(14,2) '$.basic_fare', yq DECIMAL(14,2) '$.yq', yr DECIMAL(14,2) '$.yr',
                k3_tax DECIMAL(14,2) '$.k3_tax', tax_others DECIMAL(14,2) '$.tax_others', seat DECIMAL(14,2) '$.seat',
                meal DECIMAL(14,2) '$.meal', baggage DECIMAL(14,2) '$.baggage', other_ssr DECIMAL(14,2) '$.other_ssr',
                disc_on NVARCHAR(20) '$.disc_on', disc_type NVARCHAR(12) '$.disc_type', disc_value DECIMAL(14,2) '$.disc_value',
                tds_per DECIMAL(5,2) '$.tds_per',
                markup DECIMAL(14,2) '$.markup', addl_markup DECIMAL(14,2) '$.addl_markup',
                service_fee DECIMAL(14,2) '$.service_fee', addl_service_fee DECIMAL(14,2) '$.addl_service_fee',
                supp_comm_on NVARCHAR(20) '$.supp_comm_on', supp_comm_type NVARCHAR(12) '$.supp_comm_type',
                supp_comm_value DECIMAL(14,2) '$.supp_comm_value', supp_tds_per DECIMAL(5,2) '$.supp_tds_per',
                supp_markup DECIMAL(14,2) '$.supp_markup', supp_addl_markup DECIMAL(14,2) '$.supp_addl_markup',
                supp_service_fee DECIMAL(14,2) '$.supp_service_fee', supp_addl_service_fee DECIMAL(14,2) '$.supp_addl_service_fee',
                supplier_penalty DECIMAL(14,2) '$.supplier_penalty', cancellation_penalty DECIMAL(14,2) '$.cancellation_penalty',
                agent_penalty DECIMAL(14,2) '$.agent_penalty',
                cust_markup_reversal DECIMAL(14,2) '$.cust_markup_reversal',
                cust_addl_markup_reversal DECIMAL(14,2) '$.cust_addl_markup_reversal',
                cust_ssr_markup_reversal DECIMAL(14,2) '$.cust_ssr_markup_reversal',
                supp_markup_reversal DECIMAL(14,2) '$.supp_markup_reversal',
                supp_addl_markup_reversal DECIMAL(14,2) '$.supp_addl_markup_reversal',
                supp_ssr_markup_reversal DECIMAL(14,2) '$.supp_ssr_markup_reversal'
            ) j ON j.id = cl.id
            WHERE cl.cancellation_ticket_id = @Id;

            -- Re-post this cancellation's own Journal Voucher in place with
            -- the recomputed totals (never a 2nd row for the same
            -- cancellation). A cancellation saved before the JV feature
            -- existed (2026-10-07) has no row yet - it gets its first one
            -- here, on its first edit.
            DECLARE @CxInvoiceDate DATE, @CxBranchName NVARCHAR(100);
            SELECT @CxInvoiceDate = invoice_date, @CxBranchName = branch_name FROM dbo.Cancellation_AL_Tickets WHERE id = @Id;
            IF EXISTS (SELECT 1 FROM dbo.JournalVoucher WHERE source_cancellation_ticket_id = @Id)
                UPDATE dbo.JournalVoucher
                SET voucher_date = @CxInvoiceDate, narration = @JvNarration,
                    total_debit = @JvTotalDebit, total_credit = @JvTotalCredit,
                    updated_at = SYSUTCDATETIME()
                WHERE source_cancellation_ticket_id = @Id;
            ELSE
            BEGIN
                DECLARE @NextNumCxU INT = (SELECT ISNULL(MAX(TRY_CAST(SUBSTRING(voucher_no, 5, 20) AS INT)), 0) + 1 FROM dbo.JournalVoucher WHERE company_id = @CompanyId AND category = 'AIRLINE_CANCELLATION' AND voucher_no LIKE 'ALC-%');
                INSERT INTO dbo.JournalVoucher
                    (company_id, branch_name, voucher_type, voucher_date, narration, category, voucher_no,
                     source_cancellation_ticket_id, total_debit, total_credit, lines_json, created_at, updated_at)
                VALUES
                    (@CompanyId, ISNULL(@CxBranchName, 'Chennai Branch'), 'Tax Invoice', @CxInvoiceDate, @JvNarration, 'AIRLINE_CANCELLATION',
                     'ALC-' + CAST(@NextNumCxU AS NVARCHAR(10)), @Id, @JvTotalDebit, @JvTotalCredit, '[]', SYSUTCDATETIME(), SYSUTCDATETIME());
            END

            COMMIT TRAN;
            SELECT @Id AS id, v.id AS voucher_id, v.voucher_no, 'Success' AS status
            FROM dbo.JournalVoucher v
            WHERE v.source_cancellation_ticket_id = @Id;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END
END
GO

-- ==========================================================================
-- dbo.sp_AppUser
-- Module   : User Management (Control Panel > User Management)
-- Actions  : LIST, SAVE (upsert by id), DELETE
-- Replaces : views.app_user_list / app_user_save / app_user_delete's ORM code
-- Note     : no login/session system exists yet - this table only stores
--            the user + is used by sp_UserMenuAccess for per-menu flags.
-- ==========================================================================
CREATE OR ALTER PROCEDURE dbo.sp_AppUser
    @Action         NVARCHAR(50),
    @Id             INT             = NULL,
    @FullName       NVARCHAR(150)   = NULL,
    @Email          NVARCHAR(200)   = NULL,
    @Role           NVARCHAR(50)    = NULL,
    @BranchName     NVARCHAR(100)   = NULL,
    @IsSuperAdmin   BIT             = NULL,
    @IsActive       BIT             = NULL,
    @PasswordHash   NVARCHAR(256)   = NULL
AS
BEGIN
    SET NOCOUNT ON;

    -- Login lookup (views.auth_login) - the only action that returns
    -- password_hash to a caller that actually uses it.
    IF @Action = 'GET_BY_EMAIL'
    BEGIN
        SELECT * FROM dbo.AppUsers WHERE email = @Email;
        RETURN;
    END

    IF @Action = 'LIST'
    BEGIN
        SELECT u.*,
               (SELECT COUNT(*) FROM dbo.UserMenuAccess uma WHERE uma.user_id = u.id AND uma.can_view = 1) AS menu_count
        FROM dbo.AppUsers u
        WHERE @Id IS NULL OR u.id = @Id
        ORDER BY u.full_name;
        RETURN;
    END

    IF @Action = 'SAVE'
    BEGIN
        IF @FullName IS NULL OR LTRIM(RTRIM(@FullName)) = ''
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'full_name is required' AS error;
            RETURN;
        END
        IF @Email IS NULL OR LTRIM(RTRIM(@Email)) = ''
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'email is required' AS error;
            RETURN;
        END
        IF EXISTS (SELECT 1 FROM dbo.AppUsers WHERE email = @Email AND (@Id IS NULL OR id <> @Id))
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'A user with email "' + @Email + '" already exists.' AS error;
            RETURN;
        END
        -- Demoting/deactivating the last remaining Super Admin would lock
        -- everyone out of User Management - block it the same way DELETE
        -- below does.
        IF @Id IS NOT NULL AND (@IsSuperAdmin = 0 OR @IsActive = 0)
           AND EXISTS (SELECT 1 FROM dbo.AppUsers WHERE id = @Id AND is_super_admin = 1)
           AND (SELECT COUNT(*) FROM dbo.AppUsers WHERE is_super_admin = 1 AND is_active = 1) <= 1
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'At least one active Super Admin must remain.' AS error;
            RETURN;
        END

        SET @Role = ISNULL(NULLIF(@Role, ''), 'User');
        SET @IsSuperAdmin = ISNULL(@IsSuperAdmin, 0);
        SET @IsActive = ISNULL(@IsActive, 1);

        BEGIN TRY
            BEGIN TRAN;

            DECLARE @ResultId INT;
            DECLARE @WasCreated BIT = 0;

            IF @Id IS NOT NULL AND EXISTS (SELECT 1 FROM dbo.AppUsers WHERE id = @Id)
            BEGIN
                -- A blank password on edit means "keep the current one".
                UPDATE dbo.AppUsers
                SET full_name = @FullName, email = @Email, role = @Role, branch_name = @BranchName,
                    is_super_admin = @IsSuperAdmin, is_active = @IsActive,
                    password_hash = ISNULL(@PasswordHash, password_hash), updated_at = SYSUTCDATETIME()
                WHERE id = @Id;
                SET @ResultId = @Id;
            END
            ELSE
            BEGIN
                INSERT INTO dbo.AppUsers (full_name, email, role, branch_name, is_super_admin, is_active, password_hash, created_at, updated_at)
                VALUES (@FullName, @Email, @Role, @BranchName, @IsSuperAdmin, @IsActive, @PasswordHash, SYSUTCDATETIME(), SYSUTCDATETIME());
                SET @ResultId = SCOPE_IDENTITY();
                SET @WasCreated = 1;
            END

            COMMIT TRAN;

            SELECT *, @WasCreated AS was_created, 'Success' AS status
            FROM dbo.AppUsers WHERE id = @ResultId;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END

    IF @Action = 'DELETE'
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM dbo.AppUsers WHERE id = @Id)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'User not found.' AS error;
            RETURN;
        END
        IF EXISTS (SELECT 1 FROM dbo.AppUsers WHERE id = @Id AND is_super_admin = 1)
           AND (SELECT COUNT(*) FROM dbo.AppUsers WHERE is_super_admin = 1 AND is_active = 1) <= 1
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'At least one active Super Admin must remain.' AS error;
            RETURN;
        END

        BEGIN TRY
            BEGIN TRAN;
            -- Django's on_delete=CASCADE/SET_NULL is ORM-only - the real DB
            -- foreign keys have no ON DELETE action, so dependents go first.
            DELETE FROM dbo.UserMenuAccess WHERE user_id = @Id;
            UPDATE dbo.UserMenuAccess SET created_by_id = NULL WHERE created_by_id = @Id;
            DELETE FROM dbo.AppUsers WHERE id = @Id;
            COMMIT TRAN;
            SELECT @Id AS id, 'Success' AS status;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END
END
GO

-- ==========================================================================
-- dbo.sp_MenuMaster
-- Module   : User Management (menu picklist for the Access modal)
-- Actions  : LIST (active menus only, ordered for grouped rendering)
-- ==========================================================================
CREATE OR ALTER PROCEDURE dbo.sp_MenuMaster
    @Action NVARCHAR(50)
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'LIST'
    BEGIN
        SELECT * FROM dbo.MenuMaster WHERE is_active = 1 ORDER BY module, sort_order;
        RETURN;
    END
END
GO

-- ==========================================================================
-- dbo.sp_UserMenuAccess
-- Module   : User Management (per-user Access modal)
-- Actions  : GET (every active menu for one user, LEFT JOINed with
--            whatever UserMenuAccess row already exists so unset menus
--            come back as all-false instead of being left out),
--            SAVE (one transaction, upserts every row from @AccessJson -
--            a JSON array of {menu_key, can_view, can_add, can_edit,
--            can_delete, can_print, can_export})
-- ==========================================================================
CREATE OR ALTER PROCEDURE dbo.sp_UserMenuAccess
    @Action      NVARCHAR(50),
    @UserId      INT             = NULL,
    @CreatedBy   INT             = NULL,
    @AccessJson  NVARCHAR(MAX)   = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'GET'
    BEGIN
        IF @UserId IS NULL OR NOT EXISTS (SELECT 1 FROM dbo.AppUsers WHERE id = @UserId)
        BEGIN
            SELECT NULL AS menu_key, 'Error' AS status, 'User not found.' AS error;
            RETURN;
        END

        SELECT
            mm.menu_key, mm.title, mm.parent_key, mm.module, mm.sort_order,
            ISNULL(uma.can_view, 0) AS can_view, ISNULL(uma.can_add, 0) AS can_add,
            ISNULL(uma.can_edit, 0) AS can_edit, ISNULL(uma.can_delete, 0) AS can_delete,
            ISNULL(uma.can_print, 0) AS can_print, ISNULL(uma.can_export, 0) AS can_export
        FROM dbo.MenuMaster mm
        LEFT JOIN dbo.UserMenuAccess uma ON uma.menu_key = mm.menu_key AND uma.user_id = @UserId
        WHERE mm.is_active = 1
        ORDER BY mm.module, mm.sort_order;
        RETURN;
    END

    IF @Action = 'SAVE'
    BEGIN
        IF @UserId IS NULL OR NOT EXISTS (SELECT 1 FROM dbo.AppUsers WHERE id = @UserId)
        BEGIN
            SELECT NULL AS menu_key, 'Error' AS status, 'User not found.' AS error;
            RETURN;
        END

        BEGIN TRY
            BEGIN TRAN;

            MERGE dbo.UserMenuAccess AS target
            USING (
                SELECT menu_key, can_view, can_add, can_edit, can_delete, ISNULL(can_print, 0) AS can_print, ISNULL(can_export, 0) AS can_export
                FROM OPENJSON(@AccessJson) WITH (
                    menu_key NVARCHAR(60) '$.menu_key',
                    can_view BIT '$.can_view',
                    can_add BIT '$.can_add',
                    can_edit BIT '$.can_edit',
                    can_delete BIT '$.can_delete',
                    can_print BIT '$.can_print',
                    can_export BIT '$.can_export'
                )
            ) AS src
            ON target.user_id = @UserId AND target.menu_key = src.menu_key
            WHEN MATCHED THEN
                UPDATE SET can_view = src.can_view, can_add = src.can_add, can_edit = src.can_edit,
                           can_delete = src.can_delete, can_print = src.can_print, can_export = src.can_export,
                           updated_at = SYSUTCDATETIME()
            WHEN NOT MATCHED THEN
                INSERT (user_id, menu_key, can_view, can_add, can_edit, can_delete, can_print, can_export, created_by_id, created_at, updated_at)
                VALUES (@UserId, src.menu_key, src.can_view, src.can_add, src.can_edit, src.can_delete, src.can_print, src.can_export, @CreatedBy, SYSUTCDATETIME(), SYSUTCDATETIME());

            COMMIT TRAN;
            SELECT @UserId AS user_id, 'Success' AS status;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS menu_key, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END
END
GO


-- ============================================================================
-- dbo.sp_SSRTicket - SSR Updation (trans-airline-ssr.html). Header + lines +
-- its own Journal Voucher (category AIRLINE_SSR, ALS-n) in one transaction.
-- The JV's ledger rows are recomputed live in Python (views._compute_ssr_jv_lines,
-- driven by Ledger Mapping) - only the totals/narration are stored here.
-- Actions: LIST, LIST_FOR_ORIGINAL_LINES, GET_HEADER, GET_LINES, SAVE (insert, or update when @Id set).
-- ============================================================================
CREATE OR ALTER PROCEDURE dbo.sp_SSRTicket
    @Action                    NVARCHAR(50),
    @Id                        INT             = NULL,
    @CompanyId                 INT             = NULL,
    @OriginalTicketId          INT             = NULL,
    @SourceRescheduleTicketId  INT             = NULL,
    @CustomerName              NVARCHAR(150)   = NULL,
    @BranchName                NVARCHAR(100)   = NULL,
    @InvoiceNumber             NVARCHAR(20)    = NULL,
    @InvoiceDate               DATE            = NULL,
    @InvoiceType               NVARCHAR(100)   = NULL,
    @TravelType                NVARCHAR(20)    = NULL,
    @UserName                  NVARCHAR(100)   = NULL,
    @Currency                  NVARCHAR(5)     = NULL,
    @Roe                       DECIMAL(10,4)   = NULL,
    @SsrReference              NVARCHAR(30)    = NULL,
    @SsrRefDate                DATE            = NULL,
    @AirlinePnr                NVARCHAR(13)    = NULL,
    @GdsPnr                    NVARCHAR(13)    = NULL,
    @PaymentMode               NVARCHAR(20)    = NULL,
    @PaymentGatewayRef         NVARCHAR(60)    = NULL,
    @BookingMode               NVARCHAR(20)    = NULL,
    @ParentPnr                 NVARCHAR(30)    = NULL,   -- direct SSR (no booking here): the Parent PNR it was pushed with   -- 'Auto Push' from ticket_import; NULL = Manual (the screen)
    @LinesJson                 NVARCHAR(MAX)   = NULL,
    @JvNarration               NVARCHAR(250)   = NULL,
    @JvTotalDebit              DECIMAL(16,2)   = NULL,
    @JvTotalCredit             DECIMAL(16,2)   = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'LIST'
    BEGIN
        -- One row per SSR line - the SSR page's Find popup.
        SELECT sl.id, st.id AS ssr_ticket_id, st.invoice_number, st.invoice_date,
               st.ssr_reference AS booking_reference, st.airline_pnr, st.gds_pnr,
               cust.name AS customer_name, sl.ticket_no, sl.passenger_name, sl.sector,
               sl.ssr_items, sl.total_billed
        FROM dbo.SSR_AL_TicketLines sl
        INNER JOIN dbo.SSR_AL_Tickets st ON st.id = sl.ssr_ticket_id
        INNER JOIN dbo.Ledgers cust ON cust.id = st.customer_ledger_id
        WHERE st.company_id = @CompanyId
        ORDER BY st.id DESC, sl.id;
        RETURN;
    END

    IF @Action = 'LIST_FOR_ORIGINAL_LINES'
    BEGIN
        -- Every SSR line sold on the given booking passengers (@LinesJson =
        -- JSON array of AL_TicketLines ids) - Cancellation adds these SSR
        -- charges into its Return SSR figures (views.cancellation_fare_totals).
        SELECT sl.id, sl.original_ticket_line_id, sl.reschedule_line_id,
               sl.seat, sl.meal, sl.baggage, sl.other_ssr
        FROM dbo.SSR_AL_TicketLines sl
        INNER JOIN dbo.SSR_AL_Tickets st ON st.id = sl.ssr_ticket_id
        WHERE st.company_id = @CompanyId
          AND sl.original_ticket_line_id IN (SELECT CAST([value] AS INT) FROM OPENJSON(@LinesJson))
        ORDER BY sl.id;
        RETURN;
    END

    IF @Action = 'GET_HEADER'
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM dbo.SSR_AL_Tickets WHERE id = @Id AND company_id = @CompanyId)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'SSR Updation not found.' AS error;
            RETURN;
        END
        SELECT st.id, st.original_ticket_id, st.source_reschedule_ticket_id, st.invoice_number, st.invoice_date,
               st.invoice_type, st.booking_mode, st.booking_status, cust.name AS customer_name, st.customer_ledger_id,
               cust.state_name AS customer_state, st.travel_type, st.user_name, st.currency, st.roe,
               st.ssr_reference, st.ssr_ref_date, st.airline_pnr, st.gds_pnr, st.payment_mode, st.payment_gateway_ref, st.branch_name,
               st.parent_pnr,
               ot.invoice_number AS original_invoice_number, rt.invoice_number AS source_reschedule_invoice_number,
               jv.id AS voucher_id, jv.voucher_no, jv.total_debit AS jv_total_debit, jv.total_credit AS jv_total_credit,
               'Success' AS status
        FROM dbo.SSR_AL_Tickets st
        INNER JOIN dbo.Ledgers cust ON cust.id = st.customer_ledger_id
        LEFT JOIN dbo.AL_Tickets ot ON ot.id = st.original_ticket_id   -- NULL = direct SSR
        LEFT JOIN dbo.Rescheduled_Al_Ticket rt ON rt.id = st.source_reschedule_ticket_id
        LEFT JOIN dbo.JournalVoucher jv ON jv.source_ssr_ticket_id = st.id
        WHERE st.id = @Id AND st.company_id = @CompanyId;
        RETURN;
    END

    IF @Action = 'GET_LINES'
    BEGIN
        SELECT sl.id, sl.original_ticket_line_id, sl.reschedule_line_id, sl.ticket_no, sl.passenger_name,
               sl.pax_type, sl.airline_category, sl.sector, sl.office_id, sl.supplier_ledger_id,
               supp.name AS supplier_name, supp.state_name AS supplier_state, sl.fop, sl.card_number, sl.ssr_items, sl.ssr_ticket_numbers, sl.ssr_charges,
               sl.seat, sl.meal, sl.baggage, sl.other_ssr, sl.markup, sl.service_fee,
               sl.supp_markup, sl.supp_service_fee, sl.total_billed
        FROM dbo.SSR_AL_TicketLines sl
        INNER JOIN dbo.SSR_AL_Tickets st ON st.id = sl.ssr_ticket_id
        LEFT JOIN dbo.Ledgers supp ON supp.id = sl.supplier_ledger_id
        WHERE sl.ssr_ticket_id = @Id AND st.company_id = @CompanyId
        ORDER BY sl.id;
        RETURN;
    END

    IF @Action = 'SAVE'
    BEGIN
        DECLARE @CustLedgerId INT, @ResultId INT, @VoucherId INT, @VoucherNo NVARCHAR(20), @LineIds NVARCHAR(MAX);
        DECLARE @BadSupplier NVARCHAR(150), @BadLine NVARCHAR(30);

        IF @Id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dbo.SSR_AL_Tickets WHERE id = @Id AND company_id = @CompanyId)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'SSR Updation not found.' AS error;
            RETURN;
        END

        SELECT @CustLedgerId = id FROM dbo.Ledgers
        WHERE company_id = @CompanyId AND name = @CustomerName AND ledger_category = 'DEBTOR';
        IF @CustLedgerId IS NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, '"' + ISNULL(@CustomerName, '') + '" is not a real customer ledger (Sundry Debtors).' AS error;
            RETURN;
        END

        -- A direct SSR (Auto Push) has no booking here: it sits on a direct
        -- Reschedule (@SourceRescheduleTicketId) or only has its Parent PNR.
        IF (@OriginalTicketId IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dbo.AL_Tickets WHERE id = @OriginalTicketId AND company_id = @CompanyId))
           OR (@SourceRescheduleTicketId IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dbo.Rescheduled_Al_Ticket WHERE id = @SourceRescheduleTicketId AND company_id = @CompanyId))
           OR (@OriginalTicketId IS NULL AND @SourceRescheduleTicketId IS NULL AND NULLIF(LTRIM(RTRIM(@ParentPnr)), '') IS NULL)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'The original booking for this SSR was not found.' AS error;
            RETURN;
        END

        -- Invoice Number is shared across Booking / Reschedule / Cancellation / SSR.
        IF EXISTS (SELECT 1 FROM dbo.AL_Tickets WHERE company_id = @CompanyId AND invoice_number = @InvoiceNumber)
           OR EXISTS (SELECT 1 FROM dbo.Rescheduled_Al_Ticket WHERE company_id = @CompanyId AND invoice_number = @InvoiceNumber)
           OR EXISTS (SELECT 1 FROM dbo.Cancellation_AL_Tickets WHERE company_id = @CompanyId AND invoice_number = @InvoiceNumber)
           OR EXISTS (SELECT 1 FROM dbo.SSR_AL_Tickets WHERE company_id = @CompanyId AND invoice_number = @InvoiceNumber AND (@Id IS NULL OR id <> @Id))
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Invoice Number "' + @InvoiceNumber + '" already exists.' AS error;
            RETURN;
        END

        -- SSR Reference (S PNR) may repeat: one booking can have several SSR
        -- Updations (migration 0088). The Invoice Number above stays unique.

        -- Every line must be a passenger of the original booking (direct: of
        -- the direct Reschedule it sits on, or linked to nothing at all).
        SELECT TOP 1 @BadLine = ISNULL(j.ticket_no, '?')
        FROM OPENJSON(@LinesJson) WITH (original_ticket_line_id INT '$.original_ticket_line_id', reschedule_line_id INT '$.reschedule_line_id',
                                        ticket_no NVARCHAR(30) '$.ticket_no') j
        WHERE (@OriginalTicketId IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM dbo.AL_TicketLines tl WHERE tl.id = j.original_ticket_line_id AND tl.ticket_id = @OriginalTicketId))
           OR (@OriginalTicketId IS NULL AND j.original_ticket_line_id IS NOT NULL)
           OR (@OriginalTicketId IS NULL AND @SourceRescheduleTicketId IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM dbo.Rescheduled_Al_TicketLines rl
                               WHERE rl.id = j.reschedule_line_id AND rl.reschedule_ticket_id = @SourceRescheduleTicketId))
           OR (@OriginalTicketId IS NULL AND @SourceRescheduleTicketId IS NULL AND j.reschedule_line_id IS NOT NULL);
        IF @BadLine IS NOT NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Ticket No. ' + @BadLine + ' is not a passenger of the original booking.' AS error;
            RETURN;
        END

        SELECT TOP 1 @BadSupplier = j.supplier_name
        FROM OPENJSON(@LinesJson) WITH (supplier_name NVARCHAR(150) '$.supplier_name') j
        WHERE j.supplier_name IS NOT NULL AND j.supplier_name <> ''
          AND NOT EXISTS (SELECT 1 FROM dbo.Ledgers l WHERE l.company_id = @CompanyId AND l.name = j.supplier_name AND l.ledger_category = 'CREDITOR');
        IF @BadSupplier IS NOT NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, '"' + @BadSupplier + '" is not a real supplier ledger (Sundry Creditors).' AS error;
            RETURN;
        END

        BEGIN TRY
            BEGIN TRAN;

            IF @Id IS NULL
            BEGIN
                INSERT INTO dbo.SSR_AL_Tickets
                    (company_id, branch_name, original_ticket_id, source_reschedule_ticket_id, invoice_number, invoice_date,
                     invoice_type, booking_mode, booking_status, customer_ledger_id, travel_type, user_name, currency, roe,
                     ssr_reference, ssr_ref_date, airline_pnr, gds_pnr, payment_mode, payment_gateway_ref, parent_pnr, created_at, updated_at)
                VALUES
                    (@CompanyId, @BranchName, @OriginalTicketId, @SourceRescheduleTicketId, @InvoiceNumber, @InvoiceDate,
                     @InvoiceType, ISNULL(NULLIF(@BookingMode, ''), 'Manual'), 'SSR Updated', @CustLedgerId, @TravelType, @UserName, ISNULL(@Currency, 'INR'), ISNULL(@Roe, 1),
                     @SsrReference, @SsrRefDate, @AirlinePnr, @GdsPnr, @PaymentMode, @PaymentGatewayRef,
                     CASE WHEN @OriginalTicketId IS NULL THEN NULLIF(LTRIM(RTRIM(@ParentPnr)), '') END, SYSUTCDATETIME(), SYSUTCDATETIME());
                SET @ResultId = CAST(SCOPE_IDENTITY() AS INT);
            END
            ELSE
            BEGIN
                SET @ResultId = @Id;
                UPDATE dbo.SSR_AL_Tickets
                SET invoice_number = @InvoiceNumber, invoice_date = @InvoiceDate, invoice_type = @InvoiceType,
                    user_name = @UserName, ssr_reference = @SsrReference, ssr_ref_date = @SsrRefDate,
                    payment_mode = @PaymentMode, payment_gateway_ref = @PaymentGatewayRef, updated_at = SYSUTCDATETIME()
                WHERE id = @Id AND company_id = @CompanyId;
                -- Lines have no children of their own - replaced wholesale.
                DELETE FROM dbo.SSR_AL_TicketLines WHERE ssr_ticket_id = @Id;
            END

            INSERT INTO dbo.SSR_AL_TicketLines
                (ssr_ticket_id, original_ticket_line_id, reschedule_line_id, ticket_no, passenger_name, pax_type,
                 airline_category, sector, office_id, supplier_ledger_id, fop, card_number, ssr_items, ssr_ticket_numbers, ssr_charges,
                 seat, meal, baggage, other_ssr, markup, service_fee, supp_markup, supp_service_fee, total_billed)
            SELECT @ResultId, j.original_ticket_line_id, j.reschedule_line_id, j.ticket_no, j.passenger_name, j.pax_type,
                   j.airline_category, j.sector, j.office_id,
                   (SELECT id FROM dbo.Ledgers WHERE company_id = @CompanyId AND name = j.supplier_name AND ledger_category = 'CREDITOR'),
                   j.fop, j.card_number, j.ssr_items, j.ssr_ticket_numbers, j.ssr_charges,
                   ISNULL(j.seat, 0), ISNULL(j.meal, 0), ISNULL(j.baggage, 0), ISNULL(j.other_ssr, 0),
                   ISNULL(j.markup, 0), ISNULL(j.service_fee, 0), ISNULL(j.supp_markup, 0), ISNULL(j.supp_service_fee, 0),
                   ISNULL(j.total_billed, 0)
            FROM OPENJSON(@LinesJson) WITH (
                original_ticket_line_id INT '$.original_ticket_line_id', reschedule_line_id INT '$.reschedule_line_id',
                ticket_no NVARCHAR(20) '$.ticket_no', passenger_name NVARCHAR(100) '$.passenger_name',
                pax_type NVARCHAR(10) '$.pax_type', airline_category NVARCHAR(5) '$.airline_category',
                sector NVARCHAR(20) '$.sector', office_id NVARCHAR(30) '$.office_id',
                supplier_name NVARCHAR(150) '$.supplier_name', fop NVARCHAR(20) '$.fop', card_number NVARCHAR(40) '$.card_number', ssr_items NVARCHAR(MAX) '$.ssr_items',
                ssr_ticket_numbers NVARCHAR(MAX) '$.ssr_ticket_numbers', ssr_charges NVARCHAR(MAX) '$.ssr_charges',
                seat DECIMAL(14,2) '$.seat', meal DECIMAL(14,2) '$.meal', baggage DECIMAL(14,2) '$.baggage',
                other_ssr DECIMAL(14,2) '$.other_ssr', markup DECIMAL(14,2) '$.markup', service_fee DECIMAL(14,2) '$.service_fee',
                supp_markup DECIMAL(14,2) '$.supp_markup', supp_service_fee DECIMAL(14,2) '$.supp_service_fee',
                total_billed DECIMAL(14,2) '$.total_billed'
            ) j;

            -- One JV per SSR Updation - upserted in place on edit.
            SELECT @VoucherId = id FROM dbo.JournalVoucher WHERE source_ssr_ticket_id = @ResultId;
            IF @VoucherId IS NOT NULL
            BEGIN
                UPDATE dbo.JournalVoucher
                SET voucher_date = @InvoiceDate, narration = @JvNarration, total_debit = @JvTotalDebit,
                    total_credit = @JvTotalCredit, updated_at = SYSUTCDATETIME()
                WHERE id = @VoucherId;
            END
            ELSE
            BEGIN
                DECLARE @NextNum INT = (SELECT ISNULL(MAX(TRY_CAST(SUBSTRING(voucher_no, 5, 20) AS INT)), 0) + 1
                                        FROM dbo.JournalVoucher
                                        WHERE company_id = @CompanyId AND category = 'AIRLINE_SSR' AND voucher_no LIKE 'ALS-%');
                INSERT INTO dbo.JournalVoucher
                    (company_id, branch_name, voucher_type, voucher_date, narration, category, voucher_no,
                     source_ssr_ticket_id, total_debit, total_credit, lines_json, created_at, updated_at)
                VALUES
                    (@CompanyId, ISNULL(@BranchName, 'Chennai Branch'), 'Tax Invoice', @InvoiceDate, @JvNarration, 'AIRLINE_SSR',
                     'ALS-' + CAST(@NextNum AS NVARCHAR(10)), @ResultId, @JvTotalDebit, @JvTotalCredit, '[]', SYSUTCDATETIME(), SYSUTCDATETIME());
                SET @VoucherId = CAST(SCOPE_IDENTITY() AS INT);
            END
            SELECT @VoucherNo = voucher_no FROM dbo.JournalVoucher WHERE id = @VoucherId;

            COMMIT TRAN;

            SELECT @LineIds = STRING_AGG(CAST(id AS NVARCHAR(10)), ',') FROM dbo.SSR_AL_TicketLines WHERE ssr_ticket_id = @ResultId;
            SELECT @ResultId AS id, @LineIds AS line_ids, @VoucherId AS voucher_id, @VoucherNo AS voucher_no, 'Success' AS status;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END
END
GO


-- ============================================================================
-- dbo.sp_MiscTransaction - Miscellaneous (trans-misc.html). One row per
-- transaction (Description + Base Amount, customer / supplier Markup and
-- Service Fee) + its own Journal Voucher (category MISC, MSC-n) in one
-- transaction. The JV's ledger rows are recomputed live in Python
-- (views._compute_misc_jv_lines, driven by Ledger Mapping) - only the
-- totals / narration are stored here. A Cancelled transaction has no JV.
-- Actions: LIST, GET, SAVE (insert, or update when @Id set).
-- ============================================================================
CREATE OR ALTER PROCEDURE dbo.sp_MiscTransaction
    @Action             NVARCHAR(50),
    @Id                 INT             = NULL,
    @CompanyId          INT             = NULL,
    @BranchName         NVARCHAR(100)   = NULL,
    @InvoiceNumber      NVARCHAR(20)    = NULL,
    @InvoiceDate        DATE            = NULL,
    @InvoiceType        NVARCHAR(100)   = NULL,
    @Status             NVARCHAR(20)    = NULL,
    @UserName           NVARCHAR(100)   = NULL,
    @Reference          NVARCHAR(30)    = NULL,
    @RefDate            DATE            = NULL,
    @PaymentMode        NVARCHAR(20)    = NULL,
    @PaymentGatewayRef  NVARCHAR(60)    = NULL,
    @Currency           NVARCHAR(5)     = NULL,
    @CustomerName       NVARCHAR(150)   = NULL,
    @SupplierName       NVARCHAR(150)   = NULL,
    @Description        NVARCHAR(MAX)   = NULL,
    @BaseAmount         DECIMAL(14,2)   = NULL,
    @OtherTaxes         DECIMAL(14,2)   = NULL,
    @Markup             DECIMAL(14,2)   = NULL,
    @ServiceFee         DECIMAL(14,2)   = NULL,
    @SuppMarkup         DECIMAL(14,2)   = NULL,
    @SuppServiceFee     DECIMAL(14,2)   = NULL,
    @TotalBilled        DECIMAL(14,2)   = NULL,
    @JvNarration        NVARCHAR(250)   = NULL,
    @JvTotalDebit       DECIMAL(16,2)   = NULL,
    @JvTotalCredit      DECIMAL(16,2)   = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'LIST'
    BEGIN
        -- Find popup.
        SELECT m.id, m.invoice_number, m.invoice_date, m.invoice_type, m.status, m.reference, m.ref_date,
               cust.name AS customer_name, supp.name AS supplier_name, m.description, m.total_billed
        FROM dbo.Misc_Transactions m
        INNER JOIN dbo.Ledgers cust ON cust.id = m.customer_ledger_id
        INNER JOIN dbo.Ledgers supp ON supp.id = m.supplier_ledger_id
        WHERE m.company_id = @CompanyId
        ORDER BY m.id DESC;
        RETURN;
    END

    IF @Action = 'GET'
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM dbo.Misc_Transactions WHERE id = @Id AND company_id = @CompanyId)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Miscellaneous transaction not found.' AS error;
            RETURN;
        END
        SELECT m.id, m.branch_name, m.invoice_number, m.invoice_date, m.invoice_type, m.status AS misc_status,
               m.user_name, m.reference, m.ref_date, m.payment_mode, m.payment_gateway_ref, m.currency,
               m.customer_ledger_id, cust.name AS customer_name, cust.state_name AS customer_state,
               m.supplier_ledger_id, supp.name AS supplier_name, supp.state_name AS supplier_state,
               m.description, m.base_amount, m.other_taxes, m.markup, m.service_fee, m.supp_markup, m.supp_service_fee, m.total_billed,
               jv.id AS voucher_id, jv.voucher_no, 'Success' AS status
        FROM dbo.Misc_Transactions m
        INNER JOIN dbo.Ledgers cust ON cust.id = m.customer_ledger_id
        INNER JOIN dbo.Ledgers supp ON supp.id = m.supplier_ledger_id
        LEFT JOIN dbo.JournalVoucher jv ON jv.source_misc_ticket_id = m.id
        WHERE m.id = @Id AND m.company_id = @CompanyId;
        RETURN;
    END

    IF @Action = 'SAVE'
    BEGIN
        DECLARE @CustLedgerId INT, @SuppLedgerId INT, @ResultId INT, @VoucherId INT, @VoucherNo NVARCHAR(20);

        IF @Id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dbo.Misc_Transactions WHERE id = @Id AND company_id = @CompanyId)
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Miscellaneous transaction not found.' AS error;
            RETURN;
        END
        SET @Status = ISNULL(NULLIF(@Status, ''), 'Confirmed');
        IF @Status NOT IN ('Confirmed', 'Cancelled')
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Status must be Confirmed or Cancelled.' AS error;
            RETURN;
        END

        SELECT @CustLedgerId = id FROM dbo.Ledgers
        WHERE company_id = @CompanyId AND name = @CustomerName AND ledger_category = 'DEBTOR';
        IF @CustLedgerId IS NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, '"' + ISNULL(@CustomerName, '') + '" is not a real customer ledger (Sundry Debtors).' AS error;
            RETURN;
        END
        SELECT @SuppLedgerId = id FROM dbo.Ledgers
        WHERE company_id = @CompanyId AND name = @SupplierName AND ledger_category = 'CREDITOR';
        IF @SuppLedgerId IS NULL
        BEGIN
            SELECT NULL AS id, 'Error' AS status, '"' + ISNULL(@SupplierName, '') + '" is not a real supplier ledger (Sundry Creditors).' AS error;
            RETURN;
        END

        -- Invoice Number is shared across Booking / Reschedule / Cancellation / SSR / Miscellaneous.
        IF EXISTS (SELECT 1 FROM dbo.AL_Tickets WHERE company_id = @CompanyId AND invoice_number = @InvoiceNumber)
           OR EXISTS (SELECT 1 FROM dbo.Rescheduled_Al_Ticket WHERE company_id = @CompanyId AND invoice_number = @InvoiceNumber)
           OR EXISTS (SELECT 1 FROM dbo.Cancellation_AL_Tickets WHERE company_id = @CompanyId AND invoice_number = @InvoiceNumber)
           OR EXISTS (SELECT 1 FROM dbo.SSR_AL_Tickets WHERE company_id = @CompanyId AND invoice_number = @InvoiceNumber)
           OR EXISTS (SELECT 1 FROM dbo.Misc_Transactions WHERE company_id = @CompanyId AND invoice_number = @InvoiceNumber AND (@Id IS NULL OR id <> @Id))
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Invoice Number "' + @InvoiceNumber + '" already exists.' AS error;
            RETURN;
        END
        IF EXISTS (SELECT 1 FROM dbo.Misc_Transactions WHERE company_id = @CompanyId AND reference = @Reference AND (@Id IS NULL OR id <> @Id))
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'Reference "' + @Reference + '" already exists.' AS error;
            RETURN;
        END

        BEGIN TRY
            BEGIN TRAN;

            IF @Id IS NULL
            BEGIN
                INSERT INTO dbo.Misc_Transactions
                    (company_id, branch_name, invoice_number, invoice_date, invoice_type, status, user_name, reference, ref_date,
                     payment_mode, payment_gateway_ref, currency, customer_ledger_id, supplier_ledger_id, description,
                     base_amount, other_taxes, markup, service_fee, supp_markup, supp_service_fee, total_billed, created_at, updated_at)
                VALUES
                    (@CompanyId, @BranchName, @InvoiceNumber, @InvoiceDate, @InvoiceType, @Status, @UserName, @Reference, @RefDate,
                     @PaymentMode, @PaymentGatewayRef, ISNULL(@Currency, 'INR'), @CustLedgerId, @SuppLedgerId, @Description,
                     ISNULL(@BaseAmount, 0), ISNULL(@OtherTaxes, 0), ISNULL(@Markup, 0), ISNULL(@ServiceFee, 0), ISNULL(@SuppMarkup, 0), ISNULL(@SuppServiceFee, 0),
                     ISNULL(@TotalBilled, 0), SYSUTCDATETIME(), SYSUTCDATETIME());
                SET @ResultId = CAST(SCOPE_IDENTITY() AS INT);
            END
            ELSE
            BEGIN
                SET @ResultId = @Id;
                UPDATE dbo.Misc_Transactions
                SET invoice_number = @InvoiceNumber, invoice_date = @InvoiceDate, invoice_type = @InvoiceType, status = @Status,
                    user_name = @UserName, reference = @Reference, ref_date = @RefDate, payment_mode = @PaymentMode,
                    payment_gateway_ref = @PaymentGatewayRef, customer_ledger_id = @CustLedgerId, supplier_ledger_id = @SuppLedgerId,
                    description = @Description, base_amount = ISNULL(@BaseAmount, 0), other_taxes = ISNULL(@OtherTaxes, 0),
                    markup = ISNULL(@Markup, 0),
                    service_fee = ISNULL(@ServiceFee, 0), supp_markup = ISNULL(@SuppMarkup, 0),
                    supp_service_fee = ISNULL(@SuppServiceFee, 0), total_billed = ISNULL(@TotalBilled, 0), updated_at = SYSUTCDATETIME()
                WHERE id = @Id AND company_id = @CompanyId;
            END

            -- One JV per Confirmed transaction - upserted in place on edit;
            -- Cancelled removes it (nothing posted to the books).
            SELECT @VoucherId = id FROM dbo.JournalVoucher WHERE source_misc_ticket_id = @ResultId;
            IF @Status = 'Cancelled'
            BEGIN
                IF @VoucherId IS NOT NULL DELETE FROM dbo.JournalVoucher WHERE id = @VoucherId;
                SET @VoucherId = NULL;
            END
            ELSE IF @VoucherId IS NOT NULL
            BEGIN
                UPDATE dbo.JournalVoucher
                SET voucher_date = @InvoiceDate, narration = @JvNarration, total_debit = @JvTotalDebit,
                    total_credit = @JvTotalCredit, updated_at = SYSUTCDATETIME()
                WHERE id = @VoucherId;
            END
            ELSE
            BEGIN
                DECLARE @NextNum INT = (SELECT ISNULL(MAX(TRY_CAST(SUBSTRING(voucher_no, 5, 20) AS INT)), 0) + 1
                                        FROM dbo.JournalVoucher
                                        WHERE company_id = @CompanyId AND category = 'MISC' AND voucher_no LIKE 'MSC-%');
                INSERT INTO dbo.JournalVoucher
                    (company_id, branch_name, voucher_type, voucher_date, narration, category, voucher_no,
                     source_misc_ticket_id, total_debit, total_credit, lines_json, created_at, updated_at)
                VALUES
                    (@CompanyId, ISNULL(@BranchName, 'Chennai Branch'), 'Tax Invoice', @InvoiceDate, @JvNarration, 'MISC',
                     'MSC-' + CAST(@NextNum AS NVARCHAR(10)), @ResultId, @JvTotalDebit, @JvTotalCredit, '[]', SYSUTCDATETIME(), SYSUTCDATETIME());
                SET @VoucherId = CAST(SCOPE_IDENTITY() AS INT);
            END
            SELECT @VoucherNo = voucher_no FROM dbo.JournalVoucher WHERE id = @VoucherId;

            COMMIT TRAN;
            SELECT @ResultId AS id, @VoucherId AS voucher_id, @VoucherNo AS voucher_no, 'Success' AS status;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS id, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END
END
GO

-- ============================================================
-- dbo.sp_AirlineDropdown - airline dropdown lists (Booking, Reschedule,
-- Cancellation, SSR, Returns / DSR, FOP Master). Each value has a short
-- code (Confirmed = CON, Adult = ADT ...) for Auto Push / import.
--   LIST    : active values of every list (or one @ListKey), screen order.
--   RESOLVE : one value of @ListKey by its @Code or its @Name.
-- ============================================================
CREATE OR ALTER PROCEDURE dbo.sp_AirlineDropdown
    @Action  NVARCHAR(20),
    @ListKey NVARCHAR(50)  = NULL,
    @Code    NVARCHAR(10)  = NULL,
    @Name    NVARCHAR(100) = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'LIST'
    BEGIN
        SELECT list_key, code, name, ISNULL(display_label, name) AS label, sort_order, is_default
        FROM dbo.AirlineDropdownValues
        WHERE is_active = 1 AND (@ListKey IS NULL OR list_key = @ListKey)
        ORDER BY list_key, sort_order, id;
        RETURN;
    END

    IF @Action = 'RESOLVE'
    BEGIN
        SELECT TOP 1 list_key, code, name, ISNULL(display_label, name) AS label
        FROM dbo.AirlineDropdownValues
        WHERE is_active = 1 AND list_key = @ListKey
          AND ((@Code IS NOT NULL AND code = @Code) OR (@Code IS NULL AND name = @Name));
        RETURN;
    END
END
GO

-- ============================================================
-- dbo.sp_AuditLog - edit history of Booking / Reschedule / Cancellation /
-- SSR Updation (who changed what, when) - views.audited().
--   SNAPSHOT : the document straight from its tables, as JSON (header +
--              lines, with customer / supplier names), before / after a save.
--   CHAIN    : the follow-up documents of a Booking / Reschedule (same
--              original booking) - an edit can carry changes down to them.
--   INSERT   : one log row.
--   LIST     : log rows of one document (newest first), or of a company.
-- ============================================================
CREATE OR ALTER PROCEDURE dbo.sp_AuditLog
    @Action      NVARCHAR(20),
    @CompanyId   INT           = NULL,
    @Module      NVARCHAR(30)  = NULL,
    @DocumentId  INT           = NULL,
    @DocumentNo  NVARCHAR(50)  = NULL,
    @LogAction   NVARCHAR(20)  = NULL,
    @Source      NVARCHAR(150) = NULL,
    @UserId      INT           = NULL,
    @UserName    NVARCHAR(150) = NULL,
    @ChangeCount INT           = 0,
    @Changes     NVARCHAR(MAX) = NULL,
    @Top         INT           = 500
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'SNAPSHOT'
    BEGIN
        IF @Module = 'Booking'
            SELECT
                (SELECT t.*, c.name AS customer_name, s.name AS supplier_name
                 FROM dbo.AL_Tickets t
                 LEFT JOIN dbo.Ledgers c ON c.id = t.customer_ledger_id
                 LEFT JOIN dbo.Ledgers s ON s.id = t.supplier_ledger_id
                 WHERE t.id = @DocumentId
                 FOR JSON PATH, INCLUDE_NULL_VALUES, WITHOUT_ARRAY_WRAPPER) AS header_json,
                (SELECT l.*, s.name AS supplier_name
                 FROM dbo.AL_TicketLines l
                 LEFT JOIN dbo.Ledgers s ON s.id = l.supplier_ledger_id
                 WHERE l.ticket_id = @DocumentId ORDER BY l.id
                 FOR JSON PATH, INCLUDE_NULL_VALUES) AS lines_json;
        ELSE IF @Module = 'Reschedule'
            SELECT
                (SELECT t.*, c.name AS customer_name, s.name AS supplier_name
                 FROM dbo.Rescheduled_Al_Ticket t
                 LEFT JOIN dbo.Ledgers c ON c.id = t.customer_ledger_id
                 LEFT JOIN dbo.Ledgers s ON s.id = t.supplier_ledger_id
                 WHERE t.id = @DocumentId
                 FOR JSON PATH, INCLUDE_NULL_VALUES, WITHOUT_ARRAY_WRAPPER) AS header_json,
                (SELECT l.*, s.name AS supplier_name
                 FROM dbo.Rescheduled_Al_TicketLines l
                 LEFT JOIN dbo.Ledgers s ON s.id = l.supplier_ledger_id
                 WHERE l.reschedule_ticket_id = @DocumentId ORDER BY l.id
                 FOR JSON PATH, INCLUDE_NULL_VALUES) AS lines_json;
        ELSE IF @Module = 'Cancellation'
            SELECT
                (SELECT t.*, c.name AS customer_name, s.name AS supplier_name
                 FROM dbo.Cancellation_AL_Tickets t
                 LEFT JOIN dbo.Ledgers c ON c.id = t.customer_ledger_id
                 LEFT JOIN dbo.Ledgers s ON s.id = t.supplier_ledger_id
                 WHERE t.id = @DocumentId
                 FOR JSON PATH, INCLUDE_NULL_VALUES, WITHOUT_ARRAY_WRAPPER) AS header_json,
                (SELECT l.*, s.name AS supplier_name
                 FROM dbo.Cancellation_Al_TicketLines l
                 LEFT JOIN dbo.Ledgers s ON s.id = l.supplier_ledger_id
                 WHERE l.cancellation_ticket_id = @DocumentId ORDER BY l.id
                 FOR JSON PATH, INCLUDE_NULL_VALUES) AS lines_json;
        ELSE IF @Module = 'SSR Updation'
            SELECT
                (SELECT t.*, c.name AS customer_name
                 FROM dbo.SSR_AL_Tickets t
                 LEFT JOIN dbo.Ledgers c ON c.id = t.customer_ledger_id
                 WHERE t.id = @DocumentId
                 FOR JSON PATH, INCLUDE_NULL_VALUES, WITHOUT_ARRAY_WRAPPER) AS header_json,
                (SELECT l.*, s.name AS supplier_name
                 FROM dbo.SSR_AL_TicketLines l
                 LEFT JOIN dbo.Ledgers s ON s.id = l.supplier_ledger_id
                 WHERE l.ssr_ticket_id = @DocumentId ORDER BY l.id
                 FOR JSON PATH, INCLUDE_NULL_VALUES) AS lines_json;
        RETURN;
    END

    IF @Action = 'CHAIN'
    BEGIN
        DECLARE @Root INT = CASE @Module
            WHEN 'Booking' THEN @DocumentId
            WHEN 'Reschedule' THEN (SELECT original_ticket_id FROM dbo.Rescheduled_Al_Ticket WHERE id = @DocumentId)
        END;
        SELECT module, id FROM (
            SELECT 'Reschedule' AS module, id FROM dbo.Rescheduled_Al_Ticket WHERE original_ticket_id = @Root
            UNION ALL SELECT 'Cancellation', id FROM dbo.Cancellation_AL_Tickets WHERE original_ticket_id = @Root
            UNION ALL SELECT 'SSR Updation', id FROM dbo.SSR_AL_Tickets WHERE original_ticket_id = @Root
        ) x
        WHERE @Root IS NOT NULL AND NOT (x.module = @Module AND x.id = @DocumentId)
        ORDER BY module, id;
        RETURN;
    END

    IF @Action = 'INSERT'
    BEGIN
        INSERT INTO dbo.AuditLogs
            (company_id, module, document_id, document_no, action, source, user_id, user_name, change_count, changes, changed_at)
        VALUES (@CompanyId, @Module, @DocumentId, @DocumentNo, @LogAction, @Source, @UserId, @UserName,
                ISNULL(@ChangeCount, 0), @Changes, SYSUTCDATETIME());
        SELECT CAST(SCOPE_IDENTITY() AS INT) AS id;
        RETURN;
    END

    IF @Action = 'LIST'
    BEGIN
        SELECT TOP (@Top) id, company_id, module, document_id, document_no, action, source,
               user_id, user_name, change_count, changes, changed_at
        FROM dbo.AuditLogs
        WHERE company_id = @CompanyId
          AND (@Module IS NULL OR module = @Module)
          AND (@DocumentId IS NULL OR document_id = @DocumentId)
        ORDER BY changed_at DESC, id DESC;
        RETURN;
    END
END
GO


-- ============================================================================
-- Airline ticket Auto Push import (migration 0074) - accounting/ticket_import.py
-- ============================================================================
CREATE OR ALTER PROCEDURE dbo.sp_TicketImport_Stage
    -- INSERT_JSON : @RowsJson = JSON array, one object per passenger, keys =
    --               staging column names (+ raw_payload). A document still
    --               Pending / Error is replaced by the new push; one already
    --               Processing / Imported / Skipped is never touched.
    --               Returns one row per pushed passenger with its outcome.
    -- DOC_STATUS  : one row per document (filters optional).
    -- REQUEUE     : Error documents back to Pending (retry_count reset).
    @Action         NVARCHAR(30),
    @CompanyId      INT            = NULL,
    @BatchId        NVARCHAR(50)   = NULL,
    @RowsJson       NVARCHAR(MAX)  = NULL,
    @DocKeysJson    NVARCHAR(MAX)  = NULL,
    @SourceSystem   NVARCHAR(50)   = NULL,
    @DocRef         NVARCHAR(60)   = NULL,
    @ProcessStatus  NVARCHAR(20)   = NULL,
    @Top            INT            = 200
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'INSERT_JSON'
    BEGIN
        IF @RowsJson IS NULL OR ISJSON(@RowsJson) = 0
        BEGIN
            SELECT 'Error' AS status, 'RowsJson must be a JSON array.' AS error;
            RETURN;
        END

        SELECT j.*,
               j.ticket_status + N'|' + CAST(j.company_id AS NVARCHAR(10)) + N'|' + j.source_system + N'|' + j.doc_ref AS doc_key
        INTO #Src
        FROM OPENJSON(@RowsJson) WITH (
            source_system NVARCHAR(50), doc_ref NVARCHAR(60), source_record_id NVARCHAR(100),
            ticket_status NVARCHAR(20), company_id INT,
            branch_name NVARCHAR(100), invoice_number NVARCHAR(20), invoice_date DATE, invoice_type NVARCHAR(100),
            booking_mode NVARCHAR(20), booking_type NVARCHAR(50), booking_status NVARCHAR(20),
            customer_name NVARCHAR(150), supplier_name NVARCHAR(150), travel_type NVARCHAR(20), user_name NVARCHAR(100),
            currency NVARCHAR(5), roe DECIMAL(10,4), booking_given_by NVARCHAR(25), booking_reference NVARCHAR(30),
            booking_ref_date DATE, airline_pnr NVARCHAR(13), gds_pnr NVARCHAR(13), office_id NVARCHAR(30),
            payment_mode NVARCHAR(20), payment_gateway_ref NVARCHAR(60), airline_category NVARCHAR(5),
            original_ticket_no NVARCHAR(30), airline_code NVARCHAR(200), airline_name NVARCHAR(200),
            line_airline_category NVARCHAR(5), flight_no NVARCHAR(200), ticket_no NVARCHAR(30),
            passenger_name NVARCHAR(50), pax_type NVARCHAR(10), sector NVARCHAR(200), travel_date NVARCHAR(200),
            cabin NVARCHAR(200), travel_class NVARCHAR(200), fare_type NVARCHAR(300), line_supplier_name NVARCHAR(150),
            line_office_id NVARCHAR(30), fop NVARCHAR(20), card_number NVARCHAR(40), line_status NVARCHAR(15),
            basic_fare DECIMAL(14,2), yq DECIMAL(14,2), yr DECIMAL(14,2), k3_tax DECIMAL(14,2), tax_others DECIMAL(14,2),
            seat DECIMAL(14,2), meal DECIMAL(14,2), baggage DECIMAL(14,2), other_ssr DECIMAL(14,2),
            disc_on NVARCHAR(20), disc_type NVARCHAR(12), disc_value DECIMAL(14,2), tds_per DECIMAL(5,2),
            pg_charges DECIMAL(14,2), pg_charges_percentage DECIMAL(5,2), markup DECIMAL(14,2), addl_markup DECIMAL(14,2),
            ssr_markup DECIMAL(14,2), service_fee DECIMAL(14,2), addl_service_fee DECIMAL(14,2), ssr_service_fee DECIMAL(14,2),
            gst_pct DECIMAL(5,2), supp_comm_on NVARCHAR(20), supp_comm_type NVARCHAR(12), supp_comm_value DECIMAL(14,2),
            supp_tds_per DECIMAL(5,2), supp_markup DECIMAL(14,2), supp_addl_markup DECIMAL(14,2), supp_ssr_markup DECIMAL(14,2),
            supp_service_fee DECIMAL(14,2), supp_addl_service_fee DECIMAL(14,2), supp_ssr_service_fee DECIMAL(14,2),
            supp_gst_pct DECIMAL(5,2), agent_penalty DECIMAL(14,2), reschedule_penalty DECIMAL(14,2),
            supplier_penalty DECIMAL(14,2), cancellation_penalty DECIMAL(14,2), cust_markup_reversal DECIMAL(14,2),
            cust_addl_markup_reversal DECIMAL(14,2), cust_ssr_markup_reversal DECIMAL(14,2), supp_markup_reversal DECIMAL(14,2),
            supp_addl_markup_reversal DECIMAL(14,2), supp_ssr_markup_reversal DECIMAL(14,2),
            tds_amount_override DECIMAL(14,2), supp_tds_amount_override DECIMAL(14,2), total_billed DECIMAL(14,2),
            raw_payload NVARCHAR(MAX)
        ) j;

        BEGIN TRY
            BEGIN TRAN;

            -- Outcome per pushed passenger, decided before anything changes.
            SELECT s.source_system, s.source_record_id, s.doc_key,
                   CASE
                       WHEN t.staging_id IS NOT NULL AND t.process_status IN ('Pending', 'Error') THEN 'Refreshed'
                       WHEN t.staging_id IS NOT NULL THEN 'Unchanged'
                       WHEN EXISTS (SELECT 1 FROM dbo.Ticket_Import_Staging d WITH (UPDLOCK, HOLDLOCK)
                                    WHERE d.doc_key = s.doc_key AND d.process_status IN ('Processing', 'Imported', 'Skipped')) THEN 'Ignored'
                       ELSE 'Inserted'
                   END AS outcome
            INTO #Out
            FROM #Src s
            LEFT JOIN dbo.Ticket_Import_Staging t WITH (UPDLOCK, HOLDLOCK)
                   ON t.source_system = s.source_system AND t.source_record_id = s.source_record_id;

            -- A document pushed again while still Pending / Error is replaced
            -- as a whole (so a passenger dropped from it is dropped here too).
            DELETE t FROM dbo.Ticket_Import_Staging t
            WHERE t.process_status IN ('Pending', 'Error')
              AND (t.doc_key IN (SELECT doc_key FROM #Out WHERE outcome IN ('Inserted', 'Refreshed'))
                   OR EXISTS (SELECT 1 FROM #Out o WHERE o.outcome = 'Refreshed'
                              AND o.source_system = t.source_system AND o.source_record_id = t.source_record_id));

            INSERT INTO dbo.Ticket_Import_Staging (
                batch_id, source_system, doc_ref, source_record_id, ticket_status, company_id,
                branch_name, invoice_number, invoice_date, invoice_type, booking_mode, booking_type, booking_status,
                customer_name, supplier_name, travel_type, user_name, currency, roe, booking_given_by,
                booking_reference, booking_ref_date, airline_pnr, gds_pnr, office_id, payment_mode, payment_gateway_ref,
                airline_category, original_ticket_no, airline_code, airline_name, line_airline_category, flight_no,
                ticket_no, passenger_name, pax_type, sector, travel_date, cabin, travel_class, fare_type,
                line_supplier_name, line_office_id, fop, card_number, line_status,
                basic_fare, yq, yr, k3_tax, tax_others, seat, meal, baggage, other_ssr,
                disc_on, disc_type, disc_value, tds_per, pg_charges, pg_charges_percentage,
                markup, addl_markup, ssr_markup, service_fee, addl_service_fee, ssr_service_fee, gst_pct,
                supp_comm_on, supp_comm_type, supp_comm_value, supp_tds_per, supp_markup, supp_addl_markup,
                supp_ssr_markup, supp_service_fee, supp_addl_service_fee, supp_ssr_service_fee, supp_gst_pct,
                agent_penalty, reschedule_penalty, supplier_penalty, cancellation_penalty,
                cust_markup_reversal, cust_addl_markup_reversal, cust_ssr_markup_reversal,
                supp_markup_reversal, supp_addl_markup_reversal, supp_ssr_markup_reversal,
                tds_amount_override, supp_tds_amount_override, total_billed, raw_payload)
            SELECT
                @BatchId, s.source_system, s.doc_ref, s.source_record_id, s.ticket_status, s.company_id,
                s.branch_name, s.invoice_number, s.invoice_date, s.invoice_type, s.booking_mode, s.booking_type, s.booking_status,
                s.customer_name, s.supplier_name, s.travel_type, s.user_name, s.currency, s.roe, s.booking_given_by,
                s.booking_reference, s.booking_ref_date, s.airline_pnr, s.gds_pnr, s.office_id, s.payment_mode, s.payment_gateway_ref,
                s.airline_category, s.original_ticket_no, s.airline_code, s.airline_name, s.line_airline_category, s.flight_no,
                s.ticket_no, s.passenger_name, s.pax_type, s.sector, s.travel_date, s.cabin, s.travel_class, s.fare_type,
                s.line_supplier_name, s.line_office_id, s.fop, s.card_number, s.line_status,
                ISNULL(s.basic_fare, 0), ISNULL(s.yq, 0), ISNULL(s.yr, 0), ISNULL(s.k3_tax, 0), ISNULL(s.tax_others, 0),
                ISNULL(s.seat, 0), ISNULL(s.meal, 0), ISNULL(s.baggage, 0), ISNULL(s.other_ssr, 0),
                s.disc_on, s.disc_type, ISNULL(s.disc_value, 0), ISNULL(s.tds_per, 0), ISNULL(s.pg_charges, 0), ISNULL(s.pg_charges_percentage, 0),
                ISNULL(s.markup, 0), ISNULL(s.addl_markup, 0), ISNULL(s.ssr_markup, 0), ISNULL(s.service_fee, 0),
                ISNULL(s.addl_service_fee, 0), ISNULL(s.ssr_service_fee, 0), ISNULL(s.gst_pct, 0),
                s.supp_comm_on, s.supp_comm_type, ISNULL(s.supp_comm_value, 0), ISNULL(s.supp_tds_per, 0),
                ISNULL(s.supp_markup, 0), ISNULL(s.supp_addl_markup, 0), ISNULL(s.supp_ssr_markup, 0),
                ISNULL(s.supp_service_fee, 0), ISNULL(s.supp_addl_service_fee, 0), ISNULL(s.supp_ssr_service_fee, 0), ISNULL(s.supp_gst_pct, 0),
                ISNULL(s.agent_penalty, 0), ISNULL(s.reschedule_penalty, 0), ISNULL(s.supplier_penalty, 0), ISNULL(s.cancellation_penalty, 0),
                ISNULL(s.cust_markup_reversal, 0), ISNULL(s.cust_addl_markup_reversal, 0), ISNULL(s.cust_ssr_markup_reversal, 0),
                ISNULL(s.supp_markup_reversal, 0), ISNULL(s.supp_addl_markup_reversal, 0), ISNULL(s.supp_ssr_markup_reversal, 0),
                s.tds_amount_override, s.supp_tds_amount_override, s.total_billed, s.raw_payload
            FROM #Src s
            INNER JOIN #Out o ON o.source_system = s.source_system AND o.source_record_id = s.source_record_id
            WHERE o.outcome IN ('Inserted', 'Refreshed');

            COMMIT TRAN;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT 'Error' AS status, ERROR_MESSAGE() AS error;
            RETURN;
        END CATCH

        SELECT o.doc_key, o.source_record_id, o.outcome, t.staging_id, t.process_status,
               t.saved_invoice_number, t.error_message
        FROM #Out o
        LEFT JOIN dbo.Ticket_Import_Staging t
               ON t.source_system = o.source_system AND t.source_record_id = o.source_record_id;
        RETURN;
    END

    IF @Action = 'DOC_STATUS'
    BEGIN
        SELECT TOP (@Top)
               doc_key, MAX(company_id) AS company_id, MAX(source_system) AS source_system, MAX(doc_ref) AS doc_ref,
               MAX(ticket_status) AS ticket_status, MAX(batch_id) AS batch_id, COUNT(*) AS passengers,
               MAX(process_status) AS process_status, MAX(retry_count) AS retry_count, MAX(error_message) AS error_message,
               MAX(saved_invoice_number) AS invoice_number, MAX(saved_voucher_no) AS voucher_no,
               MAX(target_header_id) AS target_header_id, MAX(invoice_type) AS invoice_type,
               MIN(received_at) AS received_at, MAX(processed_at) AS processed_at
        FROM dbo.Ticket_Import_Staging
        WHERE (@CompanyId IS NULL OR company_id = @CompanyId)
          AND (@BatchId IS NULL OR batch_id = @BatchId)
          AND (@SourceSystem IS NULL OR source_system = @SourceSystem)
          AND (@DocRef IS NULL OR doc_ref = @DocRef)
          AND (@ProcessStatus IS NULL OR process_status = @ProcessStatus)
          AND (@DocKeysJson IS NULL OR doc_key IN (SELECT [value] FROM OPENJSON(@DocKeysJson)))
        GROUP BY doc_key
        ORDER BY MAX(staging_id) DESC;
        RETURN;
    END

    IF @Action = 'REQUEUE'
    BEGIN
        UPDATE dbo.Ticket_Import_Staging
        SET process_status = 'Pending', retry_count = 0, error_message = NULL, run_id = NULL, picked_at = NULL
        WHERE process_status = 'Error'
          AND (@CompanyId IS NULL OR company_id = @CompanyId)
          AND (@DocKeysJson IS NULL OR doc_key IN (SELECT [value] FROM OPENJSON(@DocKeysJson)));
        SELECT @@ROWCOUNT AS rows_requeued, 'Success' AS status;
        RETURN;
    END

    SELECT 'Error' AS status, 'Unknown @Action ' + ISNULL(@Action, '') AS error;
END
GO

CREATE OR ALTER PROCEDURE dbo.sp_TicketImport_Scheduler
    -- START_RUN       : opens a run log row, returns run_id.
    -- RESET_STUCK     : Processing for over @StuckMinutes (crashed run) -> Pending.
    -- FETCH_PENDING   : claims up to @BatchSize whole documents (Processing) and
    --                   returns their rows, Confirmed first, then Rescheduled,
    --                   then Cancelled. A Rescheduled / Cancelled document waits
    --                   while the ticket it changes is itself still queued here.
    -- RESOLVE_PARENTS : the CURRENT live line of each Ticket No. in
    --                   @TicketNosJson (a reschedule line not yet rescheduled /
    --                   cancelled, else the original booking line) + its header.
    -- MARK_IMPORTED / MARK_ERROR / MARK_SKIPPED : by @DocKey.
    -- FINISH_RUN      : closes the run log row.
    @Action          NVARCHAR(30),
    @CompanyId       INT            = NULL,
    @RunId           BIGINT         = NULL,
    @BatchSize       INT            = 50,
    @StuckMinutes    INT            = 30,
    @DocKey          NVARCHAR(200)  = NULL,
    @TicketNosJson   NVARCHAR(MAX)  = NULL,
    @TargetHeaderId  INT            = NULL,
    @InvoiceNumber   NVARCHAR(20)   = NULL,
    @VoucherNo       NVARCHAR(30)   = NULL,
    @ErrorMessage    NVARCHAR(1000) = NULL,
    @MaxRetry        INT            = 3,
    @DocsImported    INT            = NULL,
    @DocsFailed      INT            = NULL,
    @Message         NVARCHAR(1000) = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'START_RUN'
    BEGIN
        INSERT INTO dbo.Ticket_Import_Run_Log (company_id) VALUES (@CompanyId);
        SELECT CAST(SCOPE_IDENTITY() AS BIGINT) AS run_id, 'Success' AS status;
        RETURN;
    END

    IF @Action = 'RESET_STUCK'
    BEGIN
        UPDATE dbo.Ticket_Import_Staging
        SET process_status = 'Pending', picked_at = NULL, run_id = NULL,
            error_message = 'Reset after being stuck in Processing for over ' + CAST(@StuckMinutes AS NVARCHAR(10)) + ' minutes.'
        WHERE process_status = 'Processing'
          AND picked_at < DATEADD(MINUTE, -@StuckMinutes, SYSUTCDATETIME())
          AND (@CompanyId IS NULL OR company_id = @CompanyId);
        SELECT @@ROWCOUNT AS rows_reset, 'Success' AS status;
        RETURN;
    END

    IF @Action = 'FETCH_PENDING'
    BEGIN
        DECLARE @Claimed TABLE (staging_id BIGINT PRIMARY KEY);

        SET XACT_ABORT ON;
        BEGIN TRAN;
        -- One claimer at a time, so two runs never split one document.
        EXEC sp_getapplock @Resource = 'TicketImport_Fetch', @LockMode = 'Exclusive', @LockOwner = 'Transaction', @LockTimeout = 30000;

        DECLARE @Candidates TABLE (staging_id BIGINT PRIMARY KEY, doc_key NVARCHAR(200), status_order INT, ready BIT);
        INSERT INTO @Candidates (staging_id, doc_key, status_order, ready)
        SELECT s.staging_id, s.doc_key,
               CASE s.ticket_status WHEN 'Confirmed' THEN 1 WHEN 'Rescheduled' THEN 2 WHEN 'SSR' THEN 3 ELSE 4 END,
               CASE WHEN s.ticket_status = 'Confirmed' THEN 1
                    WHEN EXISTS (SELECT 1 FROM dbo.Rescheduled_Al_TicketLines rl
                                 INNER JOIN dbo.Rescheduled_Al_Ticket rt ON rt.id = rl.reschedule_ticket_id
                                 WHERE rt.company_id = s.company_id AND rl.ticket_no = s.original_ticket_no
                                   AND rl.rescheduled = 0 AND rl.canceled = 0) THEN 1
                    WHEN EXISTS (SELECT 1 FROM dbo.AL_TicketLines tl
                                 INNER JOIN dbo.AL_Tickets t ON t.id = tl.ticket_id
                                 WHERE t.company_id = s.company_id AND tl.ticket_no = s.original_ticket_no
                                   AND tl.rescheduled = 0 AND tl.canceled = 0) THEN 1
                    -- Parent not live yet but still queued here -> wait for it.
                    WHEN EXISTS (SELECT 1 FROM dbo.Ticket_Import_Staging w
                                 WHERE w.company_id = s.company_id AND w.ticket_no = s.original_ticket_no
                                   AND w.staging_id <> s.staging_id AND w.process_status IN ('Pending', 'Processing')) THEN 0
                    -- Nowhere at all -> hand it out so it fails with a clear message.
                    ELSE 1 END
        FROM dbo.Ticket_Import_Staging s
        WHERE s.process_status = 'Pending'
          AND (@CompanyId IS NULL OR s.company_id = @CompanyId)
          AND (@RunId IS NULL OR s.run_id IS NULL OR s.run_id <> @RunId);   -- failed earlier in this run -> next run

        UPDATE s
        SET process_status = 'Processing', picked_at = SYSUTCDATETIME(), run_id = @RunId
        OUTPUT inserted.staging_id INTO @Claimed (staging_id)
        FROM dbo.Ticket_Import_Staging s
        INNER JOIN @Candidates c ON c.staging_id = s.staging_id
        WHERE s.process_status = 'Pending'
          AND c.doc_key IN (SELECT TOP (@BatchSize) doc_key FROM @Candidates
                            GROUP BY doc_key HAVING MIN(CAST(ready AS INT)) = 1
                            ORDER BY MIN(status_order), MIN(staging_id));
        COMMIT TRAN;

        IF @RunId IS NOT NULL
            UPDATE dbo.Ticket_Import_Run_Log SET rows_picked = rows_picked + (SELECT COUNT(*) FROM @Claimed) WHERE run_id = @RunId;

        SELECT s.*
        FROM dbo.Ticket_Import_Staging s
        INNER JOIN @Claimed k ON k.staging_id = s.staging_id
        ORDER BY CASE s.ticket_status WHEN 'Confirmed' THEN 1 WHEN 'Rescheduled' THEN 2 WHEN 'SSR' THEN 3 ELSE 4 END, s.doc_key, s.staging_id;
        RETURN;
    END

    IF @Action = 'RESOLVE_PARENTS'
    BEGIN
        SELECT n.ticket_no AS lookup_ticket_no,
               CASE k.pri WHEN 1 THEN 'Reschedule' ELSE 'Booking' END AS parent_kind,
               k.line_id AS live_line_id,
               COALESCE(rt.original_ticket_id, t.id) AS original_ticket_id,
               COALESCE(rl.original_ticket_line_id, tl.id) AS original_ticket_line_id,
               rt.id AS reschedule_ticket_id,
               -- header of the live document (h_ = header field)
               COALESCE(rt.invoice_number, t.invoice_number) AS h_invoice_number,
               COALESCE(rt.invoice_type, t.invoice_type) AS h_invoice_type,
               COALESCE(rt.branch_name, t.branch_name) AS h_branch_name,
               COALESCE(rt.booking_type, t.booking_type) AS h_booking_type,
               COALESCE(rt.travel_type, t.travel_type) AS h_travel_type,
               COALESCE(rt.user_name, t.user_name) AS h_user_name,
               COALESCE(rt.currency, t.currency) AS h_currency,
               COALESCE(rt.roe, t.roe) AS h_roe,
               COALESCE(rt.booking_given_by, t.booking_given_by) AS h_booking_given_by,
               COALESCE(rt.booking_reference, t.booking_reference) AS h_booking_reference,
               COALESCE(rt.airline_pnr, t.airline_pnr) AS h_airline_pnr,
               COALESCE(rt.gds_pnr, t.gds_pnr) AS h_gds_pnr,
               COALESCE(rt.office_id, t.office_id) AS h_office_id,
               COALESCE(rt.payment_mode, t.payment_mode) AS h_payment_mode,
               COALESCE(rt.payment_gateway_ref, t.payment_gateway_ref) AS h_payment_gateway_ref,
               COALESCE(rt.airline_category, t.airline_category) AS h_airline_category,
               hc.name AS h_customer_name, hs.name AS h_supplier_name,
               -- the live passenger line (same names as the Ticket Entry line fields)
               COALESCE(rl.airline_code, tl.airline_code) AS airline_code,
               COALESCE(rl.airline_name, tl.airline_name) AS airline_name,
               COALESCE(rl.airline_category, tl.airline_category) AS airline_category,
               COALESCE(rl.flight_no, tl.flight_no) AS flight_no,
               COALESCE(rl.ticket_no, tl.ticket_no) AS ticket_no,
               COALESCE(rl.passenger_name, tl.passenger_name) AS passenger_name,
               COALESCE(rl.pax_type, tl.pax_type) AS pax_type,
               COALESCE(rl.sector, tl.sector) AS sector,
               COALESCE(rl.travel_date, tl.travel_date) AS travel_date,
               COALESCE(rl.cabin, tl.cabin) AS cabin,
               COALESCE(rl.travel_class, tl.travel_class) AS travel_class,
               COALESCE(rl.fare_type, tl.fare_type) AS fare_type,
               COALESCE(rl.basic_fare, tl.basic_fare) AS basic_fare,
               COALESCE(rl.yq, tl.yq) AS yq,
               COALESCE(rl.yr, tl.yr) AS yr,
               COALESCE(rl.k3_tax, tl.k3_tax) AS k3_tax,
               COALESCE(rl.tax_others, tl.tax_others) AS tax_others,
               COALESCE(rl.seat, tl.seat) AS seat,
               COALESCE(rl.meal, tl.meal) AS meal,
               COALESCE(rl.baggage, tl.baggage) AS baggage,
               COALESCE(rl.other_ssr, tl.other_ssr) AS other_ssr,
               COALESCE(rl.disc_on, tl.disc_on) AS disc_on,
               COALESCE(rl.disc_type, tl.disc_type) AS disc_type,
               COALESCE(rl.disc_value, tl.disc_value) AS disc_value,
               COALESCE(rl.tds_per, tl.tds_per) AS tds_per,
               COALESCE(rl.pg_charges, tl.pg_charges) AS pg_charges,
               COALESCE(rl.pg_charges_percentage, tl.pg_charges_percentage) AS pg_charges_percentage,
               COALESCE(rl.markup, tl.markup) AS markup,
               COALESCE(rl.addl_markup, tl.addl_markup) AS addl_markup,
               COALESCE(rl.ssr_markup, tl.ssr_markup) AS ssr_markup,
               COALESCE(rl.service_fee, tl.service_fee) AS service_fee,
               COALESCE(rl.addl_service_fee, tl.addl_service_fee) AS addl_service_fee,
               COALESCE(rl.ssr_service_fee, tl.ssr_service_fee) AS ssr_service_fee,
               COALESCE(rl.gst_pct, tl.gst_pct) AS gst_pct,
               COALESCE(rl.status, tl.status) AS status,
               COALESCE(rl.office_id, tl.office_id) AS office_id,
               COALESCE(rl.fop, tl.fop) AS fop,
               COALESCE(rl.card_number, tl.card_number) AS card_number,
               COALESCE(rl.supp_comm_on, tl.supp_comm_on) AS supp_comm_on,
               COALESCE(rl.supp_comm_type, tl.supp_comm_type) AS supp_comm_type,
               COALESCE(rl.supp_comm_value, tl.supp_comm_value) AS supp_comm_value,
               COALESCE(rl.supp_tds_per, tl.supp_tds_per) AS supp_tds_per,
               COALESCE(rl.supp_markup, tl.supp_markup) AS supp_markup,
               COALESCE(rl.supp_addl_markup, tl.supp_addl_markup) AS supp_addl_markup,
               COALESCE(rl.supp_service_fee, tl.supp_service_fee) AS supp_service_fee,
               COALESCE(rl.supp_addl_service_fee, tl.supp_addl_service_fee) AS supp_addl_service_fee,
               COALESCE(rl.supp_gst_pct, tl.supp_gst_pct) AS supp_gst_pct,
               COALESCE(rl.supp_ssr_markup, tl.supp_ssr_markup) AS supp_ssr_markup,
               COALESCE(rl.supp_ssr_service_fee, tl.supp_ssr_service_fee) AS supp_ssr_service_fee,
               COALESCE(rl.total_billed, tl.total_billed) AS total_billed,
               ls.name AS supplier_name
        FROM (SELECT DISTINCT CAST([value] AS NVARCHAR(30)) AS ticket_no FROM OPENJSON(@TicketNosJson)) n
        CROSS APPLY (
            SELECT TOP 1 x.pri, x.line_id FROM (
                SELECT 1 AS pri, rl0.id AS line_id
                FROM dbo.Rescheduled_Al_TicketLines rl0
                INNER JOIN dbo.Rescheduled_Al_Ticket rt0 ON rt0.id = rl0.reschedule_ticket_id
                WHERE rt0.company_id = @CompanyId AND rl0.ticket_no = n.ticket_no AND rl0.rescheduled = 0 AND rl0.canceled = 0
                UNION ALL
                SELECT 2, tl0.id
                FROM dbo.AL_TicketLines tl0
                INNER JOIN dbo.AL_Tickets t0 ON t0.id = tl0.ticket_id
                WHERE t0.company_id = @CompanyId AND tl0.ticket_no = n.ticket_no AND tl0.rescheduled = 0 AND tl0.canceled = 0
            ) x
            ORDER BY x.pri, x.line_id DESC
        ) k
        LEFT JOIN dbo.Rescheduled_Al_TicketLines rl ON k.pri = 1 AND rl.id = k.line_id
        LEFT JOIN dbo.Rescheduled_Al_Ticket rt ON rt.id = rl.reschedule_ticket_id
        LEFT JOIN dbo.AL_TicketLines tl ON k.pri = 2 AND tl.id = k.line_id
        LEFT JOIN dbo.AL_Tickets t ON t.id = tl.ticket_id
        LEFT JOIN dbo.Ledgers hc ON hc.id = COALESCE(rt.customer_ledger_id, t.customer_ledger_id)
        LEFT JOIN dbo.Ledgers hs ON hs.id = COALESCE(rt.supplier_ledger_id, t.supplier_ledger_id)
        LEFT JOIN dbo.Ledgers ls ON ls.id = COALESCE(rl.supplier_ledger_id, tl.supplier_ledger_id);
        RETURN;
    END

    IF @Action = 'MARK_IMPORTED'
    BEGIN
        UPDATE dbo.Ticket_Import_Staging
        SET process_status = 'Imported', processed_at = SYSUTCDATETIME(), target_header_id = @TargetHeaderId,
            saved_invoice_number = @InvoiceNumber, saved_voucher_no = @VoucherNo, error_message = NULL
        WHERE doc_key = @DocKey AND process_status = 'Processing';
        SELECT @@ROWCOUNT AS rows_marked, 'Imported' AS process_status;
        RETURN;
    END

    IF @Action = 'MARK_ERROR'
    BEGIN
        -- Back to Pending until @MaxRetry tries, then Error for a person to look at.
        UPDATE dbo.Ticket_Import_Staging
        SET retry_count = retry_count + 1,
            process_status = CASE WHEN retry_count + 1 >= @MaxRetry THEN 'Error' ELSE 'Pending' END,
            error_message = LEFT(ISNULL(@ErrorMessage, 'Import failed.'), 1000),
            processed_at = SYSUTCDATETIME(), picked_at = NULL
        WHERE doc_key = @DocKey AND process_status = 'Processing';
        SELECT @@ROWCOUNT AS rows_marked,
               (SELECT MAX(process_status) FROM dbo.Ticket_Import_Staging WHERE doc_key = @DocKey) AS process_status;
        RETURN;
    END

    IF @Action = 'MARK_SKIPPED'
    BEGIN
        UPDATE dbo.Ticket_Import_Staging
        SET process_status = 'Skipped', processed_at = SYSUTCDATETIME(), error_message = @ErrorMessage
        WHERE doc_key = @DocKey AND process_status IN ('Processing', 'Pending', 'Error');
        SELECT @@ROWCOUNT AS rows_marked, 'Skipped' AS process_status;
        RETURN;
    END

    IF @Action = 'FINISH_RUN'
    BEGIN
        UPDATE dbo.Ticket_Import_Run_Log
        SET finished_at = SYSUTCDATETIME(), docs_imported = ISNULL(@DocsImported, docs_imported),
            docs_failed = ISNULL(@DocsFailed, docs_failed), message = @Message
        WHERE run_id = @RunId;
        SELECT @RunId AS run_id, 'Success' AS status;
        RETURN;
    END

    SELECT 'Error' AS status, 'Unknown @Action ' + ISNULL(@Action, '') AS error;
END
GO

CREATE OR ALTER PROCEDURE dbo.sp_TicketImport_ErrorLog
    -- INSERT_JSON : @RowsJson = [ {company_id, source_system, ..., error_message}, ... ]
    -- LIST        : newest first; @FromDate / @ToDate are IST dates; @Resolved
    --               NULL = all, 0 = open, 1 = resolved; @Search matches the
    --               booking reference / parent PNR / ticket no / field / message.
    --               @Source: API = everything but the Agent DB scheduler
    --               (the Error Log page's "API Push" tab), AGENT_DB = only the
    --               scheduler's rows ("Automated Database Scheduler" tab).
    -- RESOLVE     : closes the open rows of @DocKey (it was imported later).
    @Action         NVARCHAR(20),
    @RowsJson       NVARCHAR(MAX)  = NULL,
    @CompanyId      INT            = NULL,
    @FromDate       DATE           = NULL,
    @ToDate         DATE           = NULL,
    @BookingStatus  NVARCHAR(20)   = NULL,
    @ErrorType      NVARCHAR(30)   = NULL,
    @Stage          NVARCHAR(20)   = NULL,
    @Resolved       BIT            = NULL,
    @Search         NVARCHAR(100)  = NULL,
    @DocKey         NVARCHAR(200)  = NULL,
    @Note           NVARCHAR(200)  = NULL,
    @Top            INT            = 500,
    @Source         NVARCHAR(20)   = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'INSERT_JSON'
    BEGIN
        INSERT INTO dbo.Ticket_Import_Error_Log (
            company_id, source_system, batch_id, doc_key, booking_status, booking_reference, parent_pnr,
            passenger_no, ticket_no, passenger_name, field_name, field_label, received_value, expected_value,
            error_type, severity, stage, error_message)
        SELECT j.company_id, j.source_system, j.batch_id, j.doc_key, j.booking_status, j.booking_reference, j.parent_pnr,
               j.passenger_no, j.ticket_no, j.passenger_name, j.field_name, j.field_label,
               LEFT(j.received_value, 500), LEFT(j.expected_value, 500),
               j.error_type, ISNULL(j.severity, 'Error'), j.stage, LEFT(j.error_message, 1000)
        FROM OPENJSON(@RowsJson) WITH (
            company_id INT, source_system NVARCHAR(50), batch_id NVARCHAR(50), doc_key NVARCHAR(200),
            booking_status NVARCHAR(20), booking_reference NVARCHAR(60), parent_pnr NVARCHAR(60),
            passenger_no INT, ticket_no NVARCHAR(60), passenger_name NVARCHAR(100),
            field_name NVARCHAR(100), field_label NVARCHAR(100),
            received_value NVARCHAR(MAX), expected_value NVARCHAR(MAX),
            error_type NVARCHAR(30), severity NVARCHAR(10), stage NVARCHAR(20), error_message NVARCHAR(MAX)
        ) j;
        SELECT @@ROWCOUNT AS rows_logged, 'Success' AS status;
        RETURN;
    END

    IF @Action = 'LIST'
    BEGIN
        SELECT TOP (@Top)
               e.error_log_id,
               CONVERT(DATETIME2(0), SWITCHOFFSET(CONVERT(DATETIMEOFFSET, e.logged_at), '+05:30')) AS logged_at,
               e.company_id, e.source_system, e.batch_id, e.doc_key, e.booking_status, e.booking_reference,
               e.parent_pnr, e.passenger_no, e.ticket_no, e.passenger_name, e.field_name, e.field_label,
               e.received_value, e.expected_value, e.error_type, e.severity, e.stage, e.error_message, e.is_resolved,
               CONVERT(DATETIME2(0), SWITCHOFFSET(CONVERT(DATETIMEOFFSET, e.resolved_at), '+05:30')) AS resolved_at,
               e.resolved_note
        FROM dbo.Ticket_Import_Error_Log e
        WHERE (@CompanyId IS NULL OR e.company_id = @CompanyId OR e.company_id IS NULL)
          AND (@FromDate IS NULL OR e.logged_at >= DATEADD(MINUTE, -330, CAST(@FromDate AS DATETIME2)))
          AND (@ToDate IS NULL OR e.logged_at < DATEADD(MINUTE, -330, CAST(DATEADD(DAY, 1, @ToDate) AS DATETIME2)))
          AND (@BookingStatus IS NULL OR e.booking_status = @BookingStatus)
          AND (@ErrorType IS NULL OR e.error_type = @ErrorType)
          AND (@Stage IS NULL OR e.stage = @Stage)
          AND (@Resolved IS NULL OR e.is_resolved = @Resolved)
          AND (@Source IS NULL
               OR (@Source = 'AGENT_DB' AND e.source_system = 'AGENT_DB')
               OR (@Source = 'API' AND ISNULL(e.source_system, '') <> 'AGENT_DB'))
          AND (@Search IS NULL
               OR e.booking_reference LIKE '%' + @Search + '%' OR e.parent_pnr LIKE '%' + @Search + '%'
               OR e.ticket_no LIKE '%' + @Search + '%' OR e.passenger_name LIKE '%' + @Search + '%'
               OR e.field_name LIKE '%' + @Search + '%' OR e.field_label LIKE '%' + @Search + '%'
               OR e.received_value LIKE '%' + @Search + '%' OR e.error_message LIKE '%' + @Search + '%')
        ORDER BY e.error_log_id DESC;
        RETURN;
    END

    IF @Action = 'RESOLVE'
    BEGIN
        UPDATE dbo.Ticket_Import_Error_Log
        SET is_resolved = 1, resolved_at = SYSUTCDATETIME(), resolved_note = @Note
        WHERE doc_key = @DocKey AND is_resolved = 0;
        SELECT @@ROWCOUNT AS rows_resolved, 'Success' AS status;
        RETURN;
    END

    SELECT 'Error' AS status, 'Unknown @Action ' + ISNULL(@Action, '') AS error;
END
GO

CREATE OR ALTER PROCEDURE dbo.sp_TicketImport_InvoiceType
    -- LIST : the Invoice Type picked for each Booking Status (Confirmed /
    --        Rescheduled / Cancelled / SSR) of @CompanyId.
    -- SET  : @VoucherTypeId becomes the Auto Push Invoice Type of every status
    --        in @TicketStatusesJson (taking it over from any other type) and
    --        stops being it for every status left out. Confirmed / Rescheduled /
    --        SSR need an Airline voucher type, Cancelled a Credit Note one.
    @Action              NVARCHAR(10),
    @CompanyId           INT            = NULL,
    @VoucherTypeId       INT            = NULL,
    @TicketStatusesJson  NVARCHAR(MAX)  = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'SET'
    BEGIN
        DECLARE @Category NVARCHAR(20), @Name NVARCHAR(100);
        SELECT @Category = voucher_category, @Name = name
        FROM dbo.VoucherType WHERE id = @VoucherTypeId AND company_id = @CompanyId;
        IF @Name IS NULL
        BEGIN
            SELECT 'Error' AS status, 'Voucher Type not found.' AS error;
            RETURN;
        END

        DECLARE @Wanted TABLE (ticket_status NVARCHAR(20) PRIMARY KEY);
        INSERT INTO @Wanted (ticket_status)
        SELECT DISTINCT [value] FROM OPENJSON(ISNULL(@TicketStatusesJson, '[]'));

        IF EXISTS (SELECT 1 FROM @Wanted WHERE ticket_status NOT IN ('Confirmed', 'Rescheduled', 'Cancelled', 'SSR'))
        BEGIN
            SELECT 'Error' AS status, 'Booking Status must be Confirmed, Rescheduled, Cancelled or SSR.' AS error;
            RETURN;
        END
        IF @Category <> 'Airline' AND EXISTS (SELECT 1 FROM @Wanted WHERE ticket_status IN ('Confirmed', 'Rescheduled', 'SSR'))
        BEGIN
            SELECT 'Error' AS status,
                   'Only an Airline voucher type can be the Auto Push Invoice Type for Confirmed / Rescheduled / SSR tickets.' AS error;
            RETURN;
        END
        IF @Category <> 'Credit Note' AND EXISTS (SELECT 1 FROM @Wanted WHERE ticket_status = 'Cancelled')
        BEGIN
            SELECT 'Error' AS status,
                   'Only a Credit Note voucher type can be the Auto Push Invoice Type for Cancelled tickets.' AS error;
            RETURN;
        END

        BEGIN TRAN;
        DELETE FROM dbo.Ticket_Import_Invoice_Type
        WHERE company_id = @CompanyId AND voucher_type_id = @VoucherTypeId
          AND ticket_status NOT IN (SELECT ticket_status FROM @Wanted);

        MERGE dbo.Ticket_Import_Invoice_Type AS t
        USING (SELECT ticket_status FROM @Wanted) AS w
           ON t.company_id = @CompanyId AND t.ticket_status = w.ticket_status
        WHEN MATCHED THEN UPDATE SET voucher_type_id = @VoucherTypeId, updated_at = SYSUTCDATETIME()
        WHEN NOT MATCHED THEN INSERT (company_id, ticket_status, voucher_type_id) VALUES (@CompanyId, w.ticket_status, @VoucherTypeId);
        COMMIT TRAN;
        SET @Action = 'LIST';
    END

    IF @Action = 'LIST'
    BEGIN
        SELECT t.ticket_status, t.voucher_type_id, v.name AS voucher_type_name, v.voucher_category, v.is_active,
               'Success' AS status
        FROM dbo.Ticket_Import_Invoice_Type t
        INNER JOIN dbo.VoucherType v ON v.id = t.voucher_type_id
        WHERE t.company_id = @CompanyId
        ORDER BY CASE t.ticket_status WHEN 'Confirmed' THEN 1 WHEN 'Rescheduled' THEN 2 WHEN 'SSR' THEN 3 ELSE 4 END;
        RETURN;
    END

    SELECT 'Error' AS status, 'Unknown @Action ' + ISNULL(@Action, '') AS error;
END
GO

CREATE OR ALTER PROCEDURE dbo.sp_MasterMappingPin
    -- LIST                 : every pin of @CompanyId, with the pinned ledger's GST %.
    -- DOCUMENTS            : saved documents of @CompanyId dated @FromDate or later that
    --                        @ProductType's mapping applies to (Airline: Booking,
    --                        Reschedule, Cancellation, SSR Updation and Miscellaneous -
    --                        Misc falls back to Airline for Output / Input GST;
    --                        Miscellaneous: Miscellaneous only). doc_date = the date
    --                        the document's mappings are resolved for.
    -- SAVE_JSON            : @RowsJson pins; a document already pinned for the field keeps its pin.
    -- DELETE_FIELD         : pins of @FieldName on documents dated @FromDate or later.
    -- DELETE_DOCUMENT      : every pin of one document (@DocType, @DocId) - it was edited.
    -- DELETE_HISTORY_AFTER : Ledger Mapping history rows of @FieldName dated after @FromDate.
    @Action        NVARCHAR(30),
    @CompanyId     INT            = NULL,
    @ProductType   NVARCHAR(20)   = NULL,
    @FieldName     NVARCHAR(100)  = NULL,
    @FromDate      DATE           = NULL,
    @DocType       NVARCHAR(20)   = NULL,
    @DocId         INT            = NULL,
    @RowsJson      NVARCHAR(MAX)  = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'LIST'
    BEGIN
        SELECT p.product_type, p.field_name, p.doc_type, p.doc_id, p.doc_date, p.ledger_id,
               COALESCE(NULLIF(l.alias_name, ''), l.name, p.ledger_name) AS ledger_name,
               ISNULL(l.gst_percentage, 0) AS ledger_gst_percentage, p.masters_category, p.effective_from
        FROM dbo.MasterMappingPin p
        LEFT JOIN dbo.Ledgers l ON l.id = p.ledger_id
        WHERE p.company_id = @CompanyId;
        RETURN;
    END

    IF @Action = 'DOCUMENTS'
    BEGIN
        SELECT doc_type, doc_id, doc_no, doc_date FROM (
            SELECT 'ticket' AS doc_type, id AS doc_id, invoice_number AS doc_no,
                   COALESCE(invoice_date, booking_ref_date) AS doc_date
            FROM dbo.AL_Tickets WHERE company_id = @CompanyId AND @ProductType = 'Airline'
            UNION ALL
            SELECT 'reschedule', id, invoice_number, COALESCE(invoice_date, booking_ref_date)
            FROM dbo.Rescheduled_Al_Ticket WHERE company_id = @CompanyId AND @ProductType = 'Airline'
            UNION ALL
            SELECT 'cancellation', id, invoice_number, COALESCE(invoice_date, cancellation_ref_date)
            FROM dbo.Cancellation_AL_Tickets WHERE company_id = @CompanyId AND @ProductType = 'Airline'
            UNION ALL
            SELECT 'ssr', id, invoice_number, invoice_date
            FROM dbo.SSR_AL_Tickets WHERE company_id = @CompanyId AND @ProductType = 'Airline'
            UNION ALL
            SELECT 'misc', id, invoice_number, invoice_date
            FROM dbo.Misc_Transactions WHERE company_id = @CompanyId AND @ProductType IN ('Airline', 'Miscellaneous')
        ) d
        WHERE d.doc_date >= @FromDate
        ORDER BY d.doc_date, d.doc_type, d.doc_id;
        RETURN;
    END

    IF @Action = 'SAVE_JSON'
    BEGIN
        INSERT INTO dbo.MasterMappingPin
            (company_id, product_type, field_name, doc_type, doc_id, doc_date, ledger_id, ledger_name, masters_category, effective_from)
        SELECT j.company_id, j.product_type, j.field_name, j.doc_type, j.doc_id, j.doc_date, j.ledger_id, j.ledger_name,
               j.masters_category, j.effective_from
        FROM OPENJSON(@RowsJson) WITH (
            company_id INT, product_type NVARCHAR(20), field_name NVARCHAR(100), doc_type NVARCHAR(20), doc_id INT,
            doc_date DATE, ledger_id INT, ledger_name NVARCHAR(200), masters_category NVARCHAR(40), effective_from DATE
        ) j
        WHERE NOT EXISTS (SELECT 1 FROM dbo.MasterMappingPin p
                          WHERE p.company_id = j.company_id AND p.product_type = j.product_type
                            AND p.field_name = j.field_name AND p.doc_type = j.doc_type AND p.doc_id = j.doc_id);
        SELECT @@ROWCOUNT AS rows_pinned, 'Success' AS status;
        RETURN;
    END

    IF @Action = 'DELETE_FIELD'
    BEGIN
        DELETE FROM dbo.MasterMappingPin
        WHERE company_id = @CompanyId AND product_type = @ProductType AND field_name = @FieldName AND doc_date >= @FromDate;
        SELECT @@ROWCOUNT AS rows_deleted, 'Success' AS status;
        RETURN;
    END

    IF @Action = 'DELETE_DOCUMENT'
    BEGIN
        DELETE FROM dbo.MasterMappingPin WHERE doc_type = @DocType AND doc_id = @DocId;
        SELECT @@ROWCOUNT AS rows_deleted, 'Success' AS status;
        RETURN;
    END

    IF @Action = 'DELETE_HISTORY_AFTER'
    BEGIN
        DELETE FROM dbo.MasterMappingHistory
        WHERE company_id = @CompanyId AND product_type = @ProductType AND field_name = @FieldName
          AND effective_from > @FromDate;
        SELECT @@ROWCOUNT AS rows_deleted, 'Success' AS status;
        RETURN;
    END

    SELECT 'Error' AS status, 'Unknown @Action ' + ISNULL(@Action, '') AS error;
END
GO

CREATE OR ALTER PROCEDURE dbo.sp_TicketLineGstAmount
    -- LIST            : every line's GST amounts.
    -- SAVE_JSON       : @RowsJson rows (insert or replace by line_type + doc_id + ticket_no).
    -- DELETE_DOCUMENT : every row of one document (@LineType, @DocId) - it was edited on screen.
    @Action      NVARCHAR(20),
    @RowsJson    NVARCHAR(MAX) = NULL,
    @LineType    NVARCHAR(20)  = NULL,
    @DocId       INT           = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'LIST'
    BEGIN
        SELECT line_type, doc_id, ticket_no, service_fee_gst, addl_service_fee_gst, ssr_service_fee_gst,
               supp_service_fee_gst, supp_addl_service_fee_gst, supp_ssr_service_fee_gst
        FROM dbo.Ticket_Line_Gst_Amount;
        RETURN;
    END

    IF @Action = 'SAVE_JSON'
    BEGIN
        MERGE dbo.Ticket_Line_Gst_Amount AS t
        USING (
            SELECT * FROM OPENJSON(@RowsJson) WITH (
                line_type NVARCHAR(20), doc_id INT, ticket_no NVARCHAR(30),
                service_fee_gst DECIMAL(14,2), addl_service_fee_gst DECIMAL(14,2), ssr_service_fee_gst DECIMAL(14,2),
                supp_service_fee_gst DECIMAL(14,2), supp_addl_service_fee_gst DECIMAL(14,2), supp_ssr_service_fee_gst DECIMAL(14,2)
            )
        ) AS s ON t.line_type = s.line_type AND t.doc_id = s.doc_id AND t.ticket_no = s.ticket_no
        WHEN MATCHED THEN UPDATE SET
            service_fee_gst = s.service_fee_gst, addl_service_fee_gst = s.addl_service_fee_gst,
            ssr_service_fee_gst = s.ssr_service_fee_gst, supp_service_fee_gst = s.supp_service_fee_gst,
            supp_addl_service_fee_gst = s.supp_addl_service_fee_gst, supp_ssr_service_fee_gst = s.supp_ssr_service_fee_gst
        WHEN NOT MATCHED THEN INSERT
            (line_type, doc_id, ticket_no, service_fee_gst, addl_service_fee_gst, ssr_service_fee_gst,
             supp_service_fee_gst, supp_addl_service_fee_gst, supp_ssr_service_fee_gst)
            VALUES (s.line_type, s.doc_id, s.ticket_no, s.service_fee_gst, s.addl_service_fee_gst, s.ssr_service_fee_gst,
                    s.supp_service_fee_gst, s.supp_addl_service_fee_gst, s.supp_ssr_service_fee_gst);
        SELECT @@ROWCOUNT AS rows_saved, 'Success' AS status;
        RETURN;
    END

    IF @Action = 'DELETE_DOCUMENT'
    BEGIN
        DELETE FROM dbo.Ticket_Line_Gst_Amount WHERE line_type = @LineType AND doc_id = @DocId;
        SELECT @@ROWCOUNT AS rows_deleted, 'Success' AS status;
        RETURN;
    END

    SELECT 'Error' AS status, 'Unknown @Action ' + ISNULL(@Action, '') AS error;
END
GO

-- ==========================================================================
-- Procedure : dbo.sp_TicketImport_KnownTickets (migration 0082)
-- Auto Push direct Reschedule / Cancellation: which Ticket Nos. this software
-- already has (Booking, Reschedule or Cancellation, any state). A ticket not
-- found anywhere is saved direct; a known one that is no longer live is refused.
-- ==========================================================================
CREATE OR ALTER PROCEDURE dbo.sp_TicketImport_KnownTickets
    @CompanyId      INT,
    @TicketNosJson  NVARCHAR(MAX)            -- ["6E123", ...]
AS
BEGIN
    SET NOCOUNT ON;
    SELECT n.ticket_no,
           CASE WHEN EXISTS (SELECT 1 FROM dbo.Cancellation_Al_TicketLines cl
                             INNER JOIN dbo.Cancellation_AL_Tickets c ON c.id = cl.cancellation_ticket_id
                             WHERE c.company_id = @CompanyId AND cl.ticket_no = n.ticket_no) THEN 'Cancellation'
                WHEN EXISTS (SELECT 1 FROM dbo.Rescheduled_Al_TicketLines rl
                             INNER JOIN dbo.Rescheduled_Al_Ticket r ON r.id = rl.reschedule_ticket_id
                             WHERE r.company_id = @CompanyId AND rl.ticket_no = n.ticket_no) THEN 'Reschedule'
                ELSE 'Booking' END AS found_on
    FROM (SELECT DISTINCT CAST([value] AS NVARCHAR(30)) AS ticket_no FROM OPENJSON(@TicketNosJson)) n
    WHERE EXISTS (SELECT 1 FROM dbo.AL_TicketLines tl INNER JOIN dbo.AL_Tickets t ON t.id = tl.ticket_id
                  WHERE t.company_id = @CompanyId AND tl.ticket_no = n.ticket_no)
       OR EXISTS (SELECT 1 FROM dbo.Rescheduled_Al_TicketLines rl INNER JOIN dbo.Rescheduled_Al_Ticket r ON r.id = rl.reschedule_ticket_id
                  WHERE r.company_id = @CompanyId AND rl.ticket_no = n.ticket_no)
       OR EXISTS (SELECT 1 FROM dbo.Cancellation_Al_TicketLines cl INNER JOIN dbo.Cancellation_AL_Tickets c ON c.id = cl.cancellation_ticket_id
                  WHERE c.company_id = @CompanyId AND cl.ticket_no = n.ticket_no);
END
GO

-- ==========================================================================
-- Procedure : dbo.sp_DocumentAttribute (migration 0083)
-- Ticket Entry Attributes popup - LIST / SAVE_JSON of a document's Field / Value rows.
-- ==========================================================================
CREATE OR ALTER PROCEDURE dbo.sp_DocumentAttribute
    -- LIST      : one document's Field / Value rows, in order.
    -- SAVE_JSON : replaces one document's rows with @RowsJson
    --             ([{"field_name", "field_value"}, ...] - rows without a Field are skipped).
    @Action         NVARCHAR(20),
    @CompanyId      INT            = NULL,
    @DocType        NVARCHAR(20)   = NULL,
    @DocId          INT            = NULL,
    @InvoiceNumber  NVARCHAR(20)   = NULL,
    @RowsJson       NVARCHAR(MAX)  = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'LIST'
    BEGIN
        SELECT attribute_id, company_id, doc_type, doc_id, invoice_number, sort_order, field_name, field_value
        FROM dbo.Ticket_Document_Attribute
        WHERE doc_type = @DocType AND doc_id = @DocId
        ORDER BY sort_order, attribute_id;
        RETURN;
    END

    IF @Action = 'SAVE_JSON'
    BEGIN
        BEGIN TRY
            BEGIN TRAN;
            DELETE FROM dbo.Ticket_Document_Attribute WHERE doc_type = @DocType AND doc_id = @DocId;
            INSERT INTO dbo.Ticket_Document_Attribute (company_id, doc_type, doc_id, invoice_number, sort_order, field_name, field_value)
            SELECT @CompanyId, @DocType, @DocId, @InvoiceNumber,
                   ROW_NUMBER() OVER (ORDER BY CAST(j.[key] AS INT)),
                   LTRIM(RTRIM(v.field_name)), NULLIF(LTRIM(RTRIM(v.field_value)), '')
            FROM OPENJSON(@RowsJson) j
            CROSS APPLY OPENJSON(j.[value]) WITH (
                field_name  NVARCHAR(100) '$.field_name',
                field_value NVARCHAR(500) '$.field_value'
            ) v
            WHERE NULLIF(LTRIM(RTRIM(v.field_name)), '') IS NOT NULL;
            DECLARE @Saved INT = @@ROWCOUNT;
            COMMIT TRAN;
            SELECT 'Success' AS status, @Saved AS saved;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END
END
GO

-- ==========================================================================
-- Procedure : dbo.sp_PGMasterBackdate (migration 0084)
-- PG Master Effective From before today - Replace / Retain (like Ledger Mapping).
-- ==========================================================================
CREATE OR ALTER PROCEDURE dbo.sp_PGMasterBackdate
    -- PG Master Effective From before today (like Ledger Mapping):
    -- DOCUMENTS            : saved Booking / Reschedule / Cancellation paid through @GatewayName, dated @FromDate or later.
    -- LATER_HISTORY        : the gateway's history rows dated @FromDate or later (replaced by the new values).
    -- DELETE_HISTORY_AFTER : drops the gateway's history rows dated after @FromDate.
    -- PINS_SAVE_JSON       : "Retain old ledgers" - @RowsJson pins (one per document, insert or replace).
    -- PINS_DELETE_GATEWAY  : "Replace all" - the gateway's pins on documents dated @FromDate or later.
    -- PINS_DELETE_DOCUMENT : a document edited on screen takes today's PG settings.
    @Action        NVARCHAR(30),
    @CompanyId     INT            = NULL,
    @GatewayName   NVARCHAR(100)  = NULL,
    @FromDate      DATE           = NULL,
    @DocType       NVARCHAR(20)   = NULL,
    @DocId         INT            = NULL,
    @RowsJson      NVARCHAR(MAX)  = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'DOCUMENTS'
    BEGIN
        SELECT 'ticket' AS doc_type, t.id AS doc_id, t.invoice_number, COALESCE(t.invoice_date, t.booking_ref_date) AS doc_date
        FROM dbo.AL_Tickets t
        WHERE t.company_id = @CompanyId AND t.payment_mode = 'Payment Gateway' AND t.payment_gateway_ref = @GatewayName
          AND COALESCE(t.invoice_date, t.booking_ref_date) >= @FromDate
        UNION ALL
        SELECT 'reschedule', r.id, r.invoice_number, COALESCE(r.invoice_date, r.booking_ref_date)
        FROM dbo.Rescheduled_Al_Ticket r
        WHERE r.company_id = @CompanyId AND r.payment_mode = 'Payment Gateway' AND r.payment_gateway_ref = @GatewayName
          AND COALESCE(r.invoice_date, r.booking_ref_date) >= @FromDate
        UNION ALL
        SELECT 'cancellation', c.id, c.invoice_number, COALESCE(c.invoice_date, c.cancellation_ref_date)
        FROM dbo.Cancellation_AL_Tickets c
        WHERE c.company_id = @CompanyId AND c.payment_mode = 'Payment Gateway' AND c.payment_gateway_ref = @GatewayName
          AND COALESCE(c.invoice_date, c.cancellation_ref_date) >= @FromDate
        ORDER BY doc_date, doc_type, doc_id;
        RETURN;
    END

    IF @Action = 'LATER_HISTORY'
    BEGIN
        SELECT h.effective_from, h.payment_master_ledger_name, h.pg_charges_master_ledger_name, h.pg_charges_percentage
        FROM dbo.PGMasterHistory h
        INNER JOIN dbo.PGMaster p ON p.id = h.pg_master_id
        WHERE p.company_id = @CompanyId AND p.gateway_name = @GatewayName AND h.effective_from >= @FromDate
        ORDER BY h.effective_from;
        RETURN;
    END

    IF @Action = 'DELETE_HISTORY_AFTER'
    BEGIN
        DELETE h FROM dbo.PGMasterHistory h
        INNER JOIN dbo.PGMaster p ON p.id = h.pg_master_id
        WHERE p.company_id = @CompanyId AND p.gateway_name = @GatewayName AND h.effective_from > @FromDate;
        SELECT @@ROWCOUNT AS deleted;
        RETURN;
    END

    IF @Action = 'PINS_SAVE_JSON'
    BEGIN
        MERGE dbo.PGMasterPin AS tgt
        USING (
            SELECT * FROM OPENJSON(@RowsJson) WITH (
                company_id INT '$.company_id', gateway_name NVARCHAR(100) '$.gateway_name',
                doc_type NVARCHAR(20) '$.doc_type', doc_id INT '$.doc_id', doc_date DATE '$.doc_date',
                payment_master_ledger_id INT '$.payment_master_ledger_id',
                payment_master_ledger_name NVARCHAR(200) '$.payment_master_ledger_name',
                pg_charges_master_ledger_id INT '$.pg_charges_master_ledger_id',
                pg_charges_master_ledger_name NVARCHAR(200) '$.pg_charges_master_ledger_name',
                pg_charges_percentage DECIMAL(5,2) '$.pg_charges_percentage',
                effective_from DATE '$.effective_from'
            )
        ) AS src
        ON tgt.company_id = src.company_id AND tgt.doc_type = src.doc_type AND tgt.doc_id = src.doc_id
        WHEN MATCHED THEN UPDATE SET
            gateway_name = src.gateway_name, doc_date = src.doc_date,
            payment_master_ledger_id = src.payment_master_ledger_id, payment_master_ledger_name = src.payment_master_ledger_name,
            pg_charges_master_ledger_id = src.pg_charges_master_ledger_id, pg_charges_master_ledger_name = src.pg_charges_master_ledger_name,
            pg_charges_percentage = src.pg_charges_percentage, effective_from = src.effective_from
        WHEN NOT MATCHED THEN INSERT
            (company_id, gateway_name, doc_type, doc_id, doc_date, payment_master_ledger_id, payment_master_ledger_name,
             pg_charges_master_ledger_id, pg_charges_master_ledger_name, pg_charges_percentage, effective_from)
        VALUES
            (src.company_id, src.gateway_name, src.doc_type, src.doc_id, src.doc_date, src.payment_master_ledger_id,
             src.payment_master_ledger_name, src.pg_charges_master_ledger_id, src.pg_charges_master_ledger_name,
             src.pg_charges_percentage, src.effective_from);
        SELECT @@ROWCOUNT AS saved;
        RETURN;
    END

    IF @Action = 'PINS_DELETE_GATEWAY'
    BEGIN
        DELETE FROM dbo.PGMasterPin
        WHERE company_id = @CompanyId AND gateway_name = @GatewayName AND (@FromDate IS NULL OR doc_date >= @FromDate);
        SELECT @@ROWCOUNT AS deleted;
        RETURN;
    END

    IF @Action = 'PINS_DELETE_DOCUMENT'
    BEGIN
        DELETE FROM dbo.PGMasterPin WHERE doc_type = @DocType AND doc_id = @DocId;
        SELECT @@ROWCOUNT AS deleted;
        RETURN;
    END
END
GO

-- ==========================================================================
-- Procedure : dbo.sp_AgentDbScheduler_Log (migration 0085)
-- Runs of the Automated Database Scheduler (Airline_Agent -> invoices).
-- ==========================================================================
CREATE OR ALTER PROCEDURE dbo.sp_AgentDbScheduler_Log
    -- INSERT : one scheduler run that fetched rows from the Airline_Agent
    --          database (a run with nothing to fetch is not logged).
    -- LIST   : newest first; times in IST; @FromDate / @ToDate are IST dates.
    @Action           NVARCHAR(20),
    @RunStartedAt     DATETIME2      = NULL,
    @RunFinishedAt    DATETIME2      = NULL,
    @SourceDatabase   NVARCHAR(128)  = NULL,
    @SourceTable      NVARCHAR(128)  = NULL,
    @RecordsFetched   INT            = NULL,
    @InvoicesFetched  INT            = NULL,
    @ImportedCount    INT            = NULL,
    @PendingCount     INT            = NULL,
    @ErrorCount       INT            = NULL,
    @Message          NVARCHAR(1000) = NULL,
    @FromDate         DATE           = NULL,
    @ToDate           DATE           = NULL,
    @Top              INT            = 200
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'INSERT'
    BEGIN
        INSERT INTO dbo.Agent_DB_Scheduler_Log (
            run_started_at, run_finished_at, source_database, source_table, records_fetched, invoices_fetched,
            imported_count, pending_count, error_count, message)
        VALUES (@RunStartedAt, @RunFinishedAt, @SourceDatabase, @SourceTable, ISNULL(@RecordsFetched, 0),
                ISNULL(@InvoicesFetched, 0), ISNULL(@ImportedCount, 0), ISNULL(@PendingCount, 0),
                ISNULL(@ErrorCount, 0), @Message);
        SELECT CAST(SCOPE_IDENTITY() AS BIGINT) AS log_id, 'Success' AS status;
        RETURN;
    END

    IF @Action = 'LIST'
    BEGIN
        SELECT TOP (@Top)
               l.log_id,
               CONVERT(DATETIME2(0), SWITCHOFFSET(CONVERT(DATETIMEOFFSET, l.run_started_at), '+05:30')) AS run_started_at,
               CONVERT(DATETIME2(0), SWITCHOFFSET(CONVERT(DATETIMEOFFSET, l.run_finished_at), '+05:30')) AS run_finished_at,
               l.source_database, l.source_table, l.records_fetched, l.invoices_fetched,
               l.imported_count, l.pending_count, l.error_count, l.message
        FROM dbo.Agent_DB_Scheduler_Log l
        WHERE (@FromDate IS NULL OR l.run_started_at >= DATEADD(MINUTE, -330, CAST(@FromDate AS DATETIME2)))
          AND (@ToDate IS NULL OR l.run_started_at < DATEADD(MINUTE, -330, CAST(DATEADD(DAY, 1, @ToDate) AS DATETIME2)))
        ORDER BY l.log_id DESC;
        RETURN;
    END

    SELECT 'Error' AS status, 'Unknown @Action ' + ISNULL(@Action, '') AS error;
END
GO

-- ==========================================================================
-- Procedure : dbo.sp_AgentDbTicketLog (migration 0086)
-- Automated Database Scheduler - one log row per Agent row picked up.
-- ==========================================================================
CREATE OR ALTER PROCEDURE dbo.sp_AgentDbTicketLog
    -- One row per Agent row (passenger) the Automated Database Scheduler
    -- picked up - the Agent's own table is only read, never written.
    -- CLAIM_JSON  : first drops 'Processing' rows older than @StuckMinutes (a
    --               run that died - they are picked up again), then inserts
    --               @RowsJson [{agent_row_id, company_id, booking_status,
    --               booking_reference, ticket_no, pax_name}] as 'Processing';
    --               returns the agent_row_ids claimed (already logged = skipped).
    -- RESULT_JSON : @RowsJson [{agent_row_id, process_status, invoice_number,
    --               voucher_no, import_doc_key, error_message}].
    -- RELEASE_JSON: deletes the 'Processing' rows of @RowsJson [{agent_row_id}]
    --               (the run failed - they are picked up again).
    -- SET_RUN     : @SchedulerLogId on the rows of @RowsJson [{agent_row_id}].
    -- WAITING     : company_id + import_doc_key of rows still Pending / Error.
    -- REFRESH     : the final import status of @DocKey (saved later by the
    --               Ticket Import Scheduler) onto its Pending / Error rows.
    @Action          NVARCHAR(20),
    @SourceDatabase  NVARCHAR(128)  = NULL,
    @SourceTable     NVARCHAR(128)  = NULL,
    @RowsJson        NVARCHAR(MAX)  = NULL,
    @StuckMinutes    INT            = 30,
    @SchedulerLogId  BIGINT         = NULL,
    @DocKey          NVARCHAR(200)  = NULL,
    @ProcessStatus   NVARCHAR(20)   = NULL,
    @InvoiceNumber   NVARCHAR(30)   = NULL,
    @VoucherNo       NVARCHAR(30)   = NULL,
    @ErrorMessage    NVARCHAR(2000) = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'CLAIM_JSON'
    BEGIN
        DELETE FROM dbo.Agent_DB_Ticket_Log
        WHERE source_database = @SourceDatabase AND source_table = @SourceTable
          AND process_status = 'Processing' AND processing_at < DATEADD(MINUTE, -@StuckMinutes, SYSUTCDATETIME());

        INSERT INTO dbo.Agent_DB_Ticket_Log (
            source_database, source_table, agent_row_id, company_id, booking_status, booking_reference,
            ticket_no, pax_name, process_status)
        OUTPUT inserted.agent_row_id
        SELECT @SourceDatabase, @SourceTable, j.agent_row_id, j.company_id, j.booking_status, j.booking_reference,
               j.ticket_no, j.pax_name, 'Processing'
        FROM OPENJSON(@RowsJson) WITH (
            agent_row_id BIGINT, company_id INT, booking_status NVARCHAR(100), booking_reference NVARCHAR(100),
            ticket_no NVARCHAR(100), pax_name NVARCHAR(100)
        ) j
        WHERE NOT EXISTS (SELECT 1 FROM dbo.Agent_DB_Ticket_Log l
                          WHERE l.source_database = @SourceDatabase AND l.source_table = @SourceTable
                            AND l.agent_row_id = j.agent_row_id);
        RETURN;
    END

    IF @Action = 'RESULT_JSON'
    BEGIN
        UPDATE l
        SET process_status = j.process_status, processed_at = SYSUTCDATETIME(), invoice_number = j.invoice_number,
            voucher_no = j.voucher_no, import_doc_key = j.import_doc_key, error_message = LEFT(j.error_message, 2000)
        FROM dbo.Agent_DB_Ticket_Log l
        JOIN OPENJSON(@RowsJson) WITH (
            agent_row_id BIGINT, process_status NVARCHAR(20), invoice_number NVARCHAR(30), voucher_no NVARCHAR(30),
            import_doc_key NVARCHAR(200), error_message NVARCHAR(MAX)
        ) j ON j.agent_row_id = l.agent_row_id
        WHERE l.source_database = @SourceDatabase AND l.source_table = @SourceTable;
        SELECT @@ROWCOUNT AS updated;
        RETURN;
    END

    IF @Action = 'RELEASE_JSON'
    BEGIN
        DELETE l
        FROM dbo.Agent_DB_Ticket_Log l
        JOIN OPENJSON(@RowsJson) WITH (agent_row_id BIGINT) j ON j.agent_row_id = l.agent_row_id
        WHERE l.source_database = @SourceDatabase AND l.source_table = @SourceTable AND l.process_status = 'Processing';
        SELECT @@ROWCOUNT AS released;
        RETURN;
    END

    IF @Action = 'SET_RUN'
    BEGIN
        UPDATE l SET scheduler_log_id = @SchedulerLogId
        FROM dbo.Agent_DB_Ticket_Log l
        JOIN OPENJSON(@RowsJson) WITH (agent_row_id BIGINT) j ON j.agent_row_id = l.agent_row_id
        WHERE l.source_database = @SourceDatabase AND l.source_table = @SourceTable;
        SELECT @@ROWCOUNT AS updated;
        RETURN;
    END

    IF @Action = 'WAITING'
    BEGIN
        SELECT DISTINCT company_id, import_doc_key
        FROM dbo.Agent_DB_Ticket_Log
        WHERE process_status IN ('Pending', 'Error') AND import_doc_key IS NOT NULL;
        RETURN;
    END

    IF @Action = 'REFRESH'
    BEGIN
        UPDATE dbo.Agent_DB_Ticket_Log
        SET process_status = @ProcessStatus, processed_at = SYSUTCDATETIME(), invoice_number = @InvoiceNumber,
            voucher_no = @VoucherNo, error_message = @ErrorMessage
        WHERE import_doc_key = @DocKey AND process_status IN ('Pending', 'Error')
          AND (process_status <> @ProcessStatus OR ISNULL(error_message, N'') <> ISNULL(@ErrorMessage, N''));
        SELECT @@ROWCOUNT AS updated;
        RETURN;
    END

    SELECT 'Error' AS status, 'Unknown @Action ' + ISNULL(@Action, '') AS error;
END
GO
