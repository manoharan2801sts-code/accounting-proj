from django.db import migrations


def add_check(apps, schema_editor):
    if schema_editor.connection.vendor == "microsoft":
        schema_editor.execute("ALTER TABLE dbo.Misc_Transactions ADD CONSTRAINT ck_misc_status CHECK (status IN ('Confirmed', 'Cancelled'));")
    else:
        try:
            schema_editor.execute("ALTER TABLE `Misc_Transactions` ADD CONSTRAINT `ck_misc_status` CHECK (`status` IN ('Confirmed', 'Cancelled'));")
        except Exception:
            pass


def drop_check(apps, schema_editor):
    if schema_editor.connection.vendor == "microsoft":
        schema_editor.execute("ALTER TABLE dbo.Misc_Transactions DROP CONSTRAINT ck_misc_status;")
    else:
        try:
            schema_editor.execute("ALTER TABLE `Misc_Transactions` DROP CHECK `ck_misc_status`;")
        except Exception:
            pass


class Migration(migrations.Migration):
    """Miscellaneous transaction Status - only Confirmed / Cancelled."""

    atomic = False
    dependencies = [("accounting", "0056_misc_transaction")]

    operations = [
        migrations.RunPython(add_check, drop_check),
    ]
