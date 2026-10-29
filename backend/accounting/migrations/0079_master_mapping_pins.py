from django.db import migrations

# Ledger Mapping - back-dated change (Effective From before today):
#   "Replace all previous data also" - every document dated from that day on
#       (saved ones too) posts to the new ledger.
#   "Retain old ledgers" - every document ALREADY SAVED from that day on keeps
#       the ledger it posted to; only new / edited documents take the new one.
# Documents carry no ledger of their own (their JVs are worked out from Ledger
# Mapping by the document's date), so "Retain" pins each saved document to its
# old ledger here; models.resolve_mapping reads the pin first. Editing and
# saving a document drops its pins.
#   dbo.MasterMappingPin       - one row per (document, mapped field)
#   dbo.sp_MasterMappingPin    - LIST / DOCUMENTS / SAVE_JSON / DELETE_FIELD /
#                                DELETE_DOCUMENT / DELETE_HISTORY_AFTER
# Mirrored in Schema.sql (table) and StoredProcedures.sql (procedure).

TABLE_SQL = """
IF OBJECT_ID('dbo.MasterMappingPin', 'U') IS NULL
CREATE TABLE dbo.MasterMappingPin (
    id                  INT IDENTITY(1,1) PRIMARY KEY,
    company_id          INT            NOT NULL,
    product_type        NVARCHAR(20)   NOT NULL,
    field_name          NVARCHAR(100)  NOT NULL,
    doc_type            NVARCHAR(20)   NOT NULL
        CONSTRAINT ck_mmp_doc_type CHECK (doc_type IN ('ticket', 'reschedule', 'cancellation', 'ssr', 'misc')),
    doc_id              INT            NOT NULL,
    doc_date            DATE           NOT NULL,
    ledger_id           INT            NOT NULL CONSTRAINT fk_mmp_ledger REFERENCES dbo.Ledgers (id),
    ledger_name         NVARCHAR(200)  NULL,
    masters_category    NVARCHAR(40)   NULL,
    effective_from      DATE           NULL,      -- Effective From of the mapping the document was pinned to
    created_at          DATETIME2      NOT NULL CONSTRAINT df_mmp_created DEFAULT SYSUTCDATETIME(),
    CONSTRAINT uq_mmp_doc_field UNIQUE (company_id, product_type, field_name, doc_type, doc_id)
);
"""
INDEX_SQL = """
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_mmp_doc')
    CREATE INDEX ix_mmp_doc ON dbo.MasterMappingPin (doc_type, doc_id);
"""

PROC_SQL = """
CREATE OR ALTER PROCEDURE dbo.sp_MasterMappingPin
    -- LIST                 : every pin of @CompanyId, with the pinned ledger's GST %.
    -- DOCUMENTS            : saved documents of @CompanyId dated @FromDate or later that
    --                        @ProductType's mapping applies to (Airline: Booking,
    --                        Reschedule, Cancellation, SSR Updation and Miscellaneous -
    --                        Misc falls back to Airline for Output / Input GST;
    --                        Miscellaneous: Miscellaneous only). doc_date = the date
    --                        the document's mappings are resolved for.
    -- SAVE_JSON            : @RowsJson pins; a document already pinned for the field keeps its pin.
    -- DELETE_FIELD         : pins of @FieldName on documents dated @FromDate or later.
    -- DELETE_DOCUMENT      : every pin of one document (@DocType, @DocId) - it was edited.
    -- DELETE_HISTORY_AFTER : Ledger Mapping history rows of @FieldName dated after @FromDate.
    @Action        NVARCHAR(30),
    @CompanyId     INT            = NULL,
    @ProductType   NVARCHAR(20)   = NULL,
    @FieldName     NVARCHAR(100)  = NULL,
    @FromDate      DATE           = NULL,
    @DocType       NVARCHAR(20)   = NULL,
    @DocId         INT            = NULL,
    @RowsJson      NVARCHAR(MAX)  = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'LIST'
    BEGIN
        SELECT p.product_type, p.field_name, p.doc_type, p.doc_id, p.doc_date, p.ledger_id,
               COALESCE(NULLIF(l.alias_name, ''), l.name, p.ledger_name) AS ledger_name,
               ISNULL(l.gst_percentage, 0) AS ledger_gst_percentage, p.masters_category, p.effective_from
        FROM dbo.MasterMappingPin p
        LEFT JOIN dbo.Ledgers l ON l.id = p.ledger_id
        WHERE p.company_id = @CompanyId;
        RETURN;
    END

    IF @Action = 'DOCUMENTS'
    BEGIN
        SELECT doc_type, doc_id, doc_no, doc_date FROM (
            SELECT 'ticket' AS doc_type, id AS doc_id, invoice_number AS doc_no,
                   COALESCE(invoice_date, booking_ref_date) AS doc_date
            FROM dbo.AL_Tickets WHERE company_id = @CompanyId AND @ProductType = 'Airline'
            UNION ALL
            SELECT 'reschedule', id, invoice_number, COALESCE(invoice_date, booking_ref_date)
            FROM dbo.Rescheduled_Al_Ticket WHERE company_id = @CompanyId AND @ProductType = 'Airline'
            UNION ALL
            SELECT 'cancellation', id, invoice_number, COALESCE(invoice_date, cancellation_ref_date)
            FROM dbo.Cancellation_AL_Tickets WHERE company_id = @CompanyId AND @ProductType = 'Airline'
            UNION ALL
            SELECT 'ssr', id, invoice_number, invoice_date
            FROM dbo.SSR_AL_Tickets WHERE company_id = @CompanyId AND @ProductType = 'Airline'
            UNION ALL
            SELECT 'misc', id, invoice_number, invoice_date
            FROM dbo.Misc_Transactions WHERE company_id = @CompanyId AND @ProductType IN ('Airline', 'Miscellaneous')
        ) d
        WHERE d.doc_date >= @FromDate
        ORDER BY d.doc_date, d.doc_type, d.doc_id;
        RETURN;
    END

    IF @Action = 'SAVE_JSON'
    BEGIN
        INSERT INTO dbo.MasterMappingPin
            (company_id, product_type, field_name, doc_type, doc_id, doc_date, ledger_id, ledger_name, masters_category, effective_from)
        SELECT j.company_id, j.product_type, j.field_name, j.doc_type, j.doc_id, j.doc_date, j.ledger_id, j.ledger_name,
               j.masters_category, j.effective_from
        FROM OPENJSON(@RowsJson) WITH (
            company_id INT, product_type NVARCHAR(20), field_name NVARCHAR(100), doc_type NVARCHAR(20), doc_id INT,
            doc_date DATE, ledger_id INT, ledger_name NVARCHAR(200), masters_category NVARCHAR(40), effective_from DATE
        ) j
        WHERE NOT EXISTS (SELECT 1 FROM dbo.MasterMappingPin p
                          WHERE p.company_id = j.company_id AND p.product_type = j.product_type
                            AND p.field_name = j.field_name AND p.doc_type = j.doc_type AND p.doc_id = j.doc_id);
        SELECT @@ROWCOUNT AS rows_pinned, 'Success' AS status;
        RETURN;
    END

    IF @Action = 'DELETE_FIELD'
    BEGIN
        DELETE FROM dbo.MasterMappingPin
        WHERE company_id = @CompanyId AND product_type = @ProductType AND field_name = @FieldName AND doc_date >= @FromDate;
        SELECT @@ROWCOUNT AS rows_deleted, 'Success' AS status;
        RETURN;
    END

    IF @Action = 'DELETE_DOCUMENT'
    BEGIN
        DELETE FROM dbo.MasterMappingPin WHERE doc_type = @DocType AND doc_id = @DocId;
        SELECT @@ROWCOUNT AS rows_deleted, 'Success' AS status;
        RETURN;
    END

    IF @Action = 'DELETE_HISTORY_AFTER'
    BEGIN
        DELETE FROM dbo.MasterMappingHistory
        WHERE company_id = @CompanyId AND product_type = @ProductType AND field_name = @FieldName
          AND effective_from > @FromDate;
        SELECT @@ROWCOUNT AS rows_deleted, 'Success' AS status;
        RETURN;
    END

    SELECT 'Error' AS status, 'Unknown @Action ' + ISNULL(@Action, '') AS error;
END
"""


class Migration(migrations.Migration):
    """Ledger Mapping back-dated changes - Retain old ledgers on saved documents."""

    dependencies = [("accounting", "0078_ticket_import_error_log")]

    operations = [
        migrations.RunSQL(
            [TABLE_SQL, INDEX_SQL, PROC_SQL],
            reverse_sql=[
                "DROP PROCEDURE IF EXISTS dbo.sp_MasterMappingPin;",
                "DROP TABLE IF EXISTS dbo.MasterMappingPin;",
            ],
        ),
    ]
