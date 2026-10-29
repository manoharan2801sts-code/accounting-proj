from django.db import migrations

# Airline ticket Auto Push - GST amounts sent by the Agent.
# The Agent works out its own Service Fee / Addl Service Fee / SSR Service Fee
# GST (customer and supplier side). Those amounts are saved as sent and used
# instead of fee x Ledger Mapping GST % (TicketLine.computed_gst /
# computed_supp_gst and the Reschedule / Cancellation equivalents) - the %
# calculation stays for manual entry. A document edited on screen drops them.
#   dbo.Ticket_Line_Gst_Amount   - one row per (document, ticket no) line
#   dbo.sp_TicketLineGstAmount   - LIST / SAVE_JSON / DELETE_DOCUMENT
# Mirrored in Schema.sql (table) and StoredProcedures.sql (procedure).

TABLE_SQL = """
IF OBJECT_ID('dbo.Ticket_Line_Gst_Amount', 'U') IS NULL
CREATE TABLE dbo.Ticket_Line_Gst_Amount (
    line_type                   NVARCHAR(20)   NOT NULL
        CONSTRAINT ck_tlga_line_type CHECK (line_type IN ('ticket', 'reschedule', 'cancellation')),
    doc_id                      INT            NOT NULL,      -- AL_Tickets / Rescheduled_Al_Ticket / Cancellation_AL_Tickets id
    ticket_no                   NVARCHAR(30)   NOT NULL,      -- the line's own Ticket No.
    service_fee_gst             DECIMAL(14,2)  NULL,          -- NULL = worked out from Ledger Mapping GST %
    addl_service_fee_gst        DECIMAL(14,2)  NULL,
    ssr_service_fee_gst         DECIMAL(14,2)  NULL,
    supp_service_fee_gst        DECIMAL(14,2)  NULL,
    supp_addl_service_fee_gst   DECIMAL(14,2)  NULL,
    supp_ssr_service_fee_gst    DECIMAL(14,2)  NULL,
    source                      NVARCHAR(30)   NOT NULL CONSTRAINT df_tlga_source DEFAULT 'Auto Push',
    created_at                  DATETIME2      NOT NULL CONSTRAINT df_tlga_created DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_tlga PRIMARY KEY (line_type, doc_id, ticket_no)
);
"""

PROC_SQL = """
CREATE OR ALTER PROCEDURE dbo.sp_TicketLineGstAmount
    -- LIST            : every line's GST amounts.
    -- SAVE_JSON       : @RowsJson rows (insert or replace by line_type + doc_id + ticket_no).
    -- DELETE_DOCUMENT : every row of one document (@LineType, @DocId) - it was edited on screen.
    @Action      NVARCHAR(20),
    @RowsJson    NVARCHAR(MAX) = NULL,
    @LineType    NVARCHAR(20)  = NULL,
    @DocId       INT           = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'LIST'
    BEGIN
        SELECT line_type, doc_id, ticket_no, service_fee_gst, addl_service_fee_gst, ssr_service_fee_gst,
               supp_service_fee_gst, supp_addl_service_fee_gst, supp_ssr_service_fee_gst
        FROM dbo.Ticket_Line_Gst_Amount;
        RETURN;
    END

    IF @Action = 'SAVE_JSON'
    BEGIN
        MERGE dbo.Ticket_Line_Gst_Amount AS t
        USING (
            SELECT * FROM OPENJSON(@RowsJson) WITH (
                line_type NVARCHAR(20), doc_id INT, ticket_no NVARCHAR(30),
                service_fee_gst DECIMAL(14,2), addl_service_fee_gst DECIMAL(14,2), ssr_service_fee_gst DECIMAL(14,2),
                supp_service_fee_gst DECIMAL(14,2), supp_addl_service_fee_gst DECIMAL(14,2), supp_ssr_service_fee_gst DECIMAL(14,2)
            )
        ) AS s ON t.line_type = s.line_type AND t.doc_id = s.doc_id AND t.ticket_no = s.ticket_no
        WHEN MATCHED THEN UPDATE SET
            service_fee_gst = s.service_fee_gst, addl_service_fee_gst = s.addl_service_fee_gst,
            ssr_service_fee_gst = s.ssr_service_fee_gst, supp_service_fee_gst = s.supp_service_fee_gst,
            supp_addl_service_fee_gst = s.supp_addl_service_fee_gst, supp_ssr_service_fee_gst = s.supp_ssr_service_fee_gst
        WHEN NOT MATCHED THEN INSERT
            (line_type, doc_id, ticket_no, service_fee_gst, addl_service_fee_gst, ssr_service_fee_gst,
             supp_service_fee_gst, supp_addl_service_fee_gst, supp_ssr_service_fee_gst)
            VALUES (s.line_type, s.doc_id, s.ticket_no, s.service_fee_gst, s.addl_service_fee_gst, s.ssr_service_fee_gst,
                    s.supp_service_fee_gst, s.supp_addl_service_fee_gst, s.supp_ssr_service_fee_gst);
        SELECT @@ROWCOUNT AS rows_saved, 'Success' AS status;
        RETURN;
    END

    IF @Action = 'DELETE_DOCUMENT'
    BEGIN
        DELETE FROM dbo.Ticket_Line_Gst_Amount WHERE line_type = @LineType AND doc_id = @DocId;
        SELECT @@ROWCOUNT AS rows_deleted, 'Success' AS status;
        RETURN;
    END

    SELECT 'Error' AS status, 'Unknown @Action ' + ISNULL(@Action, '') AS error;
END
"""


class Migration(migrations.Migration):
    """Auto Push - GST amounts sent by the Agent, used as sent."""

    dependencies = [("accounting", "0079_master_mapping_pins")]

    operations = [
        migrations.RunSQL(
            [TABLE_SQL, PROC_SQL],
            reverse_sql=[
                "DROP PROCEDURE IF EXISTS dbo.sp_TicketLineGstAmount;",
                "DROP TABLE IF EXISTS dbo.Ticket_Line_Gst_Amount;",
            ],
        ),
    ]
