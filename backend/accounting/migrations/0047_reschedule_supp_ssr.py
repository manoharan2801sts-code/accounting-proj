from django.db import migrations, models


class Migration(migrations.Migration):
    """Supplier SSR Markup / SSR Service Fee on Reschedule lines (same as TicketLine's)."""

    dependencies = [("accounting", "0046_companymaster_bank_details")]

    operations = [
        migrations.AddField(
            model_name="rescheduleairlineticketline", name="supp_ssr_markup",
            field=models.DecimalField(decimal_places=2, default=0, db_default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="rescheduleairlineticketline", name="supp_ssr_service_fee",
            field=models.DecimalField(decimal_places=2, default=0, db_default=0, max_digits=14),
        ),
    ]
