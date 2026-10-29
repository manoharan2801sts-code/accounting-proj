from django.db import migrations, models

# SSR Updation: Card Number with an editable FOP (same as Reschedule) - an
# Own Card / Client Card FOP keeps the FOP Master card it was paid with.
#   dbo.SSR_AL_TicketLines.card_number
#   dbo.sp_SSRTicket - GET_LINES returns it, SAVE stores it
# Mirrored in Schema.sql and StoredProcedures.sql.

COLUMN_SQL = """
IF COL_LENGTH('dbo.SSR_AL_TicketLines', 'card_number') IS NULL
    ALTER TABLE dbo.SSR_AL_TicketLines ADD card_number NVARCHAR(40) NULL;
"""

PROC_SQL = """
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

        IF EXISTS (SELECT 1 FROM dbo.SSR_AL_Tickets WHERE company_id = @CompanyId AND ssr_reference = @SsrReference AND (@Id IS NULL OR id <> @Id))
        BEGIN
            SELECT NULL AS id, 'Error' AS status, 'SSR Reference "' + @SsrReference + '" already exists.' AS error;
            RETURN;
        END

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
                     @InvoiceType, 'Manual', 'SSR Updated', @CustLedgerId, @TravelType, @UserName, ISNULL(@Currency, 'INR'), ISNULL(@Roe, 1),
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


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0086_agent_db_ticket_log"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(
                COLUMN_SQL, "ALTER TABLE dbo.SSR_AL_TicketLines DROP COLUMN card_number;")],
            state_operations=[migrations.AddField(
                model_name="ssrairlineticketline", name="card_number",
                field=models.CharField(blank=True, max_length=40, null=True))],
        ),
        migrations.RunSQL(PROC_SQL, migrations.RunSQL.noop),
    ]
