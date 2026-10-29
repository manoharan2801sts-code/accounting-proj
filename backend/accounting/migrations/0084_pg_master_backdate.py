from django.db import migrations

# PG Master - Effective From before today (like Ledger Mapping). Saved
# Booking / Reschedule / Cancellation JVs read the PG Master snapshot in force
# on their date, so a back-dated change is confirmed on screen first:
#   "replace" - every document dated from then on (saved ones too) takes it;
#   "retain"  - saved documents keep the PG settings they use now (pinned);
#               only new / edited documents take the new ones.
# Either way the gateway's later history rows are replaced.
#   dbo.PGMasterPin           - one pin per saved document ("retain")
#   dbo.sp_PGMasterBackdate   - DOCUMENTS / LATER_HISTORY / DELETE_HISTORY_AFTER / PINS_*
#   dbo.sp_PGMaster           - EFFECTIVE_SNAPSHOT: @DocType / @DocId - a pin wins
# Mirrored in Schema.sql and StoredProcedures.sql.

TABLE_SQL = """
IF OBJECT_ID('dbo.PGMasterPin', 'U') IS NULL
CREATE TABLE dbo.PGMasterPin (
    pin_id                          INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_pgmp PRIMARY KEY,
    company_id                      INT            NOT NULL,
    gateway_name                    NVARCHAR(100)  NOT NULL,
    doc_type                        NVARCHAR(20)   NOT NULL
        CONSTRAINT ck_pgmp_doc_type CHECK (doc_type IN ('ticket', 'reschedule', 'cancellation')),
    doc_id                          INT            NOT NULL,      -- AL_Tickets / Rescheduled_Al_Ticket / Cancellation_AL_Tickets id
    doc_date                        DATE           NULL,
    payment_master_ledger_id        INT            NULL,
    payment_master_ledger_name      NVARCHAR(200)  NULL,
    pg_charges_master_ledger_id     INT            NULL,
    pg_charges_master_ledger_name   NVARCHAR(200)  NULL,
    pg_charges_percentage           DECIMAL(5,2)   NULL,
    effective_from                  DATE           NULL,          -- Effective From of the snapshot the document was pinned to
    created_at                      DATETIME2      NOT NULL CONSTRAINT df_pgmp_created DEFAULT SYSUTCDATETIME(),
    CONSTRAINT uq_pgmp_doc UNIQUE (company_id, doc_type, doc_id)
);
"""

PROC_SQL = """
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
"""

PG_MASTER_SQL = r"""
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
"""


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0083_document_attributes"),
    ]

    operations = [
        migrations.RunSQL(TABLE_SQL, "DROP TABLE IF EXISTS dbo.PGMasterPin;"),
        migrations.RunSQL(PROC_SQL, "DROP PROCEDURE IF EXISTS dbo.sp_PGMasterBackdate;"),
        migrations.RunSQL(PG_MASTER_SQL, migrations.RunSQL.noop),
    ]
