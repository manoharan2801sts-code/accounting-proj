from django.db import migrations, models


class Migration(migrations.Migration):
    # The two columns are written by dbo.sp_Ticket (raw SQL), so they need a
    # real DB-level default, not just Django's default.

    dependencies = [
        ("accounting", "0041_ticketline_supp_ssr_markup_service_fee"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ticketline",
            name="supp_ssr_markup",
            field=models.DecimalField(decimal_places=2, default=0, db_default=0, max_digits=14),
        ),
        migrations.AlterField(
            model_name="ticketline",
            name="supp_ssr_service_fee",
            field=models.DecimalField(decimal_places=2, default=0, db_default=0, max_digits=14),
        ),
    ]
