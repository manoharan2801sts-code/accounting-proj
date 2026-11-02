from django.db import migrations

# The month-wise ledger summary becomes year-wise: one table per financial
# year (Apr - Mar), [YY-YY-Accounting_Ledger] (e.g. [26-27-Accounting_Ledger]),
# each month as columns (<Mon>_Cr, <Mon>_Dr, <Mon>_Balance) + Overall_Total.
# The per-month tables of 0094 are dropped; every company is rebuilt before
# its next report. Mirrored in StoredProcedures.sql.

PROC_SQL = r"""
CREATE OR ALTER PROCEDURE dbo.sp_AccountingLedger
    -- Year-wise ledger summary: one table per financial year (Apr - Mar),
    -- [YY-YY-Accounting_Ledger] (e.g. [26-27-Accounting_Ledger]), created on its
    -- first SAVE_YEAR. One row per company + ledger:
    --   Ledger_Name, Opening_Balance (ledger opening / previous year's Overall_Total),
    --   per month <Mon>_Cr, <Mon>_Dr, <Mon>_Balance (Dr - Cr) from Apr up to the last
    --   month with postings, and Overall_Total (Opening_Balance + every month's Balance).
    -- A month's columns are added when it first has postings - the table is rebuilt
    -- (rows kept) so the months stay in order and Overall_Total stays the last column.
    -- Rows are worked out in Python (accounting/ledger_months.py).
    -- SAVE_YEAR   : replaces @CompanyId's rows of @TableName with @RowsJson; @MonthsJson
    --               ["Apr", "May", ...] = the month columns the rows carry.
    -- READ_YEAR   : @CompanyId's rows of @TableName (none when the table does not exist).
    -- LIST_TABLES : every year table that exists.
    -- DOC_DATE    : company + voucher date of one document (@DocType ticket / reschedule /
    --               cancellation / ssr / misc / voucher, @DocId) - the date its month is decided by.
    -- DATE_RANGE  : @CompanyId's first and last voucher date (Journal Vouchers + manual Vouchers).
    -- GET_STATUS / SET_STATUS : @CompanyId's dirty flag (SET_STATUS with no @CompanyId = every company).
    @Action      NVARCHAR(30),
    @CompanyId   INT            = NULL,
    @TableName   SYSNAME        = NULL,
    @RowsJson    NVARCHAR(MAX)  = NULL,
    @MonthsJson  NVARCHAR(400)  = NULL,
    @DocType     NVARCHAR(20)   = NULL,
    @DocId       INT            = NULL,
    @IsDirty     BIT            = NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF @TableName IS NOT NULL AND @TableName NOT LIKE '[0-9][0-9]-[0-9][0-9]-Accounting[_]Ledger'
    BEGIN
        SELECT 'Error' AS status, 'Invalid year table name "' + @TableName + '".' AS error;
        RETURN;
    END
    DECLARE @T NVARCHAR(300) = N'dbo.' + QUOTENAME(@TableName), @Sql NVARCHAR(MAX);

    IF @Action = 'SAVE_YEAR'
    BEGIN
        DECLARE @Fy TABLE (seq INT PRIMARY KEY, mon NVARCHAR(3));
        INSERT INTO @Fy VALUES (1, 'Apr'), (2, 'May'), (3, 'Jun'), (4, 'Jul'), (5, 'Aug'), (6, 'Sep'),
                               (7, 'Oct'), (8, 'Nov'), (9, 'Dec'), (10, 'Jan'), (11, 'Feb'), (12, 'Mar');
        DECLARE @Sent TABLE (mon NVARCHAR(10));
        INSERT INTO @Sent SELECT [value] FROM OPENJSON(ISNULL(@MonthsJson, N'[]'));
        IF EXISTS (SELECT 1 FROM @Sent s WHERE NOT EXISTS (SELECT 1 FROM @Fy f WHERE f.mon = s.mon))
        BEGIN
            SELECT 'Error' AS status, 'Invalid month in @MonthsJson.' AS error;
            RETURN;
        END

        -- Month columns of the table: the ones it has + the ones sent, in Apr..Mar order.
        DECLARE @Seq INT = 1, @Mon NVARCHAR(3), @Count INT = 0, @Missing BIT = 0,
                @Defs NVARCHAR(MAX) = N'', @Keep NVARCHAR(MAX) = N'', @Cols NVARCHAR(MAX) = N'', @With NVARCHAR(MAX) = N'';
        WHILE @Seq <= 12
        BEGIN
            SELECT @Mon = mon FROM @Fy WHERE seq = @Seq;
            DECLARE @Has BIT = CASE WHEN OBJECT_ID(@T, 'U') IS NOT NULL AND COL_LENGTH(@T, @Mon + '_Cr') IS NOT NULL THEN 1 ELSE 0 END,
                    @Want BIT = CASE WHEN EXISTS (SELECT 1 FROM @Sent WHERE mon = @Mon) THEN 1 ELSE 0 END;
            IF @Has = 1 OR @Want = 1
            BEGIN
                SET @Count += 1;
                SET @Defs += N', ' + QUOTENAME(@Mon + N'_Cr') + N' DECIMAL(19,4) NULL, ' + QUOTENAME(@Mon + N'_Dr')
                           + N' DECIMAL(19,4) NULL, ' + QUOTENAME(@Mon + N'_Balance') + N' DECIMAL(19,4) NULL';
            END
            IF @Has = 1
                SET @Keep += N', ' + QUOTENAME(@Mon + N'_Cr') + N', ' + QUOTENAME(@Mon + N'_Dr') + N', ' + QUOTENAME(@Mon + N'_Balance');
            IF @Want = 1
            BEGIN
                SET @Cols += N', ' + QUOTENAME(@Mon + N'_Cr') + N', ' + QUOTENAME(@Mon + N'_Dr') + N', ' + QUOTENAME(@Mon + N'_Balance');
                SET @With += N', ' + QUOTENAME(@Mon + N'_Cr') + N' DECIMAL(19,4) ''$.' + @Mon + N'_Cr'', '
                           + QUOTENAME(@Mon + N'_Dr') + N' DECIMAL(19,4) ''$.' + @Mon + N'_Dr'', '
                           + QUOTENAME(@Mon + N'_Balance') + N' DECIMAL(19,4) ''$.' + @Mon + N'_Balance''';
                IF @Has = 0 SET @Missing = 1;
            END
            SET @Seq += 1;
        END

        DECLARE @Create NVARCHAR(MAX) = N' (
                company_id       INT            NOT NULL,
                ledger_id        INT            NOT NULL,
                Ledger_Name      NVARCHAR(200)  NULL,
                Opening_Balance  DECIMAL(19,4)  NOT NULL' + @Defs + N',
                Overall_Total    DECIMAL(19,4)  NOT NULL,
                updated_at       DATETIME2      NOT NULL CONSTRAINT ' + QUOTENAME(N'df_' + @TableName + N'_' + CAST(@Count AS NVARCHAR(2)))
                + N' DEFAULT SYSUTCDATETIME(),
                CONSTRAINT ' + QUOTENAME(N'pk_' + @TableName + N'_' + CAST(@Count AS NVARCHAR(2))) + N' PRIMARY KEY (company_id, ledger_id)
            );';
        IF OBJECT_ID(@T, 'U') IS NULL
        BEGIN
            SET @Sql = N'CREATE TABLE ' + @T + @Create;
            EXEC sp_executesql @Sql;
        END
        ELSE IF @Missing = 1
        BEGIN
            -- New month: rebuild the table with its columns in order, every company's rows kept.
            DECLARE @NewName SYSNAME = @TableName + N'__new', @N NVARCHAR(300);
            SET @N = N'dbo.' + QUOTENAME(@NewName);
            SET @Sql = N'CREATE TABLE ' + @N + @Create + N'
                INSERT INTO ' + @N + N' (company_id, ledger_id, Ledger_Name, Opening_Balance' + @Keep + N', Overall_Total, updated_at)
                SELECT company_id, ledger_id, Ledger_Name, Opening_Balance' + @Keep + N', Overall_Total, updated_at FROM ' + @T + N';
                DROP TABLE ' + @T + N';';
            EXEC sp_executesql @Sql;
            SET @N = N'dbo.' + @NewName;
            EXEC sp_rename @N, @TableName;
        END

        DECLARE @Saved INT;
        SET @Sql = N'DELETE FROM ' + @T + N' WHERE company_id = @CompanyId;
            INSERT INTO ' + @T + N' (company_id, ledger_id, Ledger_Name, Opening_Balance' + @Cols + N', Overall_Total)
            SELECT @CompanyId, j.* FROM OPENJSON(@RowsJson) WITH (
                ledger_id INT ''$.ledger_id'', Ledger_Name NVARCHAR(200) ''$.Ledger_Name'',
                Opening_Balance DECIMAL(19,4) ''$.Opening_Balance''' + @With + N',
                Overall_Total DECIMAL(19,4) ''$.Overall_Total''
            ) j;
            SELECT @Saved = @@ROWCOUNT;';
        EXEC sp_executesql @Sql, N'@CompanyId INT, @RowsJson NVARCHAR(MAX), @Saved INT OUTPUT',
             @CompanyId, @RowsJson, @Saved OUTPUT;
        SELECT 'Success' AS status, @TableName AS table_name, @Saved AS rows_saved;
        RETURN;
    END

    IF @Action = 'READ_YEAR'
    BEGIN
        IF OBJECT_ID(@T, 'U') IS NULL
        BEGIN
            SELECT CAST(NULL AS INT) AS ledger_id WHERE 1 = 0;
            RETURN;
        END
        SET @Sql = N'SELECT * FROM ' + @T + N' WHERE company_id = @CompanyId;';
        EXEC sp_executesql @Sql, N'@CompanyId INT', @CompanyId;
        RETURN;
    END

    IF @Action = 'LIST_TABLES'
    BEGIN
        SELECT name AS table_name FROM sys.tables
        WHERE name LIKE '[0-9][0-9]-[0-9][0-9]-Accounting[_]Ledger';
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

DROP_MONTH_TABLES = """
DECLARE @drop NVARCHAR(MAX) = N'';
SELECT @drop += N'DROP TABLE dbo.' + QUOTENAME(name) + N';' FROM sys.tables
WHERE name LIKE '[A-Z][a-z][a-z][_][0-9][0-9]-Accounting[_]Ledger';
EXEC sp_executesql @drop;
UPDATE dbo.Accounting_Ledger_Status SET is_dirty = 1;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0094_accounting_ledger_months"),
    ]

    operations = [
        migrations.RunSQL(PROC_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(DROP_MONTH_TABLES, migrations.RunSQL.noop),
    ]
