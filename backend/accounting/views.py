"""
Voyager ERP — Ledger Groups API
-----------------------------------------------------------------
This replaces the hardcoded COA_DEFS array that used to live in the
frontend's mock-data.js. The frontend now calls GET /api/ledger-groups/
and gets these rows straight from SQL Server instead.
"""
import hmac
import json
import math
import os
import re
from datetime import datetime, date, timedelta
from django.http import JsonResponse, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt
from django.forms.models import model_to_dict
from django.db import transaction, IntegrityError
from django.db.models import ProtectedError, Q, Prefetch

from .models import LedgerGroup, Ledger, Ticket, TicketLine, Voucher, JournalVoucher, VoucherType, SupplierCommissionRule, MasterMapping, FOPMaster, PGMaster, PGMasterHistory, CompanyMaster, RescheduleAirlineTicket, RescheduleAirlineTicketLine, CancellationAirlineTicket, CancellationAirlineTicketLine, _field_gst_pct_cache
from .jv_hardcode import JV_LINE_MAP
from . import sp_client


def ledger_groups_list(request):
    """
    GET /api/ledger-groups/?company_id=1
    Returns a FLAT list (id, name, code, account_type, parent_id, is_group,
    is_system) — same shape the frontend's renderGroupOptions() already
    expects, so swapping the data source doesn't require rewriting the
    tree-building logic in page-ledger-entry.js.

    Stored Procedure architecture (2026-10-06 decision) - this is the
    first module migrated off the ORM: data comes from dbo.sp_LedgerGroup
    (StoredProcedures.sql) via sp_client.ledger_group_list(), not a
    LedgerGroup.objects.filter() query.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    data = sp_client.ledger_group_list(company_id)
    return JsonResponse(data, safe=False)


@csrf_exempt
def ledger_group_create(request):
    """
    POST /api/ledger-groups/create/
    Body: { "company_id": 1, "name": "...", "code": "...", "account_type": "ASSET", "parent_id": 5 }
    Kept separate from the list endpoint on purpose — the ledger-entry
    form only needs to READ groups today; this is here so adding new
    groups from the UI later is a one-line frontend change, not a new
    backend endpoint.

    Stored Procedure architecture - saves via dbo.sp_LedgerGroup's SAVE
    action (sp_client.ledger_group_save()), not LedgerGroup.objects.create().
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    required = ["company_id", "name", "account_type"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        return JsonResponse({"error": f"Missing required field(s): {', '.join(missing)}"}, status=400)

    try:
        group = sp_client.ledger_group_save(
            company_id=body["company_id"],
            name=body["name"],
            account_type=body["account_type"],
            code=body.get("code"),
            parent_id=body.get("parent_id"),
            is_group=body.get("is_group", True),
        )
    except sp_client.StoredProcedureError as err:
        return JsonResponse({"error": str(err)}, status=400)
    return JsonResponse(group, status=201)


LEDGER_FIELDS = [
    "bank_account_no", "bank_branch", "ifsc_code", "swift_code",
    "alias_name", "address_line1", "address_line2", "agent_id",
    "maintain_balance_bill_wise", "place_of_supply",
    "city", "pincode", "state_name", "gst_no", "gst_registration_type", "pan_no",
    "emirate", "po_box_no", "vat_trn_no", "trade_license_no", "trade_license_expiry",
    "creditor_type", "supplier_code", "office_id",
    "tax_category", "tax_type",
    "gst_applicable", "gst_tax_type", "gst_percentage",
    "tds_applicable", "tds_percentage", "hsn_code",
    "tcs_applicable", "tcs_percentage",
]


@csrf_exempt
def ledger_create(request):
    """
    POST /api/ledgers/create/
    Body: the same flat payload page-ledger-entry.js already builds —
    name, parent_id (-> group), opening_balance, opening_balance_type,
    ledger_category, plus whichever category-specific fields apply.
    Saves a real row into the Ledgers table.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    required = ["company_id", "name", "parent_id"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        return JsonResponse({"error": f"Missing required field(s): {', '.join(missing)}"}, status=400)

    extra = {f: body[f] for f in LEDGER_FIELDS if f in body}
    if extra.get("agent_id") == "":
        extra["agent_id"] = None

    try:
        ledger = sp_client.ledger_save(
            company_id=body["company_id"],
            name=body["name"],
            parent_id=body["parent_id"],
            opening_balance=body.get("opening_balance", 0) or 0,
            opening_balance_type=body.get("opening_balance_type", "Debit"),
            ledger_category=body.get("ledger_category", "OTHER"),
            extra_fields=extra,
        )
    except sp_client.StoredProcedureError as err:
        msg = str(err)
        status = 409 if "already exists" in msg or "already used" in msg else 400
        return JsonResponse({"error": msg}, status=status)
    return JsonResponse(
        {"id": ledger["id"], "name": ledger["name"], "group_id": ledger["parent_id"], "message": "Ledger created."},
        status=201,
    )


@csrf_exempt
def ledger_delete(request, ledger_id):
    """
    DELETE /api/ledgers/<id>/delete/?company_id=1
    Removes a real row from the Ledgers table. This is what the
    "Delete" button on the Chart of Accounts page now actually calls —
    previously it was checking mock data, which is why deleting a
    real DB-created ledger (like "MANO") failed with "Ledger not found".
    """
    if request.method != "DELETE":
        return HttpResponseNotAllowed(["DELETE"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    try:
        sp_client.ledger_delete(ledger_id, company_id)
    except sp_client.StoredProcedureError as err:
        msg = str(err)
        status = 404 if msg == "Ledger not found." else 409
        return JsonResponse({"error": msg}, status=status)
    return JsonResponse({"message": "Ledger deleted."}, status=200)


def customers_list(request):
    """
    GET /api/customers/?company_id=1
    Real customers = Ledgers created under a Sundry Debtors-type group
    (ledger_category='DEBTOR'). This replaces the hardcoded "Sundaram
    Exports 1-10" customer list the New Ticket form used to load from
    mock-data.js — any ledger created via the New Ledger form under
    Sundry Debtors (like "GOKUL S") now shows up here automatically.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    data = sp_client.customers_list(company_id)
    return JsonResponse(data, safe=False)


def ledger_detail(request, ledger_id):
    """
    GET /api/ledgers/<id>/?company_id=1
    Returns one ledger's full field set — used by ledger-entry.html to
    prefill the edit form. Field names match the payload the form
    already builds, so prefillForm() needs no field-name translation.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    data = sp_client.ledger_get(ledger_id, company_id)
    if not data:
        return JsonResponse({"error": "Ledger not found."}, status=404)
    for f in ("opening_balance", "balance", "gst_percentage", "tds_percentage", "tcs_percentage"):
        if data.get(f) is not None:
            data[f] = float(data[f])
    for f in LEDGER_FIELDS:
        v = data.get(f)
        if hasattr(v, "isoformat"):
            data[f] = v.isoformat()
    return JsonResponse(data)


@csrf_exempt
def ledger_update(request, ledger_id):
    """
    PUT /api/ledgers/<id>/update/?company_id=1
    Same body shape as ledger_create. Updates a real row in place.
    """
    if request.method != "PUT":
        return HttpResponseNotAllowed(["PUT"])

    company_id = request.GET.get("company_id")
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    if "agent_id" in body and body["agent_id"] == "":
        body["agent_id"] = None

    extra = {f: body[f] for f in LEDGER_FIELDS if f in body}

    try:
        sp_client.ledger_update(
            ledger_id, company_id,
            name=body.get("name"),
            parent_id=body.get("parent_id"),
            opening_balance=body.get("opening_balance") if "opening_balance" in body else None,
            opening_balance_type=body.get("opening_balance_type"),
            ledger_category=body.get("ledger_category"),
            extra_fields=extra,
        )
    except sp_client.StoredProcedureError as err:
        msg = str(err)
        status = 404 if msg == "Ledger not found." else (409 if "already" in msg else 400)
        return JsonResponse({"error": msg}, status=status)
    return JsonResponse({"id": int(ledger_id), "message": "Ledger updated."})


def ledger_agent_id_available(request):
    """
    GET /api/ledgers/agent-id-available/?agent_id=AGT-001&exclude_id=5
    Agent ID is unique GLOBALLY (across every company/ledger), not just
    within one company — matches "no duplicate allowed" as stated.
    """
    agent_id = (request.GET.get("agent_id") or "").strip()
    exclude_id = request.GET.get("exclude_id")
    if not agent_id:
        return JsonResponse({"available": True})
    return JsonResponse({"available": sp_client.ledger_agent_id_available(agent_id, exclude_id)})


def ledger_name_available(request):
    """
    GET /api/ledgers/name-available/?company_id=1&name=Gokul+Kumar&exclude_id=5
    Live uniqueness check the New Ledger form calls on blur, so a
    duplicate name is caught before Save instead of only after.
    """
    company_id = request.GET.get("company_id")
    name = (request.GET.get("name") or "").strip()
    exclude_id = request.GET.get("exclude_id")
    if not company_id or not name:
        return JsonResponse({"available": True})
    return JsonResponse({"available": sp_client.ledger_name_available(company_id, name, exclude_id)})


def suppliers_list(request):
    """
    GET /api/suppliers/?company_id=1
    Real suppliers = Ledgers under a Sundry Creditors-type group
    (ledger_category='CREDITOR'). Same pattern as customers_list.
    Includes office_id and supplier_code so the New Ticket form can
    auto-fill those from the selected supplier's ledger record.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    data = sp_client.suppliers_list(company_id)
    return JsonResponse(data, safe=False)


def _fop_payment_lines(ticket, lines):
    """
    Mirrors the FOP Payment tab in the JV modal (renderFopPaymentTab in
    page-ticket-entry.js) — only posts when the ticket's FOP != Cash
    (first line's FOP is the ticket's representative FOP, same convention
    _compute_jv_lines uses). Own Card credits the FOP Master card's own
    ledger; Client Card credits Customer instead (the client's own card
    was charged directly). Debits Supplier the same amount either way —
    this is what nets Supplier's JV credit back to zero for that ticket
    once the card/customer side absorbs it, instead of double-counting.
    """
    fop = lines[0].fop if lines else None
    if not fop or fop == "Cash":
        return []

    supplier_groups = {}
    for l in lines:
        group = supplier_groups.setdefault(l.supplier_id, {"ledger": l.supplier, "amount": 0.0})
        group["amount"] += (
            float(l.supplier_cost) - float(l.computed_supp_commission) + float(l.computed_supp_tds)
            + float(l.supp_markup) + float(l.supp_addl_markup)
            + float(l.supp_service_fee) + float(l.supp_addl_service_fee)
            + float(l.computed_supp_gst)
        )
    total_amount = round(sum(g["amount"] for g in supplier_groups.values()), 2)
    if total_amount == 0:
        return []

    result = [(g["ledger"].id, g["amount"], 0) for g in supplier_groups.values() if g["ledger"]]
    if fop == "Own Card":
        card_number = lines[0].card_number or ""
        card = sp_client.fop_master_get_by_card_number(ticket.company_id, card_number)
        if card:
            result.append((card["card_master_ledger_id"], 0, total_amount))
    else:  # Client Card
        result.append((ticket.customer_id, 0, total_amount))
    return result


def _pg_receipt_lines(ticket, lines):
    """
    Mirrors the PG Receipts tab (renderPgReceiptsTab) — only posts when
    Payment Mode = "Payment Gateway". Credits Customer the full Total
    Billed (same amount Customer was already debited in the JV), netting
    that ticket's Customer balance to zero (fully settled via gateway).

    The gateway ledger's own Debit = Total Billed (compute_total(), same
    figure as the Customer credit — includes Sup Markup/Sup Addl
    Markup/Sup Service Fee/Sup Addl Service Fee/Sup GST Amount) + PG
    Charges + PG GST (PG Charges * that gateway's PG Charges Master
    ledger's own GST% — display-only elsewhere, not part of GST Amount/
    computed_gst, but included here in the gateway's own Debit total).

    PG Charges are then ALSO debited against that gateway's PG Master ->
    PG Charges Master ledger and credited back against the gateway
    ledger itself - netting the gateway ledger back down by that amount
    while still recording the charges as their own real expense line.
    PG GST is shown as its own Credit line the same way (see
    ledger_book_report / day_book_report's callers of this function -
    both fold every tuple this returns into that ledger's real balance).
    """
    if ticket.payment_mode != "Payment Gateway":
        return []
    customer_total = round(sum(float(l.compute_total()) for l in lines), 2)
    if customer_total == 0:
        return []
    result = [(ticket.customer_id, 0, customer_total)]
    snapshot = _pg_master_effective_snapshot(ticket.company_id, ticket.payment_gateway_ref or "", ticket.invoice_date or ticket.booking_ref_date)
    if snapshot:
        pg_charges_total = round(sum(float(l.pg_charges or 0) for l in lines), 2)
        pg_gst_pct = snapshot["pg_charges_master_ledger_gst_percentage"]
        pg_gst_total = round(pg_charges_total * pg_gst_pct / 100, 2)

        gateway_debit_total = round(customer_total + pg_charges_total + pg_gst_total, 2)
        result.append((snapshot["payment_master_ledger_id"], gateway_debit_total, 0))
        if pg_charges_total and snapshot["pg_charges_master_ledger_id"]:
            result.append((snapshot["pg_charges_master_ledger_id"], pg_charges_total, 0))
            result.append((snapshot["payment_master_ledger_id"], 0, pg_charges_total))
        if pg_gst_total:
            result.append((snapshot["payment_master_ledger_id"], 0, pg_gst_total))
    return result


def _pg_master_effective_snapshot(company_id, gateway_name, as_of_date):
    """
    Resolves the PG Master ledger mapping + PG Charges Percentage that was
    actually in force for `gateway_name` on `as_of_date` (a ticket's own
    Invoice Date) — the latest PGMasterHistory row whose effective_from
    is on or before that date, falling back to the gateway's live PGMaster
    row when no history snapshot qualifies (tickets booked before any
    Effective From date was ever recorded for this gateway).

    This is the single source of truth every PG Charges calculation and
    JV/report posting must go through, so editing a gateway's rate/ledger
    later never rewrites the ledger or amount already-booked tickets
    calculate against.
    """
    if not gateway_name:
        return None
    snapshot = sp_client.pg_master_effective_snapshot(company_id, gateway_name, as_of_date)
    if not snapshot:
        return None
    return {
        "payment_master_ledger_id": snapshot["payment_master_ledger_id"],
        "payment_master_ledger_name": snapshot["payment_master_ledger_name"],
        "pg_charges_master_ledger_id": snapshot["pg_charges_master_ledger_id"],
        "pg_charges_master_ledger_name": snapshot["pg_charges_master_ledger_name"],
        "pg_charges_master_ledger_gst_percentage": float(snapshot["pg_charges_master_ledger_gst_percentage"] or 0),
        "pg_charges_percentage": float(snapshot["pg_charges_percentage"] or 0),
        "effective_from": snapshot["effective_from"].isoformat() if snapshot["effective_from"] else None,
    }


def _ledger_balance_deltas(company_id, as_of_date=None, from_date=None):
    """
    Net Debit-minus-Credit per ledger_id, accumulated from every posted
    transaction for this company — used to turn each Ledger's static
    opening_balance into its real, current running balance.

    Sources, since ticket-driven JournalVoucher rows never persist their
    per-ledger breakdown (only the aggregate total_debit/total_credit —
    see ticket_create above), only manual Vouchers do:
      1. Manual Vouchers (voucher-entry.html, its own separate table from
         JournalVoucher) — lines_json already has a resolved
         ledger_id/debit/credit per line, just sum those.
      2. Every Ticket's Journal Voucher tab lines, recomputed live via
         _compute_jv_lines (same formula the JV tab itself uses).
      3. Every Ticket's FOP Payment tab lines (_fop_payment_lines).
      4. Every Ticket's PG Receipts tab lines (_pg_receipt_lines).
    All three JV-modal tabs post real ledger movements, not just the
    first one — a ticket paid via Payment Gateway settles its Customer
    debit right back out through the PG Receipts tab, for example, so
    skipping tabs 3/4 overstates ledgers that are actually fully settled.

    as_of_date (optional, "YYYY-MM-DD"): only include transactions dated
    on or before it — a period-end "closing balance" snapshot (Cash &
    Bank Book) instead of the always-current balance Chart of Accounts
    and the Ledger report want.

    from_date (optional, "YYYY-MM-DD"): only include transactions dated
    on or after it too — together with as_of_date this gives the net
    MOVEMENT strictly within one period (Profit and Loss Account), as
    opposed to the all-time-to-date running balance every other caller
    of this function wants (opening_balance is meaningless for a P&L
    period and is deliberately never added on top of this elsewhere).
    """
    deltas = {}

    def add(ledger_id, debit, credit):
        if not ledger_id:
            return
        deltas[ledger_id] = deltas.get(ledger_id, 0.0) + float(debit or 0) - float(credit or 0)

    for v in sp_client.vouchers_list(company_id):
        voucher_date = v["voucher_date"]
        if as_of_date and voucher_date and voucher_date > _parse_date(as_of_date):
            continue
        if from_date and voucher_date and voucher_date < _parse_date(from_date):
            continue
        for line in (json.loads(v["lines_json"]) if v["lines_json"] else []):
            add(line.get("ledger_id"), line.get("debit"), line.get("credit"))

    # Shared across every ticket below (all belong to this same company_id)
    # instead of _compute_jv_lines re-querying its own fresh copy of each
    # for every single ticket - see that function's own docstring/comments
    # for why this was the dominant cost on pages that process many
    # tickets at once (Chart of Accounts, Trial Balance, Cash & Bank Book).
    jv_mapping_cache, jv_company_state = _jv_prep(company_id)

    ticket_groups = {}
    for row in sp_client.tickets_list_for_balance(company_id, as_of_date=as_of_date, from_date=from_date):
        ticket_groups.setdefault(row["ticket_id"], {"header": row, "line_rows": []})["line_rows"].append(row)
    for group in ticket_groups.values():
        header = group["header"]
        ticket_proxy = Ticket(
            company_id=header["company_id"],
            customer=Ledger(id=header["customer_id"], name=header["customer_name"], state_name=header["customer_state_name"]),
            booking_reference=header["booking_reference"], airline_pnr=header["airline_pnr"],
            payment_mode=header["payment_mode"], payment_gateway_ref=header["payment_gateway_ref"],
            invoice_date=header["invoice_date"], booking_ref_date=header["booking_ref_date"],
        )
        lines = [
            TicketLine(
                ticket=ticket_proxy,
                supplier=Ledger(id=r["supplier_ledger_id"], name=r["supplier_name"]) if r["supplier_ledger_id"] else None,
                **{f: r[f] for f in TICKET_LINE_FIELDS if f in r},
            )
            for r in group["line_rows"]
        ]
        accounts, _narration, _total_debit, _total_credit = _compute_jv_lines(ticket_proxy, lines, mapping_cache=jv_mapping_cache, company_state=jv_company_state)
        for a in accounts:
            add(a.get("ledger_id"), a.get("debit"), a.get("credit"))
        for ledger_id, debit, credit in _fop_payment_lines(ticket_proxy, lines):
            add(ledger_id, debit, credit)
        for ledger_id, debit, credit in _pg_receipt_lines(ticket_proxy, lines):
            add(ledger_id, debit, credit)

    # Reschedule tickets - entirely separate/additive from the Booking
    # tickets above (see _compute_reschedule_jv_lines' own docstring) -
    # same live-recompute convention, just against RescheduleAirlineTicket/
    # RescheduleAirlineTicketLine and its own JV formula + FOP/PG tabs.
    resched_groups = {}
    for row in sp_client.reschedule_tickets_list_for_balance(company_id, as_of_date=as_of_date, from_date=from_date):
        resched_groups.setdefault(row["reschedule_ticket_id"], {"header": row, "line_rows": []})["line_rows"].append(row)
    for group in resched_groups.values():
        header = group["header"]
        resched_proxy = RescheduleAirlineTicket(
            company_id=header["company_id"],
            customer=Ledger(id=header["customer_id"], name=header["customer_name"], state_name=header["customer_state_name"]),
            booking_reference=header["booking_reference"], airline_pnr=header["airline_pnr"],
            payment_mode=header["payment_mode"], payment_gateway_ref=header["payment_gateway_ref"],
            invoice_date=header["invoice_date"], booking_ref_date=header["booking_ref_date"],
        )
        lines = [
            RescheduleAirlineTicketLine(
                reschedule_ticket=resched_proxy,
                supplier=Ledger(id=r["supplier_ledger_id"], name=r["supplier_name"]) if r["supplier_ledger_id"] else None,
                **{f: r[f] for f in RESCHED_LINE_FIELDS if f in r},
            )
            for r in group["line_rows"]
        ]
        accounts, _narration, _total_debit, _total_credit = _compute_reschedule_jv_lines(resched_proxy, lines, mapping_cache=jv_mapping_cache, company_state=jv_company_state)
        for a in accounts:
            add(a.get("ledger_id"), a.get("debit"), a.get("credit"))
        for ledger_id, debit, credit in _reschedule_fop_payment_lines(resched_proxy, lines):
            add(ledger_id, debit, credit)
        for ledger_id, debit, credit in _reschedule_pg_receipt_lines(resched_proxy, lines):
            add(ledger_id, debit, credit)

    return deltas


def accounts_list(request):
    """
    GET /api/accounts/?company_id=1
    Groups + ledgers merged into ONE flat list, in the exact shape
    page-accounts.js already expects (id, code, name, account_type,
    is_group, parent_id, balance) — so the Chart of Accounts tree
    renders new DB ledgers under their real group with zero frontend
    rendering changes. Balance is opening_balance plus every posted
    transaction's net Debit-minus-Credit against that ledger (see
    _ledger_balance_deltas) — not just the static opening balance.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    rows = []
    for g in LedgerGroup.objects.filter(company_id=company_id):
        rows.append({
            "id": f"g{g.id}", "code": g.code or "", "name": g.name,
            "account_type": g.account_type, "is_group": True,
            "parent_id": f"g{g.parent_id}" if g.parent_id else None,
            "balance": None,
        })
    deltas = _ledger_balance_deltas(company_id)
    # Was 2 queries PER ledger (Ticket.objects.filter(customer_id=...).exists()
    # / supplier_id) - with 50+ ledgers that's 100+ extra round trips on
    # every single page load. Two queries total instead, building a set to
    # check membership against inside the loop.
    used_customer_ids = set(Ticket.objects.filter(company_id=company_id).values_list("customer_id", flat=True))
    used_supplier_ids = set(Ticket.objects.filter(company_id=company_id, supplier_id__isnull=False).values_list("supplier_id", flat=True))
    # Reschedule tickets use ledgers too - a ledger used ONLY by a
    # reschedule (never by a plain Ticket) must still count as in-use.
    used_customer_ids |= set(RescheduleAirlineTicket.objects.filter(company_id=company_id).values_list("customer_id", flat=True))
    used_supplier_ids |= set(RescheduleAirlineTicket.objects.filter(company_id=company_id, supplier_id__isnull=False).values_list("supplier_id", flat=True))
    used_ledger_ids = used_customer_ids | used_supplier_ids
    for l in Ledger.objects.filter(company_id=company_id).select_related("group"):
        in_use = l.id in used_ledger_ids
        rows.append({
            "id": l.id, "code": l.group.code or "", "name": l.name,
            "account_type": l.account_type, "is_group": False,
            "parent_id": f"g{l.group_id}",
            "balance": float(l.signed_balance) + deltas.get(l.id, 0.0),
            "is_in_use": in_use,
        })
    return JsonResponse(rows, safe=False)


def _ledger_transactions(company_id, ledger, from_date=None, to_date=None):
    """
    Shared by ledger_book_report and ledger_monthly_summary - builds the
    exact same posted-transaction list for ONE real leaf Ledger (manual
    Vouchers' lines_json, plus every Ticket's Journal Voucher + FOP
    Payment + PG Receipts tabs, recomputed live) with a running balance,
    optionally windowed to [from_date, to_date] (ISO strings). Returns
    (company, txns, opening, closing, total_debit, total_credit).
    """
    ledger_id = ledger.id
    ledger_names = {r["id"]: r["name"] for r in sp_client.ledger_list(company_id)}
    company = sp_client.company_master_get(company_id)
    txns = []

    # Ascending by id, matching the plain (unordered) ORM queryset's
    # implicit insertion-order this replaced - txns.sort() below is a
    # stable sort keyed only by date, so ties need this same tie-break
    # order going in, or same-day rows could swap places on screen.
    for v in sorted(sp_client.vouchers_list(company_id), key=lambda row: row["id"]):
        voucher_date = v["voucher_date"]
        if from_date and voucher_date and voucher_date.isoformat() < from_date:
            continue
        if to_date and voucher_date and voucher_date.isoformat() > to_date:
            continue
        lines = json.loads(v["lines_json"]) if v["lines_json"] else []
        mine = [l for l in lines if l.get("ledger_id") == ledger_id]
        if not mine:
            continue
        debit = round(sum(float(l.get("debit") or 0) for l in mine), 2)
        credit = round(sum(float(l.get("credit") or 0) for l in mine), 2)
        others = sorted({l.get("ledger_name") for l in lines if l.get("ledger_id") != ledger_id and l.get("ledger_name")})
        txns.append({
            "date": voucher_date.isoformat() if voucher_date else None,
            "voucher_type": v["voucher_type"], "voucher_no": v["voucher_no"] or "-",
            "particulars": v["narration"] or ", ".join(others) or "-",
            "s_pnr": "-", "air_pnr": "-", "ticket_no": "-",
            "opposite": ", ".join(others) or "-", "debit": debit, "credit": credit,
            "ticket_id": None, "reschedule_ticket_id": None,
        })

    jv_mapping_cache, jv_company_state = _jv_prep(company_id)
    ticket_groups = {}
    for row in sp_client.tickets_list_for_balance(company_id, as_of_date=to_date, from_date=from_date):
        ticket_groups.setdefault(row["ticket_id"], {"header": row, "line_rows": []})["line_rows"].append(row)
    for group in ticket_groups.values():
        header = group["header"]
        ticket_proxy = Ticket(
            id=header["ticket_id"], company_id=header["company_id"],
            customer=Ledger(id=header["customer_id"], name=header["customer_name"], state_name=header["customer_state_name"]),
            booking_reference=header["booking_reference"], airline_pnr=header["airline_pnr"],
            payment_mode=header["payment_mode"], payment_gateway_ref=header["payment_gateway_ref"],
            invoice_date=header["invoice_date"], booking_ref_date=header["booking_ref_date"],
            invoice_number=header["invoice_number"], office_id=header["ticket_office_id"],
        )
        lines = [
            TicketLine(
                ticket=ticket_proxy,
                supplier=Ledger(id=r["supplier_ledger_id"], name=r["supplier_name"]) if r["supplier_ledger_id"] else None,
                **{f: r[f] for f in TICKET_LINE_FIELDS if f in r},
            )
            for r in group["line_rows"]
        ]
        accounts, _narration, _td, _tc = _compute_jv_lines(ticket_proxy, lines, mapping_cache=jv_mapping_cache, company_state=jv_company_state)
        combined = list(accounts)
        for lid, debit, credit in _fop_payment_lines(ticket_proxy, lines):
            combined.append({"ledger_id": lid, "ledger_name": ledger_names.get(lid, "-"), "debit": debit, "credit": credit})
        for lid, debit, credit in _pg_receipt_lines(ticket_proxy, lines):
            combined.append({"ledger_id": lid, "ledger_name": ledger_names.get(lid, "-"), "debit": debit, "credit": credit})

        mine = [a for a in combined if a.get("ledger_id") == ledger_id]
        if not mine:
            continue
        debit = round(sum(float(a.get("debit") or 0) for a in mine), 2)
        credit = round(sum(float(a.get("credit") or 0) for a in mine), 2)
        if debit == 0 and credit == 0:
            continue
        others = sorted({a.get("ledger_name") for a in combined if a.get("ledger_id") != ledger_id and a.get("ledger_name")})
        airline_names = sorted({n.strip() for r in group["line_rows"] for n in (r["airline_name"] or "").split(",") if n.strip()})
        ticket_nos = sorted({r["ticket_no"] for r in group["line_rows"] if r["ticket_no"]})
        particulars = " - ".join(x for x in [", ".join(airline_names), header["ticket_office_id"]] if x) or "-"
        txns.append({
            "date": header["invoice_date"].isoformat() if header["invoice_date"] else None,
            "voucher_type": "Tax Invoice", "voucher_no": header["voucher_no"] or header["invoice_number"],
            "particulars": particulars,
            "s_pnr": header["booking_reference"] or "-", "air_pnr": header["airline_pnr"] or "-",
            "ticket_no": ", ".join(ticket_nos) or "-",
            "opposite": ", ".join(others) or "-", "debit": debit, "credit": credit,
            "ticket_id": header["ticket_id"], "reschedule_ticket_id": None,
        })

    # Reschedule tickets - same recompute convention as above, against
    # RescheduleAirlineTicket/RescheduleAirlineTicketLine and the separate
    # _compute_reschedule_jv_lines formula + its own FOP/PG tabs. Rows
    # carry reschedule_ticket_id (not ticket_id) so the frontend can link
    # to ticket-entry.html?reschedule_saved_id=... instead.
    resched_groups = {}
    for row in sp_client.reschedule_tickets_list_for_balance(company_id, as_of_date=to_date, from_date=from_date):
        resched_groups.setdefault(row["reschedule_ticket_id"], {"header": row, "line_rows": []})["line_rows"].append(row)
    for group in resched_groups.values():
        header = group["header"]
        resched_proxy = RescheduleAirlineTicket(
            id=header["reschedule_ticket_id"], company_id=header["company_id"],
            customer=Ledger(id=header["customer_id"], name=header["customer_name"], state_name=header["customer_state_name"]),
            booking_reference=header["booking_reference"], airline_pnr=header["airline_pnr"],
            payment_mode=header["payment_mode"], payment_gateway_ref=header["payment_gateway_ref"],
            invoice_date=header["invoice_date"], booking_ref_date=header["booking_ref_date"],
            invoice_number=header["invoice_number"], office_id=header["ticket_office_id"],
        )
        lines = [
            RescheduleAirlineTicketLine(
                reschedule_ticket=resched_proxy,
                supplier=Ledger(id=r["supplier_ledger_id"], name=r["supplier_name"]) if r["supplier_ledger_id"] else None,
                **{f: r[f] for f in RESCHED_LINE_FIELDS if f in r},
            )
            for r in group["line_rows"]
        ]
        accounts, _narration, _td, _tc = _compute_reschedule_jv_lines(resched_proxy, lines, mapping_cache=jv_mapping_cache, company_state=jv_company_state)
        combined = list(accounts)
        for lid, debit, credit in _reschedule_fop_payment_lines(resched_proxy, lines):
            combined.append({"ledger_id": lid, "ledger_name": ledger_names.get(lid, "-"), "debit": debit, "credit": credit})
        for lid, debit, credit in _reschedule_pg_receipt_lines(resched_proxy, lines):
            combined.append({"ledger_id": lid, "ledger_name": ledger_names.get(lid, "-"), "debit": debit, "credit": credit})

        mine = [a for a in combined if a.get("ledger_id") == ledger_id]
        if not mine:
            continue
        debit = round(sum(float(a.get("debit") or 0) for a in mine), 2)
        credit = round(sum(float(a.get("credit") or 0) for a in mine), 2)
        if debit == 0 and credit == 0:
            continue
        others = sorted({a.get("ledger_name") for a in combined if a.get("ledger_id") != ledger_id and a.get("ledger_name")})
        airline_names = sorted({n.strip() for r in group["line_rows"] for n in (r["airline_name"] or "").split(",") if n.strip()})
        ticket_nos = sorted({r["ticket_no"] for r in group["line_rows"] if r["ticket_no"]})
        particulars = " - ".join(x for x in [", ".join(airline_names), header["ticket_office_id"]] if x) or "-"
        txns.append({
            "date": header["invoice_date"].isoformat() if header["invoice_date"] else None,
            "voucher_type": "Tax Invoice (Reschedule)", "voucher_no": header["voucher_no"] or header["invoice_number"],
            "particulars": particulars,
            "s_pnr": header["booking_reference"] or "-", "air_pnr": header["airline_pnr"] or "-",
            "ticket_no": ", ".join(ticket_nos) or "-",
            "opposite": ", ".join(others) or "-", "debit": debit, "credit": credit,
            "ticket_id": None, "reschedule_ticket_id": header["reschedule_ticket_id"],
        })

    txns.sort(key=lambda x: x["date"] or "")
    opening = float(ledger.opening_balance) if ledger.opening_balance_type == "Debit" else -float(ledger.opening_balance)
    running = opening
    total_debit = 0.0
    total_credit = 0.0
    for tx in txns:
        running = round(running + tx["debit"] - tx["credit"], 2)
        tx["running_balance"] = running
        total_debit += tx["debit"]
        total_credit += tx["credit"]

    return company, txns, round(opening, 2), round(running, 2), round(total_debit, 2), round(total_credit, 2)


def ledger_book_report(request):
    """
    GET /api/ledger-book/?company_id=1&ledger_id=42[&from_date&to_date]
    Tally-style ledger statement for ONE real leaf Ledger: opening balance,
    then one row per posted transaction that actually touches it (date,
    voucher type, voucher no, opposite account(s), debit, credit, running
    balance). Each row that came from a Ticket carries ticket_id, so the
    frontend can jump straight to that ticket (view mode) when clicked.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    ledger_id = request.GET.get("ledger_id")
    if not company_id or not ledger_id:
        return JsonResponse({"error": "company_id and ledger_id are required"}, status=400)
    try:
        ledger_id = int(ledger_id)
        ledger = Ledger.objects.get(id=ledger_id, company_id=company_id)
    except (ValueError, Ledger.DoesNotExist):
        return JsonResponse({"error": "Ledger not found."}, status=404)

    from_date = request.GET.get("from_date")
    to_date = request.GET.get("to_date")

    company, txns, opening, closing, total_debit, total_credit = _ledger_transactions(company_id, ledger, from_date, to_date)

    return JsonResponse({
        "ledger_id": ledger.id, "ledger_name": ledger.name,
        "company_name": company["company_name"] if company else "",
        "from_date": from_date, "to_date": to_date,
        "opening_balance": opening,
        "closing_balance": closing,
        "total_debit": total_debit, "total_credit": total_credit,
        "transactions": txns,
    })


def ledger_monthly_summary(request):
    """
    GET /api/ledger-book/monthly/?company_id=1&ledger_id=42[&from_date&to_date]
    Tally-style "Monthly Summary" sitting between Trial Balance and the
    full Ledger Book - one row per calendar month in the requested window
    (Debit total, Credit total, running Closing Balance; months with no
    activity just carry the balance forward unchanged), each with its own
    from_date/to_date so the frontend can drill into Ledger Book pre-
    filtered to that one month.

    Defaults to the company's full financial year when from_date/to_date
    aren't given. When they are (the page's own From/To filter), the
    window's Opening Balance is the real running balance as of the day
    before from_date - not the ledger's own (FY-start) opening_balance -
    computed by replaying every transaction before that date first.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    ledger_id = request.GET.get("ledger_id")
    if not company_id or not ledger_id:
        return JsonResponse({"error": "company_id and ledger_id are required"}, status=400)
    try:
        ledger_id = int(ledger_id)
        ledger = Ledger.objects.get(id=ledger_id, company_id=company_id)
    except (ValueError, Ledger.DoesNotExist):
        return JsonResponse({"error": "Ledger not found."}, status=404)

    company = CompanyMaster.objects.filter(id=company_id).first()
    fy_start = company.financial_year_from if company and company.financial_year_from else None
    if not fy_start:
        # No explicit Financial Year From set on this company yet - default
        # by country instead of always assuming India's Apr-Mar year:
        # UAE (and any other country whose books run on the calendar year)
        # defaults to Jan-Dec instead.
        today = date.today()
        if _company_uses_calendar_year(company):
            fy_start = date(today.year, 1, 1)
        else:
            fy_year = today.year if today.month >= 4 else today.year - 1
            fy_start = date(fy_year, 4, 1)
    fy_end = date(fy_start.year + 1, fy_start.month, fy_start.day) - timedelta(days=1)

    req_from = request.GET.get("from_date")
    req_to = request.GET.get("to_date")
    try:
        window_from = date.fromisoformat(req_from) if req_from else fy_start
        window_to = date.fromisoformat(req_to) if req_to else fy_end
    except ValueError:
        return JsonResponse({"error": "from_date/to_date must be YYYY-MM-DD."}, status=400)
    if window_from > window_to:
        return JsonResponse({"error": "From date must be on or before To date."}, status=400)

    ledger_opening = float(ledger.opening_balance) if ledger.opening_balance_type == "Debit" else -float(ledger.opening_balance)
    if window_from > fy_start:
        # Balance as it actually stood the day before this window starts -
        # not the ledger's own (FY-start) opening_balance, which is only
        # correct when the window starts at the FY's own beginning.
        _c, _t, _o, opening, _td, _tc = _ledger_transactions(
            company_id, ledger, fy_start.isoformat(), (window_from - timedelta(days=1)).isoformat()
        )
    else:
        opening = ledger_opening

    company, txns, _o2, _closing, _td2, _tc2 = _ledger_transactions(
        company_id, ledger, window_from.isoformat(), window_to.isoformat()
    )

    # One row per calendar month spanned by the window, each with its own
    # [from_date, to_date] for drill-down into Ledger Book.
    months = []
    cursor = date(window_from.year, window_from.month, 1)
    while cursor <= window_to:
        month_start = max(cursor, window_from)
        month_end = min(
            date(cursor.year + (1 if cursor.month == 12 else 0), (cursor.month % 12) + 1, 1) - timedelta(days=1),
            window_to,
        )
        months.append({
            "month_name": cursor.strftime("%B"), "year": cursor.year,
            "from_date": month_start.isoformat(), "to_date": month_end.isoformat(),
            "debit": 0.0, "credit": 0.0, "closing_balance": None,
        })
        cursor = date(cursor.year + (1 if cursor.month == 12 else 0), (cursor.month % 12) + 1, 1)

    running = opening
    for m in months:
        month_txns = [tx for tx in txns if m["from_date"] <= (tx["date"] or "") <= m["to_date"]]
        m["debit"] = round(sum(tx["debit"] for tx in month_txns), 2)
        m["credit"] = round(sum(tx["credit"] for tx in month_txns), 2)
        running = round(running + m["debit"] - m["credit"], 2)
        # Carried forward even for a month with zero activity - matches
        # the reference "Monthly Summary" screen, where an empty month
        # still shows the balance as it stood, not a blank cell.
        m["closing_balance"] = running
        m["has_activity"] = bool(month_txns)

    total_debit = round(sum(m["debit"] for m in months), 2)
    total_credit = round(sum(m["credit"] for m in months), 2)

    return JsonResponse({
        "ledger_id": ledger.id, "ledger_name": ledger.name,
        "company_name": company["company_name"] if company else "",
        "financial_year_from": fy_start.isoformat(), "financial_year_to": fy_end.isoformat(),
        "from_date": window_from.isoformat(), "to_date": window_to.isoformat(),
        "opening_balance": round(opening, 2),
        "closing_balance": running,
        "total_debit": total_debit, "total_credit": total_credit,
        "months": months,
    })


def day_book_report(request):
    """
    GET /api/day-book/?company_id=1[&from_date&to_date]
    Tally-style Day Book: one row per posted voucher (every manual
    Voucher + every ticket-driven JournalVoucher, Booking and Reschedule
    alike) within the date range - unlike the Ledger report this does not
    re-explode a voucher into its individual ledger lines, it lists the
    voucher itself. Manual Vouchers show their own real total_debit/
    total_credit (a true, balanced double-entry total). Ticket-driven
    rows show the Customer ledger's own posted amount instead of the
    voucher's stored total_debit/total_credit - that stored total is
    inflated well past the real invoice value by JV_LINE_MAP's
    intentional duplicate Consolidator/Markup Credit lines (see
    jv_hardcode.py), so it doesn't represent "the value of this
    transaction" the way this column should; the Customer amount is
    recomputed live via _compute_jv_lines/_compute_reschedule_jv_lines
    for that reason. Shown under Debit ONLY (2026-10-08, explicit request) -
    a ticket is always a Debit-the-customer Tax Invoice, so Credit is 0 for
    these rows rather than mirroring the same figure onto both sides;
    manual Vouchers keep their own real total_debit/total_credit on their
    own natural sides. Ticket-driven rows also surface S PNR / Air-PNR /
    Ticket No and are clickable through to that ticket (ticket_id) or
    reschedule ticket (reschedule_ticket_id), same convention as the
    Ledger report. Manual Vouchers and ticket-driven JournalVoucher rows
    live in separate tables, so this merges all three querysets into one
    chronological list rather than filtering one table. Because of the
    Debit-only convention above, the grand Total row at the bottom no
    longer nets Debit=Credit overall - only manual Vouchers (each
    individually balanced) still contribute equally to both totals.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    from_date = request.GET.get("from_date")
    to_date = request.GET.get("to_date")
    company = CompanyMaster.objects.filter(id=company_id).first()

    # Seeded ONCE for the whole report (2026-10-08 perf fix) - every call
    # below to _compute_jv_lines/_compute_reschedule_jv_lines used to be
    # given no mapping_cache/company_state, so each one built its OWN
    # empty cache and re-ran every single Master Mapping lookup (~20
    # fields) from scratch - with many vouchers that was hundreds of
    # repeated, identical queries (the mapping data is the same company
    # throughout this whole request) for no reason. This is the exact
    # same _jv_prep() already used by ticket_create/ticket_update for the
    # same reason.
    mapping_cache, company_state = _jv_prep(company_id)

    txns = []

    manual_vouchers = Voucher.objects.filter(company_id=company_id)
    if from_date:
        manual_vouchers = manual_vouchers.filter(voucher_date__gte=from_date)
    if to_date:
        manual_vouchers = manual_vouchers.filter(voucher_date__lte=to_date)
    for v in manual_vouchers:
        lines = v.lines_json or []
        # Particulars + which side the amount shows under = the FIRST
        # ledger line as actually entered/saved on the voucher (2026-10-08,
        # replaces an earlier voucher-type-based guess that got the
        # direction backwards for a real Payment voucher: Dr the party
        # first, Cr Bank second - the user wants "Party 1000 Debit" shown,
        # not a fixed "Payment = show under Credit" rule). lines_json
        # preserves entry order (voucher-entry.html's own row order), so
        # lines[0] is whichever ledger was picked first - typically the
        # party/expense side for Payment/Receipt, the first ledger entered
        # for Journal/Contra. Its own debit/credit (not a derived "opposite"
        # ledger) is used directly, so whichever side it actually is gets
        # shown - no voucher-type-specific rule needed.
        first = lines[0] if lines else {}
        first_name = first.get("ledger_name")
        debit_amt = float(first.get("debit") or 0)
        credit_amt = float(first.get("credit") or 0)
        txns.append({
            "date": v.voucher_date.isoformat() if v.voucher_date else None,
            "particulars": v.narration or first_name or "-",
            "voucher_type": v.voucher_type,
            "s_pnr": "-", "air_pnr": "-", "ticket_no": "-",
            "voucher_no": v.voucher_no or "-",
            "debit": debit_amt, "credit": credit_amt,
            "ticket_id": None, "reschedule_ticket_id": None,
        })

    journal_vouchers = JournalVoucher.objects.filter(company_id=company_id, source_ticket__isnull=False).select_related(
        "source_ticket", "source_ticket__customer"
    ).prefetch_related(
        # select_related("supplier") on the inner queryset too - _compute_
        # jv_lines reads l.supplier per line to group the Supplier row;
        # without this each distinct supplier access is its own query.
        Prefetch("source_ticket__lines", queryset=TicketLine.objects.select_related("supplier"))
    )
    if from_date:
        journal_vouchers = journal_vouchers.filter(voucher_date__gte=from_date)
    if to_date:
        journal_vouchers = journal_vouchers.filter(voucher_date__lte=to_date)
    for v in journal_vouchers:
        t = v.source_ticket
        # prefetch_related above means .all() here reuses the already-
        # fetched batch instead of firing its own query per ticket (was a
        # real N+1 - one extra round trip per voucher).
        lines = list(t.lines.all()) if t else []
        ticket_nos = sorted({l.ticket_no for l in lines if l.ticket_no})
        # The Customer ledger's OWN posted amount, not the voucher's
        # total_debit/total_credit - that total is inflated well past the
        # real invoice value by JV_LINE_MAP's intentional duplicate
        # Consolidator/Markup Credit lines (see jv_hardcode.py), so it
        # doesn't mean "the value of this transaction" the way Day Book's
        # Amount column should. Shown under both Debit and Credit (the
        # ticket is always a Debit-the-customer Tax Invoice), same
        # same-value-both-columns convention this table already uses.
        customer_amount = 0.0
        if lines:
            accounts, _n, _td, _tc = _compute_jv_lines(t, lines, mapping_cache, company_state)
            customer_row = next((a for a in accounts if a.get("role") == "customer"), None)
            if customer_row:
                customer_amount = customer_row.get("debit") or customer_row.get("credit") or 0.0
        txns.append({
            "date": v.voucher_date.isoformat() if v.voucher_date else None,
            "particulars": t.customer.name if t and t.customer else "-",
            "voucher_type": v.voucher_type,
            "s_pnr": (t.booking_reference if t else "") or "-", "air_pnr": (t.airline_pnr if t else "") or "-",
            "ticket_no": ", ".join(ticket_nos) or "-",
            "voucher_no": v.voucher_no or "-",
            # Shown under Debit ONLY (2026-10-08) - a ticket is always a
            # Debit-the-customer Tax Invoice, so Credit stays 0 instead of
            # mirroring the same figure onto both sides (previous
            # convention - changed on explicit request; this means the
            # Day Book's own grand Total row no longer nets Debit=Credit
            # overall, since manual Vouchers below still contribute to
            # both sides).
            "debit": customer_amount, "credit": 0.0,
            "ticket_id": t.id if t else None, "reschedule_ticket_id": None,
        })

    # Reschedule tickets' own JournalVoucher rows - entirely separate from
    # the Booking rows above (filtered out there via source_ticket__isnull
    # =False), linked instead via source_reschedule_ticket. Clickable
    # through to ticket-entry.html?reschedule_saved_id=... (reschedule_
    # ticket_id), not the plain ticket_id the Booking rows use.
    resched_journal_vouchers = JournalVoucher.objects.filter(
        company_id=company_id, source_reschedule_ticket__isnull=False
    ).select_related("source_reschedule_ticket", "source_reschedule_ticket__customer").prefetch_related(
        Prefetch("source_reschedule_ticket__lines", queryset=RescheduleAirlineTicketLine.objects.select_related("supplier"))
    )
    if from_date:
        resched_journal_vouchers = resched_journal_vouchers.filter(voucher_date__gte=from_date)
    if to_date:
        resched_journal_vouchers = resched_journal_vouchers.filter(voucher_date__lte=to_date)
    for v in resched_journal_vouchers:
        rt = v.source_reschedule_ticket
        lines = list(rt.lines.all()) if rt else []
        ticket_nos = sorted({l.ticket_no for l in lines if l.ticket_no})
        # Same reasoning as the Booking loop above - the Customer ledger's
        # own amount, not the voucher's inflated total_debit/total_credit.
        customer_amount = 0.0
        if lines:
            accounts, _n, _td, _tc = _compute_reschedule_jv_lines(rt, lines, mapping_cache, company_state)
            customer_row = next((a for a in accounts if a.get("role") == "customer"), None)
            if customer_row:
                customer_amount = customer_row.get("debit") or customer_row.get("credit") or 0.0
        txns.append({
            "date": v.voucher_date.isoformat() if v.voucher_date else None,
            "particulars": rt.customer.name if rt and rt.customer else "-",
            "voucher_type": v.voucher_type,
            "s_pnr": (rt.booking_reference if rt else "") or "-", "air_pnr": (rt.airline_pnr if rt else "") or "-",
            "ticket_no": ", ".join(ticket_nos) or "-",
            "voucher_no": v.voucher_no or "-",
            # Same Debit-only convention as the Booking rows above.
            "debit": customer_amount, "credit": 0.0,
            "ticket_id": None, "reschedule_ticket_id": rt.id if rt else None,
        })

    txns.sort(key=lambda x: x["date"] or "")
    total_debit = round(sum(tx["debit"] for tx in txns), 2)
    total_credit = round(sum(tx["credit"] for tx in txns), 2)

    return JsonResponse({
        "company_name": company.company_name if company else "",
        "from_date": from_date, "to_date": to_date,
        "total_debit": total_debit, "total_credit": total_credit,
        "transactions": txns,
    })


def _normalize_group_name(name):
    """Case/punctuation-insensitive comparison key - "Cash-in-Hand",
    "Cash-in-hand" and "Cash in Hand" all normalize to the same string."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


CASH_BANK_BOOK_GROUP_NAMES = ["Cash-in-Hand", "Bank Accounts"]


def cash_bank_book_report(request):
    """
    GET /api/cash-bank-book/?company_id=1[&from_date&to_date]
    Tally-style Cash & Bank Book "Group Summary": every Ledger under the
    Cash-in-Hand and Bank Accounts groups, each showing its own closing
    balance as of to_date (opening_balance + every posted transaction up
    to that date - see _ledger_balance_deltas(as_of_date=...)), grouped
    under its own group with a group subtotal, plus a grand total across
    both groups.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    from_date = request.GET.get("from_date")
    to_date = request.GET.get("to_date")
    deltas = _ledger_balance_deltas(company_id, as_of_date=to_date)

    target_keys = {_normalize_group_name(n) for n in CASH_BANK_BOOK_GROUP_NAMES}
    groups_out = []
    grand_total = 0.0
    matched_groups = [g for g in LedgerGroup.objects.filter(company_id=company_id)
                       if _normalize_group_name(g.name) in target_keys]
    # Keep Cash-in-Hand before Bank Accounts regardless of DB row order.
    matched_groups.sort(key=lambda g: CASH_BANK_BOOK_GROUP_NAMES.index(
        next(n for n in CASH_BANK_BOOK_GROUP_NAMES if _normalize_group_name(n) == _normalize_group_name(g.name))
    ))

    for g in matched_groups:
        ledger_rows = []
        group_total = 0.0
        for l in Ledger.objects.filter(company_id=company_id, group_id=g.id).order_by("name"):
            bal = round(float(l.signed_balance) + deltas.get(l.id, 0.0), 2)
            ledger_rows.append({"id": l.id, "name": l.name, "closing_balance": bal})
            group_total += bal
        group_total = round(group_total, 2)
        groups_out.append({"group_name": g.name, "closing_balance": group_total, "ledgers": ledger_rows})
        grand_total += group_total

    return JsonResponse({
        "from_date": from_date, "to_date": to_date,
        "groups": groups_out, "grand_total": round(grand_total, 2),
    })


def _trial_balance_dr_cr(amount):
    """Positive net (Debit-heavy, per Ledger.signed_balance's convention)
    shows in the Debit column, negative (Credit-heavy) in the Credit
    column as a positive number - never both on the same row."""
    amount = round(amount, 2)
    return (amount, 0.0) if amount >= 0 else (0.0, -amount)


def trial_balance_report(request):
    """
    GET /api/trial-balance/?company_id=1&to_date=2026-09-05[&from_date=...][&group_id=7]
    Tally-style Trial Balance, drillable to any depth via group_id:

    - No group_id (top level): one row per "primary" Ledger Group - a
      direct child of a root group like Assets/Liabilities/Income/
      Expenses (e.g. Capital Account, Current Liabilities, Current
      Assets, Indirect Income, Indirect Expenses).
    - group_id given: same shape, but rows are THAT group's own
      immediate children instead (a mix of sub-groups and/or Ledgers
      straight under it) - what report-trial-balance.html shows when
      you click into a group. "context" describes that group itself
      (its own name + rolled-up total, shown as the page's highlighted
      header row) and "back" says where the Back link at the bottom
      should go: another group_id one level up, or null for the plain
      top-level Trial Balance if this group's own parent is just an
      internal root wrapper (Assets/Liabilities/Income/Expenses) that
      the UI never shows as its own page.

    Every row's own total is rolled up from every Ledger under it
    however deeply nested (see group_rollup) even though only ONE level
    of children is ever returned per call - drilling further is a
    separate request with that row's own id as group_id.

    Closing Balance is always "as of to_date" (opening_balance plus every
    posted transaction up to that date, from ledger inception - not just
    movement within from_date/to_date, which is only decorative in the
    header here, matching real Tally behaviour) - same convention as
    cash_bank_book_report.

    Rows with no Ledger anywhere under them (e.g. an unused "Fixed
    Assets") are left out entirely, same as Tally only listing groups
    that actually have something posted to them.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    from_date = request.GET.get("from_date")
    to_date = request.GET.get("to_date")
    group_id = request.GET.get("group_id")
    deltas = _ledger_balance_deltas(company_id, as_of_date=to_date)

    all_groups = sp_client.ledger_group_list(company_id)
    groups_by_id = {g["id"]: g for g in all_groups}
    children_by_parent = {}
    for g in all_groups:
        children_by_parent.setdefault(g["parent_id"], []).append(g)
    all_ledgers = sp_client.ledger_list(company_id)
    ledgers_by_group = {}
    for l in all_ledgers:
        ledgers_by_group.setdefault(l["parent_id"], []).append(l)

    def ledger_balance(l):
        return float(l["balance"]) + deltas.get(l["id"], 0.0)

    def group_rollup(gid):
        """(total balance, ledger count) for everything under this group, however deep."""
        total = sum(ledger_balance(l) for l in ledgers_by_group.get(gid, []))
        count = len(ledgers_by_group.get(gid, []))
        for child in children_by_parent.get(gid, []):
            child_total, child_count = group_rollup(child["id"])
            total += child_total
            count += child_count
        return total, count

    def build_rows(parent_group_id):
        rows = []
        total_debit = 0.0
        total_credit = 0.0
        for g in sorted(children_by_parent.get(parent_group_id, []), key=lambda g: g["name"]):
            g_total, g_count = group_rollup(g["id"])
            if g_count == 0:
                continue
            debit, credit = _trial_balance_dr_cr(g_total)
            rows.append({"type": "group", "id": g["id"], "name": g["name"], "debit": debit, "credit": credit})
            total_debit += debit
            total_credit += credit
        for l in sorted(ledgers_by_group.get(parent_group_id, []), key=lambda l: l["name"]):
            l_debit, l_credit = _trial_balance_dr_cr(ledger_balance(l))
            rows.append({"type": "ledger", "id": l["id"], "name": l["name"], "debit": l_debit, "credit": l_credit})
            total_debit += l_debit
            total_credit += l_credit
        return rows, round(total_debit, 2), round(total_credit, 2)

    root_group_ids = {g["id"] for g in all_groups if g["parent_id"] is None}

    context = None
    back = None
    if group_id:
        group = groups_by_id.get(int(group_id))
        if not group:
            return JsonResponse({"error": "Group not found."}, status=404)
        g_total, _count = group_rollup(group["id"])
        debit, credit = _trial_balance_dr_cr(g_total)
        context = {"id": group["id"], "name": group["name"], "debit": debit, "credit": credit}
        if group["parent_id"] in root_group_ids or group["parent_id"] is None:
            back = {"group_id": None, "label": "Trial Balance"}
        else:
            parent = groups_by_id.get(group["parent_id"])
            back = {"group_id": parent["id"] if parent else None, "label": parent["name"] if parent else "Trial Balance"}
        rows, total_debit, total_credit = build_rows(group["id"])
    else:
        # Top level - every "primary" group (parented directly by a root
        # wrapper) stands in for that wrapper, which is never shown itself.
        rows = []
        total_debit = 0.0
        total_credit = 0.0
        for rid in root_group_ids:
            r_rows, r_debit, r_credit = build_rows(rid)
            rows.extend(r_rows)
            total_debit += r_debit
            total_credit += r_credit
        rows.sort(key=lambda r: r["name"])
        total_debit = round(total_debit, 2)
        total_credit = round(total_credit, 2)

        # "Detailed View" checkbox (frontend) - when on, each primary
        # group row here also carries its own one-level-deeper "children"
        # array inline (the pre-drill-down behaviour), instead of the
        # user having to click in to see anything beneath a primary group.
        if request.GET.get("detailed") == "1":
            for row in rows:
                if row["type"] == "group":
                    row["children"], _cd, _cc = build_rows(row["id"])

    return JsonResponse({
        "from_date": from_date, "to_date": to_date,
        "context": context, "back": back,
        "rows": rows,
        "total_debit": total_debit, "total_credit": total_credit,
    })


# Real Ledger Group names this company's seed data always creates (see
# groups.html's own seeding) - a Trading & Profit and Loss Account is
# built from exactly these 6, same convention real Tally uses: Purchase
# Accounts/Direct Expenses/Sales Accounts/Direct Income form the Trading
# section (top), Indirect Expenses/Indirect Income form the P&L section
# (bottom). Matched by NAME (not id) since every company's own copy of
# these groups has a different id.
PROFIT_LOSS_GROUP_NAMES = {
    "purchase": "Purchase Accounts", "direct_expense": "Direct Expenses",
    "sales": "Sales Accounts", "direct_income": "Direct Income",
    "indirect_expense": "Indirect Expenses", "indirect_income": "Indirect Income",
}


def profit_loss_report(request):
    """
    GET /api/profit-loss/?company_id=1&from_date=...&to_date=...
    Classic two-column Trading & Profit and Loss Account (Tally-style,
    not a modern vertical income statement):

    Trading Account (top) - Dr: Purchase Accounts + Direct Expenses,
    Cr: Sales Accounts + Direct Income. Nets to Gross Profit (Cr > Dr,
    shown as "Gross Profit c/o" on the Dr side to balance it, then
    carried down as "Gross Profit b/f" on the Cr side of the P&L section
    below) or Gross Loss (the mirror image - "Gross Loss c/o" on Cr,
    "Gross Loss b/f" on Dr below).

    Profit and Loss Account (bottom) - Dr: Indirect Expenses (+ Gross
    Loss b/f if the Trading Account made a loss), Cr: Indirect Income
    (+ Gross Profit b/f if it made a profit). Nets to Net Profit (shown
    on the Dr side to balance, since Cr > Dr) or Net Loss (shown on the
    Cr side, since Dr > Cr) - matches the screenshot's own "Net Loss"
    placement exactly.

    Every one of the 6 named groups (PROFIT_LOSS_GROUP_NAMES) is rolled
    up and itemised by its own Ledgers, however deeply nested underneath
    it (sub-groups included) - a group with nothing posted under it in
    this period is left out entirely, same as Tally.

    Uses PERIOD movement only (_ledger_balance_deltas' own from_date
    param), never opening_balance - that's a Balance Sheet concept, not
    meaningful for a Profit and Loss Account covering just this period.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    from_date = request.GET.get("from_date")
    to_date = request.GET.get("to_date")
    deltas = _ledger_balance_deltas(company_id, as_of_date=to_date, from_date=from_date)

    all_groups = list(LedgerGroup.objects.filter(company_id=company_id))
    groups_by_name = {g.name: g for g in all_groups}
    children_by_parent = {}
    for g in all_groups:
        children_by_parent.setdefault(g.parent_id, []).append(g)
    all_ledgers = list(Ledger.objects.filter(company_id=company_id))
    ledgers_by_group = {}
    for l in all_ledgers:
        ledgers_by_group.setdefault(l.group_id, []).append(l)

    def ledgers_under(gid):
        """Every Ledger under this group, however deeply nested."""
        out = list(ledgers_by_group.get(gid, []))
        for child in children_by_parent.get(gid, []):
            out.extend(ledgers_under(child.id))
        return out

    # side="debit" (Purchase/Direct Expense/Indirect Expense) - a normal
    # expense posts as a Debit, so its own delta (debit - credit) IS the
    # amount directly. side="credit" (Sales/Direct Income/Indirect
    # Income) - income posts as a Credit, so the amount is the delta
    # flipped (credit - debit).
    def group_section(name, side):
        group = groups_by_name.get(name)
        if not group:
            return {"name": name, "items": [], "total": 0.0}
        items = []
        total = 0.0
        for l in sorted(ledgers_under(group.id), key=lambda l: l.name):
            d = deltas.get(l.id, 0.0)
            amount = d if side == "debit" else -d
            amount = round(amount, 2)
            if amount == 0:
                continue
            items.append({"ledger_id": l.id, "name": l.name, "amount": amount})
            total += amount
        return {"name": group.name, "items": items, "total": round(total, 2)}

    purchase = group_section(PROFIT_LOSS_GROUP_NAMES["purchase"], "debit")
    direct_expense = group_section(PROFIT_LOSS_GROUP_NAMES["direct_expense"], "debit")
    sales = group_section(PROFIT_LOSS_GROUP_NAMES["sales"], "credit")
    direct_income = group_section(PROFIT_LOSS_GROUP_NAMES["direct_income"], "credit")
    indirect_expense = group_section(PROFIT_LOSS_GROUP_NAMES["indirect_expense"], "debit")
    indirect_income = group_section(PROFIT_LOSS_GROUP_NAMES["indirect_income"], "credit")

    trading_dr = round(purchase["total"] + direct_expense["total"], 2)
    trading_cr = round(sales["total"] + direct_income["total"], 2)
    gross_profit = round(trading_cr - trading_dr, 2)  # positive = profit, negative = loss

    pl_dr = round(indirect_expense["total"] + (-gross_profit if gross_profit < 0 else 0), 2)
    pl_cr = round(indirect_income["total"] + (gross_profit if gross_profit > 0 else 0), 2)
    net_profit = round(pl_cr - pl_dr, 2)  # positive = profit, negative = loss

    return JsonResponse({
        "from_date": from_date, "to_date": to_date,
        "trading": {
            "debit": {"purchase": purchase, "direct_expense": direct_expense},
            "credit": {"sales": sales, "direct_income": direct_income},
            "gross_profit": gross_profit,  # negative means Gross Loss
            "total_debit": round(max(trading_dr, trading_cr), 2),
            "total_credit": round(max(trading_dr, trading_cr), 2),
        },
        "pl": {
            "debit": {"indirect_expense": indirect_expense},
            "credit": {"indirect_income": indirect_income},
            "net_profit": net_profit,  # negative means Net Loss
            "total_debit": round(max(pl_dr, pl_cr), 2),
            "total_credit": round(max(pl_dr, pl_cr), 2),
        },
    })


TICKET_HEADER_FIELDS = [
    "invoice_number", "invoice_date", "invoice_type", "booking_mode", "booking_type", "booking_status",
    "travel_type", "user_name", "currency", "roe", "booking_given_by",
    "booking_reference", "booking_ref_date", "airline_pnr", "gds_pnr", "office_id",
    "payment_mode", "payment_gateway_ref", "airline_category", "branch_name",
]
TICKET_LINE_FIELDS = [
    "airline_code", "airline_name", "airline_category", "flight_no", "ticket_no", "passenger_name", "pax_type",
    "sector", "travel_date", "cabin", "travel_class", "fare_type", "basic_fare", "yq", "yr", "k3_tax", "tax_others", "seat", "meal",
    "baggage", "other_ssr", "disc_on", "disc_type", "disc_value", "tds_per", "pg_charges", "pg_charges_percentage",
    "markup", "addl_markup", "ssr_markup", "service_fee", "addl_service_fee", "ssr_service_fee", "gst_pct", "status",
    "office_id", "fop", "card_number", "supp_comm_on", "supp_comm_type", "supp_comm_value", "supp_tds_per",
    "supp_markup", "supp_addl_markup", "supp_service_fee", "supp_addl_service_fee", "supp_gst_pct",
]
TICKET_LINE_NUMERIC_FIELDS = {
    "basic_fare", "yq", "yr", "k3_tax", "tax_others", "seat", "meal", "baggage", "other_ssr",
    "disc_value", "tds_per", "pg_charges", "pg_charges_percentage", "markup", "addl_markup", "ssr_markup", "service_fee", "addl_service_fee", "ssr_service_fee", "gst_pct",
    "supp_comm_value", "supp_tds_per",
    "supp_markup", "supp_addl_markup", "supp_service_fee", "supp_addl_service_fee", "supp_gst_pct",
}


def _safe_decimal(value, default=0):
    """
    Coerces whatever the client sent for a decimal field into a real,
    finite number. Guards against the crash seen in production: an
    empty string, None, or other non-numeric value reaching Django's
    DecimalField at save time raises decimal.InvalidOperation with an
    unhelpful traceback instead of a clean validation error.

    Critical subtlety: Python's float() does NOT raise for the strings
    "NaN", "Infinity", or "-Infinity" — it happily returns nan/inf,
    which then crashes later at Decimal.quantize() time with this exact
    same InvalidOperation error. A plain try/except around float()
    alone does not catch this; isfinite() explicitly does.
    """
    if value is None or value == "":
        return default
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _parse_date(val):
    if not val:
        return None
    return datetime.strptime(val, "%Y-%m-%d").date() if isinstance(val, str) else val


def _company_uses_calendar_year(company):
    """
    True for a company whose books run Jan-Dec (UAE and most countries
    outside India) rather than India's own Apr-Mar financial year - used
    only as a FALLBACK when that company has no explicit Financial Year
    From date set on CompanyMaster yet (once set, that explicit date
    always wins regardless of country - see ledger_monthly_summary).
    Matched loosely against CompanyMaster's free-text Country field
    rather than a fixed country list, so "UAE", "U.A.E", "United Arab
    Emirates" etc. all resolve the same way.
    """
    country = (company.country if company else "") or ""
    country = country.strip().lower()
    return bool(country) and country not in ("india", "in", "bharat")


def _next_voucher_no(model, company_id, category):
    """
    Next sequential number for this company+category, e.g. AL-1, AL-2 for
    Airline (model=JournalVoucher) or VCH-1, VCH-2 for a manual voucher
    (model=Voucher). Based on how many vouchers already exist in that
    category on that specific table — numbers are never reused even if
    an earlier voucher is later deleted, since we count existing rows at
    the moment of creation, inside the same atomic transaction as the
    insert that follows.
    """
    prefix = model.CATEGORY_PREFIX.get(category, "VCH")
    count = model.objects.filter(company_id=company_id, category=category).count()
    return f"{prefix}-{count + 1}"


def _compute_jv_lines(ticket, lines, mapping_cache=None, company_state=None):
    """
    Shared by both the auto-post-on-save (ticket_create) and the JV tab's
    read-only display (ticket_jv_preview) — one formula, used in exactly
    one place, so the two can never drift out of sync with each other.

    Driven by accounting/jv_hardcode.py's JV_LINE_MAP (project owner's
    update, 2026-09-18): every line's ledger is resolved from Master
    Mapping (per company + product_type="Airline") by (masters_category,
    field_name), except Customer/Supplier which keep resolving to the
    ticket's own real Ledger. Payment Mode / FOP no longer change which
    lines post — every combination produces the same structure.

    Supplier is picked per passenger line (not once on the ticket header),
    so lines can point at different supplier ledgers — group them here and
    emit one row per distinct supplier actually used. Lines with no
    supplier picked are grouped together under a single unassigned row.
    Supplier's Credit amount now also includes the Sup Markup/Sup Addl
    Markup/Sup Service Fee/Sup Addl Service Fee/Sup GST Amount fields.

    Per the project owner's explicit instruction, JV_LINE_MAP's two
    "Markup A/c" (and siblings) Credit lines are intentional duplicates —
    this JV does not need to debit-credit balance.
    """
    role_amounts = {
        "commission": sum(float(l.computed_supp_commission) for l in lines),
        "commission_tds": sum(float(l.computed_supp_tds) for l in lines),
        "supp_markup": sum(float(l.supp_markup) for l in lines),
        "supp_addl_markup": sum(float(l.supp_addl_markup) for l in lines),
        "supp_service_fee": sum(float(l.supp_service_fee) for l in lines),
        "supp_addl_service_fee": sum(float(l.supp_addl_service_fee) for l in lines),
        "supp_gst": sum(float(l.computed_supp_gst) for l in lines),
        "discount": sum(float(l.computed_discount) for l in lines),
        "discount_tds": sum(float(l.computed_tds) for l in lines),
        "markup": sum(float(l.markup) for l in lines),
        "addl_markup": sum(float(l.addl_markup) for l in lines),
        "ssr_markup": sum(float(l.ssr_markup) for l in lines),
        "service_fee": sum(float(l.service_fee) for l in lines),
        "addl_service_fee": sum(float(l.addl_service_fee) for l in lines),
        "ssr_service_fee": sum(float(l.ssr_service_fee) for l in lines),
        "gst": sum(float(l.computed_gst) for l in lines),
    }
    # compute_total() already nets Basic+YQ+YR+K3+Tax&Others+Seat+Meal+Baggage
    # +Other SSR + TDS Amount + Markup+Addl Markup+SSR Markup + Service Fee+
    # Addl Service Fee+SSR Service Fee + GST Amount - Cust Discount.
    customer_total = sum(float(l.compute_total()) for l in lines)

    supplier_groups = {}
    for l in lines:
        group = supplier_groups.setdefault(l.supplier_id, {"ledger": l.supplier, "amount": 0.0})
        group["amount"] += (
            float(l.supplier_cost) - float(l.computed_supp_commission) + float(l.computed_supp_tds)
            + float(l.supp_markup) + float(l.supp_addl_markup)
            + float(l.supp_service_fee) + float(l.supp_addl_service_fee)
            + float(l.computed_supp_gst)
        )

    def dr_cr_amounts(dr_cr, amount):
        amount = round(amount, 2)
        return (amount, 0) if dr_cr == "Debit" else (0, amount)

    def customer_rows(dr_cr, amount):
        debit, credit = dr_cr_amounts(dr_cr, amount)
        return [{"role": "customer", "ledger_id": ticket.customer_id,
                 "ledger_name": ticket.customer.name,
                 "debit": debit, "credit": credit}]

    def supplier_rows(dr_cr):
        rows = []
        for g in supplier_groups.values():
            debit, credit = dr_cr_amounts(dr_cr, g["amount"])
            ledger = g["ledger"]
            name = ledger.name if ledger else "— (no supplier selected)"
            rows.append({
                "role": "supplier",
                "ledger_id": ledger.id if ledger else None,
                "ledger_name": name,
                "debit": debit, "credit": credit,
            })
        return rows

    # Cache Master Mapping lookups — several JV_LINE_MAP entries share the
    # same (masters_category, field_name) (e.g. the two "Markup A/c" Credit
    # lines), no need to hit the DB twice for the same one. Callers that
    # process many tickets in one request (_ledger_balance_deltas) pass
    # their own shared dict in, so this only gets queried once total per
    # (company, category, field) instead of once per ticket - was 253
    # near-identical MasterMapping queries on a single Chart of Accounts
    # page load before this (one full mapping_cache per ticket, discarded
    # every time), the single dominant cause of that page's ~5s load time.
    if mapping_cache is None:
        mapping_cache = {}
    def mapped_ledger(masters_category, field_name):
        key = (ticket.company_id, masters_category, field_name)
        if key not in mapping_cache:
            m = MasterMapping.objects.filter(
                company_id=ticket.company_id, product_type="Airline",
                masters_category=masters_category, field_name=field_name,
            ).select_related("ledger").first()
            mapping_cache[key] = (
                (m.ledger_id, m.ledger.name) if m
                else (None, f"{field_name} (not mapped in Master Mapping)")
            )
        return mapping_cache[key]

    def mapped_row(dr_cr, masters_category, field_name, amount):
        debit, credit = dr_cr_amounts(dr_cr, amount)
        ledger_id, ledger_name = mapped_ledger(masters_category, field_name)
        return {"role": field_name, "ledger_id": ledger_id, "ledger_name": ledger_name, "debit": debit, "credit": credit}

    # Output GST (Credit side): same State (Company Master's State vs the
    # customer Ledger's own State from Ledger Master) = intra-state sale,
    # split Credit half/half into Output CGST A/c + Output SGST A/c;
    # different State = inter-state, one combined Output IGST A/c line.
    # JV_LINE_MAP has TWO Credit "Output IGST A/c" entries (customer-side
    # "gst" and supplier-side "supp_gst" - previously kept as separate
    # rows per an earlier instruction). Per the newer instruction, those
    # no longer show as two/duplicate "Output IGST A/c" rows - both feed
    # ONE combined Output GST amount here instead, which then follows the
    # same-state/different-state rule above as a single set of lines.
    # The separate DEBIT "Input IGST A/c" line (also fed by supp_gst) is
    # a different line entirely (Input, not Output) and is untouched.
    if company_state is None:
        company_state = (CompanyMaster.objects.filter(id=ticket.company_id).values_list("state", flat=True).first() or "").strip().lower()
    customer_state = (ticket.customer.state_name or "").strip().lower()
    same_state = bool(company_state) and bool(customer_state) and company_state == customer_state
    OUTPUT_GST_KEYS = {"gst", "supp_gst"}

    accounts = customer_rows("Debit", customer_total) + supplier_rows("Credit")
    output_gst_emitted = False
    for dr_cr, masters_category, field_name, amount_key in JV_LINE_MAP:
        if dr_cr == "Credit" and masters_category == "GST and TDS" and field_name == "Output IGST A/c" and amount_key in OUTPUT_GST_KEYS:
            if not output_gst_emitted:
                output_gst_emitted = True
                combined_gst = round(role_amounts["gst"] + role_amounts["supp_gst"], 2)
                if same_state:
                    half = round(combined_gst / 2, 2)
                    accounts.append(mapped_row("Credit", "GST and TDS", "Output CGST A/c", half))
                    accounts.append(mapped_row("Credit", "GST and TDS", "Output SGST A/c", half))
                else:
                    accounts.append(mapped_row("Credit", "GST and TDS", "Output IGST A/c", combined_gst))
            continue
        accounts.append(mapped_row(dr_cr, masters_category, field_name, role_amounts[amount_key]))

    narration = " / ".join([p for p in [ticket.booking_reference, ticket.airline_pnr, lines[0].ticket_no] if p])
    total_debit = round(sum(a["debit"] for a in accounts), 2)
    total_credit = round(sum(a["credit"] for a in accounts), 2)
    return accounts, narration, total_debit, total_credit


def _jv_prep(company_id):
    """
    Fetches, ONCE per request, everything _compute_jv_lines needs to run
    without any live ORM query of its own: every Airline Master Mapping
    for this company (seeds both the ledger-per-(masters_category,
    field_name) cache and the per-field GST% cache computed_gst reads)
    plus Company Master's own State. Stored Procedure architecture: the
    JV LINE arithmetic itself stays in Python (ported from TicketLine's
    own @property formulas, unchanged), only the data it reads comes from
    sp_client now instead of MasterMapping.objects.filter()/CompanyMaster.
    objects.filter() queries at property-access time.
    """
    mappings = sp_client.master_mapping_list(company_id, product_type="Airline")
    mapping_cache = {
        (company_id, m["masters_category"], m["field_name"]): (m["ledger_id"], m["ledger_name"])
        for m in mappings
    }
    for m in mappings:
        cache_key = (company_id, m["field_name"])
        if cache_key not in _field_gst_pct_cache:
            _field_gst_pct_cache[cache_key] = float(m["ledger_gst_percentage"] or 0)
    # Live-only speed-up: company_id arrives from the query string as "1",
    # but mapped_ledger()/computed_gst look keys up by ticket.company_id (1),
    # so the entries above never hit and every field fell back to its own
    # MasterMapping query (~25 per report - minutes on TiDB). Also seed the
    # int-keyed entries, with exactly the values those fallback queries
    # return: the mapped Ledger's current name, and its GST% (0 if unmapped).
    if str(company_id).isdigit():
        company_key = int(company_id)
        mapped = [m for m in mappings if m["ledger_id"] is not None]
        names = dict(Ledger.objects.filter(id__in={m["ledger_id"] for m in mapped}).values_list("id", "name"))
        for m in mapped:
            if m["ledger_id"] in names:
                mapping_cache[(company_key, m["masters_category"], m["field_name"])] = (m["ledger_id"], names[m["ledger_id"]])
        per_field = {}
        for m in mappings:
            per_field.setdefault(m["field_name"], []).append(m)
        for field_name, rows in per_field.items():
            if len(rows) == 1 and (company_key, field_name) not in _field_gst_pct_cache:
                _field_gst_pct_cache[(company_key, field_name)] = float(rows[0]["ledger_gst_percentage"] or 0)
    company = sp_client.company_master_get(company_id)
    company_state = ((company or {}).get("state") or "").strip().lower()
    return mapping_cache, company_state


def _build_ticket_lines(company_id, customer_row, lines_in):
    """
    Builds unsaved TicketLine instances (pure in-memory value objects -
    never queried/saved here) from the request's line dicts, resolving
    each line's own supplier_name via sp_client (not the ORM) and
    computing total_billed the same way ticket_create/ticket_update
    always have. Raises ValueError(message) for a bad per-line
    supplier_name, matching the original 400 error text.
    """
    line_objs, lines_json = [], []
    for line_in in lines_in:
        line_kwargs = {f: line_in[f] for f in TICKET_LINE_FIELDS if f in line_in}
        # Every numeric field always gets a real value (defaulting to 0 when
        # absent from the request) - unlike the old TicketLine(**line_kwargs)
        # ORM path, which could silently lean on the model field's own
        # default=0 for an omitted key, this dict becomes a literal JSON
        # payload for dbo.sp_Ticket's OPENJSON insert, which has no such
        # per-field default to fall back on.
        for f in TICKET_LINE_NUMERIC_FIELDS:
            line_kwargs[f] = _safe_decimal(line_kwargs.get(f))
        line_kwargs.setdefault("pax_type", "Adult")
        line_kwargs.setdefault("status", "ISSUED")

        supplier_name = line_in.get("supplier_name")
        line_supplier = None
        if supplier_name:
            supp_row = sp_client.ledger_get_by_name(company_id, supplier_name, "CREDITOR")
            if not supp_row:
                raise ValueError(
                    f"\"{supplier_name}\" (Ticket No. {line_in.get('ticket_no', '?')}) is not a real supplier ledger (Sundry Creditors)."
                )
            line_supplier = Ledger(id=supp_row["id"], name=supp_row["name"])

        ticket_proxy = Ticket(company_id=company_id, customer=Ledger(id=customer_row["id"], name=customer_row["name"]))
        line = TicketLine(ticket=ticket_proxy, supplier=line_supplier, **line_kwargs)
        line.total_billed = _safe_decimal(line.compute_total())
        line_objs.append(line)

        line_json = dict(line_kwargs)
        line_json["total_billed"] = line.total_billed
        line_json["supplier_name"] = supplier_name
        lines_json.append(line_json)
    return line_objs, lines_json


@csrf_exempt
@transaction.atomic
def ticket_create(request):
    """
    POST /api/tickets/create/
    Body: { company_id, ...header fields, customer_name, supplier_name,
            lines: [ {...line fields}, ... ] }

    Real server-side checks the client-side form already does, done
    again here since a browser's JS validation can always be bypassed:
    - customer_name / supplier_name must match a real Ledger
      (ledger_category DEBTOR / CREDITOR) for this company
    - invoice_number and booking_reference must be unique per company
    - ticket_no must be unique across ALL tickets, and not repeated
      within the same submitted lines array
    - total_billed is recomputed server-side per line — the browser's
      number is never trusted directly

    Stored Procedure architecture: every read/write this needs (ledger
    resolution, uniqueness checks, the Ticket+TicketLines batch insert,
    the JournalVoucher insert) goes through dbo.sp_Ticket's SAVE action
    via sp_client.ticket_save() - no Model.objects.create()/.filter()
    loop. The JV line arithmetic itself (_compute_jv_lines, unchanged)
    still runs in Python against unsaved TicketLine instances built by
    _build_ticket_lines(), then only the computed totals/narration are
    sent to the stored procedure to persist.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    company_id = body.get("company_id")
    lines_in = body.get("lines") or []
    if not company_id or not body.get("customer_name") or not body.get("invoice_number") or not lines_in:
        return JsonResponse({"error": "company_id, customer_name, invoice_number and at least one line are required."}, status=400)

    missing_required = [
        label for key, label in
        [("invoice_type", "Invoice Type"), ("booking_type", "Booking Type"), ("booking_status", "Booking Status")]
        if not body.get(key)
    ]
    if missing_required:
        verb = "is" if len(missing_required) == 1 else "are"
        return JsonResponse({"error": f"{', '.join(missing_required)} {verb} required."}, status=400)

    customer_row = sp_client.ledger_get_by_name(company_id, body["customer_name"], "DEBTOR")
    if not customer_row:
        return JsonResponse({"error": f"\"{body['customer_name']}\" is not a real customer ledger (Sundry Debtors)."}, status=400)

    if body.get("supplier_name") and not sp_client.ledger_get_by_name(company_id, body["supplier_name"], "CREDITOR"):
        return JsonResponse({"error": f"\"{body['supplier_name']}\" is not a real supplier ledger (Sundry Creditors)."}, status=400)

    header_kwargs = {f: body[f] for f in TICKET_HEADER_FIELDS if f in body}
    header_kwargs["invoice_date"] = _parse_date(header_kwargs.get("invoice_date"))
    header_kwargs["booking_ref_date"] = _parse_date(header_kwargs.get("booking_ref_date"))
    if "roe" in header_kwargs:
        header_kwargs["roe"] = _safe_decimal(header_kwargs["roe"], default=1)
    header_kwargs["supplier_name"] = body.get("supplier_name")

    try:
        line_objs, lines_json = _build_ticket_lines(company_id, customer_row, lines_in)
    except ValueError as err:
        return JsonResponse({"error": str(err)}, status=400)

    # Auto-post the JV immediately — no separate "Post Voucher" step. Every
    # account head/ledger here is hardcoded (jv_hardcode.py) — customer and
    # supplier are the only two backed by a real Ledger row, and both are
    # already validated to exist above.
    mapping_cache, company_state = _jv_prep(company_id)
    ticket_proxy = Ticket(
        company_id=company_id, customer=Ledger(id=customer_row["id"], name=customer_row["name"], state_name=customer_row.get("state_name")),
        booking_reference=header_kwargs.get("booking_reference"), airline_pnr=header_kwargs.get("airline_pnr"),
    )
    accounts, narration, total_debit, total_credit = _compute_jv_lines(ticket_proxy, line_objs, mapping_cache, company_state)
    total_debit, total_credit = round(total_debit, 2), round(total_credit, 2)
    if total_debit == 0 and total_credit == 0:
        return JsonResponse({"error": "This ticket's GL entry total is zero — check the fare fields."}, status=400)

    try:
        result = sp_client.ticket_save(
            company_id, body["customer_name"], header_kwargs, lines_json, narration, total_debit, total_credit,
        )
    except sp_client.StoredProcedureError as err:
        msg = str(err)
        status = 409 if "already exists" in msg or "Duplicate" in msg else 400
        return JsonResponse({"error": msg}, status=status)

    balanced = abs(total_debit - total_credit) < 0.01
    status_note = f"Balanced ✓ (Debit {total_debit:.2f} = Credit {total_credit:.2f})" \
        if balanced else f"⚠ Debit {total_debit:.2f} ≠ Credit {total_credit:.2f} — check the JV tab"
    return JsonResponse({
        "id": result["id"], "line_ids": result["line_ids"], "voucher_id": result["voucher_id"], "voucher_no": result["voucher_no"],
        "message": f"Ticket saved and GL entry {result['voucher_no']} posted — {status_note}.",
    }, status=201)


@csrf_exempt
@transaction.atomic
def ticket_update(request, ticket_id):
    """
    POST /api/tickets/<id>/update/
    Body: same shape as tickets/create/. Used by the New Ticket form's
    "Edit" button on an already-saved ticket — same validation as create,
    except uniqueness checks (Invoice Number/Booking Reference/Ticket No)
    exclude this ticket's own existing rows. Lines are matched to what's
    already saved by ticket_no and updated in place (not deleted and
    recreated wholesale) - a line that's already been rescheduled is
    PROTECTed from deletion (RescheduleAirlineTicketLine.original_ticket_
    line), so a blind delete-all would crash every time this ticket is
    edited again after that. The JV is still always recomputed fresh
    rather than patched. Updates the existing Voucher in place instead of
    posting a second one for the same ticket.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    company_id = body.get("company_id")
    lines_in = body.get("lines") or []
    if not company_id or not body.get("customer_name") or not body.get("invoice_number") or not lines_in:
        return JsonResponse({"error": "company_id, customer_name, invoice_number and at least one line are required."}, status=400)

    existing_header, _existing_lines = sp_client.ticket_get(ticket_id, company_id)
    if not existing_header:
        return JsonResponse({"error": "Ticket not found."}, status=404)

    missing_required = [
        label for key, label in
        [("invoice_type", "Invoice Type"), ("booking_type", "Booking Type"), ("booking_status", "Booking Status")]
        if not body.get(key)
    ]
    if missing_required:
        verb = "is" if len(missing_required) == 1 else "are"
        return JsonResponse({"error": f"{', '.join(missing_required)} {verb} required."}, status=400)

    customer_row = sp_client.ledger_get_by_name(company_id, body["customer_name"], "DEBTOR")
    if not customer_row:
        return JsonResponse({"error": f"\"{body['customer_name']}\" is not a real customer ledger (Sundry Debtors)."}, status=400)

    if body.get("supplier_name") and not sp_client.ledger_get_by_name(company_id, body["supplier_name"], "CREDITOR"):
        return JsonResponse({"error": f"\"{body['supplier_name']}\" is not a real supplier ledger (Sundry Creditors)."}, status=400)

    header_kwargs = {f: body[f] for f in TICKET_HEADER_FIELDS if f in body}
    header_kwargs["invoice_date"] = _parse_date(header_kwargs.get("invoice_date"))
    header_kwargs["booking_ref_date"] = _parse_date(header_kwargs.get("booking_ref_date"))
    if "roe" in header_kwargs:
        header_kwargs["roe"] = _safe_decimal(header_kwargs["roe"], default=1)
    header_kwargs["supplier_name"] = body.get("supplier_name")

    try:
        line_objs, lines_json = _build_ticket_lines(company_id, customer_row, lines_in)
    except ValueError as err:
        return JsonResponse({"error": str(err)}, status=400)

    # Narration uses the EFFECTIVE (updated-if-provided, else still-current)
    # booking_reference/airline_pnr - same as the old setattr-onto-the-
    # existing-instance behaviour.
    mapping_cache, company_state = _jv_prep(company_id)
    ticket_proxy = Ticket(
        company_id=company_id, customer=Ledger(id=customer_row["id"], name=customer_row["name"], state_name=customer_row.get("state_name")),
        booking_reference=header_kwargs.get("booking_reference", existing_header["booking_reference"]),
        airline_pnr=header_kwargs.get("airline_pnr", existing_header["airline_pnr"]),
    )
    accounts, narration, total_debit, total_credit = _compute_jv_lines(ticket_proxy, line_objs, mapping_cache, company_state)
    total_debit, total_credit = round(total_debit, 2), round(total_credit, 2)
    if total_debit == 0 and total_credit == 0:
        return JsonResponse({"error": "This ticket's GL entry total is zero — check the fare fields."}, status=400)

    try:
        result = sp_client.ticket_save(
            company_id, body["customer_name"], header_kwargs, lines_json, narration, total_debit, total_credit,
            ticket_id=ticket_id,
        )
    except sp_client.StoredProcedureError as err:
        msg = str(err)
        status = 404 if msg == "Ticket not found." else (409 if "already exists" in msg or "Duplicate" in msg or "cannot be removed" in msg else 400)
        return JsonResponse({"error": msg}, status=status)

    balanced = abs(total_debit - total_credit) < 0.01
    status_note = f"Balanced ✓ (Debit {total_debit:.2f} = Credit {total_credit:.2f})" \
        if balanced else f"⚠ Debit {total_debit:.2f} ≠ Credit {total_credit:.2f} — check the JV tab"
    return JsonResponse({
        "id": result["id"], "line_ids": result["line_ids"], "voucher_id": result["voucher_id"], "voucher_no": result["voucher_no"],
        "message": f"Ticket updated and GL entry {result['voucher_no']} re-posted — {status_note}.",
    })


RESCHED_LINE_FIELDS = TICKET_LINE_FIELDS + ["agent_penalty", "reschedule_penalty", "supplier_penalty"]
RESCHED_LINE_NUMERIC_FIELDS = TICKET_LINE_NUMERIC_FIELDS | {"agent_penalty", "reschedule_penalty", "supplier_penalty"}


def _resolve_reschedule_chain(original_ticket_id, lines_in, existing_combo_keys=None):
    """
    Resolves every line's chain info (the real original TicketLine, plus
    the previous reschedule line it's based on when chaining) in ONE
    dbo.sp_RescheduleTicket RESOLVE_LINES call, and runs the same
    validation reschedule_ticket_create/update always have: every line
    must reference a real original_ticket_line_id belonging to this
    ticket, and none of them (or their chain source, if chained) may
    already be rescheduled - UNLESS that exact (original_ticket_line_id,
    based_on_reschedule_line_id) combo is already attached to THIS SAME
    reschedule ticket (existing_combo_keys, from reschedule_ticket_update -
    an ineligible flag there is simply this edit's own prior save, not a
    conflict; create always passes an empty set since nothing is "this
    ticket's own" yet). Returns {original_ticket_line_id: chain_row} on
    success, or raises ValueError(message) with the exact original error
    text (caller maps it to the right HTTP status).
    """
    existing_combo_keys = existing_combo_keys or set()
    line_original_ids = [l.get("original_ticket_line_id") for l in lines_in]
    if not all(line_original_ids):
        raise ValueError("Each line must reference the original ticket line it was rescheduled from.")

    pairs = [{"original_ticket_line_id": l.get("original_ticket_line_id"), "reschedule_line_id": l.get("reschedule_line_id")} for l in lines_in]
    rows = sp_client.reschedule_resolve_lines(original_ticket_id, pairs)
    chain_by_original = {r["original_ticket_line_id"]: r for r in rows}

    missing_original = [oid for oid in line_original_ids if chain_by_original.get(oid, {}).get("original_id") is None]
    if missing_original:
        raise ValueError("One or more lines reference an original ticket line that doesn't belong to this ticket.")

    already_rescheduled = []
    for oid in set(line_original_ids):
        row = chain_by_original[oid]
        if (oid, row["based_on_id"]) in existing_combo_keys:
            continue
        if row["based_on_id"] is not None:
            if row["based_on_rescheduled"]:
                already_rescheduled.append(row["based_on_ticket_no"])
        elif row["original_rescheduled"]:
            already_rescheduled.append(row["original_ticket_no"])
    if already_rescheduled:
        names = ", ".join(sorted(set(already_rescheduled)))
        raise ValueError(f"Ticket No. {names} has already been rescheduled and cannot be rescheduled again.")

    return chain_by_original


def _build_reschedule_lines(company_id, lines_in, chain_by_original):
    """
    Builds unsaved RescheduleAirlineTicketLine instances (pure in-memory
    value objects, never queried/saved here) from the request's line
    dicts, same pattern as _build_ticket_lines - plus each line's own
    chain fields (original_ticket_line_id, based_on_reschedule_line_id,
    parent_pnr) resolved from chain_by_original (see
    _resolve_reschedule_chain). Raises ValueError(message) for a bad
    per-line supplier_name.
    """
    line_objs, lines_json = [], []
    for line_in in lines_in:
        line_kwargs = {f: line_in[f] for f in RESCHED_LINE_FIELDS if f in line_in}
        for f in RESCHED_LINE_NUMERIC_FIELDS:
            line_kwargs[f] = _safe_decimal(line_kwargs.get(f))
        line_kwargs.setdefault("pax_type", "Adult")
        line_kwargs.setdefault("status", "ISSUED")

        supplier_name = line_in.get("supplier_name")
        line_supplier = None
        if supplier_name:
            supp_row = sp_client.ledger_get_by_name(company_id, supplier_name, "CREDITOR")
            if not supp_row:
                raise ValueError(
                    f"\"{supplier_name}\" (Ticket No. {line_in.get('ticket_no', '?')}) is not a real supplier ledger (Sundry Creditors)."
                )
            line_supplier = Ledger(id=supp_row["id"], name=supp_row["name"])

        row = chain_by_original[line_in["original_ticket_line_id"]]
        parent_pnr = row["based_on_booking_reference"] if row["based_on_id"] is not None else row["original_ticket_booking_reference"]

        resched_ticket_proxy = RescheduleAirlineTicket(company_id=company_id)
        line = RescheduleAirlineTicketLine(reschedule_ticket=resched_ticket_proxy, supplier=line_supplier, **line_kwargs)
        line.total_billed = _safe_decimal(line.compute_total())
        line_objs.append(line)

        line_json = dict(line_kwargs)
        line_json["total_billed"] = line.total_billed
        line_json["supplier_name"] = supplier_name
        line_json["original_ticket_line_id"] = row["original_id"]
        line_json["based_on_reschedule_line_id"] = row["based_on_id"]
        line_json["parent_pnr"] = parent_pnr
        lines_json.append(line_json)
    return line_objs, lines_json


@csrf_exempt
@transaction.atomic
def reschedule_ticket_create(request):
    """
    POST /api/reschedule-tickets/create/
    Body: { company_id, original_ticket_id, ...header fields (same shape
    as tickets/create/'s TICKET_HEADER_FIELDS), customer_name,
    supplier_name, lines: [ {...TICKET_LINE_FIELDS, agent_penalty,
    reschedule_penalty, supplier_penalty, original_ticket_line_id}, ... ] }

    Persists the brand-new "Reschedule PNR Details" ticket + its lines
    into RescheduleAirlineTicket/RescheduleAirlineTicketLine — the
    original ticket/line ("Parent PNR Details") is never touched, only
    linked via original_ticket / original_ticket_line. Auto-posts this
    reschedule's own JournalVoucher immediately (category
    "AIRLINE_RESCHEDULE", ALR-1/ALR-2/... numbering, source_reschedule_
    ticket set instead of source_ticket) using _compute_reschedule_jv_
    lines — entirely additive, the original ticket's own JournalVoucher
    row is never touched or adjusted.

    Stored Procedure architecture: same approach as ticket_create - the JV
    arithmetic (_compute_reschedule_jv_lines, unchanged) runs in Python
    against unsaved RescheduleAirlineTicketLine instances, chain
    resolution/eligibility reads go through dbo.sp_RescheduleTicket's
    RESOLVE_LINES action, and the actual Ticket+Lines+JournalVoucher write
    (plus eligibility flips) goes through its SAVE action - no
    Model.objects.create()/.filter() loop.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    company_id = body.get("company_id")
    original_ticket_id = body.get("original_ticket_id")
    lines_in = body.get("lines") or []
    if not company_id or not original_ticket_id or not body.get("customer_name") or not body.get("invoice_number") or not body.get("booking_reference") or not lines_in:
        return JsonResponse({"error": "company_id, original_ticket_id, customer_name, invoice_number, booking_reference and at least one line are required."}, status=400)

    original_header, _lines = sp_client.ticket_get(original_ticket_id, company_id)
    if not original_header:
        return JsonResponse({"error": "Original ticket not found."}, status=404)

    missing_required = [
        label for key, label in
        [("invoice_type", "Invoice Type"), ("booking_type", "Booking Type"), ("booking_status", "Booking Status")]
        if not body.get(key)
    ]
    if missing_required:
        verb = "is" if len(missing_required) == 1 else "are"
        return JsonResponse({"error": f"{', '.join(missing_required)} {verb} required."}, status=400)

    customer_row = sp_client.ledger_get_by_name(company_id, body["customer_name"], "DEBTOR")
    if not customer_row:
        return JsonResponse({"error": f"\"{body['customer_name']}\" is not a real customer ledger (Sundry Debtors)."}, status=400)

    if body.get("supplier_name") and not sp_client.ledger_get_by_name(company_id, body["supplier_name"], "CREDITOR"):
        return JsonResponse({"error": f"\"{body['supplier_name']}\" is not a real supplier ledger (Sundry Creditors)."}, status=400)

    try:
        chain_by_original = _resolve_reschedule_chain(original_ticket_id, lines_in)
    except ValueError as err:
        msg = str(err)
        status = 409 if "already been rescheduled" in msg else (404 if "not found" in msg else 400)
        return JsonResponse({"error": msg}, status=status)

    header_kwargs = {f: body[f] for f in TICKET_HEADER_FIELDS if f in body}
    header_kwargs["invoice_date"] = _parse_date(header_kwargs.get("invoice_date"))
    header_kwargs["booking_ref_date"] = _parse_date(header_kwargs.get("booking_ref_date"))
    if "roe" in header_kwargs:
        header_kwargs["roe"] = _safe_decimal(header_kwargs["roe"], default=1)
    header_kwargs["supplier_name"] = body.get("supplier_name")

    try:
        line_objs, lines_json = _build_reschedule_lines(company_id, lines_in, chain_by_original)
    except ValueError as err:
        return JsonResponse({"error": str(err)}, status=400)

    mapping_cache, company_state = _jv_prep(company_id)
    resched_ticket_proxy = RescheduleAirlineTicket(
        company_id=company_id, customer=Ledger(id=customer_row["id"], name=customer_row["name"], state_name=customer_row.get("state_name")),
        booking_reference=header_kwargs.get("booking_reference"), airline_pnr=header_kwargs.get("airline_pnr"),
    )
    accounts, narration, total_debit, total_credit = _compute_reschedule_jv_lines(resched_ticket_proxy, line_objs, mapping_cache, company_state)
    total_debit, total_credit = round(total_debit, 2), round(total_credit, 2)
    if total_debit == 0 and total_credit == 0:
        return JsonResponse({"error": "This reschedule ticket's GL entry total is zero — check the fare fields."}, status=400)

    try:
        result = sp_client.reschedule_ticket_save(
            company_id, body["customer_name"], header_kwargs, lines_json, narration, total_debit, total_credit,
            original_ticket_id=original_ticket_id,
        )
    except sp_client.StoredProcedureError as err:
        msg = str(err)
        status = 409 if "already exists" in msg or "Duplicate" in msg or "already been rescheduled" in msg else 400
        return JsonResponse({"error": msg}, status=status)

    balanced = abs(total_debit - total_credit) < 0.01
    status_note = f"Balanced ✓ (Debit {total_debit:.2f} = Credit {total_credit:.2f})" \
        if balanced else f"⚠ Debit {total_debit:.2f} ≠ Credit {total_credit:.2f} — check the JV tab"
    return JsonResponse({
        "id": result["id"], "line_ids": result["line_ids"], "voucher_id": result["voucher_id"], "voucher_no": result["voucher_no"],
        "message": f"Reschedule ticket saved and GL entry {result['voucher_no']} posted — {status_note}.",
    }, status=201)


@csrf_exempt
@transaction.atomic
def reschedule_ticket_update(request, reschedule_ticket_id):
    """
    POST /api/reschedule-tickets/<id>/update/
    Body: same shape as reschedule-tickets/create/. Used when the
    Reschedule lookup screen's "Saved" radio finds an already-saved
    RescheduleAirlineTicket and the user edits/re-saves it from
    ticket-entry.html. original_ticket is NEVER changed by this endpoint
    (whatever the body sends for original_ticket_id is ignored) - which
    original ticket a reschedule was raised against is fixed at creation.
    Replaces this reschedule ticket's lines wholesale (delete + recreate),
    same convention as ticket_update.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    company_id = body.get("company_id")
    lines_in = body.get("lines") or []
    if not company_id or not body.get("customer_name") or not body.get("invoice_number") or not body.get("booking_reference") or not lines_in:
        return JsonResponse({"error": "company_id, customer_name, invoice_number, booking_reference and at least one line are required."}, status=400)

    existing_header = sp_client.reschedule_ticket_get_header(reschedule_ticket_id, company_id)
    if not existing_header:
        return JsonResponse({"error": "Reschedule ticket not found."}, status=404)
    original_ticket_id = existing_header["original_ticket_id"]

    missing_required = [
        label for key, label in
        [("invoice_type", "Invoice Type"), ("booking_type", "Booking Type"), ("booking_status", "Booking Status")]
        if not body.get(key)
    ]
    if missing_required:
        verb = "is" if len(missing_required) == 1 else "are"
        return JsonResponse({"error": f"{', '.join(missing_required)} {verb} required."}, status=400)

    customer_row = sp_client.ledger_get_by_name(company_id, body["customer_name"], "DEBTOR")
    if not customer_row:
        return JsonResponse({"error": f"\"{body['customer_name']}\" is not a real customer ledger (Sundry Debtors)."}, status=400)

    if body.get("supplier_name") and not sp_client.ledger_get_by_name(company_id, body["supplier_name"], "CREDITOR"):
        return JsonResponse({"error": f"\"{body['supplier_name']}\" is not a real supplier ledger (Sundry Creditors)."}, status=400)

    # Lines already attached to THIS SAME reschedule ticket, in the same
    # (original, chain-source) configuration, are expected to already show
    # ineligible - only a genuinely new attachment is a real conflict.
    existing_combo_keys = {
        (row["original_ticket_line_id"], row["based_on_reschedule_line_id"])
        for row in sp_client.reschedule_ticket_line_keys(reschedule_ticket_id)
    }

    try:
        chain_by_original = _resolve_reschedule_chain(original_ticket_id, lines_in, existing_combo_keys)
    except ValueError as err:
        msg = str(err)
        status = 409 if "already been rescheduled" in msg else 400
        return JsonResponse({"error": msg}, status=status)

    header_kwargs = {f: body[f] for f in TICKET_HEADER_FIELDS if f in body}
    header_kwargs["invoice_date"] = _parse_date(header_kwargs.get("invoice_date"))
    header_kwargs["booking_ref_date"] = _parse_date(header_kwargs.get("booking_ref_date"))
    if "roe" in header_kwargs:
        header_kwargs["roe"] = _safe_decimal(header_kwargs["roe"], default=1)
    header_kwargs["supplier_name"] = body.get("supplier_name")

    try:
        line_objs, lines_json = _build_reschedule_lines(company_id, lines_in, chain_by_original)
    except ValueError as err:
        return JsonResponse({"error": str(err)}, status=400)

    mapping_cache, company_state = _jv_prep(company_id)
    resched_ticket_proxy = RescheduleAirlineTicket(
        company_id=company_id, customer=Ledger(id=customer_row["id"], name=customer_row["name"], state_name=customer_row.get("state_name")),
        booking_reference=header_kwargs.get("booking_reference", existing_header["booking_reference"]),
        airline_pnr=header_kwargs.get("airline_pnr", existing_header["airline_pnr"]),
    )
    accounts, narration, total_debit, total_credit = _compute_reschedule_jv_lines(resched_ticket_proxy, line_objs, mapping_cache, company_state)
    total_debit, total_credit = round(total_debit, 2), round(total_credit, 2)
    if total_debit == 0 and total_credit == 0:
        return JsonResponse({"error": "This reschedule ticket's GL entry total is zero — check the fare fields."}, status=400)

    try:
        result = sp_client.reschedule_ticket_save(
            company_id, body["customer_name"], header_kwargs, lines_json, narration, total_debit, total_credit,
            reschedule_ticket_id=reschedule_ticket_id,
        )
    except sp_client.StoredProcedureError as err:
        msg = str(err)
        status = 404 if msg == "Reschedule ticket not found." else (
            409 if "already exists" in msg or "Duplicate" in msg or "already been rescheduled" in msg else 400)
        return JsonResponse({"error": msg}, status=status)

    balanced = abs(total_debit - total_credit) < 0.01
    status_note = f"Balanced ✓ (Debit {total_debit:.2f} = Credit {total_credit:.2f})" \
        if balanced else f"⚠ Debit {total_debit:.2f} ≠ Credit {total_credit:.2f} — check the JV tab"
    return JsonResponse({
        "id": result["id"], "line_ids": result["line_ids"], "voucher_id": result["voucher_id"], "voucher_no": result["voucher_no"],
        "message": f"Reschedule ticket updated and GL entry {result['voucher_no']} re-posted — {status_note}.",
    })


def reschedule_ticket_lookup(request):
    """
    GET /api/reschedule-tickets/lookup/?company_id=1&s_pnr=..&airline_pnr=..&ticket_no=..
    Same identifier-priority convention as tickets/lookup-for-reschedule/
    (Ticket No first, then S PNR, then Airline PNR) but searches the
    RescheduleAirlineTicket/RescheduleAirlineTicketLine tables instead -
    used by the Reschedule lookup screen's "Saved" radio to find an
    already-saved reschedule (S PNR here means this reschedule's OWN
    Rescheduled Ref, not the original ticket's Booking Reference).
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    s_pnr = (request.GET.get("s_pnr") or "").strip()
    airline_pnr = (request.GET.get("airline_pnr") or "").strip()
    ticket_no = (request.GET.get("ticket_no") or "").strip()
    if not (s_pnr or airline_pnr or ticket_no):
        return JsonResponse({"error": "Enter S PNR, Airline PNR or Ticket No to search."}, status=400)

    resched_ticket = None
    if ticket_no:
        line = RescheduleAirlineTicketLine.objects.filter(
            reschedule_ticket__company_id=company_id, ticket_no=ticket_no
        ).select_related("reschedule_ticket").first()
        resched_ticket = line.reschedule_ticket if line else None
    if not resched_ticket and s_pnr:
        resched_ticket = RescheduleAirlineTicket.objects.filter(company_id=company_id, booking_reference=s_pnr).first()
    if not resched_ticket and airline_pnr:
        resched_ticket = RescheduleAirlineTicket.objects.filter(company_id=company_id, airline_pnr=airline_pnr).first()

    if not resched_ticket:
        return JsonResponse({"error": "No saved reschedule ticket found matching that S PNR / Airline PNR / Ticket No."}, status=404)

    return JsonResponse({"reschedule_ticket_id": resched_ticket.id})


PARENT_CHAIN_SUM_FIELDS = [
    "basic_fare", "yq", "yr", "k3_tax", "tax_others", "seat", "meal", "baggage", "other_ssr",
    "markup", "addl_markup", "ssr_markup", "service_fee", "addl_service_fee", "ssr_service_fee",
    "supp_markup", "supp_addl_markup", "supp_service_fee", "supp_addl_service_fee", "pg_charges",
    # Only exist on RescheduleAirlineTicketLine, never on the true
    # original TicketLine (a fresh booking has nothing to charge a
    # penalty against yet) - getattr(..., 0) below naturally returns 0
    # for the original, so these are correctly 0 on a FIRST reschedule
    # (chain is empty, nothing to sum) and only start accumulating from
    # the second reschedule onward, exactly as specified.
    "agent_penalty", "reschedule_penalty", "supplier_penalty",
]
# disc_value/supp_comm_value are handled separately below (not summed as
# raw numbers here) - each one is a RATE under "Percentage" but a real
# currency AMOUNT under "Flat", so blindly summing the raw field across a
# chain that mixes both types would add percentages to amounts and
# produce nonsense (e.g. a 1121% "discount"). Everything else on a line
# (passenger info, sector/flight details, FOP, discount/commission TYPE
# and RATE, office/supplier) is a point-in-time choice, not a running
# total - the LATEST item in the chain's own value is used as-is, never
# summed.
PARENT_CHAIN_PASSTHROUGH_FIELDS = [
    "airline_code", "airline_name", "airline_category", "flight_no", "ticket_no", "passenger_name", "pax_type",
    "sector", "travel_date", "cabin", "travel_class", "fare_type", "status",
    "disc_on", "pg_charges_percentage", "gst_pct",
    "office_id", "fop", "card_number",
    "supp_comm_on", "supp_gst_pct",
]


def _resolve_parent_chain_line(original_ticket_line, based_on_reschedule_line):
    """
    "Parent PNR Details" for a reschedule that is itself chained off a
    PREVIOUS reschedule must show the CUMULATIVE fare totals across the
    whole chain (original booking + every reschedule in between), not
    just the immediately-previous reschedule's own standalone figures -
    e.g. Ref 1 Basic Fare 998 + Ref 2's own 26 = 1024 shown when creating
    Ref 3. Walks based_on_reschedule_line backwards from the given link
    down to the true original TicketLine, summing every fare AMOUNT
    field (PARENT_CHAIN_SUM_FIELDS) across every level, while every
    other field (passenger info, discount/commission type+rate, FOP,
    etc. - PARENT_CHAIN_PASSTHROUGH_FIELDS) is taken from whichever item
    is most recent in the chain, since those are a fresh choice each
    reschedule rather than something that accumulates.

    based_on_reschedule_line=None means this is a reschedule of the
    original ticket directly (no chaining) - the original line's own
    values are returned unchanged.

    Returns a plain dict shaped like TICKET_LINE_FIELDS/RESCHED_LINE_FIELDS
    (plus total_billed=0, recomputed client-side from the summed inputs),
    never an ORM object, since this is a frozen display-only snapshot -
    not something ever saved back to the database.
    """
    chain = []
    node = based_on_reschedule_line
    while node is not None:
        chain.append(node)
        node = node.based_on_reschedule_line
    chain.reverse()  # oldest reschedule first, most recent last

    latest = chain[-1] if chain else original_ticket_line

    result = {}
    for f in PARENT_CHAIN_SUM_FIELDS:
        total = float(getattr(original_ticket_line, f, 0) or 0)
        for node in chain:
            total += float(getattr(node, f, 0) or 0)
        result[f] = total

    if chain:
        # Chained - the running Discount/Commission AMOUNT across every
        # level is the SUM of each level's own ALREADY-COMPUTED amount
        # (computed_discount/computed_supp_commission - these honor that
        # level's own Flat/Percentage type and base, so this is a real
        # cumulative currency total, e.g. Ref 1's 50 + Ref 2's 25 = 75).
        # Always shown as "Flat" here regardless of what type any
        # individual level actually used - there is no single rate that
        # reproduces this total via the frontend's own Amount = f(type,
        # value) formula, and showing it as "Percentage" would have the
        # frontend multiply this already-final amount by a rate AGAIN,
        # producing nonsense (e.g. a 1121% "discount").
        result["disc_value"] = round(
            float(original_ticket_line.computed_discount) + sum(float(n.computed_discount) for n in chain), 2
        )
        result["disc_type"] = "Flat"
        result["supp_comm_value"] = round(
            float(original_ticket_line.computed_supp_commission) + sum(float(n.computed_supp_commission) for n in chain), 2
        )
        result["supp_comm_type"] = "Flat"
        # True cumulative TDS is the SUM of each level's own computed_tds
        # (its own amount x its own rate) - e.g. Booking's own TDS 22.38 +
        # 1st Reschedule's own TDS 0.31 = 22.69. No single TDS % actually
        # produced that chain, so rather than show a meaningless "blended"
        # rate (confusing on its own), TDS % is shown as 0 and the real
        # summed amount is sent explicitly as tds_amount/supp_tds_amount -
        # the frontend overrides its live-derived display with these for
        # the frozen Parent tab only (see applyRescheduleTab).
        result["tds_per"] = 0.0
        result["tds_amount"] = round(
            float(original_ticket_line.computed_tds) + sum(float(n.computed_tds) for n in chain), 2
        )
        result["supp_tds_per"] = 0.0
        result["supp_tds_amount"] = round(
            float(original_ticket_line.computed_supp_tds) + sum(float(n.computed_supp_tds) for n in chain), 2
        )
    else:
        # No chaining - nothing to aggregate, so the original line's own
        # type/value/rate is shown exactly as entered (a legitimate
        # Percentage discount, or its real TDS %, same as before this fix).
        # tds_amount/supp_tds_amount are left unset (None) - the frontend's
        # normal live Amount x Rate derivation is already correct here.
        result["disc_value"] = float(original_ticket_line.disc_value)
        result["disc_type"] = original_ticket_line.disc_type
        result["supp_comm_value"] = float(original_ticket_line.supp_comm_value)
        result["supp_comm_type"] = original_ticket_line.supp_comm_type
        result["tds_per"] = float(original_ticket_line.tds_per)
        result["supp_tds_per"] = float(original_ticket_line.supp_tds_per)
        result["tds_amount"] = None
        result["supp_tds_amount"] = None

    passthrough_numeric = {
        "pg_charges_percentage", "gst_pct", "supp_gst_pct",
    }
    for f in PARENT_CHAIN_PASSTHROUGH_FIELDS:
        value = getattr(latest, f, None)
        result[f] = (float(value) if value is not None else None) if f in passthrough_numeric else value
    result["supplier_name"] = latest.supplier.name if getattr(latest, "supplier_id", None) else None
    result["total_billed"] = 0
    return result


def reschedule_parent_chain_line(request):
    """
    GET /api/reschedule-tickets/parent-chain-line/?company_id=1&original_ticket_line_id=5&based_on_reschedule_line_id=9
    Returns the cumulative "Parent PNR Details" line (see
    _resolve_parent_chain_line) for a given chain position. Used by
    ticket-entry.html both when creating a brand-new reschedule
    (original_ticket_line_id=the eligible line being rescheduled,
    based_on_reschedule_line_id=the immediate parent reschedule's own
    line if chaining, omitted otherwise) and when viewing/editing an
    already-saved reschedule (same two ids, read back from that
    reschedule's own stored original_ticket_line_id/reschedule_line_id).
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    original_ticket_line_id = request.GET.get("original_ticket_line_id")
    based_on_reschedule_line_id = request.GET.get("based_on_reschedule_line_id")
    if not company_id or not original_ticket_line_id:
        return JsonResponse({"error": "company_id and original_ticket_line_id are required"}, status=400)

    try:
        original_line = TicketLine.objects.select_related("supplier", "ticket").get(
            id=original_ticket_line_id, ticket__company_id=company_id
        )
    except TicketLine.DoesNotExist:
        return JsonResponse({"error": "Original ticket line not found."}, status=404)

    based_on = None
    if based_on_reschedule_line_id:
        try:
            based_on = RescheduleAirlineTicketLine.objects.select_related("supplier", "reschedule_ticket").get(
                id=based_on_reschedule_line_id, reschedule_ticket__company_id=company_id
            )
        except RescheduleAirlineTicketLine.DoesNotExist:
            return JsonResponse({"error": "Parent reschedule line not found."}, status=404)

    result = _resolve_parent_chain_line(original_line, based_on)

    # One entry per ancestor level, each showing THAT level's own
    # standalone data (not summed) - sits alongside the cumulative total
    # above, for a separate "one tab per ancestor PNR" view. Ordered
    # nearest-ancestor-first (Tab 1 = the immediate parent, last = the
    # true original), reusing _resolve_parent_chain_line itself for each
    # level (based_on_reschedule_line=None there means "just this one
    # line's own data, nothing to aggregate" - works for either a
    # TicketLine or a RescheduleAirlineTicketLine, both expose the same
    # computed_discount/computed_supp_commission/etc properties this
    # relies on).
    chain_levels = []
    node = based_on
    while node is not None:
        chain_levels.append({
            "pnr": node.reschedule_ticket.booking_reference,
            **_resolve_parent_chain_line(node, None),
        })
        node = node.based_on_reschedule_line
    chain_levels.append({
        "pnr": original_line.ticket.booking_reference,
        **_resolve_parent_chain_line(original_line, None),
    })
    result["chain_levels"] = chain_levels

    return JsonResponse(result)


def reschedule_ticket_detail(request, reschedule_ticket_id):
    """
    GET /api/reschedule-tickets/<id>/?company_id=1
    Full reschedule ticket header + ALL its lines - same shape/field names
    as tickets/<id>/ so ticket-entry.html's page-ticket-entry.js can reuse
    its existing passenger-object handling directly. Does NOT embed the
    original ticket's own data (Parent PNR Details) - the frontend fetches
    that separately via tickets/<original_ticket_id>/ (already-existing
    endpoint), same call enterRescheduleMode() already makes for a
    brand-new reschedule.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    try:
        rt = RescheduleAirlineTicket.objects.select_related("customer", "supplier").get(id=reschedule_ticket_id, company_id=company_id)
    except RescheduleAirlineTicket.DoesNotExist:
        return JsonResponse({"error": "Reschedule ticket not found."}, status=404)

    lines = [{
        "id": l.id, "original_ticket_line_id": l.original_ticket_line_id,
        # Status column (renderPaxTable, 2026-10-07) - THIS reschedule
        # line's own state: rescheduled=True means it was itself later
        # rescheduled again (chaining); canceled=True means this specific
        # reschedule was cancelled (views.cancellation_ticket_create /
        # sp_CancellationTicket's SAVE action flips this one independently
        # of the true original TicketLine's own flag).
        "rescheduled": l.rescheduled, "canceled": l.canceled,
        # Set only when this reschedule was itself chained off a PREVIOUS
        # reschedule - re-sent as the same key reschedule_ticket_create/
        # update expect, so re-saving a chained reschedule never loses its
        # chain link.
        "reschedule_line_id": l.based_on_reschedule_line_id,
        # Stored, not dynamically re-derived - whatever Parent PNR was
        # actually used when THIS reschedule was created, permanently.
        "parent_pnr": l.parent_pnr,
        "airline_code": l.airline_code, "airline_name": l.airline_name, "airline_category": l.airline_category,
        "flight_no": l.flight_no,
        "ticket_no": l.ticket_no, "passenger_name": l.passenger_name, "pax_type": l.pax_type,
        "sector": l.sector, "travel_date": l.travel_date,
        "cabin": l.cabin, "travel_class": l.travel_class, "fare_type": l.fare_type,
        "basic_fare": float(l.basic_fare), "yq": float(l.yq), "yr": float(l.yr), "k3_tax": float(l.k3_tax),
        "tax_others": float(l.tax_others), "seat": float(l.seat), "meal": float(l.meal),
        "baggage": float(l.baggage), "other_ssr": float(l.other_ssr), "disc_on": l.disc_on,
        "disc_type": l.disc_type, "disc_value": float(l.disc_value), "tds_per": float(l.tds_per),
        "pg_charges": float(l.pg_charges or 0), "pg_charges_percentage": float(l.pg_charges_percentage) if l.pg_charges_percentage is not None else None,
        "markup": float(l.markup), "addl_markup": float(l.addl_markup), "ssr_markup": float(l.ssr_markup),
        "service_fee": float(l.service_fee),
        "addl_service_fee": float(l.addl_service_fee), "ssr_service_fee": float(l.ssr_service_fee), "gst_pct": float(l.gst_pct),
        "total_billed": float(l.total_billed), "status": l.status,
        "supplier_name": l.supplier.name if l.supplier else None, "office_id": l.office_id, "fop": l.fop,
        "card_number": l.card_number,
        "supp_comm_on": l.supp_comm_on, "supp_comm_type": l.supp_comm_type,
        "supp_comm_value": float(l.supp_comm_value), "supp_tds_per": float(l.supp_tds_per),
        "supp_markup": float(l.supp_markup), "supp_addl_markup": float(l.supp_addl_markup),
        "supp_service_fee": float(l.supp_service_fee), "supp_addl_service_fee": float(l.supp_addl_service_fee),
        "supp_gst_pct": float(l.supp_gst_pct),
        "agent_penalty": float(l.agent_penalty), "reschedule_penalty": float(l.reschedule_penalty),
        "supplier_penalty": float(l.supplier_penalty),
    } for l in rt.lines.select_related("supplier").all()]

    return JsonResponse({
        "id": rt.id, "original_ticket_id": rt.original_ticket_id,
        "invoice_number": rt.invoice_number, "invoice_date": rt.invoice_date.isoformat() if rt.invoice_date else None,
        "invoice_type": rt.invoice_type, "booking_mode": rt.booking_mode, "booking_type": rt.booking_type,
        "booking_status": rt.booking_status, "customer_name": rt.customer.name, "travel_type": rt.travel_type,
        "user_name": rt.user_name, "currency": rt.currency, "roe": float(rt.roe), "booking_given_by": rt.booking_given_by,
        "booking_reference": rt.booking_reference, "booking_ref_date": rt.booking_ref_date.isoformat() if rt.booking_ref_date else None,
        "airline_pnr": rt.airline_pnr, "gds_pnr": rt.gds_pnr, "supplier_name": rt.supplier.name if rt.supplier else None,
        "office_id": rt.office_id, "payment_mode": rt.payment_mode, "payment_gateway_ref": rt.payment_gateway_ref,
        "airline_category": rt.airline_category, "branch_name": rt.branch_name, "lines": lines,
    })


# ============================================================
# Reschedule-only Journal Voucher - entirely separate from
# _compute_jv_lines/JV_LINE_MAP (jv_hardcode.py), which is Booking's own
# JV and must never be touched by this. The frontend now filters out
# zero-amount rows itself (renderRescheduleJvPreview), and the two
# "Output IGST A/c" entries below (customer-side "gst" and supplier-side
# "supp_gst") are combined and state-split into Output CGST/Output SGST
# or a single Output IGST A/c, matching Booking's own JV exactly (see
# _compute_reschedule_jv_lines' own Output GST handling below).
# ============================================================
RESCHED_JV_LINE_MAP = [
    ("Credit", "Earnings From Supplier", "Commission A/c", "commission"),
    ("Debit", "GST and TDS", "Commission TDS A/c", "commission_tds"),
    ("Debit", "Expenditure To Supplier", "Supplier Markup A/c", "supp_markup"),
    ("Debit", "Expenditure To Supplier", "Supplier Addl Markup A/c", "supp_addl_markup"),
    ("Debit", "Expenditure To Supplier", "Supplier Service Fee A/c", "supp_service_fee"),
    ("Debit", "Expenditure To Supplier", "Supplier Addl Service Fee A/c", "supp_addl_service_fee"),
    ("Debit", "GST and TDS", "Input IGST A/c", "supp_gst"),
    ("Debit", "Expenditure To Supplier", "Supplier Reschedule Penalty A/c", "reschedule_penalty"),
    ("Credit", "Earnings From Customer", "Consolidator Markup A/c", "supp_markup"),
    ("Credit", "Earnings From Customer", "Consolidator Addl Markup A/c", "supp_addl_markup"),
    ("Credit", "Earnings From Customer", "Consolidator Service Fee A/c", "supp_service_fee"),
    ("Credit", "Earnings From Customer", "Consolidator Addl Service Fee A/c", "supp_addl_service_fee"),
    ("Credit", "GST and TDS", "Output IGST A/c", "supp_gst"),
    ("Credit", "Earnings From Customer", "Consolidator Reschedule Penalty A/c", "reschedule_penalty"),
    ("Debit", "Expenditure To Customer", "Discount A/c", "discount"),
    ("Credit", "GST and TDS", "Discount TDS A/c", "discount_tds"),
    ("Credit", "Earnings From Customer", "Markup A/c", "markup"),
    ("Credit", "Earnings From Customer", "Addl Markup A/c", "addl_markup"),
    ("Credit", "Earnings From Customer", "SSR Markup A/c", "ssr_markup"),
    ("Credit", "Earnings From Customer", "Service Fee A/c", "service_fee"),
    ("Credit", "Earnings From Customer", "Addl Service Fee A/c", "addl_service_fee"),
    ("Credit", "Earnings From Customer", "SSR Service Fee A/c", "ssr_service_fee"),
    ("Credit", "GST and TDS", "Output IGST A/c", "gst"),
    ("Credit", "Expenditure To Customer", "Agent Penalty A/c", "agent_penalty"),
]


def _compute_reschedule_jv_lines(resched_ticket, lines, mapping_cache=None, company_state=None):
    """
    Customer (Debit) = Basic+YQ+YR+K3+Tax&Others+Seat+Meal+Baggage+Other
    SSR + Customer TDS + Customer Markup/Addl Markup/Service Fee/Addl
    Service Fee/SSR Markup/SSR Service Fee + Customer GST - Cust Discount
    + Sup Markup/Addl Markup/Service Fee/Addl Service Fee/GST + Supplier
    Penalty + Reschedule Penalty + Agent Penalty. The first 15 terms
    (everything up to "- Cust Discount") plus the Sup Markup/Service Fee/
    GST terms are exactly RescheduleAirlineTicketLine.compute_total() -
    reused directly, then the 3 penalties are added on top (compute_total()
    predates them and intentionally excludes them, same as Booking's own
    TicketLine.compute_total()).

    Supplier (Credit) = Basic+YQ+YR+K3+Tax&Others+Seat+Meal+Baggage+Other
    SSR - Supplier Commission + Supplier TDS + Sup Markup/Addl Markup/
    Service Fee/Addl Service Fee/GST + Supplier Penalty + Reschedule
    Penalty (no Agent Penalty here - that's Customer-only).
    """
    role_amounts = {
        "commission": sum(float(l.computed_supp_commission) for l in lines),
        "commission_tds": sum(float(l.computed_supp_tds) for l in lines),
        "supp_markup": sum(float(l.supp_markup) for l in lines),
        "supp_addl_markup": sum(float(l.supp_addl_markup) for l in lines),
        "supp_service_fee": sum(float(l.supp_service_fee) for l in lines),
        "supp_addl_service_fee": sum(float(l.supp_addl_service_fee) for l in lines),
        "supp_gst": sum(float(l.computed_supp_gst) for l in lines),
        "reschedule_penalty": sum(float(l.reschedule_penalty) for l in lines),
        "discount": sum(float(l.computed_discount) for l in lines),
        "discount_tds": sum(float(l.computed_tds) for l in lines),
        "markup": sum(float(l.markup) for l in lines),
        "addl_markup": sum(float(l.addl_markup) for l in lines),
        "ssr_markup": sum(float(l.ssr_markup) for l in lines),
        "service_fee": sum(float(l.service_fee) for l in lines),
        "addl_service_fee": sum(float(l.addl_service_fee) for l in lines),
        "ssr_service_fee": sum(float(l.ssr_service_fee) for l in lines),
        "gst": sum(float(l.computed_gst) for l in lines),
        "agent_penalty": sum(float(l.agent_penalty) for l in lines),
    }
    penalties_total = sum(
        float(l.supplier_penalty) + float(l.reschedule_penalty) + float(l.agent_penalty) for l in lines
    )
    customer_total = sum(float(l.compute_total()) for l in lines) + penalties_total

    supplier_groups = {}
    for l in lines:
        group = supplier_groups.setdefault(l.supplier_id, {"ledger": l.supplier, "amount": 0.0})
        group["amount"] += (
            float(l.supplier_cost) - float(l.computed_supp_commission) + float(l.computed_supp_tds)
            + float(l.supp_markup) + float(l.supp_addl_markup)
            + float(l.supp_service_fee) + float(l.supp_addl_service_fee)
            + float(l.computed_supp_gst)
            + float(l.supplier_penalty) + float(l.reschedule_penalty)
        )

    def dr_cr_amounts(dr_cr, amount):
        amount = round(amount, 2)
        return (amount, 0) if dr_cr == "Debit" else (0, amount)

    def customer_rows(dr_cr, amount):
        debit, credit = dr_cr_amounts(dr_cr, amount)
        return [{"role": "customer", "ledger_id": resched_ticket.customer_id,
                 "ledger_name": resched_ticket.customer.name, "debit": debit, "credit": credit}]

    def supplier_rows(dr_cr):
        rows = []
        for g in supplier_groups.values():
            debit, credit = dr_cr_amounts(dr_cr, g["amount"])
            ledger = g["ledger"]
            name = ledger.name if ledger else "— (no supplier selected)"
            rows.append({"role": "supplier", "ledger_id": ledger.id if ledger else None,
                         "ledger_name": name, "debit": debit, "credit": credit})
        return rows

    if mapping_cache is None:
        mapping_cache = {}

    def mapped_ledger(masters_category, field_name):
        key = (resched_ticket.company_id, masters_category, field_name)
        if key not in mapping_cache:
            m = MasterMapping.objects.filter(
                company_id=resched_ticket.company_id, product_type="Airline",
                masters_category=masters_category, field_name=field_name,
            ).select_related("ledger").first()
            mapping_cache[key] = (
                (m.ledger_id, m.ledger.name) if m
                else (None, f"{field_name} (not mapped in Master Mapping)")
            )
        return mapping_cache[key]

    def mapped_row(dr_cr, masters_category, field_name, amount):
        debit, credit = dr_cr_amounts(dr_cr, amount)
        ledger_id, ledger_name = mapped_ledger(masters_category, field_name)
        return {"role": field_name, "ledger_id": ledger_id, "ledger_name": ledger_name, "debit": debit, "credit": credit}

    # Output GST - same concept as Booking's own JV: the customer-side
    # ("gst") and supplier-side ("supp_gst") Output IGST A/c amounts are
    # combined into ONE, then shown as Output CGST + Output SGST (split in
    # half) when the customer is in the SAME state as the company, or one
    # combined Output IGST A/c otherwise - never as two separate, literal
    # "Output IGST A/c" rows the way this used to.  The separate DEBIT
    # "Input IGST A/c" line (also fed by supp_gst) is untouched - that's a
    # different line entirely (Input, not Output).
    if company_state is None:
        company_state = (CompanyMaster.objects.filter(id=resched_ticket.company_id).values_list("state", flat=True).first() or "").strip().lower()
    customer_state = (resched_ticket.customer.state_name or "").strip().lower()
    same_state = bool(company_state) and bool(customer_state) and company_state == customer_state
    OUTPUT_GST_KEYS = {"gst", "supp_gst"}

    accounts = customer_rows("Debit", customer_total) + supplier_rows("Credit")
    output_gst_emitted = False
    for dr_cr, masters_category, field_name, amount_key in RESCHED_JV_LINE_MAP:
        if dr_cr == "Credit" and masters_category == "GST and TDS" and field_name == "Output IGST A/c" and amount_key in OUTPUT_GST_KEYS:
            if not output_gst_emitted:
                output_gst_emitted = True
                combined_gst = round(role_amounts["gst"] + role_amounts["supp_gst"], 2)
                if same_state:
                    half = round(combined_gst / 2, 2)
                    accounts.append(mapped_row("Credit", "GST and TDS", "Output CGST A/c", half))
                    accounts.append(mapped_row("Credit", "GST and TDS", "Output SGST A/c", half))
                else:
                    accounts.append(mapped_row("Credit", "GST and TDS", "Output IGST A/c", combined_gst))
            continue
        accounts.append(mapped_row(dr_cr, masters_category, field_name, role_amounts[amount_key]))

    narration = " / ".join(filter(None, [
        resched_ticket.booking_reference, resched_ticket.airline_pnr,
        lines[0].ticket_no if lines else None,
    ]))
    total_debit = round(sum(a["debit"] for a in accounts), 2)
    total_credit = round(sum(a["credit"] for a in accounts), 2)
    return accounts, narration, total_debit, total_credit


def _reschedule_fop_payment_lines(resched_ticket, lines):
    """
    Reschedule's own FOP Payment settlement (JV-3 Own Card / JV-4 Client
    Card) - mirrors _fop_payment_lines exactly, except the per-line
    supplier amount also folds in Supplier Penalty + Reschedule Penalty
    (see _compute_reschedule_jv_lines' own supplier formula, which this
    must stay in sync with - the two tabs settle the SAME Supplier
    balance the Main JV debited/credited).
    """
    fop = lines[0].fop if lines else None
    if not fop or fop == "Cash":
        return []

    supplier_groups = {}
    for l in lines:
        group = supplier_groups.setdefault(l.supplier_id, {"ledger": l.supplier, "amount": 0.0})
        group["amount"] += (
            float(l.supplier_cost) - float(l.computed_supp_commission) + float(l.computed_supp_tds)
            + float(l.supp_markup) + float(l.supp_addl_markup)
            + float(l.supp_service_fee) + float(l.supp_addl_service_fee)
            + float(l.computed_supp_gst)
            + float(l.supplier_penalty) + float(l.reschedule_penalty)
        )
    total_amount = round(sum(g["amount"] for g in supplier_groups.values()), 2)
    if total_amount == 0:
        return []

    result = [(g["ledger"].id, g["amount"], 0) for g in supplier_groups.values() if g["ledger"]]
    if fop == "Own Card":
        card_number = lines[0].card_number or ""
        card = sp_client.fop_master_get_by_card_number(resched_ticket.company_id, card_number)
        if card:
            result.append((card["card_master_ledger_id"], 0, total_amount))
    else:  # Client Card
        result.append((resched_ticket.customer_id, 0, total_amount))
    return result


def _reschedule_pg_receipt_lines(resched_ticket, lines):
    """
    Reschedule's own PG Receipt settlement (JV-2/JV-5) - mirrors
    _pg_receipt_lines, except the Customer amount settled back to zero
    also folds in Supplier Penalty + Reschedule Penalty + Agent Penalty
    (see _compute_reschedule_jv_lines' own customer formula, which this
    must stay in sync with - same Customer balance the Main JV debited).
    """
    if resched_ticket.payment_mode != "Payment Gateway":
        return []
    customer_total = round(sum(
        float(l.compute_total()) + float(l.supplier_penalty) + float(l.reschedule_penalty) + float(l.agent_penalty)
        for l in lines
    ), 2)
    if customer_total == 0:
        return []
    result = [(resched_ticket.customer_id, 0, customer_total)]
    snapshot = _pg_master_effective_snapshot(
        resched_ticket.company_id, resched_ticket.payment_gateway_ref or "",
        resched_ticket.invoice_date or resched_ticket.booking_ref_date,
    )
    if snapshot:
        pg_charges_total = round(sum(float(l.pg_charges or 0) for l in lines), 2)
        pg_gst_pct = snapshot["pg_charges_master_ledger_gst_percentage"]
        pg_gst_total = round(pg_charges_total * pg_gst_pct / 100, 2)

        gateway_debit_total = round(customer_total + pg_charges_total + pg_gst_total, 2)
        result.append((snapshot["payment_master_ledger_id"], gateway_debit_total, 0))
        if pg_charges_total and snapshot["pg_charges_master_ledger_id"]:
            result.append((snapshot["pg_charges_master_ledger_id"], pg_charges_total, 0))
            result.append((snapshot["payment_master_ledger_id"], 0, pg_charges_total))
        if pg_gst_total:
            result.append((snapshot["payment_master_ledger_id"], 0, pg_gst_total))
    return result


def reschedule_jv_preview(request, reschedule_ticket_id):
    """
    GET /api/reschedule-tickets/<id>/jv-preview/?company_id=1
    Always computes the JV lines LIVE from this reschedule ticket's own
    lines (_compute_reschedule_jv_lines) - never reads a stored snapshot.
    JournalVoucher is only consulted here to report whether this
    reschedule ticket has actually been posted yet (reschedule_ticket_
    create/update auto-post one immediately on save, same as a normal
    ticket), and its ALR-prefixed voucher_no if so.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    try:
        rt = RescheduleAirlineTicket.objects.select_related("customer", "supplier").get(id=reschedule_ticket_id, company_id=company_id)
    except RescheduleAirlineTicket.DoesNotExist:
        return JsonResponse({"error": "Reschedule ticket not found."}, status=404)

    lines = list(rt.lines.all())
    if not lines:
        return JsonResponse({"error": "This reschedule ticket has no lines to build a voucher from."}, status=400)

    accounts, narration, total_debit, total_credit = _compute_reschedule_jv_lines(rt, lines)

    voucher = JournalVoucher.objects.filter(source_reschedule_ticket_id=rt.id).only("id", "voucher_no").first()

    return JsonResponse({
        "posted": voucher is not None,
        "voucher_id": voucher.id if voucher else None,
        "voucher_no": voucher.voucher_no if voucher else None,
        "branch_name": rt.branch_name or "Chennai Branch",
        "voucher_type": "Tax Invoice",
        "voucher_date": rt.invoice_date.isoformat() if rt.invoice_date else None,
        "narration": narration,
        "accounts": accounts,
        "total_debit": total_debit,
        "total_credit": total_credit,
    })


@csrf_exempt
def reschedule_jv_preview_draft(request):
    """
    POST /api/reschedule-tickets/jv-preview-draft/
    Same body shape as reschedule-tickets/create/ - lets the Reschedule
    PNR Details form show a live JV preview before Save Ticket. Builds
    UNSAVED RescheduleAirlineTicket/RescheduleAirlineTicketLine instances
    (never .save()'d) to run through the exact same _compute_reschedule_
    jv_lines used above, same looseness as ticket_jv_preview_draft (a
    missing/invalid supplier just posts that line's Supplier row against
    no ledger rather than rejecting the whole preview).
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    company_id = body.get("company_id")
    lines_in = body.get("lines") or []
    if not company_id or not lines_in:
        return JsonResponse({"error": "company_id and at least one line are required."}, status=400)

    customer = None
    if body.get("customer_name"):
        customer = Ledger.objects.filter(company_id=company_id, name=body["customer_name"], ledger_category="DEBTOR").first()
    if customer is None:
        return JsonResponse({"error": "Pick a Customer before previewing the JV."}, status=400)

    supplier = None
    if body.get("supplier_name"):
        supplier = Ledger.objects.filter(company_id=company_id, name=body["supplier_name"], ledger_category="CREDITOR").first()

    header_kwargs = {f: body[f] for f in TICKET_HEADER_FIELDS if f in body}
    header_kwargs["invoice_date"] = _parse_date(header_kwargs.get("invoice_date"))
    header_kwargs["booking_ref_date"] = _parse_date(header_kwargs.get("booking_ref_date"))
    if "roe" in header_kwargs:
        header_kwargs["roe"] = _safe_decimal(header_kwargs["roe"], default=1)

    resched_ticket = RescheduleAirlineTicket(company_id=company_id, customer=customer, supplier=supplier, **header_kwargs)

    line_objs = []
    for line_in in lines_in:
        line_kwargs = {f: line_in[f] for f in RESCHED_LINE_FIELDS if f in line_in}
        for f in RESCHED_LINE_NUMERIC_FIELDS:
            if f in line_kwargs:
                line_kwargs[f] = _safe_decimal(line_kwargs[f])

        line_supplier = None
        if line_in.get("supplier_name"):
            line_supplier = Ledger.objects.filter(company_id=company_id, name=line_in["supplier_name"], ledger_category="CREDITOR").first()

        line = RescheduleAirlineTicketLine(reschedule_ticket=resched_ticket, supplier=line_supplier, **line_kwargs)
        line.total_billed = _safe_decimal(line.compute_total())
        line_objs.append(line)

    accounts, narration, total_debit, total_credit = _compute_reschedule_jv_lines(resched_ticket, line_objs)
    total_debit, total_credit = round(total_debit, 2), round(total_credit, 2)

    return JsonResponse({
        "posted": False, "voucher_id": None, "voucher_no": None,
        "branch_name": resched_ticket.branch_name or "Chennai Branch",
        "voucher_type": "Tax Invoice",
        "voucher_date": resched_ticket.invoice_date.isoformat() if resched_ticket.invoice_date else None,
        "narration": narration,
        "accounts": accounts,
        "total_debit": total_debit,
        "total_credit": total_credit,
    })


def ticket_detail(request, ticket_id):
    """
    GET /api/tickets/<id>/?company_id=1
    Full ticket header + ALL its lines (every passenger), properly
    nested — unlike tickets_list which returns one flat row per line.
    Used by ticket-entry.html's view-only mode.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    header, sp_lines = sp_client.ticket_get(ticket_id, company_id)
    if not header:
        return JsonResponse({"error": "Ticket not found."}, status=404)

    lines = [{
        "id": l["id"],
        # Status column (renderPaxTable, 2026-10-07) - canceled wins if both
        # are somehow true (shouldn't happen in practice, but a cancelled
        # line is also marked reschedule-ineligible by nothing in particular -
        # these two flags are independently set, never mutually exclusive by
        # a DB constraint).
        "rescheduled": bool(l["rescheduled"]), "canceled": bool(l["canceled"]),
        "airline_code": l["airline_code"], "airline_name": l["airline_name"], "airline_category": l["airline_category"],
        "flight_no": l["flight_no"],
        "ticket_no": l["ticket_no"], "passenger_name": l["passenger_name"], "pax_type": l["pax_type"],
        "sector": l["sector"], "travel_date": l["travel_date"],
        "cabin": l["cabin"], "travel_class": l["travel_class"], "fare_type": l["fare_type"],
        "basic_fare": float(l["basic_fare"]), "yq": float(l["yq"]), "yr": float(l["yr"]), "k3_tax": float(l["k3_tax"]),
        "tax_others": float(l["tax_others"]), "seat": float(l["seat"]), "meal": float(l["meal"]),
        "baggage": float(l["baggage"]), "other_ssr": float(l["other_ssr"]), "disc_on": l["disc_on"],
        "disc_type": l["disc_type"], "disc_value": float(l["disc_value"]), "tds_per": float(l["tds_per"]),
        "pg_charges": float(l["pg_charges"] or 0), "pg_charges_percentage": float(l["pg_charges_percentage"]) if l["pg_charges_percentage"] is not None else None,
        "markup": float(l["markup"]), "addl_markup": float(l["addl_markup"]), "ssr_markup": float(l["ssr_markup"]),
        "service_fee": float(l["service_fee"]),
        "addl_service_fee": float(l["addl_service_fee"]), "ssr_service_fee": float(l["ssr_service_fee"]), "gst_pct": float(l["gst_pct"]),
        "total_billed": float(l["total_billed"]), "status": l["status"],
        "supplier_name": l["supplier_name"], "office_id": l["office_id"], "fop": l["fop"],
        "card_number": l["card_number"],
        "supp_comm_on": l["supp_comm_on"], "supp_comm_type": l["supp_comm_type"],
        "supp_comm_value": float(l["supp_comm_value"]), "supp_tds_per": float(l["supp_tds_per"]),
        "supp_markup": float(l["supp_markup"]), "supp_addl_markup": float(l["supp_addl_markup"]),
        "supp_service_fee": float(l["supp_service_fee"]), "supp_addl_service_fee": float(l["supp_addl_service_fee"]),
        "supp_gst_pct": float(l["supp_gst_pct"]),
        "computed_discount": float(l["computed_discount"]), "computed_tds": float(l["computed_tds"]), "computed_gst": float(l["computed_gst"]),
        "computed_supp_commission": float(l["computed_supp_commission"]), "computed_supp_tds": float(l["computed_supp_tds"]),
        "computed_supp_gst": float(l["computed_supp_gst"]),
    } for l in sp_lines]

    return JsonResponse({
        "id": header["id"], "invoice_number": header["invoice_number"],
        "invoice_date": header["invoice_date"].isoformat() if header["invoice_date"] else None,
        "invoice_type": header["invoice_type"], "booking_mode": header["booking_mode"], "booking_type": header["booking_type"],
        "booking_status": header["booking_status"], "customer_name": header["customer_name"], "travel_type": header["travel_type"],
        "user_name": header["user_name"], "currency": header["currency"], "roe": float(header["roe"]), "booking_given_by": header["booking_given_by"],
        "booking_reference": header["booking_reference"], "booking_ref_date": header["booking_ref_date"].isoformat() if header["booking_ref_date"] else None,
        "airline_pnr": header["airline_pnr"], "gds_pnr": header["gds_pnr"], "supplier_name": header["supplier_name"],
        "office_id": header["office_id"], "payment_mode": header["payment_mode"], "payment_gateway_ref": header["payment_gateway_ref"],
        "airline_category": header["airline_category"],
        "branch_name": header["branch_name"], "lines": lines,
    })


def reschedule_tickets_list(request):
    """
    GET /api/reschedule-tickets/list/?company_id=1
    One row per RescheduleAirlineTicketLine, same flat shape as
    tickets_list() (reused by report-dsr-airline-booking.html, which
    merges this in alongside the normal tickets_list() rows so Reschedule
    bookings show up in DSR too) - "ticket_id" is always null here (there
    is no Ticket backing these rows) and "reschedule_ticket_id" is set
    instead, so callers that group/link by ticket can tell the two apart.
    booking_status is always "Re-Scheduled" (frozen at creation - see
    enterRescheduleMode()/enterSavedRescheduleMode() in page-ticket-
    entry.js), which DSR's own Status filter already expects.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    rows = []
    for l in sp_client.reschedule_tickets_list(company_id):
        rows.append({
            "id": l["id"], "ticket_id": None, "reschedule_ticket_id": l["reschedule_ticket_id"],
            "pnr": l["pnr"],
            "ticket_no": l["ticket_no"], "airline_name": l["airline_name"], "airline_code": l["airline_code"],
            "flight_no": l["flight_no"], "passenger_name": l["passenger_name"], "pax_type": l["pax_type"],
            "sector": l["sector"], "issue_date": l["issue_date"].isoformat() if l["issue_date"] else None,
            "travel_date": l["travel_date"],
            "basic_fare": float(l["basic_fare"]), "markup": float(l["markup"]), "total_billed": float(l["total_billed"]),
            "status": l["status"],
            "invoice_number": l["invoice_number"], "invoice_date": l["invoice_date"].isoformat() if l["invoice_date"] else None,
            "invoice_type": l["invoice_type"], "booking_mode": l["booking_mode"], "booking_type": l["booking_type"],
            "booking_status": l["booking_status"], "customer_name": l["customer_name"],
            "travel_type": l["travel_type"], "user_name": l["user_name"], "currency": l["currency"], "roe": float(l["roe"]),
            "booking_given_by": l["booking_given_by"], "payment_mode": l["payment_mode"], "airline_category": l["airline_category"],
            "booking_reference": l["booking_reference"], "booking_ref_date": l["booking_ref_date"].isoformat() if l["booking_ref_date"] else None,
            "airline_pnr": l["airline_pnr"], "gds_pnr": l["gds_pnr"], "supplier_name": l["supplier_name"],
            "office_id": l["office_id"], "fop": l["fop"], "card_number": l["card_number"],
            "yq": float(l["yq"]), "yr": float(l["yr"]), "k3_tax": float(l["k3_tax"]), "tax_others": float(l["tax_others"]),
            "seat": float(l["seat"]), "meal": float(l["meal"]), "baggage": float(l["baggage"]), "other_ssr": float(l["other_ssr"]),
            "disc_on": l["disc_on"], "disc_type": l["disc_type"], "disc_value": float(l["disc_value"]), "tds_per": float(l["tds_per"]),
            "addl_markup": float(l["addl_markup"]), "ssr_markup": float(l["ssr_markup"]), "service_fee": float(l["service_fee"]),
            "addl_service_fee": float(l["addl_service_fee"]), "ssr_service_fee": float(l["ssr_service_fee"]), "gst_pct": float(l["gst_pct"]),
            "supp_comm_on": l["supp_comm_on"], "supp_comm_type": l["supp_comm_type"],
            "supp_comm_value": float(l["supp_comm_value"]), "supp_tds_per": float(l["supp_tds_per"]),
            "supp_markup": float(l["supp_markup"]), "supp_addl_markup": float(l["supp_addl_markup"]),
            "supp_service_fee": float(l["supp_service_fee"]), "supp_addl_service_fee": float(l["supp_addl_service_fee"]),
            "computed_discount": float(l["computed_discount"]), "computed_tds": float(l["computed_tds"]), "computed_gst": float(l["computed_gst"]),
            "computed_supp_gst": float(l["computed_supp_gst"]),
            "agent_penalty": float(l["agent_penalty"]), "reschedule_penalty": float(l["reschedule_penalty"]),
            "supplier_penalty": float(l["supplier_penalty"]),
        })
    return JsonResponse(rows, safe=False)


def tickets_list(request):
    """
    GET /api/tickets/?company_id=1
    One row per TicketLine, joined with its Ticket header — matches
    exactly what tickets.html's table + details modal already expect
    (pnr, ticket_no, airline_name, passenger_name, sector, issue_date,
    basic_fare, markup, total_billed, status, plus every header/line
    detail field for the "View Details" modal).
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    rows = []
    for l in sp_client.tickets_list(company_id):
        rows.append({
            "id": l["id"], "ticket_id": l["ticket_id"],
            "pnr": l["pnr"],
            "ticket_no": l["ticket_no"], "airline_name": l["airline_name"], "airline_code": l["airline_code"],
            "flight_no": l["flight_no"], "passenger_name": l["passenger_name"], "pax_type": l["pax_type"],
            "sector": l["sector"], "issue_date": l["issue_date"].isoformat() if l["issue_date"] else None,
            "travel_date": l["travel_date"],
            "basic_fare": float(l["basic_fare"]), "markup": float(l["markup"]), "total_billed": float(l["total_billed"]),
            "status": l["status"],
            "invoice_number": l["invoice_number"], "invoice_date": l["invoice_date"].isoformat() if l["invoice_date"] else None,
            "invoice_type": l["invoice_type"], "booking_mode": l["booking_mode"], "booking_type": l["booking_type"],
            "booking_status": l["booking_status"], "customer_name": l["customer_name"],
            "travel_type": l["travel_type"], "user_name": l["user_name"], "currency": l["currency"], "roe": float(l["roe"]),
            "booking_given_by": l["booking_given_by"], "payment_mode": l["payment_mode"], "airline_category": l["airline_category"],
            "booking_reference": l["booking_reference"], "booking_ref_date": l["booking_ref_date"].isoformat() if l["booking_ref_date"] else None,
            "airline_pnr": l["airline_pnr"], "gds_pnr": l["gds_pnr"], "supplier_name": l["supplier_name"],
            "office_id": l["office_id"], "fop": l["fop"], "card_number": l["card_number"],
            "yq": float(l["yq"]), "yr": float(l["yr"]), "k3_tax": float(l["k3_tax"]), "tax_others": float(l["tax_others"]),
            "seat": float(l["seat"]), "meal": float(l["meal"]), "baggage": float(l["baggage"]), "other_ssr": float(l["other_ssr"]),
            "disc_on": l["disc_on"], "disc_type": l["disc_type"], "disc_value": float(l["disc_value"]), "tds_per": float(l["tds_per"]),
            "addl_markup": float(l["addl_markup"]), "ssr_markup": float(l["ssr_markup"]), "service_fee": float(l["service_fee"]),
            "addl_service_fee": float(l["addl_service_fee"]), "ssr_service_fee": float(l["ssr_service_fee"]), "gst_pct": float(l["gst_pct"]),
            "supp_comm_on": l["supp_comm_on"], "supp_comm_type": l["supp_comm_type"],
            "supp_comm_value": float(l["supp_comm_value"]), "supp_tds_per": float(l["supp_tds_per"]),
            "supp_markup": float(l["supp_markup"]), "supp_addl_markup": float(l["supp_addl_markup"]),
            "supp_service_fee": float(l["supp_service_fee"]), "supp_addl_service_fee": float(l["supp_addl_service_fee"]),
            "computed_discount": float(l["computed_discount"]), "computed_tds": float(l["computed_tds"]), "computed_gst": float(l["computed_gst"]),
            "computed_supp_gst": float(l["computed_supp_gst"]),
        })
    return JsonResponse(rows, safe=False)


def ticket_lookup_for_reschedule(request):
    """
    GET /api/tickets/lookup-for-reschedule/?company_id=1&s_pnr=..&airline_pnr=..&ticket_no=..
    Finds a single Ticket by whichever identifier was actually given -
    Ticket No first (unique to one TicketLine, so most specific), then
    S PNR (Booking Reference), then Airline PNR - and returns every
    eligible (not yet rescheduled) passenger on that ticket with their own
    sectors already split out.

    Also searches RescheduleAirlineTicket/RescheduleAirlineTicketLine by
    the exact same 3 identifiers (chaining) - rescheduling an
    ALREADY-RESCHEDULED ticket again. FKs always anchor back to the true
    original Ticket/TicketLine regardless of chain depth (ticket_id/
    matched_line_id below are always the ORIGINAL ids, since that's what
    reschedule_ticket_create needs), but the response's booking_reference/
    airline_pnr/invoice_number and each passenger's own fields come from
    the MATCHED RESCHEDULE's own data when found there, so "Parent PNR
    Details" on the next reschedule reflects the most recent state, not
    the stale several-steps-back original. source_reschedule_ticket_id is
    set in that case so the frontend can carry it through to ticket-
    entry.html, and each passenger carries its own reschedule_line_id
    (the chain link reschedule_ticket_create needs to flip the RIGHT
    eligibility flag - the reschedule's own, not the original's, which
    was already flipped False the first time around).

    TicketLine/RescheduleAirlineTicketLine both store a multi-city
    ticket's sector/flight_no/travel_class/travel_date as one comma-joined
    value per field (same convention page-ticket-entry.js's own
    parseSectorsFromPassenger() splits client-side) - mirrored here so the
    Reschedule page can show each sector as its own row without
    re-implementing that parsing twice.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    s_pnr = (request.GET.get("s_pnr") or "").strip()
    airline_pnr = (request.GET.get("airline_pnr") or "").strip()
    ticket_no = (request.GET.get("ticket_no") or "").strip()
    if not (s_pnr or airline_pnr or ticket_no):
        return JsonResponse({"error": "Enter S PNR, Airline PNR or Ticket No to search."}, status=400)

    ticket = None
    matched_line_id = None
    matched_line = None
    resched_source = None       # RescheduleAirlineTicket, set when found via reschedule data
    resched_source_line = None  # RescheduleAirlineTicketLine, set only on an exact Ticket No match

    if ticket_no:
        line = TicketLine.objects.filter(ticket__company_id=company_id, ticket_no=ticket_no).select_related("ticket").first()
        if line:
            ticket = line.ticket
            matched_line_id = line.id
            matched_line = line
        else:
            rline = RescheduleAirlineTicketLine.objects.filter(
                reschedule_ticket__company_id=company_id, ticket_no=ticket_no
            ).select_related("reschedule_ticket", "original_ticket_line__ticket").first()
            if rline:
                resched_source_line = rline
                resched_source = rline.reschedule_ticket
                matched_line = rline.original_ticket_line
                matched_line_id = matched_line.id
                ticket = matched_line.ticket
    if not ticket and s_pnr:
        ticket = Ticket.objects.filter(company_id=company_id, booking_reference=s_pnr).first()
        if not ticket:
            rt = RescheduleAirlineTicket.objects.filter(company_id=company_id, booking_reference=s_pnr).select_related("original_ticket").first()
            if rt:
                resched_source = rt
                ticket = rt.original_ticket
    if not ticket and airline_pnr:
        ticket = Ticket.objects.filter(company_id=company_id, airline_pnr=airline_pnr).first()
        if not ticket:
            rt = RescheduleAirlineTicket.objects.filter(company_id=company_id, airline_pnr=airline_pnr).select_related("original_ticket").first()
            if rt:
                resched_source = rt
                ticket = rt.original_ticket

    if not ticket:
        return JsonResponse({"error": "No ticket found matching that S PNR / Airline PNR / Ticket No."}, status=404)

    # Searched by an EXACT Ticket No that's already been rescheduled - this
    # one specific passenger can never be rescheduled again, regardless of
    # whether other passengers on the same invoice are still eligible.
    # Checks the RIGHT flag depending on which table actually matched:
    # the reschedule's own (if chaining) or the original line's.
    already_rescheduled = (
        resched_source_line.rescheduled if resched_source_line is not None
        else (matched_line is not None and matched_line.rescheduled)
    )
    if already_rescheduled:
        return JsonResponse({
            "error": "This ticket has already been rescheduled and cannot be rescheduled again."
        }, status=409)

    def split_sectors(l):
        pairs = [p.strip() for p in (l.sector or "").split(",") if p.strip()]
        flight_nos = (l.flight_no or "").split(",")
        classes = (l.travel_class or "").split(",")
        dates = [d.strip() for d in (l.travel_date or "").split(",")]
        return [{
            "sector": pairs[i],
            "flight_no": (flight_nos[i].strip() if i < len(flight_nos) else ""),
            "travel_class": (classes[i].strip() if i < len(classes) else ""),
            "travel_date": dates[i] if i < len(dates) else (dates[0] if len(dates) == 1 else ""),
        } for i in range(len(pairs))]

    # Partial passenger reschedule: a passenger/line that's already been
    # rescheduled (rescheduled=True) is excluded here rather than blocking
    # the whole invoice/reschedule - other passengers who haven't been
    # rescheduled yet must still show up.
    # A cancelled passenger can't be rescheduled either.
    if resched_source is not None:
        eligible_lines = list(resched_source.lines.filter(rescheduled=False, canceled=False))
    else:
        eligible_lines = [l for l in ticket.lines.all() if not l.rescheduled and not l.canceled]
    if not eligible_lines:
        return JsonResponse({
            "error": "No passenger on this booking is left to reschedule - each one has already been rescheduled or cancelled."
        }, status=409)

    passengers = [{
        # Always the TRUE original line's id (reschedule_ticket_create's
        # own original_ticket_line_id) regardless of chain depth.
        "line_id": l.original_ticket_line_id if resched_source is not None else l.id,
        "ticket_no": l.ticket_no, "pax_type": l.pax_type, "passenger_name": l.passenger_name,
        "sectors": split_sectors(l),
        # Set only when this passenger came from a reschedule (chaining) -
        # the chain link the NEW reschedule's own line needs.
        "reschedule_line_id": l.id if resched_source is not None else None,
    } for l in eligible_lines]

    return JsonResponse({
        "ticket_id": ticket.id,
        "invoice_number": resched_source.invoice_number if resched_source is not None else ticket.invoice_number,
        "booking_reference": resched_source.booking_reference if resched_source is not None else ticket.booking_reference,
        "airline_pnr": resched_source.airline_pnr if resched_source is not None else ticket.airline_pnr,
        # Only set when the search matched by Ticket No specifically -
        # that identifies ONE particular passenger's line, not just the
        # ticket as a whole (a ticket can have several passengers who
        # each have their own ticket_no). The frontend uses this to
        # pre-select that exact passenger instead of just the first row.
        "matched_line_id": matched_line_id,
        # Set whenever the match came from a reschedule rather than the
        # original ticket - the frontend carries this through as
        # parent_reschedule_id so ticket-entry.html can build "Parent PNR
        # Details" from that reschedule's own data instead of the original.
        "source_reschedule_ticket_id": resched_source.id if resched_source is not None else None,
        "passengers": passengers,
    })


def ticket_lookup_for_cancellation(request):
    """
    GET /api/tickets/lookup-for-cancellation/?company_id=1&s_pnr=..&airline_pnr=..&ticket_no=..
    Finds a single Ticket by whichever identifier was actually given -
    same 3-way search priority as ticket_lookup_for_reschedule (Ticket No
    first, then S PNR/Booking Reference, then Airline PNR).

    Also searches RescheduleAirlineTicket/RescheduleAirlineTicketLine by
    the exact same 3 identifiers, same chaining logic as the reschedule
    lookup - if a passenger has since been rescheduled, their CURRENT
    live data lives there, not on the stale original Ticket, so:
      - Searching by that reschedule's own new PNR/Ticket No finds and
        returns ITS OWN data (works correctly, any chain depth).
      - Searching by an exact Ticket No that's since been superseded by a
        reschedule errors instead of silently loading the outdated
        original (points the user at the new PNR/Ticket No instead).
      - Searching by the ORIGINAL ticket's own S PNR/Airline PNR - which
        still validly identifies whichever passengers on it have NOT yet
        been rescheduled - returns only THOSE (partial reschedule: e.g.
        2 of 4 passengers rescheduled, searching the original S PNR
        correctly shows just the remaining 2, not the 2 that moved).
    Each returned passenger's own "line_id" is that line's own real id in
    WHICHEVER table currently holds its live data (the original
    TicketLine, or that specific RescheduleAirlineTicketLine) - the
    frontend uses source_reschedule_ticket_id (set only when the match
    came from a reschedule) to know which one to fetch full details from.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    s_pnr = (request.GET.get("s_pnr") or "").strip()
    airline_pnr = (request.GET.get("airline_pnr") or "").strip()
    ticket_no = (request.GET.get("ticket_no") or "").strip()
    if not (s_pnr or airline_pnr or ticket_no):
        return JsonResponse({"error": "Enter S PNR, Airline PNR or Ticket No to search."}, status=400)

    ticket = None
    matched_line_id = None
    matched_line = None
    resched_source = None       # RescheduleAirlineTicket, set when found via reschedule data
    resched_source_line = None  # RescheduleAirlineTicketLine, set only on an exact Ticket No match

    if ticket_no:
        line = TicketLine.objects.filter(ticket__company_id=company_id, ticket_no=ticket_no).select_related("ticket").first()
        if line:
            ticket = line.ticket
            matched_line_id = line.id
            matched_line = line
        else:
            rline = RescheduleAirlineTicketLine.objects.filter(
                reschedule_ticket__company_id=company_id, ticket_no=ticket_no
            ).select_related("reschedule_ticket", "original_ticket_line__ticket").first()
            if rline:
                resched_source_line = rline
                resched_source = rline.reschedule_ticket
                matched_line = rline.original_ticket_line
                matched_line_id = rline.id  # the reschedule's OWN id - cancellation loads this live record, not the stale original
                ticket = matched_line.ticket
    if not ticket and s_pnr:
        ticket = Ticket.objects.filter(company_id=company_id, booking_reference=s_pnr).first()
        if not ticket:
            rt = RescheduleAirlineTicket.objects.filter(company_id=company_id, booking_reference=s_pnr).select_related("original_ticket").first()
            if rt:
                resched_source = rt
                ticket = rt.original_ticket
    if not ticket and airline_pnr:
        ticket = Ticket.objects.filter(company_id=company_id, airline_pnr=airline_pnr).first()
        if not ticket:
            rt = RescheduleAirlineTicket.objects.filter(company_id=company_id, airline_pnr=airline_pnr).select_related("original_ticket").first()
            if rt:
                resched_source = rt
                ticket = rt.original_ticket

    if not ticket:
        return JsonResponse({"error": "No ticket found matching that S PNR / Airline PNR / Ticket No."}, status=404)

    # Exact Ticket No match on a line that's since been superseded by a
    # reschedule (any chain depth) - the stale original no longer
    # reflects this passenger's current state.
    already_rescheduled = (
        resched_source_line.rescheduled if resched_source_line is not None
        else (matched_line is not None and matched_line.rescheduled)
    )
    if already_rescheduled:
        return JsonResponse({
            "error": "This ticket has already been rescheduled - search using its new PNR/Ticket No instead."
        }, status=409)

    def split_sectors(l):
        pairs = [p.strip() for p in (l.sector or "").split(",") if p.strip()]
        flight_nos = (l.flight_no or "").split(",")
        classes = (l.travel_class or "").split(",")
        dates = [d.strip() for d in (l.travel_date or "").split(",")]
        return [{
            "sector": pairs[i],
            "flight_no": (flight_nos[i].strip() if i < len(flight_nos) else ""),
            "travel_class": (classes[i].strip() if i < len(classes) else ""),
            "travel_date": dates[i] if i < len(dates) else (dates[0] if len(dates) == 1 else ""),
        } for i in range(len(pairs))]

    # Partial passenger reschedule: a passenger/line that's already been
    # rescheduled (rescheduled=True) is excluded here rather than blocking
    # the whole invoice - other passengers who haven't been rescheduled
    # yet must still show up, with their own live data.
    # Already-cancelled passengers are excluded too - they can't be
    # cancelled a second time.
    if resched_source is not None:
        current_lines = list(resched_source.lines.filter(rescheduled=False, canceled=False))
    else:
        current_lines = [l for l in ticket.lines.all() if not l.rescheduled and not l.canceled]
    if not current_lines:
        return JsonResponse({
            "error": "No passenger on this booking is left to cancel - each one has already been cancelled or rescheduled (search a rescheduled passenger by their new PNR/Ticket No)."
        }, status=409)

    passengers = [{
        "line_id": l.id, "ticket_no": l.ticket_no, "pax_type": l.pax_type,
        "passenger_name": l.passenger_name, "sectors": split_sectors(l),
    } for l in current_lines]

    return JsonResponse({
        "ticket_id": ticket.id,
        "invoice_number": resched_source.invoice_number if resched_source is not None else ticket.invoice_number,
        "booking_reference": resched_source.booking_reference if resched_source is not None else ticket.booking_reference,
        "airline_pnr": resched_source.airline_pnr if resched_source is not None else ticket.airline_pnr,
        "matched_line_id": matched_line_id,
        "source_reschedule_ticket_id": resched_source.id if resched_source is not None else None,
        "passengers": passengers,
    })


CANCEL_LINE_FIELDS = TICKET_LINE_FIELDS

# Cancellation-only amounts persisted on Cancellation_Al_TicketLines (added
# 2026-10-07 for the Cancellation Journal Voucher) - never part of
# TICKET_LINE_FIELDS, so they're read off each raw request line separately.
# The 5 *_markup_reversal keys are the Markup Reversal popup's individual
# COMPONENT amounts (page-ticket-entry.js sets them on the passenger at Apply
# time), not the combined Customer/Supplier totals.
CANCEL_JV_LINE_FIELDS = [
    "supplier_penalty", "cancellation_penalty", "agent_penalty",
    "cust_markup_reversal", "cust_addl_markup_reversal", "cust_ssr_markup_reversal",
    "supp_markup_reversal", "supp_addl_markup_reversal",
]


# ============================================================
# Cancellation Journal Voucher (2026-10-07 explicit spec) - a SEPARATE JV
# per cancellation (JournalVoucher.category "AIRLINE_CANCELLATION", ALC-n),
# never touching the original booking's own JV or Booking/Reschedule's own
# formulas (JV_LINE_MAP/_compute_jv_lines/RESCHED_JV_LINE_MAP/
# _compute_reschedule_jv_lines/_fop_payment_lines are all untouched).
#
# JV-1 (Top-up + Cash)        = Main only
# JV-2 (Top-up + Own Card)    = Main + FOP leg: Supplier Cr / FOP card ledger Dr
# JV-3 (Top-up + Client Card) = Main + FOP leg: Supplier Cr / Customer Dr
# The Main portion is the SAME 31 lines in all three (rows 1-2 = Customer
# Credit / Supplier Debit, built in _compute_cancellation_jv_lines; rows
# 3-31 = CANCEL_JV_LINE_MAP below, in the spec's own order). Selection is
# driven by each cancellation line's own `fop` (anything other than "Own
# Card"/"Client Card" = no FOP leg, i.e. JV-1). Exact Dr/Cr direction as
# given in the spec - never flipped to force a balance.
#
# Rows 10 and 16 are DELIBERATELY the same ledger ("Supplier Cancellation
# Penalty A/c") on opposite sides - re-confirmed explicitly (2026-10-07,
# second pass) via the user's own Excel-sourced spec: "Supplier Cancellation
# Penalty A/c - DEBIT = Penalty Amount" AND "Supplier Cancellation Penalty
# A/c - CREDIT = Penalty Amount", both flagged IMPORTANT, with an explicit
# "do not rename the accounting fields" rule. An EARLIER pass briefly
# "corrected" this to Dr Supplier-side/Cr Consolidator-side (mirroring
# Reschedule's own Supplier/Consolidator Reschedule Penalty A/c pair,
# unifying the two field names) - that was a misreading of a separate,
# UI-label-only request ("Penalty Amount" instead of "Reschedule Penalty"/
# "Cancellation Penalty" as the on-screen label text) and has been reverted:
# Cancellation's own "Supplier Cancellation Penalty A/c" field is its own
# distinct Master Mapping entry, separate from Reschedule's "Supplier/
# Consolidator Reschedule Penalty A/c" - scoped to the Cancellation page
# only, Reschedule's own JV/mapping is untouched (RESCHED_JV_LINE_MAP keeps
# its original field names). Rows 15/27 are still two separate literal
# "Output IGST A/c" Credit rows, kept exactly as specified (unlike Booking/
# Reschedule, whose own Output GST rows are combined + state-split into
# CGST/SGST by a later, separate instruction for those two flows only).
#
# Each entry: (dr_cr, masters_category, field_name, amount_key) - same
# shape and same Master Mapping (masters_category, field_name) literals as
# JV_LINE_MAP/RESCHED_JV_LINE_MAP; the only field_name new to this module is
# ("Expenditure To Supplier", "Supplier Cancellation Penalty A/c").
# ============================================================
CANCEL_JV_LINE_MAP = [
    ("Debit", "Earnings From Supplier", "Commission A/c", "commission"),                                   # 3
    ("Credit", "GST and TDS", "Commission TDS A/c", "commission_tds"),                                     # 4
    ("Debit", "Expenditure To Supplier", "Supplier Markup A/c", "supp_markup"),                            # 5
    ("Debit", "Expenditure To Supplier", "Supplier Addl Markup A/c", "supp_addl_markup"),                  # 6
    ("Debit", "Expenditure To Supplier", "Supplier Service Fee A/c", "supp_service_fee"),                  # 7
    ("Debit", "Expenditure To Supplier", "Supplier Addl Service Fee A/c", "supp_addl_service_fee"),        # 8
    ("Debit", "GST and TDS", "Input IGST A/c", "supp_gst"),                                                # 9
    ("Debit", "Expenditure To Supplier", "Supplier Cancellation Penalty A/c", "cancellation_penalty"),      # 10
    ("Credit", "Earnings From Customer", "Consolidator Markup A/c", "supp_markup"),                        # 11
    ("Credit", "Earnings From Customer", "Consolidator Addl Markup A/c", "supp_addl_markup"),              # 12
    ("Credit", "Earnings From Customer", "Consolidator Service Fee A/c", "supp_service_fee"),              # 13
    ("Credit", "Earnings From Customer", "Consolidator Addl Service Fee A/c", "supp_addl_service_fee"),    # 14
    ("Credit", "GST and TDS", "Output IGST A/c", "supp_gst"),                                              # 15
    ("Credit", "Expenditure To Supplier", "Supplier Cancellation Penalty A/c", "cancellation_penalty"),     # 16
    ("Credit", "Expenditure To Supplier", "Supplier Markup A/c", "supp_markup_reversal"),                  # 17
    ("Credit", "Expenditure To Supplier", "Supplier Addl Markup A/c", "supp_addl_markup_reversal"),        # 18
    ("Debit", "Earnings From Customer", "Consolidator Markup A/c", "supp_markup_reversal"),                # 19
    ("Debit", "Earnings From Customer", "Consolidator Addl Markup A/c", "supp_addl_markup_reversal"),      # 20
    ("Credit", "Expenditure To Customer", "Discount A/c", "discount"),                                     # 21
    ("Debit", "GST and TDS", "Discount TDS A/c", "discount_tds"),                                          # 22
    ("Credit", "Earnings From Customer", "Markup A/c", "markup"),                                          # 23
    ("Credit", "Earnings From Customer", "Addl Markup A/c", "addl_markup"),                                # 24
    ("Credit", "Earnings From Customer", "Service Fee A/c", "service_fee"),                                # 25
    ("Credit", "Earnings From Customer", "Addl Service Fee A/c", "addl_service_fee"),                      # 26
    ("Credit", "GST and TDS", "Output IGST A/c", "gst"),                                                   # 27
    ("Credit", "Expenditure To Customer", "Agent Penalty A/c", "agent_penalty"),                           # 28
    ("Debit", "Earnings From Customer", "Markup A/c", "cust_markup_reversal"),                             # 29
    ("Debit", "Earnings From Customer", "Addl Markup A/c", "cust_addl_markup_reversal"),                   # 30
    ("Debit", "Earnings From Customer", "SSR Markup A/c", "cust_ssr_markup_reversal"),                     # 31
]


def _cancellation_line_amounts(l):
    """
    Every per-line amount the Cancellation JV needs, each rounded to 2
    decimals ONCE here (the computed ones - discount/TDS/GST/commission -
    can carry sub-paisa fractions). Every row of the JV (the two composite
    Customer/Supplier rows AND the individual mapped rows) is then built
    from these same rounded figures, so the entry's Debit = Credit identity
    holds exactly instead of drifting by a paisa from rounding each row's
    own unrounded sum independently.

    Customer (row 1) and Supplier (row 2) use the spec's exact formulas;
    "Customer/Supplier Markup Reversal" there are the component sums.
    """
    r2 = lambda v: round(float(v or 0), 2)
    a = {
        "supplier_cost": r2(l.supplier_cost),
        "supplier_penalty": r2(l.supplier_penalty),
        "cancellation_penalty": r2(l.cancellation_penalty),
        "agent_penalty": r2(l.agent_penalty),
        "commission": r2(l.computed_supp_commission),
        "commission_tds": r2(l.computed_supp_tds),
        "supp_markup": r2(l.supp_markup),
        "supp_addl_markup": r2(l.supp_addl_markup),
        "supp_service_fee": r2(l.supp_service_fee),
        "supp_addl_service_fee": r2(l.supp_addl_service_fee),
        "supp_gst": r2(l.computed_supp_gst),
        "discount": r2(l.computed_discount),
        "discount_tds": r2(l.computed_tds),
        "markup": r2(l.markup),
        "addl_markup": r2(l.addl_markup),
        "service_fee": r2(l.service_fee),
        "addl_service_fee": r2(l.addl_service_fee),
        "gst": r2(l.computed_gst),
        "cust_markup_reversal": r2(l.cust_markup_reversal),
        "cust_addl_markup_reversal": r2(l.cust_addl_markup_reversal),
        "cust_ssr_markup_reversal": r2(l.cust_ssr_markup_reversal),
        "supp_markup_reversal": r2(l.supp_markup_reversal),
        "supp_addl_markup_reversal": r2(l.supp_addl_markup_reversal),
    }
    cust_reversal = a["cust_markup_reversal"] + a["cust_addl_markup_reversal"] + a["cust_ssr_markup_reversal"]
    supp_reversal = a["supp_markup_reversal"] + a["supp_addl_markup_reversal"]
    # Row 1 - Customer (Credit)
    a["customer_amount"] = (
        a["supplier_cost"] - a["supplier_penalty"] - a["discount"] + a["discount_tds"]
        - a["markup"] - a["addl_markup"] - a["service_fee"] - a["addl_service_fee"]
        - a["agent_penalty"] - a["gst"]
        - a["supp_markup"] - a["supp_addl_markup"] - a["supp_service_fee"] - a["supp_addl_service_fee"]
        - a["supp_gst"] - a["cancellation_penalty"]
        + cust_reversal + supp_reversal
    )
    # Row 2 - Supplier (Debit); also the FOP leg's amount (JV-2/JV-3)
    a["supplier_amount"] = (
        a["supplier_cost"] - a["commission"] + a["commission_tds"] - a["supplier_penalty"]
        - a["supp_markup"] - a["supp_addl_markup"] - a["supp_service_fee"] - a["supp_addl_service_fee"]
        - a["supp_gst"] - a["cancellation_penalty"]
        + supp_reversal
    )
    return a


def _cancellation_jv_type(lines):
    """JV-1/JV-2/JV-3 label from the lines' own FOP (unknown FOP -> JV-1)."""
    kinds = {{"Own Card": "JV-2", "Client Card": "JV-3"}.get(l.fop, "JV-1") for l in lines}
    return kinds.pop() if len(kinds) == 1 else "Mixed (" + "/".join(sorted(kinds)) + ")"


def _compute_cancellation_jv_lines(cancel_ticket, lines, mapping_cache=None, company_state=None):
    """
    The Main Cancellation JV (identical for JV-1/JV-2/JV-3) - same
    structure/return shape as _compute_jv_lines/_compute_reschedule_jv_lines:
    (accounts, narration, total_debit, total_credit), accounts being
    {"role","ledger_id","ledger_name","debit","credit"} rows. Customer
    resolves to the cancellation's own customer Ledger, Supplier is grouped
    per line's own supplier Ledger (one row per distinct supplier), every
    other row resolves via Master Mapping (product_type "Airline") through
    the same mapping_cache convention (seeded by _jv_prep).

    company_state is accepted only for signature parity with the Booking/
    Reschedule functions - the spec posts both Output IGST rows literally,
    so no same-state CGST/SGST split is applied here.

    Totals here are the MAIN portion only; the caller adds
    _cancellation_fop_payment_lines' leg on top before the balance check.
    """
    per_line = [_cancellation_line_amounts(l) for l in lines]
    role_keys = {key for _, _, _, key in CANCEL_JV_LINE_MAP}
    role_amounts = {key: sum(a[key] for a in per_line) for key in role_keys}
    customer_total = sum(a["customer_amount"] for a in per_line)

    supplier_groups = {}
    for l, a in zip(lines, per_line):
        group = supplier_groups.setdefault(l.supplier_id, {"ledger": l.supplier, "amount": 0.0})
        group["amount"] += a["supplier_amount"]

    def dr_cr_amounts(dr_cr, amount):
        amount = round(amount, 2)
        return (amount, 0) if dr_cr == "Debit" else (0, amount)

    if mapping_cache is None:
        mapping_cache = {}

    def mapped_ledger(masters_category, field_name):
        key = (cancel_ticket.company_id, masters_category, field_name)
        if key not in mapping_cache:
            m = MasterMapping.objects.filter(
                company_id=cancel_ticket.company_id, product_type="Airline",
                masters_category=masters_category, field_name=field_name,
            ).select_related("ledger").first()
            mapping_cache[key] = (
                (m.ledger_id, m.ledger.name) if m
                else (None, f"{field_name} (not mapped in Master Mapping)")
            )
        return mapping_cache[key]

    # Row 1 - Customer (Credit)
    debit, credit = dr_cr_amounts("Credit", customer_total)
    accounts = [{"role": "customer", "ledger_id": cancel_ticket.customer_id,
                 "ledger_name": cancel_ticket.customer.name, "debit": debit, "credit": credit}]
    # Row 2 - Supplier (Debit), one row per distinct supplier
    for g in supplier_groups.values():
        debit, credit = dr_cr_amounts("Debit", g["amount"])
        ledger = g["ledger"]
        accounts.append({"role": "supplier", "ledger_id": ledger.id if ledger else None,
                         "ledger_name": ledger.name if ledger else "— (no supplier selected)",
                         "debit": debit, "credit": credit})
    # Rows 3-31
    for dr_cr, masters_category, field_name, amount_key in CANCEL_JV_LINE_MAP:
        debit, credit = dr_cr_amounts(dr_cr, role_amounts[amount_key])
        ledger_id, ledger_name = mapped_ledger(masters_category, field_name)
        accounts.append({"role": field_name, "ledger_id": ledger_id, "ledger_name": ledger_name,
                         "debit": debit, "credit": credit})

    narration = " / ".join(filter(None, [
        "Cancellation", cancel_ticket.cancellation_reference, cancel_ticket.airline_pnr,
        lines[0].ticket_no if lines else None,
    ]))[:250]
    total_debit = round(sum(a["debit"] for a in accounts), 2)
    total_credit = round(sum(a["credit"] for a in accounts), 2)
    return accounts, narration, total_debit, total_credit


def _cancellation_fop_payment_lines(cancel_ticket, lines):
    """
    The FOP Payment leg of JV-2 (Own Card) / JV-3 (Client Card) - same
    (ledger_id, debit, credit) tuple shape as _fop_payment_lines, but its
    own separate function (and the spec's own direction, which is the
    reverse of Booking's: Supplier is CREDITED here). Per line, by that
    line's own fop:
      Own Card    -> Supplier Cr + FOP card's own ledger (FOP Master, by the
                     line's card_number) Dr, both = row 2's Supplier formula
      Client Card -> Supplier Cr + Customer Dr, both = row 2's Supplier
                     formula (literal spec - the Supplier amount, not the
                     Customer one)
      Cash / anything else -> no FOP leg (JV-1).
    Raises ValueError (clean 400 message) if an Own Card line's card isn't
    in FOP Master - posting the Supplier credit without its card debit
    would leave the JV unbalanced.
    """
    supplier_credit, counterpart_debit = {}, {}
    card_cache = {}
    for l in lines:
        if l.fop not in ("Own Card", "Client Card"):
            continue
        amount = _cancellation_line_amounts(l)["supplier_amount"]
        supplier_credit[l.supplier_id] = supplier_credit.get(l.supplier_id, 0.0) + amount
        if l.fop == "Own Card":
            card_number = l.card_number or ""
            if card_number not in card_cache:
                card_cache[card_number] = sp_client.fop_master_get_by_card_number(cancel_ticket.company_id, card_number)
            card = card_cache[card_number]
            if not card or not card.get("card_master_ledger_id"):
                raise ValueError(
                    f"Ticket No. {l.ticket_no}: FOP card \"{card_number}\" has no Card Master ledger in FOP Master - "
                    "the Own Card FOP leg of the Cancellation JV can't be posted."
                )
            ledger_id = card["card_master_ledger_id"]
        else:
            ledger_id = cancel_ticket.customer_id
        counterpart_debit[ledger_id] = counterpart_debit.get(ledger_id, 0.0) + amount

    result = [(ledger_id, 0, round(amt, 2)) for ledger_id, amt in supplier_credit.items()]
    result += [(ledger_id, round(amt, 2), 0) for ledger_id, amt in counterpart_debit.items()]
    return result


def _post_cancellation_jv(company_id, cancel_ticket, line_objs):
    """
    Main JV + FOP leg -> (narration, total_debit, total_credit, jv_type,
    error). Totals cover the WHOLE posted entry (Main + FOP leg together) -
    unlike Booking, whose stored total is Main-only - since the balance rule
    applies to the full Cancellation JV. error is a ready 400 message (FOP
    card missing, or Debit <> Credit beyond 0.01) - the caller must then
    write NOTHING (no cancellation header/lines either), per the spec.
    """
    mapping_cache, company_state = _jv_prep(company_id)
    _, narration, total_debit, total_credit = _compute_cancellation_jv_lines(
        cancel_ticket, line_objs, mapping_cache, company_state,
    )
    try:
        fop_rows = _cancellation_fop_payment_lines(cancel_ticket, line_objs)
    except ValueError as err:
        return narration, None, None, None, str(err)
    total_debit = round(total_debit + sum(d for _, d, _ in fop_rows), 2)
    total_credit = round(total_credit + sum(c for _, _, c in fop_rows), 2)
    jv_type = _cancellation_jv_type(line_objs)
    if abs(total_debit - total_credit) > 0.01:
        return narration, total_debit, total_credit, jv_type, (
            f"Cancellation Journal Voucher ({jv_type}) does not balance: Total Debit {total_debit:.2f} "
            f"≠ Total Credit {total_credit:.2f}. Nothing was saved - correct the fare/penalty/markup "
            "fields and save again."
        )
    return narration, total_debit, total_credit, jv_type, None


def _cancellation_line_obj(cancel_ticket, line_values, supplier):
    """Unsaved CancellationAirlineTicketLine (pure value object, never saved) from a plain field dict."""
    model_fields = {f.name for f in CancellationAirlineTicketLine._meta.concrete_fields}
    kwargs = {k: v for k, v in line_values.items() if k in model_fields and k not in ("id", "supplier", "cancellation_ticket")}
    return CancellationAirlineTicketLine(cancellation_ticket=cancel_ticket, supplier=supplier, **kwargs)


def cancellation_jv_preview(request, cancellation_id):
    """
    GET /api/cancellation-tickets/<id>/jv-preview/?company_id=1
    Mirrors ticket_jv_preview/reschedule_jv_preview exactly, for an
    ALREADY-SAVED Cancellation (the "Journal Voucher" button on a saved/
    edit-mode Cancellation) - always recomputes LIVE from the saved lines
    via _compute_cancellation_jv_lines, never reads a stored snapshot
    (there is none - accounts are never persisted, same as Booking/
    Reschedule). `accounts`/total_debit/total_credit here are the MAIN
    portion only (rows 1-31) - the FOP leg (JV-2 Own Card/JV-3 Client Card)
    is rendered as its own separate tab by the frontend, exactly like
    Reschedule's own jv-preview/renderRescheduleFopPaymentTab, derived from
    these same `accounts`' "supplier" role rows rather than a second
    backend round-trip.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    header, lines = sp_client.cancellation_ticket_get(cancellation_id, company_id)
    if not header:
        return JsonResponse({"error": "Cancellation not found."}, status=404)
    if not lines:
        return JsonResponse({"error": "This cancellation has no lines to build a voucher from."}, status=400)

    cancel_proxy = CancellationAirlineTicket(
        company_id=company_id,
        customer=Ledger(id=header["customer_ledger_id"], name=header["customer_name"]),
        cancellation_reference=header.get("cancellation_reference"), airline_pnr=header.get("airline_pnr"),
    )
    line_objs = []
    for l in lines:
        merged = dict(l)
        for f in TICKET_LINE_NUMERIC_FIELDS | set(CANCEL_JV_LINE_FIELDS):
            merged[f] = _safe_decimal(merged.get(f))
        line_supplier = (
            Ledger(id=l["supplier_ledger_id"], name=l.get("supplier_name"))
            if l.get("supplier_ledger_id") else None
        )
        line_objs.append(_cancellation_line_obj(cancel_proxy, merged, line_supplier))

    mapping_cache, company_state = _jv_prep(company_id)
    accounts, narration, total_debit, total_credit = _compute_cancellation_jv_lines(cancel_proxy, line_objs, mapping_cache, company_state)

    voucher = JournalVoucher.objects.filter(source_cancellation_ticket_id=cancellation_id).only("id", "voucher_no").first()

    return JsonResponse({
        "posted": voucher is not None,
        "voucher_id": voucher.id if voucher else None,
        "voucher_no": voucher.voucher_no if voucher else None,
        "branch_name": header.get("branch_name") or "Chennai Branch",
        "voucher_type": "Tax Invoice",
        "voucher_date": header["invoice_date"].isoformat() if header.get("invoice_date") else None,
        "narration": narration,
        "accounts": accounts,
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "fop": (lines[0].get("fop") if lines else None),
    })


@csrf_exempt
def cancellation_jv_preview_draft(request):
    """
    POST /api/cancellation-tickets/jv-preview-draft/
    Same body shape as cancellation-tickets/create/ - lets the Cancellation
    form show a live JV preview before Save Cancellation, same pattern as
    ticket_jv_preview_draft/reschedule_jv_preview_draft. Builds UNSAVED
    CancellationAirlineTicket/CancellationAirlineTicketLine instances
    (never .save()'d) through the exact same _compute_cancellation_jv_lines
    used by the real save - the preview always matches what Save
    Cancellation would actually post (Main portion; see cancellation_jv_
    preview's own docstring for why the FOP leg isn't included here).

    Looser than cancellation_ticket_create on purpose (same reasoning as
    ticket_jv_preview_draft) - a line mid-edit without a valid supplier
    just posts that line's Supplier row against no ledger rather than
    rejecting the whole preview.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    company_id = body.get("company_id")
    lines_in = body.get("lines") or []
    if not company_id or not lines_in:
        return JsonResponse({"error": "company_id and at least one line are required."}, status=400)

    customer = None
    if body.get("customer_name"):
        customer = Ledger.objects.filter(company_id=company_id, name=body["customer_name"], ledger_category="DEBTOR").first()
    if customer is None:
        return JsonResponse({"error": "Pick a Customer before previewing the JV."}, status=400)

    cancel_proxy = CancellationAirlineTicket(
        company_id=company_id, customer=customer,
        cancellation_reference=body.get("cancellation_reference"), airline_pnr=body.get("airline_pnr"),
    )

    line_objs = []
    for line_in in lines_in:
        line_kwargs = {f: line_in[f] for f in CANCEL_LINE_FIELDS if f in line_in}
        for f in TICKET_LINE_NUMERIC_FIELDS:
            if f in line_kwargs:
                line_kwargs[f] = _safe_decimal(line_kwargs[f])
        for f in CANCEL_JV_LINE_FIELDS:
            line_kwargs[f] = _safe_decimal(line_in.get(f))

        line_supplier = None
        if line_in.get("supplier_name"):
            line_supplier = Ledger.objects.filter(company_id=company_id, name=line_in["supplier_name"], ledger_category="CREDITOR").first()

        line_objs.append(_cancellation_line_obj(cancel_proxy, line_kwargs, line_supplier))

    mapping_cache, company_state = _jv_prep(company_id)
    accounts, narration, total_debit, total_credit = _compute_cancellation_jv_lines(cancel_proxy, line_objs, mapping_cache, company_state)

    voucher_date = _parse_date(body.get("cancellation_ref_date")) or _parse_date(body.get("invoice_date"))
    return JsonResponse({
        "posted": False, "voucher_id": None, "voucher_no": None,
        "branch_name": "Chennai Branch",
        "voucher_type": "Tax Invoice",
        "voucher_date": voucher_date.isoformat() if voucher_date else None,
        "narration": narration,
        "accounts": accounts,
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "fop": (lines_in[0].get("fop") if lines_in else None),
    })


def cancellation_tickets_list(request):
    """
    GET /api/cancellation-tickets/list/?company_id=1
    One row per cancelled line, flat shape matching the generic Find
    modal's results table - same convention as reschedule_tickets_list.
    Used so Cancellation's own "Find" popup (page-ticket-entry.js,
    cancellationMode branch of runFindSearch) shows only cancelled
    tickets instead of the full tickets list (2026-10-06 request).
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    rows = [{
        "id": l["id"], "cancellation_ticket_id": l["cancellation_ticket_id"],
        "invoice_number": l["invoice_number"], "booking_reference": l["booking_reference"],
        "airline_pnr": l["airline_pnr"], "gds_pnr": l["gds_pnr"],
        "ticket_no": l["ticket_no"], "passenger_name": l["passenger_name"],
        "total_billed": float(l["total_billed"]),
    } for l in sp_client.cancellation_tickets_list(company_id)]
    return JsonResponse(rows, safe=False)


def cancellation_fare_totals(request):
    """
    POST /api/cancellation-tickets/fare-totals/
    Body: { company_id, lines: [ { original_ticket_line_id, reschedule_line_id }, ... ] }

    Cancellation's own "Base Fare & Tax Components" card must show the
    CUMULATIVE fare across the whole chain being cancelled (original
    booking + every reschedule up to and including the one actually
    picked), not just the one record's own standalone figures - e.g.
    cancelling a 2nd reschedule shows Booking's Basic Fare + Reschedule
    1's own + Reschedule 2's own, summed. reschedule_line_id (when the
    passenger being cancelled currently lives on a reschedule, not the
    true original) is that RescheduleAirlineTicketLine's OWN id, not its
    parent link - _resolve_parent_chain_line walks its own
    based_on_reschedule_line chain backward from there, same cumulative
    math already proven for Reschedule's own "Parent PNR Details" (see
    reschedule_parent_chain_line). Supplier Penalty is deliberately
    excluded from this auto-fetch (2026-10-06 decision) - always
    returned as 0 regardless of its own chain value, never summed.

    Customer Discount and Supplier Commission (amount + TDS) get the
    same cumulative-chain treatment, reusing the exact fields
    _resolve_parent_chain_line already computes for this (disc_value/
    disc_type always "Flat" + tds_amount when chained, the line's own
    real values when not chained). tds_amount/supp_tds_amount come back
    null when there's no chain - the frontend then falls back to its
    normal live Amount x Rate derivation instead of forcing an override.

    markup/addl_markup/ssr_markup/supp_markup/supp_addl_markup are the
    same cumulative chain totals too, but NOT shown directly on any
    field (those inputs are reset to 0 for Cancellation - a fresh
    provisional entry, see enterCancellationMode) - they're informational
    only, feeding the Markup Reversal popup's checkbox amounts so the
    user can pick which ones to reverse.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    company_id = body.get("company_id")
    lines_in = body.get("lines") or []
    if not company_id or not lines_in:
        return JsonResponse({"error": "company_id and lines are required"}, status=400)

    original_ids = [l.get("original_ticket_line_id") for l in lines_in if l.get("original_ticket_line_id")]
    originals = TicketLine.objects.filter(id__in=original_ids, ticket__company_id=company_id).in_bulk()

    reschedule_ids = [l.get("reschedule_line_id") for l in lines_in if l.get("reschedule_line_id")]
    rescheds = (
        RescheduleAirlineTicketLine.objects.filter(id__in=reschedule_ids, reschedule_ticket__company_id=company_id).in_bulk()
        if reschedule_ids else {}
    )

    totals = []
    for line_in in lines_in:
        oid = line_in.get("original_ticket_line_id")
        rid = line_in.get("reschedule_line_id")
        original_line = originals.get(oid)
        if original_line is None:
            totals.append({"original_ticket_line_id": oid, "error": "Original ticket line not found."})
            continue
        based_on = rescheds.get(rid) if rid else None
        chain = _resolve_parent_chain_line(original_line, based_on)
        totals.append({
            "original_ticket_line_id": oid,
            "basic_fare": chain["basic_fare"], "yq": chain["yq"], "yr": chain["yr"], "k3_tax": chain["k3_tax"],
            "tax_others": chain["tax_others"], "seat": chain["seat"], "meal": chain["meal"], "baggage": chain["baggage"],
            "other_ssr": chain["other_ssr"],
            "supplier_penalty": 0,
            "disc_on": chain["disc_on"], "disc_type": chain["disc_type"], "disc_value": chain["disc_value"],
            "tds_per": chain["tds_per"], "tds_amount": chain["tds_amount"],
            "supp_comm_on": chain["supp_comm_on"], "supp_comm_type": chain["supp_comm_type"], "supp_comm_value": chain["supp_comm_value"],
            "supp_tds_per": chain["supp_tds_per"], "supp_tds_amount": chain["supp_tds_amount"],
            "markup": chain["markup"], "addl_markup": chain["addl_markup"], "ssr_markup": chain["ssr_markup"],
            "supp_markup": chain["supp_markup"], "supp_addl_markup": chain["supp_addl_markup"],
        })

    return JsonResponse({"totals": totals})


@csrf_exempt
@transaction.atomic
def cancellation_ticket_create(request):
    """
    POST /api/cancellation-tickets/create/
    Body: { company_id, original_ticket_id, source_reschedule_ticket_id
            (optional - set when ticket_lookup_for_cancellation matched a
            passenger whose live data currently lives on a reschedule, not
            the true original ticket), customer_name, supplier_name,
            ...header fields (same shape as tickets/create/'s
            TICKET_HEADER_FIELDS, except cancellation_reference/
            cancellation_ref_date instead of booking_reference/
            booking_ref_date), lines: [ {...TICKET_LINE_FIELDS, line_id},
            ... ] }

    Persists the Cancellation record (header + lines) into
    Cancellation_AL_Tickets/Cancellation_Al_TicketLines, AND posts this
    cancellation's own separate Journal Voucher (2026-10-07 - see
    _compute_cancellation_jv_lines/_post_cancellation_jv), category
    "AIRLINE_CANCELLATION" - computed and balance-checked (Debit=Credit)
    BEFORE anything is written; the whole request is rejected with a 400 if
    the JV doesn't balance, same as Tickets/Reschedule's own auto-posted JV
    but with its own separate formula/ledgers. Each line's own "line_id" is
    whichever row ticket_lookup_for_cancellation actually
    matched (a real TicketLine id normally, or a
    RescheduleAirlineTicketLine id when the passenger's live data came
    from a reschedule instead) - resolved back to the TRUE original
    TicketLine id (original_ticket_line_id) before saving, same hop
    that lookup endpoint's own "matched_line" already makes for display.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    company_id = body.get("company_id")
    original_ticket_id = body.get("original_ticket_id")
    source_reschedule_ticket_id = body.get("source_reschedule_ticket_id")
    lines_in = body.get("lines") or []
    if not company_id or not original_ticket_id or not body.get("customer_name") or not body.get("invoice_number") \
            or not body.get("cancellation_reference") or not lines_in:
        return JsonResponse({
            "error": "company_id, original_ticket_id, customer_name, invoice_number, cancellation_reference and at least one line are required."
        }, status=400)

    customer_row = sp_client.ledger_get_by_name(company_id, body["customer_name"], "DEBTOR")
    if not customer_row:
        return JsonResponse({"error": f"\"{body['customer_name']}\" is not a real customer ledger (Sundry Debtors)."}, status=400)

    if body.get("supplier_name") and not sp_client.ledger_get_by_name(company_id, body["supplier_name"], "CREDITOR"):
        return JsonResponse({"error": f"\"{body['supplier_name']}\" is not a real supplier ledger (Sundry Creditors)."}, status=400)

    # Pure in-memory value object (never queried/saved) feeding the
    # Cancellation Journal Voucher computation below - only the fields
    # _compute_cancellation_jv_lines/_cancellation_fop_payment_lines actually
    # read (company_id, customer, cancellation_reference, airline_pnr) need
    # to be real.
    cancel_proxy = CancellationAirlineTicket(
        company_id=company_id, customer=Ledger(id=customer_row["id"], name=customer_row["name"]),
        cancellation_reference=body.get("cancellation_reference"), airline_pnr=body.get("airline_pnr"),
    )

    # Resolve each line's TRUE original TicketLine id. A straight pass-
    # through normally; one hop through RescheduleAirlineTicketLine when
    # this cancellation was raised against an already-rescheduled
    # passenger (source_reschedule_ticket_id set).
    original_id_by_line_id = {}
    if source_reschedule_ticket_id:
        reschedule_line_ids = [l.get("line_id") for l in lines_in if l.get("line_id")]
        original_id_by_line_id = sp_client.reschedule_resolve_original_line_ids(reschedule_line_ids)

    lines_json, line_objs = [], []
    for line_in in lines_in:
        line_id = line_in.get("line_id")
        if source_reschedule_ticket_id:
            original_ticket_line_id = original_id_by_line_id.get(line_id)
            if not original_ticket_line_id:
                return JsonResponse({
                    "error": f"Could not resolve the original ticket line for \"{line_in.get('ticket_no', '?')}\" - try the lookup again."
                }, status=400)
        else:
            original_ticket_line_id = line_id

        line_kwargs = {f: line_in[f] for f in CANCEL_LINE_FIELDS if f in line_in}
        for f in TICKET_LINE_NUMERIC_FIELDS:
            line_kwargs[f] = _safe_decimal(line_kwargs.get(f))
        line_kwargs.setdefault("pax_type", "Adult")
        line_kwargs.setdefault("status", "ISSUED")
        # Cancellation JV-only amounts (2026-10-07) - never part of
        # CANCEL_LINE_FIELDS/TICKET_LINE_FIELDS, read off the raw line dict
        # separately. See CANCEL_JV_LINE_FIELDS.
        for f in CANCEL_JV_LINE_FIELDS:
            line_kwargs[f] = _safe_decimal(line_in.get(f))

        supplier_name = line_in.get("supplier_name")
        line_supplier = None
        if supplier_name:
            supp_row = sp_client.ledger_get_by_name(company_id, supplier_name, "CREDITOR")
            if not supp_row:
                return JsonResponse({
                    "error": f"\"{supplier_name}\" (Ticket No. {line_in.get('ticket_no', '?')}) is not a real supplier ledger (Sundry Creditors)."
                }, status=400)
            line_supplier = Ledger(id=supp_row["id"], name=supp_row["name"])

        line_json = dict(line_kwargs)
        line_json["total_billed"] = _safe_decimal(line_in.get("total_billed"))
        line_json["supplier_name"] = supplier_name
        line_json["original_ticket_line_id"] = original_ticket_line_id
        # line_id IS the RescheduleAirlineTicketLine's own id in this case
        # (ticket_lookup_for_cancellation's "matched_line_id" convention) -
        # carried through so the SP can also flip THAT specific reschedule
        # line's own `canceled` flag, not just the true original's.
        line_json["reschedule_line_id"] = line_id if source_reschedule_ticket_id else None
        lines_json.append(line_json)
        line_objs.append(_cancellation_line_obj(cancel_proxy, line_kwargs, line_supplier))

    header_fields = {f: body[f] for f in TICKET_HEADER_FIELDS if f in body and f not in ("booking_reference", "booking_ref_date")}
    header_fields["invoice_date"] = _parse_date(header_fields.get("invoice_date"))
    header_fields["cancellation_reference"] = body.get("cancellation_reference")
    header_fields["cancellation_ref_date"] = _parse_date(body.get("cancellation_ref_date"))
    header_fields["supplier_name"] = body.get("supplier_name")
    if "roe" in header_fields:
        header_fields["roe"] = _safe_decimal(header_fields["roe"], default=1)

    # Cancellation Journal Voucher (2026-10-07) - computed BEFORE the actual
    # save so an unbalanced/invalid JV rejects the WHOLE cancellation
    # (header+lines+JV together), never just the JV on its own.
    jv_narration, jv_total_debit, jv_total_credit, jv_type, jv_error = _post_cancellation_jv(company_id, cancel_proxy, line_objs)
    if jv_error:
        return JsonResponse({"error": jv_error}, status=400)

    try:
        result = sp_client.cancellation_ticket_save(
            company_id, original_ticket_id, body["customer_name"], header_fields, lines_json,
            jv_narration, jv_total_debit, jv_total_credit,
        )
    except sp_client.StoredProcedureError as err:
        msg = str(err)
        status = 404 if "not found" in msg else (409 if "already" in msg else 400)
        return JsonResponse({"error": msg}, status=status)

    return JsonResponse({
        "id": result["id"], "line_ids": result["line_ids"],
        "message": "Cancellation saved.",
    }, status=201)


# Only the fields that are actually editable once a Cancellation is saved -
# the SAME subset editable at creation time (Base Fare & Tax Components,
# Customer Discount, Supplier Commission, Markup, Service Fee). Deliberately
# excludes airline_code/ticket_no/passenger_name/etc. (passenger identity
# fields - never change after the fact) and the Cancellation JV's own
# penalty/Markup Reversal amounts (CANCEL_JV_LINE_FIELDS) - not editable
# through this endpoint yet, so an update's recomputed JV reuses whatever
# was already saved for those 8 fields (see cancellation_ticket_update).
CANCEL_UPDATE_LINE_FIELDS = [
    "basic_fare", "yq", "yr", "k3_tax", "tax_others", "seat", "meal", "baggage", "other_ssr",
    "disc_on", "disc_type", "disc_value", "tds_per",
    "markup", "addl_markup", "service_fee", "addl_service_fee",
    "supp_comm_on", "supp_comm_type", "supp_comm_value", "supp_tds_per",
    "supp_markup", "supp_addl_markup", "supp_service_fee", "supp_addl_service_fee",
]
CANCEL_UPDATE_LINE_NUMERIC_FIELDS = {
    "basic_fare", "yq", "yr", "k3_tax", "tax_others", "seat", "meal", "baggage", "other_ssr",
    "disc_value", "tds_per", "markup", "addl_markup", "service_fee", "addl_service_fee",
    "supp_comm_value", "supp_tds_per", "supp_markup", "supp_addl_markup", "supp_service_fee", "supp_addl_service_fee",
}


@csrf_exempt
@transaction.atomic
def cancellation_ticket_update(request, cancellation_id):
    """
    POST /api/cancellation-tickets/<id>/update/
    Body: { company_id, invoice_date, invoice_type, user_name, payment_mode,
            payment_gateway_ref, cancellation_reference, cancellation_ref_date,
            lines: [ {id, ...CANCEL_UPDATE_LINE_FIELDS}, ... ] }

    Edits the SAME fields that were editable when this Cancellation was
    first created (2026-10-06 follow-up - "Add edit option in
    cancellation"). Each line is matched by its own already-saved
    Cancellation_Al_TicketLines id (body's "id", NOT original_ticket_line_id -
    nothing about which lines/passengers exist is changing here).

    Also recomputes and re-posts this cancellation's own Journal Voucher in
    place (2026-10-07) - the edited CANCEL_UPDATE_LINE_FIELDS are merged on
    top of each line's already-saved full data (fetched fresh via GET_LINES;
    ticket_no/fop/card_number/supplier and the 8 CANCEL_JV_LINE_FIELDS
    amounts aren't editable through this endpoint yet, so they're carried
    over unchanged from what's already saved) before recomputing, same
    balance-checked-before-write rule as creation - the whole update is
    rejected with a 400 if the recomputed JV doesn't balance.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    company_id = body.get("company_id")
    lines_in = body.get("lines") or []
    if not company_id or not lines_in:
        return JsonResponse({"error": "company_id and at least one line are required."}, status=400)

    header_fields = {
        "invoice_number": body.get("invoice_number"),
        "invoice_date": _parse_date(body.get("invoice_date")),
        "invoice_type": body.get("invoice_type"),
        "user_name": body.get("user_name"),
        "payment_mode": body.get("payment_mode"),
        "payment_gateway_ref": body.get("payment_gateway_ref"),
        "cancellation_reference": body.get("cancellation_reference"),
        "cancellation_ref_date": _parse_date(body.get("cancellation_ref_date")),
    }

    saved_header, saved_lines = sp_client.cancellation_ticket_get(cancellation_id, company_id)
    if not saved_header:
        return JsonResponse({"error": "Cancellation not found."}, status=404)
    saved_lines_by_id = {l["id"]: l for l in (saved_lines or [])}

    # Pure in-memory value object for the JV recompute below - same
    # reasoning as cancellation_ticket_create's own cancel_proxy.
    cancel_proxy = CancellationAirlineTicket(
        company_id=company_id,
        customer=Ledger(id=saved_header["customer_ledger_id"], name=saved_header["customer_name"]),
        cancellation_reference=header_fields.get("cancellation_reference") or saved_header["cancellation_reference"],
        airline_pnr=saved_header.get("airline_pnr"),
    )

    lines_json, line_objs = [], []
    for line_in in lines_in:
        line_id = line_in.get("id")
        if not line_id:
            return JsonResponse({"error": "Each line must carry its own saved id."}, status=400)
        saved_line = saved_lines_by_id.get(line_id)
        if not saved_line:
            return JsonResponse({"error": f"Line id {line_id} does not belong to this cancellation."}, status=400)

        line_kwargs = {f: line_in.get(f) for f in CANCEL_UPDATE_LINE_FIELDS}
        for f in CANCEL_UPDATE_LINE_NUMERIC_FIELDS:
            line_kwargs[f] = _safe_decimal(line_kwargs.get(f))
        line_kwargs["id"] = line_id
        lines_json.append(line_kwargs)

        # The edited fields on top of this line's already-saved full state
        # (ticket_no/fop/card_number/supplier/penalty/Markup Reversal amounts
        # are not editable here - carried over as-saved) so the JV reflects
        # the TRUE post-edit values.
        merged = dict(saved_line)
        merged.update(line_kwargs)
        # Every numeric field the computed properties touch must end up a
        # plain float, not whatever type it arrived as (pyodbc returns real
        # decimal.Decimal for DB columns) - CANCEL_UPDATE_LINE_NUMERIC_FIELDS
        # alone isn't enough here, since fields like supp_gst_pct aren't
        # editable but ARE read by computed_supp_gst, and Decimal * float
        # raises TypeError. _cancellation_line_obj's own CREATE-path
        # counterpart avoids this by casting the full TICKET_LINE_NUMERIC_FIELDS
        # set regardless of what the request actually sent.
        for f in TICKET_LINE_NUMERIC_FIELDS | set(CANCEL_JV_LINE_FIELDS):
            merged[f] = _safe_decimal(merged.get(f))
        line_supplier = (
            Ledger(id=saved_line["supplier_ledger_id"], name=saved_line.get("supplier_name"))
            if saved_line.get("supplier_ledger_id") else None
        )
        line_objs.append(_cancellation_line_obj(cancel_proxy, merged, line_supplier))

    jv_narration, jv_total_debit, jv_total_credit, jv_type, jv_error = _post_cancellation_jv(company_id, cancel_proxy, line_objs)
    if jv_error:
        return JsonResponse({"error": jv_error}, status=400)

    try:
        result = sp_client.cancellation_ticket_update(
            cancellation_id, company_id, header_fields, lines_json,
            jv_narration, jv_total_debit, jv_total_credit,
        )
    except sp_client.StoredProcedureError as err:
        msg = str(err)
        status = 404 if "not found" in msg else (409 if "already" in msg else 400)
        return JsonResponse({"error": msg}, status=status)

    return JsonResponse({"id": result["id"], "message": "Cancellation updated."})


def cancellation_ticket_detail(request, cancellation_id):
    """GET /api/cancellation-tickets/<id>/?company_id=1 - one saved Cancellation's header + lines."""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    header, lines = sp_client.cancellation_ticket_get(cancellation_id, company_id)
    if not header:
        return JsonResponse({"error": "Cancellation not found."}, status=404)

    return JsonResponse({
        "id": header["id"], "original_ticket_id": header["original_ticket_id"],
        "invoice_number": header["invoice_number"],
        "invoice_date": header["invoice_date"].isoformat() if header["invoice_date"] else None,
        "invoice_type": header["invoice_type"], "booking_mode": header["booking_mode"], "booking_type": header["booking_type"],
        "booking_status": header["booking_status"], "customer_name": header["customer_name"], "travel_type": header["travel_type"],
        "user_name": header["user_name"], "currency": header["currency"], "roe": float(header["roe"]),
        "booking_given_by": header["booking_given_by"],
        "cancellation_reference": header["cancellation_reference"],
        "cancellation_ref_date": header["cancellation_ref_date"].isoformat() if header["cancellation_ref_date"] else None,
        "airline_pnr": header["airline_pnr"], "gds_pnr": header["gds_pnr"], "supplier_name": header["supplier_name"],
        "office_id": header["office_id"], "payment_mode": header["payment_mode"], "payment_gateway_ref": header["payment_gateway_ref"],
        "airline_category": header["airline_category"], "branch_name": header["branch_name"],
        "lines": [{
            "id": l["id"], "original_ticket_line_id": l["original_ticket_line_id"],
            "airline_code": l["airline_code"], "airline_name": l["airline_name"], "airline_category": l["airline_category"],
            "flight_no": l["flight_no"], "ticket_no": l["ticket_no"], "passenger_name": l["passenger_name"], "pax_type": l["pax_type"],
            "sector": l["sector"], "travel_date": l["travel_date"], "cabin": l["cabin"], "travel_class": l["travel_class"], "fare_type": l["fare_type"],
            "basic_fare": float(l["basic_fare"]), "yq": float(l["yq"]), "yr": float(l["yr"]), "k3_tax": float(l["k3_tax"]),
            "tax_others": float(l["tax_others"]), "seat": float(l["seat"]), "meal": float(l["meal"]), "baggage": float(l["baggage"]),
            "other_ssr": float(l["other_ssr"]), "disc_on": l["disc_on"], "disc_type": l["disc_type"], "disc_value": float(l["disc_value"]),
            "tds_per": float(l["tds_per"]), "pg_charges": float(l["pg_charges"]),
            "pg_charges_percentage": float(l["pg_charges_percentage"]) if l["pg_charges_percentage"] is not None else None,
            "markup": float(l["markup"]), "addl_markup": float(l["addl_markup"]), "ssr_markup": float(l["ssr_markup"]),
            "service_fee": float(l["service_fee"]), "addl_service_fee": float(l["addl_service_fee"]), "ssr_service_fee": float(l["ssr_service_fee"]),
            "gst_pct": float(l["gst_pct"]), "total_billed": float(l["total_billed"]), "status": l["status"],
            "supplier_name": l["supplier_name"], "office_id": l["office_id"], "fop": l["fop"], "card_number": l["card_number"],
            "supp_comm_on": l["supp_comm_on"], "supp_comm_type": l["supp_comm_type"], "supp_comm_value": float(l["supp_comm_value"]),
            "supp_tds_per": float(l["supp_tds_per"]), "supp_markup": float(l["supp_markup"]), "supp_addl_markup": float(l["supp_addl_markup"]),
            "supp_service_fee": float(l["supp_service_fee"]), "supp_addl_service_fee": float(l["supp_addl_service_fee"]),
            "supp_gst_pct": float(l["supp_gst_pct"]),
        } for l in lines],
    })


def ticket_jv_preview(request, ticket_id):
    """
    GET /api/tickets/<id>/jv-preview/?company_id=1
    Always computes the JV lines LIVE from this ticket's TicketLines
    using the exact same Python formula as auto-posting (_compute_jv_lines)
    — never reads the stored VoucherLines snapshot. The Voucher table is
    only consulted here to report whether this ticket has actually been
    posted yet, and its category-prefixed voucher_no (e.g. AL-3) if so.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    try:
        ticket = Ticket.objects.select_related("customer", "supplier").get(id=ticket_id, company_id=company_id)
    except Ticket.DoesNotExist:
        return JsonResponse({"error": "Ticket not found."}, status=404)

    lines = list(ticket.lines.all())
    if not lines:
        return JsonResponse({"error": "This ticket has no ticket lines to build a voucher from."}, status=400)

    accounts, narration, total_debit, total_credit = _compute_jv_lines(ticket, lines)

    voucher = JournalVoucher.objects.filter(source_ticket_id=ticket.id).only("id", "voucher_no").first()

    return JsonResponse({
        "posted": voucher is not None,
        "voucher_id": voucher.id if voucher else None,
        "voucher_no": voucher.voucher_no if voucher else None,
        "branch_name": ticket.branch_name or "Chennai Branch",
        "voucher_type": "Tax Invoice",
        "voucher_date": ticket.invoice_date.isoformat() if ticket.invoice_date else None,
        "narration": narration,
        "accounts": accounts,
        "total_debit": total_debit,
        "total_credit": total_credit,
    })


@csrf_exempt
def ticket_jv_preview_draft(request):
    """
    POST /api/tickets/jv-preview-draft/
    Same body shape as tickets/create/ (company_id, header fields,
    customer_name, supplier_name, lines: [...]) — lets the New Ticket form
    show a live JV preview BEFORE the ticket is saved, so the JV tab can
    stay open and re-request this on every fare edit. Builds an UNSAVED
    Ticket + TicketLine instances (never .save()'d, nothing touches the
    DB) purely to run them through the exact same _compute_jv_lines used
    by real auto-posting, so the preview always matches what Save Ticket
    would actually post.

    Looser than ticket_create on purpose — a passenger mid-edit may not
    have a valid Office ID/supplier yet, so a missing/invalid supplier
    just posts that line's Supplier row against no ledger rather than
    rejecting the whole preview.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    company_id = body.get("company_id")
    lines_in = body.get("lines") or []
    if not company_id or not lines_in:
        return JsonResponse({"error": "company_id and at least one line are required."}, status=400)

    customer = None
    if body.get("customer_name"):
        customer = Ledger.objects.filter(company_id=company_id, name=body["customer_name"], ledger_category="DEBTOR").first()
    if customer is None:
        # Unlike supplier (which every account-head formula tolerates being
        # unpicked), the Customer row is not optional in _compute_jv_lines —
        # it unconditionally reads ticket.customer.alias_name/name, so a
        # missing Customer would otherwise crash with an AttributeError.
        return JsonResponse({"error": "Pick a Customer before previewing the JV."}, status=400)

    supplier = None
    if body.get("supplier_name"):
        supplier = Ledger.objects.filter(company_id=company_id, name=body["supplier_name"], ledger_category="CREDITOR").first()

    header_kwargs = {f: body[f] for f in TICKET_HEADER_FIELDS if f in body}
    header_kwargs["invoice_date"] = _parse_date(header_kwargs.get("invoice_date"))
    header_kwargs["booking_ref_date"] = _parse_date(header_kwargs.get("booking_ref_date"))
    if "roe" in header_kwargs:
        header_kwargs["roe"] = _safe_decimal(header_kwargs["roe"], default=1)

    ticket = Ticket(company_id=company_id, customer=customer, supplier=supplier, **header_kwargs)

    line_objs = []
    for line_in in lines_in:
        line_kwargs = {f: line_in[f] for f in TICKET_LINE_FIELDS if f in line_in}
        for f in TICKET_LINE_NUMERIC_FIELDS:
            if f in line_kwargs:
                line_kwargs[f] = _safe_decimal(line_kwargs[f])

        line_supplier = None
        if line_in.get("supplier_name"):
            line_supplier = Ledger.objects.filter(company_id=company_id, name=line_in["supplier_name"], ledger_category="CREDITOR").first()

        line = TicketLine(ticket=ticket, supplier=line_supplier, **line_kwargs)
        line.total_billed = _safe_decimal(line.compute_total())
        line_objs.append(line)

    accounts, narration, total_debit, total_credit = _compute_jv_lines(ticket, line_objs)
    total_debit, total_credit = round(total_debit, 2), round(total_credit, 2)

    return JsonResponse({
        "posted": False, "voucher_id": None, "voucher_no": None,
        "branch_name": ticket.branch_name or "Chennai Branch",
        "voucher_type": "Tax Invoice",
        "voucher_date": ticket.invoice_date.isoformat() if ticket.invoice_date else None,
        "narration": narration,
        "accounts": accounts,
        "total_debit": total_debit,
        "total_credit": total_credit,
    })


@csrf_exempt
def _voucher_dict(v):
    """v: the row dict sp_client.vouchers_list/voucher_get/voucher_save returns (dbo.sp_Voucher)."""
    lines_json = v["lines_json"]
    return {
        "id": v["id"], "voucher_no": v["voucher_no"], "branch_name": v["branch_name"], "voucher_type": v["voucher_type"],
        "voucher_date": v["voucher_date"].isoformat() if v["voucher_date"] else None,
        "narration": v["narration"],
        "total_debit": float(v["total_debit"]), "total_credit": float(v["total_credit"]),
        "lines": json.loads(lines_json) if lines_json else [],
    }


@csrf_exempt
@transaction.atomic
def voucher_create(request):
    """
    POST /api/vouchers/create/
    Body: { company_id, branch_name, voucher_type, voucher_date, narration,
            lines: [{ledger_id, debit, credit}, ...] }
    Saves into the Voucher table (manual double-entry postings only,
    voucher-entry.html) — never JournalVoucher, which only ticket_create/
    ticket_update ever write to.

    Real server-side balance check — total debit MUST equal total credit,
    checked here regardless of what the browser calculated, closing the
    exact "client-only balance validation" gap flagged earlier for the
    generic voucher-entry form.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    try:
        voucher = sp_client.voucher_save(
            body.get("company_id"), body.get("branch_name"), body.get("voucher_type", "Journal"),
            _parse_date(body.get("voucher_date")), body.get("narration"), body.get("lines") or [],
        )
    except sp_client.StoredProcedureError as err:
        return JsonResponse({"error": str(err)}, status=400)

    return JsonResponse({"id": voucher["id"], "message": "Voucher posted."}, status=201)


def voucher_detail(request, voucher_id):
    """GET /api/vouchers/<id>/?company_id=1 — one manual Voucher, for the Edit form to prefill from."""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    voucher = sp_client.voucher_get(voucher_id, company_id)
    if not voucher:
        return JsonResponse({"error": "Voucher not found."}, status=404)

    return JsonResponse(_voucher_dict(voucher))


@csrf_exempt
@transaction.atomic
def voucher_update(request, voucher_id):
    """
    POST /api/vouchers/<id>/update/
    Same body/validation as voucher_create - updates the existing row in
    place instead of posting a new one. voucher_no is never reassigned.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    try:
        voucher = sp_client.voucher_save(
            body.get("company_id"), body.get("branch_name"), body.get("voucher_type", "Journal"),
            _parse_date(body.get("voucher_date")), body.get("narration"), body.get("lines") or [],
            voucher_id=voucher_id,
        )
    except sp_client.StoredProcedureError as err:
        msg = str(err)
        status = 404 if msg == "Voucher not found." else 400
        return JsonResponse({"error": msg}, status=status)

    return JsonResponse({"id": voucher["id"], "message": "Voucher updated."})


def vouchers_list(request):
    """
    GET /api/vouchers/?company_id=1
    Manually created vouchers only (the Voucher table) — vouchers
    auto-generated from a ticket's JV live in the separate JournalVoucher
    table entirely and are intentionally excluded here. Those stay
    viewable only from the ticket's own "View JV" page
    (voucher-entry.html?ticket_id=X), not in this general register.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    vouchers = sp_client.vouchers_list(company_id)
    return JsonResponse([_voucher_dict(v) for v in vouchers], safe=False)


def _voucher_type_dict(vt):
    """vt: the row dict sp_client.voucher_type_get/list/save returns (dbo.sp_VoucherType)."""
    return {
        "id": vt["id"], "name": vt["name"], "alias_name": vt["alias_name"],
        "voucher_category": vt["voucher_category"], "is_active": vt["is_active"],
        "number_method": vt["number_method"],
        "allow_additional_numbering": vt["allow_additional_numbering"],
        "allow_effective_dates": vt["allow_effective_dates"],
        "allow_narration": vt["allow_narration"],
        "an_width_of_invoice_number": vt["an_width_of_invoice_number"],
        "an_prefill_with_zero": vt["an_prefill_with_zero"],
        "an_restart_applicable_from": vt["an_restart_applicable_from"].isoformat() if vt["an_restart_applicable_from"] else None,
        "an_restart_starting_number": vt["an_restart_starting_number"],
        "an_restart_period": vt["an_restart_period"],
        "an_prefix_details": vt["an_prefix_details"],
        "an_suffix_details": vt["an_suffix_details"],
    }


def voucher_type_list(request):
    """GET /api/voucher-type/?company_id=1[&id=1] - every voucher type for a company, or one by id."""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    voucher_type_id = request.GET.get("id")
    if voucher_type_id:
        vt = sp_client.voucher_type_get(voucher_type_id, company_id)
        if not vt:
            return JsonResponse({"error": "Voucher Type not found."}, status=404)
        return JsonResponse(_voucher_type_dict(vt))

    rows = sp_client.voucher_type_list(company_id)
    return JsonResponse([_voucher_type_dict(vt) for vt in rows], safe=False)


@csrf_exempt
def voucher_type_save(request):
    """
    POST /api/voucher-type/save/
    Body: { "id": 1 (optional - update if present), "company_id": 1,
            "name": "...", "alias_name": "...", "voucher_category": "General",
            "is_active": true, "number_method": "Automatic",
            "allow_additional_numbering": false, "allow_effective_dates": false,
            "allow_narration": true,
            "an_width_of_invoice_number": 6, "an_prefill_with_zero": false,
            "an_restart_applicable_from": "2026-04-01", "an_restart_starting_number": 1,
            "an_restart_period": "None", "an_prefix_details": "...", "an_suffix_details": "..." }
    Upserts by (company_id, name) - the table's unique key - unless "id" is given.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    company_id = body.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    name = (body.get("name") or "").strip()
    if not name:
        return JsonResponse({"error": "Voucher Name is required."}, status=400)

    fields = {
        "name": name,
        "alias_name": (body.get("alias_name") or "").strip() or None,
        "voucher_category": body.get("voucher_category") or "General",
        "is_active": bool(body.get("is_active", True)),
        "number_method": body.get("number_method") or "Automatic",
        "allow_additional_numbering": bool(body.get("allow_additional_numbering", False)),
        "allow_effective_dates": bool(body.get("allow_effective_dates", False)),
        "allow_narration": bool(body.get("allow_narration", True)),
        "an_width_of_invoice_number": body.get("an_width_of_invoice_number") or None,
        "an_prefill_with_zero": bool(body.get("an_prefill_with_zero", False)),
        "an_restart_applicable_from": _parse_date(body.get("an_restart_applicable_from")),
        "an_restart_starting_number": body.get("an_restart_starting_number") or None,
        "an_restart_period": body.get("an_restart_period") or "None",
        "an_prefix_details": (body.get("an_prefix_details") or "").strip() or None,
        "an_suffix_details": (body.get("an_suffix_details") or "").strip() or None,
    }

    voucher_type_id = body.get("id")
    try:
        vt = sp_client.voucher_type_save(company_id, fields, voucher_type_id=voucher_type_id)
    except sp_client.StoredProcedureError as err:
        msg = str(err)
        status = 404 if "not found" in msg else 409
        return JsonResponse({"error": msg}, status=status)
    return JsonResponse(_voucher_type_dict(vt), status=200 if voucher_type_id else 201)


@csrf_exempt
def voucher_type_delete(request, voucher_type_id):
    """DELETE /api/voucher-type/<id>/delete/?company_id=1"""
    if request.method != "DELETE":
        return HttpResponseNotAllowed(["DELETE"])

    company_id = request.GET.get("company_id")
    try:
        sp_client.voucher_type_delete(voucher_type_id, company_id)
    except sp_client.StoredProcedureError as err:
        return JsonResponse({"error": str(err)}, status=404)
    return JsonResponse({"message": "Voucher Type deleted."})


def voucher_type_next_number(request):
    """
    GET /api/voucher-type/next-number/?company_id=1&name=Tax+Invoice[&voucher_date=2026-09-23]
    Ticket Entry's Invoice Number, driven by the selected Invoice Type's
    (=VoucherType) own Number Method:
      - "Manual" -> {"number_method": "Manual", "next_number": null} - the
        field stays a plain editable text box, nothing suggested.
      - "Automatic" / "Automatic & Manual Override" -> a suggested number is
        computed from that voucher type's Additional Numbering Details
        (prefix/suffix, zero-padding width, and a Restart Numbering period
        that resets the sequence every Day/Week/Month/Year). The caller
        decides whether to lock the field (Automatic) or leave it editable
        with this as a starting value (Automatic & Manual Override).
    Numbers already used are read straight off existing Tickets.invoice_type
    (matched by this exact voucher type name) rather than kept in a separate
    counter column, so it self-heals if a ticket is edited/deleted.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    name = (request.GET.get("name") or "").strip()
    if not company_id or not name:
        return JsonResponse({"error": "company_id and name are required"}, status=400)

    vt = sp_client.voucher_type_get_by_name(company_id, name)
    if not vt:
        return JsonResponse({"error": "Voucher Type not found."}, status=404)

    if vt["number_method"] == "Manual":
        return JsonResponse({"number_method": vt["number_method"], "next_number": None})

    voucher_date = _parse_date(request.GET.get("voucher_date")) or datetime.now().date()
    prefix = vt["an_prefix_details"] or ""
    suffix = vt["an_suffix_details"] or ""
    width = vt["an_width_of_invoice_number"]
    starting_number = vt["an_restart_starting_number"] or 1
    period = vt["an_restart_period"] if vt["allow_additional_numbering"] else "None"

    # A Reschedule ticket is still invoiced under the SAME Invoice Type
    # (Sales Invoice etc) as a plain booking, so it must share one
    # continuous numbering sequence with Ticket - not its own separate
    # one. Without this, a reschedule invoice number was never counted
    # here, so the next plain booking after it could suggest an already-
    # used number again (collision) instead of continuing past it.
    restart_from = vt["an_restart_applicable_from"] if (vt["allow_additional_numbering"] and vt["an_restart_applicable_from"]) else None
    rows = sp_client.tickets_invoice_numbers_by_type(company_id, name, from_date=restart_from)

    def in_bucket(invoice_date):
        """True if invoice_date falls in the same Restart Numbering bucket as voucher_date for this period (Daily/Weekly/Monthly/Yearly/None)."""
        if not invoice_date or period in (None, "None"):
            return True
        if period == "Daily":
            return invoice_date == voucher_date
        if period == "Monthly":
            return invoice_date.year == voucher_date.year and invoice_date.month == voucher_date.month
        if period == "Yearly":
            return invoice_date.year == voucher_date.year
        if period == "Weekly":
            iso_year, iso_week, _ = voucher_date.isocalendar()
            week_start = date.fromisocalendar(iso_year, iso_week, 1)
            week_end = date.fromisocalendar(iso_year, iso_week, 7)
            return week_start <= invoice_date <= week_end
        return True

    all_invoice_numbers = [r["invoice_number"] for r in rows if in_bucket(r["invoice_date"])]

    max_seq = None
    for inv_no in all_invoice_numbers:
        s = inv_no or ""
        if prefix and s.startswith(prefix):
            s = s[len(prefix):]
        if suffix and s.endswith(suffix):
            s = s[:len(s) - len(suffix)]
        if s.isdigit():
            max_seq = max(max_seq or 0, int(s))

    next_seq = (max_seq + 1) if max_seq is not None else starting_number
    seq_str = str(next_seq).zfill(width) if (vt["an_prefill_with_zero"] and width) else str(next_seq)
    next_number = f"{prefix}{seq_str}{suffix}"

    return JsonResponse({"number_method": vt["number_method"], "next_number": next_number})


SUPPLIER_RULE_FIELDS = [
    "office_id", "supplier_name", "travel_type", "airline_category", "cabin", "fare_type", "comm_on",
    "calc_type", "calc_pct", "flat_amt", "valid_upto",
]


def _supplier_rule_dict(r):
    """r: the row dict sp_client.supplier_commission_rules_list/save returns (dbo.sp_SupplierCommissionRule)."""
    return {
        "id": r["id"], "type": r["type"],
        "office_id": r["office_id"], "supplier_name": r["supplier_name"],
        "travel_type": r["travel_type"], "airline_category": r["airline_category"],
        "cabin": r["cabin"], "fare_type": r["fare_type"], "comm_on": r["comm_on"],
        "calc_type": r["calc_type"], "calc_pct": float(r["calc_pct"]), "flat_amt": float(r["flat_amt"]),
        "valid_upto": r["valid_upto"].isoformat() if r["valid_upto"] else None,
    }


def supplier_commission_rules_list(request):
    """
    GET /api/supplier-commission-rules/?company_id=1[&office_id=IGE6381]
    Backs both the Supplier Master's "Supplier Commission List" table and
    the New Ticket modal's Office-ID auto-fill lookup (pass office_id to
    narrow to just that supplier's rules).
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    rules = sp_client.supplier_commission_rules_list(company_id, office_id=request.GET.get("office_id"))
    return JsonResponse([_supplier_rule_dict(r) for r in rules], safe=False)


@csrf_exempt
def supplier_commission_rule_create(request):
    """
    POST /api/supplier-commission-rules/create/
    Body: { "company_id": 1, "office_id": "IGE6381", "supplier_name": "...",
            "travel_type": "Domestic", "airline_category": "LCC", "cabin": "Economy",
            "fare_type": "Normal Fare", "calc_type": "Percentage", "calc_pct": 5,
            "flat_amt": 0, "valid_upto": "2026-12-31" }
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    company_id = body.get("company_id")
    office_id = (body.get("office_id") or "").strip()
    if not company_id or not office_id:
        return JsonResponse({"error": "company_id and office_id are required"}, status=400)

    fields = {"office_id": office_id}
    for f in SUPPLIER_RULE_FIELDS:
        if f == "office_id":
            continue
        if f in body and body[f] not in (None, ""):
            fields[f] = body[f]
    rule = sp_client.supplier_commission_rule_save(company_id, fields)
    return JsonResponse(_supplier_rule_dict(rule), status=201)


@csrf_exempt
def supplier_commission_rule_delete(request, rule_id):
    """DELETE /api/supplier-commission-rules/<id>/delete/?company_id=1"""
    if request.method != "DELETE":
        return HttpResponseNotAllowed(["DELETE"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    try:
        sp_client.supplier_commission_rule_delete(rule_id, company_id)
    except sp_client.StoredProcedureError as err:
        return JsonResponse({"error": str(err)}, status=404)
    return JsonResponse({"ok": True})


def ledgers_by_group_name(request):
    """
    GET /api/ledgers-by-group/?company_id=1&group_name=Incomes
    Powers the "Load The Data's From Group X" ledger dropdowns on the
    Master Mapping / FOP Master pages. Several things make a naive
    "group__name=X" filter miss real ledgers:
      1. Naming — a company's actual top-level group may be "Income" where
         the field spec says "Incomes" (or any other singular/plural or
         casing difference), and "Duties & Taxes" vs "Duties and Taxes" —
         so matching is case-insensitive and tolerant of a trailing "s"
         either way, and of "and" vs "&".
      2. Depth — ledgers are usually created under a CHILD group (e.g.
         Income -> Direct Income -> "Service Fee"), not directly under the
         top-level group, so this walks the whole subtree under every
         matched group rather than only that group's direct ledgers.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    group_name = request.GET.get("group_name")
    if not company_id or not group_name:
        return JsonResponse({"error": "company_id and group_name are required"}, status=400)

    # Every spelling variant worth trying: plain, plural/singular swap, and
    # " and " <-> " & " swap (each combined with the plural/singular swap too).
    variants = {group_name, group_name.rstrip("s"), group_name + "s"}
    for v in list(variants):
        if " and " in v.lower():
            swapped = re.sub(r"\band\b", "&", v, flags=re.IGNORECASE)
            variants.update({swapped, swapped.rstrip("s"), swapped + "s"})
        if "&" in v:
            swapped = v.replace("&", "and")
            variants.update({swapped, swapped.rstrip("s"), swapped + "s"})

    rows = sp_client.ledgers_by_group_names(company_id, variants)
    return JsonResponse([{"id": r["id"], "name": r["name"]} for r in rows], safe=False)


def _master_mapping_dict(m):
    """m: the row dict sp_client.master_mapping_list/save_row returns (dbo.sp_MasterMapping)."""
    return {
        "id": m["id"], "product_type": m["product_type"],
        "masters_category": m["masters_category"], "masters_category_id": m["masters_category_id"],
        "field_name": m["field_name"], "ledger_id": m["ledger_id"], "ledger_name": m["ledger_name"],
        "ledger_gst_percentage": float(m["ledger_gst_percentage"] or 0),
        "effective_from": m["effective_from"].isoformat() if m["effective_from"] else None,
    }


def master_mapping_list(request):
    """
    GET /api/master-mapping/?company_id=1[&product_type=Airline][&masters_category=GST and TDS]
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    rows = sp_client.master_mapping_list(
        company_id, product_type=request.GET.get("product_type"), masters_category=request.GET.get("masters_category"),
    )
    return JsonResponse([_master_mapping_dict(m) for m in rows], safe=False)


@csrf_exempt
def master_mapping_save(request):
    """
    POST /api/master-mapping/save/
    Body: { "company_id": 1, "product_type": "Airline", "masters_category": "Earnings From Customer",
            "rows": [ { "field_name": "Markup A/c", "ledger_id": 12, "effective_from": "2026-04-01" }, ... ] }
    Upserts each row by (company_id, product_type, field_name) — saving a
    Masters category's fields again updates the existing mapping instead of
    creating a duplicate (per the table's unique constraint).
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    company_id = body.get("company_id")
    product_type = body.get("product_type")
    masters_category = body.get("masters_category")
    rows_in = body.get("rows") or []
    if not company_id or not product_type or not masters_category or not rows_in:
        return JsonResponse({"error": "company_id, product_type, masters_category and rows are required"}, status=400)

    saved = []
    for row in rows_in:
        field_name = (row.get("field_name") or "").strip()
        ledger_id = row.get("ledger_id")
        effective_from = row.get("effective_from")
        if not field_name or not ledger_id or not effective_from:
            continue

        try:
            mapping = sp_client.master_mapping_save_row(
                company_id, product_type, masters_category,
                MasterMapping.MASTERS_CATEGORY_IDS.get(masters_category, 0),
                field_name, ledger_id, effective_from,
            )
        except sp_client.StoredProcedureError as err:
            msg = str(err)
            status = 404 if "not found" in msg else 409
            return JsonResponse({"error": msg}, status=status)
        saved.append(_master_mapping_dict(mapping))

    _field_gst_pct_cache.clear()
    return JsonResponse(saved, safe=False, status=201)


@csrf_exempt
def master_mapping_delete(request, mapping_id):
    """DELETE /api/master-mapping/<id>/delete/?company_id=1"""
    if request.method != "DELETE":
        return HttpResponseNotAllowed(["DELETE"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    try:
        sp_client.master_mapping_delete(mapping_id, company_id)
    except sp_client.StoredProcedureError as err:
        return JsonResponse({"error": str(err)}, status=404)
    _field_gst_pct_cache.clear()
    return JsonResponse({"ok": True})


def _fop_master_dict(f):
    """f: the row dict sp_client.fop_master_list/save returns (dbo.sp_FOPMaster)."""
    return {
        "id": f["id"], "card_type": f["card_type"], "card_number": f["card_number"], "bank_name": f["bank_name"],
        "card_master_ledger_id": f["card_master_ledger_id"], "card_master_ledger_name": f["card_master_ledger_name"],
        "is_active": f["is_active"],
    }


def fop_master_list(request):
    """GET /api/fop-master/?company_id=1[&card_type=Own Card]"""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    rows = sp_client.fop_master_list(company_id, card_type=request.GET.get("card_type"))
    return JsonResponse([_fop_master_dict(f) for f in rows], safe=False)


@csrf_exempt
def fop_master_save(request):
    """
    POST /api/fop-master/save/
    Body: { "company_id": 1, "card_type": "Own Card", "card_number": "4111...",
            "card_master_ledger_id": 12, "is_active": true }
    Upserts by (company_id, card_number) — Card Number is the natural
    unique key (no duplicates), matching the table's unique constraint.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    company_id = body.get("company_id")
    card_type = body.get("card_type")
    card_number = (body.get("card_number") or "").strip()
    ledger_id = body.get("card_master_ledger_id")
    if not company_id or not card_type or not card_number:
        return JsonResponse({"error": "company_id, card_type and card_number are required"}, status=400)

    card_id = body.get("id")
    try:
        card = sp_client.fop_master_save(
            company_id, card_type, card_number,
            bank_name=(body.get("bank_name") or "").strip() or None,
            card_master_ledger_id=ledger_id,
            is_active=bool(body.get("is_active", True)),
            card_id=card_id,
        )
    except sp_client.StoredProcedureError as err:
        msg = str(err)
        status = 404 if "not found" in msg else (409 if "already used" in msg else 400)
        return JsonResponse({"error": msg}, status=status)
    return JsonResponse(_fop_master_dict(card), status=200 if card_id else 201)


@csrf_exempt
def fop_master_delete(request, card_id):
    """DELETE /api/fop-master/<id>/delete/?company_id=1"""
    if request.method != "DELETE":
        return HttpResponseNotAllowed(["DELETE"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    try:
        sp_client.fop_master_delete(card_id, company_id)
    except sp_client.StoredProcedureError as err:
        return JsonResponse({"error": str(err)}, status=404)
    return JsonResponse({"ok": True})


def _pg_master_dict(p):
    """p: the row dict sp_client.pg_master_list/save returns (dbo.sp_PGMaster)."""
    return {
        "id": p["id"], "gateway_name": p["gateway_name"],
        "payment_master_ledger_id": p["payment_master_ledger_id"], "payment_master_ledger_name": p["payment_master_ledger_name"],
        "pg_charges_master_ledger_id": p["pg_charges_master_ledger_id"], "pg_charges_master_ledger_name": p["pg_charges_master_ledger_name"],
        "pg_charges_master_ledger_gst_percentage": float(p["pg_charges_master_ledger_gst_percentage"] or 0),
        "pg_charges_percentage": float(p["pg_charges_percentage"]) if p["pg_charges_percentage"] is not None else None,
        "pg_charges_percentage_effective_from": p["pg_charges_percentage_effective_from"].isoformat() if p["pg_charges_percentage_effective_from"] else None,
        "is_active": p["is_active"],
    }


def pg_master_list(request):
    """GET /api/pg-master/?company_id=1"""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    rows = sp_client.pg_master_list(company_id)
    return JsonResponse([_pg_master_dict(p) for p in rows], safe=False)


@csrf_exempt
def pg_master_save(request):
    """
    POST /api/pg-master/save/
    Body: { "company_id": 1, "gateway_name": "Razorpay",
            "payment_master_ledger_id": 12, "is_active": true }
    Upserts by (company_id, gateway_name) — Payment Gateway Name is the
    natural unique key (no duplicates), matching the table's unique constraint.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    company_id = body.get("company_id")
    gateway_name = (body.get("gateway_name") or "").strip()
    ledger_id = body.get("payment_master_ledger_id")
    if not company_id or not gateway_name or not ledger_id:
        return JsonResponse({"error": "company_id, gateway_name and payment_master_ledger_id are required"}, status=400)

    charges_percentage = _safe_decimal(body.get("pg_charges_percentage"), default=None)
    if charges_percentage is not None and not (0 <= charges_percentage <= 100):
        return JsonResponse({"error": "PG Charges Percentage must be between 0 and 100."}, status=400)
    charges_percentage_effective_from = _parse_date(body.get("pg_charges_percentage_effective_from"))

    gw_id = body.get("id")
    try:
        gateway = sp_client.pg_master_save(
            company_id, gateway_name, ledger_id,
            pg_charges_master_ledger_id=body.get("pg_charges_master_ledger_id"),
            pg_charges_percentage=charges_percentage,
            pg_charges_percentage_effective_from=charges_percentage_effective_from,
            is_active=bool(body.get("is_active", True)),
            gateway_id=gw_id,
        )
    except sp_client.StoredProcedureError as err:
        msg = str(err)
        status = 404 if "not found" in msg else (409 if "already used" in msg else 400)
        return JsonResponse({"error": msg}, status=status)
    return JsonResponse(_pg_master_dict(gateway), status=200 if gw_id else 201)


def pg_master_history_list(request, gateway_id):
    """GET /api/pg-master/<id>/history/?company_id=1 — snapshots newest-first, for a "View History" popup."""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    rows = sp_client.pg_master_history_list(gateway_id, company_id)
    return JsonResponse([{
        "id": h["id"], "effective_from": h["effective_from"].isoformat(),
        "payment_master_ledger_name": h["payment_master_ledger_name"],
        "pg_charges_master_ledger_name": h["pg_charges_master_ledger_name"],
        "pg_charges_percentage": float(h["pg_charges_percentage"]) if h["pg_charges_percentage"] is not None else None,
    } for h in rows], safe=False)


def pg_master_effective(request):
    """
    GET /api/pg-master/effective/?company_id=1&gateway_name=Razorpay&as_of_date=2026-09-24
    The frontend's single source of truth for PG Charges calculation and
    display — resolves via _pg_master_effective_snapshot() so a ticket
    always uses whatever was in force on its own Invoice Date.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    gateway_name = request.GET.get("gateway_name")
    if not company_id or not gateway_name:
        return JsonResponse({"error": "company_id and gateway_name are required"}, status=400)

    as_of_date = _parse_date(request.GET.get("as_of_date"))
    snapshot = _pg_master_effective_snapshot(company_id, gateway_name, as_of_date)
    if not snapshot:
        return JsonResponse({"error": "Payment Gateway not found."}, status=404)
    return JsonResponse(snapshot)


@csrf_exempt
def pg_master_delete(request, gateway_id):
    """DELETE /api/pg-master/<id>/delete/?company_id=1"""
    if request.method != "DELETE":
        return HttpResponseNotAllowed(["DELETE"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    try:
        sp_client.pg_master_delete(gateway_id, company_id)
    except sp_client.StoredProcedureError as err:
        return JsonResponse({"error": str(err)}, status=404)
    return JsonResponse({"ok": True})


def _company_master_dict(c):
    """c: the row dict sp_client.company_master_get/list/save returns (dbo.sp_CompanyMaster)."""
    return {
        "id": c["id"], "company_name": c["company_name"], "mailing_name": c["mailing_name"],
        "address": c["address"], "country": c["country"], "state": c["state"], "pincode": c["pincode"],
        "telephone": c["telephone"], "mobile": c["mobile"], "email": c["email"],
        "financial_year_from": c["financial_year_from"].isoformat() if c["financial_year_from"] else None,
        "books_beginning_from": c["books_beginning_from"].isoformat() if c["books_beginning_from"] else None,
        "gst_reg_type": c["gst_reg_type"], "gst_no": c["gst_no"], "pan_number": c["pan_number"],
        "cin_number": c["cin_number"], "tan_number": c["tan_number"], "hsn_sac": c["hsn_sac"],
        "currency_symbol": c["currency_symbol"], "currency_name": c["currency_name"],
        "decimal_places": c["decimal_places"],
        "logo_base64": c["logo_base64"], "seal_base64": c["seal_base64"],
    }


def company_master_list(request):
    """GET /api/company-master/[?id=1] - every company, or one by id."""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("id")
    if company_id:
        c = sp_client.company_master_get(company_id)
        if not c:
            return JsonResponse({"error": "Company not found."}, status=404)
        return JsonResponse(_company_master_dict(c))

    rows = sp_client.company_master_list()
    return JsonResponse([_company_master_dict(c) for c in rows], safe=False)


@csrf_exempt
def company_master_save(request):
    """
    POST /api/company-master/save/
    Body: { "id": 1 (optional - update if present), "company_name": "...",
            "mailing_name": "...", "address": "...", "country": "India",
            "state": "...", "pincode": "...", "telephone": "...", "mobile": "...",
            "email": "...", "financial_year_from": "2026-04-01",
            "books_beginning_from": "2026-04-01", "gst_reg_type": "Regular",
            "gst_no": "...", "pan_number": "...", "cin_number": "...", "tan_number": "...",
            "currency_symbol": "...", "currency_name": "...", "decimal_places": 2,
            "hsn_sac": "..." }
    Upserts by company_name (the table's unique key) unless "id" is given —
    when "id" IS given, it's always used as this row's own primary key
    (creating a fresh row with exactly that id if none exists yet, not
    just updating an existing one), since CompanyMaster.id is the same
    company_id every other table in this app scopes its data by (see the
    model's own docstring) — the page always passes the active company's
    id from the top-nav switcher, never lets the DB auto-assign one.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    company_name = (body.get("company_name") or "").strip()
    if not company_name:
        return JsonResponse({"error": "company_name is required"}, status=400)

    fields = {
        "company_name": company_name,
        "mailing_name": (body.get("mailing_name") or "").strip() or None,
        "address": (body.get("address") or "").strip() or None,
        "country": (body.get("country") or "India").strip() or "India",
        "state": (body.get("state") or "").strip() or None,
        "pincode": (body.get("pincode") or "").strip() or None,
        "telephone": (body.get("telephone") or "").strip() or None,
        "mobile": (body.get("mobile") or "").strip() or None,
        "email": (body.get("email") or "").strip() or None,
        "financial_year_from": _parse_date(body.get("financial_year_from")),
        "books_beginning_from": _parse_date(body.get("books_beginning_from")),
        "gst_reg_type": body.get("gst_reg_type") or "Regular",
        "gst_no": (body.get("gst_no") or "").strip().upper() or None,
        "pan_number": (body.get("pan_number") or "").strip().upper() or None,
        "cin_number": (body.get("cin_number") or "").strip().upper() or None,
        "tan_number": (body.get("tan_number") or "").strip().upper() or None,
        "hsn_sac": (body.get("hsn_sac") or "").strip() or None,
        "currency_symbol": (body.get("currency_symbol") or "").strip() or None,
        "currency_name": (body.get("currency_name") or "").strip() or None,
        "decimal_places": int(body["decimal_places"]) if body.get("decimal_places") not in (None, "") else 2,
        "logo_base64": body.get("logo_base64") or None,
        "seal_base64": body.get("seal_base64") or None,
    }

    try:
        company = sp_client.company_master_save(fields, company_id=body.get("id"))
    except sp_client.StoredProcedureError as err:
        return JsonResponse({"error": str(err)}, status=409)
    status = 201 if company.get("was_created") else 200
    return JsonResponse(_company_master_dict(company), status=status)


@csrf_exempt
def company_master_delete(request, company_id):
    """DELETE /api/company-master/<id>/delete/"""
    if request.method != "DELETE":
        return HttpResponseNotAllowed(["DELETE"])

    try:
        sp_client.company_master_delete(company_id)
    except sp_client.StoredProcedureError as err:
        return JsonResponse({"error": str(err)}, status=404)
    return JsonResponse({"ok": True})


@csrf_exempt
def seed_database(request):
    """
    GET/POST /api/seed-database/?token=<SEED_TOKEN>[&force=true]
    Initializes TiDB / MySQL database with all groups, ledgers, tickets, and mappings.

    A forced seed wipes the app's data tables (see converted_inserts.sql),
    so this is disabled (404) unless the SEED_TOKEN environment variable is
    set, and then only answers a request carrying that exact token. Set
    SEED_TOKEN on Render just for a data update, call this once, then
    delete the variable again.
    """
    seed_token = os.environ.get("SEED_TOKEN", "")
    if not seed_token:
        return JsonResponse({"error": "Not found."}, status=404)
    if not hmac.compare_digest(request.GET.get("token", ""), seed_token):
        return JsonResponse({"error": "Invalid token."}, status=403)

    from load_initial_data import load_data
    force = request.GET.get("force", "false").lower() in ("true", "1")
    res = load_data(force=force)
    return JsonResponse(res)


# ---- Live-only endpoints (not in the build): kept from the previous live views.py ----

def dashboard_summary(request):
    """
    GET /api/dashboard/?company_id=1
    Feeds dashboard.html's hero cards/revenue+finance+compliance tiles/
    trend chart/product-mix chart/branch table - shape driven entirely by
    window.VoyagerHardcode.DASHBOARD_HERO_CARDS/DASHBOARD_REVENUE_TILES/
    DASHBOARD_FINANCE_TILES's dataPath strings plus dashboard.js's own
    direct data.* reads, not something this view gets to choose freely.

    Only "Airline" tickets exist in this app today (Hotel/Visa/Tour/
    Insurance never got their own modules built) - every revenue/mix
    figure that would come from those stays 0 rather than being mocked,
    same principle as everywhere else real data replaced mock data this
    session: show what's real, don't fabricate the rest.

    Sales = each ticket's real Total Billed (TicketLine.compute_total(),
    same figure the customer is actually debited). "Revenue" here means
    the agency's own earnings on top of the raw fare (markup/service
    fee/commission), not the gross sale - matches how Ledgers already
    separate "Sales Accounts" from "Direct/Indirect Income" in the Chart
    of Accounts.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    today = datetime.now().date()
    fy_start = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
    month_start = today.replace(day=1)

    tickets = list(
        Ticket.objects.filter(company_id=company_id, invoice_date__gte=fy_start)
        .prefetch_related("lines")
    )

    def line_sales(l):
        return float(l.compute_total())

    def line_earnings(l):
        return (
            float(l.markup) + float(l.addl_markup) + float(l.ssr_markup)
            + float(l.service_fee) + float(l.addl_service_fee) + float(l.ssr_service_fee)
        )

    def line_service_charges(l):
        return float(l.service_fee) + float(l.addl_service_fee) + float(l.ssr_service_fee)

    def line_markup(l):
        return float(l.markup) + float(l.addl_markup) + float(l.ssr_markup)

    today_sales = month_sales = ytd_sales = 0.0
    ticket_revenue = service_charges = markup_revenue = 0.0
    monthly = {}  # "YYYY-MM" -> {"sales": x, "profit": y}
    branch = {}   # branch_name -> {"sales": x, "profit": y}

    for t in tickets:
        lines = list(t.lines.all())
        if not lines:
            continue
        t_sales = sum(line_sales(l) for l in lines)
        t_earnings = sum(line_earnings(l) for l in lines)
        ytd_sales += t_sales
        if t.invoice_date >= month_start:
            month_sales += t_sales
        if t.invoice_date == today:
            today_sales += t_sales
        ticket_revenue += t_earnings
        service_charges += sum(line_service_charges(l) for l in lines)
        markup_revenue += sum(line_markup(l) for l in lines)

        bucket = t.invoice_date.strftime("%Y-%m")
        m = monthly.setdefault(bucket, {"sales": 0.0, "profit": 0.0})
        m["sales"] += t_sales
        m["profit"] += t_earnings

        b = branch.setdefault(t.branch_name or "Unassigned", {"sales": 0.0, "profit": 0.0})
        b["sales"] += t_sales
        b["profit"] += t_earnings

    # Computed once and shared by every tile below - _ledger_balance_deltas
    # replays every ticket's postings, and was being re-run for each of
    # the 6 cash/bank/receivable/payable/GST/TDS figures (plus a Ledger
    # query per group each time), which made this page take ~17s on TiDB.
    deltas = _ledger_balance_deltas(company_id)
    all_groups = list(LedgerGroup.objects.filter(company_id=company_id))
    ledgers_by_group = {}
    for l in Ledger.objects.filter(company_id=company_id):
        ledgers_by_group.setdefault(l.group_id, []).append(l)

    def group_net_balance(group_names):
        keys = {_normalize_group_name(n) for n in group_names}
        groups = [g for g in all_groups if _normalize_group_name(g.name) in keys]
        total = 0.0
        for g in groups:
            for l in ledgers_by_group.get(g.id, []):
                total += float(l.signed_balance) + deltas.get(l.id, 0.0)
        return total

    cash_position = group_net_balance(["Cash-in-Hand"])
    bank_position = group_net_balance(["Bank Accounts"])
    receivables = max(0.0, group_net_balance(["Sundry Debtors"]))
    payables = max(0.0, -group_net_balance(["Sundry Creditors"]))

    def duties_taxes_total(keyword):
        groups = [g for g in all_groups if _normalize_group_name(g.name) == _normalize_group_name("Duties & Taxes")]
        total = 0.0
        for g in groups:
            for l in ledgers_by_group.get(g.id, []):
                if keyword.lower() not in l.name.lower():
                    continue
                total += float(l.signed_balance) + deltas.get(l.id, 0.0)
        return max(0.0, -total)

    gst_payable = duties_taxes_total("GST")
    tds_payable = duties_taxes_total("TDS")

    months_sorted = sorted(monthly.keys())[-6:]
    month_labels = [datetime.strptime(m, "%Y-%m").strftime("%b") for m in months_sorted]

    return JsonResponse({
        "sales": {
            "today_sales": round(today_sales, 2),
            "month_sales": round(month_sales, 2),
            "ytd_sales": round(ytd_sales, 2),
        },
        "revenue": {
            "ticket_revenue": round(ticket_revenue, 2),
            "hotel_revenue": 0, "visa_revenue": 0, "insurance_revenue": 0,
            "service_charges": round(service_charges, 2),
            "markup_revenue": round(markup_revenue, 2),
        },
        "finance": {
            "cash_position": round(cash_position, 2),
            "bank_position": round(bank_position, 2),
            "outstanding_receivables": round(receivables, 2),
            "outstanding_payables": round(payables, 2),
            "bsp_liability": 0,
            "supplier_liability": round(payables, 2),
        },
        "compliance": {
            "gst_payable": round(gst_payable, 2),
            "tds_payable": round(tds_payable, 2),
            "vat_payable": 0,
        },
        "monthly_revenue_trend": [{"label": month_labels[i], "value": round(monthly[m]["sales"], 2)} for i, m in enumerate(months_sorted)],
        "profitability_trend": [{"label": month_labels[i], "value": round(monthly[m]["profit"], 2)} for i, m in enumerate(months_sorted)],
        "product_mix": [
            {"product": "Airline Tickets", "value": round(ticket_revenue, 2)},
            {"product": "Hotels", "value": 0},
            {"product": "Visa", "value": 0},
            {"product": "Insurance", "value": 0},
        ],
        "branch_performance": [
            {"branch_name": name, "sales": round(v["sales"], 2), "profit": round(v["profit"], 2)}
            for name, v in sorted(branch.items(), key=lambda kv: -kv[1]["sales"])
        ],
    })


@csrf_exempt
def ledger_group_delete(request, group_id):
    """
    DELETE /api/ledger-groups/<id>/delete/?company_id=1
    Refuses a system group outright, and any group that still has child
    groups or ledgers under it (Ledger.group and LedgerGroup.parent are
    both on_delete=PROTECT) - matches the confirm dialog's own "This only
    works if no ledgers exist under it" text.
    """
    if request.method != "DELETE":
        return HttpResponseNotAllowed(["DELETE"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    try:
        group = LedgerGroup.objects.get(id=group_id, company_id=company_id)
    except LedgerGroup.DoesNotExist:
        return JsonResponse({"error": "Group not found."}, status=404)
    if group.is_system:
        return JsonResponse({"error": "System groups can't be deleted."}, status=403)

    try:
        group.delete()
    except ProtectedError:
        return JsonResponse(
            {"error": f"\"{group.name}\" still has ledgers or sub-groups under it and can't be deleted."}, status=409
        )
    return JsonResponse({"message": "Group deleted."}, status=200)


@csrf_exempt
def ledger_group_update(request, group_id):
    """
    PUT /api/ledger-groups/<id>/update/?company_id=1
    Body: { "name": "...", "parent_id": 5 }
    System (master) groups can't be edited - matches groups.html's own
    "System group - cannot be modified" guard, enforced server-side too.
    """
    if request.method != "PUT":
        return HttpResponseNotAllowed(["PUT"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    try:
        group = LedgerGroup.objects.get(id=group_id, company_id=company_id)
    except LedgerGroup.DoesNotExist:
        return JsonResponse({"error": "Group not found."}, status=404)
    if group.is_system:
        return JsonResponse({"error": "System groups can't be modified."}, status=403)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    name = (body.get("name") or "").strip()
    parent_id = body.get("parent_id")
    if not name or not parent_id:
        return JsonResponse({"error": "name and parent_id are required"}, status=400)

    try:
        parent = LedgerGroup.objects.get(id=parent_id, company_id=company_id)
    except LedgerGroup.DoesNotExist:
        return JsonResponse({"error": "Parent group not found."}, status=400)

    if LedgerGroup.objects.filter(company_id=company_id, name__iexact=name, parent_id=parent_id).exclude(id=group.id).exists():
        return JsonResponse({"error": f"A group named \"{name}\" already exists under this parent."}, status=409)

    group.name = name
    group.parent = parent
    group.account_type = parent.account_type
    group.save()
    return JsonResponse(model_to_dict(group), status=200)


def parties_customers_list(request):
    """
    GET /api/parties/customers/?company_id=1
    customers.html's own list view (credit limit/utilisation, running
    outstanding) - a different shape than customers_list() above (which
    only feeds Ticket Entry's customer picker), so kept as its own
    endpoint rather than overloading that one. Same real Ledgers
    (ledger_category='DEBTOR') either way - "outstanding" is opening
    balance plus every posted transaction, same convention as Trial
    Balance/Ledger Book (see _ledger_balance_deltas).
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    deltas = _ledger_balance_deltas(company_id)
    customers = Ledger.objects.filter(company_id=company_id, ledger_category="DEBTOR")
    data = [
        {
            "id": c.id, "name": c.name, "code": f"LED-{c.id:05d}",
            "customer_type": c.customer_type or "RETAIL",
            "credit_limit": float(c.credit_limit or 0),
            "credit_days": c.credit_days or 0,
            "outstanding": round(float(c.signed_balance) + deltas.get(c.id, 0.0), 2),
        }
        for c in customers
    ]
    return JsonResponse(data, safe=False)


def parties_suppliers_list(request):
    """
    GET /api/parties/suppliers/?company_id=1
    suppliers.html's own list view - see parties_customers_list's
    docstring, same reasoning. "outstanding" is shown as a positive
    "amount we owe them" figure even though a Sundry Creditor's own
    signed_balance is credit-heavy (negative), matching how Trial
    Balance/this same Ledger's own Sundry Creditors group already
    displays it.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    deltas = _ledger_balance_deltas(company_id)
    suppliers = Ledger.objects.filter(company_id=company_id, ledger_category="CREDITOR")
    data = [
        {
            "id": s.id, "name": s.name, "code": s.supplier_code or f"LED-{s.id:05d}",
            "supplier_type": s.creditor_type or "General Creditor",
            "credit_days": s.credit_days or 0,
            # Clamped at 0 - a ledger that's actually net-debit (we're owed
            # money, e.g. a payment gateway clearing account) isn't a
            # negative "amount payable", it's simply nothing owed.
            "outstanding": max(0.0, round(-(float(s.signed_balance) + deltas.get(s.id, 0.0)), 2)),
        }
        for s in suppliers
    ]
    return JsonResponse(data, safe=False)
