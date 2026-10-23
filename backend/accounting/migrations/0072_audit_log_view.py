from django.db import migrations

VIEW = """CREATE OR ALTER VIEW dbo.vw_AuditLogChanges AS
-- Edit history of the airline entries (Booking / Reschedule / Cancellation /
-- SSR Updation), one row per changed field - backend only, e.g.
--   SELECT * FROM dbo.vw_AuditLogChanges WHERE document_no = 'TA/TAX/00012/26-27' ORDER BY changed_at_ist DESC;
--   SELECT * FROM dbo.vw_AuditLogChanges WHERE user_name = 'Rahul Mehta' ORDER BY changed_at_ist DESC;
SELECT a.id AS log_id, a.company_id, a.module, a.document_id, a.document_no,
       a.action, a.source, a.user_id, a.user_name,
       DATEADD(MINUTE, 330, a.changed_at) AS changed_at_ist,   -- stored in UTC; +5:30 = India time
       j.scope, j.line AS passenger, j.field, j.old AS old_value, j.new AS new_value
FROM dbo.AuditLogs a
OUTER APPLY OPENJSON(NULLIF(a.changes, '[]')) WITH (
    scope NVARCHAR(40) '$.scope', line NVARCHAR(200) '$.line', field NVARCHAR(100) '$.field',
    old NVARCHAR(MAX) '$.old', new NVARCHAR(MAX) '$.new'
) j"""


def create_audit_view(apps, schema_editor):
    if schema_editor.connection.vendor == "microsoft":
        with schema_editor.connection.cursor() as cur:
            cur.execute(VIEW)


def drop_audit_view(apps, schema_editor):
    if schema_editor.connection.vendor == "microsoft":
        with schema_editor.connection.cursor() as cur:
            cur.execute("DROP VIEW IF EXISTS dbo.vw_AuditLogChanges;")


class Migration(migrations.Migration):
    """dbo.vw_AuditLogChanges - the edit history, one row per changed field (backend only)."""

    dependencies = [("accounting", "0071_audit_logs")]

    operations = [
        migrations.RunPython(create_audit_view, drop_audit_view),
    ]
