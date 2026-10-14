from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0043_ssr_airline_ticket"),
    ]

    operations = [
        migrations.AddField(
            model_name="companymaster",
            name="invoice_template",
            field=models.CharField(db_default="classic", default="classic", max_length=20),
        ),
    ]
