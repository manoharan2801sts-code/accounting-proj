import re

from django.db import migrations, models

# New Booking Type list (AirlineDropdownValues, list_key bookingTypes) -
# replaces the old values. "SSR Updation" stays (last) - the DSR reports label
# SSR Updation rows with it and filter on this list.
BOOKING_TYPES = [
    ("TDB", "Travel Desk Booking"),
    ("MB", "Manual Booking"),
    ("RPA", "Retrieve PNR Accounting"),
    ("RPTI", "Retrieve PNR Ticketing (I)"),
    ("RPTQ", "Retrieve PNR Ticketing (Q)"),
    ("APIB", "API Booking"),
    ("ABW", "Agent Booking (Web)"),
    ("TC", "Travel Co-ordinator"),
    ("TCBM", "Travel Co-ordinator Booking (Mobile)"),
    ("EBSBT", "Employee Booking (SBT)"),
    ("MOB", "Mobile Booking"),
    ("IB", "Indesk Booking"),
    ("SUB", "Super User Booking"),
    ("MWB", "Mobile Web Booking"),
    ("EBM", "Employee Booking (Mobile)"),
    ("VTAMB", "VTA - Mail Booking"),
]

# Saved Booking / Reschedule / Cancellation entries: old name -> new name.
RENAMES = {
    "Travel Desk": "Travel Desk Booking",
    "Indesk": "Indesk Booking",
    "Agent": "Agent Booking (Web)",
    "Travel Co-Ordinator": "Travel Co-ordinator",
}

TICKET_TABLES = ("AL_Tickets", "Rescheduled_Al_Ticket", "Cancellation_AL_Tickets")

# "Travel Co-ordinator Booking (Mobile)" is 36 characters - booking_type was
# NVARCHAR(30). Widened to 50 on the tables and on the procedures that carry it.
PROCEDURES = ("sp_Ticket", "sp_RescheduleTicket", "sp_CancellationTicket", "sp_TicketImport_Stage")
WIDEN = [
    (re.compile(r"(@BookingType\s+)NVARCHAR\s*\(\s*30\s*\)", re.I), r"\1NVARCHAR(50)"),
    (re.compile(r"(\bbooking_type\s+)NVARCHAR\s*\(\s*30\s*\)", re.I), r"\1NVARCHAR(50)"),
]


def widen_columns_and_procedures(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for table in TICKET_TABLES + ("Ticket_Import_Staging",):
            cursor.execute(f"ALTER TABLE dbo.{table} ALTER COLUMN booking_type NVARCHAR(50) NULL")
        # Each procedure is re-created from its OWN deployed definition with
        # only the booking_type length changed - nothing else in it moves.
        for proc in PROCEDURES:
            cursor.execute("SELECT OBJECT_DEFINITION(OBJECT_ID(%s))", [f"dbo.{proc}"])
            definition = cursor.fetchone()[0]
            if definition is None:
                raise RuntimeError(f"dbo.{proc} is not deployed in this database.")
            changed = definition
            for pattern, repl in WIDEN:
                changed = pattern.sub(repl, changed)
            if changed == definition:
                continue   # already 50 (or never had the 30-length declaration)
            # The stored text can start with comments - match the header by name.
            header = r"\bCREATE\s+(?:OR\s+ALTER\s+)?PROC(?:EDURE)?\s+(?=(?:\[?dbo\]?\.)?\[?" + proc + r"\b)"
            changed, n = re.subn(header, "CREATE OR ALTER PROCEDURE ", changed, count=1, flags=re.I)
            if n != 1:
                raise RuntimeError(f"Could not read the CREATE PROCEDURE header of dbo.{proc}.")
            cursor.execute(changed)   # no params -> no %-formatting, the text goes as-is


def update_booking_types(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DELETE FROM dbo.AirlineDropdownValues WHERE list_key = 'bookingTypes' AND code <> 'SSR'")
        for i, (code, name) in enumerate(BOOKING_TYPES, 1):
            cursor.execute(
                "INSERT INTO dbo.AirlineDropdownValues (list_key, code, name, display_label, sort_order, is_default, is_active, created_at, updated_at) "
                "VALUES ('bookingTypes', %s, %s, NULL, %s, 0, 1, SYSUTCDATETIME(), SYSUTCDATETIME())",
                [code, name, i * 10],
            )
        cursor.execute(
            "UPDATE dbo.AirlineDropdownValues SET sort_order = %s, updated_at = SYSUTCDATETIME() "
            "WHERE list_key = 'bookingTypes' AND code = 'SSR'", [(len(BOOKING_TYPES) + 1) * 10],
        )
        for table in TICKET_TABLES:
            for old, new in RENAMES.items():
                cursor.execute(f"UPDATE dbo.{table} SET booking_type = %s WHERE booking_type = %s", [new, old])


class Migration(migrations.Migration):
    """New Booking Type dropdown values (with codes); booking_type widened to 50 characters."""

    dependencies = [("accounting", "0074_ticket_import_staging")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(widen_columns_and_procedures, migrations.RunPython.noop)],
            state_operations=[
                migrations.AlterField(model_name="ticket", name="booking_type",
                                      field=models.CharField(blank=True, max_length=50, null=True)),
                migrations.AlterField(model_name="rescheduleairlineticket", name="booking_type",
                                      field=models.CharField(blank=True, max_length=50, null=True)),
                migrations.AlterField(model_name="cancellationairlineticket", name="booking_type",
                                      field=models.CharField(blank=True, max_length=50, null=True)),
            ],
        ),
        migrations.RunPython(update_booking_types, migrations.RunPython.noop),
    ]
