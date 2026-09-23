# Generated to match the manual ALTER TABLE run against Accounting_DB —
# apply with: python manage.py migrate accounting --fake
# (same workflow as 0001_initial.py: table already altered by hand via SQL,
# this just brings Django's migration history in line with it.)

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0002_ticket_ticketline_voucher'),
    ]

    operations = [
        migrations.AddField(
            model_name='ticketline',
            name='airline_category',
            field=models.CharField(blank=True, choices=[('LCC', 'LCC'), ('FSC', 'FSC'), ('OSC', 'OSC')], max_length=5, null=True),
        ),
        migrations.AddField(
            model_name='ticketline',
            name='office_id',
            field=models.CharField(blank=True, max_length=30, null=True),
        ),
        migrations.AddField(
            model_name='ticketline',
            name='fop',
            field=models.CharField(blank=True, choices=[('Own Card', 'Own Card'), ('Client Card', 'Client Card')], max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='ticketline',
            name='supplier',
            field=models.ForeignKey(blank=True, db_column='supplier_ledger_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='ticketlines_as_supplier', to='accounting.ledger'),
        ),
    ]