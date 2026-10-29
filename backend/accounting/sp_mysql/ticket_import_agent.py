"""
ticket_import_agent.py — MySQL / TiDB emulation for Auto Push Ticket Import,
PG Master backdating, Document Attributes, GST line amounts, and the
Automated Database Scheduler (Airline_Agent).

Mirrors the T-SQL implementations in backend/StoredProcedures.sql.
"""
import datetime
import json
from decimal import Decimal
from django.db import transaction, connection

from . import sp, query, query_one, execute, bits, to_bool_param, to_decimal, to_date, error_row


def _p_int(v):
    if v is None or v == "":
        return None
    return int(v)


def _p_str(v, maxlen=None):
    if v is None:
        return None
    s = str(v).strip()
    if maxlen:
        s = s[:maxlen]
    return s


def _json_load(v):
    if not v:
        return []
    if isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return []


# ===========================================================================
# dbo.sp_DocumentAttribute
# ===========================================================================

@sp("dbo.sp_DocumentAttribute", "LIST")
def doc_attribute_list(p):
    doc_type = _p_str(p.get("DocType"), 20)
    doc_id = _p_int(p.get("DocId"))
    sql = """
        SELECT attribute_id, company_id, doc_type, doc_id, invoice_number, sort_order, field_name, field_value
        FROM Ticket_Document_Attribute
        WHERE doc_type = %s AND doc_id = %s
        ORDER BY sort_order, attribute_id
    """
    return query(sql, [doc_type, doc_id])


@sp("dbo.sp_DocumentAttribute", "SAVE_JSON")
def doc_attribute_save_json(p):
    company_id = _p_int(p.get("CompanyId"))
    doc_type = _p_str(p.get("DocType"), 20)
    doc_id = _p_int(p.get("DocId"))
    invoice_number = _p_str(p.get("InvoiceNumber"), 20)
    rows = _json_load(p.get("RowsJson"))

    with transaction.atomic():
        execute("DELETE FROM Ticket_Document_Attribute WHERE doc_type = %s AND doc_id = %s", [doc_type, doc_id])
        sort_order = 1
        for r in rows:
            fname = _p_str(r.get("field_name"), 100)
            fval = _p_str(r.get("field_value"), 500)
            if not fname:
                continue
            execute("""
                INSERT INTO Ticket_Document_Attribute
                    (company_id, doc_type, doc_id, invoice_number, sort_order, field_name, field_value, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6))
            """, [company_id, doc_type, doc_id, invoice_number, sort_order, fname, fval])
            sort_order += 1

    return query("SELECT * FROM Ticket_Document_Attribute WHERE doc_type = %s AND doc_id = %s ORDER BY sort_order", [doc_type, doc_id])


# ===========================================================================
# dbo.sp_TicketLineGstAmount
# ===========================================================================

@sp("dbo.sp_TicketLineGstAmount", "LIST")
def ticket_line_gst_list(p):
    return query("""
        SELECT line_type, doc_id, ticket_no, service_fee_gst, addl_service_fee_gst, ssr_service_fee_gst,
               supp_service_fee_gst, supp_addl_service_fee_gst, supp_ssr_service_fee_gst
        FROM Ticket_Line_Gst_Amount
    """)


@sp("dbo.sp_TicketLineGstAmount", "SAVE_JSON")
def ticket_line_gst_save_json(p):
    rows = _json_load(p.get("RowsJson"))
    with transaction.atomic():
        for r in rows:
            l_type = _p_str(r.get("line_type"), 20)
            doc_id = _p_int(r.get("doc_id"))
            t_no = _p_str(r.get("ticket_no"), 30)
            if not (l_type and doc_id and t_no):
                continue
            execute("""
                INSERT INTO Ticket_Line_Gst_Amount
                    (line_type, doc_id, ticket_no, service_fee_gst, addl_service_fee_gst, ssr_service_fee_gst,
                     supp_service_fee_gst, supp_addl_service_fee_gst, supp_ssr_service_fee_gst, source, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'API', UTC_TIMESTAMP(6))
                ON DUPLICATE KEY UPDATE
                    service_fee_gst = VALUES(service_fee_gst),
                    addl_service_fee_gst = VALUES(addl_service_fee_gst),
                    ssr_service_fee_gst = VALUES(ssr_service_fee_gst),
                    supp_service_fee_gst = VALUES(supp_service_fee_gst),
                    supp_addl_service_fee_gst = VALUES(supp_addl_service_fee_gst),
                    supp_ssr_service_fee_gst = VALUES(supp_ssr_service_fee_gst)
            """, [
                l_type, doc_id, t_no,
                to_decimal(r.get("service_fee_gst")), to_decimal(r.get("addl_service_fee_gst")), to_decimal(r.get("ssr_service_fee_gst")),
                to_decimal(r.get("supp_service_fee_gst")), to_decimal(r.get("supp_addl_service_fee_gst")), to_decimal(r.get("supp_ssr_service_fee_gst"))
            ])
    return [{"status": "Success"}]


@sp("dbo.sp_TicketLineGstAmount", "DELETE_DOCUMENT")
def ticket_line_gst_delete_doc(p):
    l_type = _p_str(p.get("LineType"), 20)
    doc_id = _p_int(p.get("DocId"))
    cnt, _ = execute("DELETE FROM Ticket_Line_Gst_Amount WHERE line_type = %s AND doc_id = %s", [l_type, doc_id])
    return [{"deleted": cnt}]


# ===========================================================================
# dbo.sp_MasterMappingPin
# ===========================================================================

@sp("dbo.sp_MasterMappingPin", "LIST")
def master_mapping_pin_list(p):
    company_id = _p_int(p.get("CompanyId"))
    sql = """
        SELECT p.product_type, p.field_name, p.doc_type, p.doc_id, p.doc_date, p.ledger_id,
               p.ledger_name, p.masters_category, l.gst_rate_percentage
        FROM MasterMappingPin p
        LEFT JOIN Ledgers l ON l.id = p.ledger_id
        WHERE p.company_id = %s
    """
    return query(sql, [company_id])


@sp("dbo.sp_MasterMappingPin", "DOCUMENTS")
def master_mapping_pin_documents(p):
    company_id = _p_int(p.get("CompanyId"))
    from_date = to_date(p.get("FromDate"))
    sql = """
        SELECT 'Booking' AS doc_type, id AS doc_id, invoice_number, invoice_date AS doc_date FROM AL_Tickets
        WHERE company_id = %s AND invoice_date >= %s
        UNION ALL
        SELECT 'Reschedule', id, invoice_number, invoice_date FROM Rescheduled_Al_Ticket
        WHERE company_id = %s AND invoice_date >= %s
        UNION ALL
        SELECT 'Cancellation', id, invoice_number, invoice_date FROM Cancellation_AL_Tickets
        WHERE company_id = %s AND invoice_date >= %s
        UNION ALL
        SELECT 'SSR Updation', id, invoice_number, invoice_date FROM SSR_AL_Tickets
        WHERE company_id = %s AND invoice_date >= %s
        UNION ALL
        SELECT 'Miscellaneous', id, voucher_no, transaction_date FROM Misc_Transactions
        WHERE company_id = %s AND transaction_date >= %s
        ORDER BY doc_date, doc_type, doc_id
    """
    return query(sql, [company_id, from_date, company_id, from_date, company_id, from_date, company_id, from_date, company_id, from_date])


@sp("dbo.sp_MasterMappingPin", "SAVE_JSON")
def master_mapping_pin_save_json(p):
    rows = _json_load(p.get("RowsJson"))
    with transaction.atomic():
        for r in rows:
            cid = _p_int(r.get("company_id"))
            ptype = _p_str(r.get("product_type"), 20)
            fname = _p_str(r.get("field_name"), 100)
            dtype = _p_str(r.get("doc_type"), 20)
            did = _p_int(r.get("doc_id"))
            ddate = to_date(r.get("doc_date"))
            lid = _p_int(r.get("ledger_id"))
            lname = _p_str(r.get("ledger_name"), 200)
            mcat = _p_str(r.get("masters_category"), 40)
            efrom = to_date(r.get("effective_from"))
            execute("""
                INSERT INTO MasterMappingPin
                    (company_id, product_type, field_name, doc_type, doc_id, doc_date, ledger_id, ledger_name, masters_category, effective_from, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6))
                ON DUPLICATE KEY UPDATE ledger_id = VALUES(ledger_id), ledger_name = VALUES(ledger_name)
            """, [cid, ptype, fname, dtype, did, ddate, lid, lname, mcat, efrom])
    return [{"status": "Success"}]


@sp("dbo.sp_MasterMappingPin", "DELETE_FIELD")
def master_mapping_pin_delete_field(p):
    company_id = _p_int(p.get("CompanyId"))
    fname = _p_str(p.get("FieldName"), 100)
    from_date = to_date(p.get("FromDate"))
    cnt, _ = execute("""
        DELETE FROM MasterMappingPin
        WHERE company_id = %s AND field_name = %s AND (%s IS NULL OR doc_date >= %s)
    """, [company_id, fname, from_date, from_date])
    return [{"deleted": cnt}]


@sp("dbo.sp_MasterMappingPin", "DELETE_DOCUMENT")
def master_mapping_pin_delete_doc(p):
    dtype = _p_str(p.get("DocType"), 20)
    did = _p_int(p.get("DocId"))
    cnt, _ = execute("DELETE FROM MasterMappingPin WHERE doc_type = %s AND doc_id = %s", [dtype, did])
    return [{"deleted": cnt}]


@sp("dbo.sp_MasterMappingPin", "DELETE_HISTORY_AFTER")
def master_mapping_pin_delete_history(p):
    company_id = _p_int(p.get("CompanyId"))
    ptype = _p_str(p.get("ProductType"), 20)
    fname = _p_str(p.get("FieldName"), 100)
    from_date = to_date(p.get("FromDate"))
    cnt, _ = execute("""
        DELETE FROM MasterMappingHistory
        WHERE company_id = %s AND product_type = %s AND field_name = %s AND effective_from > %s
    """, [company_id, ptype, fname, from_date])
    return [{"deleted": cnt}]


# ===========================================================================
# dbo.sp_PGMasterBackdate
# ===========================================================================

@sp("dbo.sp_PGMasterBackdate", "DOCUMENTS")
def pg_master_backdate_docs(p):
    company_id = _p_int(p.get("CompanyId"))
    gateway = _p_str(p.get("GatewayName"), 100)
    from_date = to_date(p.get("FromDate"))
    sql = """
        SELECT 'Booking' AS doc_type, id AS doc_id, invoice_number, invoice_date AS doc_date FROM AL_Tickets
        WHERE company_id = %s AND payment_gateway_ref = %s AND (%s IS NULL OR invoice_date >= %s)
        UNION ALL
        SELECT 'Reschedule', id, invoice_number, invoice_date FROM Rescheduled_Al_Ticket
        WHERE company_id = %s AND payment_gateway_ref = %s AND (%s IS NULL OR invoice_date >= %s)
        UNION ALL
        SELECT 'Cancellation', id, invoice_number, invoice_date FROM Cancellation_AL_Tickets
        WHERE company_id = %s AND payment_gateway_ref = %s AND (%s IS NULL OR invoice_date >= %s)
        ORDER BY doc_date, doc_type, doc_id
    """
    return query(sql, [company_id, gateway, from_date, from_date, company_id, gateway, from_date, from_date, company_id, gateway, from_date, from_date])


@sp("dbo.sp_PGMasterBackdate", "LATER_HISTORY")
def pg_master_backdate_later_history(p):
    company_id = _p_int(p.get("CompanyId"))
    gateway = _p_str(p.get("GatewayName"), 100)
    from_date = to_date(p.get("FromDate"))
    sql = """
        SELECT * FROM PGMasterHistory
        WHERE company_id = %s AND gateway_name = %s AND effective_from >= %s
        ORDER BY effective_from
    """
    return query(sql, [company_id, gateway, from_date])


@sp("dbo.sp_PGMasterBackdate", "DELETE_HISTORY_AFTER")
def pg_master_backdate_delete_history(p):
    company_id = _p_int(p.get("CompanyId"))
    gateway = _p_str(p.get("GatewayName"), 100)
    from_date = to_date(p.get("FromDate"))
    cnt, _ = execute("""
        DELETE FROM PGMasterHistory
        WHERE company_id = %s AND gateway_name = %s AND effective_from > %s
    """, [company_id, gateway, from_date])
    return [{"deleted": cnt}]


@sp("dbo.sp_PGMasterBackdate", "PINS_SAVE_JSON")
def pg_master_backdate_pins_save(p):
    rows = _json_load(p.get("RowsJson"))
    with transaction.atomic():
        for r in rows:
            cid = _p_int(r.get("company_id"))
            gname = _p_str(r.get("gateway_name"), 100)
            dtype = _p_str(r.get("doc_type"), 20)
            did = _p_int(r.get("doc_id"))
            ddate = to_date(r.get("doc_date"))
            pm_id = _p_int(r.get("payment_master_ledger_id"))
            pm_name = _p_str(r.get("payment_master_ledger_name"), 200)
            pg_id = _p_int(r.get("pg_charges_master_ledger_id"))
            pg_name = _p_str(r.get("pg_charges_master_ledger_name"), 200)
            pct = to_decimal(r.get("pg_charges_percentage"))
            efrom = to_date(r.get("effective_from"))
            execute("""
                INSERT INTO PGMasterPin
                    (company_id, gateway_name, doc_type, doc_id, doc_date, payment_master_ledger_id,
                     payment_master_ledger_name, pg_charges_master_ledger_id, pg_charges_master_ledger_name,
                     pg_charges_percentage, effective_from, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, UTC_TIMESTAMP(6))
                ON DUPLICATE KEY UPDATE
                    payment_master_ledger_id = VALUES(payment_master_ledger_id),
                    payment_master_ledger_name = VALUES(payment_master_ledger_name),
                    pg_charges_master_ledger_id = VALUES(pg_charges_master_ledger_id),
                    pg_charges_master_ledger_name = VALUES(pg_charges_master_ledger_name),
                    pg_charges_percentage = VALUES(pg_charges_percentage)
            """, [cid, gname, dtype, did, ddate, pm_id, pm_name, pg_id, pg_name, pct, efrom])
    return [{"status": "Success"}]


@sp("dbo.sp_PGMasterBackdate", "PINS_DELETE_GATEWAY")
def pg_master_backdate_pins_delete_gw(p):
    company_id = _p_int(p.get("CompanyId"))
    gateway = _p_str(p.get("GatewayName"), 100)
    from_date = to_date(p.get("FromDate"))
    cnt, _ = execute("""
        DELETE FROM PGMasterPin
        WHERE company_id = %s AND gateway_name = %s AND (%s IS NULL OR doc_date >= %s)
    """, [company_id, gateway, from_date, from_date])
    return [{"deleted": cnt}]


@sp("dbo.sp_PGMasterBackdate", "PINS_DELETE_DOCUMENT")
def pg_master_backdate_pins_delete_doc(p):
    dtype = _p_str(p.get("DocType"), 20)
    did = _p_int(p.get("DocId"))
    cnt, _ = execute("DELETE FROM PGMasterPin WHERE doc_type = %s AND doc_id = %s", [dtype, did])
    return [{"deleted": cnt}]


# ===========================================================================
# dbo.sp_TicketImport_Stage
# ===========================================================================

@sp("dbo.sp_TicketImport_Stage", "INSERT_JSON")
def ticket_import_stage_insert(p):
    rows = _json_load(p.get("RowsJson"))
    batch_id = _p_str(p.get("BatchId"), 50)
    outcomes = []

    with transaction.atomic():
        for r in rows:
            s_sys = _p_str(r.get("source_system"), 50)
            s_rec = _p_str(r.get("source_record_id"), 100)
            d_ref = _p_str(r.get("doc_ref"), 60)
            t_stat = _p_str(r.get("ticket_status"), 20)
            cid = _p_int(r.get("company_id"))
            doc_key = f"{t_stat}|{cid}|{s_sys}|{d_ref}"

            existing = query_one("""
                SELECT staging_id, process_status FROM Ticket_Import_Staging
                WHERE source_system = %s AND source_record_id = %s
            """, [s_sys, s_rec])

            outcome = "Inserted"
            if existing:
                if existing["process_status"] in ("Pending", "Error"):
                    outcome = "Refreshed"
                    execute("DELETE FROM Ticket_Import_Staging WHERE staging_id = %s", [existing["staging_id"]])
                else:
                    outcome = "Unchanged"
            else:
                doc_existing = query_one("""
                    SELECT process_status FROM Ticket_Import_Staging
                    WHERE doc_key = %s LIMIT 1
                """, [doc_key])
                if doc_existing and doc_existing["process_status"] not in ("Pending", "Error"):
                    outcome = "Skipped"

            if outcome in ("Inserted", "Refreshed"):
                cols = [
                    "batch_id", "source_system", "doc_ref", "source_record_id", "received_at", "ticket_status",
                    "company_id", "branch_name", "invoice_number", "invoice_date", "invoice_type", "booking_mode",
                    "booking_type", "booking_status", "customer_name", "supplier_name", "travel_type", "user_name",
                    "currency", "roe", "booking_given_by", "booking_reference", "booking_ref_date", "airline_pnr",
                    "gds_pnr", "office_id", "payment_mode", "payment_gateway_ref", "airline_category",
                    "original_ticket_no", "airline_code", "airline_name", "line_airline_category", "flight_no",
                    "ticket_no", "passenger_name", "pax_type", "sector", "travel_date", "cabin", "travel_class",
                    "fare_type", "line_supplier_name", "line_office_id", "fop", "card_number", "line_status",
                    "basic_fare", "yq", "yr", "k3_tax", "tax_others", "seat", "meal", "baggage", "other_ssr",
                    "disc_on", "disc_type", "disc_value", "tds_per", "pg_charges", "pg_charges_percentage",
                    "markup", "addl_markup", "ssr_markup", "service_fee", "addl_service_fee", "ssr_service_fee",
                    "gst_pct", "supp_comm_on", "supp_comm_type", "supp_comm_value", "supp_tds_per", "supp_markup",
                    "supp_addl_markup", "supp_ssr_markup", "supp_service_fee", "supp_addl_service_fee",
                    "supp_ssr_service_fee", "supp_gst_pct", "agent_penalty", "reschedule_penalty", "supplier_penalty",
                    "cancellation_penalty", "cust_markup_reversal", "cust_addl_markup_reversal",
                    "cust_ssr_markup_reversal", "supp_markup_reversal", "supp_addl_markup_reversal",
                    "supp_ssr_markup_reversal", "tds_amount_override", "supp_tds_amount_override", "total_billed",
                    "raw_payload", "process_status", "retry_count"
                ]
                vals = [
                    batch_id, s_sys, d_ref, s_rec, datetime.datetime.now(datetime.timezone.utc), t_stat,
                    cid, _p_str(r.get("branch_name"), 100), _p_str(r.get("invoice_number"), 20), to_date(r.get("invoice_date")),
                    _p_str(r.get("invoice_type"), 100), _p_str(r.get("booking_mode"), 20), _p_str(r.get("booking_type"), 50),
                    _p_str(r.get("booking_status"), 20), _p_str(r.get("customer_name"), 150), _p_str(r.get("supplier_name"), 150),
                    _p_str(r.get("travel_type"), 20), _p_str(r.get("user_name"), 100), _p_str(r.get("currency"), 5),
                    to_decimal(r.get("roe")), _p_str(r.get("booking_given_by"), 25), _p_str(r.get("booking_reference"), 30),
                    to_date(r.get("booking_ref_date")), _p_str(r.get("airline_pnr"), 13), _p_str(r.get("gds_pnr"), 13),
                    _p_str(r.get("office_id"), 30), _p_str(r.get("payment_mode"), 20), _p_str(r.get("payment_gateway_ref"), 60),
                    _p_str(r.get("airline_category"), 5), _p_str(r.get("original_ticket_no"), 30), _p_str(r.get("airline_code"), 200),
                    _p_str(r.get("airline_name"), 200), _p_str(r.get("line_airline_category"), 5), _p_str(r.get("flight_no"), 200),
                    _p_str(r.get("ticket_no"), 30), _p_str(r.get("passenger_name"), 50), _p_str(r.get("pax_type"), 10),
                    _p_str(r.get("sector"), 200), _p_str(r.get("travel_date"), 200), _p_str(r.get("cabin"), 200),
                    _p_str(r.get("travel_class"), 200), _p_str(r.get("fare_type"), 300), _p_str(r.get("line_supplier_name"), 150),
                    _p_str(r.get("line_office_id"), 30), _p_str(r.get("fop"), 20), _p_str(r.get("card_number"), 40),
                    _p_str(r.get("line_status"), 15),
                    to_decimal(r.get("basic_fare")) or 0, to_decimal(r.get("yq")) or 0, to_decimal(r.get("yr")) or 0,
                    to_decimal(r.get("k3_tax")) or 0, to_decimal(r.get("tax_others")) or 0, to_decimal(r.get("seat")) or 0,
                    to_decimal(r.get("meal")) or 0, to_decimal(r.get("baggage")) or 0, to_decimal(r.get("other_ssr")) or 0,
                    _p_str(r.get("disc_on"), 20), _p_str(r.get("disc_type"), 12), to_decimal(r.get("disc_value")) or 0,
                    to_decimal(r.get("tds_per")) or 0, to_decimal(r.get("pg_charges")) or 0, to_decimal(r.get("pg_charges_percentage")) or 0,
                    to_decimal(r.get("markup")) or 0, to_decimal(r.get("addl_markup")) or 0, to_decimal(r.get("ssr_markup")) or 0,
                    to_decimal(r.get("service_fee")) or 0, to_decimal(r.get("addl_service_fee")) or 0, to_decimal(r.get("ssr_service_fee")) or 0,
                    to_decimal(r.get("gst_pct")) or 0, _p_str(r.get("supp_comm_on"), 20), _p_str(r.get("supp_comm_type"), 12),
                    to_decimal(r.get("supp_comm_value")) or 0, to_decimal(r.get("supp_tds_per")) or 0, to_decimal(r.get("supp_markup")) or 0,
                    to_decimal(r.get("supp_addl_markup")) or 0, to_decimal(r.get("supp_ssr_markup")) or 0, to_decimal(r.get("supp_service_fee")) or 0,
                    to_decimal(r.get("supp_addl_service_fee")) or 0, to_decimal(r.get("supp_ssr_service_fee")) or 0,
                    to_decimal(r.get("supp_gst_pct")) or 0, to_decimal(r.get("agent_penalty")) or 0, to_decimal(r.get("reschedule_penalty")) or 0,
                    to_decimal(r.get("supplier_penalty")) or 0, to_decimal(r.get("cancellation_penalty")) or 0,
                    to_decimal(r.get("cust_markup_reversal")) or 0, to_decimal(r.get("cust_addl_markup_reversal")) or 0,
                    to_decimal(r.get("cust_ssr_markup_reversal")) or 0, to_decimal(r.get("supp_markup_reversal")) or 0,
                    to_decimal(r.get("supp_addl_markup_reversal")) or 0, to_decimal(r.get("supp_ssr_markup_reversal")) or 0,
                    to_decimal(r.get("tds_amount_override")), to_decimal(r.get("supp_tds_amount_override")), to_decimal(r.get("total_billed")),
                    r.get("raw_payload"), "Pending", 0
                ]
                placeholders = ", ".join(["%s"] * len(vals))
                execute(f"INSERT INTO Ticket_Import_Staging ({', '.join(cols)}) VALUES ({placeholders})", vals)

            outcomes.append({
                "source_system": s_sys, "source_record_id": s_rec, "doc_key": doc_key, "outcome": outcome
            })

    return outcomes


@sp("dbo.sp_TicketImport_Stage", "DOC_STATUS")
def ticket_import_stage_doc_status(p):
    cid = _p_int(p.get("CompanyId"))
    batch_id = _p_str(p.get("BatchId"), 50)
    s_sys = _p_str(p.get("SourceSystem"), 50)
    d_ref = _p_str(p.get("DocRef"), 60)
    p_status = _p_str(p.get("ProcessStatus"), 20)
    doc_keys = _json_load(p.get("DocKeysJson"))
    top = _p_int(p.get("Top")) or 200

    where = ["1=1"]
    args = []
    if cid:
        where.append("company_id = %s")
        args.append(cid)
    if batch_id:
        where.append("batch_id = %s")
        args.append(batch_id)
    if s_sys:
        where.append("source_system = %s")
        args.append(s_sys)
    if d_ref:
        where.append("doc_ref = %s")
        args.append(d_ref)
    if p_status:
        where.append("process_status = %s")
        args.append(p_status)
    if doc_keys:
        ph = ", ".join(["%s"] * len(doc_keys))
        where.append(f"doc_key IN ({ph})")
        args.extend(doc_keys)

    sql = f"""
        SELECT doc_key, company_id, ticket_status, source_system, doc_ref,
               MIN(received_at) AS received_at,
               process_status,
               COUNT(*) AS passenger_count,
               MAX(retry_count) AS retry_count,
               MAX(error_message) AS error_message,
               MAX(saved_invoice_number) AS saved_invoice_number,
               MAX(saved_voucher_no) AS saved_voucher_no
        FROM Ticket_Import_Staging
        WHERE {" AND ".join(where)}
        GROUP BY doc_key, company_id, ticket_status, source_system, doc_ref, process_status
        ORDER BY received_at DESC
        LIMIT {top}
    """
    return query(sql, args)


@sp("dbo.sp_TicketImport_Stage", "REQUEUE")
def ticket_import_stage_requeue(p):
    cid = _p_int(p.get("CompanyId"))
    doc_keys = _json_load(p.get("DocKeysJson"))
    if not doc_keys:
        return [{"rows_requeued": 0}]
    ph = ", ".join(["%s"] * len(doc_keys))
    sql = f"""
        UPDATE Ticket_Import_Staging
        SET process_status = 'Pending', retry_count = 0, error_message = NULL, picked_at = NULL
        WHERE process_status = 'Error' AND doc_key IN ({ph})
    """
    args = list(doc_keys)
    if cid:
        sql += " AND company_id = %s"
        args.append(cid)
    cnt, _ = execute(sql, args)
    return [{"rows_requeued": cnt}]


# ===========================================================================
# dbo.sp_TicketImport_Scheduler
# ===========================================================================

@sp("dbo.sp_TicketImport_Scheduler", "START_RUN")
def ticket_import_scheduler_start(p):
    cid = _p_int(p.get("CompanyId"))
    _, run_id = execute("""
        INSERT INTO Ticket_Import_Run_Log (company_id, started_at, rows_picked, docs_imported, docs_failed)
        VALUES (%s, UTC_TIMESTAMP(6), 0, 0, 0)
    """, [cid])
    return [{"run_id": run_id}]


@sp("dbo.sp_TicketImport_Scheduler", "RESET_STUCK")
def ticket_import_scheduler_reset_stuck(p):
    cid = _p_int(p.get("CompanyId"))
    stuck_min = _p_int(p.get("StuckMinutes")) or 30
    cnt, _ = execute("""
        UPDATE Ticket_Import_Staging
        SET process_status = 'Pending', picked_at = NULL, run_id = NULL
        WHERE process_status = 'Processing'
          AND picked_at < DATE_SUB(UTC_TIMESTAMP(6), INTERVAL %s MINUTE)
          AND (%s IS NULL OR company_id = %s)
    """, [stuck_min, cid, cid])
    return [{"rows_reset": cnt}]


@sp("dbo.sp_TicketImport_Scheduler", "FETCH_PENDING")
def ticket_import_scheduler_fetch_pending(p):
    cid = _p_int(p.get("CompanyId"))
    run_id = _p_int(p.get("RunId"))
    batch_size = _p_int(p.get("BatchSize")) or 50

    with transaction.atomic():
        docs = query(f"""
            SELECT doc_key
            FROM Ticket_Import_Staging
            WHERE process_status = 'Pending' AND (%s IS NULL OR company_id = %s)
            GROUP BY doc_key, ticket_status
            ORDER BY CASE ticket_status WHEN 'Confirmed' THEN 1 WHEN 'Rescheduled' THEN 2 WHEN 'SSR' THEN 3 ELSE 4 END,
                     MIN(received_at)
            LIMIT {batch_size}
        """, [cid, cid])

        if not docs:
            return []

        keys = [d["doc_key"] for d in docs]
        ph = ", ".join(["%s"] * len(keys))
        execute(f"""
            UPDATE Ticket_Import_Staging
            SET process_status = 'Processing', run_id = %s, picked_at = UTC_TIMESTAMP(6)
            WHERE doc_key IN ({ph})
        """, [run_id] + keys)

        return query(f"""
            SELECT * FROM Ticket_Import_Staging
            WHERE doc_key IN ({ph})
            ORDER BY doc_key, staging_id
        """, keys)


@sp("dbo.sp_TicketImport_Scheduler", "RESOLVE_PARENTS")
def ticket_import_scheduler_resolve_parents(p):
    cid = _p_int(p.get("CompanyId"))
    t_nos = _json_load(p.get("TicketNosJson"))
    if not t_nos:
        return []

    ph = ", ".join(["%s"] * len(t_nos))
    sql = f"""
        SELECT tl.ticket_no AS lookup_ticket_no, tl.ticket_no, t.id AS ticket_id, t.invoice_number, t.invoice_date,
               t.customer_ledger_id, t.supplier_ledger_id, tl.id AS ticket_line_id,
               tl.basic_fare, tl.yq, tl.yr, tl.k3_tax, tl.tax_others,
               tl.markup, tl.service_fee, tl.service_fee_gst
        FROM AL_TicketLines tl
        JOIN AL_Tickets t ON t.id = tl.ticket_id
        WHERE t.company_id = %s AND tl.ticket_no IN ({ph})
    """
    return query(sql, [cid] + t_nos)


@sp("dbo.sp_TicketImport_Scheduler", "MARK_IMPORTED")
def ticket_import_scheduler_mark_imported(p):
    doc_key = _p_str(p.get("DocKey"), 200)
    target_id = _p_int(p.get("TargetHeaderId"))
    inv_num = _p_str(p.get("InvoiceNumber"), 20)
    v_no = _p_str(p.get("VoucherNo"), 50)

    cnt, _ = execute("""
        UPDATE Ticket_Import_Staging
        SET process_status = 'Imported', processed_at = UTC_TIMESTAMP(6), target_header_id = %s,
            saved_invoice_number = %s, saved_voucher_no = %s, error_message = NULL
        WHERE doc_key = %s AND process_status = 'Processing'
    """, [target_id, inv_num, v_no, doc_key])
    return [{"rows_marked": cnt, "process_status": "Imported"}]


@sp("dbo.sp_TicketImport_Scheduler", "MARK_ERROR")
def ticket_import_scheduler_mark_error(p):
    doc_key = _p_str(p.get("DocKey"), 200)
    msg = _p_str(p.get("ErrorMessage"), 1000) or "Import failed."
    max_retry = _p_int(p.get("MaxRetry")) or 3

    cnt, _ = execute("""
        UPDATE Ticket_Import_Staging
        SET retry_count = retry_count + 1,
            process_status = CASE WHEN retry_count + 1 >= %s THEN 'Error' ELSE 'Pending' END,
            error_message = %s, processed_at = UTC_TIMESTAMP(6), picked_at = NULL
        WHERE doc_key = %s AND process_status = 'Processing'
    """, [max_retry, msg, doc_key])

    row = query_one("SELECT MAX(process_status) AS process_status FROM Ticket_Import_Staging WHERE doc_key = %s", [doc_key])
    return [{"rows_marked": cnt, "process_status": (row or {}).get("process_status") or "Error"}]


@sp("dbo.sp_TicketImport_Scheduler", "FINISH_RUN")
def ticket_import_scheduler_finish_run(p):
    run_id = _p_int(p.get("RunId"))
    imported = _p_int(p.get("DocsImported")) or 0
    failed = _p_int(p.get("DocsFailed")) or 0
    msg = _p_str(p.get("Message"), 1000)

    execute("""
        UPDATE Ticket_Import_Run_Log
        SET finished_at = UTC_TIMESTAMP(6), docs_imported = %s, docs_failed = %s, message = %s
        WHERE run_id = %s
    """, [imported, failed, msg, run_id])
    return [{"run_id": run_id, "status": "Success"}]


# ===========================================================================
# dbo.sp_TicketImport_ErrorLog
# ===========================================================================

@sp("dbo.sp_TicketImport_ErrorLog", "INSERT_JSON")
def ticket_import_error_log_insert(p):
    rows = _json_load(p.get("RowsJson"))
    with transaction.atomic():
        for r in rows:
            execute("""
                INSERT INTO Ticket_Import_Error_Log
                    (company_id, source_system, batch_id, doc_key, booking_status, booking_reference,
                     parent_pnr, passenger_no, ticket_no, passenger_name, field_name, field_label,
                     received_value, expected_value, error_type, severity, stage, error_message,
                     is_resolved, logged_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, UTC_TIMESTAMP(6))
            """, [
                _p_int(r.get("company_id")), _p_str(r.get("source_system"), 50), _p_str(r.get("batch_id"), 50),
                _p_str(r.get("doc_key"), 200), _p_str(r.get("booking_status"), 20), _p_str(r.get("booking_reference"), 60),
                _p_str(r.get("parent_pnr"), 60), _p_int(r.get("passenger_no")), _p_str(r.get("ticket_no"), 60),
                _p_str(r.get("passenger_name"), 100), _p_str(r.get("field_name"), 100), _p_str(r.get("field_label"), 100),
                _p_str(r.get("received_value"), 500), _p_str(r.get("expected_value"), 500), _p_str(r.get("error_type"), 30) or "Error",
                _p_str(r.get("severity"), 10) or "High", _p_str(r.get("stage"), 20) or "Validate",
                _p_str(r.get("error_message"), 1000) or ""
            ])
    return [{"status": "Success"}]


@sp("dbo.sp_TicketImport_ErrorLog", "LIST")
def ticket_import_error_log_list(p):
    cid = _p_int(p.get("CompanyId"))
    from_date = to_date(p.get("FromDate"))
    to_date_val = to_date(p.get("ToDate"))
    b_stat = _p_str(p.get("BookingStatus"), 20)
    e_type = _p_str(p.get("ErrorType"), 30)
    stage = _p_str(p.get("Stage"), 20)
    resolved = to_bool_param(p.get("Resolved"))
    search = _p_str(p.get("Search"), 100)
    source = _p_str(p.get("Source"), 20)
    top = _p_int(p.get("Top")) or 500

    where = ["1=1"]
    args = []
    if cid:
        where.append("company_id = %s")
        args.append(cid)
    if from_date:
        where.append("logged_at >= %s")
        args.append(from_date)
    if to_date_val:
        where.append("logged_at < DATE_ADD(%s, INTERVAL 1 DAY)")
        args.append(to_date_val)
    if b_stat:
        where.append("booking_status = %s")
        args.append(b_stat)
    if e_type:
        where.append("error_type = %s")
        args.append(e_type)
    if stage:
        where.append("stage = %s")
        args.append(stage)
    if resolved is not None:
        where.append("is_resolved = %s")
        args.append(1 if resolved else 0)
    if search:
        where.append("(booking_reference LIKE %s OR parent_pnr LIKE %s OR ticket_no LIKE %s OR error_message LIKE %s)")
        pat = f"%{search}%"
        args.extend([pat, pat, pat, pat])
    if source == "API":
        where.append("source_system <> 'AGENT_DB'")
    elif source == "AGENT_DB":
        where.append("source_system = 'AGENT_DB'")

    sql = f"""
        SELECT error_log_id, logged_at, company_id, source_system, batch_id, doc_key,
               booking_status, booking_reference, parent_pnr, passenger_no, ticket_no,
               passenger_name, field_name, field_label, received_value, expected_value,
               error_type, severity, stage, error_message, is_resolved, resolved_at, resolved_note
        FROM Ticket_Import_Error_Log
        WHERE {" AND ".join(where)}
        ORDER BY error_log_id DESC
        LIMIT {top}
    """
    rows = query(sql, args)
    for r in rows:
        bits(r, "is_resolved")
    return rows


@sp("dbo.sp_TicketImport_ErrorLog", "RESOLVE")
def ticket_import_error_log_resolve(p):
    doc_key = _p_str(p.get("DocKey"), 200)
    note = _p_str(p.get("Note"), 200)
    cnt, _ = execute("""
        UPDATE Ticket_Import_Error_Log
        SET is_resolved = 1, resolved_at = UTC_TIMESTAMP(6), resolved_note = %s
        WHERE doc_key = %s AND is_resolved = 0
    """, [note, doc_key])
    return [{"resolved": cnt}]


# ===========================================================================
# dbo.sp_TicketImport_InvoiceType
# ===========================================================================

@sp("dbo.sp_TicketImport_InvoiceType", "LIST")
def ticket_import_invoice_type_list(p):
    cid = _p_int(p.get("CompanyId"))
    sql = """
        SELECT m.ticket_status, m.voucher_type_id, vt.name AS voucher_type_name, vt.voucher_category
        FROM Ticket_Import_Invoice_Type m
        JOIN VoucherType vt ON vt.id = m.voucher_type_id
        WHERE m.company_id = %s
    """
    return query(sql, [cid])


@sp("dbo.sp_TicketImport_InvoiceType", "SET")
def ticket_import_invoice_type_set(p):
    cid = _p_int(p.get("CompanyId"))
    vt_id = _p_int(p.get("VoucherTypeId"))
    statuses = _json_load(p.get("TicketStatusesJson"))

    vt = query_one("SELECT voucher_category, name FROM VoucherType WHERE id = %s AND company_id = %s", [vt_id, cid])
    if not vt:
        return error_row("Voucher Type not found.")

    with transaction.atomic():
        for st in statuses:
            st_name = _p_str(st, 20)
            if not st_name:
                continue
            execute("""
                INSERT INTO Ticket_Import_Invoice_Type (company_id, ticket_status, voucher_type_id, updated_at)
                VALUES (%s, %s, %s, UTC_TIMESTAMP(6))
                ON DUPLICATE KEY UPDATE voucher_type_id = VALUES(voucher_type_id), updated_at = UTC_TIMESTAMP(6)
            """, [cid, st_name, vt_id])

    return query("""
        SELECT m.ticket_status, m.voucher_type_id, vt.name AS voucher_type_name
        FROM Ticket_Import_Invoice_Type m
        JOIN VoucherType vt ON vt.id = m.voucher_type_id
        WHERE m.company_id = %s
    """, [cid])


# ===========================================================================
# dbo.sp_TicketImport_KnownTickets
# ===========================================================================

@sp("dbo.sp_TicketImport_KnownTickets", "")
@sp("dbo.sp_TicketImport_KnownTickets", "SELECT")
@sp("dbo.sp_TicketImport_KnownTickets", "LIST")
def ticket_import_known_tickets(p):
    cid = _p_int(p.get("CompanyId"))
    t_nos = _json_load(p.get("TicketNosJson"))
    if not t_nos:
        return []
    res = []
    for tno in t_nos:
        tno_str = _p_str(tno, 30)
        found = query_one("""
            SELECT 'Cancellation' AS found_on FROM Cancellation_Al_TicketLines cl
            JOIN Cancellation_AL_Tickets c ON c.id = cl.cancellation_ticket_id
            WHERE c.company_id = %s AND cl.ticket_no = %s LIMIT 1
        """, [cid, tno_str])
        if not found:
            found = query_one("""
                SELECT 'Reschedule' AS found_on FROM Rescheduled_Al_TicketLines rl
                JOIN Rescheduled_Al_Ticket r ON r.id = rl.reschedule_ticket_id
                WHERE r.company_id = %s AND rl.ticket_no = %s LIMIT 1
            """, [cid, tno_str])
        if not found:
            found = query_one("""
                SELECT 'Booking' AS found_on FROM AL_TicketLines tl
                JOIN AL_Tickets t ON t.id = tl.ticket_id
                WHERE t.company_id = %s AND tl.ticket_no = %s LIMIT 1
            """, [cid, tno_str])
        if found:
            res.append({"ticket_no": tno_str, "found_on": found["found_on"]})
    return res


# ===========================================================================
# dbo.sp_AgentDbScheduler_Log
# ===========================================================================

@sp("dbo.sp_AgentDbScheduler_Log", "INSERT")
def agent_db_scheduler_log_insert(p):
    r_start = p.get("RunStartedAt")
    r_fin = p.get("RunFinishedAt")
    s_db = _p_str(p.get("SourceDatabase"), 128)
    s_tbl = _p_str(p.get("SourceTable"), 128)
    rec_f = _p_int(p.get("RecordsFetched")) or 0
    inv_f = _p_int(p.get("InvoicesFetched")) or 0
    imp_c = _p_int(p.get("ImportedCount")) or 0
    pend_c = _p_int(p.get("PendingCount")) or 0
    err_c = _p_int(p.get("ErrorCount")) or 0
    msg = _p_str(p.get("Message"), 1000)

    _, log_id = execute("""
        INSERT INTO Agent_DB_Scheduler_Log
            (run_started_at, run_finished_at, source_database, source_table, records_fetched,
             invoices_fetched, imported_count, pending_count, error_count, message)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, [r_start, r_fin, s_db, s_tbl, rec_f, inv_f, imp_c, pend_c, err_c, msg])
    return [{"log_id": log_id, "status": "Success"}]


@sp("dbo.sp_AgentDbScheduler_Log", "LIST")
def agent_db_scheduler_log_list(p):
    from_date = to_date(p.get("FromDate"))
    to_date_val = to_date(p.get("ToDate"))
    top = _p_int(p.get("Top")) or 200

    where = ["1=1"]
    args = []
    if from_date:
        where.append("run_started_at >= %s")
        args.append(from_date)
    if to_date_val:
        where.append("run_started_at < DATE_ADD(%s, INTERVAL 1 DAY)")
        args.append(to_date_val)

    sql = f"""
        SELECT log_id, run_started_at, run_finished_at, source_database, source_table,
               records_fetched, invoices_fetched, imported_count, pending_count, error_count, message
        FROM Agent_DB_Scheduler_Log
        WHERE {" AND ".join(where)}
        ORDER BY log_id DESC
        LIMIT {top}
    """
    return query(sql, args)


# ===========================================================================
# dbo.sp_AgentDbTicketLog
# ===========================================================================

@sp("dbo.sp_AgentDbTicketLog", "CLAIM_JSON")
def agent_db_ticket_log_claim(p):
    s_db = _p_str(p.get("SourceDatabase"), 128)
    s_tbl = _p_str(p.get("SourceTable"), 128)
    stuck_min = _p_int(p.get("StuckMinutes")) or 30
    rows = _json_load(p.get("RowsJson"))

    execute("""
        DELETE FROM Agent_DB_Ticket_Log
        WHERE source_database = %s AND source_table = %s
          AND process_status = 'Processing'
          AND processing_at < DATE_SUB(UTC_TIMESTAMP(6), INTERVAL %s MINUTE)
    """, [s_db, s_tbl, stuck_min])

    claimed = []
    with transaction.atomic():
        for r in rows:
            row_id = _p_int(r.get("agent_row_id"))
            exists = query_one("""
                SELECT 1 AS x FROM Agent_DB_Ticket_Log
                WHERE source_database = %s AND source_table = %s AND agent_row_id = %s
            """, [s_db, s_tbl, row_id])
            if not exists:
                execute("""
                    INSERT INTO Agent_DB_Ticket_Log
                        (source_database, source_table, agent_row_id, company_id, booking_status,
                         booking_reference, ticket_no, pax_name, process_status, processing_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Processing', UTC_TIMESTAMP(6))
                """, [
                    s_db, s_tbl, row_id, _p_int(r.get("company_id")),
                    _p_str(r.get("booking_status"), 100), _p_str(r.get("booking_reference"), 100),
                    _p_str(r.get("ticket_no"), 100), _p_str(r.get("pax_name"), 100)
                ])
                claimed.append({"agent_row_id": row_id})
    return claimed


@sp("dbo.sp_AgentDbTicketLog", "RESULT_JSON")
def agent_db_ticket_log_result(p):
    s_db = _p_str(p.get("SourceDatabase"), 128)
    s_tbl = _p_str(p.get("SourceTable"), 128)
    rows = _json_load(p.get("RowsJson"))
    cnt = 0
    with transaction.atomic():
        for r in rows:
            row_id = _p_int(r.get("agent_row_id"))
            p_stat = _p_str(r.get("process_status"), 20)
            inv_num = _p_str(r.get("invoice_number"), 30)
            v_no = _p_str(r.get("voucher_no"), 30)
            d_key = _p_str(r.get("import_doc_key"), 200)
            err_msg = _p_str(r.get("error_message"), 2000)

            c, _ = execute("""
                UPDATE Agent_DB_Ticket_Log
                SET process_status = %s, processed_at = UTC_TIMESTAMP(6), invoice_number = %s,
                    voucher_no = %s, import_doc_key = %s, error_message = %s
                WHERE source_database = %s AND source_table = %s AND agent_row_id = %s
            """, [p_stat, inv_num, v_no, d_key, err_msg, s_db, s_tbl, row_id])
            cnt += c
    return [{"updated": cnt}]


@sp("dbo.sp_AgentDbTicketLog", "RELEASE_JSON")
def agent_db_ticket_log_release(p):
    s_db = _p_str(p.get("SourceDatabase"), 128)
    s_tbl = _p_str(p.get("SourceTable"), 128)
    rows = _json_load(p.get("RowsJson"))
    ids = [_p_int(r.get("agent_row_id")) for r in rows if _p_int(r.get("agent_row_id")) is not None]
    if not ids:
        return [{"released": 0}]
    ph = ", ".join(["%s"] * len(ids))
    cnt, _ = execute(f"""
        DELETE FROM Agent_DB_Ticket_Log
        WHERE source_database = %s AND source_table = %s AND process_status = 'Processing'
          AND agent_row_id IN ({ph})
    """, [s_db, s_tbl] + ids)
    return [{"released": cnt}]


@sp("dbo.sp_AgentDbTicketLog", "SET_RUN")
def agent_db_ticket_log_set_run(p):
    s_db = _p_str(p.get("SourceDatabase"), 128)
    s_tbl = _p_str(p.get("SourceTable"), 128)
    sched_id = _p_int(p.get("SchedulerLogId"))
    rows = _json_load(p.get("RowsJson"))
    ids = [_p_int(r.get("agent_row_id")) for r in rows if _p_int(r.get("agent_row_id")) is not None]
    if not ids:
        return [{"updated": 0}]
    ph = ", ".join(["%s"] * len(ids))
    cnt, _ = execute(f"""
        UPDATE Agent_DB_Ticket_Log
        SET scheduler_log_id = %s
        WHERE source_database = %s AND source_table = %s AND agent_row_id IN ({ph})
    """, [sched_id, s_db, s_tbl] + ids)
    return [{"updated": cnt}]


@sp("dbo.sp_AgentDbTicketLog", "WAITING")
def agent_db_ticket_log_waiting(p):
    sql = """
        SELECT DISTINCT company_id, import_doc_key
        FROM Agent_DB_Ticket_Log
        WHERE process_status IN ('Pending', 'Error') AND import_doc_key IS NOT NULL
    """
    return query(sql)


@sp("dbo.sp_AgentDbTicketLog", "REFRESH")
def agent_db_ticket_log_refresh(p):
    d_key = _p_str(p.get("DocKey"), 200)
    p_stat = _p_str(p.get("ProcessStatus"), 20)
    inv_num = _p_str(p.get("InvoiceNumber"), 30)
    v_no = _p_str(p.get("VoucherNo"), 30)
    err_msg = _p_str(p.get("ErrorMessage"), 2000)

    cnt, _ = execute("""
        UPDATE Agent_DB_Ticket_Log
        SET process_status = %s, processed_at = UTC_TIMESTAMP(6), invoice_number = %s,
            voucher_no = %s, error_message = %s
        WHERE import_doc_key = %s AND process_status IN ('Pending', 'Error')
    """, [p_stat, inv_num, v_no, err_msg, d_key])
    return [{"updated": cnt}]
