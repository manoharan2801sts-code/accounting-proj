"""
dbo.sp_Ticket and dbo.sp_Voucher (backend/sp_reference/StoredProcedures.sql)
ported to Python + MySQL/TiDB.

sp_Ticket : LIST, LIST_INVOICE_NUMBERS_BY_TYPE, LIST_FOR_BALANCE, GET_HEADER,
            GET_LINES, SAVE (create + update, auto-posted JournalVoucher AL-n)
sp_Voucher: LIST, GET_BY_ID, SAVE (manual vouchers, VCH-n)

Notes on fidelity:
- SQL Server's default collation compares strings case-insensitively and
  ignores trailing spaces. Every text equality the T-SQL does is written
  here as LOWER(RTRIM(col)) COLLATE utf8mb4_bin = LOWER(RTRIM(value)), which
  behaves the same on local MySQL (utf8mb4_unicode_ci tables) and on TiDB
  (utf8mb4_bin by default).
- The computed_* columns of LIST/GET_LINES are evaluated in Python with
  Decimal and given the scale SQL Server's decimal type rules produce
  (computed_tds / computed_supp_tds are rounded to 6 dp there, because the
  product's precision exceeds 38).
- OPENJSON ... WITH (...) column types are applied by _jcol(); parameters
  are coerced to their declared T-SQL types (NVARCHAR(n) truncation,
  DECIMAL(p,s) rounding, DATE, INT) by the _p_* helpers, as EXEC would.
"""
import datetime
import json
import re
from decimal import Decimal, ROUND_HALF_UP, localcontext

from django.db import transaction

from . import sp, query, query_one, execute, SPThrow, bits, to_date


# ---------------------------------------------------------------------------
# Generic T-SQL emulation helpers
# ---------------------------------------------------------------------------

def _err(message):
    """`SELECT NULL AS id, 'Error' AS status, <msg> AS error`."""
    return [{"id": None, "status": "Error", "error": message}]


class _Rollback(Exception):
    """ROLLBACK TRAN + SELECT <error row> + RETURN inside a transaction."""

    def __init__(self, rows):
        super().__init__("rollback")
        self.rows = rows


def _now():
    """SYSUTCDATETIME() - stored as naive UTC (settings.USE_TZ = True)."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _db_message(exc):
    """ERROR_MESSAGE() equivalent for an exception raised inside BEGIN TRY."""
    args = getattr(exc, "args", ())
    if len(args) >= 2 and isinstance(args[0], int):
        return str(args[1])
    return str(exc)


def _norm(s):
    """Key for SQL Server's case-insensitive, trailing-space-insensitive equality."""
    return None if s is None else str(s).rstrip(" ").lower()


def _ci(col):
    """SQL fragment: case/trailing-space-insensitive equality of `col` with one %s param."""
    return f"LOWER(RTRIM({col})) COLLATE utf8mb4_bin = LOWER(RTRIM(%s))"


def _ci_lit(col, literal):
    """SQL fragment: CI equality of `col` with a fixed (lower-case, safe) literal."""
    return f"LOWER(RTRIM({col})) COLLATE utf8mb4_bin = '{literal.lower()}'"


_INT_RE = re.compile(r"^\s*[+-]?\d+\s*$")
_DEC_RE = re.compile(r"^\s*[+-]?(\d+\.?\d*|\.\d+)\s*$")


def _int_range(v, raw):
    if not (-2147483648 <= v <= 2147483647):
        raise SPThrow(f"The conversion of the nvarchar value '{raw}' overflowed an int column.")
    return v


def _p_int(v):
    """An INT parameter."""
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, (float, Decimal)):
        return int(v)  # numeric -> int truncates
    s = str(v)
    if s.strip() == "":
        return 0  # CAST('' AS INT) = 0
    if _INT_RE.match(s):
        return _int_range(int(s.strip()), s)
    raise SPThrow("Error converting data type nvarchar to int.")


def _p_str(v, n=None):
    """An NVARCHAR(n) parameter - silently truncated to n characters."""
    if v is None:
        return None
    s = v if isinstance(v, str) else str(v)
    return s if n is None else s[:n]


def _quantize(d, p, s, source="numeric"):
    with localcontext() as ctx:
        ctx.prec = 80
        q = d.quantize(Decimal(1).scaleb(-s), rounding=ROUND_HALF_UP)
        if q.adjusted() >= p - s and q != 0:
            raise SPThrow(f"Arithmetic overflow error converting {source} to data type numeric.")
        return q


def _p_dec(v, p, s):
    """A DECIMAL(p,s) parameter."""
    if v is None:
        return None
    if isinstance(v, bool):
        return _quantize(Decimal(int(v)), p, s)
    if isinstance(v, Decimal):
        return _quantize(v, p, s)
    if isinstance(v, int):
        return _quantize(Decimal(v), p, s)
    if isinstance(v, float):
        return _quantize(Decimal(repr(v)), p, s, "float")
    st = str(v)
    if not _DEC_RE.match(st):
        raise SPThrow("Error converting data type nvarchar to numeric.")
    return _quantize(Decimal(st.strip()), p, s, "nvarchar")


def _p_date(v):
    """A DATE parameter."""
    if isinstance(v, str) and v.strip() == "":
        return datetime.date(1900, 1, 1)  # CAST('' AS DATE)
    try:
        return to_date(v)
    except (ValueError, TypeError):
        raise SPThrow("Conversion failed when converting date and/or time from character string.")


# --- OPENJSON ---------------------------------------------------------------

class _JNum(str):
    """A JSON number, kept as its literal text (as OPENJSON sees it)."""


def _first_key_wins(pairs):
    d = {}
    for k, v in pairs:
        if k not in d:  # JSON path lookups return the first matching property
            d[k] = v
    return d


def _parse_json(text):
    try:
        return json.loads(text, parse_float=_JNum, parse_int=_JNum, object_pairs_hook=_first_key_wins)
    except (ValueError, TypeError):
        raise SPThrow("JSON text is not properly formatted.")


def _openjson(text):
    """OPENJSON(@json) default schema -> [(key, value), ...]; NULL -> no rows."""
    if text is None:
        return []
    doc = _parse_json(text if isinstance(text, str) else str(text))
    if isinstance(doc, list):
        return list(enumerate(doc))
    if isinstance(doc, dict):
        return list(doc.items())
    raise SPThrow("JSON text is not properly formatted.")


def _jcol(item, key, typ):
    """
    One OPENJSON WITH(...) column: `typ` is ("nv", n) / ("dec", p, s) / ("int",).
    Non-object rows, missing keys, JSON null and object/array values -> NULL.
    """
    if not isinstance(item, dict):
        return None
    v = item.get(key)
    if v is None or isinstance(v, (dict, list)):
        return None
    kind = typ[0]
    if kind == "nv":
        s = ("true" if v else "false") if isinstance(v, bool) else str(v)
        return s[:typ[1]]
    if isinstance(v, bool):
        raise SPThrow("Error converting data type nvarchar to numeric." if kind == "dec"
                      else f"Conversion failed when converting the nvarchar value '{'true' if v else 'false'}' to data type int.")
    if kind == "dec":
        if isinstance(v, _JNum):
            try:
                d = Decimal(str(v))
            except Exception:
                raise SPThrow("Error converting data type nvarchar to numeric.")
            return _quantize(d, typ[1], typ[2], "nvarchar")
        if not _DEC_RE.match(v):
            raise SPThrow("Error converting data type nvarchar to numeric.")
        return _quantize(Decimal(v.strip()), typ[1], typ[2], "nvarchar")
    if kind == "int":
        if _INT_RE.match(v):
            return _int_range(int(v.strip()), v)
        if v.strip() == "" and not isinstance(v, _JNum):
            return 0
        raise SPThrow(f"Conversion failed when converting the nvarchar value '{v}' to data type int.")
    raise ValueError(kind)


def _json_value_text(item, key):
    """JSON_VALUE(<OPENJSON [value]>, '$.key') in lax mode -> text or NULL."""
    if isinstance(item, str) and not isinstance(item, _JNum):
        item = _parse_json(item)  # a string row's [value] is raw text, parsed as JSON
    if not isinstance(item, dict):
        return None
    v = item.get(key)
    if v is None or isinstance(v, (dict, list)):
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _try_cast_int(text):
    """TRY_CAST(<nvarchar> AS INT)."""
    if text is None:
        return None
    if text.strip(" ") == "":
        return 0
    if _INT_RE.match(text):
        v = int(text.strip())
        return v if -2147483648 <= v <= 2147483647 else None
    return None


def _forjson_str(s):
    out = ['"']
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "/":
            out.append("\\/")
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\f":
            out.append("\\f")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _forjson_val(v):
    if isinstance(v, str):
        return _forjson_str(v)
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, Decimal):
        return format(v, "f")
    return str(v)


def _for_json_path(rows):
    """FOR JSON PATH: compact array of objects, NULL-valued properties omitted; no rows -> NULL."""
    if not rows:
        return None
    objs = []
    for r in rows:
        objs.append("{" + ",".join(f"{_forjson_str(k)}:{_forjson_val(v)}" for k, v in r.items() if v is not None) + "}")
    return "[" + ",".join(objs) + "]"


# ---------------------------------------------------------------------------
# dbo.sp_Ticket
# ---------------------------------------------------------------------------

def _dsum(*xs):
    if any(x is None for x in xs):
        return None
    return sum(xs, Decimal(0))


def _dmul(a, b):
    return None if a is None or b is None else a * b


def _ddiv100(a):
    return None if a is None else a / Decimal(100)


def _comm_base(r, on):
    on = _norm(on)
    b, yq, yr = r["basic_fare"], r["yq"], r["yr"]
    if on == "basic":
        return b
    if on == "basic + yq":
        return _dsum(b, yq)
    if on == "basic + yr":
        return _dsum(b, yr)
    if on == "basic + yq + yr":
        return _dsum(b, yq, yr)
    if on == "gross":
        return _dsum(b, yq, yr, r["k3_tax"], r["tax_others"], r["seat"], r["meal"], r["baggage"], r["other_ssr"])
    return Decimal(0)


def _comm(r, typ, on, value):
    typ = _norm(typ)
    if typ == "percentage":
        return _dmul(_comm_base(r, on), _ddiv100(value))
    if typ == "flat":
        return value
    return Decimal(0)


def _scale(v, s):
    if v is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 80
        return v.quantize(Decimal(1).scaleb(-s), rounding=ROUND_HALF_UP)


def _fill_computed(r):
    """
    The six computed_* columns of LIST/GET_LINES, typed as SQL Server types
    them: discount/supp_commission DECIMAL(38,6); tds/supp_tds DECIMAL(38,6)
    (rounded - the exact product would need scale 12 and precision 48);
    gst DECIMAL(26,8); supp_gst DECIMAL(25,8). Consumes the hidden
    _gst_svc/_gst_addlsvc/_gst_ssrsvc columns.
    """
    g_svc = r.pop("_gst_svc")
    g_addl = r.pop("_gst_addlsvc")
    g_ssr = r.pop("_gst_ssrsvc")
    g_suppsvc = r.pop("_gst_suppsvc")
    g_suppaddl = r.pop("_gst_suppaddlsvc")
    with localcontext() as ctx:
        ctx.prec = 80
        disc = _comm(r, r["disc_type"], r["disc_on"], r["disc_value"])
        supp = _comm(r, r["supp_comm_type"], r["supp_comm_on"], r["supp_comm_value"])
        r["computed_discount"] = _scale(disc, 6)
        r["computed_tds"] = _scale(_dmul(_scale(disc, 6), _ddiv100(r["tds_per"])), 6)
        z = Decimal(0)
        r["computed_gst"] = _scale(_dsum(
            _ddiv100(_dmul(r["service_fee"], g_svc if g_svc is not None else z)),
            _ddiv100(_dmul(r["addl_service_fee"], g_addl if g_addl is not None else z)),
            _ddiv100(_dmul(r["ssr_service_fee"], g_ssr if g_ssr is not None else z)),
        ), 8)
        r["computed_supp_commission"] = _scale(supp, 6)
        r["computed_supp_tds"] = _scale(_dmul(_scale(supp, 6), _ddiv100(r["supp_tds_per"])), 6)
        # 8.10.26 build: each Supplier fee times its OWN mapped ledger's GST%
        # (Master Mapping), no longer the flat supp_gst_pct.
        r["computed_supp_gst"] = _scale(_dsum(
            _ddiv100(_dmul(r["supp_service_fee"], g_suppsvc if g_suppsvc is not None else z)),
            _ddiv100(_dmul(r["supp_addl_service_fee"], g_suppaddl if g_suppaddl is not None else z)),
        ), 8)
    return r


_COMPUTED_PLACEHOLDERS = (
    "NULL AS computed_discount, NULL AS computed_tds, NULL AS computed_gst, "
    "NULL AS computed_supp_commission, NULL AS computed_supp_tds, NULL AS computed_supp_gst"
)

_GST_JOINS = f"""
    LEFT JOIN `MasterMapping` mm_svc ON mm_svc.company_id = t.company_id AND {_ci_lit('mm_svc.product_type', 'Airline')} AND {_ci_lit('mm_svc.field_name', 'Service Fee A/c')}
    LEFT JOIN `Ledgers` l_svc ON l_svc.id = mm_svc.ledger_id
    LEFT JOIN `MasterMapping` mm_addlsvc ON mm_addlsvc.company_id = t.company_id AND {_ci_lit('mm_addlsvc.product_type', 'Airline')} AND {_ci_lit('mm_addlsvc.field_name', 'Addl Service Fee A/c')}
    LEFT JOIN `Ledgers` l_addlsvc ON l_addlsvc.id = mm_addlsvc.ledger_id
    LEFT JOIN `MasterMapping` mm_ssrsvc ON mm_ssrsvc.company_id = t.company_id AND {_ci_lit('mm_ssrsvc.product_type', 'Airline')} AND {_ci_lit('mm_ssrsvc.field_name', 'SSR Service Fee A/c')}
    LEFT JOIN `Ledgers` l_ssrsvc ON l_ssrsvc.id = mm_ssrsvc.ledger_id
    LEFT JOIN `MasterMapping` mm_suppsvc ON mm_suppsvc.company_id = t.company_id AND {_ci_lit('mm_suppsvc.product_type', 'Airline')} AND {_ci_lit('mm_suppsvc.field_name', 'Supplier Service Fee A/c')}
    LEFT JOIN `Ledgers` l_suppsvc ON l_suppsvc.id = mm_suppsvc.ledger_id
    LEFT JOIN `MasterMapping` mm_suppaddlsvc ON mm_suppaddlsvc.company_id = t.company_id AND {_ci_lit('mm_suppaddlsvc.product_type', 'Airline')} AND {_ci_lit('mm_suppaddlsvc.field_name', 'Supplier Addl Service Fee A/c')}
    LEFT JOIN `Ledgers` l_suppaddlsvc ON l_suppaddlsvc.id = mm_suppaddlsvc.ledger_id
"""
_GST_HIDDEN = ("l_svc.gst_percentage AS _gst_svc, l_addlsvc.gst_percentage AS _gst_addlsvc, l_ssrsvc.gst_percentage AS _gst_ssrsvc, "
               "l_suppsvc.gst_percentage AS _gst_suppsvc, l_suppaddlsvc.gst_percentage AS _gst_suppaddlsvc")


@sp("dbo.sp_Ticket", "LIST")
def ticket_list(p):
    cid = _p_int(p.get("CompanyId"))
    rows = query(f"""
        SELECT
            tl.id, t.id AS ticket_id,
            COALESCE(t.airline_pnr, t.gds_pnr, t.booking_reference) AS pnr,
            tl.ticket_no, tl.airline_name, tl.airline_code, tl.flight_no, tl.passenger_name, tl.pax_type,
            tl.sector, t.invoice_date AS issue_date, tl.travel_date,
            tl.basic_fare, tl.markup, tl.total_billed, tl.status,
            t.invoice_number, t.invoice_date, t.invoice_type, t.booking_mode, t.booking_type,
            t.booking_status, cust.name AS customer_name,
            t.travel_type, t.user_name, t.currency, t.roe, t.booking_given_by, t.payment_mode, tl.airline_category,
            t.booking_reference, t.booking_ref_date, t.airline_pnr, t.gds_pnr, supp.name AS supplier_name,
            tl.office_id, tl.fop, tl.card_number,
            tl.yq, tl.yr, tl.k3_tax, tl.tax_others, tl.seat, tl.meal, tl.baggage, tl.other_ssr,
            tl.disc_on, tl.disc_type, tl.disc_value, tl.tds_per,
            tl.addl_markup, tl.ssr_markup, tl.service_fee, tl.addl_service_fee, tl.ssr_service_fee, tl.gst_pct,
            tl.supp_comm_on, tl.supp_comm_type, tl.supp_comm_value, tl.supp_tds_per,
            tl.supp_markup, tl.supp_addl_markup, tl.supp_service_fee, tl.supp_addl_service_fee,
            {_COMPUTED_PLACEHOLDERS},
            tl.supp_gst_pct,
            {_GST_HIDDEN}
        FROM `AL_TicketLines` tl
        INNER JOIN `AL_Tickets` t ON t.id = tl.ticket_id
        INNER JOIN `Ledgers` cust ON cust.id = t.customer_ledger_id
        LEFT JOIN `Ledgers` supp ON supp.id = tl.supplier_ledger_id
        {_GST_JOINS}
        WHERE t.company_id = %s
        ORDER BY tl.id DESC, mm_svc.id, mm_addlsvc.id, mm_ssrsvc.id, mm_suppsvc.id, mm_suppaddlsvc.id
    """, [cid])
    return [_fill_computed(r) for r in rows]


@sp("dbo.sp_Ticket", "LIST_INVOICE_NUMBERS_BY_TYPE")
def ticket_list_invoice_numbers_by_type(p):
    cid = _p_int(p.get("CompanyId"))
    inv_type = _p_str(p.get("InvoiceType"), 100)
    from_date = _p_date(p.get("FromDate"))
    rows = []
    for table in ("AL_Tickets", "Rescheduled_Al_Ticket"):
        rows += query(f"""
            SELECT invoice_number, invoice_date FROM `{table}`
            WHERE company_id = %s AND {_ci('invoice_type')}
              AND (%s IS NULL OR invoice_date >= %s)
            ORDER BY id
        """, [cid, inv_type, from_date, from_date])
    return rows


@sp("dbo.sp_Ticket", "LIST_FOR_BALANCE")
def ticket_list_for_balance(p):
    cid = _p_int(p.get("CompanyId"))
    as_of = _p_date(p.get("AsOfDate"))
    from_date = _p_date(p.get("FromDate"))
    return query("""
        SELECT
            t.id AS ticket_id, t.company_id, cust.id AS customer_id, cust.name AS customer_name, cust.state_name AS customer_state_name,
            t.booking_reference, t.airline_pnr, t.payment_mode, t.payment_gateway_ref, t.invoice_date, t.booking_ref_date, t.branch_name,
            t.office_id AS ticket_office_id, t.invoice_number, v.voucher_no,
            tl.id AS line_id, tl.airline_code, tl.airline_name, tl.airline_category, tl.flight_no, tl.ticket_no, tl.passenger_name, tl.pax_type,
            tl.sector, tl.travel_date, tl.cabin, tl.travel_class, tl.fare_type,
            tl.basic_fare, tl.yq, tl.yr, tl.k3_tax, tl.tax_others, tl.seat, tl.meal, tl.baggage, tl.other_ssr,
            tl.disc_on, tl.disc_type, tl.disc_value, tl.tds_per, tl.pg_charges, tl.pg_charges_percentage,
            tl.markup, tl.addl_markup, tl.ssr_markup, tl.service_fee, tl.addl_service_fee, tl.ssr_service_fee, tl.gst_pct,
            tl.status, tl.office_id, tl.fop, tl.card_number,
            tl.supp_comm_on, tl.supp_comm_type, tl.supp_comm_value, tl.supp_tds_per,
            tl.supp_markup, tl.supp_addl_markup, tl.supp_service_fee, tl.supp_addl_service_fee, tl.supp_gst_pct,
            tl.total_billed, tl.supplier_ledger_id, supp.name AS supplier_name
        FROM `AL_Tickets` t
        INNER JOIN `Ledgers` cust ON cust.id = t.customer_ledger_id
        INNER JOIN `AL_TicketLines` tl ON tl.ticket_id = t.id
        LEFT JOIN `Ledgers` supp ON supp.id = tl.supplier_ledger_id
        LEFT JOIN `JournalVoucher` v ON v.source_ticket_id = t.id
        WHERE t.company_id = %s
          AND (%s IS NULL OR t.invoice_date <= %s)
          AND (%s IS NULL OR t.invoice_date >= %s)
        ORDER BY t.id, tl.id, v.id
    """, [cid, as_of, as_of, from_date, from_date])


@sp("dbo.sp_Ticket", "GET_HEADER")
def ticket_get_header(p):
    tid = _p_int(p.get("Id"))
    cid = _p_int(p.get("CompanyId"))
    if not query_one("SELECT 1 AS x FROM `AL_Tickets` WHERE id = %s AND company_id = %s", [tid, cid]):
        return _err("Ticket not found.")
    return query("""
        SELECT t.id, t.invoice_number, t.invoice_date, t.invoice_type, t.booking_mode, t.booking_type,
               t.booking_status, cust.name AS customer_name, t.travel_type, t.user_name, t.currency, t.roe,
               t.booking_given_by, t.booking_reference, t.booking_ref_date, t.airline_pnr, t.gds_pnr,
               supp.name AS supplier_name, t.office_id, t.payment_mode, t.payment_gateway_ref,
               t.airline_category, t.branch_name, 'Success' AS status
        FROM `AL_Tickets` t
        INNER JOIN `Ledgers` cust ON cust.id = t.customer_ledger_id
        LEFT JOIN `Ledgers` supp ON supp.id = t.supplier_ledger_id
        WHERE t.id = %s AND t.company_id = %s
    """, [tid, cid])


@sp("dbo.sp_Ticket", "GET_LINES")
def ticket_get_lines(p):
    tid = _p_int(p.get("Id"))
    rows = query(f"""
        SELECT tl.id, tl.rescheduled, tl.canceled,
               tl.airline_code, tl.airline_name, tl.airline_category, tl.flight_no, tl.ticket_no,
               tl.passenger_name, tl.pax_type, tl.sector, tl.travel_date, tl.cabin, tl.travel_class, tl.fare_type,
               tl.basic_fare, tl.yq, tl.yr, tl.k3_tax, tl.tax_others, tl.seat, tl.meal, tl.baggage, tl.other_ssr,
               tl.disc_on, tl.disc_type, tl.disc_value, tl.tds_per, tl.pg_charges, tl.pg_charges_percentage,
               tl.markup, tl.addl_markup, tl.ssr_markup, tl.service_fee, tl.addl_service_fee, tl.ssr_service_fee,
               tl.gst_pct, tl.total_billed, tl.status, tl.office_id, tl.fop, tl.card_number,
               tl.supp_comm_on, tl.supp_comm_type, tl.supp_comm_value, tl.supp_tds_per,
               tl.supp_markup, tl.supp_addl_markup, tl.supp_service_fee, tl.supp_addl_service_fee, tl.supp_gst_pct,
               ls.name AS supplier_name,
               {_COMPUTED_PLACEHOLDERS},
               {_GST_HIDDEN}
        FROM `AL_TicketLines` tl
        INNER JOIN `AL_Tickets` t ON t.id = tl.ticket_id
        LEFT JOIN `Ledgers` ls ON ls.id = tl.supplier_ledger_id
        {_GST_JOINS}
        WHERE tl.ticket_id = %s
        ORDER BY tl.id, mm_svc.id, mm_addlsvc.id, mm_ssrsvc.id, mm_suppsvc.id, mm_suppaddlsvc.id
    """, [tid])
    return [bits(_fill_computed(r), "rescheduled", "canceled") for r in rows]


# OPENJSON(@LinesJson) WITH (...) schema of sp_Ticket SAVE's MERGE/INSERT.
_NV = lambda n: ("nv", n)  # noqa: E731
_D142 = ("dec", 14, 2)
_D52 = ("dec", 5, 2)
_LINE_SCHEMA = [
    ("airline_code", _NV(200)), ("airline_name", _NV(200)), ("airline_category", _NV(5)), ("flight_no", _NV(200)),
    ("ticket_no", _NV(30)), ("passenger_name", _NV(50)), ("pax_type", _NV(10)), ("sector", _NV(200)),
    ("travel_date", _NV(200)), ("cabin", _NV(200)), ("travel_class", _NV(200)), ("fare_type", _NV(300)),
    ("basic_fare", _D142), ("yq", _D142), ("yr", _D142), ("k3_tax", _D142), ("tax_others", _D142),
    ("seat", _D142), ("meal", _D142), ("baggage", _D142), ("other_ssr", _D142),
    ("disc_on", _NV(20)), ("disc_type", _NV(12)), ("disc_value", _D142), ("tds_per", _D52),
    ("pg_charges", _D142), ("pg_charges_percentage", _D52),
    ("markup", _D142), ("addl_markup", _D142), ("ssr_markup", _D142),
    ("service_fee", _D142), ("addl_service_fee", _D142), ("ssr_service_fee", _D142), ("gst_pct", _D52),
    ("status", _NV(15)), ("office_id", _NV(30)), ("fop", _NV(20)), ("card_number", _NV(40)),
    ("supp_comm_on", _NV(20)), ("supp_comm_type", _NV(12)), ("supp_comm_value", _D142), ("supp_tds_per", _D52),
    ("supp_markup", _D142), ("supp_addl_markup", _D142), ("supp_service_fee", _D142),
    ("supp_addl_service_fee", _D142), ("supp_gst_pct", _D52), ("total_billed", _D142),
    ("supplier_name", _NV(150)),
]
# Line columns written by MERGE UPDATE / INSERT, in the T-SQL INSERT column order
# (ticket_no is only written on INSERT; status/supplier_ledger_id are special-cased).
_LINE_DATA_COLS = [c for c, _ in _LINE_SCHEMA if c not in ("supplier_name",)]


def _ledger_id(cid, name, category):
    """`SELECT @X = id FROM Ledgers WHERE company_id=@C AND name=@N AND ledger_category=...` (last row wins)."""
    if name is None:
        return None
    row = query_one(
        f"SELECT id FROM `Ledgers` WHERE company_id = %s AND {_ci('name')} AND {_ci_lit('ledger_category', category)} "
        "ORDER BY id DESC LIMIT 1",
        [cid, name],
    )
    return row["id"] if row else None


def _ledger_subquery(cid, name, category, cache):
    """Scalar subquery `(SELECT id FROM Ledgers WHERE ...)` - more than one row is an error."""
    if name is None:
        return None
    key = _norm(name)
    if key not in cache:
        rows = query(
            f"SELECT id FROM `Ledgers` WHERE company_id = %s AND {_ci('name')} AND {_ci_lit('ledger_category', category)} ORDER BY id",
            [cid, name],
        )
        if len(rows) > 1:
            raise SPThrow("Subquery returned more than 1 value. This is not permitted when the subquery follows "
                          "=, !=, <, <= , >, >= or when the subquery is used as an expression.")
        cache[key] = rows[0]["id"] if rows else None
    return cache[key]


def _next_jv_no(cid, prefix, category):
    n = query_one(
        f"SELECT COUNT(*) AS n FROM `JournalVoucher` WHERE company_id = %s AND {_ci_lit('category', category)}", [cid]
    )["n"]
    return f"{prefix}-{int(n) + 1}"


@sp("dbo.sp_Ticket", "SAVE")
def ticket_save(p):
    # Parameters, coerced to their declared types (as EXEC does).
    tid = _p_int(p.get("Id"))
    cid = _p_int(p.get("CompanyId"))
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
    lines_json = _p_str(p.get("LinesJson"))
    jv_narration = _p_str(p.get("JvNarration"), 250)
    jv_total_debit = _p_dec(p.get("JvTotalDebit"), 16, 2)
    jv_total_credit = _p_dec(p.get("JvTotalCredit"), 16, 2)

    cust_ledger_id = _ledger_id(cid, customer_name, "DEBTOR")
    if cust_ledger_id is None:
        return _err('"' + (customer_name or "") + '" is not a real customer ledger (Sundry Debtors).')
    supp_ledger_id = None
    if supplier_name is not None:
        supp_ledger_id = _ledger_id(cid, supplier_name, "CREDITOR")
        if supp_ledger_id is None:
            return _err('"' + supplier_name + '" is not a real supplier ledger (Sundry Creditors).')

    # Invoice Number uniqueness - shared sequence with Rescheduled_Al_Ticket.
    if invoice_number is not None and (
        query_one(f"SELECT 1 AS x FROM `AL_Tickets` WHERE company_id = %s AND {_ci('invoice_number')} "
                  "AND (%s IS NULL OR id <> %s) LIMIT 1", [cid, invoice_number, tid, tid])
        or query_one(f"SELECT 1 AS x FROM `Rescheduled_Al_Ticket` WHERE company_id = %s AND {_ci('invoice_number')} LIMIT 1",
                     [cid, invoice_number])
    ):
        return _err('Invoice Number "' + invoice_number + '" already exists.')
    if booking_reference is not None and query_one(
        f"SELECT 1 AS x FROM `AL_Tickets` WHERE company_id = %s AND {_ci('booking_reference')} "
        "AND (%s IS NULL OR id <> %s) LIMIT 1", [cid, booking_reference, tid, tid]
    ):
        return _err('Booking Reference "' + booking_reference + '" already exists.')

    items = [v for _, v in _openjson(lines_json)]

    # Duplicate Ticket No within this submission (GROUP BY ticket_no - NULLs form one group too).
    seen = set()
    for item in items:
        k = _norm(_jcol(item, "ticket_no", _NV(30)))
        if k in seen:
            return _err("Duplicate Ticket Number within this submission.")
        seen.add(k)

    # Ticket No is globally unique across ALL tickets' lines (except this ticket's own, on update).
    json_keys = [k for k in seen if k is not None]
    if json_keys:
        marks = ", ".join(["%s"] * len(json_keys))
        dup = query_one(
            f"SELECT tl.ticket_no FROM `AL_TicketLines` tl "
            f"WHERE LOWER(RTRIM(tl.ticket_no)) COLLATE utf8mb4_bin IN ({marks}) AND (%s IS NULL OR tl.ticket_id <> %s) "
            "ORDER BY tl.id LIMIT 1",
            json_keys + [tid, tid],
        )
        if dup:
            return _err('Ticket Number "' + dup["ticket_no"] + '" already exists.')

    # Every line's own supplier_name (if given) must resolve to a real supplier ledger.
    for item in items:
        line_supp = _jcol(item, "supplier_name", _NV(150))
        if line_supp is not None and _ledger_id(cid, line_supp, "CREDITOR") is None:
            line_tno = _jcol(item, "ticket_no", _NV(30))
            return _err('"' + line_supp + '" (Ticket No. ' + (line_tno if line_tno is not None else "?")
                        + ') is not a real supplier ledger (Sundry Creditors).')

    try:
        with transaction.atomic():
            now = _now()
            was_created = False
            supp_cache = {}

            def src_rows():
                rows = []
                for item in items:
                    rows.append({c: _jcol(item, c, typ) for c, typ in _LINE_SCHEMA})
                for r in rows:
                    r["supplier_ledger_id"] = _ledger_subquery(cid, r["supplier_name"], "CREDITOR", supp_cache)
                return rows

            def insert_line(ticket_id, r):
                cols = ["ticket_id"] + _LINE_DATA_COLS + ["supplier_ledger_id", "rescheduled", "canceled", "created_at", "updated_at"]
                vals = [ticket_id] + [
                    (r["status"] if r["status"] is not None else "ISSUED") if c == "status" else r[c]
                    for c in _LINE_DATA_COLS
                ] + [r["supplier_ledger_id"], 0, 0, now, now]
                execute(
                    f"INSERT INTO `AL_TicketLines` ({', '.join(f'`{c}`' for c in cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                    vals,
                )

            if tid is not None and query_one("SELECT 1 AS x FROM `AL_Tickets` WHERE id = %s AND company_id = %s", [tid, cid]):
                result_id = tid
                execute("""
                    UPDATE `AL_Tickets`
                    SET customer_ledger_id = %s, supplier_ledger_id = %s,
                        invoice_number = %s, invoice_date = %s, invoice_type = %s,
                        booking_mode = COALESCE(%s, booking_mode), booking_type = %s, booking_status = %s,
                        travel_type = %s, user_name = %s, currency = COALESCE(%s, currency), roe = COALESCE(%s, roe),
                        booking_given_by = %s, booking_reference = %s, booking_ref_date = %s,
                        airline_pnr = %s, gds_pnr = %s, office_id = %s,
                        payment_mode = %s, payment_gateway_ref = %s, airline_category = %s,
                        branch_name = %s
                    WHERE id = %s
                """, [cust_ledger_id, supp_ledger_id, invoice_number, invoice_date, invoice_type,
                      booking_mode, booking_type, booking_status, travel_type, user_name, currency, roe,
                      booking_given_by, booking_reference, booking_ref_date, airline_pnr, gds_pnr, office_id,
                      payment_mode, payment_gateway_ref, airline_category, branch_name, tid])

                existing = query(
                    "SELECT id, ticket_no, rescheduled FROM `AL_TicketLines` WHERE ticket_id = %s ORDER BY id", [tid]
                )
                incoming = {_norm(_jcol(item, "ticket_no", _NV(30))) for item in items} - {None}

                # A line already rescheduled can't be dropped from the ticket.
                protected = [ln["ticket_no"] for ln in existing
                             if ln["rescheduled"] == 1 and _norm(ln["ticket_no"]) not in incoming]
                if protected:
                    protected.sort(key=lambda s: (_norm(s), s))
                    raise _Rollback(_err("Ticket No. " + ", ".join(protected)
                                         + " has already been rescheduled and cannot be removed from this ticket."))

                drop_ids = [ln["id"] for ln in existing
                            if ln["rescheduled"] == 0 and _norm(ln["ticket_no"]) not in incoming]
                if drop_ids:
                    execute(f"DELETE FROM `AL_TicketLines` WHERE id IN ({', '.join(['%s'] * len(drop_ids))})", drop_ids)

                # MERGE: upsert each incoming line by (ticket_id, ticket_no).
                remaining = {}
                for ln in existing:
                    if ln["id"] not in drop_ids:
                        remaining.setdefault(_norm(ln["ticket_no"]), ln["id"])
                upd_cols = [c for c in _LINE_DATA_COLS if c != "ticket_no"]
                for r in src_rows():
                    match_id = remaining.get(_norm(r["ticket_no"])) if r["ticket_no"] is not None else None
                    if match_id is not None:
                        sets, vals = [], []
                        for c in upd_cols:
                            if c == "status":
                                sets.append("`status` = COALESCE(%s, `status`)")
                            else:
                                sets.append(f"`{c}` = %s")
                            vals.append(r[c])
                        sets += ["`supplier_ledger_id` = %s", "`updated_at` = %s"]
                        vals += [r["supplier_ledger_id"], now, match_id]
                        execute(f"UPDATE `AL_TicketLines` SET {', '.join(sets)} WHERE id = %s", vals)
                    else:
                        insert_line(tid, r)

                # Upsert this ticket's JournalVoucher in place.
                if query_one("SELECT 1 AS x FROM `JournalVoucher` WHERE source_ticket_id = %s LIMIT 1", [tid]):
                    execute("""
                        UPDATE `JournalVoucher`
                        SET branch_name = %s, voucher_date = %s, narration = %s, total_debit = %s, total_credit = %s,
                            updated_at = %s
                        WHERE source_ticket_id = %s
                    """, [branch_name if branch_name is not None else "Chennai Branch", invoice_date, jv_narration,
                          jv_total_debit, jv_total_credit, now, tid])
                else:
                    _insert_ticket_jv(cid, branch_name, invoice_date, jv_narration, tid, jv_total_debit, jv_total_credit, now)
            else:
                _, result_id = execute("""
                    INSERT INTO `AL_Tickets`
                        (company_id, branch_name, invoice_number, invoice_date, invoice_type, booking_mode, booking_type, booking_status,
                         customer_ledger_id, supplier_ledger_id, travel_type, user_name, currency, roe, booking_given_by,
                         booking_reference, booking_ref_date, airline_pnr, gds_pnr, office_id, payment_mode, payment_gateway_ref,
                         airline_category, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, [cid, branch_name, invoice_number, invoice_date, invoice_type,
                      booking_mode if booking_mode is not None else "Manual", booking_type, booking_status,
                      cust_ledger_id, supp_ledger_id, travel_type, user_name,
                      currency if currency is not None else "INR", roe if roe is not None else Decimal(1),
                      booking_given_by, booking_reference, booking_ref_date, airline_pnr, gds_pnr, office_id,
                      payment_mode, payment_gateway_ref, airline_category, now, now])
                result_id = int(result_id)
                was_created = True
                for r in src_rows():
                    insert_line(result_id, r)
                _insert_ticket_jv(cid, branch_name, invoice_date, jv_narration, result_id, jv_total_debit, jv_total_credit, now)

        line_ids = query("SELECT id FROM `AL_TicketLines` WHERE ticket_id = %s ORDER BY id", [result_id])
        line_ids_str = ",".join(str(r["id"]) for r in line_ids) if line_ids else None
        vouchers = query("SELECT id, voucher_no FROM `JournalVoucher` WHERE source_ticket_id = %s ORDER BY id", [result_id])
        return [{
            "id": result_id, "line_ids": line_ids_str, "voucher_id": v["id"], "voucher_no": v["voucher_no"],
            "was_created": was_created, "status": "Success",
        } for v in vouchers]
    except _Rollback as rb:
        return rb.rows
    except Exception as exc:  # BEGIN CATCH: ROLLBACK (atomic already did) + error row
        return _err(_db_message(exc))


def _insert_ticket_jv(cid, branch_name, invoice_date, narration, ticket_id, total_debit, total_credit, now):
    voucher_no = _next_jv_no(cid, "AL", "AIRLINE")
    execute("""
        INSERT INTO `JournalVoucher`
            (company_id, branch_name, voucher_type, voucher_date, narration, category, voucher_no,
             source_ticket_id, total_debit, total_credit, lines_json, created_at, updated_at)
        VALUES (%s, %s, 'Tax Invoice', %s, %s, 'AIRLINE', %s, %s, %s, %s, '[]', %s, %s)
    """, [cid, branch_name if branch_name is not None else "Chennai Branch", invoice_date, narration, voucher_no,
          ticket_id, total_debit, total_credit, now, now])


# ---------------------------------------------------------------------------
# dbo.sp_Voucher
# ---------------------------------------------------------------------------

_VOUCHER_COLS = "id, voucher_no, branch_name, voucher_type, voucher_date, narration, total_debit, total_credit, lines_json"


def _text(rows):
    """lines_json is NVARCHAR(MAX) on SQL Server -> always str."""
    for r in rows:
        if isinstance(r.get("lines_json"), (bytes, bytearray)):
            r["lines_json"] = r["lines_json"].decode("utf-8")
    return rows


@sp("dbo.sp_Voucher", "LIST")
def voucher_list(p):
    cid = _p_int(p.get("CompanyId"))
    return _text(query(f"SELECT {_VOUCHER_COLS} FROM `Vouchers` WHERE company_id = %s ORDER BY voucher_date DESC, id DESC", [cid]))


@sp("dbo.sp_Voucher", "GET_BY_ID")
def voucher_get_by_id(p):
    vid = _p_int(p.get("Id"))
    cid = _p_int(p.get("CompanyId"))
    return _text(query(f"SELECT {_VOUCHER_COLS} FROM `Vouchers` WHERE id = %s AND company_id = %s", [vid, cid]))


def _str2(d):
    """CAST(<decimal(38,2)> AS NVARCHAR(30))."""
    d = _scale(d, 2)
    if d == 0:
        d = abs(d)
    return format(d, "f")


@sp("dbo.sp_Voucher", "SAVE")
def voucher_save(p):
    vid = _p_int(p.get("Id"))
    cid = _p_int(p.get("CompanyId"))
    branch_name = _p_str(p.get("BranchName"), 100)
    voucher_type = _p_str(p.get("VoucherType"), 20)
    voucher_date = _p_date(p.get("VoucherDate"))
    narration = _p_str(p.get("Narration"), 250)
    lines_json = _p_str(p.get("LinesJson"))

    required = "company_id, voucher_date, and at least 2 lines are required."
    if cid is None or voucher_date is None:
        return _err(required)
    entries = _openjson(lines_json)
    if len(entries) < 2:
        return _err(required)
    if vid is not None and not query_one("SELECT 1 AS x FROM `Vouchers` WHERE id = %s AND company_id = %s", [vid, cid]):
        return _err("Voucher not found.")

    dec162 = ("dec", 16, 2)
    debits = [_jcol(v, "debit", dec162) for _, v in entries]
    credits = [_jcol(v, "credit", dec162) for _, v in entries]
    zero = Decimal("0.00")
    total_debit = _p_dec(sum((d if d is not None else zero for d in debits), zero), 16, 2)
    total_credit = _p_dec(sum((c if c is not None else zero for c in credits), zero), 16, 2)

    if _scale(total_debit, 2) != _scale(total_credit, 2):
        return _err("Voucher is unbalanced: total debit " + _str2(total_debit)
                    + " does not equal total credit " + _str2(total_credit) + ".")
    if _scale(total_debit, 2) == 0:
        return _err("Voucher total cannot be zero.")

    def rn(key):
        return key if isinstance(key, int) else _p_int(key)  # CAST([key] AS INT)

    numbered = sorted(((rn(k), _try_cast_int(_json_value_text(v, "ledger_id"))) for k, v in entries), key=lambda x: x[0])
    missing = next((n for n, lid in numbered if lid is None), None)
    if missing is not None:
        return _err("Line " + str(missing + 1) + " is missing a ledger — check that all system ledgers exist.")

    ids = sorted({lid for _, lid in numbered})
    found = {r["id"]: r["name"] for r in query(
        f"SELECT id, name FROM `Ledgers` WHERE id IN ({', '.join(['%s'] * len(ids))})", ids)}
    bad = next((n for n, lid in numbered if lid not in found), None)
    if bad is not None:
        return _err("Line " + str(bad + 1) + " references a ledger that doesn't exist.")

    # Resolved lines_json (FOR JSON PATH): ledger_id, ledger_name, debit, credit - INNER JOIN Ledgers.
    resolved = []
    for (_, v), d, c in zip(entries, debits, credits):
        lid = _jcol(v, "ledger_id", ("int",))
        if lid is None or lid not in found:
            continue
        resolved.append({"ledger_id": lid, "ledger_name": found[lid],
                         "debit": d if d is not None else zero, "credit": c if c is not None else zero})
    resolved_json = _for_json_path(resolved)

    try:
        with transaction.atomic():
            vtype = voucher_type if voucher_type is not None else "Journal"
            if vid is not None:
                execute("""
                    UPDATE `Vouchers`
                    SET branch_name = %s, voucher_type = %s, voucher_date = %s,
                        narration = %s, total_debit = %s, total_credit = %s, lines_json = %s
                    WHERE id = %s
                """, [branch_name, vtype, voucher_date, narration, total_debit, total_credit, resolved_json, vid])
                result_id = vid
            else:
                n = query_one(
                    f"SELECT COUNT(*) AS n FROM `Vouchers` WHERE company_id = %s AND {_ci_lit('category', 'MANUAL')}", [cid]
                )["n"]
                now = _now()
                _, result_id = execute("""
                    INSERT INTO `Vouchers`
                        (company_id, branch_name, voucher_type, voucher_date, narration, category, voucher_no,
                         total_debit, total_credit, lines_json, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, 'MANUAL', %s, %s, %s, %s, %s, %s)
                """, [cid, branch_name, vtype, voucher_date, narration, f"VCH-{int(n) + 1}",
                      total_debit, total_credit, resolved_json, now, now])
                result_id = int(result_id)
        rows = _text(query(f"SELECT {_VOUCHER_COLS}, 'Success' AS status FROM `Vouchers` WHERE id = %s", [result_id]))
        return rows
    except Exception as exc:
        return _err(_db_message(exc))
