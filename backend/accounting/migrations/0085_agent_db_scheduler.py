from django.db import migrations

# Automated Database Scheduler (agent_db_scheduler.py): the Agent puts
# tickets in the Airline_Agent database (AGENT_DB_NAME / AGENT_DB_TABLE in
# .env); every AGENT_DB_SCHEDULER_MINUTES the scheduler saves them as
# invoices through the Auto Push pipeline (source_system AGENT_DB).
#   dbo.Agent_DB_Scheduler_Log    - one row per run that fetched rows
#   dbo.sp_AgentDbScheduler_Log   - INSERT / LIST
#   dbo.sp_TicketImport_ErrorLog  - LIST: @Source API / AGENT_DB (the two
#                                   tabs of the Error Log page)
# The Airline_Agent database itself: manage.py setup_agent_db.
# Mirrored in Schema.sql and StoredProcedures.sql.

TABLE_SQL = """
IF OBJECT_ID('dbo.Agent_DB_Scheduler_Log', 'U') IS NULL
CREATE TABLE dbo.Agent_DB_Scheduler_Log (
    log_id              BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_adsl PRIMARY KEY,
    run_started_at      DATETIME2      NOT NULL,      -- UTC; listed in IST
    run_finished_at     DATETIME2      NULL,
    source_database     NVARCHAR(128)  NULL,          -- AGENT_DB_NAME  (.env)
    source_table        NVARCHAR(128)  NULL,          -- AGENT_DB_TABLE (.env)
    records_fetched     INT            NOT NULL,      -- passenger rows picked up
    invoices_fetched    INT            NOT NULL,      -- invoices they make up
    imported_count      INT            NOT NULL CONSTRAINT df_adsl_imported DEFAULT 0,   -- rows saved as invoices
    pending_count       INT            NOT NULL CONSTRAINT df_adsl_pending DEFAULT 0,    -- rows queued (waiting for their parent ticket)
    error_count         INT            NOT NULL CONSTRAINT df_adsl_error DEFAULT 0,      -- rows Rejected / Duplicate / Error
    message             NVARCHAR(1000) NULL
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_adsl_started')
    CREATE INDEX ix_adsl_started ON dbo.Agent_DB_Scheduler_Log (run_started_at);
"""

LOG_PROC_SQL = """
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
"""

ERROR_LOG_SQL = """
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
"""


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0084_pg_master_backdate"),
    ]

    operations = [
        migrations.RunSQL(TABLE_SQL, "DROP TABLE IF EXISTS dbo.Agent_DB_Scheduler_Log;"),
        migrations.RunSQL(LOG_PROC_SQL, "DROP PROCEDURE IF EXISTS dbo.sp_AgentDbScheduler_Log;"),
        migrations.RunSQL(ERROR_LOG_SQL, migrations.RunSQL.noop),
    ]
