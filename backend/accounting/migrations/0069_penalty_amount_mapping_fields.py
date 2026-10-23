from django.db import migrations


def update_mapping_fields(apps, schema_editor):
    try:
        MasterMapping = apps.get_model("accounting", "MasterMapping")
        MasterMappingHistory = apps.get_model("accounting", "MasterMappingHistory")
    except LookupError:
        return

    for Model in (MasterMapping, MasterMappingHistory):
        # 1. Update 'Supplier Reschedule Penalty A/c' -> 'Supplier Penalty Amount A/c'
        try:
            Model.objects.filter(field_name="Supplier Reschedule Penalty A/c").update(field_name="Supplier Penalty Amount A/c")
        except Exception:
            pass

        # 2. Deduplicate / Update 'Supplier Cancellation Penalty A/c'
        try:
            existing_targets = set(
                Model.objects.filter(field_name="Supplier Penalty Amount A/c").values_list("company_id", "product_type")
            )
            for obj in Model.objects.filter(field_name="Supplier Cancellation Penalty A/c"):
                if (obj.company_id, obj.product_type) in existing_targets:
                    obj.delete()
                else:
                    obj.field_name = "Supplier Penalty Amount A/c"
                    obj.save(update_fields=["field_name"])
        except Exception:
            pass

        # 3. Update 'Consolidator Reschedule Penalty A/c' -> 'Consolidator Penalty Amount A/c'
        try:
            Model.objects.filter(field_name="Consolidator Reschedule Penalty A/c").update(field_name="Consolidator Penalty Amount A/c")
        except Exception:
            pass


def reverse_mapping_fields(apps, schema_editor):
    try:
        MasterMapping = apps.get_model("accounting", "MasterMapping")
        MasterMappingHistory = apps.get_model("accounting", "MasterMappingHistory")
    except LookupError:
        return

    for Model in (MasterMapping, MasterMappingHistory):
        try:
            Model.objects.filter(field_name="Supplier Penalty Amount A/c").update(field_name="Supplier Reschedule Penalty A/c")
            Model.objects.filter(field_name="Consolidator Penalty Amount A/c").update(field_name="Consolidator Reschedule Penalty A/c")
        except Exception:
            pass


class Migration(migrations.Migration):
    dependencies = [("accounting", "0068_ssr_charges")]

    operations = [
        migrations.RunPython(update_mapping_fields, reverse_mapping_fields),
    ]
