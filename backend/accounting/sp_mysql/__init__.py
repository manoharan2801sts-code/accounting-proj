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
import datetime
import decimal

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


def exec_sp(proc_name, params=None):
    params = dict(params or {})
    action = str(params.get("Action") or "").upper()
    handler = HANDLERS.get((proc_name.lower(), action))
    if handler is None:
        raise NotImplementedError(f"{proc_name} @Action='{action}' has no MySQL implementation")
    return handler(params) or []


# Register every procedure's handlers.
from . import ledger_masters, setup_masters, tickets_vouchers, reschedule_cancellation  # noqa: E402,F401
