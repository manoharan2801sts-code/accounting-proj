"""
dbo.sp_SSRTicket (backend/sp_reference/StoredProcedures.sql) for MySQL/TiDB.

sp_SSRTicket: LIST, GET_HEADER, GET_LINES, SAVE (insert or update header + lines + JournalVoucher ALS-n)
"""
import datetime
import json
import re
from decimal import Decimal, ROUND_HALF_UP

from django.db import DatabaseError, transaction

from . import SPThrow, bits, execute, query, query_one, sp, to_date

PROC = "dbo.sp_SSRTicket"

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

def _p_dec(params, key, p=14, s=2, default=Decimal("0.00")):
    v = params.get(key)
    if v is None or v == "":
        return default
    try:
        d = Decimal(str(v))
        fmt = Decimal("1." + "0" * s) if s > 0 else Decimal("1")
        return d.quantize(fmt, rounding=ROUND_HALF_UP)
    except Exception:
        return default

def _err(message):
    return [{"id": None, "status": "Error", "error": message}]

@sp("dbo.sp_SSRTicket", "LIST")
def ssr_ticket_list(params):
    company_id = _p_int(params, "CompanyId")
    return query(
        "SELECT sl.id, st.id AS ssr_ticket_id, st.invoice_number, st.invoice_date, "
        "st.ssr_reference AS booking_reference, st.airline_pnr, st.gds_pnr, "
        "cust.name AS customer_name, sl.ticket_no, sl.passenger_name, sl.sector, "
        "sl.ssr_items, sl.total_billed "
        "FROM `SSR_AL_TicketLines` sl "
        "INNER JOIN `SSR_AL_Tickets` st ON st.id = sl.ssr_ticket_id "
        "INNER JOIN `Ledgers` cust ON cust.id = st.customer_ledger_id "
        "WHERE st.company_id = %s "
        "ORDER BY st.id DESC, sl.id",
        [company_id],
    )

@sp("dbo.sp_SSRTicket", "LIST_FOR_ORIGINAL_LINES")
def ssr_ticket_list_for_original_lines(params):
    company_id = _p_int(params, "CompanyId")
    lines_json = params.get("LinesJson")
    if not lines_json:
        return []
    try:
        ids = json.loads(lines_json) if isinstance(lines_json, str) else list(lines_json)
    except Exception:
        ids = []
    if not ids:
        return []
    placeholders = ", ".join(["%s"] * len(ids))
    return query(
        f"SELECT sl.id, sl.original_ticket_line_id, sl.reschedule_line_id, "
        f"sl.seat, sl.meal, sl.baggage, sl.other_ssr "
        f"FROM `SSR_AL_TicketLines` sl "
        f"INNER JOIN `SSR_AL_Tickets` st ON st.id = sl.ssr_ticket_id "
        f"WHERE st.company_id = %s "
        f"AND sl.original_ticket_line_id IN ({placeholders}) "
        f"ORDER BY sl.id",
        [company_id] + [int(x) for x in ids],
    )

@sp("dbo.sp_SSRTicket", "GET_HEADER")
def ssr_ticket_get_header(params):
    ssr_id = _p_int(params, "Id")
    company_id = _p_int(params, "CompanyId")

    row = query_one(
        "SELECT 1 AS `x` FROM `SSR_AL_Tickets` WHERE `id` = %s AND `company_id` = %s",
        [ssr_id, company_id],
    )
    if not row:
        return _err("SSR Updation not found.")

    rows = query(
        "SELECT st.id, st.original_ticket_id, st.source_reschedule_ticket_id, st.invoice_number, st.invoice_date, "
        "st.invoice_type, st.booking_mode, st.booking_status, cust.name AS customer_name, st.customer_ledger_id, "
        "cust.state_name AS customer_state, st.travel_type, st.user_name, st.currency, st.roe, "
        "st.ssr_reference, st.ssr_ref_date, st.airline_pnr, st.gds_pnr, st.payment_mode, st.payment_gateway_ref, st.branch_name, "
        "ot.invoice_number AS original_invoice_number, rt.invoice_number AS source_reschedule_invoice_number, "
        "jv.id AS voucher_id, jv.voucher_no, jv.total_debit AS jv_total_debit, jv.total_credit AS jv_total_credit, "
        "'Success' AS status "
        "FROM `SSR_AL_Tickets` st "
        "INNER JOIN `Ledgers` cust ON cust.id = st.customer_ledger_id "
        "INNER JOIN `AL_Tickets` ot ON ot.id = st.original_ticket_id "
        "LEFT JOIN `Rescheduled_Al_Ticket` rt ON rt.id = st.source_reschedule_ticket_id "
        "LEFT JOIN `JournalVoucher` jv ON jv.source_ssr_ticket_id = st.id "
        "WHERE st.id = %s AND st.company_id = %s",
        [ssr_id, company_id],
    )
    return rows

@sp("dbo.sp_SSRTicket", "GET_LINES")
def ssr_ticket_get_lines(params):
    ssr_id = _p_int(params, "Id")
    company_id = _p_int(params, "CompanyId")
    return query(
        "SELECT sl.id, sl.original_ticket_line_id, sl.reschedule_line_id, sl.ticket_no, sl.passenger_name, "
        "sl.pax_type, sl.airline_category, sl.sector, sl.office_id, sl.supplier_ledger_id, "
        "supp.name AS supplier_name, supp.state_name AS supplier_state, sl.fop, sl.ssr_items, sl.ssr_ticket_numbers, "
        "sl.seat, sl.meal, sl.baggage, sl.other_ssr, sl.markup, sl.service_fee, "
        "sl.supp_markup, sl.supp_service_fee, sl.total_billed "
        "FROM `SSR_AL_TicketLines` sl "
        "INNER JOIN `SSR_AL_Tickets` st ON st.id = sl.ssr_ticket_id "
        "LEFT JOIN `Ledgers` supp ON supp.id = sl.supplier_ledger_id "
        "WHERE sl.ssr_ticket_id = %s AND st.company_id = %s "
        "ORDER BY sl.id",
        [ssr_id, company_id],
    )

@sp("dbo.sp_SSRTicket", "SAVE")
def ssr_ticket_save(params):
    ssr_id = _p_int(params, "Id")
    company_id = _p_int(params, "CompanyId")
    original_ticket_id = _p_int(params, "OriginalTicketId")
    source_reschedule_ticket_id = _p_int(params, "SourceRescheduleTicketId")
    customer_name = _p_str(params, "CustomerName", 150)
    branch_name = _p_str(params, "BranchName", 100) or "Chennai Branch"
    invoice_number = _p_str(params, "InvoiceNumber", 20)
    invoice_date = _p_date(params, "InvoiceDate")
    invoice_type = _p_str(params, "InvoiceType", 100)
    travel_type = _p_str(params, "TravelType", 20)
    user_name = _p_str(params, "UserName", 100)
    currency = _p_str(params, "Currency", 5) or "INR"
    roe = _p_dec(params, "Roe", 10, 4, default=Decimal("1.0000"))
    ssr_reference = _p_str(params, "SsrReference", 30)
    ssr_ref_date = _p_date(params, "SsrRefDate")
    airline_pnr = _p_str(params, "AirlinePnr", 13)
    gds_pnr = _p_str(params, "GdsPnr", 13)
    payment_mode = _p_str(params, "PaymentMode", 20)
    payment_gateway_ref = _p_str(params, "PaymentGatewayRef", 60)
    lines_json_raw = params.get("LinesJson")
    jv_narration = _p_str(params, "JvNarration", 250)
    jv_total_debit = _p_dec(params, "JvTotalDebit", 16, 2)
    jv_total_credit = _p_dec(params, "JvTotalCredit", 16, 2)

    if ssr_id is not None and not query_one(
        "SELECT 1 AS `x` FROM `SSR_AL_Tickets` WHERE `id` = %s AND `company_id` = %s",
        [ssr_id, company_id],
    ):
        return _err("SSR Updation not found.")

    cust_row = query_one(
        "SELECT `id` FROM `Ledgers` WHERE `company_id` = %s AND LOWER(TRIM(`name`)) = LOWER(TRIM(%s)) AND LOWER(TRIM(`ledger_category`)) = 'debtor'",
        [company_id, customer_name],
    )
    if not cust_row:
        return _err(f'"{customer_name or ""}" is not a real customer ledger (Sundry Debtors).')
    cust_ledger_id = cust_row["id"]

    if not query_one(
        "SELECT 1 AS `x` FROM `AL_Tickets` WHERE `id` = %s AND `company_id` = %s",
        [original_ticket_id, company_id],
    ):
        return _err("The original booking for this SSR was not found.")

    # Unique invoice number check across AL_Tickets, Rescheduled_Al_Ticket, Cancellation_AL_Tickets, SSR_AL_Tickets
    inv_exists = (
        query_one("SELECT 1 AS `x` FROM `AL_Tickets` WHERE `company_id` = %s AND `invoice_number` = %s", [company_id, invoice_number])
        or query_one("SELECT 1 AS `x` FROM `Rescheduled_Al_Ticket` WHERE `company_id` = %s AND `invoice_number` = %s", [company_id, invoice_number])
        or query_one("SELECT 1 AS `x` FROM `Cancellation_AL_Tickets` WHERE `company_id` = %s AND `invoice_number` = %s", [company_id, invoice_number])
        or query_one(
            "SELECT 1 AS `x` FROM `SSR_AL_Tickets` WHERE `company_id` = %s AND `invoice_number` = %s AND (%s IS NULL OR `id` <> %s)",
            [company_id, invoice_number, ssr_id, ssr_id],
        )
    )
    if inv_exists:
        return _err(f'Invoice Number "{invoice_number}" already exists.')

    if query_one(
        "SELECT 1 AS `x` FROM `SSR_AL_Tickets` WHERE `company_id` = %s AND `ssr_reference` = %s AND (%s IS NULL OR `id` <> %s)",
        [company_id, ssr_reference, ssr_id, ssr_id],
    ):
        return _err(f'SSR Reference "{ssr_reference}" already exists.')

    lines = json.loads(lines_json_raw) if isinstance(lines_json_raw, str) else (lines_json_raw or [])

    # Validate each line's passenger & supplier
    for l in lines:
        orig_line_id = l.get("original_ticket_line_id")
        t_no = l.get("ticket_no") or "?"
        if not query_one(
            "SELECT 1 AS `x` FROM `AL_TicketLines` WHERE `id` = %s AND `ticket_id` = %s",
            [orig_line_id, original_ticket_id],
        ):
            return _err(f"Ticket No. {t_no} is not a passenger of the original booking.")

        supp_name = l.get("supplier_name")
        if supp_name:
            if not query_one(
                "SELECT 1 AS `x` FROM `Ledgers` WHERE `company_id` = %s AND LOWER(TRIM(`name`)) = LOWER(TRIM(%s)) AND LOWER(TRIM(`ledger_category`)) = 'creditor'",
                [company_id, supp_name],
            ):
                return _err(f'"{supp_name}" is not a real supplier ledger (Sundry Creditors).')

    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    try:
        with transaction.atomic():
            if ssr_id is None:
                _, result_id = execute(
                    "INSERT INTO `SSR_AL_Tickets` "
                    "(`company_id`, `branch_name`, `original_ticket_id`, `source_reschedule_ticket_id`, "
                    "`invoice_number`, `invoice_date`, `invoice_type`, `booking_mode`, `booking_status`, "
                    "`customer_ledger_id`, `travel_type`, `user_name`, `currency`, `roe`, "
                    "`ssr_reference`, `ssr_ref_date`, `airline_pnr`, `gds_pnr`, `payment_mode`, `payment_gateway_ref`, `created_at`, `updated_at`) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, 'Manual', 'SSR Updated', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    [
                        company_id, branch_name, original_ticket_id, source_reschedule_ticket_id,
                        invoice_number, invoice_date, invoice_type,
                        cust_ledger_id, travel_type, user_name, currency, roe,
                        ssr_reference, ssr_ref_date, airline_pnr, gds_pnr, payment_mode, payment_gateway_ref, now, now,
                    ],
                )
            else:
                result_id = ssr_id
                execute(
                    "UPDATE `SSR_AL_Tickets` SET "
                    "`invoice_number` = %s, `invoice_date` = %s, `invoice_type` = %s, "
                    "`user_name` = %s, `ssr_reference` = %s, `ssr_ref_date` = %s, "
                    "`payment_mode` = %s, `payment_gateway_ref` = %s, `updated_at` = %s "
                    "WHERE `id` = %s AND `company_id` = %s",
                    [
                        invoice_number, invoice_date, invoice_type,
                        user_name, ssr_reference, ssr_ref_date,
                        payment_mode, payment_gateway_ref, now, ssr_id, company_id,
                    ],
                )
                execute("DELETE FROM `SSR_AL_TicketLines` WHERE `ssr_ticket_id` = %s", [ssr_id])

            inserted_line_ids = []
            for l in lines:
                supp_name = l.get("supplier_name")
                supp_id = None
                if supp_name:
                    s_row = query_one(
                        "SELECT `id` FROM `Ledgers` WHERE `company_id` = %s AND LOWER(TRIM(`name`)) = LOWER(TRIM(%s)) AND LOWER(TRIM(`ledger_category`)) = 'creditor'",
                        [company_id, supp_name],
                    )
                    supp_id = s_row["id"] if s_row else None

                ssr_items_val = l.get("ssr_items")
                if isinstance(ssr_items_val, (dict, list)):
                    ssr_items_val = json.dumps(ssr_items_val)

                ssr_ticket_numbers_val = l.get("ssr_ticket_numbers")
                if isinstance(ssr_ticket_numbers_val, (dict, list)):
                    ssr_ticket_numbers_val = json.dumps(ssr_ticket_numbers_val)

                _, lid = execute(
                    "INSERT INTO `SSR_AL_TicketLines` "
                    "(`ssr_ticket_id`, `original_ticket_line_id`, `reschedule_line_id`, `ticket_no`, "
                    "`passenger_name`, `pax_type`, `airline_category`, `sector`, `office_id`, "
                    "`supplier_ledger_id`, `fop`, `ssr_items`, `ssr_ticket_numbers`, `seat`, `meal`, `baggage`, `other_ssr`, "
                    "`markup`, `service_fee`, `supp_markup`, `supp_service_fee`, `total_billed`) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    [
                        result_id, l.get("original_ticket_line_id"), l.get("reschedule_line_id"),
                        l.get("ticket_no"), l.get("passenger_name"), l.get("pax_type"),
                        l.get("airline_category"), l.get("sector"), l.get("office_id"),
                        supp_id, l.get("fop"), ssr_items_val, ssr_ticket_numbers_val,
                        _p_dec(l, "seat"), _p_dec(l, "meal"), _p_dec(l, "baggage"), _p_dec(l, "other_ssr"),
                        _p_dec(l, "markup"), _p_dec(l, "service_fee"), _p_dec(l, "supp_markup"), _p_dec(l, "supp_service_fee"),
                        _p_dec(l, "total_billed"),
                    ],
                )
                inserted_line_ids.append(str(lid))

            # JV Upsert
            jv_row = query_one(
                "SELECT `id`, `voucher_no` FROM `JournalVoucher` WHERE `source_ssr_ticket_id` = %s",
                [result_id],
            )
            if jv_row:
                voucher_id = jv_row["id"]
                voucher_no = jv_row["voucher_no"]
                execute(
                    "UPDATE `JournalVoucher` SET "
                    "`voucher_date` = %s, `narration` = %s, `total_debit` = %s, "
                    "`total_credit` = %s, `updated_at` = %s "
                    "WHERE `id` = %s",
                    [invoice_date, jv_narration, jv_total_debit, jv_total_credit, now, voucher_id],
                )
            else:
                existing_jvs = query(
                    "SELECT `voucher_no` FROM `JournalVoucher` WHERE `company_id` = %s AND `category` = 'AIRLINE_SSR' AND `voucher_no` LIKE 'ALS-%%'",
                    [company_id],
                )
                max_n = 0
                for ej in existing_jvs:
                    vno = ej.get("voucher_no") or ""
                    m = re.match(r"^ALS-(\d+)$", vno)
                    if m:
                        try:
                            num = int(m.group(1))
                            if num > max_n:
                                max_n = num
                        except ValueError:
                            pass
                voucher_no = f"ALS-{max_n + 1}"
                _, voucher_id = execute(
                    "INSERT INTO `JournalVoucher` "
                    "(`company_id`, `branch_name`, `voucher_type`, `voucher_date`, `narration`, `category`, "
                    "`voucher_no`, `source_ssr_ticket_id`, `total_debit`, `total_credit`, `lines_json`, `created_at`, `updated_at`) "
                    "VALUES (%s, %s, 'Tax Invoice', %s, %s, 'AIRLINE_SSR', %s, %s, %s, %s, '[]', %s, %s)",
                    [
                        company_id, branch_name, invoice_date, jv_narration,
                        voucher_no, result_id, jv_total_debit, jv_total_credit, now, now,
                    ],
                )

            line_ids_str = ",".join(inserted_line_ids)
            return [{
                "id": result_id,
                "line_ids": line_ids_str,
                "voucher_id": voucher_id,
                "voucher_no": voucher_no,
                "status": "Success",
            }]
    except DatabaseError as err:
        return _err(str(err))
