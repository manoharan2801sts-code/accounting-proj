from django.db import migrations


def add(apps, schema_editor):
    # Miscellaneous is a real transaction screen now (trans-misc.html) -
    # grantable in User Management like the Airline screens.
    apps.get_model("accounting", "MenuMaster").objects.update_or_create(
        menu_key="trans-misc",
        defaults={"title": "Miscellaneous", "parent_key": None, "module": "Transactions", "sort_order": 5, "is_active": True},
    )


def remove(apps, schema_editor):
    apps.get_model("accounting", "MenuMaster").objects.filter(menu_key="trans-misc").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0057_misc_status_check"),
    ]

    operations = [
        migrations.RunPython(add, remove),
    ]
