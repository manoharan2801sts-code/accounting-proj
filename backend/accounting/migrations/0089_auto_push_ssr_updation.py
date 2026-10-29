from django.db import migrations

# Auto Push Booking Status SSR (SSR Updation) - API and Agent database:
#   Ticket_Import_Staging / Ticket_Import_Invoice_Type - ticket_status may be 'SSR'
#   AirlineDropdownValues  - bookingStatuses code SSR = "SSR Updated"
#   sp_SSRTicket           - @BookingMode (Auto Push); the screen still saves Manual
#   sp_TicketImport_Scheduler   - SSR documents saved after Booking / Reschedule, before Cancellation
#   sp_TicketImport_InvoiceType - SSR takes an Airline voucher type (Voucher Type > Auto Push Invoice For)
# Booking / Reschedule / Cancellation are unchanged. Mirrored in Schema.sql and StoredProcedures.sql.

TABLE_SQL = """
-- Booking Status SSR (SSR Updation) for Auto Push.
IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'ck_tis_ticket_status')
    ALTER TABLE dbo.Ticket_Import_Staging DROP CONSTRAINT ck_tis_ticket_status;
ALTER TABLE dbo.Ticket_Import_Staging ADD CONSTRAINT ck_tis_ticket_status
    CHECK (ticket_status IN ('Confirmed', 'Rescheduled', 'Cancelled', 'SSR'));
IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'ck_tiit_ticket_status')
    ALTER TABLE dbo.Ticket_Import_Invoice_Type DROP CONSTRAINT ck_tiit_ticket_status;
ALTER TABLE dbo.Ticket_Import_Invoice_Type ADD CONSTRAINT ck_tiit_ticket_status
    CHECK (ticket_status IN ('Confirmed', 'Rescheduled', 'Cancelled', 'SSR'));
IF NOT EXISTS (SELECT 1 FROM dbo.AirlineDropdownValues WHERE list_key = N'bookingStatuses' AND (code = N'SSR' OR name = N'SSR Updated'))
    INSERT INTO dbo.AirlineDropdownValues (list_key, code, name, display_label, sort_order, is_default, is_active, created_at, updated_at)
    VALUES (N'bookingStatuses', N'SSR', N'SSR Updated', NULL, 40, 0, 1, SYSUTCDATETIME(), SYSUTCDATETIME());
"""

REVERSE_SQL = """
DELETE FROM dbo.AirlineDropdownValues WHERE list_key = N'bookingStatuses' AND code = N'SSR';
ALTER TABLE dbo.Ticket_Import_Staging DROP CONSTRAINT ck_tis_ticket_status;
ALTER TABLE dbo.Ticket_Import_Staging ADD CONSTRAINT ck_tis_ticket_status CHECK (ticket_status IN ('Confirmed', 'Rescheduled', 'Cancelled'));
ALTER TABLE dbo.Ticket_Import_Invoice_Type DROP CONSTRAINT ck_tiit_ticket_status;
ALTER TABLE dbo.Ticket_Import_Invoice_Type ADD CONSTRAINT ck_tiit_ticket_status CHECK (ticket_status IN ('Confirmed', 'Rescheduled', 'Cancelled'));
"""

PROC_1_SQL = """
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
    @BookingMode               NVARCHAR(20)    = NULL,   -- 'Auto Push' from ticket_import; NULL = Manual (the screen)
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
               ot.invoice_number AS original_invoice_number, rt.invoice_number AS source_reschedule_invoice_number,
               jv.id AS voucher_id, jv.voucher_no, jv.total_debit AS jv_total_debit, jv.total_credit AS jv_total_credit,
               'Success' AS status
        FROM dbo.SSR_AL_Tickets st
        INNER JOIN dbo.Ledgers cust ON cust.id = st.customer_ledger_id
        INNER JOIN dbo.AL_Tickets ot ON ot.id = st.original_ticket_id
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

        IF NOT EXISTS (SELECT 1 FROM dbo.AL_Tickets WHERE id = @OriginalTicketId AND company_id = @CompanyId)
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

        -- Every line must be a passenger of the original booking.
        SELECT TOP 1 @BadLine = ISNULL(j.ticket_no, '?')
        FROM OPENJSON(@LinesJson) WITH (original_ticket_line_id INT '$.original_ticket_line_id', ticket_no NVARCHAR(30) '$.ticket_no') j
        WHERE NOT EXISTS (SELECT 1 FROM dbo.AL_TicketLines tl WHERE tl.id = j.original_ticket_line_id AND tl.ticket_id = @OriginalTicketId);
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
                     ssr_reference, ssr_ref_date, airline_pnr, gds_pnr, payment_mode, payment_gateway_ref, created_at, updated_at)
                VALUES
                    (@CompanyId, @BranchName, @OriginalTicketId, @SourceRescheduleTicketId, @InvoiceNumber, @InvoiceDate,
                     @InvoiceType, ISNULL(NULLIF(@BookingMode, ''), 'Manual'), 'SSR Updated', @CustLedgerId, @TravelType, @UserName, ISNULL(@Currency, 'INR'), ISNULL(@Roe, 1),
                     @SsrReference, @SsrRefDate, @AirlinePnr, @GdsPnr, @PaymentMode, @PaymentGatewayRef, SYSUTCDATETIME(), SYSUTCDATETIME());
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
"""

PROC_2_SQL = """
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
"""

PROC_3_SQL = """
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
"""


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0088_ssr_reference_not_unique"),
    ]

    operations = [
        migrations.RunSQL(TABLE_SQL, REVERSE_SQL),
        migrations.RunSQL(PROC_1_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(PROC_2_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(PROC_3_SQL, migrations.RunSQL.noop),
    ]
