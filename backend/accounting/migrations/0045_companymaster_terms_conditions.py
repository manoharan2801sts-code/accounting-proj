from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0044_companymaster_invoice_template"),
    ]

    operations = [
        migrations.AddField(
            model_name="companymaster",
            name="terms_conditions",
            field=models.TextField(blank=True, null=True),
        ),
    ]
