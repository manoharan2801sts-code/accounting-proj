# Ledger gained maintain_balance_bill_wise, place_of_supply, and the
# uq_ledger_agent_id constraint at some point after 0001_initial without a
# migration ever being written for them — makemigrations surfaced this as
# drift while fixing the Ticket/TicketLine/Voucher gap (see 0002). Unrelated
# to Supplier Commission; split out so that change stays scoped.
# If these already exist in Accounting_DB (likely, per this project's
# manual-SQL convention), apply with: python manage.py migrate accounting --fake

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0003_ticketline_supplier_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='ledger',
            name='maintain_balance_bill_wise',
            field=models.CharField(blank=True, max_length=5, null=True),
        ),
        migrations.AddField(
            model_name='ledger',
            name='place_of_supply',
            field=models.CharField(blank=True, max_length=60, null=True),
        ),
        migrations.AddConstraint(
            model_name='ledger',
            constraint=models.UniqueConstraint(condition=models.Q(('agent_id__isnull', False)), fields=('agent_id',), name='uq_ledger_agent_id'),
        ),
    ]
