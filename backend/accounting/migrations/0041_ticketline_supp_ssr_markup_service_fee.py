from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0040_menu_master_balance_sheet"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticketline",
            name="supp_ssr_markup",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="ticketline",
            name="supp_ssr_service_fee",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
    ]
