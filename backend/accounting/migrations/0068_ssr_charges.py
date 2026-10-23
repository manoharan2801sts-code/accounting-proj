from django.db import migrations, models


class SafeAddField(migrations.AddField):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        try:
            super().database_forwards(app_label, schema_editor, from_state, to_state)
        except Exception as e:
            err = str(e).lower()
            if "duplicate column" in err or "already exists" in err:
                return
            raise


class Migration(migrations.Migration):
    """Per SSR type charges (Amt, Supplier / Customer SSR Markup + SSR Service Fee) on SSR Updation lines."""

    dependencies = [("accounting", "0067_fop_master_history")]

    operations = [
        SafeAddField(
            model_name="ssrairlineticketline", name="ssr_charges",
            field=models.TextField(blank=True, null=True),
        ),
    ]

