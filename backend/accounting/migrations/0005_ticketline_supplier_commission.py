# Supplier Commission fields on the ticket-entry modal's right-hand box
# (Cust Discount On / Discount Type / Discount Value / TDS %) — UI-only until
# now, this makes them persistable. Mirrors the existing customer discount
# fields (disc_on/disc_type/disc_value/tds_per).
# Run the ALTER TABLE below by hand against Accounting_DB, then:
#   python manage.py migrate accounting --fake
#
# ALTER TABLE TicketLines ADD
#     supp_disc_on      VARCHAR(20)     NULL,
#     supp_disc_type    VARCHAR(12)     NULL,
#     supp_disc_value   DECIMAL(14,2)   NOT NULL CONSTRAINT DF_TicketLines_supp_disc_value DEFAULT 0,
#     supp_tds_per      DECIMAL(5,2)    NOT NULL CONSTRAINT DF_TicketLines_supp_tds_per DEFAULT 0;

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0004_ledger_untracked_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticketline',
            name='supp_disc_on',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='ticketline',
            name='supp_disc_type',
            field=models.CharField(blank=True, choices=[('Percentage', 'Percentage'), ('Flat', 'Flat')], max_length=12, null=True),
        ),
        migrations.AddField(
            model_name='ticketline',
            name='supp_disc_value',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name='ticketline',
            name='supp_tds_per',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
    ]
