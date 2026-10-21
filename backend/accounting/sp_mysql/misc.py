"""
dbo.sp_MiscTransaction (backend/sp_reference/StoredProcedures.sql) for MySQL/TiDB.

sp_MiscTransaction: LIST, GET, SAVE
"""
from decimal import Decimal, ROUND_HALF_UP

from django.db import DatabaseError, transaction

from . import SPThrow, execute, query, query_one, sp, to_date

PROC = "dbo.sp_MiscTransaction"


def _p_int(params, key):
    v = params.get(key)
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        raise SPThrow(f"Cannot convert '{v}' to int.")


def _p_str(params, key, max_len=None):
    v = params.get(key)
    if v is None:
        return None
    s = str(v)
    if max_len:
        s = s[:max_len]
    return s


def _p_date(params, key):
    v = params.get(key)
    if v is None:
        return None
    return to_date(v)


def _p_dec(params, key, default=Decimal("0.00")):
    v = params.get(key)
    if v is None or v == "":
        return default
    try:
        d = Decimal(str(v))
        return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return default


def _err(message):
    return [{"id": None, "status": "Error", "error": message}]


@sp(PROC, "LIST")
def misc_list(params):
    company_id = _p_int(params, "CompanyId")
    sql = """
        SELECT m.id, m.invoice_number, m.invoice_date, m.invoice_type, m.status, m.reference, m.ref_date,
               cust.name AS customer_name, supp.name AS supplier_name, m.description, m.total_billed
        FROM Misc_Transactions m
        INNER JOIN Ledgers cust ON cust.id = m.customer_ledger_id
        INNER JOIN Ledgers supp ON supp.id = m.supplier_ledger_id
        WHERE m.company_id = %s
        ORDER BY m.id DESC
    """
    return query(sql, [company_id])


@sp(PROC, "GET")
def misc_get(params):
    mid = _p_int(params, "Id")
    company_id = _p_int(params, "CompanyId")
    sql = """
        SELECT m.id, m.branch_name, m.invoice_number, m.invoice_date, m.invoice_type, m.status AS misc_status,
               m.user_name, m.reference, m.ref_date, m.payment_mode, m.payment_gateway_ref, m.currency,
               m.customer_ledger_id, cust.name AS customer_name, cust.state_name AS customer_state,
               m.supplier_ledger_id, supp.name AS supplier_name, supp.state_name AS supplier_state,
               m.description, m.base_amount, m.other_taxes, m.markup, m.service_fee, m.supp_markup, m.supp_service_fee, m.total_billed,
               jv.id AS voucher_id, jv.voucher_no, 'Success' AS status
        FROM Misc_Transactions m
        INNER JOIN Ledgers cust ON cust.id = m.customer_ledger_id
        INNER JOIN Ledgers supp ON supp.id = m.supplier_ledger_id
        LEFT JOIN JournalVoucher jv ON jv.source_misc_ticket_id = m.id
        WHERE m.id = %s AND m.company_id = %s
    """
    row = query_one(sql, [mid, company_id])
    if not row:
        return _err("Miscellaneous transaction not found.")
    return [row]


@sp(PROC, "SAVE")
def misc_save(params):
    mid = _p_int(params, "Id")
    company_id = _p_int(params, "CompanyId")
    branch_name = _p_str(params, "BranchName", 100)
    invoice_number = _p_str(params, "InvoiceNumber", 20)
    invoice_date = _p_date(params, "InvoiceDate")
    invoice_type = _p_str(params, "InvoiceType", 100)
    status = _p_str(params, "Status", 20) or "Confirmed"
    user_name = _p_str(params, "UserName", 100)
    reference = _p_str(params, "Reference", 30)
    ref_date = _p_date(params, "RefDate")
    payment_mode = _p_str(params, "PaymentMode", 20)
    payment_gateway_ref = _p_str(params, "PaymentGatewayRef", 60)
    currency = _p_str(params, "Currency", 5) or "INR"
    customer_name = _p_str(params, "CustomerName", 150)
    supplier_name = _p_str(params, "SupplierName", 150)
    description = params.get("Description")

    base_amount = _p_dec(params, "BaseAmount")
    other_taxes = _p_dec(params, "OtherTaxes")
    markup = _p_dec(params, "Markup")
    service_fee = _p_dec(params, "ServiceFee")
    supp_markup = _p_dec(params, "SuppMarkup")
    supp_service_fee = _p_dec(params, "SuppServiceFee")
    total_billed = _p_dec(params, "TotalBilled")

    jv_narration = _p_str(params, "JvNarration", 250)
    jv_total_debit = _p_dec(params, "JvTotalDebit")
    jv_total_credit = _p_dec(params, "JvTotalCredit")

    if mid is not None:
        if not query_one("SELECT 1 AS x FROM Misc_Transactions WHERE id = %s AND company_id = %s", [mid, company_id]):
            return _err("Miscellaneous transaction not found.")

    if status not in ("Confirmed", "Cancelled"):
        return _err("Status must be Confirmed or Cancelled.")

    cust_row = query_one(
        "SELECT id FROM Ledgers WHERE company_id = %s AND name = %s AND ledger_category = 'DEBTOR'",
        [company_id, customer_name],
    )
    if not cust_row:
        return _err(f'"{customer_name or ""}" is not a real customer ledger (Sundry Debtors).')
    cust_ledger_id = cust_row["id"]

    supp_row = query_one(
        "SELECT id FROM Ledgers WHERE company_id = %s AND name = %s AND ledger_category = 'CREDITOR'",
        [company_id, supplier_name],
    )
    if not supp_row:
        return _err(f'"{supplier_name or ""}" is not a real supplier ledger (Sundry Creditors).')
    supp_ledger_id = supp_row["id"]

    # Invoice number uniqueness
    dup_inv = (
        query_one("SELECT 1 AS x FROM AL_Tickets WHERE company_id = %s AND invoice_number = %s", [company_id, invoice_number])
        or query_one("SELECT 1 AS x FROM Rescheduled_Al_Ticket WHERE company_id = %s AND invoice_number = %s", [company_id, invoice_number])
        or query_one("SELECT 1 AS x FROM Cancellation_AL_Tickets WHERE company_id = %s AND invoice_number = %s", [company_id, invoice_number])
        or query_one("SELECT 1 AS x FROM SSR_AL_Tickets WHERE company_id = %s AND invoice_number = %s", [company_id, invoice_number])
        or query_one("SELECT 1 AS x FROM Misc_Transactions WHERE company_id = %s AND invoice_number = %s AND (%s IS NULL OR id <> %s)", [company_id, invoice_number, mid, mid])
    )
    if dup_inv:
        return _err(f'Invoice Number "{invoice_number}" already exists.')

    dup_ref = query_one(
        "SELECT 1 AS x FROM Misc_Transactions WHERE company_id = %s AND reference = %s AND (%s IS NULL OR id <> %s)",
        [company_id, reference, mid, mid],
    )
    if dup_ref:
        return _err(f'Reference "{reference}" already exists.')

    try:
        with transaction.atomic():
            if mid is None:
                insert_sql = """
                    INSERT INTO Misc_Transactions
                        (company_id, branch_name, invoice_number, invoice_date, invoice_type, status, user_name, reference, ref_date,
                         payment_mode, payment_gateway_ref, currency, customer_ledger_id, supplier_ledger_id, description,
                         base_amount, other_taxes, markup, service_fee, supp_markup, supp_service_fee, total_billed, created_at, updated_at)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                         %s, %s, %s, %s, %s, %s,
                         %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))
                """
                _, result_id = execute(insert_sql, [
                    company_id, branch_name, invoice_number, invoice_date, invoice_type, status, user_name, reference, ref_date,
                    payment_mode, payment_gateway_ref, currency, cust_ledger_id, supp_ledger_id, description,
                    base_amount, other_taxes, markup, service_fee, supp_markup, supp_service_fee, total_billed,
                ])
            else:
                result_id = mid
                update_sql = """
                    UPDATE Misc_Transactions
                    SET invoice_number = %s, invoice_date = %s, invoice_type = %s, status = %s,
                        user_name = %s, reference = %s, ref_date = %s, payment_mode = %s,
                        payment_gateway_ref = %s, customer_ledger_id = %s, supplier_ledger_id = %s,
                        description = %s, base_amount = %s, other_taxes = %s,
                        markup = %s, service_fee = %s, supp_markup = %s,
                        supp_service_fee = %s, total_billed = %s, updated_at = UTC_TIMESTAMP(6)
                    WHERE id = %s AND company_id = %s
                """
                execute(update_sql, [
                    invoice_number, invoice_date, invoice_type, status,
                    user_name, reference, ref_date, payment_mode,
                    payment_gateway_ref, cust_ledger_id, supp_ledger_id,
                    description, base_amount, other_taxes,
                    markup, service_fee, supp_markup,
                    supp_service_fee, total_billed, mid, company_id,
                ])

            jv_row = query_one("SELECT id, voucher_no FROM JournalVoucher WHERE source_misc_ticket_id = %s", [result_id])
            voucher_id = jv_row["id"] if jv_row else None
            voucher_no = jv_row["voucher_no"] if jv_row else None

            if status == "Cancelled":
                if voucher_id is not None:
                    execute("DELETE FROM JournalVoucher WHERE id = %s", [voucher_id])
                voucher_id = None
                voucher_no = None
            elif voucher_id is not None:
                execute(
                    "UPDATE JournalVoucher SET voucher_date = %s, narration = %s, total_debit = %s, total_credit = %s, updated_at = UTC_TIMESTAMP(6) WHERE id = %s",
                    [invoice_date, jv_narration, jv_total_debit, jv_total_credit, voucher_id],
                )
            else:
                max_row = query_one(
                    "SELECT COALESCE(MAX(CAST(SUBSTRING(voucher_no, 5) AS UNSIGNED)), 0) AS max_num "
                    "FROM JournalVoucher "
                    "WHERE company_id = %s AND category = 'MISC' AND voucher_no LIKE 'MSC-%%'",
                    [company_id],
                )
                next_num = (max_row["max_num"] if max_row else 0) + 1
                voucher_no = f"MSC-{next_num}"
                _, voucher_id = execute(
                    """
                    INSERT INTO JournalVoucher
                        (company_id, branch_name, voucher_type, voucher_date, narration, category, voucher_no,
                         source_misc_ticket_id, total_debit, total_credit, lines_json, created_at, updated_at)
                    VALUES
                        (%s, %s, 'Tax Invoice', %s, %s, 'MISC', %s, %s, %s, %s, '[]', UTC_TIMESTAMP(6), UTC_TIMESTAMP(6))
                    """,
                    [company_id, branch_name or "Chennai Branch", invoice_date, jv_narration, voucher_no, result_id, jv_total_debit, jv_total_credit],
                )

        return [{"id": result_id, "voucher_id": voucher_id, "voucher_no": voucher_no, "status": "Success"}]
    except DatabaseError as exc:
        return _err(str(exc))
