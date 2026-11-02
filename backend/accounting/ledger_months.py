"""
Year-wise ledger summary - one table per financial year (Apr - Mar),
[YY-YY-Accounting_Ledger] (e.g. [26-27-Accounting_Ledger]), created
automatically by dbo.sp_AccountingLedger. One row per company + ledger:

    Ledger_Name
    Opening_Balance   the ledger's opening balance (first year) / the previous
                      year's Overall_Total
    <Mon>_Cr, <Mon>_Dr  every posting of that month (JV, FOP Payment, PG Receipt,
                      manual Vouchers - the same postings the reports used),
                      Apr up to the last month with postings
    <Mon>_Balance     <Mon>_Dr - <Mon>_Cr
    Overall_Total     Opening_Balance + every month's Balance

Reports read balances from here (cumulative(), used by
views._ledger_balance_deltas) instead of working out every document again.

Kept current by:
  * @posts_to_ledger on every document save view - the document's month
    BEFORE the save (an edit can change its date) and AFTER it are worked
    out again; the year's Overall_Total and every later year's
    Opening_Balance / Overall_Total follow;
  * @changes_postings on the masters that change how documents post (Ledger,
    Ledger Mapping, FOP / PG Master, Company, Supplier Commission) - marks
    the company dirty, so its tables are rebuilt in full before the next
    report reads them;
  * manage.py rebuild_accounting_ledger - after data was changed outside the app.
A sync that fails marks the company dirty instead of failing the save.
"""
import functools
import json
import logging
from datetime import date, timedelta

from . import sp_client

logger = logging.getLogger(__name__)

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
FY_START = 4   # April


def _key(day):
    return (day.year, day.month)


def _next(key):
    year, month = key
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _first_day(key):
    return date(key[0], key[1], 1)


def _last_day(key):
    return _first_day(_next(key)) - timedelta(days=1)


def _fy(key):
    """Financial year of a month = the year its April falls in: (2027, 2) -> 2026."""
    return key[0] if key[1] >= FY_START else key[0] - 1


def _fy_months(fy):
    """[(2026, 4), (2026, 5) ... (2027, 3)]."""
    return [(fy, m) for m in range(FY_START, 13)] + [(fy + 1, m) for m in range(1, FY_START)]


def table_name(fy):
    """2026 -> '26-27-Accounting_Ledger'."""
    return f"{fy % 100:02d}-{(fy + 1) % 100:02d}-Accounting_Ledger"


def _table_fy(name):
    return 2000 + int(name[:2])


def _mon(key):
    return MONTHS[key[1] - 1]


def _existing():
    return {_table_fy(n) for n in sp_client.accounting_ledger_tables()}


def _ledgers(company_id):
    """{ledger_id: (name, opening balance - Debit positive)}."""
    return {l["id"]: (l["name"], float(l["balance"] or 0)) for l in sp_client.ledger_list(company_id)}


def _read(company_id, fy):
    return {r["ledger_id"]: r for r in sp_client.accounting_ledger_read_year(company_id, table_name(fy))}


def _stored_month(rows, key):
    """{ledger_id: [debit, credit]} of one month from a year table's rows - None when it has no such column."""
    if rows and f"{_mon(key)}_Cr" not in next(iter(rows.values())):
        return None
    out = {}
    for lid, r in rows.items():
        cr, dr = r.get(f"{_mon(key)}_Cr"), r.get(f"{_mon(key)}_Dr")
        if cr is not None or dr is not None:
            out[lid] = [float(dr or 0), float(cr or 0)]
    return out


def _movements(company_id, from_day, to_day):
    """{ledger_id: [debit, credit]} posted from_day..to_day (either None = open-ended)."""
    from . import views
    return views._ledger_movements(company_id, as_of_date=to_day.isoformat() if to_day else None,
                                   from_date=from_day.isoformat() if from_day else None)


def _save_year(company_id, fy, months, data, opening, names):
    """months = [(y, m) ...] Apr onward; data = {key: {ledger_id: [debit, credit]}}. Returns {ledger_id: Overall_Total}."""
    overall = dict(opening)
    rows = []
    for lid in sorted(set(opening) | {l for key in months for l in data[key]}):
        row = {"ledger_id": lid, "Ledger_Name": names.get(lid), "Opening_Balance": round(opening.get(lid, 0.0), 4)}
        total, moved = opening.get(lid, 0.0), False
        for key in months:
            debit, credit = data[key].get(lid, (0.0, 0.0))
            moved = moved or bool(debit or credit)
            row[f"{_mon(key)}_Cr"] = round(credit, 4)
            row[f"{_mon(key)}_Dr"] = round(debit, 4)
            row[f"{_mon(key)}_Balance"] = round(debit - credit, 4)
            total += debit - credit
        overall[lid] = total
        row["Overall_Total"] = round(total, 4)
        if moved or round(row["Opening_Balance"], 4) or round(total, 4):
            rows.append(row)
    sp_client.accounting_ledger_save_year(company_id, table_name(fy), [_mon(k) for k in months], rows)
    return overall


def rebuild(company_id, from_key=None, recompute=None):
    """
    Writes the company's year tables from the year of from_key (None = its
    first year) through the year of its last voucher; each year's months run
    from Apr up to its last month with postings (the last year) or Mar.
    Months in `recompute` (None = all) are worked out again from the
    documents; the others keep their stored Cr / Dr.
    """
    company_id = int(company_id)
    first, last = sp_client.accounting_ledger_date_range(company_id)
    ledgers = _ledgers(company_id)
    names = {lid: name for lid, (name, _opening) in ledgers.items()}
    existing = _existing()
    if not first:
        for fy in existing:
            sp_client.accounting_ledger_save_year(company_id, table_name(fy), [], [])
        sp_client.accounting_ledger_set_dirty(company_id, False)
        return
    first_fy, last_key = _fy(_key(first)), _key(last)
    last_fy = _fy(last_key)
    # Years outside the company's postings now (a document moved) hold nothing for it.
    for fy in existing:
        if fy < first_fy or fy > last_fy:
            sp_client.accounting_ledger_save_year(company_id, table_name(fy), [], [])
    start_fy = _fy(from_key) if from_key else first_fy
    if start_fy <= first_fy or (start_fy - 1) not in existing:
        start_fy, recompute = first_fy, None
    if start_fy == first_fy:
        opening = {lid: o for lid, (_name, o) in ledgers.items()}
    else:
        opening = {lid: float(r["Overall_Total"]) for lid, r in _read(company_id, start_fy - 1).items()}
    for fy in range(start_fy, last_fy + 1):
        months = [k for k in _fy_months(fy) if k <= last_key]
        stored = _read(company_id, fy) if fy in existing and recompute is not None else {}
        data = {}
        for key in months:
            kept = None if recompute is None or key in recompute else _stored_month(stored, key)
            data[key] = kept if kept is not None else _movements(company_id, _first_day(key), _last_day(key))
        opening = _save_year(company_id, fy, months, data, opening, names)
    sp_client.accounting_ledger_set_dirty(company_id, False)


def ensure_built(company_id):
    if sp_client.accounting_ledger_is_dirty(int(company_id)):
        rebuild(company_id)


def sync_months(company_id, keys):
    """Works out these months again (and the Overall_Total that follows); never fails the caller."""
    keys = {k for k in keys if k}
    if not company_id or not keys:
        return
    try:
        if sp_client.accounting_ledger_is_dirty(int(company_id)):
            rebuild(company_id)
        else:
            rebuild(company_id, from_key=min(keys), recompute=keys)
    except Exception:  # noqa: BLE001 - the save itself stands; the next report rebuilds
        logger.exception("ledger year table sync failed (company %s, months %s)", company_id, sorted(keys))
        mark_dirty(company_id)


def mark_dirty(company_id=None):
    try:
        sp_client.accounting_ledger_set_dirty(int(company_id) if company_id else None, True)
    except Exception:  # noqa: BLE001
        logger.exception("could not mark the ledger year tables dirty (company %s)", company_id)


def document_month(doc_type, doc_id):
    """(company_id, (year, month)) of a saved document, or (None, None)."""
    if not doc_id:
        return None, None
    row = sp_client.accounting_ledger_document_date(doc_type, int(doc_id))
    if not row or not row.get("voucher_date"):
        return None, None
    return row["company_id"], _key(row["voucher_date"])


def sync_document(doc_type, doc_id, also=None):
    """A document changed: its month (plus `also`, e.g. its month before the edit) is worked out again."""
    company_id, key = document_month(doc_type, doc_id)
    keys = {key}
    if also:
        company_id = company_id or also[0]
        keys.add(also[1])
    sync_months(company_id, keys)


def cumulative(company_id, as_of=None):
    """
    {ledger_id: Debit - Credit} of every posting up to as_of (None = all),
    opening balance NOT included - from the year table (Opening_Balance + the
    Balance of every whole month before as_of), plus the live postings of the
    days after the last month the table covers.
    """
    company_id = int(company_id)
    ensure_built(company_id)
    existing = _existing()
    ledgers = _ledgers(company_id)
    target_fy = (max(existing) if existing else None) if as_of is None else _fy(_key(as_of))
    fy = max((y for y in existing if target_fy is not None and y <= target_fy), default=None)
    result, live_from = {}, None
    rows = _read(company_id, fy) if fy is not None else {}
    if rows:   # no rows = nothing posted up to this year for the company: all live
        columns = set(next(iter(rows.values())))
        result = {lid: float(r["Opening_Balance"]) for lid, r in rows.items()}
        covered = None
        for key in _fy_months(fy):
            whole = as_of is None or key < _key(as_of) or (key == _key(as_of) and as_of == _last_day(key))
            if not whole or f"{_mon(key)}_Cr" not in columns:
                break
            for lid, r in rows.items():
                result[lid] = result.get(lid, 0.0) + float(r.get(f"{_mon(key)}_Balance") or 0)
            covered = key
        for lid, (_name, opening) in ledgers.items():   # the table's totals include the opening balance
            result[lid] = result.get(lid, 0.0) - opening
        live_from = _first_day(_next(covered)) if covered else _first_day(_fy_months(fy)[0])
    if as_of is None or live_from is None or live_from <= as_of:
        for lid, (debit, credit) in _movements(company_id, live_from, as_of).items():
            result[lid] = result.get(lid, 0.0) + debit - credit
    return result


def _response_id(response):
    try:
        return json.loads(response.content or b"{}").get("id")
    except ValueError:
        return None


def posts_to_ledger(doc_type, id_kwarg=None):
    """Document save view: after a successful save its old and new months are worked out again."""
    def decorator(view):
        @functools.wraps(view)
        def wrapper(request, *args, **kwargs):
            doc_id = (kwargs.get(id_kwarg) or (args[0] if args else None)) if id_kwarg else None
            before = document_month(doc_type, doc_id) if doc_id else (None, None)
            response = view(request, *args, **kwargs)
            if 200 <= response.status_code < 300:
                sync_document(doc_type, doc_id or _response_id(response), also=before if before[0] else None)
            return response
        return wrapper
    return decorator


def changes_postings(view):
    """Master save view: how documents post may have changed - rebuild before the next report."""
    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        response = view(request, *args, **kwargs)
        if 200 <= response.status_code < 300:
            mark_dirty()
        return response
    return wrapper
