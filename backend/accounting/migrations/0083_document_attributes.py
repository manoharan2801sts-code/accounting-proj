from django.db import migrations

# Ticket Entry "Attributes" popup - free Field / Value pairs saved with a
# Booking, Reschedule or Cancellation, under its Invoice Number.
#   dbo.Ticket_Document_Attribute - one row per Field / Value, in screen order
#   dbo.sp_DocumentAttribute      - LIST / SAVE_JSON (replaces a document's rows)
# Rows belong to the document (doc_type + doc_id); invoice_number is kept
# with them (and follows an edited Invoice Number on the next save).
# Mirrored in Schema.sql (table) and StoredProcedures.sql (procedure).

TABLE_SQL = """
IF OBJECT_ID('dbo.Ticket_Document_Attribute', 'U') IS NULL
CREATE TABLE dbo.Ticket_Document_Attribute (
    attribute_id    INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_tda PRIMARY KEY,
    company_id      INT            NOT NULL,
    doc_type        NVARCHAR(20)   NOT NULL
        CONSTRAINT ck_tda_doc_type CHECK (doc_type IN ('ticket', 'reschedule', 'cancellation')),
    doc_id          INT            NOT NULL,      -- AL_Tickets / Rescheduled_Al_Ticket / Cancellation_AL_Tickets id
    invoice_number  NVARCHAR(20)   NULL,          -- the document's Invoice Number when saved
    sort_order      INT            NOT NULL,      -- row # in the popup
    field_name      NVARCHAR(100)  NOT NULL,
    field_value     NVARCHAR(500)  NULL,
    created_at      DATETIME2      NOT NULL CONSTRAINT df_tda_created DEFAULT SYSUTCDATETIME()
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_tda_doc')
    CREATE INDEX ix_tda_doc ON dbo.Ticket_Document_Attribute (doc_type, doc_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_tda_invoice')
    CREATE INDEX ix_tda_invoice ON dbo.Ticket_Document_Attribute (company_id, invoice_number);
"""

PROC_SQL = """
CREATE OR ALTER PROCEDURE dbo.sp_DocumentAttribute
    -- LIST      : one document's Field / Value rows, in order.
    -- SAVE_JSON : replaces one document's rows with @RowsJson
    --             ([{"field_name", "field_value"}, ...] - rows without a Field are skipped).
    @Action         NVARCHAR(20),
    @CompanyId      INT            = NULL,
    @DocType        NVARCHAR(20)   = NULL,
    @DocId          INT            = NULL,
    @InvoiceNumber  NVARCHAR(20)   = NULL,
    @RowsJson       NVARCHAR(MAX)  = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'LIST'
    BEGIN
        SELECT attribute_id, company_id, doc_type, doc_id, invoice_number, sort_order, field_name, field_value
        FROM dbo.Ticket_Document_Attribute
        WHERE doc_type = @DocType AND doc_id = @DocId
        ORDER BY sort_order, attribute_id;
        RETURN;
    END

    IF @Action = 'SAVE_JSON'
    BEGIN
        BEGIN TRY
            BEGIN TRAN;
            DELETE FROM dbo.Ticket_Document_Attribute WHERE doc_type = @DocType AND doc_id = @DocId;
            INSERT INTO dbo.Ticket_Document_Attribute (company_id, doc_type, doc_id, invoice_number, sort_order, field_name, field_value)
            SELECT @CompanyId, @DocType, @DocId, @InvoiceNumber,
                   ROW_NUMBER() OVER (ORDER BY CAST(j.[key] AS INT)),
                   LTRIM(RTRIM(v.field_name)), NULLIF(LTRIM(RTRIM(v.field_value)), '')
            FROM OPENJSON(@RowsJson) j
            CROSS APPLY OPENJSON(j.[value]) WITH (
                field_name  NVARCHAR(100) '$.field_name',
                field_value NVARCHAR(500) '$.field_value'
            ) v
            WHERE NULLIF(LTRIM(RTRIM(v.field_name)), '') IS NOT NULL;
            DECLARE @Saved INT = @@ROWCOUNT;
            COMMIT TRAN;
            SELECT 'Success' AS status, @Saved AS saved;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END
END
"""


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0082_ticket_import_known_tickets"),
    ]

    operations = [
        migrations.RunSQL(TABLE_SQL, "DROP TABLE IF EXISTS dbo.Ticket_Document_Attribute;"),
        migrations.RunSQL(PROC_SQL, "DROP PROCEDURE IF EXISTS dbo.sp_DocumentAttribute;"),
    ]
