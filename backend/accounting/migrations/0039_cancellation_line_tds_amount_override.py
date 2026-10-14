from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0038_rename_tickets_company_e95274_idx_al_tickets_company_023cd9_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="cancellationairlineticketline",
            name="tds_amount_override",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True),
        ),
        migrations.AddField(
            model_name="cancellationairlineticketline",
            name="supp_tds_amount_override",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True),
        ),
    ]
