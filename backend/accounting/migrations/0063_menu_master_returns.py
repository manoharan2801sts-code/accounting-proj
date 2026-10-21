from django.db import migrations


def rename(title):
    def run(apps, schema_editor):
        apps.get_model("accounting", "MenuMaster").objects.filter(menu_key="rep-dsr").update(title=title)
    return run


class Migration(migrations.Migration):
    """Report "DSR" renamed "Returns" (menu_key rep-dsr unchanged - user permissions point at it)."""

    dependencies = [("accounting", "0062_voucher_no_plain_numbers")]

    operations = [migrations.RunPython(rename("Returns"), rename("DSR"))]
