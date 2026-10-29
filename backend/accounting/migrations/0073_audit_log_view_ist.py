from django.db import migrations

VIEW = """CREATE OR ALTER VIEW dbo.vw_AuditLogChanges AS
-- Edit history of the airline entries (Booking / Reschedule / Cancellation /
-- SSR Updation), one row per changed field - backend only, e.g.
--   SELECT * FROM dbo.vw_AuditLogChanges WHERE document_no = 'TA/TAX/00012/26-27' ORDER BY changed_at_ist DESC;
--   SELECT * FROM dbo.vw_AuditLogChanges WHERE user_name = 'Rahul Mehta' ORDER BY changed_at_ist DESC;
SELECT a.id AS log_id, a.company_id, a.module, a.document_id, a.document_no,
       a.action, a.source, a.user_id, a.user_name,
       CAST(SWITCHOFFSET(a.changed_at, '+05:30') AS DATETIME2(0)) AS changed_at_ist,   -- stored in UTC; shown in India time
       j.scope, j.line AS passenger, j.field, j.old AS old_value, j.new AS new_value
FROM dbo.AuditLogs a
OUTER APPLY OPENJSON(NULLIF(a.changes, '[]')) WITH (
    scope NVARCHAR(40) '$.scope', line NVARCHAR(200) '$.line', field NVARCHAR(100) '$.field',
    old NVARCHAR(MAX) '$.old', new NVARCHAR(MAX) '$.new'
) j"""


class Migration(migrations.Migration):
    """vw_AuditLogChanges: changed_at_ist as a plain India date-time (no "+00:00" offset)."""

    dependencies = [("accounting", "0072_audit_log_view")]

    operations = [migrations.RunSQL(VIEW, migrations.RunSQL.noop)]
