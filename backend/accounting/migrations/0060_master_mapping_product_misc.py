from django.db import migrations, models


def _check(products):
    return f"""
IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'ck_master_mapping_product_type')
    ALTER TABLE dbo.MasterMapping DROP CONSTRAINT ck_master_mapping_product_type;
ALTER TABLE dbo.MasterMapping ADD CONSTRAINT ck_master_mapping_product_type
    CHECK (product_type IN ({products}));
"""


BASE = "'Airline', 'Hotel', 'Bus', 'Visa', 'Insurance', 'Rail'"


def update_check_forward(apps, schema_editor):
    if schema_editor.connection.vendor == "microsoft":
        schema_editor.execute(_check(BASE + ", 'Miscellaneous'"))


def update_check_backward(apps, schema_editor):
    if schema_editor.connection.vendor == "microsoft":
        schema_editor.execute(_check(BASE))


class Migration(migrations.Migration):
    """Ledger Mapping product "Miscellaneous" - the Misc ledgers (trans-misc.html) live under it."""

    atomic = False
    dependencies = [("accounting", "0059_misc_other_taxes")]

    operations = [
        migrations.RunPython(update_check_forward, update_check_backward),
        migrations.AlterField(
            model_name="mastermapping", name="product_type",
            field=models.CharField(choices=[
                ("Airline", "Airline"), ("Hotel", "Hotel"), ("Bus", "Bus"), ("Visa", "Visa"),
                ("Insurance", "Insurance"), ("Rail", "Rail"), ("Miscellaneous", "Miscellaneous"),
            ], max_length=20),
        ),
    ]
