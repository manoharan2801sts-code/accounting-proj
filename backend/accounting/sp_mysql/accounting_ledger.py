"""
MySQL / TiDB implementation for dbo.sp_AccountingLedger.
Handles financial year ledger summary tables (e.g. `26-27-accounting_ledger`)
and the Accounting_Ledger_Status table.
"""
import datetime
import json
import re

from django.db import connection
from . import sp, query, execute, query_one

VALID_YEAR_TABLE_RE = re.compile(r"^[0-9]{2}-[0-9]{2}-Accounting_Ledger$", re.IGNORECASE)
ALL_MONTHS = ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]


def _table_name_safe(name):
    clean = str(name or "").strip()
    if not VALID_YEAR_TABLE_RE.match(clean):
        raise ValueError(f'Invalid year table name "{name}".')
    return clean.lower()


@sp("dbo.sp_AccountingLedger", "SAVE_YEAR")
def save_year(params):
    company_id = int(params["CompanyId"])
    raw_tbl = params.get("TableName")
    tbl = _table_name_safe(raw_tbl)

    months_raw = params.get("MonthsJson") or "[]"
    months = json.loads(months_raw) if isinstance(months_raw, str) else list(months_raw)

    rows_raw = params.get("RowsJson") or "[]"
    rows = json.loads(rows_raw) if isinstance(rows_raw, str) else list(rows_raw)

    with connection.cursor() as cur:
        # Check if table exists
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = DATABASE() AND LOWER(table_name) = %s;
        """, [tbl])
        exists = cur.fetchone()[0] > 0

        if not exists:
            # Create table with all sent months
            month_col_defs = []
            for m in ALL_MONTHS:
                if m in months:
                    month_col_defs.append(f"`{m}_Cr` DECIMAL(19,4) NULL, `{m}_Dr` DECIMAL(19,4) NULL, `{m}_Balance` DECIMAL(19,4) NULL")
            col_str = (", " + ", ".join(month_col_defs)) if month_col_defs else ""
            create_sql = f"""
                CREATE TABLE `{tbl}` (
                    `company_id` INT NOT NULL,
                    `ledger_id` INT NOT NULL,
                    `Ledger_Name` VARCHAR(200) NULL,
                    `Opening_Balance` DECIMAL(19,4) NOT NULL
                    {col_str},
                    `Overall_Total` DECIMAL(19,4) NOT NULL,
                    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (`company_id`, `ledger_id`)
                );
            """
            cur.execute(create_sql)
        else:
            # Ensure all sent month columns exist
            cur.execute("""
                SELECT COLUMN_NAME FROM information_schema.columns
                WHERE table_schema = DATABASE() AND LOWER(table_name) = %s;
            """, [tbl])
            existing_cols = {r[0].lower() for r in cur.fetchall()}
            for m in months:
                for suffix in ["_Cr", "_Dr", "_Balance"]:
                    col_name = f"{m}{suffix}"
                    if col_name.lower() not in existing_cols:
                        cur.execute(f"ALTER TABLE `{tbl}` ADD COLUMN `{col_name}` DECIMAL(19,4) NULL;")
                        existing_cols.add(col_name.lower())

        # Delete existing company rows
        cur.execute(f"DELETE FROM `{tbl}` WHERE `company_id` = %s;", [company_id])

        # Insert new rows
        saved_count = 0
        if rows:
            for r in rows:
                cols = ["company_id", "ledger_id", "Ledger_Name", "Opening_Balance"]
                vals = [
                    company_id,
                    int(r.get("ledger_id")),
                    r.get("Ledger_Name"),
                    r.get("Opening_Balance") or 0
                ]
                for m in months:
                    cols.extend([f"{m}_Cr", f"{m}_Dr", f"{m}_Balance"])
                    vals.extend([
                        r.get(f"{m}_Cr"),
                        r.get(f"{m}_Dr"),
                        r.get(f"{m}_Balance"),
                    ])
                cols.append("Overall_Total")
                vals.append(r.get("Overall_Total") or 0)

                col_clause = ", ".join(f"`{c}`" for c in cols)
                val_placeholders = ", ".join(["%s"] * len(vals))
                cur.execute(f"REPLACE INTO `{tbl}` ({col_clause}) VALUES ({val_placeholders});", vals)
                saved_count += 1

    return [{"status": "Success", "table_name": raw_tbl, "rows_saved": saved_count}]


@sp("dbo.sp_AccountingLedger", "READ_YEAR")
def read_year(params):
    company_id = int(params["CompanyId"])
    tbl = _table_name_safe(params.get("TableName"))

    with connection.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = DATABASE() AND LOWER(table_name) = %s;
        """, [tbl])
        if cur.fetchone()[0] == 0:
            return []

    return query(f"SELECT * FROM `{tbl}` WHERE `company_id` = %s;", [company_id])


@sp("dbo.sp_AccountingLedger", "LIST_TABLES")
def list_tables(params):
    rows = query("""
        SELECT table_name AS table_name FROM information_schema.tables
        WHERE table_schema = DATABASE() AND LOWER(table_name) LIKE %s;
    """, ["%-accounting_ledger"])
    # Match the regex pattern: [0-9][0-9]-[0-9][0-9]-Accounting_Ledger
    out = []
    for r in rows:
        t = r.get("table_name") or r.get("TABLE_NAME")
        if t and VALID_YEAR_TABLE_RE.match(t):
            out.append({"table_name": t})
    return out


@sp("dbo.sp_AccountingLedger", "DOC_DATE")
def doc_date(params):
    doc_type = str(params.get("DocType") or "").lower()
    doc_id = int(params["DocId"])

    if doc_type == "voucher":
        row = query_one("SELECT company_id, voucher_date FROM vouchers WHERE id = %s;", [doc_id])
    elif doc_type == "ticket":
        row = query_one("SELECT company_id, voucher_date FROM journalvoucher WHERE source_ticket_id = %s ORDER BY id DESC LIMIT 1;", [doc_id])
    elif doc_type == "reschedule":
        row = query_one("SELECT company_id, voucher_date FROM journalvoucher WHERE source_reschedule_ticket_id = %s ORDER BY id DESC LIMIT 1;", [doc_id])
    elif doc_type == "cancellation":
        row = query_one("SELECT company_id, voucher_date FROM journalvoucher WHERE source_cancellation_ticket_id = %s ORDER BY id DESC LIMIT 1;", [doc_id])
    elif doc_type == "ssr":
        row = query_one("SELECT company_id, voucher_date FROM journalvoucher WHERE source_ssr_ticket_id = %s ORDER BY id DESC LIMIT 1;", [doc_id])
    elif doc_type == "misc":
        row = query_one("SELECT company_id, voucher_date FROM journalvoucher WHERE source_misc_ticket_id = %s ORDER BY id DESC LIMIT 1;", [doc_id])
    else:
        row = None

    if not row:
        return []
    return [{"company_id": row["company_id"], "voucher_date": row["voucher_date"]}]


@sp("dbo.sp_AccountingLedger", "DATE_RANGE")
def date_range(params):
    company_id = int(params["CompanyId"])
    row = query_one("""
        SELECT MIN(d) AS first_date, MAX(d) AS last_date FROM (
            SELECT voucher_date AS d FROM journalvoucher WHERE company_id = %s
            UNION ALL
            SELECT voucher_date AS d FROM vouchers WHERE company_id = %s
        ) x;
    """, [company_id, company_id])
    if not row:
        return [{"first_date": None, "last_date": None}]
    return [row]


@sp("dbo.sp_AccountingLedger", "GET_STATUS")
def get_status(params):
    company_id = int(params["CompanyId"])
    row = query_one("SELECT company_id, is_dirty, built_at FROM accounting_ledger_status WHERE company_id = %s;", [company_id])
    if not row:
        return []
    return [{
        "company_id": row["company_id"],
        "is_dirty": bool(row["is_dirty"]),
        "built_at": row["built_at"]
    }]


@sp("dbo.sp_AccountingLedger", "SET_STATUS")
def set_status(params):
    company_id = params.get("CompanyId")
    is_dirty = 1 if params.get("IsDirty") else 0
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if not is_dirty else None

    if company_id is None:
        if now:
            execute("UPDATE accounting_ledger_status SET is_dirty = %s, built_at = %s;", [is_dirty, now])
        else:
            execute("UPDATE accounting_ledger_status SET is_dirty = %s;", [is_dirty])
    else:
        cid = int(company_id)
        execute("""
            INSERT INTO accounting_ledger_status (company_id, is_dirty, built_at)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE is_dirty = VALUES(is_dirty), built_at = COALESCE(VALUES(built_at), built_at);
        """, [cid, is_dirty, now])

    return [{"status": "Success"}]
