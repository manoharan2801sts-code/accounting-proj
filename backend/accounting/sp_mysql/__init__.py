"""
MySQL/TiDB stand-in for the SQL Server stored procedures in
backend/sp_reference/StoredProcedures.sql.

The build routes every DB call through sp_client.exec_sp(proc, params),
which runs `EXEC dbo.sp_X @Action=..., ...` on SQL Server. Live runs on
TiDB, which has no stored procedures, so exec_sp() here dispatches to a
Python handler per (procedure, @Action) instead. Each handler does what
that @Action's T-SQL does - same validation, same writes, same result
set (column names, row order, Python value types as pyodbc would return
them) - so sp_client.py and views.py run unchanged.

Handlers live in the per-procedure modules below and register with @sp.
"""
import contextvars
import copy
import datetime
import decimal

from django.core.signals import request_finished, request_started
from django.db import connection

HANDLERS = {}


def sp(proc_name, *actions):
    """Registers a handler for one or more @Action values of a procedure."""
    def register(fn):
        for action in actions:
            HANDLERS[(proc_name.lower(), action.upper())] = fn
        return fn
    return register


class SPThrow(Exception):
    """A T-SQL THROW / RAISERROR that the procedure doesn't catch itself."""


def error_row(message):
    """The `SELECT 'Error' AS status, <msg> AS error` result of a CATCH block."""
    return [{"status": "Error", "error": message}]


def query(sql, params=None):
    """Runs SQL and returns its rows as dicts (column name -> value)."""
    memo = _query_memo.get()
    if memo is not None:
        memo_key = (sql, tuple(repr(p) for p in (params or [])))
        if memo_key not in memo:
            memo[memo_key] = _run_query(sql, params)
        return copy.deepcopy(memo[memo_key])
    return _run_query(sql, params)


def _run_query(sql, params):
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        if cursor.description is None:
            return []
        cols = [c[0] for c in cursor.description]
        return [dict(zip(cols, r)) for r in cursor.fetchall()]


def query_one(sql, params=None):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql, params=None):
    """Runs a write; returns (rowcount, lastrowid)."""
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return cursor.rowcount, cursor.lastrowid


def to_bit(v):
    """SQL Server BIT -> bool (pyodbc); MySQL tinyint(1) comes back as int."""
    return None if v is None else bool(v)


def to_bool_param(v):
    """A BIT parameter as SQL Server would coerce it (None stays NULL)."""
    if v is None:
        return None
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "on")
    return bool(v)


def to_decimal(v):
    return None if v is None else decimal.Decimal(str(v))


def to_date(v):
    """A DATE parameter: accepts date/datetime/'YYYY-MM-DD...' strings, like SQL Server's implicit conversion."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    return datetime.date.fromisoformat(str(v)[:10])


def bits(row, *names):
    """Converts the named BIT columns of a result row to bool in place."""
    for n in names:
        if n in row:
            row[n] = to_bit(row[n])
    return row


# Per-request memo for lookups that a single report repeats once per ticket
# or line (PG Master snapshot, FOP card, Master Mapping, Company, customer/
# supplier ledger by name). Each repeat is a TiDB round trip (~0.17s on
# live). Scoped to one HTTP request, and dropped on any other @Action, so
# a save inside the request can never be answered from a stale entry.
CACHED_READS = {
    ("dbo.sp_pgmaster", "EFFECTIVE_SNAPSHOT"),
    ("dbo.sp_fopmaster", "GET_BY_CARD_NUMBER"),
    ("dbo.sp_mastermapping", "LIST"),
    ("dbo.sp_companymaster", "LIST"),
    ("dbo.sp_ledger", "GET_BY_NAME"),
}
WRITE_ACTIONS = {"SAVE", "SAVE_ROW", "UPDATE", "DELETE"}
_request_cache = contextvars.ContextVar("sp_request_cache", default=None)
# While one of CACHED_READS runs: identical SELECTs inside it (e.g. the same
# gateway's id/history row for every ticket) also hit the DB once per request.
_query_memo = contextvars.ContextVar("sp_query_memo", default=None)


def _start_request_cache(**kwargs):
    _request_cache.set({"calls": {}, "queries": {}})


def _end_request_cache(**kwargs):
    _request_cache.set(None)


request_started.connect(_start_request_cache, dispatch_uid="sp_mysql_cache_start")
request_finished.connect(_end_request_cache, dispatch_uid="sp_mysql_cache_end")


def exec_sp(proc_name, params=None):
    params = dict(params or {})
    action = str(params.get("Action") or "").upper()
    key = (proc_name.lower(), action)
    handler = HANDLERS.get(key)
    if handler is None:
        raise NotImplementedError(f"{proc_name} @Action='{action}' has no MySQL implementation")
    cache = _request_cache.get()
    if cache is None:
        return handler(params) or []
    if key not in CACHED_READS:
        if action in WRITE_ACTIONS:
            cache["calls"].clear()
            cache["queries"].clear()
        return handler(params) or []
    memo_key = (key, tuple(sorted((k, repr(v)) for k, v in params.items())))
    if memo_key not in cache["calls"]:
        token = _query_memo.set(cache["queries"])
        try:
            cache["calls"][memo_key] = handler(params) or []
        finally:
            _query_memo.reset(token)
    return copy.deepcopy(cache["calls"][memo_key])


def ticket_chain_lock_message(company_id, ticket_id=None, reschedule_id=None):
    items = []
    if ticket_id is not None:
        rows = query(
            "SELECT 'Reschedule' AS kind, invoice_number FROM Rescheduled_Al_Ticket WHERE company_id = %s AND original_ticket_id = %s "
            "UNION ALL "
            "SELECT 'Cancellation' AS kind, invoice_number FROM Cancellation_AL_Tickets WHERE company_id = %s AND original_ticket_id = %s "
            "UNION ALL "
            "SELECT 'SSR Updation' AS kind, invoice_number FROM SSR_AL_Tickets WHERE company_id = %s AND original_ticket_id = %s",
            [company_id, ticket_id, company_id, ticket_id, company_id, ticket_id]
        )
        for r in rows:
            items.append(f"{r['kind']} {r['invoice_number']}")
    if reschedule_id is not None:
        rows = query(
            "SELECT DISTINCT 'Reschedule' AS kind, r2.invoice_number "
            "FROM Rescheduled_Al_TicketLines l2 "
            "JOIN Rescheduled_Al_Ticket r2 ON r2.id = l2.reschedule_ticket_id "
            "WHERE r2.company_id = %s AND r2.id <> %s "
            "  AND l2.based_on_reschedule_line_id IN (SELECT id FROM Rescheduled_Al_TicketLines WHERE reschedule_ticket_id = %s) "
            "UNION ALL "
            "SELECT 'SSR Updation' AS kind, s.invoice_number FROM SSR_AL_Tickets s "
            "WHERE s.company_id = %s AND s.source_reschedule_ticket_id = %s "
            "UNION ALL "
            "SELECT 'Cancellation' AS kind, c.invoice_number FROM Cancellation_AL_Tickets c "
            "WHERE c.company_id = %s AND c.original_ticket_id = (SELECT original_ticket_id FROM Rescheduled_Al_Ticket WHERE id = %s)",
            [company_id, reschedule_id, reschedule_id, company_id, reschedule_id, company_id, reschedule_id]
        )
        for r in rows:
            items.append(f"{r['kind']} {r['invoice_number']}")
    if not items:
        return None
    return "Locked by: " + ", ".join(items)


# Register every procedure's handlers.
from . import ledger_masters, setup_masters, tickets_vouchers, reschedule_cancellation, user_management, ssr, misc, dropdown_audit  # noqa: E402,F401

