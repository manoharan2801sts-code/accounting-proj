from django.db import migrations

# FOP short codes (AirlineDropdownValues): Cash = 1, Own Card = 2,
# Client Card = 3 - on the passenger FOP list and FOP Master's Card Types.
# Names (what transactions store) and order are unchanged.
FOP_CODES = {"Cash": "1", "Own Card": "2", "Client Card": "3"}
OLD_CODES = {"Cash": "CASH", "Own Card": "OC", "Client Card": "CC"}


def set_codes(codes):
    def run(apps, schema_editor):
        with schema_editor.connection.cursor() as cursor:
            for name, code in codes.items():
                cursor.execute(
                    "UPDATE dbo.AirlineDropdownValues SET code = %s, updated_at = SYSUTCDATETIME() "
                    "WHERE list_key IN ('fopOptions', 'cardTypes') AND name = %s", [code, name],
                )
    return run


class Migration(migrations.Migration):
    dependencies = [("accounting", "0075_booking_types_update")]

    operations = [migrations.RunPython(set_codes(FOP_CODES), set_codes(OLD_CODES))]
