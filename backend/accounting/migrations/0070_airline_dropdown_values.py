from django.db import migrations, models


def _check_table_exists(schema_editor, table_name):
    with schema_editor.connection.cursor() as cur:
        if schema_editor.connection.vendor == "microsoft":
            cur.execute("SELECT 1 FROM sys.tables WHERE name = %s", [table_name])
        else:
            cur.execute("SHOW TABLES LIKE %s", [table_name.lower()])
            if not cur.fetchone():
                cur.execute("SHOW TABLES LIKE %s", [table_name])
        return bool(cur.fetchone())


class SafeCreateModel(migrations.CreateModel):
    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        table_name = to_state.apps.get_model(app_label, self.name)._meta.db_table
        if _check_table_exists(schema_editor, table_name):
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)


SEED_ROWS = [
    ("bookingModes", "MAN", "Manual", None, 10, 1),
    ("bookingModes", "AUTO", "Auto Push", None, 20, 0),
    ("bookingTypes", "TD", "Travel Desk", None, 10, 0),
    ("bookingTypes", "IND", "Indesk", None, 20, 0),
    ("bookingTypes", "AGT", "Agent", None, 30, 0),
    ("bookingTypes", "RPA", "Retrieve PNR Accounting", None, 40, 0),
    ("bookingTypes", "MAN", "Manual Booking", None, 50, 0),
    ("bookingTypes", "MOB", "Mobile Booking", None, 60, 0),
    ("bookingTypes", "TCO", "Travel Co-Ordinator", None, 70, 0),
    ("bookingTypes", "SSR", "SSR Updation", None, 80, 0),
    ("bookingStatuses", "CON", "Confirmed", None, 10, 0),
    ("bookingStatuses", "RES", "Re-Scheduled", None, 20, 0),
    ("bookingStatuses", "CAN", "Normal Cancelled", None, 30, 0),
    ("travelTypes", "DOM", "Domestic", None, 10, 0),
    ("travelTypes", "INT", "International", None, 20, 0),
    ("custDiscountOn", "BAS", "Basic", None, 10, 0),
    ("custDiscountOn", "BYQ", "Basic + YQ", None, 20, 0),
    ("custDiscountOn", "BYR", "Basic + YR", None, 30, 0),
    ("custDiscountOn", "TOT", "Total Fare", None, 40, 0),
    ("suppCommOn", "BAS", "Basic", None, 10, 0),
    ("suppCommOn", "BYQ", "Basic + YQ", None, 20, 0),
    ("suppCommOn", "BYR", "Basic + YR", None, 30, 0),
    ("paxTypes", "ADT", "Adult", None, 10, 0),
    ("paxTypes", "CHD", "Child", None, 20, 0),
    ("paxTypes", "INF", "Infant", None, 30, 0),
    ("paymentModes", "TOP", "Top-up", None, 10, 0),
    ("paymentModes", "PG", "Payment Gateway", None, 20, 0),
    ("airlineCategories", "LCC", "LCC", None, 10, 0),
    ("airlineCategories", "FSC", "FSC", None, 20, 0),
    ("airlineCategories", "OSC", "OSC", None, 30, 0),
    ("fopOptions", "OC", "Own Card", None, 10, 0),
    ("fopOptions", "CC", "Client Card", None, 20, 0),
    ("fopOptions", "CASH", "Cash", None, 30, 0),
    ("cardTypes", "OC", "Own Card", None, 10, 0),
    ("cardTypes", "CC", "Client Card", None, 20, 0),
    ("cabinOptions", "Y", "Economy", None, 10, 0),
    ("cabinOptions", "W", "Premium Economy", None, 20, 0),
    ("cabinOptions", "C", "Business Class", None, 30, 0),
    ("cabinOptions", "F", "First Class", None, 40, 0),
    ("fareTypeOptions", "NRM", "Normal Fare", None, 10, 0),
    ("fareTypeOptions", "CRP", "Corporate Fare", None, 20, 0),
    ("fareTypeOptions", "RTL", "Retail Fare", None, 30, 0),
    ("fareTypeOptions", "ECP", "ECoupon Fare", None, 40, 0),
    ("fareTypeOptions", "SPL", "Special Fare", None, 50, 0),
    ("fareTypeOptions", "SME", "SME Fare", None, 60, 0),
    ("fareTypeOptions", "FLX", "Flexi Fare", None, 70, 0),
    ("fareTypeOptions", "MRN", "Marine Fare", None, 80, 0),
    ("fareTypeOptions", "DEF", "Defence Fare", None, 90, 0),
    ("fareTypeOptions", "RTS", "Roundtrip Special Fare", None, 100, 0),
    ("fareTypeOptions", "SMC", "SME Corporate/Corp Connect Fare", None, 110, 0),
    ("fareTypeOptions", "SMR", "SME Retail Fare", None, 120, 0),
    ("fareTypeOptions", "LAB", "Labour Fare", None, 130, 0),
    ("fareTypeOptions", "CFX", "Corporate Flexi", None, 140, 0),
    ("fareTypeOptions", "STU", "Student Fare", None, 150, 0),
    ("fareTypeOptions", "DBS", "Double Seat", None, 160, 0),
    ("fareTypeOptions", "SRC", "Senior Citizen Fare", None, 170, 0),
    ("dsrStatuses", "CON", "Confirmed", None, 10, 0),
    ("dsrStatuses", "RES", "Re-Scheduled", "Reschedule", 20, 0),
    ("dsrStatuses", "CAN", "Normal Cancelled", "Cancellation", 30, 0),
    ("dsrStatuses", "SSR", "SSR Updated", "SSR Updation", 40, 0),
    ("ssrTypes", "BAG", "Baggage", None, 10, 0),
    ("ssrTypes", "MEAL", "Meal", None, 20, 0),
    ("ssrTypes", "SEAT", "Seat", None, 30, 0),
    ("ssrTypes", "OTH", "Other SSR", None, 40, 0),
]


def seed_airline_dropdowns(apps, schema_editor):
    try:
        AirlineDropdownValue = apps.get_model("accounting", "AirlineDropdownValue")
        for list_key, code, name, display_label, sort_order, is_default in SEED_ROWS:
            AirlineDropdownValue.objects.get_or_create(
                list_key=list_key,
                code=code,
                defaults={
                    "name": name,
                    "display_label": display_label,
                    "sort_order": sort_order,
                    "is_default": bool(is_default),
                    "is_active": True,
                },
            )
    except Exception as e:
        print(f"[WARN] AirlineDropdownValue seeding skipped: {e}")


class Migration(migrations.Migration):
    dependencies = [("accounting", "0069_penalty_amount_mapping_fields")]

    operations = [
        SafeCreateModel(
            name="AirlineDropdownValue",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("list_key", models.CharField(max_length=50)),
                ("code", models.CharField(max_length=10)),
                ("name", models.CharField(max_length=100)),
                ("display_label", models.CharField(blank=True, max_length=100, null=True)),
                ("sort_order", models.IntegerField(default=0)),
                ("is_default", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "AirlineDropdownValues",
                "constraints": [
                    models.UniqueConstraint(fields=("list_key", "code"), name="uq_airline_dd_code"),
                    models.UniqueConstraint(fields=("list_key", "name"), name="uq_airline_dd_name"),
                ],
            },
        ),
        migrations.RunPython(seed_airline_dropdowns, migrations.RunPython.noop),
    ]
