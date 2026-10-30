"""
Automated Database Scheduler - airline tickets from the Agent's database
-----------------------------------------------------------------
The Agent puts tickets in AGENT_DB_NAME.dbo.AGENT_DB_TABLE (.env, default
Airline_Agent.dbo.Agent_ticket_data): one row per passenger, the columns are
the Auto Push API parameters (ticket_import.py), the invoice-level ones
repeated on every passenger row of the invoice. That table holds only the
Agent's data - the scheduler only READS it.

Every AGENT_DB_SCHEDULER_MINUTES (`manage.py run_agent_db_scheduler`,
started by start.bat) one run:
  1. picks up the Agent rows not yet in our dbo.Agent_DB_Ticket_Log (same
     SQL Server, checked in SQL): every row of the same company_id +
     booking_status + booking_reference is one invoice, picked up together,
     and logged as 'Processing';
  2. sends them through the SAME pipeline as an API push -
     ticket_import.receive_documents() with source_system AGENT_DB: every
     value checked, problems in the Error Log ("Automated Database
     Scheduler" tab of /error_log/), clean invoices saved through the Ticket
     Entry / SSR Updation views (Booking Mode "Auto Push", Booking /
     Reschedule / Cancellation / SSR Updation by booking_status C / R / X / SSR);
  3. writes each row's result in dbo.Agent_DB_Ticket_Log: process_status
     Imported / Pending / Rejected / Duplicate / Error, invoice_number,
     voucher_no, import_doc_key, error_message;
  4. logs the run in dbo.Agent_DB_Scheduler_Log - only when it fetched rows.
Rows left 'Pending' (e.g. a Reschedule waiting for its booking) are saved by
the Ticket Import Scheduler (run_ticket_import); every run here copies their
final status into the log.

Create the Agent database and table once: `manage.py setup_agent_db`.
"""
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal

from django.conf import settings
from django.db import connections
from django.http import HttpResponseNotAllowed, JsonResponse

from . import sp_client, ticket_import

logger = logging.getLogger(__name__)

SOURCE_SYSTEM = "AGENT_DB"   # Ticket_Import_Staging / Error_Log source_system of these invoices
ALIAS = "agent_db"           # settings.DATABASES alias of AGENT_DB_NAME
STUCK_MINUTES = 30           # 'Processing' this long = a run that died; the rows are picked up again
SETTLE_SECONDS = 60          # rows younger than this wait for the next run (the Agent may still be inserting the invoice)
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")

# ---------------------------------------------------------------------------
# The Agent table: the API parameters, in the API's order.
# ---------------------------------------------------------------------------
HEADER_COLUMNS = [k for k in ticket_import.HEADER_PARAMS if k != "passengers"]
# No original_ticket_no: a Reschedule's old ticket is found from its Parent PNR + passenger name.
PAX_COLUMNS = [k for k in ticket_import.PAX_TEXT_PARAMS if k != "original_ticket_no"]
DROPPED_COLUMNS = ["original_ticket_no"]
AMOUNT_COLUMNS = list(ticket_import.AMOUNT_PARAMS)
TEXT_SIZES = {   # NVARCHAR sizes - roomy on purpose: a value too long is reported by the checks, not refused by SQL
    "user_name": 200, "sector": 400, "airline_code": 400, "travel_date": 400, "flight_no": 400,
    "cabin": 400, "class": 400, "fare_type": 400,
}


def _checked(label, name):
    if not NAME_RE.match(name or ""):
        raise ValueError(f"{label} '{name}' must be letters, numbers and _ only.")
    return name


def table_names():
    """(database, table) from .env - checked, since they are put into the SQL as names."""
    return _checked("AGENT_DB_NAME", settings.AGENT_DB_NAME), _checked("AGENT_DB_TABLE", settings.AGENT_DB_TABLE)


def create_sql(db, table):
    """CREATE DATABASE / TABLE script for the Agent's database (manage.py setup_agent_db, AgentDatabase.sql)."""
    cols = [f"    agent_row_id        BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_{table} PRIMARY KEY,",
            f"    created_at          DATETIME2      NOT NULL CONSTRAINT df_{table}_created DEFAULT SYSUTCDATETIME(),",
            "    -- API parameters - invoice (repeated on every passenger row of the invoice)",
            "    company_id          INT            NOT NULL,"]
    cols += [f"    {'[' + c + ']':<20} NVARCHAR({TEXT_SIZES.get(c, 100)})  NULL," for c in HEADER_COLUMNS]
    cols.append("    -- API parameters - passenger")
    cols += [f"    {'[' + c + ']':<20} NVARCHAR({TEXT_SIZES.get(c, 100)})  NULL," for c in PAX_COLUMNS]
    cols.append("    -- API parameters - amounts (NULL = \"\")")
    cols += [f"    {'[' + c + ']':<28} DECIMAL(18,2)  NULL," for c in AMOUNT_COLUMNS]
    cols[-1] = cols[-1].rstrip(",")
    # A table created before a parameter was added (e.g. the SSR Updation ones) gets the new column.
    added = [f"IF COL_LENGTH('dbo.[{table}]', '{c}') IS NULL ALTER TABLE dbo.[{table}] ADD [{c}] NVARCHAR({TEXT_SIZES.get(c, 100)}) NULL;"
             for c in HEADER_COLUMNS + PAX_COLUMNS]
    added += [f"IF COL_LENGTH('dbo.[{table}]', '{c}') IS NULL ALTER TABLE dbo.[{table}] ADD [{c}] DECIMAL(18,2) NULL;"
              for c in AMOUNT_COLUMNS]
    return f"""IF DB_ID('{db}') IS NULL
    CREATE DATABASE [{db}];
GO

USE [{db}];
GO

-- Agent airline tickets - one row per passenger, only the Agent's data.
-- Insert every passenger of one invoice in ONE transaction. What happened
-- to each row is logged in the accounting database (dbo.Agent_DB_Ticket_Log).
IF OBJECT_ID('dbo.[{table}]', 'U') IS NULL
CREATE TABLE dbo.[{table}] (
""" + "\n".join(cols) + f"""
);
GO
-- Columns added to the API after the table was created (safe to run again)
""" + "\n".join(added) + f"""
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_{table}_invoice')
    CREATE INDEX ix_{table}_invoice ON dbo.[{table}] (company_id, booking_status, booking_reference);
GO
"""


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------
def _rows(cursor):
    names = [c[0] for c in cursor.description]
    return [dict(zip(names, r)) for r in cursor.fetchall()]


def _value(v):
    """A column value as the API would send it: NULL -> "", DECIMAL -> number."""
    if v is None:
        return ""
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def _document(rows):
    first = rows[0]
    doc = {c: _value(first[c]) for c in HEADER_COLUMNS}
    doc["passengers"] = [{c: _value(r[c]) for c in PAX_COLUMNS + AMOUNT_COLUMNS} for r in rows]
    return doc


def _new_rows(db, table, invoices):
    """
    The Agent rows of up to `invoices` invoices not yet in our log, oldest
    first - all rows of an invoice together. Read only: the log lives in the
    accounting database on the same SQL Server or MySQL/TiDB server.
    """
    our_db = _checked("DB_NAME", settings.DATABASES["default"]["NAME"])
    conn = connections[ALIAS]
    with conn.cursor() as cursor:
        if conn.vendor == "microsoft":
            cursor.execute(f"""
                ;WITH waiting AS (
                    SELECT t.* FROM dbo.[{table}] t
                    WHERE NOT EXISTS (SELECT 1 FROM [{our_db}].dbo.Agent_DB_Ticket_Log l
                                      WHERE l.source_database = %s AND l.source_table = %s
                                        AND l.agent_row_id = t.agent_row_id)
                ), pick AS (
                    SELECT TOP ({int(invoices)}) company_id, ISNULL(booking_status, N'') AS bs, ISNULL(booking_reference, N'') AS br
                    FROM waiting
                    GROUP BY company_id, ISNULL(booking_status, N''), ISNULL(booking_reference, N'')
                    HAVING MAX(created_at) < DATEADD(SECOND, -{SETTLE_SECONDS}, SYSUTCDATETIME())
                    ORDER BY MIN(agent_row_id)
                )
                SELECT w.* FROM waiting w
                JOIN pick p ON p.company_id = w.company_id AND p.bs = ISNULL(w.booking_status, N'')
                           AND p.br = ISNULL(w.booking_reference, N'')
                ORDER BY w.agent_row_id;
            """, [db, table])
        else:
            cursor.execute(f"""
                WITH waiting AS (
                    SELECT t.* FROM `{table}` t
                    WHERE NOT EXISTS (SELECT 1 FROM `{our_db}`.`Agent_DB_Ticket_Log` l
                                      WHERE l.source_database = %s AND l.source_table = %s
                                        AND l.agent_row_id = t.agent_row_id)
                ), pick AS (
                    SELECT company_id, IFNULL(booking_status, '') AS bs, IFNULL(booking_reference, '') AS br
                    FROM waiting
                    GROUP BY company_id, IFNULL(booking_status, ''), IFNULL(booking_reference, '')
                    HAVING MAX(created_at) < DATE_SUB(UTC_TIMESTAMP(6), INTERVAL {SETTLE_SECONDS} SECOND)
                    ORDER BY MIN(agent_row_id)
                    LIMIT {int(invoices)}
                )
                SELECT w.* FROM waiting w
                JOIN pick p ON p.company_id = w.company_id AND p.bs = IFNULL(w.booking_status, '')
                           AND p.br = IFNULL(w.booking_reference, '')
                ORDER BY w.agent_row_id;
            """, [db, table])
        return _rows(cursor)


def _result_status(r):
    if r.get("duplicate"):
        return "Duplicate"
    status = r.get("process_status") or "Pending"
    return "Pending" if status == "Processing" else status


def _result_error(r):
    errors = r.get("errors") or []
    text = "; ".join(e.get("message") or "" for e in errors[:10])
    if len(errors) > 10:
        text += f"; ... {len(errors) - 10} more (Error Log)"
    return text or r.get("error") or None


def _refresh_waiting():
    """Logged rows still Pending / Error: copy the final import status (saved later by run_ticket_import)."""
    by_company = {}
    for r in sp_client.agent_ticket_log_waiting():
        by_company.setdefault(r["company_id"], []).append(r["import_doc_key"])
    changed = 0
    for company_id, keys in by_company.items():
        for s in sp_client.ticket_import_doc_status(company_id, doc_keys=keys, top=len(keys)):
            if s.get("process_status") in ("Imported", "Error"):
                error = None if s["process_status"] == "Imported" else (s.get("error") or "")[:2000] or None
                changed += sp_client.agent_ticket_log_refresh(s["doc_key"], s["process_status"], s.get("invoice_number"),
                                                              s.get("voucher_no"), error)
    return changed


def run_once(invoices=None):
    """
    One scheduler run. Returns {records_fetched, invoices_fetched, imported,
    pending, errors, refreshed, log_id, documents}; log_id is None when
    nothing was fetched.
    """
    db, table = table_names()
    invoices = invoices or settings.AGENT_DB_BATCH_SIZE
    started = datetime.now(timezone.utc).replace(tzinfo=None)
    summary = {"records_fetched": 0, "invoices_fetched": 0, "imported": 0, "pending": 0, "errors": 0,
               "refreshed": _refresh_waiting(), "log_id": None, "documents": []}

    rows = _new_rows(db, table, invoices)
    claimed = sp_client.agent_ticket_log_claim(db, table, [
        {"agent_row_id": r["agent_row_id"], "company_id": r["company_id"], "booking_status": r["booking_status"],
         "booking_reference": r["booking_reference"], "ticket_no": r["ticket_no"], "pax_name": r["pax_name"]}
        for r in rows
    ], STUCK_MINUTES) if rows else set()
    rows = [r for r in rows if r["agent_row_id"] in claimed]
    if not rows:
        return summary   # nothing posted - no log row

    groups = {}
    for r in rows:
        groups.setdefault((r["company_id"], r["booking_status"] or "", r["booking_reference"] or ""), []).append(r)
    summary.update(records_fetched=len(rows), invoices_fetched=len(groups))
    batch_id = f"AGENTDB-{started:%Y%m%d%H%M%S}"
    message = None
    done = set()

    def write(group, status, invoice_number=None, voucher_no=None, doc_key=None, error=None):
        sp_client.agent_ticket_log_result(db, table, [{
            "agent_row_id": x["agent_row_id"], "process_status": status, "invoice_number": invoice_number,
            "voucher_no": voucher_no, "import_doc_key": doc_key, "error_message": error,
        } for x in group])
        done.update(x["agent_row_id"] for x in group)
        summary[{"Imported": "imported", "Pending": "pending"}.get(status, "errors")] += len(group)

    try:
        by_company = {}
        for (company_id, _, _), group in groups.items():
            by_company.setdefault(company_id, []).append(group)
        for company_id, company_groups in by_company.items():
            if not sp_client.company_master_get(company_id):
                text = f"company_id {company_id} is not an existing company."
                ticket_import._push_error(text, 400, None, SOURCE_SYSTEM, batch_id, "company_id", company_id)
                for group in company_groups:
                    write(group, "Rejected", error=text)
                continue
            size = ticket_import.MAX_DOCUMENTS_PER_PUSH
            for i in range(0, len(company_groups), size):
                chunk = company_groups[i:i + size]
                results, _ = ticket_import.receive_documents(
                    company_id, SOURCE_SYSTEM, batch_id, [_document(g) for g in chunk], process_now=True)
                for group, r in zip(chunk, results):
                    status = _result_status(r)
                    write(group, status, r.get("invoice_number"), r.get("voucher_no"), r.get("doc_key"),
                          None if status == "Imported" else _result_error(r))
                    summary["documents"].append({
                        "booking_status": group[0]["booking_status"], "booking_reference": group[0]["booking_reference"],
                        "rows": len(group), "status": status, "invoice_number": r.get("invoice_number"),
                    })
    except Exception as err:  # noqa: BLE001 - rows not finished are picked up again by the next run
        logger.exception("agent db scheduler run failed")
        message = f"Run failed: {err}"
        sp_client.agent_ticket_log_release(db, table, [r["agent_row_id"] for r in rows if r["agent_row_id"] not in done])

    finished = datetime.now(timezone.utc).replace(tzinfo=None)
    message = message or (f"{summary['imported']} imported, {summary['pending']} pending, "
                          f"{summary['errors']} not saved (see the Error Log).")
    log = sp_client.agent_db_scheduler_log_add(
        started, finished, db, table, summary["records_fetched"], summary["invoices_fetched"],
        summary["imported"], summary["pending"], summary["errors"], message[:1000])
    summary["log_id"] = (log or {}).get("log_id")
    sp_client.agent_ticket_log_set_run(db, table, sorted(done), summary["log_id"])
    summary["message"] = message
    return summary


# ---------------------------------------------------------------------------
# API: GET /api/import/agent-db/scheduler-log/ (Error Log page, scheduler tab)
# ---------------------------------------------------------------------------
def scheduler_log(request):
    """GET /api/import/agent-db/scheduler-log/[?from_date=&to_date=&top=] - the scheduler runs, newest first."""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    q = request.GET
    top = min(int(q.get("top") or 200) if (q.get("top") or "").isdigit() else 200, 2000)
    rows = sp_client.agent_db_scheduler_log_list(q.get("from_date") or None, q.get("to_date") or None, top)
    return JsonResponse({
        "rows": rows,
        "settings": {"database": settings.AGENT_DB_NAME, "table": settings.AGENT_DB_TABLE,
                     "minutes": settings.AGENT_DB_SCHEDULER_MINUTES, "enabled": settings.AGENT_DB_SCHEDULER_ENABLED},
    })
