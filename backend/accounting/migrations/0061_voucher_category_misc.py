from django.db import migrations, models


def _check(categories):
    return f"""
IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'ck_voucher_type_category')
    ALTER TABLE dbo.VoucherType DROP CONSTRAINT ck_voucher_type_category;
ALTER TABLE dbo.VoucherType ADD CONSTRAINT ck_voucher_type_category
    CHECK (voucher_category IN ({categories}));
"""


BASE = "'Airline', 'Journal', 'Payment', 'Receipt', 'Contra', 'Debit Note', 'Credit Note'"


def update_check_forward(apps, schema_editor):
    if schema_editor.connection.vendor == "microsoft":
        schema_editor.execute(_check(BASE + ", 'Miscellaneous'"))


def update_check_backward(apps, schema_editor):
    if schema_editor.connection.vendor == "microsoft":
        schema_editor.execute(_check(BASE))


class Migration(migrations.Migration):
    """Voucher Type category "Miscellaneous" - its types are the Invoice Types of trans-misc.html only."""

    atomic = False
    dependencies = [("accounting", "0060_master_mapping_product_misc")]

    operations = [
        migrations.RunPython(update_check_forward, update_check_backward),
        migrations.AlterField(
            model_name="vouchertype", name="voucher_category",
            field=models.CharField(choices=[
                ("Airline", "Airline"), ("Journal", "Journal"), ("Payment", "Payment"), ("Receipt", "Receipt"),
                ("Contra", "Contra"), ("Debit Note", "Debit Note"), ("Credit Note", "Credit Note"),
                ("Miscellaneous", "Miscellaneous"),
            ], default="Airline", max_length=20),
        ),
    ]
