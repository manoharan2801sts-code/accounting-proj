"""
MySQL/TiDB port of the "setup master" procedures in
backend/sp_reference/StoredProcedures.sql (lines 628-1357):

    dbo.sp_VoucherType            LIST, GET_BY_NAME, SAVE, DELETE
    dbo.sp_FOPMaster              LIST, GET_BY_CARD_NUMBER, SAVE, DELETE
    dbo.sp_PGMaster               LIST, HISTORY_LIST, EFFECTIVE_SNAPSHOT, SAVE, DELETE
    dbo.sp_SupplierCommissionRule LIST, SAVE, DELETE
    dbo.sp_MasterMapping          LIST, SAVE_ROW, DELETE

Each handler gets the params dict exactly as sp_client builds it and
returns the rows the T-SQL SELECTs (same column names/order/types).

Parameter coercion mirrors SQL Server's implicit conversion of the
procedure's declared parameter types (NVARCHAR(n) truncation, INT/DATE/
DECIMAL(p,s) conversion, BIT), since sp_client passes raw request values
(e.g. company_id as the query-string text "1").

Text equality (names, card numbers, filters) is compared with
LOWER(TRIM(col)) = LOWER(TRIM(%s)) so it behaves like SQL Server's
case-insensitive, trailing-space-insensitive collation on both MySQL and
TiDB (utf8mb4_bin).
"""
import datetime
import decimal

from django.db import DatabaseError, transaction

from . import SPThrow, bits, execute, query, query_one, sp, to_bool_param, to_date


# --------------------------------------------------------------------------
# Parameter coercion (SQL Server parameter-binding semantics)
# --------------------------------------------------------------------------

def _int(v):
    """An INT/SMALLINT parameter."""
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, (float, decimal.Decimal)):
        return int(v)  # SQL Server truncates toward zero
    s = str(v).strip()
    if s == "":
        return 0  # CAST('' AS INT) = 0
    try:
        return int(s)
    except ValueError:
        raise SPThrow("Error converting data type nvarchar to int.")


def _str(v, length):
    """An NVARCHAR(length) parameter - SQL Server silently truncates longer values."""
    if v is None:
        return None
    if isinstance(v, bool):
        v = "1" if v else "0"
    return str(v)[:length]


def _bit(v):
    return to_bool_param(v)


def _date(v):
    """A DATE parameter. '' converts to 1900-01-01 on SQL Server."""
    if v is None:
        return None
    if isinstance(v, str) and v.strip() == "":
        return datetime.date(1900, 1, 1)
    try:
        return to_date(v)
    except ValueError:
        raise SPThrow("Conversion failed when converting date and/or time from character string.")


def _dec(v, precision, scale):
    """A DECIMAL(precision, scale) parameter (rounded half away from zero, overflow -> error)."""
    if v is None:
        return None
    if isinstance(v, bool):
        v = int(v)
    try:
        d = decimal.Decimal(str(v).strip())
    except decimal.InvalidOperation:
        raise SPThrow("Error converting data type nvarchar to numeric.")
    if not d.is_finite():
        raise SPThrow("Error converting data type nvarchar to numeric.")
    d = d.quantize(decimal.Decimal(1).scaleb(-scale), rounding=decimal.ROUND_HALF_UP)
    if abs(d) >= decimal.Decimal(10) ** (precision - scale):
        raise SPThrow("Arithmetic overflow error converting numeric to data type numeric.")
    return d


def _blank(s):
    """`@x IS NULL OR LTRIM(RTRIM(@x)) = ''` (LTRIM/RTRIM strip spaces only)."""
    return s is None or s.strip(" ") == ""


def _eq_ci(a, b):
    """SQL Server `a = b` on text: case-insensitive, trailing spaces ignored."""
    if a is None or b is None:
        return False
    return a.rstrip(" ").lower() == b.rstrip(" ").lower()


def _ci(col):
    """SQL fragment comparing column `col` to one %s placeholder like SQL Server would."""
    return f"LOWER(TRIM({col})) = LOWER(TRIM(%s))"


def _err(message, key="id"):
    """`SELECT NULL AS <key>, 'Error' AS status, <message> AS error`."""
    return [{key: None, "status": "Error", "error": message}]


def _db_message(exc):
    """ERROR_MESSAGE() for a database error raised inside a TRY block."""
    args = getattr(exc, "args", ()) or ()
    if len(args) >= 2 and isinstance(args[1], str):
        return args[1]
    return str(exc)


def _ledger_display_name(ledger_id, company_id):
    """
    `SELECT @x = COALESCE(NULLIF(alias_name, ''), name) FROM dbo.Ledgers
     WHERE id = @LedgerId AND company_id = @CompanyId` - NULL if no row.
    NULLIF(alias_name, '') treats an all-space alias as '' (SQL Server
    ignores trailing spaces), so that's done here in Python.
    """
    row = query_one(
        "SELECT `alias_name`, `name` FROM `Ledgers` WHERE `id` = %s AND `company_id` = %s",
        [ledger_id, company_id],
    )
    if row is None:
        return None
    alias = row["alias_name"]
    if alias is not None and alias.rstrip(" ") != "":
        return alias
    return row["name"]


# ==========================================================================
# dbo.sp_VoucherType
# ==========================================================================

_VT_BITS = ("is_active", "allow_additional_numbering", "allow_effective_dates",
            "allow_narration", "an_prefill_with_zero")


def _vt_rows(rows):
    for r in rows:
        bits(r, *_VT_BITS)
    return rows


@sp("dbo.sp_VoucherType", "LIST")
def voucher_type_list(p):
    vt_id = _int(p.get("Id"))
    company_id = _int(p.get("CompanyId"))
    if vt_id is not None:
        return _vt_rows(query(
            "SELECT * FROM `VoucherType` WHERE `id` = %s AND `company_id` = %s",
            [vt_id, company_id],
        ))
    return _vt_rows(query(
        "SELECT * FROM `VoucherType` WHERE `company_id` = %s ORDER BY `name`",
        [company_id],
    ))


@sp("dbo.sp_VoucherType", "GET_BY_NAME")
def voucher_type_get_by_name(p):
    company_id = _int(p.get("CompanyId"))
    name = _str(p.get("Name"), 100)
    return _vt_rows(query(
        f"SELECT * FROM `VoucherType` WHERE `company_id` = %s AND {_ci('`name`')}",
        [company_id, name],
    ))


@sp("dbo.sp_VoucherType", "SAVE")
def voucher_type_save(p):
    vt_id = _int(p.get("Id"))
    company_id = _int(p.get("CompanyId"))
    name = _str(p.get("Name"), 100)
    alias_name = _str(p.get("AliasName"), 100)
    voucher_category = _str(p.get("VoucherCategory"), 20)
    is_active = _bit(p.get("IsActive"))
    number_method = _str(p.get("NumberMethod"), 30)
    allow_additional_numbering = _bit(p.get("AllowAdditionalNumbering"))
    allow_effective_dates = _bit(p.get("AllowEffectiveDates"))
    allow_narration = _bit(p.get("AllowNarration"))
    an_width = _int(p.get("AnWidthOfInvoiceNumber"))
    an_prefill = _bit(p.get("AnPrefillWithZero"))
    an_restart_from = _date(p.get("AnRestartApplicableFrom"))
    an_restart_start = _int(p.get("AnRestartStartingNumber"))
    an_restart_period = _str(p.get("AnRestartPeriod"), 10)
    an_prefix = _str(p.get("AnPrefixDetails"), 20)
    an_suffix = _str(p.get("AnSuffixDetails"), 20)

    if company_id is None:
        return _err("company_id is required")
    if _blank(name):
        return _err("Voucher Name is required.")
    dup = query_one(
        f"SELECT 1 AS x FROM `VoucherType` WHERE `company_id` = %s AND {_ci('`name`')}"
        " AND (%s IS NULL OR `id` <> %s)",
        [company_id, name, vt_id, vt_id],
    )
    if dup:
        return _err('"' + name + '" already exists - Voucher Name must be unique.')
    if vt_id is not None and not query_one(
        "SELECT 1 AS x FROM `VoucherType` WHERE `id` = %s AND `company_id` = %s", [vt_id, company_id]
    ):
        return _err("Voucher Type " + str(vt_id) + " not found.")

    voucher_category = "General" if voucher_category is None else voucher_category
    is_active = True if is_active is None else is_active
    number_method = "Automatic" if number_method is None else number_method
    allow_additional_numbering = False if allow_additional_numbering is None else allow_additional_numbering
    allow_effective_dates = False if allow_effective_dates is None else allow_effective_dates
    allow_narration = True if allow_narration is None else allow_narration
    an_prefill = False if an_prefill is None else an_prefill
    an_restart_period = "None" if an_restart_period is None else an_restart_period

    try:
        with transaction.atomic():
            was_created = False
            if vt_id is not None:
                # `updated_at = updated_at` keeps MySQL's ON UPDATE
                # CURRENT_TIMESTAMP from firing: the T-SQL UPDATE leaves
                # updated_at untouched.
                execute(
                    "UPDATE `VoucherType` SET `name` = %s, `alias_name` = %s, `voucher_category` = %s,"
                    " `is_active` = %s, `number_method` = %s, `allow_additional_numbering` = %s,"
                    " `allow_effective_dates` = %s, `allow_narration` = %s,"
                    " `an_width_of_invoice_number` = %s, `an_prefill_with_zero` = %s,"
                    " `an_restart_applicable_from` = %s, `an_restart_starting_number` = %s,"
                    " `an_restart_period` = %s, `an_prefix_details` = %s, `an_suffix_details` = %s,"
                    " `updated_at` = `updated_at`"
                    " WHERE `id` = %s AND `company_id` = %s",
                    [name, alias_name, voucher_category, is_active, number_method,
                     allow_additional_numbering, allow_effective_dates, allow_narration,
                     an_width, an_prefill, an_restart_from, an_restart_start, an_restart_period,
                     an_prefix, an_suffix, vt_id, company_id],
                )
                result_id = vt_id
            else:
                _, result_id = execute(
                    "INSERT INTO `VoucherType` (`company_id`, `name`, `alias_name`, `voucher_category`,"
                    " `is_active`, `number_method`, `allow_additional_numbering`, `allow_effective_dates`,"
                    " `allow_narration`, `an_width_of_invoice_number`, `an_prefill_with_zero`,"
                    " `an_restart_applicable_from`, `an_restart_starting_number`, `an_restart_period`,"
                    " `an_prefix_details`, `an_suffix_details`)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    [company_id, name, alias_name, voucher_category, is_active, number_method,
                     allow_additional_numbering, allow_effective_dates, allow_narration,
                     an_width, an_prefill, an_restart_from, an_restart_start, an_restart_period,
                     an_prefix, an_suffix],
                )
                was_created = True
        rows = query("SELECT * FROM `VoucherType` WHERE `id` = %s", [result_id])
    except DatabaseError as exc:
        return _err(_db_message(exc))
    for r in rows:
        bits(r, *_VT_BITS)
        r["was_created"] = was_created
        r["status"] = "Success"
    return rows


@sp("dbo.sp_VoucherType", "DELETE")
def voucher_type_delete(p):
    vt_id = _int(p.get("Id"))
    company_id = _int(p.get("CompanyId"))
    if not query_one("SELECT 1 AS x FROM `VoucherType` WHERE `id` = %s AND `company_id` = %s", [vt_id, company_id]):
        return _err("Voucher Type not found.")
    try:
        with transaction.atomic():
            execute("DELETE FROM `VoucherType` WHERE `id` = %s AND `company_id` = %s", [vt_id, company_id])
    except DatabaseError as exc:
        return _err(_db_message(exc))
    return [{"id": vt_id, "status": "Success"}]


# ==========================================================================
# dbo.sp_FOPMaster
# ==========================================================================

_FOP_COLS = ("`id`, `card_type`, `card_number`, `bank_name`, "
             "`card_master_ledger_id`, `card_master_ledger_name`, `is_active`")


@sp("dbo.sp_FOPMaster", "LIST")
def fop_master_list(p):
    company_id = _int(p.get("CompanyId"))
    card_type = _str(p.get("CardType"), 20)
    rows = query(
        f"SELECT {_FOP_COLS} FROM `FOPMaster`"
        f" WHERE `company_id` = %s AND (%s IS NULL OR {_ci('`card_type`')})"
        " ORDER BY `card_type`, `card_number`",
        [company_id, card_type, card_type],
    )
    return [bits(r, "is_active") for r in rows]


@sp("dbo.sp_FOPMaster", "GET_BY_CARD_NUMBER")
def fop_master_get_by_card_number(p):
    company_id = _int(p.get("CompanyId"))
    card_number = _str(p.get("CardNumber"), 40)
    return query(
        f"SELECT `id`, `card_master_ledger_id` FROM `FOPMaster`"
        f" WHERE `company_id` = %s AND {_ci('`card_number`')}",
        [company_id, card_number],
    )


@sp("dbo.sp_FOPMaster", "SAVE")
def fop_master_save(p):
    card_id = _int(p.get("Id"))
    company_id = _int(p.get("CompanyId"))
    card_type = _str(p.get("CardType"), 20)
    card_number = _str(p.get("CardNumber"), 40)
    bank_name = _str(p.get("BankName"), 100)
    ledger_id = _int(p.get("CardMasterLedgerId"))
    is_active = _bit(p.get("IsActive"))

    if company_id is None or card_type is None or _blank(card_number):
        return _err("company_id, card_type and card_number are required")
    if _eq_ci(card_type, "Own Card") and ledger_id is None:
        return _err("card_master_ledger_id is required for Own Card")

    ledger_name = None
    if ledger_id is not None:
        ledger_name = _ledger_display_name(ledger_id, company_id)
        if ledger_name is None:
            return _err("Ledger " + str(ledger_id) + " not found.")

    if query_one(
        f"SELECT 1 AS x FROM `FOPMaster` WHERE `company_id` = %s AND {_ci('`card_number`')}"
        " AND (%s IS NULL OR `id` <> %s)",
        [company_id, card_number, card_id, card_id],
    ):
        return _err('Card Number "' + card_number + '" is already used.')
    if card_id is not None and not query_one(
        "SELECT 1 AS x FROM `FOPMaster` WHERE `id` = %s AND `company_id` = %s", [card_id, company_id]
    ):
        return _err("Card " + str(card_id) + " not found.")

    is_active = True if is_active is None else is_active

    try:
        with transaction.atomic():
            if card_id is not None:
                execute(
                    "UPDATE `FOPMaster` SET `card_type` = %s, `card_number` = %s, `bank_name` = %s,"
                    " `card_master_ledger_id` = %s, `card_master_ledger_name` = %s, `is_active` = %s,"
                    " `updated_at` = `updated_at`"
                    " WHERE `id` = %s AND `company_id` = %s",
                    [card_type, card_number, bank_name, ledger_id, ledger_name, is_active, card_id, company_id],
                )
                result_id = card_id
            elif query_one(
                f"SELECT 1 AS x FROM `FOPMaster` WHERE `company_id` = %s AND {_ci('`card_number`')}",
                [company_id, card_number],
            ):
                execute(
                    "UPDATE `FOPMaster` SET `card_type` = %s, `bank_name` = %s,"
                    " `card_master_ledger_id` = %s, `card_master_ledger_name` = %s, `is_active` = %s,"
                    " `updated_at` = `updated_at`"
                    f" WHERE `company_id` = %s AND {_ci('`card_number`')}",
                    [card_type, bank_name, ledger_id, ledger_name, is_active, company_id, card_number],
                )
                found = query(
                    f"SELECT `id` FROM `FOPMaster` WHERE `company_id` = %s AND {_ci('`card_number`')}",
                    [company_id, card_number],
                )
                result_id = found[-1]["id"] if found else None
            else:
                _, result_id = execute(
                    "INSERT INTO `FOPMaster` (`company_id`, `card_type`, `card_number`, `bank_name`,"
                    " `card_master_ledger_id`, `card_master_ledger_name`, `is_active`)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    [company_id, card_type, card_number, bank_name, ledger_id, ledger_name, is_active],
                )
        rows = query(f"SELECT {_FOP_COLS} FROM `FOPMaster` WHERE `id` = %s", [result_id])
    except DatabaseError as exc:
        return _err(_db_message(exc))
    for r in rows:
        bits(r, "is_active")
        r["status"] = "Success"
    return rows


@sp("dbo.sp_FOPMaster", "DELETE")
def fop_master_delete(p):
    card_id = _int(p.get("Id"))
    company_id = _int(p.get("CompanyId"))
    if not query_one("SELECT 1 AS x FROM `FOPMaster` WHERE `id` = %s AND `company_id` = %s", [card_id, company_id]):
        return _err("Card not found.")
    try:
        with transaction.atomic():
            execute("DELETE FROM `FOPMaster` WHERE `id` = %s AND `company_id` = %s", [card_id, company_id])
    except DatabaseError as exc:
        return _err(_db_message(exc))
    return [{"id": card_id, "status": "Success"}]


# ==========================================================================
# dbo.sp_PGMaster
# ==========================================================================

_PG_SELECT = (
    "SELECT p.`id`, p.`gateway_name`,"
    " p.`payment_master_ledger_id`, p.`payment_master_ledger_name`,"
    " p.`pg_charges_master_ledger_id`, p.`pg_charges_master_ledger_name`,"
    " IFNULL(l.`gst_percentage`, 0) AS `pg_charges_master_ledger_gst_percentage`,"
    " p.`pg_charges_percentage`, p.`pg_charges_percentage_effective_from`, p.`is_active`"
    " FROM `PGMaster` p"
    " LEFT JOIN `Ledgers` l ON l.`id` = p.`pg_charges_master_ledger_id`"
)


def _pg_rows(rows):
    for r in rows:
        bits(r, "is_active")
        r["pg_charges_master_ledger_gst_percentage"] = _as_decimal(r["pg_charges_master_ledger_gst_percentage"])
    return rows


def _as_decimal(v):
    """ISNULL(decimal_col, 0) is DECIMAL on SQL Server; keep it a Decimal."""
    if v is None or isinstance(v, decimal.Decimal):
        return v
    return decimal.Decimal(str(v))


@sp("dbo.sp_PGMaster", "LIST")
def pg_master_list(p):
    company_id = _int(p.get("CompanyId"))
    return _pg_rows(query(_PG_SELECT + " WHERE p.`company_id` = %s ORDER BY p.`gateway_name`", [company_id]))


@sp("dbo.sp_PGMaster", "HISTORY_LIST")
def pg_master_history_list(p):
    gw_id = _int(p.get("Id"))
    company_id = _int(p.get("CompanyId"))
    return query(
        "SELECT `id`, `effective_from`, `payment_master_ledger_name`, `pg_charges_master_ledger_name`,"
        " `pg_charges_percentage`"
        " FROM `PGMasterHistory` WHERE `pg_master_id` = %s AND `company_id` = %s"
        " ORDER BY `effective_from` DESC",
        [gw_id, company_id],
    )


@sp("dbo.sp_PGMaster", "EFFECTIVE_SNAPSHOT")
def pg_master_effective_snapshot(p):
    company_id = _int(p.get("CompanyId"))
    gateway_name = _str(p.get("GatewayName"), 100)
    as_of = _date(p.get("AsOfDate"))

    gw = query(
        f"SELECT `id` FROM `PGMaster` WHERE `company_id` = %s AND {_ci('`gateway_name`')} ORDER BY `id`",
        [company_id, gateway_name],
    )
    gw_id = gw[-1]["id"] if gw else None  # SELECT @v = col keeps the last row's value
    if gw_id is None:
        return _err("Payment Gateway not found.", key="payment_master_ledger_id")

    hist_id = None
    if as_of is not None:
        h = query_one(
            "SELECT `id` FROM `PGMasterHistory` WHERE `pg_master_id` = %s AND `effective_from` <= %s"
            " ORDER BY `effective_from` DESC LIMIT 1",
            [gw_id, as_of],
        )
        hist_id = h["id"] if h else None

    if hist_id is not None:
        rows = query(
            "SELECT h.`payment_master_ledger_id`, h.`payment_master_ledger_name`,"
            " h.`pg_charges_master_ledger_id`, h.`pg_charges_master_ledger_name`,"
            " IFNULL((SELECT l.`gst_percentage` FROM `Ledgers` l WHERE l.`id` = h.`pg_charges_master_ledger_id`), 0)"
            " AS `pg_charges_master_ledger_gst_percentage`,"
            " IFNULL(h.`pg_charges_percentage`, 0) AS `pg_charges_percentage`,"
            " h.`effective_from`, 'Success' AS `status`"
            " FROM `PGMasterHistory` h WHERE h.`id` = %s",
            [hist_id],
        )
    else:
        rows = query(
            "SELECT p.`payment_master_ledger_id`, p.`payment_master_ledger_name`,"
            " p.`pg_charges_master_ledger_id`, p.`pg_charges_master_ledger_name`,"
            " IFNULL(l.`gst_percentage`, 0) AS `pg_charges_master_ledger_gst_percentage`,"
            " IFNULL(p.`pg_charges_percentage`, 0) AS `pg_charges_percentage`,"
            " NULL AS `effective_from`, 'Success' AS `status`"
            " FROM `PGMaster` p LEFT JOIN `Ledgers` l ON l.`id` = p.`pg_charges_master_ledger_id`"
            " WHERE p.`id` = %s",
            [gw_id],
        )
    for r in rows:
        r["pg_charges_master_ledger_gst_percentage"] = _as_decimal(r["pg_charges_master_ledger_gst_percentage"])
        r["pg_charges_percentage"] = _as_decimal(r["pg_charges_percentage"])
    return rows


@sp("dbo.sp_PGMaster", "SAVE")
def pg_master_save(p):
    gw_id = _int(p.get("Id"))
    company_id = _int(p.get("CompanyId"))
    gateway_name = _str(p.get("GatewayName"), 100)
    pay_ledger_id = _int(p.get("PaymentMasterLedgerId"))
    charges_ledger_id = _int(p.get("PgChargesMasterLedgerId"))
    pct = _dec(p.get("PgChargesPercentage"), 5, 2)
    eff_from = _date(p.get("PgChargesPercentageEffectiveFrom"))
    is_active = _bit(p.get("IsActive"))

    if company_id is None or _blank(gateway_name) or pay_ledger_id is None:
        return _err("company_id, gateway_name and payment_master_ledger_id are required")
    if pct is not None and (pct < 0 or pct > 100):
        return _err("PG Charges Percentage must be between 0 and 100.")

    pay_ledger_name = _ledger_display_name(pay_ledger_id, company_id)
    if pay_ledger_name is None:
        return _err("Ledger " + str(pay_ledger_id) + " not found.")
    charges_ledger_name = None
    if charges_ledger_id is not None:
        charges_ledger_name = _ledger_display_name(charges_ledger_id, company_id)
        if charges_ledger_name is None:
            return _err("Ledger " + str(charges_ledger_id) + " not found.")

    if query_one(
        f"SELECT 1 AS x FROM `PGMaster` WHERE `company_id` = %s AND {_ci('`gateway_name`')}"
        " AND (%s IS NULL OR `id` <> %s)",
        [company_id, gateway_name, gw_id, gw_id],
    ):
        return _err('Payment Gateway Name "' + gateway_name + '" is already used.')
    if gw_id is not None and not query_one(
        "SELECT 1 AS x FROM `PGMaster` WHERE `id` = %s AND `company_id` = %s", [gw_id, company_id]
    ):
        return _err("Payment Gateway " + str(gw_id) + " not found.")

    is_active = True if is_active is None else is_active

    try:
        with transaction.atomic():
            if gw_id is not None:
                execute(
                    "UPDATE `PGMaster` SET `gateway_name` = %s,"
                    " `payment_master_ledger_id` = %s, `payment_master_ledger_name` = %s,"
                    " `pg_charges_master_ledger_id` = %s, `pg_charges_master_ledger_name` = %s,"
                    " `pg_charges_percentage` = %s, `pg_charges_percentage_effective_from` = %s,"
                    " `is_active` = %s, `updated_at` = UTC_TIMESTAMP(6)"
                    " WHERE `id` = %s AND `company_id` = %s",
                    [gateway_name, pay_ledger_id, pay_ledger_name, charges_ledger_id, charges_ledger_name,
                     pct, eff_from, is_active, gw_id, company_id],
                )
                result_id = gw_id
            else:
                _, result_id = execute(
                    "INSERT INTO `PGMaster` (`company_id`, `gateway_name`, `payment_master_ledger_id`,"
                    " `payment_master_ledger_name`, `pg_charges_master_ledger_id`, `pg_charges_master_ledger_name`,"
                    " `pg_charges_percentage`, `pg_charges_percentage_effective_from`, `is_active`,"
                    " `created_at`, `updated_at`)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))",
                    [company_id, gateway_name, pay_ledger_id, pay_ledger_name, charges_ledger_id,
                     charges_ledger_name, pct, eff_from, is_active],
                )

            if eff_from is not None:
                if query_one(
                    "SELECT 1 AS x FROM `PGMasterHistory` WHERE `pg_master_id` = %s AND `effective_from` = %s",
                    [result_id, eff_from],
                ):
                    execute(
                        "UPDATE `PGMasterHistory` SET `company_id` = %s, `gateway_name` = %s,"
                        " `payment_master_ledger_id` = %s, `payment_master_ledger_name` = %s,"
                        " `pg_charges_master_ledger_id` = %s, `pg_charges_master_ledger_name` = %s,"
                        " `pg_charges_percentage` = %s"
                        " WHERE `pg_master_id` = %s AND `effective_from` = %s",
                        [company_id, gateway_name, pay_ledger_id, pay_ledger_name, charges_ledger_id,
                         charges_ledger_name, pct, result_id, eff_from],
                    )
                else:
                    execute(
                        "INSERT INTO `PGMasterHistory` (`pg_master_id`, `company_id`, `gateway_name`,"
                        " `payment_master_ledger_id`, `payment_master_ledger_name`,"
                        " `pg_charges_master_ledger_id`, `pg_charges_master_ledger_name`, `pg_charges_percentage`,"
                        " `effective_from`, `created_at`)"
                        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6))",
                        [result_id, company_id, gateway_name, pay_ledger_id, pay_ledger_name,
                         charges_ledger_id, charges_ledger_name, pct, eff_from],
                    )
        rows = query(_PG_SELECT + " WHERE p.`id` = %s", [result_id])
    except DatabaseError as exc:
        return _err(_db_message(exc))
    _pg_rows(rows)
    for r in rows:
        r["status"] = "Success"
    return rows


@sp("dbo.sp_PGMaster", "DELETE")
def pg_master_delete(p):
    gw_id = _int(p.get("Id"))
    company_id = _int(p.get("CompanyId"))
    if not query_one("SELECT 1 AS x FROM `PGMaster` WHERE `id` = %s AND `company_id` = %s", [gw_id, company_id]):
        return _err("Payment Gateway not found.")
    try:
        with transaction.atomic():
            execute("DELETE FROM `PGMasterHistory` WHERE `pg_master_id` = %s", [gw_id])
            execute("DELETE FROM `PGMaster` WHERE `id` = %s AND `company_id` = %s", [gw_id, company_id])
    except DatabaseError as exc:
        return _err(_db_message(exc))
    return [{"id": gw_id, "status": "Success"}]


# ==========================================================================
# dbo.sp_SupplierCommissionRule
# ==========================================================================

_SCR_COLS = ("`id`, `rule_type` AS `type`, `office_id`, `supplier_name`, `travel_type`, `airline_category`,"
             " `cabin`, `fare_type`, `comm_on`, `calc_type`, `calc_pct`, `flat_amt`, `valid_upto`")


@sp("dbo.sp_SupplierCommissionRule", "LIST")
def supplier_commission_rule_list(p):
    company_id = _int(p.get("CompanyId"))
    office_id = _str(p.get("OfficeId"), 30)
    return query(
        f"SELECT {_SCR_COLS} FROM `SupplierCommissionRules`"
        f" WHERE `company_id` = %s AND (%s IS NULL OR {_ci('`office_id`')})"
        " ORDER BY `id` DESC",
        [company_id, office_id, office_id],
    )


@sp("dbo.sp_SupplierCommissionRule", "SAVE")
def supplier_commission_rule_save(p):
    company_id = _int(p.get("CompanyId"))
    office_id = _str(p.get("OfficeId"), 30)
    supplier_name = _str(p.get("SupplierName"), 200)
    travel_type = _str(p.get("TravelType"), 20)
    airline_category = _str(p.get("AirlineCategory"), 10)
    cabin = _str(p.get("Cabin"), 30)
    fare_type = _str(p.get("FareType"), 60)
    comm_on = _str(p.get("CommOn"), 20)
    calc_type = _str(p.get("CalcType"), 12)
    calc_pct = _dec(p.get("CalcPct"), 14, 2)
    flat_amt = _dec(p.get("FlatAmt"), 14, 2)
    valid_upto = _date(p.get("ValidUpto"))

    if company_id is None or _blank(office_id):
        return _err("company_id and office_id are required")

    zero = decimal.Decimal("0")
    try:
        with transaction.atomic():
            _, new_id = execute(
                "INSERT INTO `SupplierCommissionRules` (`company_id`, `rule_type`, `office_id`, `supplier_name`,"
                " `travel_type`, `airline_category`, `cabin`, `fare_type`, `comm_on`, `calc_type`, `calc_pct`,"
                " `flat_amt`, `valid_upto`, `created_at`, `updated_at`)"
                " VALUES (%s, 'Commission', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
                " UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))",
                [company_id, office_id, supplier_name, travel_type, airline_category, cabin, fare_type,
                 comm_on, calc_type, zero if calc_pct is None else calc_pct,
                 zero if flat_amt is None else flat_amt, valid_upto],
            )
        rows = query(f"SELECT {_SCR_COLS}, 'Success' AS `status` FROM `SupplierCommissionRules` WHERE `id` = %s",
                     [new_id])
    except DatabaseError as exc:
        return _err(_db_message(exc))
    return rows


@sp("dbo.sp_SupplierCommissionRule", "DELETE")
def supplier_commission_rule_delete(p):
    rule_id = _int(p.get("Id"))
    company_id = _int(p.get("CompanyId"))
    if not query_one(
        "SELECT 1 AS x FROM `SupplierCommissionRules` WHERE `id` = %s AND `company_id` = %s", [rule_id, company_id]
    ):
        return _err("Rule not found.")
    try:
        with transaction.atomic():
            execute("DELETE FROM `SupplierCommissionRules` WHERE `id` = %s AND `company_id` = %s",
                    [rule_id, company_id])
    except DatabaseError as exc:
        return _err(_db_message(exc))
    return [{"id": rule_id, "status": "Success"}]


# ==========================================================================
# dbo.sp_MasterMapping
# ==========================================================================

_MM_SELECT = (
    "SELECT m.`id`, m.`product_type`, m.`masters_category`, m.`masters_category_id`, m.`field_name`,"
    " m.`ledger_id`, m.`ledger_name`, IFNULL(l.`gst_percentage`, 0) AS `ledger_gst_percentage`,"
    " m.`effective_from`"
)


def _mm_rows(rows):
    for r in rows:
        r["ledger_gst_percentage"] = _as_decimal(r["ledger_gst_percentage"])
    return rows


@sp("dbo.sp_MasterMapping", "LIST")
def master_mapping_list(p):
    company_id = _int(p.get("CompanyId"))
    product_type = _str(p.get("ProductType"), 20)
    masters_category = _str(p.get("MastersCategory"), 40)
    return _mm_rows(query(
        _MM_SELECT +
        " FROM `MasterMapping` m LEFT JOIN `Ledgers` l ON l.`id` = m.`ledger_id`"
        " WHERE m.`company_id` = %s"
        f" AND (%s IS NULL OR {_ci('m.`product_type`')})"
        f" AND (%s IS NULL OR {_ci('m.`masters_category`')})"
        " ORDER BY m.`product_type`, m.`masters_category`, m.`id`",
        [company_id, product_type, product_type, masters_category, masters_category],
    ))


@sp("dbo.sp_MasterMapping", "SAVE_ROW")
def master_mapping_save_row(p):
    company_id = _int(p.get("CompanyId"))
    product_type = _str(p.get("ProductType"), 20)
    masters_category = _str(p.get("MastersCategory"), 40)
    masters_category_id = _int(p.get("MastersCategoryId"))
    field_name = _str(p.get("FieldName"), 60)
    ledger_id = _int(p.get("LedgerId"))
    effective_from = _date(p.get("EffectiveFrom"))

    if (company_id is None or product_type is None or masters_category is None
            or field_name is None or ledger_id is None or effective_from is None):
        return _err("company_id, product_type, masters_category, field_name, ledger_id and effective_from are required")

    ledger_name = _ledger_display_name(ledger_id, company_id)
    if ledger_name is None:
        return _err("Ledger " + str(ledger_id) + " not found.")

    cat_id = 0 if masters_category_id is None else masters_category_id
    key_where = f"`company_id` = %s AND {_ci('`product_type`')} AND {_ci('`field_name`')}"
    key_params = [company_id, product_type, field_name]
    try:
        with transaction.atomic():
            if query_one(f"SELECT 1 AS x FROM `MasterMapping` WHERE {key_where}", key_params):
                execute(
                    "UPDATE `MasterMapping` SET `masters_category` = %s, `masters_category_id` = %s,"
                    " `ledger_id` = %s, `ledger_name` = %s, `effective_from` = %s,"
                    f" `updated_at` = UTC_TIMESTAMP(6) WHERE {key_where}",
                    [masters_category, cat_id, ledger_id, ledger_name, effective_from] + key_params,
                )
                found = query(f"SELECT `id` FROM `MasterMapping` WHERE {key_where} ORDER BY `id`", key_params)
                result_id = found[-1]["id"] if found else None
            else:
                _, result_id = execute(
                    "INSERT INTO `MasterMapping` (`company_id`, `product_type`, `masters_category`,"
                    " `masters_category_id`, `field_name`, `ledger_id`, `ledger_name`, `effective_from`,"
                    " `created_at`, `updated_at`)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))",
                    [company_id, product_type, masters_category, cat_id, field_name, ledger_id,
                     ledger_name, effective_from],
                )
        rows = query(
            _MM_SELECT + ", 'Success' AS `status`"
            " FROM `MasterMapping` m LEFT JOIN `Ledgers` l ON l.`id` = m.`ledger_id` WHERE m.`id` = %s",
            [result_id],
        )
    except DatabaseError as exc:
        return _err(_db_message(exc))
    return _mm_rows(rows)


@sp("dbo.sp_MasterMapping", "DELETE")
def master_mapping_delete(p):
    mapping_id = _int(p.get("Id"))
    company_id = _int(p.get("CompanyId"))
    if not query_one("SELECT 1 AS x FROM `MasterMapping` WHERE `id` = %s AND `company_id` = %s",
                     [mapping_id, company_id]):
        return _err("Mapping not found.")
    try:
        with transaction.atomic():
            execute("DELETE FROM `MasterMapping` WHERE `id` = %s AND `company_id` = %s", [mapping_id, company_id])
    except DatabaseError as exc:
        return _err(_db_message(exc))
    return [{"id": mapping_id, "status": "Success"}]
