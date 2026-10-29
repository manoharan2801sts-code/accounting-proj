from django.db import migrations

# Automated Database Scheduler: the status of every Agent row it picks up is
# kept HERE, not in the Agent's table (Airline_Agent.dbo.Agent_ticket_data
# holds only the Agent's data and is only read).
#   dbo.Agent_DB_Ticket_Log   - one row per Agent row: process_status,
#                               processing_at, processed_at, invoice_number,
#                               voucher_no, import_doc_key, error_message
#   dbo.sp_AgentDbTicketLog   - CLAIM_JSON / RESULT_JSON / RELEASE_JSON /
#                               SET_RUN / WAITING / REFRESH
# Mirrored in Schema.sql and StoredProcedures.sql.

TABLE_SQL = """
IF OBJECT_ID('dbo.Agent_DB_Ticket_Log', 'U') IS NULL
CREATE TABLE dbo.Agent_DB_Ticket_Log (
    ticket_log_id       BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_adtl PRIMARY KEY,
    source_database     NVARCHAR(128)  NOT NULL,      -- AGENT_DB_NAME  (.env)
    source_table        NVARCHAR(128)  NOT NULL,      -- AGENT_DB_TABLE (.env)
    agent_row_id        BIGINT         NOT NULL,      -- the Agent row (one passenger)
    scheduler_log_id    BIGINT         NULL,          -- Agent_DB_Scheduler_Log run that picked it up
    company_id          INT            NULL,
    booking_status      NVARCHAR(100)  NULL,          -- as the Agent sent it (C / R / X)
    booking_reference   NVARCHAR(100)  NULL,
    ticket_no           NVARCHAR(100)  NULL,
    pax_name            NVARCHAR(100)  NULL,
    process_status      NVARCHAR(20)   NOT NULL
        CONSTRAINT ck_adtl_status CHECK (process_status IN ('Processing', 'Imported', 'Pending', 'Rejected', 'Duplicate', 'Error')),
    processing_at       DATETIME2      NOT NULL CONSTRAINT df_adtl_processing DEFAULT SYSUTCDATETIME(),   -- picked up (UTC)
    processed_at        DATETIME2      NULL,          -- result written (UTC)
    invoice_number      NVARCHAR(30)   NULL,
    voucher_no          NVARCHAR(30)   NULL,
    import_doc_key      NVARCHAR(200)  NULL,          -- Ticket_Import_Staging.doc_key
    error_message       NVARCHAR(2000) NULL,
    CONSTRAINT uq_adtl_agent_row UNIQUE (source_database, source_table, agent_row_id)
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_adtl_status')
    CREATE INDEX ix_adtl_status ON dbo.Agent_DB_Ticket_Log (process_status, import_doc_key);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_adtl_run')
    CREATE INDEX ix_adtl_run ON dbo.Agent_DB_Ticket_Log (scheduler_log_id);
"""

PROC_SQL = """
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
"""


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0085_agent_db_scheduler"),
    ]

    operations = [
        migrations.RunSQL(TABLE_SQL, "DROP TABLE IF EXISTS dbo.Agent_DB_Ticket_Log;"),
        migrations.RunSQL(PROC_SQL, "DROP PROCEDURE IF EXISTS dbo.sp_AgentDbTicketLog;"),
    ]
