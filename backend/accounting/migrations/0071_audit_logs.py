from django.db import migrations, models


def _check_table_exists(schema_editor, table_name):
    with schema_editor.connection.cursor() as cur:
        if schema_editor.connection.vendor == "microsoft":
            cur.execute("SELECT 1 FROM sys.tables WHERE name = %s", [table_name])
        else:
            cur.execute("SHOW TABLES LIKE %s", [table_name.lower()])
            if not cur.fetchone():
                cur.execute("SHOW TABLES LIKE %s", [table_name])
        return bool(cur.fetchone())


class SafeCreateModel(migrations.CreateModel):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        table_name = to_state.apps.get_model(app_label, self.name)._meta.db_table
        if _check_table_exists(schema_editor, table_name):
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


class SafeAddIndex(migrations.AddIndex):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        try:
            super().database_forwards(app_label, schema_editor, from_state, to_state)
        except Exception as e:
            err = str(e).lower()
            if "already exists" in err or "duplicate key" in err:
                return
            raise


class Migration(migrations.Migration):
    """Edit history (who changed what) of Booking / Reschedule / Cancellation / SSR Updation."""

    dependencies = [("accounting", "0070_airline_dropdown_values")]

    operations = [
        SafeCreateModel(
            name="AuditLog",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("company_id", models.IntegerField()),
                ("module", models.CharField(max_length=30)),
                ("document_id", models.IntegerField()),
                ("document_no", models.CharField(blank=True, max_length=50, null=True)),
                ("action", models.CharField(max_length=20)),
                ("source", models.CharField(blank=True, max_length=150, null=True)),
                ("user_id", models.IntegerField(blank=True, null=True)),
                ("user_name", models.CharField(blank=True, max_length=150, null=True)),
                ("change_count", models.IntegerField(default=0)),
                ("changes", models.TextField(blank=True, null=True)),
                ("changed_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "AuditLogs",
                "indexes": [models.Index(fields=["company_id", "module", "document_id"], name="ix_audit_logs_document")],
            },
        ),
    ]
