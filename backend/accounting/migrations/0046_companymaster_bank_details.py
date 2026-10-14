from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0045_companymaster_terms_conditions"),
    ]

    operations = [
        migrations.AddField(
            model_name="companymaster",
            name="bank_account_holder",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="companymaster",
            name="bank_account_no",
            field=models.CharField(blank=True, max_length=30, null=True),
        ),
        migrations.AddField(
            model_name="companymaster",
            name="bank_ifsc",
            field=models.CharField(blank=True, max_length=15, null=True),
        ),
        migrations.AddField(
            model_name="companymaster",
            name="bank_swift",
            field=models.CharField(blank=True, max_length=15, null=True),
        ),
        migrations.AddField(
            model_name="companymaster",
            name="bank_name",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="companymaster",
            name="bank_branch",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
