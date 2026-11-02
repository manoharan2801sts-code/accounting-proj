from django.db import migrations

# Month-wise ledger summary tables [Mon_YY-Accounting_Ledger] (e.g.
# [Jan_26-Accounting_Ledger]) - created by sp_AccountingLedger on first use,
# kept current by accounting/ledger_months.py. Accounting_Ledger_Status marks
# a company whose tables must be rebuilt before the next report reads them.
# Mirrored in Schema.sql and StoredProcedures.sql.

TABLE_SQL = """
IF OBJECT_ID('dbo.Accounting_Ledger_Status', 'U') IS NULL
CREATE TABLE dbo.Accounting_Ledger_Status (
    company_id  INT        NOT NULL CONSTRAINT pk_accounting_ledger_status PRIMARY KEY,
    is_dirty    BIT        NOT NULL CONSTRAINT df_als_dirty DEFAULT 1,   -- 1 = rebuild before the next report reads
    built_at    DATETIME2  NULL                                          -- last full / partial build (UTC)
);
"""

PROC_SQL = r"""
CREATE OR ALTER PROCEDURE dbo.sp_AccountingLedger
    -- Month-wise ledger summary: one table per month, [Mon_YY-Accounting_Ledger]
    -- (e.g. [Jan_26-Accounting_Ledger]), created on its first SAVE_MONTH. Per
    -- company + ledger: debit, credit, monthly_total (debit - credit) and
    -- overall_total (previous month's overall_total + monthly_total). The rows
    -- are worked out in Python (accounting/ledger_months.py).
    -- SAVE_MONTH  : replaces @CompanyId's rows of @TableName with @RowsJson
    --               [{ledger_id, ledger_name, debit, credit, monthly_total, overall_total}].
    -- READ_MONTH  : @CompanyId's rows of @TableName (none when the table does not exist yet).
    -- LIST_TABLES : every month table that exists.
    -- DOC_DATE    : company + voucher date of one document (@DocType ticket / reschedule /
    --               cancellation / ssr / misc / voucher, @DocId) - the date its month is decided by.
    -- DATE_RANGE  : @CompanyId's first and last voucher date (Journal Vouchers + manual Vouchers).
    -- GET_STATUS / SET_STATUS : @CompanyId's dirty flag (SET_STATUS with no @CompanyId = every company).
    @Action      NVARCHAR(30),
    @CompanyId   INT            = NULL,
    @TableName   SYSNAME        = NULL,
    @RowsJson    NVARCHAR(MAX)  = NULL,
    @DocType     NVARCHAR(20)   = NULL,
    @DocId       INT            = NULL,
    @IsDirty     BIT            = NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF @TableName IS NOT NULL
       AND @TableName NOT LIKE '[A-Z][a-z][a-z][_][0-9][0-9]-Accounting[_]Ledger'
    BEGIN
        SELECT 'Error' AS status, 'Invalid month table name "' + @TableName + '".' AS error;
        RETURN;
    END
    DECLARE @T NVARCHAR(300) = N'dbo.' + QUOTENAME(@TableName), @Sql NVARCHAR(MAX);

    IF @Action = 'SAVE_MONTH'
    BEGIN
        IF OBJECT_ID(@T, 'U') IS NULL
        BEGIN
            SET @Sql = N'CREATE TABLE ' + @T + N' (
                company_id     INT            NOT NULL,
                ledger_id      INT            NOT NULL,
                ledger_name    NVARCHAR(200)  NULL,
                debit          DECIMAL(19,4)  NOT NULL,
                credit         DECIMAL(19,4)  NOT NULL,
                monthly_total  DECIMAL(19,4)  NOT NULL,
                overall_total  DECIMAL(19,4)  NOT NULL,
                updated_at     DATETIME2      NOT NULL CONSTRAINT ' + QUOTENAME(N'df_' + @TableName) + N' DEFAULT SYSUTCDATETIME(),
                CONSTRAINT ' + QUOTENAME(N'pk_' + @TableName) + N' PRIMARY KEY (company_id, ledger_id)
            );';
            EXEC sp_executesql @Sql;
        END
        SET @Sql = N'DELETE FROM ' + @T + N' WHERE company_id = @CompanyId;
            INSERT INTO ' + @T + N' (company_id, ledger_id, ledger_name, debit, credit, monthly_total, overall_total)
            SELECT @CompanyId, j.ledger_id, j.ledger_name, j.debit, j.credit, j.monthly_total, j.overall_total
            FROM OPENJSON(@RowsJson) WITH (
                ledger_id INT ''$.ledger_id'', ledger_name NVARCHAR(200) ''$.ledger_name'',
                debit DECIMAL(19,4) ''$.debit'', credit DECIMAL(19,4) ''$.credit'',
                monthly_total DECIMAL(19,4) ''$.monthly_total'', overall_total DECIMAL(19,4) ''$.overall_total''
            ) j;
            SELECT @Saved = @@ROWCOUNT;';
        DECLARE @Saved INT;
        EXEC sp_executesql @Sql, N'@CompanyId INT, @RowsJson NVARCHAR(MAX), @Saved INT OUTPUT',
             @CompanyId, @RowsJson, @Saved OUTPUT;
        SELECT 'Success' AS status, @TableName AS table_name, @Saved AS rows_saved;
        RETURN;
    END

    IF @Action = 'READ_MONTH'
    BEGIN
        IF OBJECT_ID(@T, 'U') IS NULL
        BEGIN
            SELECT CAST(NULL AS INT) AS ledger_id, CAST(NULL AS NVARCHAR(200)) AS ledger_name,
                   CAST(NULL AS DECIMAL(19,4)) AS debit, CAST(NULL AS DECIMAL(19,4)) AS credit,
                   CAST(NULL AS DECIMAL(19,4)) AS monthly_total, CAST(NULL AS DECIMAL(19,4)) AS overall_total
            WHERE 1 = 0;
            RETURN;
        END
        SET @Sql = N'SELECT ledger_id, ledger_name, debit, credit, monthly_total, overall_total
                     FROM ' + @T + N' WHERE company_id = @CompanyId;';
        EXEC sp_executesql @Sql, N'@CompanyId INT', @CompanyId;
        RETURN;
    END

    IF @Action = 'LIST_TABLES'
    BEGIN
        SELECT name AS table_name FROM sys.tables
        WHERE name LIKE '[A-Z][a-z][a-z][_][0-9][0-9]-Accounting[_]Ledger';
        RETURN;
    END

    IF @Action = 'DOC_DATE'
    BEGIN
        IF @DocType = 'voucher'
            SELECT company_id, voucher_date FROM dbo.Vouchers WHERE id = @DocId;
        ELSE
            SELECT TOP 1 company_id, voucher_date FROM dbo.JournalVoucher
            WHERE (@DocType = 'ticket' AND source_ticket_id = @DocId)
               OR (@DocType = 'reschedule' AND source_reschedule_ticket_id = @DocId)
               OR (@DocType = 'cancellation' AND source_cancellation_ticket_id = @DocId)
               OR (@DocType = 'ssr' AND source_ssr_ticket_id = @DocId)
               OR (@DocType = 'misc' AND source_misc_ticket_id = @DocId)
            ORDER BY id DESC;
        RETURN;
    END

    IF @Action = 'DATE_RANGE'
    BEGIN
        SELECT MIN(d) AS first_date, MAX(d) AS last_date FROM (
            SELECT voucher_date AS d FROM dbo.JournalVoucher WHERE company_id = @CompanyId
            UNION ALL
            SELECT voucher_date FROM dbo.Vouchers WHERE company_id = @CompanyId
        ) x;
        RETURN;
    END

    IF @Action = 'GET_STATUS'
    BEGIN
        SELECT company_id, is_dirty, built_at FROM dbo.Accounting_Ledger_Status WHERE company_id = @CompanyId;
        RETURN;
    END

    IF @Action = 'SET_STATUS'
    BEGIN
        IF @CompanyId IS NULL
            UPDATE dbo.Accounting_Ledger_Status SET is_dirty = @IsDirty;
        ELSE IF EXISTS (SELECT 1 FROM dbo.Accounting_Ledger_Status WHERE company_id = @CompanyId)
            UPDATE dbo.Accounting_Ledger_Status
            SET is_dirty = @IsDirty, built_at = CASE WHEN @IsDirty = 0 THEN SYSUTCDATETIME() ELSE built_at END
            WHERE company_id = @CompanyId;
        ELSE
            INSERT INTO dbo.Accounting_Ledger_Status (company_id, is_dirty, built_at)
            VALUES (@CompanyId, @IsDirty, CASE WHEN @IsDirty = 0 THEN SYSUTCDATETIME() END);
        SELECT 'Success' AS status;
        RETURN;
    END

    SELECT 'Error' AS status, 'Unknown @Action ' + ISNULL(@Action, '') AS error;
END
"""


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0093_remove_branch"),
    ]

    operations = [
        migrations.RunSQL(TABLE_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(PROC_SQL, migrations.RunSQL.noop),
    ]
