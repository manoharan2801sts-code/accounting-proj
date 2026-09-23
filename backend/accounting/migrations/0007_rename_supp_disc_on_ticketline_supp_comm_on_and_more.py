# Renames TicketLine's supp_disc_* columns to supp_comm_* — the frontend
# labels these "Commission Type"/"Commission %"/"Commission Amount" (not
# "Discount"), so the DB column names were out of step with the UI.
# Run the sp_rename statements in rough.txt by hand against Accounting_DB,
# then: python manage.py migrate accounting --fake

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0006_ticketline_fop_add_cash'),
    ]

    operations = [
        migrations.RenameField(
            model_name='ticketline',
            old_name='supp_disc_on',
            new_name='supp_comm_on',
        ),
        migrations.RenameField(
            model_name='ticketline',
            old_name='supp_disc_type',
            new_name='supp_comm_type',
        ),
        migrations.RenameField(
            model_name='ticketline',
            old_name='supp_disc_value',
            new_name='supp_comm_value',
        ),
    ]
