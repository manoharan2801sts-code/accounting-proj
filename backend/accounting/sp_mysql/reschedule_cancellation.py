"""
dbo.sp_RescheduleTicket and dbo.sp_CancellationTicket
(backend/sp_reference/StoredProcedures.sql) for MySQL/TiDB.

sp_RescheduleTicket : LIST, LIST_FOR_BALANCE, GET_HEADER, GET_LINE_KEYS,
                      RESOLVE_LINES, RESOLVE_ORIGINAL_LINE_IDS, SAVE
sp_CancellationTicket: LIST, GET_HEADER, GET_LINES, SAVE, UPDATE

OPENJSON(...) WITH (...) is done in Python (TiDB has no JSON_TABLE): the
JSON is parsed and each declared column converted to its WITH type
(INT / DECIMAL(p,s) rounded half-up / NVARCHAR(n) truncated), with the
same NULL-for-missing-key lax-mode behaviour. Text equality/uniqueness
that SQL Server's case-insensitive, trailing-space-insensitive collation
did implicitly is done with LOWER(TRIM(..)) so MySQL and TiDB (utf8mb4_bin)
behave alike.
"""
import datetime
import json
import re
from decimal import ROUND_HALF_UP, Decimal

from django.db import DatabaseError, transaction

from . import SPThrow, bits, execute, query, query_one, sp, to_date

RT = "dbo.sp_RescheduleTicket"
CT = "dbo.sp_CancellationTicket"


# --------------------------------------------------------------------------
# Parameter coercion (what SQL Server does when the value is bound to the
# procedure's declared parameter type)
# --------------------------------------------------------------------------

class _ConvError(SPThrow):
    """A T-SQL conversion error (caught by a CATCH block when raised inside TRY)."""


def _p_int(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    s = str(v).strip()
    if not re.fullmatch(r"[+-]?\d+", s):
        raise SPThrow(f"Conversion failed when converting the nvarchar value '{v}' to data type int.")
    return int(s)


def _p_str(v, n):
    """NVARCHAR(n) parameter - silently truncated on assignment."""
    if v is None:
        return None
    if isinstance(v, bool):
        v = int(v)
    return str(v)[:n]


def _round_dec(d, prec, scale, conv_err=SPThrow, what="nvarchar"):
    q = d.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
    if abs(q) >= Decimal(10) ** (prec - scale):
        raise conv_err(f"Arithmetic overflow error converting {what} to data type numeric.")
    return q


_DEC_RE = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)")


def _p_dec(v, prec, scale):
    if v is None:
        return None
    if isinstance(v, bool):
        d = Decimal(int(v))
    elif isinstance(v, (int, Decimal)):
        d = Decimal(v)
    elif isinstance(v, float):
        d = Decimal(repr(v))
    else:
        s = str(v).strip()
        if not _DEC_RE.fullmatch(s):
            raise SPThrow("Error converting data type nvarchar to numeric.")
        d = Decimal(s)
    return _round_dec(d, prec, scale)


def _p_date(v):
    try:
        return to_date(v)
    except (TypeError, ValueError):
        raise SPThrow("Error converting data type nvarchar to date.")


def _utcnow():
    """SYSUTCDATETIME() - naive UTC, as Django (USE_TZ=True) stores DATETIME on MySQL."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _fmt_dec(d):
    """CAST(decimal AS NVARCHAR(30))."""
    return format(d, "f")


# --------------------------------------------------------------------------
# OPENJSON(@json) WITH (col TYPE '$.col', ...)
# --------------------------------------------------------------------------

def _json_elems(text):
    """The rows OPENJSON yields: one per array element (an object -> one row)."""
    if text is None:
        return []
    try:
        doc = json.loads(text, parse_float=Decimal)
    except (TypeError, ValueError):
        raise SPThrow("JSON text is not properly formatted.")
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict):
        return [doc]
    raise SPThrow("JSON text is not properly formatted.")


def _jtext(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _j_int(v):
    if v is None or isinstance(v, (dict, list)):
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    s = _jtext(v)
    if not re.fullmatch(r"[+-]?\d+", s.strip()):
        raise _ConvError(f"Conversion failed when converting the nvarchar value '{s}' to data type int.")
    return int(s.strip())


def _j_dec(v, prec, scale):
    if v is None or isinstance(v, (dict, list)):
        return None
    if isinstance(v, bool):
        d = Decimal(int(v))
    elif isinstance(v, (int, Decimal)):
        d = Decimal(v)
    else:
        s = str(v).strip()
        if not _DEC_RE.fullmatch(s):
            raise _ConvError("Error converting data type nvarchar to numeric.")
        d = Decimal(s)
    return _round_dec(d, prec, scale, _ConvError)


def _j_str(v, n):
    if v is None or isinstance(v, (dict, list)):
        return None
    return _jtext(v)[:n]


def _openjson(elems, schema):
    """schema: list of (name, kind, *args) with kind in int/dec/str; path '$.<name>'."""
    out = []
    for e in elems:
        e = e if isinstance(e, dict) else {}
        row = {}
        for name, kind, *args in schema:
            v = e.get(name)
            if kind == "int":
                row[name] = _j_int(v)
            elif kind == "dec":
                row[name] = _j_dec(v, *args)
            else:
                row[name] = _j_str(v, *args)
        out.append(row)
    return out


def _ci_key(s):
    """SQL Server equality key for text (case-insensitive, trimmed); NULL stays NULL."""
    return None if s is None else s.strip().lower()


def _distinct_ordered_agg(values):
    """STRING_AGG(DISTINCT-ed values, ', ') WITHIN GROUP (ORDER BY value) - NULLs skipped."""
    seen = {}
    for v in values:
        if v is not None and _ci_key(v) not in seen:
            seen[_ci_key(v)] = v
    if not seen:
        return None
    return ", ".join(seen[k] for k in sorted(seen))


def _ordered_agg(values):
    """STRING_AGG(value, ', ') WITHIN GROUP (ORDER BY value) - no DISTINCT, NULLs skipped."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return ", ".join(sorted(vals, key=lambda s: (_ci_key(s), s)))


def _has_dup_ticket_no(elems):
    """GROUP BY ticket_no HAVING COUNT(*) > 1 over OPENJSON ticket_no NVARCHAR(30) (NULLs group together)."""
    counts = {}
    for r in _openjson(elems, [("ticket_no", "str", 30)]):
        k = _ci_key(r["ticket_no"])
        counts[k] = counts.get(k, 0) + 1
    return any(c > 1 for c in counts.values())


def _in(n):
    return ", ".join(["%s"] * n)


def _ledger_id(company_id, name, category, last=True):
    """`SELECT @X = id FROM Ledgers WHERE company_id=.. AND name=.. AND ledger_category=..`
    (variable assignment keeps the LAST row scanned - clustered id order)."""
    row = query_one(
        "SELECT `id` FROM `Ledgers` WHERE `company_id` = %s AND LOWER(TRIM(`name`)) = LOWER(TRIM(%s)) "
        "AND LOWER(TRIM(`ledger_category`)) = LOWER(%s) ORDER BY `id` " + ("DESC" if last else "ASC") + " LIMIT 1",
        [company_id, name, category],
    )
    return row["id"] if row else None


def _ledger_id_subquery(company_id, name):
    """`(SELECT id FROM Ledgers WHERE ... name = j.supplier_name AND ledger_category = 'CREDITOR')` as a scalar subquery."""
    if name is None:
        return None
    rows = query(
        "SELECT `id` FROM `Ledgers` WHERE `company_id` = %s AND LOWER(TRIM(`name`)) = LOWER(TRIM(%s)) "
        "AND LOWER(TRIM(`ledger_category`)) = 'creditor' ORDER BY `id` LIMIT 2",
        [company_id, name],
    )
    if len(rows) > 1:
        raise _ConvError(
            "Subquery returned more than 1 value. This is not permitted when the subquery follows "
            "=, !=, <, <= , >, >= or when the subquery is used as an expression."
        )
    return rows[0]["id"] if rows else None


def _err(message):
    """`SELECT NULL AS id, 'Error' AS status, <message> AS error`."""
    return [{"id": None, "status": "Error", "error": message}]


def _db_error_message(e):
    """ERROR_MESSAGE() for an error raised inside BEGIN TRY."""
    if isinstance(e, SPThrow):
        return str(e)
    cause = e.__cause__ or e
    args = getattr(cause, "args", ())
    if len(args) > 1 and isinstance(args[1], str):
        return args[1]
    return str(e)


def _run_try(work):
    """BEGIN TRY BEGIN TRAN ... COMMIT END TRY BEGIN CATCH ROLLBACK; SELECT error END CATCH.
    Returns (result, None) or (None, error_rows) - the rollback has happened before the error row is built."""
    try:
        with transaction.atomic():
            result = work()
    except (DatabaseError, _ConvError) as e:
        return None, _err(_db_error_message(e))
    return result, None


# ==========================================================================
# dbo.sp_RescheduleTicket
# ==========================================================================

@sp(RT, "LIST_FOR_BALANCE")
def _rt_list_for_balance(p):
    company_id = _p_int(p.get("CompanyId"))
    as_of = _p_date(p.get("AsOfDate"))
    from_d = _p_date(p.get("FromDate"))
    return query(
        """
        SELECT
            rt.id AS reschedule_ticket_id, rt.company_id, cust.id AS customer_id, cust.name AS customer_name, cust.state_name AS customer_state_name,
            rt.booking_reference, rt.airline_pnr, rt.payment_mode, rt.payment_gateway_ref, rt.invoice_date, rt.booking_ref_date, rt.branch_name,
            rt.office_id AS ticket_office_id, rt.invoice_number, v.voucher_no,
            rl.id AS line_id, rl.airline_code, rl.airline_name, rl.airline_category, rl.flight_no, rl.ticket_no, rl.passenger_name, rl.pax_type,
            rl.sector, rl.travel_date, rl.cabin, rl.travel_class, rl.fare_type,
            rl.basic_fare, rl.yq, rl.yr, rl.k3_tax, rl.tax_others, rl.seat, rl.meal, rl.baggage, rl.other_ssr, rl.supplier_penalty,
            rl.disc_on, rl.disc_type, rl.disc_value, rl.tds_per, rl.pg_charges, rl.pg_charges_percentage,
            rl.markup, rl.addl_markup, rl.ssr_markup, rl.service_fee, rl.addl_service_fee, rl.ssr_service_fee, rl.gst_pct,
            rl.status, rl.office_id, rl.fop, rl.card_number,
            rl.supp_comm_on, rl.supp_comm_type, rl.supp_comm_value, rl.supp_tds_per,
            rl.supp_markup, rl.supp_addl_markup, rl.supp_service_fee, rl.supp_addl_service_fee, rl.supp_gst_pct,
            rl.agent_penalty, rl.reschedule_penalty,
            rl.total_billed, rl.supplier_ledger_id, supp.name AS supplier_name
        FROM `Rescheduled_Al_Ticket` rt
        INNER JOIN `Ledgers` cust ON cust.id = rt.customer_ledger_id
        INNER JOIN `Rescheduled_Al_TicketLines` rl ON rl.reschedule_ticket_id = rt.id
        LEFT JOIN `Ledgers` supp ON supp.id = rl.supplier_ledger_id
        LEFT JOIN `JournalVoucher` v ON v.source_reschedule_ticket_id = rt.id
        WHERE rt.company_id = %s
          AND (%s IS NULL OR rt.invoice_date <= %s)
          AND (%s IS NULL OR rt.invoice_date >= %s)
        ORDER BY rt.id, rl.id, v.id
        """,
        [company_id, as_of, as_of, from_d, from_d],
    )


@sp(RT, "GET_HEADER")
def _rt_get_header(p):
    return query(
        "SELECT `id`, `original_ticket_id`, `booking_reference`, `airline_pnr` "
        "FROM `Rescheduled_Al_Ticket` WHERE `id` = %s AND `company_id` = %s",
        [_p_int(p.get("Id")), _p_int(p.get("CompanyId"))],
    )


@sp(RT, "GET_LINE_KEYS")
def _rt_get_line_keys(p):
    return query(
        "SELECT `original_ticket_line_id`, `based_on_reschedule_line_id` "
        "FROM `Rescheduled_Al_TicketLines` WHERE `reschedule_ticket_id` = %s ORDER BY `id`",
        [_p_int(p.get("Id"))],
    )


def _by_id(table, cols, ids):
    ids = sorted({i for i in ids if i is not None})
    if not ids:
        return {}
    rows = query(f"SELECT `id`, {cols} FROM `{table}` WHERE `id` IN ({_in(len(ids))})", ids)
    return {r["id"]: r for r in rows}


@sp(RT, "RESOLVE_ORIGINAL_LINE_IDS")
def _rt_resolve_original_line_ids(p):
    src = _openjson(_json_elems(p.get("PairsJson")), [("reschedule_line_id", "int")])
    rl = _by_id("Rescheduled_Al_TicketLines", "`original_ticket_line_id`", [s["reschedule_line_id"] for s in src])
    return [
        {
            "reschedule_line_id": s["reschedule_line_id"],
            "original_ticket_line_id": rl.get(s["reschedule_line_id"], {}).get("original_ticket_line_id"),
        }
        for s in src
    ]


@sp(RT, "RESOLVE_LINES")
def _rt_resolve_lines(p):
    original_ticket_id = _p_int(p.get("OriginalTicketId"))
    src = _openjson(
        _json_elems(p.get("PairsJson")),
        [("original_ticket_line_id", "int"), ("reschedule_line_id", "int")],
    )
    otl = {}
    oids = sorted({s["original_ticket_line_id"] for s in src if s["original_ticket_line_id"] is not None})
    if oids and original_ticket_id is not None:
        for r in query(
            f"SELECT `id`, `ticket_no`, `rescheduled` FROM `AL_TicketLines` "
            f"WHERE `ticket_id` = %s AND `id` IN ({_in(len(oids))})",
            [original_ticket_id] + oids,
        ):
            otl[r["id"]] = r
    ot = None
    if original_ticket_id is not None:
        ot = query_one("SELECT `booking_reference` FROM `AL_Tickets` WHERE `id` = %s", [original_ticket_id])
    rtl = _by_id(
        "Rescheduled_Al_TicketLines", "`ticket_no`, `rescheduled`, `reschedule_ticket_id`",
        [s["reschedule_line_id"] for s in src],
    )
    rt2 = _by_id("Rescheduled_Al_Ticket", "`booking_reference`", [r["reschedule_ticket_id"] for r in rtl.values()])

    out = []
    for s in src:
        o = otl.get(s["original_ticket_line_id"])
        b = rtl.get(s["reschedule_line_id"])
        b2 = rt2.get(b["reschedule_ticket_id"]) if b else None
        out.append(bits({
            "original_ticket_line_id": s["original_ticket_line_id"],
            "original_id": o["id"] if o else None,
            "original_ticket_no": o["ticket_no"] if o else None,
            "original_rescheduled": o["rescheduled"] if o else None,
            "original_ticket_booking_reference": ot["booking_reference"] if ot else None,
            "based_on_id": s["reschedule_line_id"],
            "based_on_ticket_no": b["ticket_no"] if b else None,
            "based_on_rescheduled": b["rescheduled"] if b else None,
            "based_on_booking_reference": b2["booking_reference"] if b2 else None,
        }, "original_rescheduled", "based_on_rescheduled"))
    return out


_DISC_BASE = """(CASE LOWER(TRIM(rl.disc_type))
                WHEN 'percentage' THEN
                    (CASE LOWER(TRIM(rl.disc_on))
                        WHEN 'basic' THEN rl.basic_fare
                        WHEN 'basic + yq' THEN rl.basic_fare + rl.yq
                        WHEN 'basic + yr' THEN rl.basic_fare + rl.yr
                        WHEN 'basic + yq + yr' THEN rl.basic_fare + rl.yq + rl.yr
                        WHEN 'gross' THEN rl.basic_fare + rl.yq + rl.yr + rl.k3_tax + rl.tax_others + rl.seat + rl.meal + rl.baggage + rl.other_ssr
                        ELSE 0 END) * (rl.disc_value / 100)
                WHEN 'flat' THEN rl.disc_value
                ELSE 0 END)"""


@sp(RT, "LIST")
def _rt_list(p):
    return query(
        f"""
        SELECT
            rl.id, CAST(NULL AS SIGNED) AS ticket_id, rt.id AS reschedule_ticket_id,
            COALESCE(rt.airline_pnr, rt.gds_pnr, rt.booking_reference) AS pnr,
            rl.ticket_no, rl.airline_name, rl.airline_code, rl.flight_no, rl.passenger_name, rl.pax_type,
            rl.sector, rt.invoice_date AS issue_date, rl.travel_date,
            rl.basic_fare, rl.markup, rl.total_billed, rl.status,
            rt.invoice_number, rt.invoice_date, rt.invoice_type, rt.booking_mode, rt.booking_type,
            rt.booking_status, cust.name AS customer_name,
            rt.travel_type, rt.user_name, rt.currency, rt.roe, rt.booking_given_by, rt.payment_mode, rl.airline_category,
            rt.booking_reference, rt.booking_ref_date, rt.airline_pnr, rt.gds_pnr, supp.name AS supplier_name,
            rl.office_id, rl.fop, rl.card_number,
            rl.yq, rl.yr, rl.k3_tax, rl.tax_others, rl.seat, rl.meal, rl.baggage, rl.other_ssr,
            rl.disc_on, rl.disc_type, rl.disc_value, rl.tds_per,
            rl.addl_markup, rl.ssr_markup, rl.service_fee, rl.addl_service_fee, rl.ssr_service_fee, rl.gst_pct,
            rl.supp_comm_on, rl.supp_comm_type, rl.supp_comm_value, rl.supp_tds_per,
            rl.supp_markup, rl.supp_addl_markup, rl.supp_service_fee, rl.supp_addl_service_fee,
            {_DISC_BASE} AS computed_discount,
            {_DISC_BASE} * (rl.tds_per / 100) AS computed_tds,
            (rl.service_fee * IFNULL(l_svc.gst_percentage, 0) / 100
             + rl.addl_service_fee * IFNULL(l_addlsvc.gst_percentage, 0) / 100
             + rl.ssr_service_fee * IFNULL(l_ssrsvc.gst_percentage, 0) / 100) AS computed_gst,
            (rl.supp_service_fee * IFNULL(l_suppsvc.gst_percentage, 0) / 100
             + rl.supp_addl_service_fee * IFNULL(l_suppaddlsvc.gst_percentage, 0) / 100) AS computed_supp_gst,
            rl.agent_penalty, rl.reschedule_penalty, rl.supplier_penalty
        FROM `Rescheduled_Al_TicketLines` rl
        INNER JOIN `Rescheduled_Al_Ticket` rt ON rt.id = rl.reschedule_ticket_id
        INNER JOIN `Ledgers` cust ON cust.id = rt.customer_ledger_id
        LEFT JOIN `Ledgers` supp ON supp.id = rl.supplier_ledger_id
        LEFT JOIN `MasterMapping` mm_svc ON mm_svc.company_id = rt.company_id
            AND LOWER(TRIM(mm_svc.product_type)) = 'airline' AND LOWER(TRIM(mm_svc.field_name)) = 'service fee a/c'
        LEFT JOIN `Ledgers` l_svc ON l_svc.id = mm_svc.ledger_id
        LEFT JOIN `MasterMapping` mm_addlsvc ON mm_addlsvc.company_id = rt.company_id
            AND LOWER(TRIM(mm_addlsvc.product_type)) = 'airline' AND LOWER(TRIM(mm_addlsvc.field_name)) = 'addl service fee a/c'
        LEFT JOIN `Ledgers` l_addlsvc ON l_addlsvc.id = mm_addlsvc.ledger_id
        LEFT JOIN `MasterMapping` mm_ssrsvc ON mm_ssrsvc.company_id = rt.company_id
            AND LOWER(TRIM(mm_ssrsvc.product_type)) = 'airline' AND LOWER(TRIM(mm_ssrsvc.field_name)) = 'ssr service fee a/c'
        LEFT JOIN `Ledgers` l_ssrsvc ON l_ssrsvc.id = mm_ssrsvc.ledger_id
        LEFT JOIN `MasterMapping` mm_suppsvc ON mm_suppsvc.company_id = rt.company_id
            AND LOWER(TRIM(mm_suppsvc.product_type)) = 'airline' AND LOWER(TRIM(mm_suppsvc.field_name)) = 'supplier service fee a/c'
        LEFT JOIN `Ledgers` l_suppsvc ON l_suppsvc.id = mm_suppsvc.ledger_id
        LEFT JOIN `MasterMapping` mm_suppaddlsvc ON mm_suppaddlsvc.company_id = rt.company_id
            AND LOWER(TRIM(mm_suppaddlsvc.product_type)) = 'airline' AND LOWER(TRIM(mm_suppaddlsvc.field_name)) = 'supplier addl service fee a/c'
        LEFT JOIN `Ledgers` l_suppaddlsvc ON l_suppaddlsvc.id = mm_suppaddlsvc.ledger_id
        WHERE rt.company_id = %s
        ORDER BY rl.id DESC
        """,
        [_p_int(p.get("CompanyId"))],
    )


_RT_LINE_SCHEMA = [
    ("original_ticket_line_id", "int"), ("based_on_reschedule_line_id", "int"),
    ("parent_pnr", "str", 30),
    ("airline_code", "str", 200), ("airline_name", "str", 200),
    ("airline_category", "str", 5), ("flight_no", "str", 200),
    ("ticket_no", "str", 30), ("passenger_name", "str", 50),
    ("pax_type", "str", 10), ("sector", "str", 200), ("travel_date", "str", 200),
    ("cabin", "str", 200), ("travel_class", "str", 200), ("fare_type", "str", 300),
    ("basic_fare", "dec", 14, 2), ("yq", "dec", 14, 2), ("yr", "dec", 14, 2),
    ("k3_tax", "dec", 14, 2), ("tax_others", "dec", 14, 2), ("seat", "dec", 14, 2),
    ("meal", "dec", 14, 2), ("baggage", "dec", 14, 2), ("other_ssr", "dec", 14, 2),
    ("supplier_penalty", "dec", 14, 2),
    ("disc_on", "str", 20), ("disc_type", "str", 12), ("disc_value", "dec", 14, 2),
    ("tds_per", "dec", 5, 2), ("pg_charges", "dec", 14, 2), ("pg_charges_percentage", "dec", 5, 2),
    ("markup", "dec", 14, 2), ("addl_markup", "dec", 14, 2), ("ssr_markup", "dec", 14, 2),
    ("service_fee", "dec", 14, 2), ("addl_service_fee", "dec", 14, 2),
    ("ssr_service_fee", "dec", 14, 2), ("gst_pct", "dec", 5, 2), ("status", "str", 15),
    ("office_id", "str", 30), ("fop", "str", 20), ("card_number", "str", 40),
    ("supp_comm_on", "str", 20), ("supp_comm_type", "str", 12),
    ("supp_comm_value", "dec", 14, 2), ("supp_tds_per", "dec", 5, 2),
    ("supp_markup", "dec", 14, 2), ("supp_addl_markup", "dec", 14, 2),
    ("supp_service_fee", "dec", 14, 2), ("supp_addl_service_fee", "dec", 14, 2),
    ("supp_gst_pct", "dec", 5, 2), ("agent_penalty", "dec", 14, 2),
    ("reschedule_penalty", "dec", 14, 2), ("total_billed", "dec", 14, 2),
    ("supplier_name", "str", 150),
]

_RT_LINE_COPY_COLS = [
    "airline_code", "airline_name", "airline_category", "flight_no", "ticket_no", "passenger_name", "pax_type",
    "sector", "travel_date", "cabin", "travel_class", "fare_type", "basic_fare", "yq", "yr", "k3_tax", "tax_others",
    "seat", "meal", "baggage", "other_ssr", "supplier_penalty", "disc_on", "disc_type", "disc_value", "tds_per",
    "pg_charges", "pg_charges_percentage", "markup", "addl_markup", "ssr_markup", "service_fee", "addl_service_fee",
    "ssr_service_fee", "gst_pct", "status", "office_id", "fop", "card_number", "supp_comm_on", "supp_comm_type",
    "supp_comm_value", "supp_tds_per", "supp_markup", "supp_addl_markup", "supp_service_fee", "supp_addl_service_fee",
    "supp_gst_pct", "agent_penalty", "reschedule_penalty", "total_billed",
]


def _first_existing_ticket_no(table, ticket_nos, extra_where="", extra_params=()):
    """TOP 1 t.ticket_no FROM <table> t INNER JOIN OPENJSON(..) j ON j.ticket_no = t.ticket_no [WHERE ...]."""
    tns = [t for t in ticket_nos if t is not None]
    if not tns:
        return None
    row = query_one(
        f"SELECT `ticket_no` FROM `{table}` WHERE LOWER(TRIM(`ticket_no`)) IN "
        f"({', '.join(['LOWER(TRIM(%s))'] * len(tns))}){extra_where} ORDER BY `id` LIMIT 1",
        list(tns) + list(extra_params),
    )
    return row["ticket_no"] if row else None


@sp(RT, "SAVE")
def _rt_save(p):
    rid = _p_int(p.get("Id"))
    company_id = _p_int(p.get("CompanyId"))
    original_ticket_id = _p_int(p.get("OriginalTicketId"))
    customer_name = _p_str(p.get("CustomerName"), 150)
    supplier_name = _p_str(p.get("SupplierName"), 150)
    branch_name = _p_str(p.get("BranchName"), 100)
    invoice_number = _p_str(p.get("InvoiceNumber"), 20)
    invoice_date = _p_date(p.get("InvoiceDate"))
    invoice_type = _p_str(p.get("InvoiceType"), 100)
    booking_mode = _p_str(p.get("BookingMode"), 20)
    booking_type = _p_str(p.get("BookingType"), 30)
    booking_status = _p_str(p.get("BookingStatus"), 20)
    travel_type = _p_str(p.get("TravelType"), 20)
    user_name = _p_str(p.get("UserName"), 100)
    currency = _p_str(p.get("Currency"), 5)
    roe = _p_dec(p.get("Roe"), 10, 4)
    booking_given_by = _p_str(p.get("BookingGivenBy"), 25)
    booking_reference = _p_str(p.get("BookingReference"), 30)
    booking_ref_date = _p_date(p.get("BookingRefDate"))
    airline_pnr = _p_str(p.get("AirlinePnr"), 13)
    gds_pnr = _p_str(p.get("GdsPnr"), 13)
    office_id = _p_str(p.get("OfficeId"), 30)
    payment_mode = _p_str(p.get("PaymentMode"), 20)
    payment_gateway_ref = _p_str(p.get("PaymentGatewayRef"), 60)
    airline_category = _p_str(p.get("AirlineCategory"), 5)
    lines_json = p.get("LinesJson")
    jv_narration = _p_str(p.get("JvNarration"), 250)
    jv_total_debit = _p_dec(p.get("JvTotalDebit"), 16, 2)
    jv_total_credit = _p_dec(p.get("JvTotalCredit"), 16, 2)

    cust_ledger_id = _ledger_id(company_id, customer_name, "DEBTOR")
    if cust_ledger_id is None:
        return _err('"' + (customer_name or "") + '" is not a real customer ledger (Sundry Debtors).')
    supp_ledger_id = None
    if supplier_name is not None:
        supp_ledger_id = _ledger_id(company_id, supplier_name, "CREDITOR")
        if supp_ledger_id is None:
            return _err('"' + supplier_name + '" is not a real supplier ledger (Sundry Creditors).')

    if rid is not None and not query_one(
        "SELECT 1 AS x FROM `Rescheduled_Al_Ticket` WHERE `id` = %s AND `company_id` = %s", [rid, company_id]
    ):
        return _err("Reschedule ticket not found.")

    if query_one(
        "SELECT 1 AS x FROM `AL_Tickets` WHERE `company_id` = %s AND LOWER(TRIM(`invoice_number`)) = LOWER(TRIM(%s)) LIMIT 1",
        [company_id, invoice_number],
    ) or query_one(
        "SELECT 1 AS x FROM `Rescheduled_Al_Ticket` WHERE `company_id` = %s AND LOWER(TRIM(`invoice_number`)) = LOWER(TRIM(%s)) "
        "AND (%s IS NULL OR `id` <> %s) LIMIT 1",
        [company_id, invoice_number, rid, rid],
    ):
        return _err('Invoice Number "' + invoice_number + '" already exists.')
    if query_one(
        "SELECT 1 AS x FROM `AL_Tickets` WHERE `company_id` = %s AND LOWER(TRIM(`booking_reference`)) = LOWER(TRIM(%s)) LIMIT 1",
        [company_id, booking_reference],
    ) or query_one(
        "SELECT 1 AS x FROM `Rescheduled_Al_Ticket` WHERE `company_id` = %s AND LOWER(TRIM(`booking_reference`)) = LOWER(TRIM(%s)) "
        "AND (%s IS NULL OR `id` <> %s) LIMIT 1",
        [company_id, booking_reference, rid, rid],
    ):
        return _err('Rescheduled Ref "' + booking_reference + '" already exists.')

    elems = _json_elems(lines_json)
    if _has_dup_ticket_no(elems):
        return _err("Duplicate Ticket Number within this submission.")

    tns = [r["ticket_no"] for r in _openjson(elems, [("ticket_no", "str", 30)])]
    dup = _first_existing_ticket_no("AL_TicketLines", tns)
    if dup is None:
        dup = _first_existing_ticket_no(
            "Rescheduled_Al_TicketLines", tns, " AND (%s IS NULL OR `reschedule_ticket_id` <> %s)", (rid, rid)
        )
    if dup is not None:
        return _err('Ticket Number "' + dup + '" already exists.')

    # Every line's own supplier_name (if given) must resolve to a real supplier ledger.
    for j in _openjson(elems, [("supplier_name", "str", 150), ("ticket_no", "str", 30)]):
        if j["supplier_name"] is not None and _ledger_id(company_id, j["supplier_name"], "CREDITOR") is None:
            return _err(
                '"' + j["supplier_name"] + '" (Ticket No. ' + (j["ticket_no"] if j["ticket_no"] is not None else "?")
                + ") is not a real supplier ledger (Sundry Creditors)."
            )

    # Save-time eligibility re-check against the live flags.
    # 8.10.26 build fix: the chain link is read from $.based_on_reschedule_line_id
    # (what views._build_reschedule_lines actually sends), not $.reschedule_line_id.
    pairs = [{"original_ticket_line_id": j["original_ticket_line_id"], "reschedule_line_id": j["based_on_reschedule_line_id"]}
             for j in _openjson(elems, [("original_ticket_line_id", "int"), ("based_on_reschedule_line_id", "int")])]
    otl = _by_id("AL_TicketLines", "`ticket_no`, `rescheduled`", [j["original_ticket_line_id"] for j in pairs])
    rtl = _by_id("Rescheduled_Al_TicketLines", "`ticket_no`, `rescheduled`", [j["reschedule_line_id"] for j in pairs])
    existing = set()
    if rid is not None:
        for r in query(
            "SELECT `original_ticket_line_id`, `based_on_reschedule_line_id` FROM `Rescheduled_Al_TicketLines` "
            "WHERE `reschedule_ticket_id` = %s", [rid]
        ):
            existing.add((r["original_ticket_line_id"],
                          -1 if r["based_on_reschedule_line_id"] is None else r["based_on_reschedule_line_id"]))
    conflicting = []
    for j in pairs:
        o, rl_id = j["original_ticket_line_id"], j["reschedule_line_id"]
        if o is not None and (o, -1 if rl_id is None else rl_id) in existing:
            continue
        o_row, r_row = otl.get(o), rtl.get(rl_id)
        if rl_id is not None:
            if r_row and r_row["rescheduled"]:
                conflicting.append(r_row["ticket_no"])
        elif o_row and o_row["rescheduled"]:
            conflicting.append(o_row["ticket_no"])
    conflicting = _distinct_ordered_agg(conflicting)
    if conflicting is not None:
        return _err("Ticket No. " + conflicting + " has already been rescheduled and cannot be rescheduled again.")

    currency_or_default = currency if currency is not None else "INR"

    def work():
        was_created = False
        now = _utcnow()
        if rid is not None:
            result_id = rid
            old = query(
                "SELECT `original_ticket_line_id`, `based_on_reschedule_line_id` FROM `Rescheduled_Al_TicketLines` "
                "WHERE `reschedule_ticket_id` = %s", [rid]
            )
            execute(
                """
                UPDATE `Rescheduled_Al_Ticket`
                SET customer_ledger_id = %s, supplier_ledger_id = %s,
                    invoice_number = %s, invoice_date = %s, invoice_type = %s,
                    booking_mode = IFNULL(%s, booking_mode), booking_type = %s, booking_status = %s,
                    travel_type = %s, user_name = %s, currency = %s, roe = IFNULL(%s, roe),
                    booking_given_by = %s, booking_reference = %s, booking_ref_date = %s,
                    airline_pnr = %s, gds_pnr = %s, office_id = %s,
                    payment_mode = %s, payment_gateway_ref = %s, airline_category = %s,
                    branch_name = %s
                WHERE id = %s
                """,
                [cust_ledger_id, supp_ledger_id, invoice_number, invoice_date, invoice_type,
                 booking_mode, booking_type, booking_status, travel_type, user_name, currency_or_default, roe,
                 booking_given_by, booking_reference, booking_ref_date, airline_pnr, gds_pnr, office_id,
                 payment_mode, payment_gateway_ref, airline_category, branch_name, rid],
            )
            # A line dropped from this resubmission goes back to eligible.
            new_orig = {j["original_ticket_line_id"] for j in _openjson(elems, [("original_ticket_line_id", "int")])}
            reset_otl = sorted({o["original_ticket_line_id"] for o in old
                                if o["original_ticket_line_id"] not in new_orig})
            reset_rtl = sorted({o["based_on_reschedule_line_id"] for o in old
                                if o["based_on_reschedule_line_id"] is not None
                                and o["original_ticket_line_id"] not in new_orig})
            if reset_otl:
                execute(f"UPDATE `AL_TicketLines` SET `rescheduled` = 0 WHERE `id` IN ({_in(len(reset_otl))})", reset_otl)
            if reset_rtl:
                execute(f"UPDATE `Rescheduled_Al_TicketLines` SET `rescheduled` = 0 WHERE `id` IN ({_in(len(reset_rtl))})",
                        reset_rtl)
            # Wholesale delete + recreate.
            execute("DELETE FROM `Rescheduled_Al_TicketLines` WHERE `reschedule_ticket_id` = %s", [rid])
        else:
            _, result_id = execute(
                """
                INSERT INTO `Rescheduled_Al_Ticket`
                    (company_id, branch_name, original_ticket_id, invoice_number, invoice_date, invoice_type, booking_mode, booking_type, booking_status,
                     customer_ledger_id, supplier_ledger_id, travel_type, user_name, currency, roe, booking_given_by,
                     booking_reference, booking_ref_date, airline_pnr, gds_pnr, office_id, payment_mode, payment_gateway_ref,
                     airline_category, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [company_id, branch_name, original_ticket_id, invoice_number, invoice_date, invoice_type,
                 booking_mode if booking_mode is not None else "Manual", booking_type, booking_status,
                 cust_ledger_id, supp_ledger_id, travel_type, user_name, currency_or_default,
                 roe if roe is not None else Decimal(1), booking_given_by,
                 booking_reference, booking_ref_date, airline_pnr, gds_pnr, office_id, payment_mode, payment_gateway_ref,
                 airline_category, now, now],
            )
            was_created = True

        cols = (["reschedule_ticket_id", "original_ticket_line_id", "based_on_reschedule_line_id", "rescheduled", "parent_pnr"]
                + _RT_LINE_COPY_COLS + ["supplier_ledger_id", "created_at", "updated_at"])
        ins_sql = (f"INSERT INTO `Rescheduled_Al_TicketLines` ({', '.join('`%s`' % c for c in cols)}) "
                   f"VALUES ({_in(len(cols))})")
        lines = _openjson(elems, _RT_LINE_SCHEMA)
        for j in lines:
            vals = dict(j)
            if vals["status"] is None:
                vals["status"] = "ISSUED"
            supp_id = _ledger_id_subquery(company_id, j["supplier_name"])
            execute(ins_sql, [result_id, j["original_ticket_line_id"], j["based_on_reschedule_line_id"], 0, j["parent_pnr"]]
                    + [vals[c] for c in _RT_LINE_COPY_COLS] + [supp_id, now, now])

        # Every line (re-)used by this save is now ineligible for further rescheduling.
        set_otl = sorted({j["original_ticket_line_id"] for j in lines if j["original_ticket_line_id"] is not None})
        set_rtl = sorted({j["based_on_reschedule_line_id"] for j in lines if j["based_on_reschedule_line_id"] is not None})
        if set_otl:
            execute(f"UPDATE `AL_TicketLines` SET `rescheduled` = 1 WHERE `id` IN ({_in(len(set_otl))})", set_otl)
        if set_rtl:
            execute(f"UPDATE `Rescheduled_Al_TicketLines` SET `rescheduled` = 1 WHERE `id` IN ({_in(len(set_rtl))})", set_rtl)

        jv_branch = branch_name if branch_name is not None else "Chennai Branch"
        if query_one("SELECT 1 AS x FROM `JournalVoucher` WHERE `source_reschedule_ticket_id` = %s LIMIT 1", [result_id]):
            execute(
                "UPDATE `JournalVoucher` SET `branch_name` = %s, `voucher_date` = %s, `narration` = %s, "
                "`total_debit` = %s, `total_credit` = %s, `updated_at` = %s WHERE `source_reschedule_ticket_id` = %s",
                [jv_branch, invoice_date, jv_narration, jv_total_debit, jv_total_credit, _utcnow(), result_id],
            )
        else:
            next_num = query_one(
                "SELECT COUNT(*) AS n FROM `JournalVoucher` WHERE `company_id` = %s "
                "AND LOWER(TRIM(`category`)) = 'airline_reschedule'", [company_id]
            )["n"] + 1
            now2 = _utcnow()
            execute(
                "INSERT INTO `JournalVoucher` (company_id, branch_name, voucher_type, voucher_date, narration, category, voucher_no, "
                "source_reschedule_ticket_id, total_debit, total_credit, lines_json, created_at, updated_at) "
                "VALUES (%s, %s, 'Tax Invoice', %s, %s, 'AIRLINE_RESCHEDULE', %s, %s, %s, %s, '[]', %s, %s)",
                [company_id, jv_branch, invoice_date, jv_narration, "ALR-" + str(next_num), result_id,
                 jv_total_debit, jv_total_credit, now2, now2],
            )
        return result_id, was_created

    res, err = _run_try(work)
    if err:
        return err
    result_id, was_created = res
    ids = [str(r["id"]) for r in query(
        "SELECT `id` FROM `Rescheduled_Al_TicketLines` WHERE `reschedule_ticket_id` = %s ORDER BY `id`", [result_id])]
    line_ids = ",".join(ids) if ids else None
    return [
        {"id": result_id, "line_ids": line_ids, "voucher_id": v["id"], "voucher_no": v["voucher_no"],
         "was_created": was_created, "status": "Success"}
        for v in query("SELECT `id`, `voucher_no` FROM `JournalVoucher` WHERE `source_reschedule_ticket_id` = %s ORDER BY `id`",
                       [result_id])
    ]


# ==========================================================================
# dbo.sp_CancellationTicket
# ==========================================================================

@sp(CT, "LIST")
def _ct_list(p):
    return query(
        """
        SELECT cl.id, ct.id AS cancellation_ticket_id,
               ct.invoice_number, ct.cancellation_reference AS booking_reference,
               ct.airline_pnr, ct.gds_pnr, cl.ticket_no, cl.passenger_name,
               cl.total_billed
        FROM `Cancellation_Al_TicketLines` cl
        INNER JOIN `Cancellation_AL_Tickets` ct ON ct.id = cl.cancellation_ticket_id
        WHERE ct.company_id = %s
        ORDER BY cl.id DESC
        """,
        [_p_int(p.get("CompanyId"))],
    )


@sp(CT, "GET_HEADER")
def _ct_get_header(p):
    cid, company_id = _p_int(p.get("Id")), _p_int(p.get("CompanyId"))
    if not query_one("SELECT 1 AS x FROM `Cancellation_AL_Tickets` WHERE `id` = %s AND `company_id` = %s", [cid, company_id]):
        return _err("Cancellation not found.")
    return query(
        """
        SELECT ct.id, ct.original_ticket_id, ct.invoice_number, ct.invoice_date, ct.invoice_type,
               ct.booking_mode, ct.booking_type, ct.booking_status, cust.name AS customer_name,
               ct.travel_type, ct.user_name, ct.currency, ct.roe, ct.booking_given_by,
               ct.cancellation_reference, ct.cancellation_ref_date, ct.airline_pnr, ct.gds_pnr,
               supp.name AS supplier_name, ct.office_id, ct.payment_mode, ct.payment_gateway_ref,
               ct.airline_category, ct.branch_name, ct.customer_ledger_id,
               jv.id AS voucher_id, jv.voucher_no, jv.total_debit AS jv_total_debit, jv.total_credit AS jv_total_credit,
               'Success' AS status
        FROM `Cancellation_AL_Tickets` ct
        INNER JOIN `Ledgers` cust ON cust.id = ct.customer_ledger_id
        LEFT JOIN `Ledgers` supp ON supp.id = ct.supplier_ledger_id
        LEFT JOIN `JournalVoucher` jv ON jv.source_cancellation_ticket_id = ct.id
        WHERE ct.id = %s AND ct.company_id = %s
        ORDER BY jv.id
        """,
        [cid, company_id],
    )


@sp(CT, "GET_LINES")
def _ct_get_lines(p):
    return query(
        """
        SELECT cl.id, cl.original_ticket_line_id, cl.airline_code, cl.airline_name, cl.airline_category,
               cl.flight_no, cl.ticket_no, cl.passenger_name, cl.pax_type, cl.sector, cl.travel_date,
               cl.cabin, cl.travel_class, cl.fare_type,
               cl.basic_fare, cl.yq, cl.yr, cl.k3_tax, cl.tax_others, cl.seat, cl.meal, cl.baggage, cl.other_ssr,
               cl.disc_on, cl.disc_type, cl.disc_value, cl.tds_per, cl.pg_charges, cl.pg_charges_percentage,
               cl.markup, cl.addl_markup, cl.ssr_markup, cl.service_fee, cl.addl_service_fee, cl.ssr_service_fee, cl.gst_pct,
               cl.supp_comm_on, cl.supp_comm_type, cl.supp_comm_value, cl.supp_tds_per,
               cl.supp_markup, cl.supp_addl_markup, cl.supp_service_fee, cl.supp_addl_service_fee, cl.supp_gst_pct,
               cl.supplier_penalty, cl.cancellation_penalty, cl.agent_penalty,
               cl.cust_markup_reversal, cl.cust_addl_markup_reversal, cl.cust_ssr_markup_reversal,
               cl.supp_markup_reversal, cl.supp_addl_markup_reversal,
               cl.total_billed, cl.status, cl.office_id, cl.fop, cl.card_number,
               cl.supplier_ledger_id, supp.name AS supplier_name
        FROM `Cancellation_Al_TicketLines` cl
        LEFT JOIN `Ledgers` supp ON supp.id = cl.supplier_ledger_id
        WHERE cl.cancellation_ticket_id = %s
        ORDER BY cl.id
        """,
        [_p_int(p.get("Id"))],
    )


_CX_PENALTY_COLS = [
    "supplier_penalty", "cancellation_penalty", "agent_penalty",
    "cust_markup_reversal", "cust_addl_markup_reversal", "cust_ssr_markup_reversal",
    "supp_markup_reversal", "supp_addl_markup_reversal",
]

_CT_LINE_SCHEMA = [
    ("original_ticket_line_id", "int"),
    ("airline_code", "str", 200), ("airline_name", "str", 200),
    ("airline_category", "str", 5), ("flight_no", "str", 200),
    ("ticket_no", "str", 30), ("passenger_name", "str", 50),
    ("pax_type", "str", 10), ("sector", "str", 200), ("travel_date", "str", 200),
    ("cabin", "str", 200), ("travel_class", "str", 200), ("fare_type", "str", 300),
    ("basic_fare", "dec", 14, 2), ("yq", "dec", 14, 2), ("yr", "dec", 14, 2),
    ("k3_tax", "dec", 14, 2), ("tax_others", "dec", 14, 2), ("seat", "dec", 14, 2),
    ("meal", "dec", 14, 2), ("baggage", "dec", 14, 2), ("other_ssr", "dec", 14, 2),
    ("disc_on", "str", 20), ("disc_type", "str", 12), ("disc_value", "dec", 14, 2),
    ("tds_per", "dec", 5, 2), ("pg_charges", "dec", 14, 2), ("pg_charges_percentage", "dec", 5, 2),
    ("markup", "dec", 14, 2), ("addl_markup", "dec", 14, 2), ("ssr_markup", "dec", 14, 2),
    ("service_fee", "dec", 14, 2), ("addl_service_fee", "dec", 14, 2),
    ("ssr_service_fee", "dec", 14, 2), ("gst_pct", "dec", 5, 2), ("status", "str", 15),
    ("office_id", "str", 30), ("fop", "str", 20), ("card_number", "str", 40),
    ("supp_comm_on", "str", 20), ("supp_comm_type", "str", 12),
    ("supp_comm_value", "dec", 14, 2), ("supp_tds_per", "dec", 5, 2),
    ("supp_markup", "dec", 14, 2), ("supp_addl_markup", "dec", 14, 2),
    ("supp_service_fee", "dec", 14, 2), ("supp_addl_service_fee", "dec", 14, 2),
    ("supp_gst_pct", "dec", 5, 2), ("total_billed", "dec", 14, 2),
    ("supplier_penalty", "dec", 14, 2), ("cancellation_penalty", "dec", 14, 2),
    ("agent_penalty", "dec", 14, 2),
    ("cust_markup_reversal", "dec", 14, 2),
    ("cust_addl_markup_reversal", "dec", 14, 2),
    ("cust_ssr_markup_reversal", "dec", 14, 2),
    ("supp_markup_reversal", "dec", 14, 2),
    ("supp_addl_markup_reversal", "dec", 14, 2),
    ("supplier_name", "str", 150),
]

_CT_LINE_INSERT_COLS = [
    "original_ticket_line_id", "airline_code", "airline_name", "airline_category", "flight_no", "ticket_no",
    "passenger_name", "pax_type", "sector", "travel_date", "cabin", "travel_class", "fare_type", "basic_fare", "yq", "yr",
    "k3_tax", "tax_others", "seat", "meal", "baggage", "other_ssr", "disc_on", "disc_type", "disc_value", "tds_per",
    "pg_charges", "pg_charges_percentage", "markup", "addl_markup", "ssr_markup", "service_fee", "addl_service_fee",
    "ssr_service_fee", "gst_pct", "status", "office_id", "fop", "card_number", "supp_comm_on", "supp_comm_type",
    "supp_comm_value", "supp_tds_per", "supp_markup", "supp_addl_markup", "supp_service_fee", "supp_addl_service_fee",
    "supp_gst_pct",
] + _CX_PENALTY_COLS + ["total_billed"]

_CT_UPDATE_SCHEMA = [
    ("id", "int"),
    ("basic_fare", "dec", 14, 2), ("yq", "dec", 14, 2), ("yr", "dec", 14, 2),
    ("k3_tax", "dec", 14, 2), ("tax_others", "dec", 14, 2), ("seat", "dec", 14, 2),
    ("meal", "dec", 14, 2), ("baggage", "dec", 14, 2), ("other_ssr", "dec", 14, 2),
    ("disc_on", "str", 20), ("disc_type", "str", 12), ("disc_value", "dec", 14, 2),
    ("tds_per", "dec", 5, 2),
    ("markup", "dec", 14, 2), ("addl_markup", "dec", 14, 2),
    ("service_fee", "dec", 14, 2), ("addl_service_fee", "dec", 14, 2),
    ("supp_comm_on", "str", 20), ("supp_comm_type", "str", 12),
    ("supp_comm_value", "dec", 14, 2), ("supp_tds_per", "dec", 5, 2),
    ("supp_markup", "dec", 14, 2), ("supp_addl_markup", "dec", 14, 2),
    ("supp_service_fee", "dec", 14, 2), ("supp_addl_service_fee", "dec", 14, 2),
    ("supplier_penalty", "dec", 14, 2), ("cancellation_penalty", "dec", 14, 2),
    ("agent_penalty", "dec", 14, 2),
    ("cust_markup_reversal", "dec", 14, 2),
    ("cust_addl_markup_reversal", "dec", 14, 2),
    ("cust_ssr_markup_reversal", "dec", 14, 2),
    ("supp_markup_reversal", "dec", 14, 2),
    ("supp_addl_markup_reversal", "dec", 14, 2),
]

_CT_UPDATE_PLAIN_COLS = [
    "basic_fare", "yq", "yr", "k3_tax", "tax_others", "seat", "meal", "baggage", "other_ssr",
    "disc_on", "disc_type", "disc_value", "tds_per", "markup", "addl_markup", "service_fee", "addl_service_fee",
    "supp_comm_on", "supp_comm_type", "supp_comm_value", "supp_tds_per",
    "supp_markup", "supp_addl_markup", "supp_service_fee", "supp_addl_service_fee",
]


def _jv_guard(jv_total_debit, jv_total_credit):
    if jv_total_debit is None or jv_total_credit is None:
        return _err("Cancellation Journal Voucher totals are missing - nothing was saved.")
    if abs(jv_total_debit - jv_total_credit) > Decimal("0.01"):
        return _err(
            "Cancellation Journal Voucher does not balance (Debit " + _fmt_dec(jv_total_debit)
            + " <> Credit " + _fmt_dec(jv_total_credit) + ") - nothing was saved."
        )
    return None


def _next_alc(company_id):
    return query_one(
        "SELECT COUNT(*) AS n FROM `JournalVoucher` WHERE `company_id` = %s "
        "AND LOWER(TRIM(`category`)) = 'airline_cancellation'", [company_id]
    )["n"] + 1


def _insert_cx_jv(company_id, branch_name, voucher_date, narration, cx_id, debit, credit):
    now = _utcnow()
    execute(
        "INSERT INTO `JournalVoucher` (company_id, branch_name, voucher_type, voucher_date, narration, category, voucher_no, "
        "source_cancellation_ticket_id, total_debit, total_credit, lines_json, created_at, updated_at) "
        "VALUES (%s, %s, 'Tax Invoice', %s, %s, 'AIRLINE_CANCELLATION', %s, %s, %s, %s, '[]', %s, %s)",
        [company_id, branch_name if branch_name is not None else "Chennai Branch", voucher_date, narration,
         "ALC-" + str(_next_alc(company_id)), cx_id, debit, credit, now, now],
    )


@sp(CT, "SAVE")
def _ct_save(p):
    company_id = _p_int(p.get("CompanyId"))
    original_ticket_id = _p_int(p.get("OriginalTicketId"))
    customer_name = _p_str(p.get("CustomerName"), 150)
    supplier_name = _p_str(p.get("SupplierName"), 150)
    branch_name = _p_str(p.get("BranchName"), 100)
    invoice_number = _p_str(p.get("InvoiceNumber"), 20)
    invoice_date = _p_date(p.get("InvoiceDate"))
    invoice_type = _p_str(p.get("InvoiceType"), 100)
    booking_mode = _p_str(p.get("BookingMode"), 20)
    booking_type = _p_str(p.get("BookingType"), 30)
    booking_status = _p_str(p.get("BookingStatus"), 20)
    travel_type = _p_str(p.get("TravelType"), 20)
    user_name = _p_str(p.get("UserName"), 100)
    currency = _p_str(p.get("Currency"), 5)
    roe = _p_dec(p.get("Roe"), 10, 4)
    booking_given_by = _p_str(p.get("BookingGivenBy"), 25)
    cancellation_reference = _p_str(p.get("CancellationReference"), 30)
    cancellation_ref_date = _p_date(p.get("CancellationRefDate"))
    airline_pnr = _p_str(p.get("AirlinePnr"), 13)
    gds_pnr = _p_str(p.get("GdsPnr"), 13)
    office_id = _p_str(p.get("OfficeId"), 30)
    payment_mode = _p_str(p.get("PaymentMode"), 20)
    payment_gateway_ref = _p_str(p.get("PaymentGatewayRef"), 60)
    airline_category = _p_str(p.get("AirlineCategory"), 5)
    lines_json = p.get("LinesJson")
    jv_narration = _p_str(p.get("JvNarration"), 250)
    jv_total_debit = _p_dec(p.get("JvTotalDebit"), 16, 2)
    jv_total_credit = _p_dec(p.get("JvTotalCredit"), 16, 2)

    cust_ledger_id = _ledger_id(company_id, customer_name, "DEBTOR")
    if cust_ledger_id is None:
        return _err('"' + (customer_name or "") + '" is not a real customer ledger (Sundry Debtors).')
    supp_ledger_id = None
    if supplier_name is not None:
        supp_ledger_id = _ledger_id(company_id, supplier_name, "CREDITOR")
        if supp_ledger_id is None:
            return _err('"' + supplier_name + '" is not a real supplier ledger (Sundry Creditors).')

    if not query_one("SELECT 1 AS x FROM `AL_Tickets` WHERE `id` = %s AND `company_id` = %s",
                     [original_ticket_id, company_id]):
        return _err("Original ticket not found.")

    if query_one(
        "SELECT 1 AS x FROM `Cancellation_AL_Tickets` WHERE `company_id` = %s "
        "AND LOWER(TRIM(`invoice_number`)) = LOWER(TRIM(%s)) LIMIT 1", [company_id, invoice_number]
    ):
        return _err('Invoice Number "' + invoice_number + '" already exists.')
    if query_one(
        "SELECT 1 AS x FROM `Cancellation_AL_Tickets` WHERE `company_id` = %s "
        "AND LOWER(TRIM(`cancellation_reference`)) = LOWER(TRIM(%s)) LIMIT 1", [company_id, cancellation_reference]
    ):
        return _err('Cancellation Reference "' + cancellation_reference + '" already exists.')

    elems = _json_elems(lines_json)
    if _has_dup_ticket_no(elems):
        return _err("Duplicate Ticket Number within this submission.")

    dup = _first_existing_ticket_no("Cancellation_Al_TicketLines",
                                    [r["ticket_no"] for r in _openjson(elems, [("ticket_no", "str", 30)])])
    if dup is not None:
        return _err('Ticket Number "' + dup + '" already exists.')

    # Every line must reference a real original TicketLine belonging to this original ticket.
    pairs = _openjson(elems, [("original_ticket_line_id", "int"), ("ticket_no", "str", 30)])
    belongs = set()
    oids = sorted({j["original_ticket_line_id"] for j in pairs if j["original_ticket_line_id"] is not None})
    if oids and original_ticket_id is not None:
        belongs = {r["id"] for r in query(
            f"SELECT `id` FROM `AL_TicketLines` WHERE `ticket_id` = %s AND `id` IN ({_in(len(oids))})",
            [original_ticket_id] + oids)}
    bad = next((j for j in pairs if j["original_ticket_line_id"] not in belongs), None)
    # TOP 1 @BadOriginalTicketNo = j.ticket_no - only an error when that first bad line's ticket_no isn't NULL.
    if bad is not None and bad["ticket_no"] is not None:
        return _err("One or more lines reference an original ticket line that doesn't belong to this ticket.")

    # Already cancelled: the original line's own canceled flag, or an existing cancellation line on it.
    otl = {}
    if oids:
        for r in query(
            f"SELECT otl.`id`, otl.`ticket_no`, otl.`canceled`, "
            f"EXISTS (SELECT 1 FROM `Cancellation_Al_TicketLines` e WHERE e.`original_ticket_line_id` = otl.`id`) AS has_cx "
            f"FROM `AL_TicketLines` otl WHERE otl.`id` IN ({_in(len(oids))})", oids
        ):
            otl[r["id"]] = r
    already = _ordered_agg([
        otl[j["original_ticket_line_id"]]["ticket_no"] for j in pairs
        if j["original_ticket_line_id"] in otl
        and (otl[j["original_ticket_line_id"]]["canceled"] or otl[j["original_ticket_line_id"]]["has_cx"])
    ])
    if already is not None:
        return _err("Ticket No. " + already + " has already been cancelled.")

    rpairs = _openjson(elems, [("reschedule_line_id", "int")])
    rl = _by_id("Rescheduled_Al_TicketLines", "`ticket_no`, `canceled`", [j["reschedule_line_id"] for j in rpairs])
    already_r = _ordered_agg([
        rl[j["reschedule_line_id"]]["ticket_no"] for j in rpairs
        if j["reschedule_line_id"] in rl and rl[j["reschedule_line_id"]]["canceled"]
    ])
    if already_r is not None:
        return _err("Ticket No. " + already_r + " has already been cancelled.")

    guard = _jv_guard(jv_total_debit, jv_total_credit)
    if guard:
        return guard

    def work():
        now = _utcnow()
        _, result_id = execute(
            """
            INSERT INTO `Cancellation_AL_Tickets`
                (company_id, branch_name, original_ticket_id, invoice_number, invoice_date, invoice_type, booking_mode, booking_type, booking_status,
                 customer_ledger_id, supplier_ledger_id, travel_type, user_name, currency, roe, booking_given_by,
                 cancellation_reference, cancellation_ref_date, airline_pnr, gds_pnr, office_id, payment_mode, payment_gateway_ref,
                 airline_category, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [company_id, branch_name, original_ticket_id, invoice_number, invoice_date, invoice_type,
             booking_mode if booking_mode is not None else "Manual", booking_type, booking_status,
             cust_ledger_id, supp_ledger_id, travel_type, user_name, currency if currency is not None else "INR",
             roe if roe is not None else Decimal(1), booking_given_by,
             cancellation_reference, cancellation_ref_date, airline_pnr, gds_pnr, office_id, payment_mode,
             payment_gateway_ref, airline_category, now, now],
        )

        cols = ["cancellation_ticket_id"] + _CT_LINE_INSERT_COLS + ["supplier_ledger_id", "created_at", "updated_at"]
        ins_sql = (f"INSERT INTO `Cancellation_Al_TicketLines` ({', '.join('`%s`' % c for c in cols)}) "
                   f"VALUES ({_in(len(cols))})")
        for j in _openjson(elems, _CT_LINE_SCHEMA):
            vals = dict(j)
            if vals["status"] is None:
                vals["status"] = "ISSUED"
            for c in _CX_PENALTY_COLS:
                if vals[c] is None:
                    vals[c] = Decimal("0.00")
            supp_id = _ledger_id_subquery(company_id, j["supplier_name"])
            execute(ins_sql, [result_id] + [vals[c] for c in _CT_LINE_INSERT_COLS] + [supp_id, now, now])

        # Mark the ORIGINAL ticket line(s) cancelled.
        set_otl = sorted({j["original_ticket_line_id"] for j in pairs if j["original_ticket_line_id"] is not None})
        if set_otl:
            execute(f"UPDATE `AL_TicketLines` SET `canceled` = 1 WHERE `id` IN ({_in(len(set_otl))})", set_otl)
        # Also the specific RESCHEDULE line, when raised against an already-rescheduled passenger.
        set_rl = sorted({j["reschedule_line_id"] for j in rpairs if j["reschedule_line_id"] is not None})
        if set_rl:
            execute(f"UPDATE `Rescheduled_Al_TicketLines` SET `canceled` = 1 WHERE `id` IN ({_in(len(set_rl))})", set_rl)

        _insert_cx_jv(company_id, branch_name, invoice_date, jv_narration, result_id, jv_total_debit, jv_total_credit)
        return result_id

    result_id, err = _run_try(work)
    if err:
        return err
    ids = [str(r["id"]) for r in query(
        "SELECT `id` FROM `Cancellation_Al_TicketLines` WHERE `cancellation_ticket_id` = %s ORDER BY `id`", [result_id])]
    line_ids = ",".join(ids) if ids else None
    return [
        {"id": result_id, "line_ids": line_ids, "voucher_id": v["id"], "voucher_no": v["voucher_no"], "status": "Success"}
        for v in query("SELECT `id`, `voucher_no` FROM `JournalVoucher` WHERE `source_cancellation_ticket_id` = %s ORDER BY `id`",
                       [result_id])
    ]


@sp(CT, "UPDATE")
def _ct_update(p):
    cid = _p_int(p.get("Id"))
    company_id = _p_int(p.get("CompanyId"))
    invoice_number = _p_str(p.get("InvoiceNumber"), 20)
    invoice_date = _p_date(p.get("InvoiceDate"))
    invoice_type = _p_str(p.get("InvoiceType"), 100)
    user_name = _p_str(p.get("UserName"), 100)
    payment_mode = _p_str(p.get("PaymentMode"), 20)
    payment_gateway_ref = _p_str(p.get("PaymentGatewayRef"), 60)
    cancellation_reference = _p_str(p.get("CancellationReference"), 30)
    cancellation_ref_date = _p_date(p.get("CancellationRefDate"))
    lines_json = p.get("LinesJson")
    jv_narration = _p_str(p.get("JvNarration"), 250)
    jv_total_debit = _p_dec(p.get("JvTotalDebit"), 16, 2)
    jv_total_credit = _p_dec(p.get("JvTotalCredit"), 16, 2)

    if not query_one("SELECT 1 AS x FROM `Cancellation_AL_Tickets` WHERE `id` = %s AND `company_id` = %s", [cid, company_id]):
        return _err("Cancellation not found.")
    if invoice_number is not None and query_one(
        "SELECT 1 AS x FROM `Cancellation_AL_Tickets` WHERE `company_id` = %s "
        "AND LOWER(TRIM(`invoice_number`)) = LOWER(TRIM(%s)) AND `id` <> %s LIMIT 1", [company_id, invoice_number, cid]
    ):
        return _err('Invoice Number "' + invoice_number + '" already exists.')
    if cancellation_reference is not None and query_one(
        "SELECT 1 AS x FROM `Cancellation_AL_Tickets` WHERE `company_id` = %s "
        "AND LOWER(TRIM(`cancellation_reference`)) = LOWER(TRIM(%s)) AND `id` <> %s LIMIT 1",
        [company_id, cancellation_reference, cid]
    ):
        return _err('Cancellation Reference "' + cancellation_reference + '" already exists.')

    guard = _jv_guard(jv_total_debit, jv_total_credit)
    if guard:
        return guard

    def work():
        now = _utcnow()
        execute(
            """
            UPDATE `Cancellation_AL_Tickets`
            SET invoice_number = IFNULL(%s, invoice_number),
                invoice_date = IFNULL(%s, invoice_date),
                invoice_type = %s,
                user_name = %s,
                payment_mode = %s,
                payment_gateway_ref = %s,
                cancellation_reference = IFNULL(%s, cancellation_reference),
                cancellation_ref_date = IFNULL(%s, cancellation_ref_date),
                updated_at = %s
            WHERE id = %s
            """,
            [invoice_number, invoice_date, invoice_type, user_name, payment_mode, payment_gateway_ref,
             cancellation_reference, cancellation_ref_date, now, cid],
        )

        set_sql = ", ".join(f"`{c}` = %s" for c in _CT_UPDATE_PLAIN_COLS + _CX_PENALTY_COLS + ["updated_at"])
        upd_sql = f"UPDATE `Cancellation_Al_TicketLines` SET {set_sql} WHERE `id` = %s AND `cancellation_ticket_id` = %s"
        for j in _openjson(_json_elems(lines_json), _CT_UPDATE_SCHEMA):
            if j["id"] is None:
                continue
            pen = [j[c] if j[c] is not None else Decimal("0.00") for c in _CX_PENALTY_COLS]
            execute(upd_sql, [j[c] for c in _CT_UPDATE_PLAIN_COLS] + pen + [now, j["id"], cid])

        hdr = query_one("SELECT `invoice_date`, `branch_name` FROM `Cancellation_AL_Tickets` WHERE `id` = %s", [cid])
        cx_invoice_date = hdr["invoice_date"] if hdr else None
        cx_branch_name = hdr["branch_name"] if hdr else None
        if query_one("SELECT 1 AS x FROM `JournalVoucher` WHERE `source_cancellation_ticket_id` = %s LIMIT 1", [cid]):
            execute(
                "UPDATE `JournalVoucher` SET `voucher_date` = %s, `narration` = %s, `total_debit` = %s, "
                "`total_credit` = %s, `updated_at` = %s WHERE `source_cancellation_ticket_id` = %s",
                [cx_invoice_date, jv_narration, jv_total_debit, jv_total_credit, _utcnow(), cid],
            )
        else:
            _insert_cx_jv(company_id, cx_branch_name, cx_invoice_date, jv_narration, cid, jv_total_debit, jv_total_credit)

    _, err = _run_try(work)
    if err:
        return err
    return [
        {"id": cid, "voucher_id": v["id"], "voucher_no": v["voucher_no"], "status": "Success"}
        for v in query("SELECT `id`, `voucher_no` FROM `JournalVoucher` WHERE `source_cancellation_ticket_id` = %s ORDER BY `id`",
                       [cid])
    ]
