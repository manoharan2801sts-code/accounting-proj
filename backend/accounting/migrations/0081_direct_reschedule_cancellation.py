from django.db import migrations, models
import django.db.models.deletion

# Direct Reschedule / Direct Cancellation (Auto Push) - a Reschedule or
# Cancellation whose booking was never entered in this software. Such a
# document has no original_ticket (header) / original_ticket_line (lines):
# the Parent PNR it was pushed with is kept instead (Reschedule: each line's
# existing parent_pnr; Cancellation: the new header parent_pnr).
#   Rescheduled_Al_Ticket.original_ticket_id            -> NULL allowed
#   Rescheduled_Al_TicketLines.original_ticket_line_id  -> NULL allowed
#   Cancellation_AL_Tickets.original_ticket_id          -> NULL allowed
#   Cancellation_Al_TicketLines.original_ticket_line_id -> NULL allowed; its
#       UNIQUE becomes a filtered unique index (one cancellation per booking line)
#   Cancellation_AL_Tickets.parent_pnr                  -> new
#   Cancellation_Al_TicketLines.reschedule_line_id      -> new (the reschedule
#       line it cancelled - links a Cancellation of a direct Reschedule)
# Procedures: fn_TicketChainLock, sp_RescheduleTicket (direct lines matched by
# Ticket No.), sp_CancellationTicket (@ParentPnr, reschedule_line_id).
# Mirrored in Schema.sql and StoredProcedures.sql.

# Each column: its plain indexes and FK are dropped and put back unchanged
# around ALTER COLUMN (SQL Server refuses to alter an indexed column); its
# UNIQUE constraint is dropped for good.
NULLABLE_SQL = """
DECLARE @t SYSNAME, @c SYSNAME, @drop NVARCHAR(MAX), @create NVARCHAR(MAX);
DECLARE cols CURSOR LOCAL FAST_FORWARD FOR
    SELECT t, c FROM (VALUES
        ('Rescheduled_Al_Ticket', 'original_ticket_id'),
        ('Rescheduled_Al_TicketLines', 'original_ticket_line_id'),
        ('Cancellation_AL_Tickets', 'original_ticket_id'),
        ('Cancellation_Al_TicketLines', 'original_ticket_line_id')) v (t, c);
OPEN cols;
FETCH NEXT FROM cols INTO @t, @c;
WHILE @@FETCH_STATUS = 0
BEGIN
    IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.' + @t) AND name = @c AND is_nullable = 0)
    BEGIN
        SELECT @drop = N'', @create = N'';
        SELECT @drop += CASE WHEN i.is_unique_constraint = 1
                             THEN N'ALTER TABLE dbo.' + QUOTENAME(@t) + N' DROP CONSTRAINT ' + QUOTENAME(i.name) + N'; '
                             ELSE N'DROP INDEX ' + QUOTENAME(i.name) + N' ON dbo.' + QUOTENAME(@t) + N'; ' END,
               @create += CASE WHEN i.is_unique = 1 THEN N''
                               ELSE N'CREATE INDEX ' + QUOTENAME(i.name) + N' ON dbo.' + QUOTENAME(@t) + N' (' + QUOTENAME(@c) + N'); ' END
        FROM sys.indexes i
        INNER JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
        INNER JOIN sys.columns cc ON cc.object_id = ic.object_id AND cc.column_id = ic.column_id
        WHERE i.object_id = OBJECT_ID('dbo.' + @t) AND cc.name = @c AND i.is_primary_key = 0;
        SELECT @drop += N'ALTER TABLE dbo.' + QUOTENAME(@t) + N' DROP CONSTRAINT ' + QUOTENAME(fk.name) + N'; ',
               @create += N'ALTER TABLE dbo.' + QUOTENAME(@t) + N' ADD CONSTRAINT ' + QUOTENAME(fk.name) + N' FOREIGN KEY ('
                          + QUOTENAME(@c) + N') REFERENCES dbo.' + QUOTENAME(OBJECT_NAME(fk.referenced_object_id)) + N' (id); '
        FROM sys.foreign_keys fk
        INNER JOIN sys.foreign_key_columns fc ON fc.constraint_object_id = fk.object_id
        INNER JOIN sys.columns cc ON cc.object_id = fc.parent_object_id AND cc.column_id = fc.parent_column_id
        WHERE fk.parent_object_id = OBJECT_ID('dbo.' + @t) AND cc.name = @c;
        EXEC (@drop);
        EXEC (N'ALTER TABLE dbo.' + @t + N' ALTER COLUMN ' + @c + N' INT NULL;');
        EXEC (@create);
    END
    FETCH NEXT FROM cols INTO @t, @c;
END
CLOSE cols;
DEALLOCATE cols;
"""

COLUMNS_SQL = """
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.Cancellation_Al_TicketLines') AND name = 'uq_cancel_line_original_line')
    CREATE UNIQUE INDEX uq_cancel_line_original_line ON dbo.Cancellation_Al_TicketLines (original_ticket_line_id)
        WHERE original_ticket_line_id IS NOT NULL;
IF COL_LENGTH('dbo.Cancellation_AL_Tickets', 'parent_pnr') IS NULL
    ALTER TABLE dbo.Cancellation_AL_Tickets ADD parent_pnr NVARCHAR(30) NULL;
IF COL_LENGTH('dbo.Cancellation_Al_TicketLines', 'reschedule_line_id') IS NULL
    ALTER TABLE dbo.Cancellation_Al_TicketLines ADD reschedule_line_id INT NULL;
"""

CHAIN_LOCK_SQL = r"""
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
"""

RESCHEDULE_PROC_SQL = r"""
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
"""

CANCELLATION_PROC_SQL = r"""
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
"""


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0080_ticket_line_gst_amounts"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(NULLABLE_SQL, migrations.RunSQL.noop),
                migrations.RunSQL(COLUMNS_SQL, migrations.RunSQL.noop),
                migrations.RunSQL(CHAIN_LOCK_SQL, migrations.RunSQL.noop),
                migrations.RunSQL(RESCHEDULE_PROC_SQL, migrations.RunSQL.noop),
                migrations.RunSQL(CANCELLATION_PROC_SQL, migrations.RunSQL.noop),
            ],
            state_operations=[
                migrations.AlterField(
                    model_name="rescheduleairlineticket", name="original_ticket",
                    field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
                                            related_name="reschedules", db_column="original_ticket_id", to="accounting.ticket"),
                ),
                migrations.AlterField(
                    model_name="rescheduleairlineticketline", name="original_ticket_line",
                    field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
                                            related_name="reschedule_lines", db_column="original_ticket_line_id",
                                            to="accounting.ticketline"),
                ),
                migrations.AlterField(
                    model_name="cancellationairlineticket", name="original_ticket",
                    field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
                                            related_name="cancellations", db_column="original_ticket_id", to="accounting.ticket"),
                ),
                migrations.AlterField(
                    model_name="cancellationairlineticketline", name="original_ticket_line",
                    field=models.OneToOneField(null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
                                               related_name="cancellation_line", db_column="original_ticket_line_id",
                                               to="accounting.ticketline"),
                ),
                migrations.AddField(
                    model_name="cancellationairlineticket", name="parent_pnr",
                    field=models.CharField(max_length=30, null=True, blank=True),
                ),
                migrations.AddField(
                    model_name="cancellationairlineticketline", name="reschedule_line",
                    field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.DO_NOTHING,
                                            db_constraint=False, related_name="cancellation_lines",
                                            db_column="reschedule_line_id", to="accounting.rescheduleairlineticketline"),
                ),
            ],
        ),
    ]
