"""
MySQL/TiDB implementations of:
  - dbo.sp_AirlineDropdown
  - dbo.sp_AuditLog
"""
import datetime
import decimal
import json

from . import execute, query, query_one, sp


def _json_serial(obj):
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    return str(obj)


# ==============================================================================
# dbo.sp_AirlineDropdown
# ==============================================================================

@sp("dbo.sp_AirlineDropdown", "LIST")
def sp_airline_dropdown_list(params):
    list_key = params.get("ListKey") or None
    if list_key:
        return query(
            "SELECT list_key, code, name, COALESCE(display_label, name) AS label, sort_order, is_default "
            "FROM `AirlineDropdownValues` "
            "WHERE is_active = 1 AND list_key = %s "
            "ORDER BY sort_order, id",
            [list_key],
        )
    return query(
        "SELECT list_key, code, name, COALESCE(display_label, name) AS label, sort_order, is_default "
        "FROM `AirlineDropdownValues` "
        "WHERE is_active = 1 "
        "ORDER BY list_key, sort_order, id"
    )


@sp("dbo.sp_AirlineDropdown", "RESOLVE")
def sp_airline_dropdown_resolve(params):
    list_key = params.get("ListKey")
    code = params.get("Code")
    name = params.get("Name")
    if code is not None:
        return query(
            "SELECT list_key, code, name, COALESCE(display_label, name) AS label "
            "FROM `AirlineDropdownValues` "
            "WHERE is_active = 1 AND list_key = %s AND code = %s "
            "LIMIT 1",
            [list_key, code],
        )
    return query(
        "SELECT list_key, code, name, COALESCE(display_label, name) AS label "
        "FROM `AirlineDropdownValues` "
        "WHERE is_active = 1 AND list_key = %s AND name = %s "
        "LIMIT 1",
        [list_key, name],
    )


# ==============================================================================
# dbo.sp_AuditLog
# ==============================================================================

@sp("dbo.sp_AuditLog", "SNAPSHOT")
def sp_audit_log_snapshot(params):
    module = params.get("Module")
    doc_id = params.get("DocumentId")
    if not module or not doc_id:
        return [{"header_json": None, "lines_json": None}]

    header_row = None
    lines_rows = []

    if module == "Booking":
        header_row = query_one(
            "SELECT t.*, c.name AS customer_name, s.name AS supplier_name "
            "FROM `AL_Tickets` t "
            "LEFT JOIN `Ledgers` c ON c.id = t.customer_ledger_id "
            "LEFT JOIN `Ledgers` s ON s.id = t.supplier_ledger_id "
            "WHERE t.id = %s",
            [doc_id],
        )
        lines_rows = query(
            "SELECT l.*, s.name AS supplier_name "
            "FROM `AL_TicketLines` l "
            "LEFT JOIN `Ledgers` s ON s.id = l.supplier_ledger_id "
            "WHERE l.ticket_id = %s ORDER BY l.id",
            [doc_id],
        )
    elif module == "Reschedule":
        header_row = query_one(
            "SELECT t.*, c.name AS customer_name, s.name AS supplier_name "
            "FROM `Rescheduled_Al_Ticket` t "
            "LEFT JOIN `Ledgers` c ON c.id = t.customer_ledger_id "
            "LEFT JOIN `Ledgers` s ON s.id = t.supplier_ledger_id "
            "WHERE t.id = %s",
            [doc_id],
        )
        lines_rows = query(
            "SELECT l.*, s.name AS supplier_name "
            "FROM `Rescheduled_Al_TicketLines` l "
            "LEFT JOIN `Ledgers` s ON s.id = l.supplier_ledger_id "
            "WHERE l.reschedule_ticket_id = %s ORDER BY l.id",
            [doc_id],
        )
    elif module == "Cancellation":
        header_row = query_one(
            "SELECT t.*, c.name AS customer_name, s.name AS supplier_name "
            "FROM `Cancellation_AL_Tickets` t "
            "LEFT JOIN `Ledgers` c ON c.id = t.customer_ledger_id "
            "LEFT JOIN `Ledgers` s ON s.id = t.supplier_ledger_id "
            "WHERE t.id = %s",
            [doc_id],
        )
        lines_rows = query(
            "SELECT l.*, s.name AS supplier_name "
            "FROM `Cancellation_Al_TicketLines` l "
            "LEFT JOIN `Ledgers` s ON s.id = l.supplier_ledger_id "
            "WHERE l.cancellation_ticket_id = %s ORDER BY l.id",
            [doc_id],
        )
    elif module == "SSR Updation":
        header_row = query_one(
            "SELECT t.*, c.name AS customer_name "
            "FROM `SSR_AL_Tickets` t "
            "LEFT JOIN `Ledgers` c ON c.id = t.customer_ledger_id "
            "WHERE t.id = %s",
            [doc_id],
        )
        lines_rows = query(
            "SELECT l.*, s.name AS supplier_name "
            "FROM `SSR_AL_TicketLines` l "
            "LEFT JOIN `Ledgers` s ON s.id = l.supplier_ledger_id "
            "WHERE l.ssr_ticket_id = %s ORDER BY l.id",
            [doc_id],
        )

    if not header_row and not lines_rows:
        return [{"header_json": None, "lines_json": None}]

    header_json = json.dumps(header_row, default=_json_serial) if header_row else None
    lines_json = json.dumps(lines_rows, default=_json_serial) if lines_rows else "[]"
    return [{"header_json": header_json, "lines_json": lines_json}]


@sp("dbo.sp_AuditLog", "CHAIN")
def sp_audit_log_chain(params):
    module = params.get("Module")
    doc_id = params.get("DocumentId")
    if not module or not doc_id:
        return []

    root_id = None
    if module == "Booking":
        root_id = doc_id
    elif module == "Reschedule":
        r = query_one("SELECT original_ticket_id FROM `Rescheduled_Al_Ticket` WHERE id = %s", [doc_id])
        if r:
            root_id = r["original_ticket_id"]

    if not root_id:
        return []

    sql = (
        "SELECT 'Reschedule' AS module, id FROM `Rescheduled_Al_Ticket` WHERE original_ticket_id = %s "
        "UNION ALL "
        "SELECT 'Cancellation' AS module, id FROM `Cancellation_AL_Tickets` WHERE original_ticket_id = %s "
        "UNION ALL "
        "SELECT 'SSR Updation' AS module, id FROM `SSR_AL_Tickets` WHERE original_ticket_id = %s "
        "ORDER BY module, id"
    )
    rows = query(sql, [root_id, root_id, root_id])
    return [r for r in rows if not (r["module"] == module and int(r["id"]) == int(doc_id))]


@sp("dbo.sp_AuditLog", "INSERT")
def sp_audit_log_insert(params):
    company_id = params.get("CompanyId")
    module = params.get("Module")
    doc_id = params.get("DocumentId")
    doc_no = params.get("DocumentNo")
    action = params.get("LogAction")
    source = params.get("Source")
    user_id = params.get("UserId")
    user_name = params.get("UserName")
    change_count = params.get("ChangeCount") or 0
    changes = params.get("Changes")
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    _, last_id = execute(
        "INSERT INTO `AuditLogs` "
        "(`company_id`, `module`, `document_id`, `document_no`, `action`, `source`, `user_id`, `user_name`, `change_count`, `changes`, `changed_at`) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        [company_id, module, doc_id, doc_no, action, source, user_id, user_name, change_count, changes, now]
    )
    return [{"id": last_id}]


@sp("dbo.sp_AuditLog", "LIST")
def sp_audit_log_list(params):
    company_id = params.get("CompanyId")
    module = params.get("Module") or None
    doc_id = params.get("DocumentId") or None
    top = int(params.get("Top") or 500)

    where = ["company_id = %s"]
    args = [company_id]
    if module:
        where.append("module = %s")
        args.append(module)
    if doc_id:
        where.append("document_id = %s")
        args.append(doc_id)

    args.append(top)
    sql = (
        f"SELECT id, company_id, module, document_id, document_no, action, source, user_id, user_name, change_count, changes, changed_at "
        f"FROM `AuditLogs` "
        f"WHERE {' AND '.join(where)} "
        f"ORDER BY changed_at DESC, id DESC LIMIT %s"
    )
    return query(sql, args)
