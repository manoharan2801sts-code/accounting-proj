from django.db import migrations

# New Fare Type list (AirlineDropdownValues, list_key fareTypeOptions) -
# replaces the old rows. Same names as before (what tickets store), new codes.
FARE_TYPES = [
    ("NF", "Normal Fare"),
    ("CF", "Corporate Fare"),
    ("RF", "Retail Fare"),
    ("ECF", "ECoupon Fare"),
    ("SF", "Special Fare"),
    ("SMEF", "SME Fare"),
    ("FF", "Flexi Fare"),
    ("MF", "Marine Fare"),
    ("DF", "Defence Fare"),
    ("RTF", "Roundtrip Special Fare"),
    ("SCCF", "SME Corporate/Corp Connect Fare"),
    ("SMERF", "SME Retail Fare"),
    ("LF", "Labour Fare"),
    ("CFX", "Corporate Flexi"),
    ("STF", "Student Fare"),
    ("DS", "Double Seat"),
    ("SCF", "Senior Citizen Fare"),
]


def replace_fare_types(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DELETE FROM dbo.AirlineDropdownValues WHERE list_key = 'fareTypeOptions'")
        for i, (code, name) in enumerate(FARE_TYPES, 1):
            cursor.execute(
                "INSERT INTO dbo.AirlineDropdownValues (list_key, code, name, display_label, sort_order, is_default, is_active, created_at, updated_at) "
                "VALUES ('fareTypeOptions', %s, %s, NULL, %s, 0, 1, SYSUTCDATETIME(), SYSUTCDATETIME())",
                [code, name, i * 10],
            )


class Migration(migrations.Migration):
    dependencies = [("accounting", "0076_fop_codes")]

    operations = [migrations.RunPython(replace_fare_types, migrations.RunPython.noop)]
