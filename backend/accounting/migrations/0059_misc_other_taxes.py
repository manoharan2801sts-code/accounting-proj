from django.db import migrations, models


class Migration(migrations.Migration):
    """Miscellaneous - Other Taxes (passed on to the customer like Base Amount)."""

    dependencies = [("accounting", "0058_menu_master_misc")]

    operations = [
        migrations.AddField(
            model_name="misctransaction", name="other_taxes",
            field=models.DecimalField(decimal_places=2, default=0, db_default=0, max_digits=14),
        ),
    ]
