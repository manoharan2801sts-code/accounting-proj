# Evening 30.9.26 build (its 0022 + 0023): the reschedule line's old
# supplier_penalty becomes reschedule_penalty, and a new supplier_penalty
# (Base Fare & Tax card) is added. Guarded like 0032/0033 so a retried
# deploy on TiDB (no transactional DDL) doesn't fail.

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
        if not self._applied(app_label, schema_editor, check_state):
            self.inner.database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        check_state = to_state if isinstance(self.inner, migrations.RemoveField) else from_state
        if self._applied(app_label, schema_editor, check_state):
            self.inner.database_backwards(app_label, schema_editor, from_state, to_state)

    def describe(self):
        return f"{self.inner.describe()} (if not already applied)"


class Migration(migrations.Migration):

    dependencies = [
        ('accounting', '0033_reschedule_airline_tickets_vouchertype_flags'),
    ]

    operations = [
        IfNeeded(migrations.RenameField(
            model_name='rescheduleairlineticketline',
            old_name='supplier_penalty',
            new_name='reschedule_penalty',
        )),
        IfNeeded(migrations.AddField(
            model_name='rescheduleairlineticketline',
            name='supplier_penalty',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        )),
    ]
