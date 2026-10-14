from django.db import migrations


def add(apps, schema_editor):
    # Balance Sheet is a real report now (balance_sheet_report) - grantable
    # in User Management like the other finished reports.
    apps.get_model("accounting", "MenuMaster").objects.update_or_create(
        menu_key="rep-balance-sheet",
        defaults={"title": "Balance Sheet", "parent_key": None, "module": "Reports", "sort_order": 9, "is_active": True},
    )


def remove(apps, schema_editor):
    apps.get_model("accounting", "MenuMaster").objects.filter(menu_key="rep-balance-sheet").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0039_cancellation_line_tds_amount_override"),
    ]

    operations = [
        migrations.RunPython(add, remove),
    ]
