# Fills a gap in the migration history: Ticket, TicketLine and Voucher were
# added to models.py and created in Accounting_DB by hand (schema.sql), but
# no CreateModel migration was ever written for them — 0001_initial only
# covers LedgerGroup/Ledger. Without this, Django's migration graph can't
# build state for 0003 (which AddFields onto 'ticketline').
# The tables already exist — apply with: python manage.py migrate accounting --fake

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Ticket',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('company_id', models.IntegerField()),
                ('branch_name', models.CharField(blank=True, max_length=100, null=True)),
                ('invoice_number', models.CharField(max_length=20)),
                ('invoice_date', models.DateField()),
                ('invoice_type', models.CharField(blank=True, choices=[('Tax Invoice', 'Tax Invoice'), ('Others', 'Others')], max_length=20, null=True)),
                ('booking_mode', models.CharField(choices=[('Manual', 'Manual'), ('Auto Push', 'Auto Push')], default='Manual', max_length=20)),
                ('booking_type', models.CharField(blank=True, max_length=30, null=True)),
                ('booking_status', models.CharField(blank=True, choices=[('Confirmed', 'Confirmed'), ('Re-Scheduled', 'Re-Scheduled')], max_length=20, null=True)),
                ('travel_type', models.CharField(blank=True, choices=[('Domestic', 'Domestic'), ('International', 'International')], max_length=20, null=True)),
                ('user_name', models.CharField(blank=True, max_length=100, null=True)),
                ('currency', models.CharField(default='INR', max_length=5)),
                ('roe', models.DecimalField(decimal_places=4, default=1, max_digits=10)),
                ('booking_given_by', models.CharField(blank=True, max_length=25, null=True)),
                ('booking_reference', models.CharField(max_length=30)),
                ('booking_ref_date', models.DateField(blank=True, null=True)),
                ('airline_pnr', models.CharField(blank=True, max_length=13, null=True)),
                ('gds_pnr', models.CharField(blank=True, max_length=13, null=True)),
                ('office_id', models.CharField(blank=True, max_length=30, null=True)),
                ('payment_mode', models.CharField(blank=True, choices=[('Top-up', 'Top-up'), ('Payment Gateway', 'Payment Gateway')], max_length=20, null=True)),
                ('airline_category', models.CharField(blank=True, choices=[('LCC', 'LCC'), ('FSC', 'FSC'), ('OSC', 'OSC')], max_length=5, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('customer', models.ForeignKey(db_column='customer_ledger_id', on_delete=django.db.models.deletion.PROTECT, related_name='tickets_as_customer', to='accounting.ledger')),
                ('supplier', models.ForeignKey(blank=True, db_column='supplier_ledger_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='tickets_as_supplier', to='accounting.ledger')),
            ],
            options={
                'db_table': 'Tickets',
            },
        ),
        migrations.CreateModel(
            name='TicketLine',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('airline_code', models.CharField(blank=True, max_length=3, null=True)),
                ('airline_name', models.CharField(blank=True, max_length=60, null=True)),
                ('flight_no', models.CharField(blank=True, max_length=15, null=True)),
                ('ticket_no', models.CharField(max_length=30)),
                ('passenger_name', models.CharField(max_length=30)),
                ('pax_type', models.CharField(choices=[('Adult', 'Adult'), ('Child', 'Child'), ('Infant', 'Infant')], default='Adult', max_length=10)),
                ('sector', models.CharField(blank=True, max_length=40, null=True)),
                ('travel_date', models.DateField(blank=True, null=True)),
                ('basic_fare', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('yq', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('yr', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('k3_tax', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('tax_others', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('seat', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('meal', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('baggage', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('other_ssr', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('disc_on', models.CharField(blank=True, max_length=20, null=True)),
                ('disc_type', models.CharField(blank=True, choices=[('Percentage', 'Percentage'), ('Flat', 'Flat')], max_length=12, null=True)),
                ('disc_value', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('tds_per', models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ('markup', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('addl_markup', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('service_fee', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('addl_service_fee', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('gst_pct', models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ('total_billed', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('status', models.CharField(choices=[('ISSUED', 'Issued'), ('REFUNDED', 'Refunded'), ('VOID', 'Void'), ('EXCHANGED', 'Exchanged')], default='ISSUED', max_length=15)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('ticket', models.ForeignKey(db_column='ticket_id', on_delete=django.db.models.deletion.CASCADE, related_name='lines', to='accounting.ticket')),
            ],
            options={
                'db_table': 'TicketLines',
            },
        ),
        migrations.CreateModel(
            name='Voucher',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('company_id', models.IntegerField()),
                ('branch_name', models.CharField(blank=True, max_length=100, null=True)),
                ('voucher_type', models.CharField(choices=[('Journal', 'Journal'), ('Contra', 'Contra'), ('Payment', 'Payment'), ('Receipt', 'Receipt'), ('Debit Note', 'Debit Note'), ('Credit Note', 'Credit Note')], default='Journal', max_length=20)),
                ('voucher_date', models.DateField()),
                ('narration', models.CharField(blank=True, max_length=250, null=True)),
                ('category', models.CharField(default='MANUAL', max_length=20)),
                ('voucher_no', models.CharField(blank=True, max_length=20, null=True)),
                ('total_debit', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('total_credit', models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ('lines_json', models.JSONField(blank=True, default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('source_ticket', models.ForeignKey(blank=True, db_column='source_ticket_id', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='vouchers', to='accounting.ticket')),
            ],
            options={
                'db_table': 'Vouchers',
            },
        ),
        migrations.AddIndex(
            model_name='ticket',
            index=models.Index(fields=['company_id'], name='Tickets_company_e95274_idx'),
        ),
        migrations.AddConstraint(
            model_name='ticket',
            constraint=models.UniqueConstraint(fields=('company_id', 'invoice_number'), name='uq_ticket_company_invoice_no'),
        ),
        migrations.AddConstraint(
            model_name='ticket',
            constraint=models.UniqueConstraint(fields=('company_id', 'booking_reference'), name='uq_ticket_company_booking_ref'),
        ),
        migrations.AddIndex(
            model_name='ticketline',
            index=models.Index(fields=['ticket'], name='TicketLines_ticket__ba671e_idx'),
        ),
        migrations.AddConstraint(
            model_name='ticketline',
            constraint=models.UniqueConstraint(fields=('ticket_no',), name='uq_ticketline_ticket_no'),
        ),
        migrations.AddIndex(
            model_name='voucher',
            index=models.Index(fields=['company_id'], name='Vouchers_company_aabd4b_idx'),
        ),
        migrations.AddIndex(
            model_name='voucher',
            index=models.Index(fields=['source_ticket'], name='Vouchers_source__74d6da_idx'),
        ),
        migrations.AddConstraint(
            model_name='voucher',
            constraint=models.UniqueConstraint(fields=('company_id', 'voucher_no'), name='uq_voucher_company_no'),
        ),
    ]
