from django.db import migrations, models


def _swap(old, new):
    """Voucher Type "Type of Voucher": rename the stored category value
    `old` -> `new` - check constraint, column default and existing rows."""
    others = "'Journal', 'Payment', 'Receipt', 'Contra', 'Debit Note', 'Credit Note'"
    return f"""
IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'ck_voucher_type_category')
    ALTER TABLE dbo.VoucherType DROP CONSTRAINT ck_voucher_type_category;
UPDATE dbo.VoucherType SET voucher_category = '{new}' WHERE voucher_category = '{old}';
DECLARE @df SYSNAME = (SELECT dc.name FROM sys.default_constraints dc
    JOIN sys.columns c ON c.object_id = dc.parent_object_id AND c.column_id = dc.parent_column_id
    WHERE dc.parent_object_id = OBJECT_ID('dbo.VoucherType') AND c.name = 'voucher_category');
IF @df IS NOT NULL EXEC('ALTER TABLE dbo.VoucherType DROP CONSTRAINT [' + @df + ']');
ALTER TABLE dbo.VoucherType ADD CONSTRAINT df_voucher_type_category DEFAULT '{new}' FOR voucher_category;
ALTER TABLE dbo.VoucherType ADD CONSTRAINT ck_voucher_type_category
    CHECK (voucher_category IN ('{new}', {others}));
"""


def swap_forward(apps, schema_editor):
    if schema_editor.connection.vendor == "microsoft":
        schema_editor.execute(_swap("General", "Airline"))
    else:
        apps.get_model("accounting", "VoucherType").objects.filter(voucher_category="General").update(voucher_category="Airline")


def swap_backward(apps, schema_editor):
    if schema_editor.connection.vendor == "microsoft":
        schema_editor.execute(_swap("Airline", "General"))
    else:
        apps.get_model("accounting", "VoucherType").objects.filter(voucher_category="Airline").update(voucher_category="General")


class Migration(migrations.Migration):
    """Voucher Type category "General" renamed to "Airline" (the ticket invoice
    types - Tax Invoice, Sales Air ...)."""

    atomic = False
    dependencies = [("accounting", "0054_master_mapping_history")]

    operations = [
        migrations.RunPython(swap_forward, swap_backward),
        migrations.AlterField(
            model_name="vouchertype", name="voucher_category",
            field=models.CharField(choices=[
                ("Airline", "Airline"), ("Journal", "Journal"), ("Payment", "Payment"), ("Receipt", "Receipt"),
                ("Contra", "Contra"), ("Debit Note", "Debit Note"), ("Credit Note", "Credit Note"),
            ], default="Airline", max_length=20),
        ),
    ]
