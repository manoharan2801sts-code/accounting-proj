from django.db import migrations

# Airline ticket Auto Push import (accounting/ticket_import.py):
#   dbo.Ticket_Import_Staging    - one row per passenger per pushed document
#   dbo.Ticket_Import_Run_Log    - one row per import run (push / scheduler)
#   dbo.sp_TicketImport_Stage    - INSERT_JSON / DOC_STATUS / REQUEUE
#   dbo.sp_TicketImport_Scheduler- START_RUN / RESET_STUCK / FETCH_PENDING /
#                                  RESOLVE_PARENTS / MARK_* / FINISH_RUN
# Mirrored in Schema.sql (tables) and StoredProcedures.sql (procedures).

TABLES_SQL = [
    """
IF OBJECT_ID('dbo.Ticket_Import_Staging', 'U') IS NULL
CREATE TABLE dbo.Ticket_Import_Staging (
    staging_id                  BIGINT IDENTITY(1,1) PRIMARY KEY,

    -- Source identity. doc_ref groups the passengers of one invoice;
    -- source_system + source_record_id (one passenger) is never imported twice.
    batch_id                    NVARCHAR(50)   NULL,
    source_system               NVARCHAR(50)   NOT NULL,
    doc_ref                     NVARCHAR(60)   NOT NULL,
    source_record_id            NVARCHAR(100)  NOT NULL,
    received_at                 DATETIME2      NOT NULL CONSTRAINT df_tis_received DEFAULT SYSUTCDATETIME(),

    -- Decides the target: Confirmed -> AL_Tickets, Rescheduled -> Rescheduled_Al_Ticket,
    -- Cancelled -> Cancellation_AL_Tickets (each + its lines + its Journal Voucher).
    ticket_status               NVARCHAR(20)   NOT NULL
        CONSTRAINT ck_tis_ticket_status CHECK (ticket_status IN ('Confirmed', 'Rescheduled', 'Cancelled')),
    company_id                  INT            NOT NULL,
    doc_key AS (ticket_status + N'|' + CAST(company_id AS NVARCHAR(10)) + N'|' + source_system + N'|' + doc_ref) PERSISTED,

    /* ---- Header ---- */
    branch_name                 NVARCHAR(100)  NULL,
    invoice_number              NVARCHAR(20)   NULL,      -- blank = generated from the Invoice Type's numbering
    invoice_date                DATE           NULL,
    invoice_type                NVARCHAR(100)  NULL,
    booking_mode                NVARCHAR(20)   NULL,
    booking_type                NVARCHAR(30)   NULL,
    booking_status              NVARCHAR(20)   NULL,
    customer_name               NVARCHAR(150)  NULL,
    supplier_name               NVARCHAR(150)  NULL,
    travel_type                 NVARCHAR(20)   NULL,
    user_name                   NVARCHAR(100)  NULL,
    currency                    NVARCHAR(5)    NULL,
    roe                         DECIMAL(10,4)  NULL,
    booking_given_by            NVARCHAR(25)   NULL,
    booking_reference           NVARCHAR(30)   NULL,      -- S PNR (Cancelled -> cancellation_reference)
    booking_ref_date            DATE           NULL,      -- (Cancelled -> cancellation_ref_date)
    airline_pnr                 NVARCHAR(13)   NULL,
    gds_pnr                     NVARCHAR(13)   NULL,
    office_id                   NVARCHAR(30)   NULL,
    payment_mode                NVARCHAR(20)   NULL,
    payment_gateway_ref         NVARCHAR(60)   NULL,
    airline_category            NVARCHAR(5)    NULL,

    /* ---- Passenger line ---- */
    original_ticket_no          NVARCHAR(30)   NULL,      -- Rescheduled / Cancelled: the passenger's current live Ticket No.
    airline_code                NVARCHAR(200)  NULL,
    airline_name                NVARCHAR(200)  NULL,
    line_airline_category       NVARCHAR(5)    NULL,
    flight_no                   NVARCHAR(200)  NULL,      -- multi-city: comma-joined, same order as sector
    ticket_no                   NVARCHAR(30)   NULL,
    passenger_name              NVARCHAR(50)   NULL,
    pax_type                    NVARCHAR(10)   NULL,
    sector                      NVARCHAR(200)  NULL,      -- e.g. MAA-DXB,DXB-MAA
    travel_date                 NVARCHAR(200)  NULL,      -- dd/mm/yyyy, comma-joined per sector
    cabin                       NVARCHAR(200)  NULL,
    travel_class                NVARCHAR(200)  NULL,
    fare_type                   NVARCHAR(300)  NULL,
    line_supplier_name          NVARCHAR(150)  NULL,
    line_office_id              NVARCHAR(30)   NULL,
    fop                         NVARCHAR(20)   NULL,
    card_number                 NVARCHAR(40)   NULL,
    line_status                 NVARCHAR(15)   NULL,

    /* ---- Fares ---- */
    basic_fare                  DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_basic DEFAULT 0,
    yq                          DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_yq DEFAULT 0,
    yr                          DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_yr DEFAULT 0,
    k3_tax                      DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_k3 DEFAULT 0,
    tax_others                  DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_taxo DEFAULT 0,
    seat                        DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_seat DEFAULT 0,
    meal                        DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_meal DEFAULT 0,
    baggage                     DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_bag DEFAULT 0,
    other_ssr                   DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_ossr DEFAULT 0,

    /* ---- Customer side ---- */
    disc_on                     NVARCHAR(20)   NULL,
    disc_type                   NVARCHAR(12)   NULL,
    disc_value                  DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_discv DEFAULT 0,
    tds_per                     DECIMAL(5,2)   NOT NULL CONSTRAINT df_tis_tds DEFAULT 0,
    pg_charges                  DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_pg DEFAULT 0,
    pg_charges_percentage       DECIMAL(5,2)   NOT NULL CONSTRAINT df_tis_pgp DEFAULT 0,
    markup                      DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_mk DEFAULT 0,
    addl_markup                 DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_amk DEFAULT 0,
    ssr_markup                  DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_smk DEFAULT 0,
    service_fee                 DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_sf DEFAULT 0,
    addl_service_fee            DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_asf DEFAULT 0,
    ssr_service_fee             DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_ssf DEFAULT 0,
    gst_pct                     DECIMAL(5,2)   NOT NULL CONSTRAINT df_tis_gst DEFAULT 0,

    /* ---- Supplier side ---- */
    supp_comm_on                NVARCHAR(20)   NULL,
    supp_comm_type              NVARCHAR(12)   NULL,
    supp_comm_value             DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_scv DEFAULT 0,
    supp_tds_per                DECIMAL(5,2)   NOT NULL CONSTRAINT df_tis_stds DEFAULT 0,
    supp_markup                 DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_smku DEFAULT 0,
    supp_addl_markup            DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_samk DEFAULT 0,
    supp_ssr_markup             DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_ssmk DEFAULT 0,
    supp_service_fee            DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_ssfe DEFAULT 0,
    supp_addl_service_fee       DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_sasf DEFAULT 0,
    supp_ssr_service_fee        DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_sssf DEFAULT 0,
    supp_gst_pct                DECIMAL(5,2)   NOT NULL CONSTRAINT df_tis_sgst DEFAULT 0,

    /* ---- Rescheduled / Cancelled ---- */
    agent_penalty               DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_agp DEFAULT 0,
    reschedule_penalty          DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_rsp DEFAULT 0,
    supplier_penalty            DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_spp DEFAULT 0,
    cancellation_penalty        DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_cxp DEFAULT 0,
    cust_markup_reversal        DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_cmr DEFAULT 0,
    cust_addl_markup_reversal   DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_camr DEFAULT 0,
    cust_ssr_markup_reversal    DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_csmr DEFAULT 0,
    supp_markup_reversal        DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_smr DEFAULT 0,
    supp_addl_markup_reversal   DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_samr DEFAULT 0,
    supp_ssr_markup_reversal    DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_ssmr DEFAULT 0,
    tds_amount_override         DECIMAL(14,2)  NULL,
    supp_tds_amount_override    DECIMAL(14,2)  NULL,

    total_billed                DECIMAL(14,2)  NULL,      -- as sent by the source
    raw_payload                 NVARCHAR(MAX)  NULL,      -- {"header": {...}, "passenger": {...}} exactly as received

    /* ---- Processing ---- */
    process_status              NVARCHAR(20)   NOT NULL CONSTRAINT df_tis_pstatus DEFAULT 'Pending'
        CONSTRAINT ck_tis_process_status CHECK (process_status IN ('Pending', 'Processing', 'Imported', 'Error', 'Skipped')),
    retry_count                 INT            NOT NULL CONSTRAINT df_tis_retry DEFAULT 0,
    error_message               NVARCHAR(1000) NULL,
    run_id                      BIGINT         NULL,
    picked_at                   DATETIME2      NULL,
    processed_at                DATETIME2      NULL,
    target_header_id            INT            NULL,      -- AL_Tickets.id / Rescheduled_Al_Ticket.id / Cancellation_AL_Tickets.id
    saved_invoice_number        NVARCHAR(20)   NULL,      -- the Invoice / Credit Note number it was saved under
    saved_voucher_no            NVARCHAR(30)   NULL,      -- the Journal Voucher posted with it

    CONSTRAINT uq_tis_source_record UNIQUE (source_system, source_record_id)
);
""",
    """
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_tis_doc_key' AND object_id = OBJECT_ID('dbo.Ticket_Import_Staging'))
    CREATE INDEX ix_tis_doc_key ON dbo.Ticket_Import_Staging (doc_key) INCLUDE (process_status);
""",
    """
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_tis_pending' AND object_id = OBJECT_ID('dbo.Ticket_Import_Staging'))
    CREATE INDEX ix_tis_pending ON dbo.Ticket_Import_Staging (process_status, company_id, staging_id);
""",
    """
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_tis_ticket_no' AND object_id = OBJECT_ID('dbo.Ticket_Import_Staging'))
    CREATE INDEX ix_tis_ticket_no ON dbo.Ticket_Import_Staging (company_id, ticket_no);
""",
    """
IF OBJECT_ID('dbo.Ticket_Import_Run_Log', 'U') IS NULL
CREATE TABLE dbo.Ticket_Import_Run_Log (
    run_id          BIGINT IDENTITY(1,1) PRIMARY KEY,
    company_id      INT            NULL,
    started_at      DATETIME2      NOT NULL CONSTRAINT df_tirl_started DEFAULT SYSUTCDATETIME(),
    finished_at     DATETIME2      NULL,
    rows_picked     INT            NOT NULL CONSTRAINT df_tirl_picked DEFAULT 0,
    docs_imported   INT            NOT NULL CONSTRAINT df_tirl_imported DEFAULT 0,
    docs_failed     INT            NOT NULL CONSTRAINT df_tirl_failed DEFAULT 0,
    message         NVARCHAR(1000) NULL
);
""",
]

STAGE_PROC_SQL = """
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
            booking_mode NVARCHAR(20), booking_type NVARCHAR(30), booking_status NVARCHAR(20),
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
"""

SCHEDULER_PROC_SQL = """
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
               CASE s.ticket_status WHEN 'Confirmed' THEN 1 WHEN 'Rescheduled' THEN 2 ELSE 3 END,
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
        ORDER BY CASE s.ticket_status WHEN 'Confirmed' THEN 1 WHEN 'Rescheduled' THEN 2 ELSE 3 END, s.doc_key, s.staging_id;
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


class Migration(migrations.Migration):
    """Airline ticket Auto Push import - staging table, run log and their procedures."""

    dependencies = [("accounting", "0073_audit_log_view_ist")]

    operations = [
        migrations.RunSQL(
            TABLES_SQL + [STAGE_PROC_SQL, SCHEDULER_PROC_SQL],
            reverse_sql=[
                "DROP PROCEDURE IF EXISTS dbo.sp_TicketImport_Scheduler;",
                "DROP PROCEDURE IF EXISTS dbo.sp_TicketImport_Stage;",
                "DROP TABLE IF EXISTS dbo.Ticket_Import_Run_Log;",
                "DROP TABLE IF EXISTS dbo.Ticket_Import_Staging;",
            ],
        ),
    ]
