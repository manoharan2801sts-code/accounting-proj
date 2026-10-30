from django.db import migrations

# Auto Push Reschedule without Original Ticket No: sp_TicketImport_Scheduler
# gets PNR_TICKETS - the live passenger lines of the booking / reschedule with
# a given Booking Reference, so ticket_import finds each passenger's ticket
# from the Parent PNR + passenger name. Mirrored in StoredProcedures.sql.

PROC_SQL = """
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
    -- PNR_TICKETS     : the live passenger lines of the booking / reschedule whose
    --                   Booking Reference is @BookingReference (a Reschedule pushed
    --                   with only its Parent PNR finds each passenger's ticket here).
    -- MARK_IMPORTED / MARK_ERROR / MARK_SKIPPED : by @DocKey.
    -- FINISH_RUN      : closes the run log row.
    @Action          NVARCHAR(30),
    @CompanyId       INT            = NULL,
    @RunId           BIGINT         = NULL,
    @BatchSize       INT            = 50,
    @StuckMinutes    INT            = 30,
    @DocKey          NVARCHAR(200)  = NULL,
    @TicketNosJson   NVARCHAR(MAX)  = NULL,
    @BookingReference NVARCHAR(30)  = NULL,
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

    IF @Action = 'PNR_TICKETS'
    BEGIN
        SELECT tl.ticket_no, tl.passenger_name, tl.pax_type
        FROM dbo.AL_TicketLines tl
        INNER JOIN dbo.AL_Tickets t ON t.id = tl.ticket_id
        WHERE t.company_id = @CompanyId AND t.booking_reference = @BookingReference
          AND tl.rescheduled = 0 AND tl.canceled = 0
        UNION ALL
        SELECT rl.ticket_no, rl.passenger_name, rl.pax_type
        FROM dbo.Rescheduled_Al_TicketLines rl
        INNER JOIN dbo.Rescheduled_Al_Ticket rt ON rt.id = rl.reschedule_ticket_id
        WHERE rt.company_id = @CompanyId AND rt.booking_reference = @BookingReference
          AND rl.rescheduled = 0 AND rl.canceled = 0;
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


def run_proc(apps, schema_editor):
    if schema_editor.connection.vendor == "microsoft":
        schema_editor.connection.cursor().execute(PROC_SQL)


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0091_user_menu_access_print_export"),
    ]

    operations = [
        migrations.RunPython(run_proc, migrations.RunPython.noop),
    ]
