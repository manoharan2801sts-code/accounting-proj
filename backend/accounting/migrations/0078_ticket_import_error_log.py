from django.db import migrations

# Airline ticket Auto Push - validation (accounting/ticket_import.py):
#   AirlineDropdownValues codes = the "Passing Code" column of the Accounting
#     API Details sheet (Booking Status C/R/X, Travel Type I/D, Payment Mode
#     1/2, Pax Type ADT/CHLD/IFT, Cabin E/PE/BC/FC) - the API takes codes only.
#   dbo.Ticket_Import_Error_Log      - one row per problem found in a push
#                                      (missing / invalid / not mapped / mismatch
#                                      / save failed), shown on /error_log/
#   dbo.Ticket_Import_Invoice_Type   - the Invoice Type (Voucher Type) the admin
#                                      picked for each Booking Status
#   dbo.sp_TicketImport_ErrorLog     - INSERT_JSON / LIST / RESOLVE
#   dbo.sp_TicketImport_InvoiceType  - LIST / SET
# Mirrored in Schema.sql (tables, seed codes) and StoredProcedures.sql (procedures).

NEW_CODES = {
    "bookingStatuses": {"Confirmed": "C", "Re-Scheduled": "R", "Normal Cancelled": "X"},
    "travelTypes": {"International": "I", "Domestic": "D"},
    "paymentModes": {"Top-up": "1", "Payment Gateway": "2"},
    "paxTypes": {"Adult": "ADT", "Child": "CHLD", "Infant": "IFT"},
    "cabinOptions": {"Economy": "E", "Premium Economy": "PE", "Business Class": "BC", "First Class": "FC"},
}
OLD_CODES = {
    "bookingStatuses": {"Confirmed": "CON", "Re-Scheduled": "RES", "Normal Cancelled": "CAN"},
    "travelTypes": {"International": "INT", "Domestic": "DOM"},
    "paymentModes": {"Top-up": "TOP", "Payment Gateway": "PG"},
    "paxTypes": {"Adult": "ADT", "Child": "CHD", "Infant": "INF"},
    "cabinOptions": {"Economy": "Y", "Premium Economy": "W", "Business Class": "C", "First Class": "F"},
}


def set_codes(codes):
    def run(apps, schema_editor):
        with schema_editor.connection.cursor() as cursor:
            for list_key, by_name in codes.items():
                for name, code in by_name.items():
                    cursor.execute(
                        "UPDATE dbo.AirlineDropdownValues SET code = %s, updated_at = SYSUTCDATETIME() "
                        "WHERE list_key = %s AND name = %s", [code, list_key, name],
                    )
    return run


TABLES_SQL = [
    """
IF OBJECT_ID('dbo.Ticket_Import_Error_Log', 'U') IS NULL
CREATE TABLE dbo.Ticket_Import_Error_Log (
    error_log_id        BIGINT IDENTITY(1,1) PRIMARY KEY,
    logged_at           DATETIME2      NOT NULL CONSTRAINT df_tiel_logged DEFAULT SYSUTCDATETIME(),
    company_id          INT            NULL,
    source_system       NVARCHAR(50)   NULL,
    batch_id            NVARCHAR(50)   NULL,
    doc_key             NVARCHAR(200)  NULL,      -- Ticket_Import_Staging.doc_key when it could be worked out
    booking_status      NVARCHAR(20)   NULL,      -- as received (C / R / X)
    booking_reference   NVARCHAR(60)   NULL,
    parent_pnr          NVARCHAR(60)   NULL,
    passenger_no        INT            NULL,      -- 1-based position in passengers[]; NULL = invoice level
    ticket_no           NVARCHAR(60)   NULL,
    passenger_name      NVARCHAR(100)  NULL,
    field_name          NVARCHAR(100)  NULL,      -- API parameter, e.g. card_number
    field_label         NVARCHAR(100)  NULL,      -- screen name, e.g. Card Number
    received_value      NVARCHAR(500)  NULL,
    expected_value      NVARCHAR(500)  NULL,
    error_type          NVARCHAR(30)   NOT NULL,  -- Missing / Invalid Format / Not Mapped / Mismatch / Not Allowed / Duplicate / Unknown Field / Save Failed
    severity            NVARCHAR(10)   NOT NULL CONSTRAINT df_tiel_severity DEFAULT 'Error',   -- Error / Warning
    stage               NVARCHAR(20)   NOT NULL,  -- Validation (push rejected) / Import (save refused)
    error_message       NVARCHAR(1000) NOT NULL,
    is_resolved         BIT            NOT NULL CONSTRAINT df_tiel_resolved DEFAULT 0,
    resolved_at         DATETIME2      NULL,
    resolved_note       NVARCHAR(200)  NULL
);
""",
    """
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_tiel_company_logged')
    CREATE INDEX ix_tiel_company_logged ON dbo.Ticket_Import_Error_Log (company_id, logged_at DESC);
""",
    """
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_tiel_doc_key')
    CREATE INDEX ix_tiel_doc_key ON dbo.Ticket_Import_Error_Log (doc_key) WHERE doc_key IS NOT NULL;
""",
    """
IF OBJECT_ID('dbo.Ticket_Import_Invoice_Type', 'U') IS NULL
CREATE TABLE dbo.Ticket_Import_Invoice_Type (
    id                  INT IDENTITY(1,1) PRIMARY KEY,
    company_id          INT            NOT NULL,
    ticket_status       NVARCHAR(20)   NOT NULL
        CONSTRAINT ck_tiit_ticket_status CHECK (ticket_status IN ('Confirmed', 'Rescheduled', 'Cancelled')),
    voucher_type_id     INT            NOT NULL
        CONSTRAINT fk_tiit_voucher_type REFERENCES dbo.VoucherType (id) ON DELETE CASCADE,
    updated_at          DATETIME2      NOT NULL CONSTRAINT df_tiit_updated DEFAULT SYSUTCDATETIME(),
    CONSTRAINT uq_tiit_company_status UNIQUE (company_id, ticket_status)
);
""",
]

ERROR_LOG_PROC_SQL = """
CREATE OR ALTER PROCEDURE dbo.sp_TicketImport_ErrorLog
    -- INSERT_JSON : @RowsJson = [ {company_id, source_system, ..., error_message}, ... ]
    -- LIST        : newest first; @FromDate / @ToDate are IST dates; @Resolved
    --               NULL = all, 0 = open, 1 = resolved; @Search matches the
    --               booking reference / parent PNR / ticket no / field / message.
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
    @Top            INT            = 500
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

INVOICE_TYPE_PROC_SQL = """
CREATE OR ALTER PROCEDURE dbo.sp_TicketImport_InvoiceType
    -- LIST : the Invoice Type picked for each Booking Status (Confirmed /
    --        Rescheduled / Cancelled) of @CompanyId.
    -- SET  : @VoucherTypeId becomes the Auto Push Invoice Type of every status
    --        in @TicketStatusesJson (taking it over from any other type) and
    --        stops being it for every status left out. Confirmed / Rescheduled
    --        need an Airline voucher type, Cancelled a Credit Note one.
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

        IF EXISTS (SELECT 1 FROM @Wanted WHERE ticket_status NOT IN ('Confirmed', 'Rescheduled', 'Cancelled'))
        BEGIN
            SELECT 'Error' AS status, 'Booking Status must be Confirmed, Rescheduled or Cancelled.' AS error;
            RETURN;
        END
        IF @Category <> 'Airline' AND EXISTS (SELECT 1 FROM @Wanted WHERE ticket_status IN ('Confirmed', 'Rescheduled'))
        BEGIN
            SELECT 'Error' AS status,
                   'Only an Airline voucher type can be the Auto Push Invoice Type for Confirmed / Rescheduled tickets.' AS error;
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
        ORDER BY CASE t.ticket_status WHEN 'Confirmed' THEN 1 WHEN 'Rescheduled' THEN 2 ELSE 3 END;
        RETURN;
    END

    SELECT 'Error' AS status, 'Unknown @Action ' + ISNULL(@Action, '') AS error;
END
"""


class Migration(migrations.Migration):
    """Auto Push validation - API codes on the dropdown lists, error log, Invoice Type per Booking Status."""

    dependencies = [("accounting", "0077_fare_type_codes")]

    operations = [
        migrations.RunPython(set_codes(NEW_CODES), set_codes(OLD_CODES)),
        migrations.RunSQL(
            TABLES_SQL + [ERROR_LOG_PROC_SQL, INVOICE_TYPE_PROC_SQL],
            reverse_sql=[
                "DROP PROCEDURE IF EXISTS dbo.sp_TicketImport_InvoiceType;",
                "DROP PROCEDURE IF EXISTS dbo.sp_TicketImport_ErrorLog;",
                "DROP TABLE IF EXISTS dbo.Ticket_Import_Invoice_Type;",
                "DROP TABLE IF EXISTS dbo.Ticket_Import_Error_Log;",
            ],
        ),
    ]
