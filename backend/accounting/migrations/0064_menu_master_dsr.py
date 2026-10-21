from django.db import migrations


def add(apps, schema_editor):
    # DSR - a second menu on the same report as Returns (report-dsr.html),
    # grantable in User Management on its own.
    apps.get_model("accounting", "MenuMaster").objects.update_or_create(
        menu_key="rep-dsr-report",
        defaults={"title": "DSR", "parent_key": None, "module": "Reports", "sort_order": 0, "is_active": True},
    )


def remove(apps, schema_editor):
    apps.get_model("accounting", "MenuMaster").objects.filter(menu_key="rep-dsr-report").delete()


class Migration(migrations.Migration):

    dependencies = [("accounting", "0063_menu_master_returns")]

    operations = [migrations.RunPython(add, remove)]
