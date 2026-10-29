from django.db import migrations, models

# User Management: two more flags per (user, menu) next to View / Add /
# Edit / Delete -
#   can_print   Print button (reports, Receivables / Payables, Tax Invoice)
#   can_export  Export Excel button (reports, Receivables / Payables)
# Existing rows get both = can_view, so nobody loses what they had.
# sp_UserMenuAccess reads / saves them. Mirrored in Schema.sql and
# StoredProcedures.sql.

COLUMN_SQL = """
IF COL_LENGTH('dbo.UserMenuAccess', 'can_print') IS NULL
BEGIN
    ALTER TABLE dbo.UserMenuAccess ADD can_print BIT NOT NULL CONSTRAINT df_uma_can_print DEFAULT 0;
    ALTER TABLE dbo.UserMenuAccess ADD can_export BIT NOT NULL CONSTRAINT df_uma_can_export DEFAULT 0;
    -- Existing users keep printing / exporting every menu they can view.
    EXEC (N'UPDATE dbo.UserMenuAccess SET can_print = can_view, can_export = can_view;');
END
"""

PROC_SQL = """
CREATE OR ALTER PROCEDURE dbo.sp_UserMenuAccess
    @Action      NVARCHAR(50),
    @UserId      INT             = NULL,
    @CreatedBy   INT             = NULL,
    @AccessJson  NVARCHAR(MAX)   = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @Action = 'GET'
    BEGIN
        IF @UserId IS NULL OR NOT EXISTS (SELECT 1 FROM dbo.AppUsers WHERE id = @UserId)
        BEGIN
            SELECT NULL AS menu_key, 'Error' AS status, 'User not found.' AS error;
            RETURN;
        END

        SELECT
            mm.menu_key, mm.title, mm.parent_key, mm.module, mm.sort_order,
            ISNULL(uma.can_view, 0) AS can_view, ISNULL(uma.can_add, 0) AS can_add,
            ISNULL(uma.can_edit, 0) AS can_edit, ISNULL(uma.can_delete, 0) AS can_delete,
            ISNULL(uma.can_print, 0) AS can_print, ISNULL(uma.can_export, 0) AS can_export
        FROM dbo.MenuMaster mm
        LEFT JOIN dbo.UserMenuAccess uma ON uma.menu_key = mm.menu_key AND uma.user_id = @UserId
        WHERE mm.is_active = 1
        ORDER BY mm.module, mm.sort_order;
        RETURN;
    END

    IF @Action = 'SAVE'
    BEGIN
        IF @UserId IS NULL OR NOT EXISTS (SELECT 1 FROM dbo.AppUsers WHERE id = @UserId)
        BEGIN
            SELECT NULL AS menu_key, 'Error' AS status, 'User not found.' AS error;
            RETURN;
        END

        BEGIN TRY
            BEGIN TRAN;

            MERGE dbo.UserMenuAccess AS target
            USING (
                SELECT menu_key, can_view, can_add, can_edit, can_delete, ISNULL(can_print, 0) AS can_print, ISNULL(can_export, 0) AS can_export
                FROM OPENJSON(@AccessJson) WITH (
                    menu_key NVARCHAR(60) '$.menu_key',
                    can_view BIT '$.can_view',
                    can_add BIT '$.can_add',
                    can_edit BIT '$.can_edit',
                    can_delete BIT '$.can_delete',
                    can_print BIT '$.can_print',
                    can_export BIT '$.can_export'
                )
            ) AS src
            ON target.user_id = @UserId AND target.menu_key = src.menu_key
            WHEN MATCHED THEN
                UPDATE SET can_view = src.can_view, can_add = src.can_add, can_edit = src.can_edit,
                           can_delete = src.can_delete, can_print = src.can_print, can_export = src.can_export,
                           updated_at = SYSUTCDATETIME()
            WHEN NOT MATCHED THEN
                INSERT (user_id, menu_key, can_view, can_add, can_edit, can_delete, can_print, can_export, created_by_id, created_at, updated_at)
                VALUES (@UserId, src.menu_key, src.can_view, src.can_add, src.can_edit, src.can_delete, src.can_print, src.can_export, @CreatedBy, SYSUTCDATETIME(), SYSUTCDATETIME());

            COMMIT TRAN;
            SELECT @UserId AS user_id, 'Success' AS status;
        END TRY
        BEGIN CATCH
            IF @@TRANCOUNT > 0 ROLLBACK TRAN;
            SELECT NULL AS menu_key, 'Error' AS status, ERROR_MESSAGE() AS error;
        END CATCH
        RETURN;
    END
END
"""


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0090_direct_ssr_updation"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(COLUMN_SQL, migrations.RunSQL.noop)],
            state_operations=[
                migrations.AddField(model_name="usermenuaccess", name="can_print", field=models.BooleanField(default=False)),
                migrations.AddField(model_name="usermenuaccess", name="can_export", field=models.BooleanField(default=False)),
            ],
        ),
        migrations.RunSQL(PROC_SQL, migrations.RunSQL.noop),
    ]
