# Removes Ledgers.airline_code — the "Airline Code (IATA)" field on the New
# Ledger form's Creditor detail section, dropped per the project owner's
# request. NOT TicketLine.airline_code (New Ticket form's per-passenger
# flight airline code) — that's a separate field on a separate model and
# is untouched.
# Run the ALTER TABLE in rough.txt by hand against Accounting_DB, then:
#   python manage.py migrate accounting --fake

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0007_rename_supp_disc_on_ticketline_supp_comm_on_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='ledger',
            name='airline_code',
        ),
    ]
