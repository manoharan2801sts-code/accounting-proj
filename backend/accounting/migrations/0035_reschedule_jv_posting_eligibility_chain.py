# 5.10.26 build (its 0024-0027): reschedule JV posting link on
# JournalVoucher, reschedule-eligibility flags, chained reschedules
# (based_on_reschedule_line) and stored parent_pnr. Guarded like
# 0032-0034 so a retried deploy on TiDB (no transactional DDL) doesn't fail.

import django.db.models.deletion
from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class IfNeeded(Operation):
    reduces_to_sql = False
    reversible = True

    def __init__(self, inner):
        self.inner = inner

    def state_forwards(self, app_label, state):
        self.inner.state_forwards(app_label, state)

    @staticmethod
    def _table(schema_editor, table):
        """(columns, constraint/index names) of `table`, lower-cased; None if the table is missing."""
        conn = schema_editor.connection
        with conn.cursor() as cursor:
            if table.lower() not in {t.lower() for t in conn.introspection.table_names(cursor)}:
                return None
            columns = {c.name.lower() for c in conn.introspection.get_table_description(cursor, table)}
            names = {n.lower() for n in conn.introspection.get_constraints(cursor, table)}
        return columns, names

    def _applied(self, app_label, schema_editor, state):
        """Whether the database already reflects self.inner having run (checked against the post-operation state)."""
        op = self.inner
        if isinstance(op, migrations.CreateModel):
            model = state.apps.get_model(app_label, op.name)
            return self._table(schema_editor, model._meta.db_table) is not None
        model = state.apps.get_model(app_label, op.model_name)
        found = self._table(schema_editor, model._meta.db_table)
        columns, names = found or (set(), set())
        if isinstance(op, migrations.RenameField):
            return model._meta.get_field(op.new_name).column.lower() in columns
        if isinstance(op, migrations.AddField):
            return model._meta.get_field(op.name).column.lower() in columns
        if isinstance(op, migrations.RemoveField):
            return model._meta.get_field(op.name).column.lower() not in columns
        if isinstance(op, migrations.AddIndex):
            return op.index.name.lower() in names
        if isinstance(op, migrations.AddConstraint):
            return op.constraint.name.lower() in names
        raise TypeError(f"IfNeeded doesn't support {type(op).__name__}")

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        # RemoveField's model no longer has the field in to_state, so check it against from_state's table instead.
        check_state = from_state if isinstance(self.inner, migrations.RemoveField) else to_state
        if self._applied(app_label, schema_editor, check_state):
            return
        if not isinstance(self.inner, migrations.AddField) or not self.inner.field.remote_field:
            self.inner.database_forwards(app_label, schema_editor, from_state, to_state)
            return
        # TiDB rejects Django's MySQL "ADD COLUMN x ..., ADD CONSTRAINT ...
        # FOREIGN KEY (x)" in one ALTER (1072 "Key column 'x' doesn't exist"),
        # so add the column first and the FK as its own ALTER right after.
        schema_editor.sql_create_column_inline_fk = None
        queued = len(schema_editor.deferred_sql)
        try:
            self.inner.database_forwards(app_label, schema_editor, from_state, to_state)
        finally:
            del schema_editor.sql_create_column_inline_fk
        fk_sql = schema_editor.deferred_sql[queued:]
        del schema_editor.deferred_sql[queued:]
        for sql in fk_sql:
            schema_editor.execute(sql)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        check_state = to_state if isinstance(self.inner, migrations.RemoveField) else from_state
        if self._applied(app_label, schema_editor, check_state):
            self.inner.database_backwards(app_label, schema_editor, from_state, to_state)

    def describe(self):
        return f"{self.inner.describe()} (if not already applied)"


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0034_reschedule_penalty_supplier_penalty'),
    ]

    operations = [
        IfNeeded(migrations.AddField(
            model_name='journalvoucher',
            name='source_reschedule_ticket',
            field=models.ForeignKey(blank=True, db_column='source_reschedule_ticket_id', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='vouchers', to='accounting.rescheduleairlineticket'),
        )),
        IfNeeded(migrations.AddIndex(
            model_name='journalvoucher',
            index=models.Index(fields=['source_reschedule_ticket'], name='journal_voucher_rtid_idx'),
        )),
        IfNeeded(migrations.AddField(
            model_name='ticketline',
            name='is_reschedule_eligible',
            field=models.BooleanField(default=True),
        )),
        IfNeeded(migrations.AddField(
            model_name='rescheduleairlineticketline',
            name='based_on_reschedule_line',
            field=models.ForeignKey(blank=True, db_column='based_on_reschedule_line_id', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='chained_reschedule_lines', to='accounting.rescheduleairlineticketline'),
        )),
        IfNeeded(migrations.AddField(
            model_name='rescheduleairlineticketline',
            name='is_reschedule_eligible',
            field=models.BooleanField(default=True),
        )),
        IfNeeded(migrations.AddField(
            model_name='rescheduleairlineticketline',
            name='parent_pnr',
            field=models.CharField(blank=True, max_length=30, null=True),
        )),
    ]
