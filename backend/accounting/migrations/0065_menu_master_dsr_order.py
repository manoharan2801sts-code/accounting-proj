from django.db import migrations


def order(returns, dsr):
    def run(apps, schema_editor):
        M = apps.get_model("accounting", "MenuMaster")
        M.objects.filter(menu_key="rep-dsr").update(sort_order=returns)
        M.objects.filter(menu_key="rep-dsr-report").update(sort_order=dsr)
    return run


class Migration(migrations.Migration):
    """Reports menu order: Returns first, then DSR."""

    dependencies = [("accounting", "0064_menu_master_dsr")]

    operations = [migrations.RunPython(order(0, 1), order(1, 0))]
