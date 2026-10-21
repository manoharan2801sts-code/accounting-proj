from django.db import migrations


def rename(title):
    def run(apps, schema_editor):
        apps.get_model("accounting", "MenuMaster").objects.filter(menu_key="accounts").update(title=title)
    return run


class Migration(migrations.Migration):
    """Masters menu "Chart of Accounts" renamed "Ledger Master" (menu_key accounts unchanged - user permissions point at it)."""

    dependencies = [("accounting", "0065_menu_master_dsr_order")]

    operations = [migrations.RunPython(rename("Ledger Master"), rename("Chart of Accounts"))]
