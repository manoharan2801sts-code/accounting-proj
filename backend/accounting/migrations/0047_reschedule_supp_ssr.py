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
    """Supplier SSR Markup / SSR Service Fee on Reschedule lines (same as TicketLine's)."""

    dependencies = [("accounting", "0046_companymaster_bank_details")]

    operations = [
        IfNeeded(migrations.AddField(
            model_name="rescheduleairlineticketline", name="supp_ssr_markup",
            field=models.DecimalField(decimal_places=2, default=0, db_default=0, max_digits=14),
        )),
        IfNeeded(migrations.AddField(
            model_name="rescheduleairlineticketline", name="supp_ssr_service_fee",
            field=models.DecimalField(decimal_places=2, default=0, db_default=0, max_digits=14),
        )),
    ]
