"""
MySQL/TiDB port of dbo.sp_LedgerGroup, dbo.sp_Ledger and dbo.sp_CompanyMaster
(backend/sp_reference/StoredProcedures.sql, lines 37-618).

Every handler takes the params dict exactly as sp_client builds it and returns
the rows the T-SQL returns (same column names, order, Python value types).

Collation: SQL Server compares text case-insensitively and ignores trailing
spaces; TiDB's default utf8mb4_bin is case-sensitive, so every text equality
below is written as LOWER(RTRIM(col)) = LOWER(RTRIM(%s)) (RTRIM, not TRIM:
SQL Server only ignores TRAILING spaces - leading spaces are significant).
"""
import datetime
import decimal
import json

from django.db import DatabaseError, DataError, transaction
from django.utils import timezone

from . import SPThrow, bits, execute, query, query_one, sp, to_bool_param


# --------------------------------------------------------------------------
# Parameter coercion - what SQL Server does when pyodbc binds a value to a
# typed procedure parameter (implicit conversion, silent NVARCHAR(n)
# truncation, DECIMAL(p,s) rounding).
# --------------------------------------------------------------------------

def _p_int(params, key):
    v = params.get(key)
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, decimal.Decimal):
        return int(v)
    s = str(v).strip()
    if s == "":
        return 0  # CAST('' AS INT) = 0 in SQL Server
    try:
        return int(s)
    except ValueError:
        raise DataError(f"Conversion failed when converting the nvarchar value '{v}' to data type int.")


def _p_str(params, key, max_len=None):
    v = params.get(key)
    if v is None:
        return None
    if isinstance(v, bool):
        v = "1" if v else "0"
    elif not isinstance(v, str):
        v = str(v)
    if max_len is not None and len(v) > max_len:
        v = v[:max_len]  # NVARCHAR(n) parameters truncate silently
    return v


def _p_dec(params, key, precision, scale):
    v = params.get(key)
    if v is None:
        return None
    try:
        if isinstance(v, bool):
            d = decimal.Decimal(int(v))
        elif isinstance(v, float):
            d = decimal.Decimal(repr(v))
        else:
            d = decimal.Decimal(str(v).strip())
        if not d.is_finite():
            raise decimal.InvalidOperation
    except decimal.InvalidOperation:
        raise DataError("Error converting data type nvarchar to numeric.")
    d = d.quantize(decimal.Decimal(1).scaleb(-scale), rounding=decimal.ROUND_HALF_UP)
    if abs(d) >= decimal.Decimal(10) ** (precision - scale):
        raise DataError("Arithmetic overflow error converting numeric to data type numeric.")
    return d


def _p_bit(params, key, default=None):
    if key not in params:
        return default
    return to_bool_param(params.get(key))


def _p_date(params, key):
    v = params.get(key)
    if v is None:
        return None
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    s = str(v).strip()
    if s == "":
        return datetime.date(1900, 1, 1)  # CAST('' AS DATE) = 1900-01-01 in SQL Server
    try:
        return datetime.date.fromisoformat(s[:10])
    except ValueError:
        raise DataError("Conversion failed when converting date and/or time from character string.")


def _utc_now():
    """SYSUTCDATETIME(), stored naive-UTC like Django does with USE_TZ=True.
    The MySQL columns are DATETIME(0), so drop the fraction rather than let
    MySQL round it up to the next second."""
    return timezone.now().astimezone(datetime.timezone.utc).replace(tzinfo=None, microsecond=0)


def _db_error_message(err):
    """ERROR_MESSAGE() equivalent for a MySQL/TiDB driver error."""
    args = getattr(err, "args", ())
    if len(args) >= 2 and isinstance(args[1], str):
        return args[1]
    return str(err)


def _db_error_number(err):
    args = getattr(err, "args", ())
    if args and isinstance(args[0], int):
        return args[0]
    return None


def _err(message):
    """SELECT NULL AS id, 'Error' AS status, <message> AS error"""
    return [{"id": None, "status": "Error", "error": message}]


def _ci_eq(col):
    return f"LOWER(RTRIM({col})) = LOWER(RTRIM(%s))"


# ==========================================================================
# dbo.sp_LedgerGroup
# ==========================================================================

@sp("dbo.sp_LedgerGroup", "SELECT")
def ledger_group_select(params):
    rows = query(
        "SELECT `id`, `name`, `code`, `account_type`, `parent_id`, `is_group`, `is_system` "
        "FROM `Ledger_Groups` WHERE `company_id` = %s ORDER BY `id`",
        [_p_int(params, "CompanyId")],
    )
    return [bits(r, "is_group", "is_system") for r in rows]


def _openjson_values(text):
    """OPENJSON(@json) WITH (v NVARCHAR(100) '$') - one value per array element
    (or per property of an object); NULL for null/nested objects/arrays."""
    if text is None:
        return []
    try:
        doc = json.loads(text)
    except (TypeError, ValueError):
        raise DataError("JSON text is not properly formatted. Unexpected character is found.")
    if isinstance(doc, list):
        items = doc
    elif isinstance(doc, dict):
        items = list(doc.values())
    else:
        raise DataError("JSON text is not properly formatted. Unexpected character is found.")
    out = []
    for item in items:
        if item is None or isinstance(item, (dict, list)):
            out.append(None)
        elif isinstance(item, bool):
            out.append("true" if item else "false")
        else:
            out.append((item if isinstance(item, str) else json.dumps(item))[:100])
    return out


@sp("dbo.sp_LedgerGroup", "LEDGERS_BY_GROUP_NAMES")
def ledgers_by_group_names(params):
    company_id = _p_int(params, "CompanyId")
    variants = {v.rstrip(" ").lower() for v in _openjson_values(params.get("NameVariantsJson")) if v is not None}
    if not variants or company_id is None:
        return []

    groups = query(
        "SELECT `id`, `name`, `parent_id` FROM `Ledger_Groups` WHERE `company_id` = %s",
        [company_id],
    )
    children = {}
    for g in groups:
        children.setdefault(g["parent_id"], []).append(g["id"])

    # Recursive CTE: anchor = groups whose name matches a variant
    # (COLLATE Latin1_General_CI_AS), then every child, level by level.
    frontier = {g["id"] for g in groups if g["name"] is not None and g["name"].rstrip(" ").lower() in variants}
    matched = set(frontier)
    level = 0
    while frontier:
        nxt = set()
        for gid in frontier:
            nxt.update(children.get(gid, ()))
        if not nxt:
            break
        level += 1
        if level > 100:  # OPTION (MAXRECURSION 100)
            raise SPThrow("The statement terminated. The maximum recursion 100 has been exhausted before statement completion.")
        matched.update(nxt)
        frontier = nxt

    if not matched:
        return []
    ids = sorted(matched)
    name_expr = ("CASE WHEN `alias_name` IS NULL OR RTRIM(`alias_name`) = '' "
                 "THEN `name` ELSE `alias_name` END")
    return query(
        f"SELECT `id`, {name_expr} AS `name` FROM `Ledgers` "
        f"WHERE `company_id` = %s AND `group_id` IN ({', '.join(['%s'] * len(ids))}) "
        f"ORDER BY LOWER({name_expr})",
        [company_id] + ids,
    )


@sp("dbo.sp_LedgerGroup", "SAVE")
def ledger_group_save(params):
    company_id = _p_int(params, "CompanyId")
    name = _p_str(params, "Name", 100)
    code = _p_str(params, "Code", 20)
    account_type = _p_str(params, "AccountType", 20)
    parent_id = _p_int(params, "ParentId")
    is_group = _p_bit(params, "IsGroup")

    if company_id is None or name is None or account_type is None:
        return _err("company_id, name and account_type are required.")

    now = _utc_now()
    try:
        with transaction.atomic():
            _, new_id = execute(
                "INSERT INTO `Ledger_Groups` "
                "(`company_id`, `name`, `code`, `account_type`, `parent_id`, `is_group`, `is_system`, `created_at`, `updated_at`) "
                "VALUES (%s, %s, %s, %s, %s, %s, 0, %s, %s)",
                [company_id, name, code, account_type, parent_id,
                 True if is_group is None else is_group, now, now],
            )
    except DatabaseError as err:
        return _err(_db_error_message(err))

    rows = query(
        "SELECT `id`, `company_id`, `name`, `code`, `account_type`, `parent_id`, "
        "`is_group`, `is_system`, `created_at`, `updated_at`, 'Success' AS `status` "
        "FROM `Ledger_Groups` WHERE `id` = %s",
        [new_id],
    )
    return [bits(r, "is_group", "is_system") for r in rows]


# ==========================================================================
# dbo.sp_Ledger
# ==========================================================================

# (column, @Param, kind, length/precision, scale) for the optional fields
# SAVE and UPDATE both take, in the procedure's column order.
_LEDGER_FIELDS = [
    ("bank_account_no", "BankAccountNo", "str", 40, None),
    ("bank_branch", "BankBranch", "str", 100, None),
    ("ifsc_code", "IfscCode", "str", 15, None),
    ("swift_code", "SwiftCode", "str", 15, None),
    ("alias_name", "AliasName", "str", 100, None),
    ("address_line1", "AddressLine1", "str", 150, None),
    ("address_line2", "AddressLine2", "str", 150, None),
    ("agent_id", "AgentId", "str", 30, None),
    ("maintain_balance_bill_wise", "MaintainBalanceBillWise", "str", 5, None),
    ("place_of_supply", "PlaceOfSupply", "str", 60, None),
    ("city", "City", "str", 60, None),
    ("pincode", "Pincode", "str", 10, None),
    ("state_name", "StateName", "str", 60, None),
    ("gst_no", "GstNo", "str", 20, None),
    ("gst_registration_type", "GstRegistrationType", "str", 20, None),
    ("pan_no", "PanNo", "str", 15, None),
    ("emirate", "Emirate", "str", 30, None),
    ("po_box_no", "PoBoxNo", "str", 20, None),
    ("vat_trn_no", "VatTrnNo", "str", 20, None),
    ("trade_license_no", "TradeLicenseNo", "str", 30, None),
    ("trade_license_expiry", "TradeLicenseExpiry", "date", None, None),
    ("creditor_type", "CreditorType", "str", 30, None),
    ("supplier_code", "SupplierCode", "str", 30, None),
    ("office_id", "OfficeId", "str", 30, None),
    ("tax_category", "TaxCategory", "str", 10, None),
    ("tax_type", "TaxType", "str", 10, None),
    ("gst_applicable", "GstApplicable", "bit", None, None),
    ("gst_tax_type", "GstTaxType", "str", 10, None),
    ("gst_percentage", "GstPercentage", "dec", 5, 2),
    ("tds_applicable", "TdsApplicable", "bit", None, None),
    ("tds_percentage", "TdsPercentage", "dec", 5, 2),
    ("hsn_code", "HsnCode", "str", 15, None),
    ("tcs_applicable", "TcsApplicable", "bit", None, None),
    ("tcs_percentage", "TcsPercentage", "dec", 5, 2),
]

# SAVE's ISNULL(@X, <default>) for the NOT NULL tax columns.
_LEDGER_SAVE_DEFAULTS = {
    "gst_applicable": False, "gst_percentage": decimal.Decimal("0"),
    "tds_applicable": False, "tds_percentage": decimal.Decimal("0"),
    "tcs_applicable": False, "tcs_percentage": decimal.Decimal("0"),
}


def _ledger_field_values(params):
    out = {}
    for col, key, kind, a, b in _LEDGER_FIELDS:
        if kind == "str":
            out[col] = _p_str(params, key, a)
        elif kind == "date":
            out[col] = _p_date(params, key)
        elif kind == "bit":
            out[col] = _p_bit(params, key)
        else:
            out[col] = _p_dec(params, key, a, b)
    return out


@sp("dbo.sp_Ledger", "LIST")
def ledger_list(params):
    return query(
        "SELECT `id`, `company_id`, `name`, `group_id` AS `parent_id`, `account_type`, `ledger_category`, "
        "`opening_balance`, "
        "CASE WHEN LOWER(RTRIM(`opening_balance_type`)) = 'debit' THEN `opening_balance` ELSE -`opening_balance` END AS `balance`, "
        "`opening_balance_type`, `agent_id`, `office_id`, `supplier_code` "
        "FROM `Ledgers` WHERE `company_id` = %s ORDER BY `id`",
        [_p_int(params, "CompanyId")],
    )


@sp("dbo.sp_Ledger", "LIST_CUSTOMERS")
def ledger_list_customers(params):
    return query(
        "SELECT `id`, `name`, "
        "CONCAT('LED-', RIGHT(CONCAT('00000', `id`), 5)) AS `code`, "
        "COALESCE(`gst_no`, `vat_trn_no`) AS `gst_no`, "
        "COALESCE("
        "  NULLIF(CONCAT_WS(', ', `address_line1`, `address_line2`, `city`, `state_name`, `pincode`), ''),"
        "  NULLIF(CONCAT_WS(', ', `address_line1`, `address_line2`, `emirate`, `po_box_no`), '')"
        ") AS `address`, "
        "`agent_id`, `state_name` "
        "FROM `Ledgers` WHERE `company_id` = %s AND LOWER(RTRIM(`ledger_category`)) = 'debtor' "
        "ORDER BY `id`",
        [_p_int(params, "CompanyId")],
    )


@sp("dbo.sp_Ledger", "LIST_SUPPLIERS")
def ledger_list_suppliers(params):
    return query(
        "SELECT `id`, `name`, "
        "COALESCE(`supplier_code`, CONCAT('LED-', RIGHT(CONCAT('00000', `id`), 5))) AS `code`, "
        "`office_id` "
        "FROM `Ledgers` WHERE `company_id` = %s AND LOWER(RTRIM(`ledger_category`)) = 'creditor' "
        "ORDER BY `id`",
        [_p_int(params, "CompanyId")],
    )


@sp("dbo.sp_Ledger", "GET_BY_ID")
def ledger_get_by_id(params):
    rows = query(
        "SELECT `id`, `name`, `group_id` AS `parent_id`, `opening_balance`, "
        "CASE WHEN LOWER(RTRIM(`opening_balance_type`)) = 'debit' THEN `opening_balance` ELSE -`opening_balance` END AS `balance`, "
        "`opening_balance_type`, `ledger_category`, "
        "`bank_account_no`, `bank_branch`, `ifsc_code`, `swift_code`, "
        "`alias_name`, `address_line1`, `address_line2`, `agent_id`, `maintain_balance_bill_wise`, `place_of_supply`, "
        "`city`, `pincode`, `state_name`, `gst_no`, `gst_registration_type`, `pan_no`, "
        "`emirate`, `po_box_no`, `vat_trn_no`, `trade_license_no`, `trade_license_expiry`, "
        "`creditor_type`, `supplier_code`, `office_id`, "
        "`tax_category`, `tax_type`, "
        "`gst_applicable`, `gst_tax_type`, `gst_percentage`, "
        "`tds_applicable`, `tds_percentage`, `hsn_code`, "
        "`tcs_applicable`, `tcs_percentage` "
        "FROM `Ledgers` WHERE `id` = %s AND `company_id` = %s",
        [_p_int(params, "Id"), _p_int(params, "CompanyId")],
    )
    return [bits(r, "gst_applicable", "tds_applicable", "tcs_applicable") for r in rows]


@sp("dbo.sp_Ledger", "GET_BY_NAME")
def ledger_get_by_name(params):
    return query(
        "SELECT `id`, `name`, `state_name`, `gst_percentage` FROM `Ledgers` "
        f"WHERE `company_id` = %s AND {_ci_eq('`name`')} AND {_ci_eq('`ledger_category`')}",
        [_p_int(params, "CompanyId"), _p_str(params, "Name", 150), _p_str(params, "LedgerCategory", 20)],
    )


@sp("dbo.sp_Ledger", "CHECK_AGENT_ID")
def ledger_check_agent_id(params):
    agent_id = _p_str(params, "AgentId", 30)
    exclude_id = _p_int(params, "ExcludeId")
    row = query_one(
        f"SELECT 1 AS `x` FROM `Ledgers` WHERE {_ci_eq('`agent_id`')} "
        "AND (%s IS NULL OR `id` <> %s) LIMIT 1",
        [agent_id, exclude_id, exclude_id],
    )
    return [{"available": row is None}]


@sp("dbo.sp_Ledger", "CHECK_NAME")
def ledger_check_name(params):
    name = _p_str(params, "Name", 150)
    exclude_id = _p_int(params, "ExcludeId")
    row = query_one(
        f"SELECT 1 AS `x` FROM `Ledgers` WHERE `company_id` = %s AND {_ci_eq('`name`')} "
        "AND (%s IS NULL OR `id` <> %s) LIMIT 1",
        [_p_int(params, "CompanyId"), name, exclude_id, exclude_id],
    )
    return [{"available": row is None}]


@sp("dbo.sp_Ledger", "SAVE")
def ledger_save(params):
    company_id = _p_int(params, "CompanyId")
    name = _p_str(params, "Name", 150)
    parent_id = _p_int(params, "ParentId")
    opening_balance = _p_dec(params, "OpeningBalance", 18, 2)
    opening_balance_type = _p_str(params, "OpeningBalanceType", 10)
    ledger_category = _p_str(params, "LedgerCategory", 20)
    fields = _ledger_field_values(params)
    agent_id = fields["agent_id"]

    if company_id is None or name is None or parent_id is None:
        return _err("company_id, name and parent_id are required.")

    grp = query_one(
        "SELECT `account_type` FROM `Ledger_Groups` WHERE `id` = %s AND `company_id` = %s",
        [parent_id, company_id],
    )
    group_account_type = grp["account_type"] if grp else None
    if group_account_type is None:
        return _err("That group doesn't exist for this company.")

    if query_one(f"SELECT 1 AS `x` FROM `Ledgers` WHERE `company_id` = %s AND {_ci_eq('`name`')} LIMIT 1",
                 [company_id, name]):
        return _err('A ledger named "' + name + '" already exists.')
    if agent_id is not None and query_one(
            f"SELECT 1 AS `x` FROM `Ledgers` WHERE {_ci_eq('`agent_id`')} LIMIT 1", [agent_id]):
        return _err('Agent ID "' + agent_id + '" is already used by another ledger.')

    for col, default in _LEDGER_SAVE_DEFAULTS.items():
        if fields[col] is None:
            fields[col] = default

    cols = ["company_id", "name", "group_id", "account_type", "ledger_category",
            "opening_balance", "opening_balance_type"]
    vals = [company_id, name, parent_id, group_account_type,
            "OTHER" if ledger_category is None else ledger_category,
            decimal.Decimal("0") if opening_balance is None else opening_balance,
            "Debit" if opening_balance_type is None else opening_balance_type]
    for col, *_ in _LEDGER_FIELDS:
        cols.append(col)
        vals.append(fields[col])
    now = _utc_now()
    cols += ["is_system", "created_at", "updated_at"]
    vals += [False, now, now]

    try:
        with transaction.atomic():
            _, new_id = execute(
                "INSERT INTO `Ledgers` (" + ", ".join(f"`{c}`" for c in cols) + ") "
                "VALUES (" + ", ".join(["%s"] * len(cols)) + ")",
                vals,
            )
    except DatabaseError as err:
        return _err(_db_error_message(err))

    return query(
        "SELECT `id`, `name`, `group_id` AS `parent_id`, 'Success' AS `status` FROM `Ledgers` WHERE `id` = %s",
        [new_id],
    )


@sp("dbo.sp_Ledger", "UPDATE")
def ledger_update(params):
    ledger_id = _p_int(params, "Id")
    company_id = _p_int(params, "CompanyId")
    name = _p_str(params, "Name", 150)
    parent_id = _p_int(params, "ParentId")
    opening_balance = _p_dec(params, "OpeningBalance", 18, 2)
    opening_balance_type = _p_str(params, "OpeningBalanceType", 10)
    ledger_category = _p_str(params, "LedgerCategory", 20)
    fields = _ledger_field_values(params)
    agent_id = fields.pop("agent_id")
    agent_id_provided = _p_bit(params, "AgentIdProvided", default=False)

    if not query_one("SELECT 1 AS `x` FROM `Ledgers` WHERE `id` = %s AND `company_id` = %s",
                     [ledger_id, company_id]):
        return _err("Ledger not found.")
    if name is not None and query_one(
            f"SELECT 1 AS `x` FROM `Ledgers` WHERE `company_id` = %s AND {_ci_eq('`name`')} AND `id` <> %s LIMIT 1",
            [company_id, name, ledger_id]):
        return _err('A ledger named "' + name + '" already exists.')
    if agent_id is not None and query_one(
            f"SELECT 1 AS `x` FROM `Ledgers` WHERE {_ci_eq('`agent_id`')} AND `id` <> %s LIMIT 1",
            [agent_id, ledger_id]):
        return _err('Agent ID "' + agent_id + '" is already used by another ledger.')

    new_group_account_type = None
    if parent_id is not None:
        grp = query_one(
            "SELECT `account_type` FROM `Ledger_Groups` WHERE `id` = %s AND `company_id` = %s",
            [parent_id, company_id],
        )
        new_group_account_type = grp["account_type"] if grp else None
        if new_group_account_type is None:
            return _err("That group doesn't exist for this company.")

    # SET col = ISNULL(@X, col) for every column, in the procedure's order.
    sets, vals = [], []

    def isnull(col, value):
        sets.append(f"`{col}` = COALESCE(%s, `{col}`)")
        vals.append(value)

    isnull("name", name)
    isnull("group_id", parent_id)
    isnull("account_type", new_group_account_type)
    isnull("opening_balance", opening_balance)
    isnull("opening_balance_type", opening_balance_type)
    isnull("ledger_category", ledger_category)
    for col, *_ in _LEDGER_FIELDS:
        if col == "agent_id":
            # agent_id = CASE WHEN @AgentIdProvided = 1 THEN @AgentId ELSE agent_id END
            if agent_id_provided:
                sets.append("`agent_id` = %s")
                vals.append(agent_id)
            continue
        isnull(col, fields[col])
    sets.append("`updated_at` = %s")
    vals.append(_utc_now())

    try:
        with transaction.atomic():
            execute(
                "UPDATE `Ledgers` SET " + ", ".join(sets) + " WHERE `id` = %s AND `company_id` = %s",
                vals + [ledger_id, company_id],
            )
    except DatabaseError as err:
        return _err(_db_error_message(err))
    return [{"id": ledger_id, "status": "Success"}]


@sp("dbo.sp_Ledger", "DELETE")
def ledger_delete(params):
    ledger_id = _p_int(params, "Id")
    company_id = _p_int(params, "CompanyId")

    if not query_one("SELECT 1 AS `x` FROM `Ledgers` WHERE `id` = %s AND `company_id` = %s",
                     [ledger_id, company_id]):
        return _err("Ledger not found.")

    try:
        with transaction.atomic():
            execute("DELETE FROM `Ledgers` WHERE `id` = %s AND `company_id` = %s", [ledger_id, company_id])
    except DatabaseError as err:
        # SQL Server error 547 (FK violation) == MySQL/TiDB 1451 on a delete.
        if _db_error_number(err) in (1451, 1217):
            row = query_one("SELECT `name` FROM `Ledgers` WHERE `id` = %s", [ledger_id])
            err_name = row["name"] if row and row["name"] is not None else ""
            return _err('"' + err_name + '" is used by one or more tickets and can\'t be deleted.')
        return _err(_db_error_message(err))
    return [{"id": ledger_id, "status": "Success"}]


# ==========================================================================
# dbo.sp_CompanyMaster
# ==========================================================================

@sp("dbo.sp_CompanyMaster", "LIST")
def company_master_list(params):
    company_id = _p_int(params, "Id")
    if company_id is not None:
        return query("SELECT * FROM `CompanyMaster` WHERE `id` = %s", [company_id])
    # ORDER BY company_name under a case-insensitive collation.
    return query("SELECT * FROM `CompanyMaster` ORDER BY LOWER(`company_name`)")


_COMPANY_FIELDS = [
    # (column, @Param, kind, max_len)
    ("company_name", "CompanyName", "str", 200),
    ("mailing_name", "MailingName", "str", 200),
    ("address", "Address", "str", None),
    ("country", "Country", "str", 100),
    ("state", "State", "str", 100),
    ("pincode", "Pincode", "str", 6),
    ("telephone", "Telephone", "str", 20),
    ("mobile", "Mobile", "str", 10),
    ("email", "Email", "str", 200),
    ("financial_year_from", "FinancialYearFrom", "date", None),
    ("books_beginning_from", "BooksBeginningFrom", "date", None),
    ("gst_reg_type", "GstRegType", "str", 20),
    ("gst_no", "GstNo", "str", 15),
    ("pan_number", "PanNumber", "str", 10),
    ("cin_number", "CinNumber", "str", 25),
    ("tan_number", "TanNumber", "str", 15),
    ("hsn_sac", "HsnSac", "str", 20),
    ("currency_symbol", "CurrencySymbol", "str", 5),
    ("currency_name", "CurrencyName", "str", 50),
    ("decimal_places", "DecimalPlaces", "int", None),
    ("logo_base64", "LogoBase64", "str", None),
    ("seal_base64", "SealBase64", "str", None),
]


@sp("dbo.sp_CompanyMaster", "SAVE")
def company_master_save(params):
    company_id = _p_int(params, "Id")
    f = {}
    for col, key, kind, max_len in _COMPANY_FIELDS:
        if kind == "str":
            f[col] = _p_str(params, key, max_len)
        elif kind == "date":
            f[col] = _p_date(params, key)
        else:
            f[col] = _p_int(params, key)
    if f["decimal_places"] is not None and not -32768 <= f["decimal_places"] <= 32767:
        raise DataError("Arithmetic overflow error converting expression to data type smallint.")

    company_name = f["company_name"]
    if company_name is None or company_name.strip(" ") == "":
        return _err("company_name is required")

    if query_one(
            f"SELECT 1 AS `x` FROM `CompanyMaster` WHERE {_ci_eq('`company_name`')} "
            "AND (%s IS NULL OR `id` <> %s) LIMIT 1",
            [company_name, company_id, company_id]):
        return _err('Company "' + company_name + '" already exists.')

    # ISNULL(NULLIF(@X, ''), default) - '' = '   ' in SQL Server.
    if f["country"] is None or f["country"].rstrip(" ") == "":
        f["country"] = "India"
    if f["gst_reg_type"] is None or f["gst_reg_type"].rstrip(" ") == "":
        f["gst_reg_type"] = "Regular"
    if f["decimal_places"] is None:
        f["decimal_places"] = 2

    cols = [c for c, *_ in _COMPANY_FIELDS]
    vals = [f[c] for c in cols]
    now = _utc_now()
    was_created = False
    try:
        with transaction.atomic():
            if company_id is not None and query_one(
                    "SELECT 1 AS `x` FROM `CompanyMaster` WHERE `id` = %s", [company_id]):
                execute(
                    "UPDATE `CompanyMaster` SET " + ", ".join(f"`{c}` = %s" for c in cols)
                    + ", `updated_at` = %s WHERE `id` = %s",
                    vals + [now, company_id],
                )
                result_id = company_id
            elif company_id is not None:
                # IDENTITY_INSERT ON: insert with the caller's exact id.
                execute(
                    "INSERT INTO `CompanyMaster` (`id`, " + ", ".join(f"`{c}`" for c in cols)
                    + ", `created_at`, `updated_at`) VALUES (" + ", ".join(["%s"] * (len(cols) + 3)) + ")",
                    [company_id] + vals + [now, now],
                )
                result_id = company_id
                was_created = True
            else:
                _, result_id = execute(
                    "INSERT INTO `CompanyMaster` (" + ", ".join(f"`{c}`" for c in cols)
                    + ", `created_at`, `updated_at`) VALUES (" + ", ".join(["%s"] * (len(cols) + 2)) + ")",
                    vals + [now, now],
                )
                was_created = True
    except DatabaseError as err:
        return _err(_db_error_message(err))

    rows = query("SELECT * FROM `CompanyMaster` WHERE `id` = %s", [result_id])
    for r in rows:
        r["was_created"] = was_created
        r["status"] = "Success"
    return rows


@sp("dbo.sp_CompanyMaster", "DELETE")
def company_master_delete(params):
    company_id = _p_int(params, "Id")
    if not query_one("SELECT 1 AS `x` FROM `CompanyMaster` WHERE `id` = %s", [company_id]):
        return _err("Company not found.")
    try:
        with transaction.atomic():
            execute("DELETE FROM `CompanyMaster` WHERE `id` = %s", [company_id])
    except DatabaseError as err:
        return _err(_db_error_message(err))
    return [{"id": company_id, "status": "Success"}]
