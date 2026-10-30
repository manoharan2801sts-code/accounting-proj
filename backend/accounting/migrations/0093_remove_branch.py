from django.db import migrations

# Branch is not used in the application: branch_name is dropped from every
# table that had it, and the procedures that read / wrote it no longer do.
# (Bank Branch - CompanyMaster / Ledgers bank_branch - is a bank's branch and stays.)
# Mirrored in Schema.sql and StoredProcedures.sql.

DROP_SQL = """
IF COL_LENGTH('dbo.AL_Tickets', 'branch_name') IS NOT NULL ALTER TABLE dbo.AL_Tickets DROP COLUMN branch_name;
IF COL_LENGTH('dbo.Rescheduled_Al_Ticket', 'branch_name') IS NOT NULL ALTER TABLE dbo.Rescheduled_Al_Ticket DROP COLUMN branch_name;
IF COL_LENGTH('dbo.Cancellation_AL_Tickets', 'branch_name') IS NOT NULL ALTER TABLE dbo.Cancellation_AL_Tickets DROP COLUMN branch_name;
IF COL_LENGTH('dbo.SSR_AL_Tickets', 'branch_name') IS NOT NULL ALTER TABLE dbo.SSR_AL_Tickets DROP COLUMN branch_name;
IF COL_LENGTH('dbo.Misc_Transactions', 'branch_name') IS NOT NULL ALTER TABLE dbo.Misc_Transactions DROP COLUMN branch_name;
IF COL_LENGTH('dbo.JournalVoucher', 'branch_name') IS NOT NULL ALTER TABLE dbo.JournalVoucher DROP COLUMN branch_name;
IF COL_LENGTH('dbo.Vouchers', 'branch_name') IS NOT NULL ALTER TABLE dbo.Vouchers DROP COLUMN branch_name;
IF COL_LENGTH('dbo.AppUsers', 'branch_name') IS NOT NULL ALTER TABLE dbo.AppUsers DROP COLUMN branch_name;
IF COL_LENGTH('dbo.Ticket_Import_Staging', 'branch_name') IS NOT NULL ALTER TABLE dbo.Ticket_Import_Staging DROP COLUMN branch_name;
"""

PROCS = [
    """
CREATE OR ALTER PROCEDURE dbo.sp_Ticket
    @Action                NVARCHAR(50),
    @AllowChainEdit       BIT             = 0,   -- Super Admin: edit even when chained (fn_TicketChainLock)
    @Id                    INT             = NULL,
    @CompanyId             INT             = NULL,
    @AsOfDate              DATE            = NULL,
    @FromDate              DATE            = NULL,
    @CustomerName          NVARCHAR(150)   = NULL,
    @SupplierName          NVARCHAR(150)   = NULL,
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
            t.booking_reference, t.airline_pnr, t.payment_mode, t.payment_gateway_ref, t.invoice_date, t.booking_ref_date,
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
               t.airline_category, 'Success' AS status
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
                    payment_mode = @PaymentMode, payment_gateway_ref = @PaymentGatewayRef, airline_category = @AirlineCategory
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
                    SET voucher_date = @InvoiceDate,
                        narration = @JvNarration, total_debit = @JvTotalDebit, total_credit = @JvTotalCredit,
                        updated_at = SYSUTCDATETIME()
                    WHERE source_ticket_id = @Id;
                ELSE
                BEGIN
                    DECLARE @NextNumU INT = (SELECT ISNULL(MAX(TRY_CAST(SUBSTRING(voucher_no, 4, 20) AS INT)), 0) + 1 FROM dbo.JournalVoucher WHERE company_id = @CompanyId AND category = 'AIRLINE' AND voucher_no LIKE 'AL-%');
                    INSERT INTO dbo.JournalVoucher
                        (company_id, voucher_type, voucher_date, narration, category, voucher_no,
                         source_ticket_id, total_debit, total_credit, lines_json, created_at, updated_at)
                    VALUES
                        (@CompanyId, 'Tax Invoice', @InvoiceDate, @JvNarration, 'AIRLINE',
                         'AL-' + CAST(@NextNumU AS NVARCHAR(10)), @Id, @JvTotalDebit, @JvTotalCredit, '[]', SYSUTCDATETIME(), SYSUTCDATETIME());
                END
            END
            ELSE
            BEGIN
                INSERT INTO dbo.AL_Tickets
                    (company_id, invoice_number, invoice_date, invoice_type, booking_mode, booking_type, booking_status,
                     customer_ledger_id, supplier_ledger_id, travel_type, user_name, currency, roe, booking_given_by,
                     booking_reference, booking_ref_date, airline_pnr, gds_pnr, office_id, payment_mode, payment_gateway_ref,
                     airline_category, created_at, updated_at)
                VALUES
                    (@CompanyId, @InvoiceNumber, @InvoiceDate, @InvoiceType, ISNULL(@BookingMode, 'Manual'), @BookingType, @BookingStatus,
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
                    (company_id, voucher_type, voucher_date, narration, category, voucher_no,
                     source_ticket_id, total_debit, total_credit, lines_json, created_at, updated_at)
                VALUES
                    (@CompanyId, 'Tax Invoice', @InvoiceDate, @JvNarration, 'AIRLINE',
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
""",
    """
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
            rt.booking_reference, rt.airline_pnr, rt.payment_mode, rt.payment_gateway_ref, rt.invoice_date, rt.booking_ref_date,
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
                    payment_mode = @PaymentMode, payment_gateway_ref = @PaymentGatewayRef, airline_category = @AirlineCategory
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
                    (company_id, original_ticket_id, invoice_number, invoice_date, invoice_type, booking_mode, booking_type, booking_status,
                     customer_ledger_id, supplier_ledger_id, travel_type, user_name, currency, roe, booking_given_by,
                     booking_reference, booking_ref_date, airline_pnr, gds_pnr, office_id, payment_mode, payment_gateway_ref,
                     airline_category, created_at, updated_at)
                VALUES
                    (@CompanyId, @OriginalTicketId, @InvoiceNumber, @InvoiceDate, @InvoiceType, ISNULL(@BookingMode, 'Manual'), @BookingType, @BookingStatus,
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
                SET voucher_date = @InvoiceDate,
                    narration = @JvNarration, total_debit = @JvTotalDebit, total_credit = @JvTotalCredit,
                    updated_at = SYSUTCDATETIME()
                WHERE source_reschedule_ticket_id = @ResultId;
            ELSE
            BEGIN
                DECLARE @NextNum INT = (SELECT ISNULL(MAX(TRY_CAST(SUBSTRING(voucher_no, 5, 20) AS INT)), 0) + 1 FROM dbo.JournalVoucher WHERE company_id = @CompanyId AND category = 'AIRLINE_RESCHEDULE' AND voucher_no LIKE 'ALR-%');
                INSERT INTO dbo.JournalVoucher
                    (company_id, voucher_type, voucher_date, narration, category, voucher_no,
                     source_reschedule_ticket_id, total_debit, total_credit, lines_json, created_at, updated_at)
                VALUES
                    (@CompanyId, 'Tax Invoice', @InvoiceDate, @JvNarration, 'AIRLINE_RESCHEDULE',
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
""",
    """
CREATE OR ALTER PROCEDURE dbo.sp_Voucher
    @Action        NVARCHAR(50),
    @Id            INT            = NULL,
    @CompanyId     INT            = NULL,
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
        SELECT id, voucher_no, voucher_type, voucher_type_name, voucher_date, narration,
               total_debit, total_credit, lines_json
        FROM dbo.Vouchers
        WHERE company_id = @CompanyId
        ORDER BY voucher_date DESC, id DESC;
        RETURN;
    END

    IF @Action = 'GET_BY_ID'
    BEGIN
        SELECT id, voucher_no, voucher_type, voucher_type_name, voucher_date, narration,
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
                    voucher_type = ISNULL(@VoucherType, 'Journal'), voucher_type_name = @VoucherTypeName, voucher_date = @VoucherDate,
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
                    (company_id, voucher_type, voucher_type_name, voucher_date, narration, category, voucher_no,
                     total_debit, total_credit, lines_json, created_at, updated_at)
                VALUES
                    (@CompanyId, ISNULL(@VoucherType, 'Journal'), @VoucherTypeName, @VoucherDate, @Narration, 'MANUAL',
                     CASE WHEN @UseManualNo = 1 THEN @ManualFullNo ELSE CAST(@NextNum AS NVARCHAR(10)) END,
                     @TotalDebit, @TotalCredit, @ResolvedLinesJson, SYSUTCDATETIME(), SYSUTCDATETIME());
                SET @ResultId = SCOPE_IDENTITY();
            END

            COMMIT TRAN;

            SELECT id, voucher_no, voucher_type, voucher_type_name, voucher_date, narration,
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
""",
    """
CREATE OR ALTER PROCEDURE dbo.sp_CancellationTicket
    @Action                  NVARCHAR(50),
    @Id                      INT             = NULL,
    @CompanyId               INT             = NULL,
    @OriginalTicketId        INT             = NULL,
    @CustomerName            NVARCHAR(150)   = NULL,
    @SupplierName            NVARCHAR(150)   = NULL,
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
               ct.airline_category, ct.customer_ledger_id,
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
                (company_id, original_ticket_id, parent_pnr, invoice_number, invoice_date, invoice_type, booking_mode, booking_type, booking_status,
                 customer_ledger_id, supplier_ledger_id, travel_type, user_name, currency, roe, booking_given_by,
                 cancellation_reference, cancellation_ref_date, airline_pnr, gds_pnr, office_id, payment_mode, payment_gateway_ref,
                 airline_category, created_at, updated_at)
            VALUES
                (@CompanyId, @OriginalTicketId, @ParentPnr, @InvoiceNumber, @InvoiceDate, @InvoiceType, ISNULL(@BookingMode, 'Manual'), @BookingType, @BookingStatus,
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
                (company_id, voucher_type, voucher_date, narration, category, voucher_no,
                 source_cancellation_ticket_id, total_debit, total_credit, lines_json, created_at, updated_at)
            VALUES
                (@CompanyId, 'Tax Invoice', @InvoiceDate, @JvNarration, 'AIRLINE_CANCELLATION',
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
            DECLARE @CxInvoiceDate DATE;
            SELECT @CxInvoiceDate = invoice_date FROM dbo.Cancellation_AL_Tickets WHERE id = @Id;
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
                    (company_id, voucher_type, voucher_date, narration, category, voucher_no,
                     source_cancellation_ticket_id, total_debit, total_credit, lines_json, created_at, updated_at)
                VALUES
                    (@CompanyId, 'Tax Invoice', @CxInvoiceDate, @JvNarration, 'AIRLINE_CANCELLATION',
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
""",
    """
CREATE OR ALTER PROCEDURE dbo.sp_AppUser
    @Action         NVARCHAR(50),
    @Id             INT             = NULL,
    @FullName       NVARCHAR(150)   = NULL,
    @Email          NVARCHAR(200)   = NULL,
    @Role           NVARCHAR(50)    = NULL,
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
                SET full_name = @FullName, email = @Email, role = @Role,
                    is_super_admin = @IsSuperAdmin, is_active = @IsActive,
                    password_hash = ISNULL(@PasswordHash, password_hash), updated_at = SYSUTCDATETIME()
                WHERE id = @Id;
                SET @ResultId = @Id;
            END
            ELSE
            BEGIN
                INSERT INTO dbo.AppUsers (full_name, email, role, is_super_admin, is_active, password_hash, created_at, updated_at)
                VALUES (@FullName, @Email, @Role, @IsSuperAdmin, @IsActive, @PasswordHash, SYSUTCDATETIME(), SYSUTCDATETIME());
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
""",
    """
CREATE OR ALTER PROCEDURE dbo.sp_SSRTicket
    @Action                    NVARCHAR(50),
    @Id                        INT             = NULL,
    @CompanyId                 INT             = NULL,
    @OriginalTicketId          INT             = NULL,
    @SourceRescheduleTicketId  INT             = NULL,
    @CustomerName              NVARCHAR(150)   = NULL,
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
               st.ssr_reference, st.ssr_ref_date, st.airline_pnr, st.gds_pnr, st.payment_mode, st.payment_gateway_ref,
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
                    (company_id, original_ticket_id, source_reschedule_ticket_id, invoice_number, invoice_date,
                     invoice_type, booking_mode, booking_status, customer_ledger_id, travel_type, user_name, currency, roe,
                     ssr_reference, ssr_ref_date, airline_pnr, gds_pnr, payment_mode, payment_gateway_ref, parent_pnr, created_at, updated_at)
                VALUES
                    (@CompanyId, @OriginalTicketId, @SourceRescheduleTicketId, @InvoiceNumber, @InvoiceDate,
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
                    (company_id, voucher_type, voucher_date, narration, category, voucher_no,
                     source_ssr_ticket_id, total_debit, total_credit, lines_json, created_at, updated_at)
                VALUES
                    (@CompanyId, 'Tax Invoice', @InvoiceDate, @JvNarration, 'AIRLINE_SSR',
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
""",
    """
CREATE OR ALTER PROCEDURE dbo.sp_MiscTransaction
    @Action             NVARCHAR(50),
    @Id                 INT             = NULL,
    @CompanyId          INT             = NULL,
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
        SELECT m.id, m.invoice_number, m.invoice_date, m.invoice_type, m.status AS misc_status,
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
                    (company_id, invoice_number, invoice_date, invoice_type, status, user_name, reference, ref_date,
                     payment_mode, payment_gateway_ref, currency, customer_ledger_id, supplier_ledger_id, description,
                     base_amount, other_taxes, markup, service_fee, supp_markup, supp_service_fee, total_billed, created_at, updated_at)
                VALUES
                    (@CompanyId, @InvoiceNumber, @InvoiceDate, @InvoiceType, @Status, @UserName, @Reference, @RefDate,
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
                    (company_id, voucher_type, voucher_date, narration, category, voucher_no,
                     source_misc_ticket_id, total_debit, total_credit, lines_json, created_at, updated_at)
                VALUES
                    (@CompanyId, 'Tax Invoice', @InvoiceDate, @JvNarration, 'MISC',
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
""",
    """
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
            invoice_number NVARCHAR(20), invoice_date DATE, invoice_type NVARCHAR(100),
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
                invoice_number, invoice_date, invoice_type, booking_mode, booking_type, booking_status,
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
                s.invoice_number, s.invoice_date, s.invoice_type, s.booking_mode, s.booking_type, s.booking_status,
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
""",
    """
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
""",
]


def run_drop_operations(apps, schema_editor):
    conn = schema_editor.connection
    if conn.vendor == "microsoft":
        with conn.cursor() as cur:
            cur.execute(DROP_SQL)
            for p in PROCS:
                cur.execute(p)
    else:
        with conn.cursor() as cur:
            tables = [
                'AL_Tickets', 'Rescheduled_Al_Ticket', 'Cancellation_AL_Tickets',
                'SSR_AL_Tickets', 'Misc_Transactions', 'JournalVoucher',
                'Vouchers', 'AppUsers', 'Ticket_Import_Staging'
            ]
            for tbl in tables:
                try:
                    cur.execute(f"ALTER TABLE `{tbl}` DROP COLUMN `branch_name`")
                except Exception:
                    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0092_ticket_import_pnr_tickets"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(run_drop_operations, migrations.RunPython.noop)
            ],
            state_operations=[
                migrations.RemoveField(model_name="ticket", name="branch_name"),
                migrations.RemoveField(model_name="rescheduleairlineticket", name="branch_name"),
                migrations.RemoveField(model_name="cancellationairlineticket", name="branch_name"),
                migrations.RemoveField(model_name="ssrairlineticket", name="branch_name"),
                migrations.RemoveField(model_name="misctransaction", name="branch_name"),
                migrations.RemoveField(model_name="journalvoucher", name="branch_name"),
                migrations.RemoveField(model_name="voucher", name="branch_name"),
                migrations.RemoveField(model_name="appuser", name="branch_name"),
            ],
        ),
    ]
