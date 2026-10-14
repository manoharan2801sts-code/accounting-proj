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
        conn = schema_editor.connection
        with conn.cursor() as cursor:
            if table.lower() not in {t.lower() for t in conn.introspection.table_names(cursor)}:
                return None
            columns = {c.name.lower() for c in conn.introspection.get_table_description(cursor, table)}
            names = {n.lower() for n in conn.introspection.get_constraints(cursor, table)}
        return columns, names

    def _applied(self, app_label, schema_editor, state):
        op = self.inner
        model = state.apps.get_model(app_label, op.model_name)
        found = self._table(schema_editor, model._meta.db_table)
        columns, names = found or (set(), set())
        if isinstance(op, migrations.AddField):
            return model._meta.get_field(op.name).column.lower() in columns
        raise TypeError(f"IfNeeded doesn't support {type(op).__name__}")

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if not self._applied(app_label, schema_editor, to_state):
            self.inner.database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if self._applied(app_label, schema_editor, from_state):
            self.inner.database_backwards(app_label, schema_editor, from_state, to_state)

    def describe(self):
        return f"{self.inner.describe()} (if not already applied)"


class Migration(migrations.Migration):
    """SSR Ticket Number per SSR type on SSR Updation lines."""

    dependencies = [("accounting", "0048_ssr_payment_gateway_ref")]

    operations = [
        IfNeeded(migrations.AddField(
            model_name="ssrairlineticketline", name="ssr_ticket_numbers",
            field=models.TextField(blank=True, null=True),
        )),
    ]
