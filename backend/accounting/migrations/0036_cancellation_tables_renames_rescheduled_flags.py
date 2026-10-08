# 7.10.26 build (its 0028-0034): "Normal Cancelled" booking status, the
# Tickets/Reschedule table renames (AL_Tickets, AL_TicketLines,
# Rescheduled_Al_Ticket, Rescheduled_Al_TicketLines), the Cancellation
# tables, the canceled/rescheduled line flags and the Cancellation JV link.
#
# State: the build's own operations, unchanged. Database: one guarded
# step per change in raw MySQL/TiDB SQL, each safe to re-run - TiDB has no
# transactional DDL, so a deploy that fails half-way must be able to retry.
# Foreign keys are always added in their own ALTER (TiDB rejects ADD COLUMN
# + ADD CONSTRAINT FOREIGN KEY on that new column in one statement).

import django.db.models.deletion
from django.db import migrations, models


def _amount():
    return models.DecimalField(db_default=0, decimal_places=2, default=0, max_digits=14)


STATUS_CHOICES = [('Confirmed', 'Confirmed'), ('Re-Scheduled', 'Re-Scheduled'), ('Normal Cancelled', 'Normal Cancelled')]

TABLE_RENAMES = [
    ("Tickets", "AL_Tickets"),
    ("TicketLines", "AL_TicketLines"),
    ("RescheduleAirlineTickets", "Rescheduled_Al_Ticket"),
    ("RescheduleAirlineTicketLines", "Rescheduled_Al_TicketLines"),
]

INDEX_RENAMES = [
    ("Rescheduled_Al_Ticket", "RescheduleA_company_33ccf0_idx", "Rescheduled_company_4fdcb4_idx"),
    ("Rescheduled_Al_Ticket", "RescheduleA_origina_53e2da_idx", "Rescheduled_origina_e2e89d_idx"),
    ("Rescheduled_Al_TicketLines", "RescheduleA_resched_4fdae7_idx", "Rescheduled_resched_bdfda6_idx"),
    ("Rescheduled_Al_TicketLines", "RescheduleA_origina_075131_idx", "Rescheduled_origina_f43cd9_idx"),
]


def _tables(cursor, conn):
    return {t.lower(): t for t in conn.introspection.table_names(cursor)}


def _columns(cursor, conn, table):
    return {c.name.lower() for c in conn.introspection.get_table_description(cursor, table)}


def _constraints(cursor, conn, table):
    return {n.lower() for n in conn.introspection.get_constraints(cursor, table)}


def forwards(apps, schema_editor):
    conn = schema_editor.connection
    q = schema_editor.quote_name
    with conn.cursor() as cursor:
        # 1. Table renames.
        tables = _tables(cursor, conn)
        for old, new in TABLE_RENAMES:
            if old.lower() in tables and new.lower() not in tables:
                cursor.execute(f"RENAME TABLE {q(tables[old.lower()])} TO {q(new)}")
        tables = _tables(cursor, conn)

        # 2. Reschedule index renames (Django's auto names follow the table name).
        for table, old, new in INDEX_RENAMES:
            names = _constraints(cursor, conn, table)
            if old.lower() in names and new.lower() not in names:
                cursor.execute(f"ALTER TABLE {q(table)} RENAME INDEX {q(old)} TO {q(new)}")

        # 3. booking_status CHECK (local MySQL only - TiDB doesn't enforce CHECKs):
        #    allow 'Normal Cancelled' like the build's Schema.sql.
        if "ck_tickets_booking_status" in _constraints(cursor, conn, "AL_Tickets"):
            cursor.execute("ALTER TABLE `AL_Tickets` DROP CHECK `ck_tickets_booking_status`")
            cursor.execute(
                "ALTER TABLE `AL_Tickets` ADD CONSTRAINT `ck_tickets_booking_status` CHECK "
                "(`booking_status` IS NULL OR `booking_status` IN ('Confirmed', 'Re-Scheduled', 'Normal Cancelled'))"
            )

        # 4. canceled flag (default 0) on both line tables.
        for table in ("AL_TicketLines", "Rescheduled_Al_TicketLines"):
            if "canceled" not in _columns(cursor, conn, table):
                cursor.execute(f"ALTER TABLE {q(table)} ADD COLUMN `canceled` tinyint(1) NOT NULL DEFAULT 0")

        # 5. is_reschedule_eligible -> rescheduled, with the meaning inverted
        #    (eligible=1 means not yet rescheduled). Computed from the old
        #    column, so re-running before the old column is dropped is harmless.
        for table in ("AL_TicketLines", "Rescheduled_Al_TicketLines"):
            cols = _columns(cursor, conn, table)
            if "is_reschedule_eligible" in cols:
                if "rescheduled" not in cols:
                    cursor.execute(f"ALTER TABLE {q(table)} ADD COLUMN `rescheduled` tinyint(1) NOT NULL DEFAULT 0")
                cursor.execute(f"UPDATE {q(table)} SET `rescheduled` = 1 - `is_reschedule_eligible`")
                cursor.execute(f"ALTER TABLE {q(table)} DROP COLUMN `is_reschedule_eligible`")

        # 6. Cancellation tables, built from the final model state (Django
        #    adds their FKs as separate ALTERs after CREATE TABLE).
        tables = _tables(cursor, conn)
        for model_name in ("CancellationAirlineTicket", "CancellationAirlineTicketLine"):
            model = apps.get_model("accounting", model_name)
            if model._meta.db_table.lower() not in tables:
                schema_editor.create_model(model)
        for sql in schema_editor.deferred_sql:
            schema_editor.execute(sql)
        schema_editor.deferred_sql.clear()

        # 7. JournalVoucher -> Cancellation link: column, index, FK - each on its own.
        cols = _columns(cursor, conn, "JournalVoucher")
        if "source_cancellation_ticket_id" not in cols:
            cursor.execute("ALTER TABLE `JournalVoucher` ADD COLUMN `source_cancellation_ticket_id` integer NULL")
        names = _constraints(cursor, conn, "JournalVoucher")
        if "journal_voucher_ctid_idx" not in names:
            cursor.execute("CREATE INDEX `journal_voucher_ctid_idx` ON `JournalVoucher` (`source_cancellation_ticket_id`)")
        if "fk_journal_voucher_cancellation" not in names:
            cursor.execute(
                "ALTER TABLE `JournalVoucher` ADD CONSTRAINT `fk_journal_voucher_cancellation` "
                "FOREIGN KEY (`source_cancellation_ticket_id`) REFERENCES `Cancellation_AL_Tickets` (`id`) ON DELETE SET NULL"
            )


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ('accounting', '0035_reschedule_jv_posting_eligibility_chain'),
    ]

    state_operations = [
        # 0028
        migrations.AlterField(model_name='rescheduleairlineticket', name='booking_status',
                              field=models.CharField(blank=True, choices=STATUS_CHOICES, max_length=20, null=True)),
        migrations.AlterField(model_name='ticket', name='booking_status',
                              field=models.CharField(blank=True, choices=STATUS_CHOICES, max_length=20, null=True)),
        # 0029
        migrations.RenameIndex(model_name='rescheduleairlineticket', new_name='Rescheduled_company_4fdcb4_idx', old_name='RescheduleA_company_33ccf0_idx'),
        migrations.RenameIndex(model_name='rescheduleairlineticket', new_name='Rescheduled_origina_e2e89d_idx', old_name='RescheduleA_origina_53e2da_idx'),
        migrations.RenameIndex(model_name='rescheduleairlineticketline', new_name='Rescheduled_resched_bdfda6_idx', old_name='RescheduleA_resched_4fdae7_idx'),
        migrations.RenameIndex(model_name='rescheduleairlineticketline', new_name='Rescheduled_origina_f43cd9_idx', old_name='RescheduleA_origina_075131_idx'),
        migrations.AlterModelTable(name='rescheduleairlineticket', table='Rescheduled_Al_Ticket'),
        migrations.AlterModelTable(name='rescheduleairlineticketline', table='Rescheduled_Al_TicketLines'),
        migrations.AlterModelTable(name='ticket', table='AL_Tickets'),
        migrations.AlterModelTable(name='ticketline', table='AL_TicketLines'),
        # 0030
        migrations.CreateModel(
            name='CancellationAirlineTicket',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('company_id', models.IntegerField()),
                ('branch_name', models.CharField(blank=True, max_length=100, null=True)),
                ('invoice_number', models.CharField(max_length=20)),
                ('invoice_date', models.DateField()),
                ('invoice_type', models.CharField(blank=True, max_length=100, null=True)),
                ('booking_mode', models.CharField(choices=[('Manual', 'Manual'), ('Auto Push', 'Auto Push')], default='Manual', max_length=20)),
                ('booking_type', models.CharField(blank=True, max_length=30, null=True)),
                ('booking_status', models.CharField(blank=True, choices=STATUS_CHOICES, max_length=20, null=True)),
                ('travel_type', models.CharField(blank=True, choices=[('Domestic', 'Domestic'), ('International', 'International')], max_length=20, null=True)),
                ('user_name', models.CharField(blank=True, max_length=100, null=True)),
                ('currency', models.CharField(default='INR', max_length=5)),
                ('roe', models.DecimalField(decimal_places=4, default=1, max_digits=10)),
                ('booking_given_by', models.CharField(blank=True, max_length=25, null=True)),
                ('cancellation_reference', models.CharField(max_length=30)),
                ('cancellation_ref_date', models.DateField(blank=True, null=True)),
                ('airline_pnr', models.CharField(blank=True, max_length=13, null=True)),
                ('gds_pnr', models.CharField(blank=True, max_length=13, null=True)),
                ('office_id', models.CharField(blank=True, max_length=30, null=True)),
                ('payment_mode', models.CharField(blank=True, choices=[('Top-up', 'Top-up'), ('Payment Gateway', 'Payment Gateway')], max_length=20, null=True)),
                ('payment_gateway_ref', models.CharField(blank=True, max_length=60, null=True)),
                ('airline_category', models.CharField(blank=True, choices=[('LCC', 'LCC'), ('FSC', 'FSC'), ('OSC', 'OSC')], max_length=5, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'db_table': 'Cancellation_AL_Tickets'},
        ),
        migrations.CreateModel(
            name='CancellationAirlineTicketLine',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('airline_code', models.CharField(blank=True, max_length=200, null=True)),
                ('airline_name', models.CharField(blank=True, max_length=200, null=True)),
                ('airline_category', models.CharField(blank=True, choices=[('LCC', 'LCC'), ('FSC', 'FSC'), ('OSC', 'OSC')], max_length=5, null=True)),
                ('flight_no', models.CharField(blank=True, max_length=200, null=True)),
                ('ticket_no', models.CharField(max_length=30)),
                ('passenger_name', models.CharField(max_length=50)),
                ('pax_type', models.CharField(choices=[('Adult', 'Adult'), ('Child', 'Child'), ('Infant', 'Infant')], default='Adult', max_length=10)),
                ('sector', models.CharField(blank=True, max_length=200, null=True)),
                ('travel_date', models.CharField(blank=True, max_length=200, null=True)),
                ('cabin', models.CharField(blank=True, max_length=200, null=True)),
                ('travel_class', models.CharField(blank=True, max_length=200, null=True)),
                ('fare_type', models.CharField(blank=True, max_length=300, null=True)),
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
                ('pg_charges', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('pg_charges_percentage', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('markup', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('addl_markup', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('ssr_markup', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('service_fee', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('addl_service_fee', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('ssr_service_fee', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('gst_pct', models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ('supp_comm_on', models.CharField(blank=True, max_length=20, null=True)),
                ('supp_comm_type', models.CharField(blank=True, choices=[('Percentage', 'Percentage'), ('Flat', 'Flat')], max_length=12, null=True)),
                ('supp_comm_value', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('supp_tds_per', models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ('supp_markup', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('supp_addl_markup', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('supp_service_fee', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('supp_addl_service_fee', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('supp_gst_pct', models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ('total_billed', models.DecimalField(decimal_places=2, default=0, max_digits=14)),
                ('status', models.CharField(choices=[('ISSUED', 'Issued'), ('REFUNDED', 'Refunded'), ('VOID', 'Void'), ('EXCHANGED', 'Exchanged')], default='ISSUED', max_length=15)),
                ('office_id', models.CharField(blank=True, max_length=30, null=True)),
                ('fop', models.CharField(blank=True, choices=[('Own Card', 'Own Card'), ('Client Card', 'Client Card'), ('Cash', 'Cash')], max_length=20, null=True)),
                ('card_number', models.CharField(blank=True, max_length=40, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'db_table': 'Cancellation_Al_TicketLines'},
        ),
        migrations.AddField(model_name='cancellationairlineticket', name='customer',
                            field=models.ForeignKey(db_column='customer_ledger_id', on_delete=django.db.models.deletion.PROTECT, related_name='cancellations_as_customer', to='accounting.ledger')),
        migrations.AddField(model_name='cancellationairlineticket', name='original_ticket',
                            field=models.ForeignKey(db_column='original_ticket_id', on_delete=django.db.models.deletion.PROTECT, related_name='cancellations', to='accounting.ticket')),
        migrations.AddField(model_name='cancellationairlineticket', name='supplier',
                            field=models.ForeignKey(blank=True, db_column='supplier_ledger_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='cancellations_as_supplier', to='accounting.ledger')),
        migrations.AddField(model_name='cancellationairlineticketline', name='cancellation_ticket',
                            field=models.ForeignKey(db_column='cancellation_ticket_id', on_delete=django.db.models.deletion.CASCADE, related_name='lines', to='accounting.cancellationairlineticket')),
        migrations.AddField(model_name='cancellationairlineticketline', name='original_ticket_line',
                            field=models.OneToOneField(db_column='original_ticket_line_id', on_delete=django.db.models.deletion.PROTECT, related_name='cancellation_line', to='accounting.ticketline')),
        migrations.AddField(model_name='cancellationairlineticketline', name='supplier',
                            field=models.ForeignKey(blank=True, db_column='supplier_ledger_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='cancellationlines_as_supplier', to='accounting.ledger')),
        migrations.AddIndex(model_name='cancellationairlineticket', index=models.Index(fields=['company_id'], name='Cancellatio_company_1fb6d9_idx')),
        migrations.AddIndex(model_name='cancellationairlineticket', index=models.Index(fields=['original_ticket'], name='Cancellatio_origina_fbd2ca_idx')),
        migrations.AddConstraint(model_name='cancellationairlineticket', constraint=models.UniqueConstraint(fields=('company_id', 'invoice_number'), name='uq_cancel_ticket_company_invoice_no')),
        migrations.AddConstraint(model_name='cancellationairlineticket', constraint=models.UniqueConstraint(fields=('company_id', 'cancellation_reference'), name='uq_cancel_ticket_company_cancel_ref')),
        migrations.AddIndex(model_name='cancellationairlineticketline', index=models.Index(fields=['cancellation_ticket'], name='Cancellatio_cancell_f89a18_idx')),
        migrations.AddConstraint(model_name='cancellationairlineticketline', constraint=models.UniqueConstraint(fields=('ticket_no',), name='uq_cancel_ticketline_ticket_no')),
        # 0031 / 0032
        migrations.AddField(model_name='rescheduleairlineticketline', name='canceled', field=models.BooleanField(db_default=False, default=False)),
        migrations.AddField(model_name='ticketline', name='canceled', field=models.BooleanField(db_default=False, default=False)),
        # 0033
        migrations.RenameField(model_name='ticketline', old_name='is_reschedule_eligible', new_name='rescheduled'),
        migrations.RenameField(model_name='rescheduleairlineticketline', old_name='is_reschedule_eligible', new_name='rescheduled'),
        migrations.AlterField(model_name='ticketline', name='rescheduled', field=models.BooleanField(db_default=False, default=False)),
        migrations.AlterField(model_name='rescheduleairlineticketline', name='rescheduled', field=models.BooleanField(db_default=False, default=False)),
        # 0034
        migrations.AddField(model_name='cancellationairlineticketline', name='supplier_penalty', field=_amount()),
        migrations.AddField(model_name='cancellationairlineticketline', name='cancellation_penalty', field=_amount()),
        migrations.AddField(model_name='cancellationairlineticketline', name='agent_penalty', field=_amount()),
        migrations.AddField(model_name='cancellationairlineticketline', name='cust_markup_reversal', field=_amount()),
        migrations.AddField(model_name='cancellationairlineticketline', name='cust_addl_markup_reversal', field=_amount()),
        migrations.AddField(model_name='cancellationairlineticketline', name='cust_ssr_markup_reversal', field=_amount()),
        migrations.AddField(model_name='cancellationairlineticketline', name='supp_markup_reversal', field=_amount()),
        migrations.AddField(model_name='cancellationairlineticketline', name='supp_addl_markup_reversal', field=_amount()),
        migrations.AddField(model_name='journalvoucher', name='source_cancellation_ticket',
                            field=models.ForeignKey(blank=True, db_column='source_cancellation_ticket_id', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='vouchers', to='accounting.cancellationairlineticket')),
        migrations.AddIndex(model_name='journalvoucher', index=models.Index(fields=['source_cancellation_ticket'], name='journal_voucher_ctid_idx')),
    ]

    # State first, so forwards() sees the final models (the Cancellation tables).
    operations = [
        migrations.SeparateDatabaseAndState(state_operations=state_operations, database_operations=[]),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
