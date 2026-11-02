import re
import xml.etree.ElementTree as ET
from pathlib import Path

from django.conf import settings
from django.db import migrations

# Several sectors on one passenger line: "/" between them instead of "," in
# Sector, Airline Code / Name / Category, Flight No, Cabin, Class and Fare Type
# (models.SEGMENT_SEP); Travel Date keeps "," (a date has "/" in it). Values
# that held a "/" themselves now use "-": Fare Type "SME Corporate/Corp Connect
# Fare" -> "SME Corporate-Corp Connect Fare", airline names "Air Central / ANA"
# -> "Air Central - ANA". Every saved ticket / reschedule / cancellation / SSR
# line and staging row is converted; the airline name is rebuilt from the
# airline codes (a name may hold a comma, e.g. "Shandong Airlines Co., Ltd.").

OLD_FARE, NEW_FARE = "SME Corporate/Corp Connect Fare", "SME Corporate-Corp Connect Fare"
SEGMENT_FIELDS = ("sector", "airline_code", "airline_category", "flight_no", "cabin", "travel_class", "fare_type")
LINE_TABLES = ("AL_TicketLines", "Rescheduled_Al_TicketLines", "Cancellation_Al_TicketLines", "Ticket_Import_Staging")


def _airlines():
    path = Path(settings.BASE_DIR).parent / "assets" / "data" / "Airlinenames.xml"
    out = {}
    for rec in ET.parse(path).getroot().iter("AIRLINEDET"):
        code = (rec.findtext("_CODE") or "").strip().upper().rstrip("*")
        name = (rec.findtext("_NAME") or "").strip()
        if code and name and code not in out:
            out[code] = re.sub(r"\s*/\s*", " - ", name)
    return out


def _columns(cursor, table):
    cursor.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = %s", [table])
    return {r[0] for r in cursor.fetchall()}


def _key(cursor, table):
    cursor.execute("""SELECT col.name FROM sys.indexes i
                      JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
                      JOIN sys.columns col ON col.object_id = ic.object_id AND col.column_id = ic.column_id
                      WHERE i.is_primary_key = 1 AND i.object_id = OBJECT_ID(%s)""", [f"dbo.{table}"])
    return cursor.fetchone()[0]   # id - staging_id on Ticket_Import_Staging


def forwards(apps, schema_editor):
    airlines = _airlines()
    with schema_editor.connection.cursor() as c:
        c.execute("UPDATE dbo.AirlineDropdownValues SET name = %s, updated_at = SYSUTCDATETIME() "
                  "WHERE list_key = 'fareTypeOptions' AND name = %s", [NEW_FARE, OLD_FARE])
        c.execute("UPDATE dbo.SupplierCommissionRules SET fare_type = %s WHERE fare_type = %s", [NEW_FARE, OLD_FARE])
        for table in LINE_TABLES + ("SSR_AL_TicketLines",):
            cols = _columns(c, table)
            fields = [f for f in SEGMENT_FIELDS + ("line_airline_category",) if f in cols]
            with_name = "airline_name" in cols and "airline_code" in cols
            key = _key(c, table)
            c.execute(f"SELECT {key}, {', '.join(fields + (['airline_name'] if with_name else []))} FROM dbo.[{table}]")
            for row in c.fetchall():
                rid, values = row[0], dict(zip(fields + (["airline_name"] if with_name else []), row[1:]))
                new = {}
                for f in fields:
                    v = values[f]
                    if v and f == "fare_type":
                        v = v.replace(OLD_FARE, NEW_FARE)
                    if v and "," in v:
                        v = "/".join(p.strip() for p in v.split(","))
                    if v != values[f]:
                        new[f] = v
                if with_name and values["airline_name"]:
                    codes = [x.strip().upper() for x in (new.get("airline_code") or values["airline_code"] or "").split("/") if x.strip()]
                    if codes and all(x in airlines for x in codes):
                        name = "/".join(airlines[x] for x in codes)
                    else:   # a code not in the list - keep the name, only the separator / " / " changes
                        name = re.sub(r"\s*/\s*", " - ", values["airline_name"]).replace(",", "/")
                    if name != values["airline_name"]:
                        new["airline_name"] = name
                if new:
                    c.execute(f"UPDATE dbo.[{table}] SET {', '.join(f'{k} = %s' for k in new)} WHERE {key} = %s",
                              list(new.values()) + [rid])
        for table in ("AL_Tickets", "Rescheduled_Al_Ticket", "Cancellation_AL_Tickets"):
            c.execute(f"UPDATE dbo.[{table}] SET airline_category = REPLACE(airline_category, ',', '/') "
                      f"WHERE airline_category LIKE '%,%'")


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0096_airline_category_per_sector"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
