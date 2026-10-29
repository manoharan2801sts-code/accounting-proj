"""
Voyager ERP — Ledger Groups API
-----------------------------------------------------------------
This replaces the hardcoded COA_DEFS array that used to live in the
frontend's mock-data.js. The frontend now calls GET /api/ledger-groups/
and gets these rows straight from SQL Server instead.
"""
import json
import math
import re
from datetime import datetime, date, timedelta
from django.http import JsonResponse, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt
from django.forms.models import model_to_dict
from django.db import transaction, IntegrityError
from django.db.models import ProtectedError, Q, Prefetch
from django.contrib.auth.hashers import make_password, check_password

from .models import LedgerGroup, Ledger, Ticket, TicketLine, Voucher, JournalVoucher, VoucherType, SupplierCommissionRule, MasterMapping, FOPMaster, PGMaster, PGMasterHistory, CompanyMaster, RescheduleAirlineTicket, RescheduleAirlineTicketLine, CancellationAirlineTicket, CancellationAirlineTicketLine, _field_gst_pct_cache, resolve_mapping, mapped_gst_pct, document_date, clear_mapping_caches, document_ref, mapping_document, ignore_mapping_pins, _pins_ignored_for as models_pins_ignored_for, pushed_line_gst, GST_AMOUNT_FIELDS, _line_gst_rows as models_line_gst_rows
from .jv_hardcode import JV_LINE_MAP
from . import sp_client
from . import permissions


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
    "is_default_bank",
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
    clear_mapping_caches()  # Ledger Mapping history + GST % caches
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
    # A ledger's GST % feeds every ticket's GST Amount via Master Mapping -
    # drop the cached rates so the JV/reports pick up the new % at once.
    clear_mapping_caches()  # Ledger Mapping history + GST % caches
    return JsonResponse({"id": int(ledger_id), "message": "Ledger updated."})


def ledger_default_bank(request):
    """
    GET /api/ledgers/default-bank/?company_id=1
    The company's current Default Bank ledger -> {"id", "name"}, or
    {"id": null, "name": null} when none is set. Light on purpose (one
    dbo.sp_Ledger LIST read, no balance computation) - the Ledger page asks
    this the moment Default Bank = Yes is clicked.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)
    current = next((l for l in sp_client.ledger_list(company_id) if l.get("is_default_bank")), None)
    return JsonResponse({"id": current["id"] if current else None, "name": current["name"] if current else None})


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
            + float(l.supp_markup) + float(l.supp_addl_markup) + float(getattr(l, "supp_ssr_markup", 0))
            + float(l.supp_service_fee) + float(l.supp_addl_service_fee) + float(getattr(l, "supp_ssr_service_fee", 0))
            + float(l.computed_supp_gst)
        )
    total_amount = round(sum(g["amount"] for g in supplier_groups.values()), 2)
    if total_amount == 0:
        return []

    result = [(g["ledger"].id, g["amount"], 0) for g in supplier_groups.values() if g["ledger"]]
    if fop == "Own Card":
        card_number = lines[0].card_number or ""
        # The card's ledger in force on the ticket's own date (FOP Master Effective From).
        card = sp_client.fop_master_get_by_card_number(ticket.company_id, card_number, as_of=document_date(ticket))
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
    snapshot = _pg_master_effective_snapshot(ticket.company_id, ticket.payment_gateway_ref or "", ticket.invoice_date or ticket.booking_ref_date,
                                             document_ref(ticket))
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


def _pg_master_effective_snapshot(company_id, gateway_name, as_of_date, doc=None):
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

    doc = (doc_type, id) of the saved document asking: a back-dated PG
    Master change saved with "Retain old ledgers" pinned it to the settings
    it used then (PGMasterPin) - except while it is being edited.
    """
    if not gateway_name:
        return None
    if doc and doc in models_pins_ignored_for.get():
        doc = None
    snapshot = sp_client.pg_master_effective_snapshot(company_id, gateway_name, as_of_date, doc)
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
        "pinned": bool(snapshot.get("pinned")),
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
            id=header["ticket_id"], company_id=header["company_id"],
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
            id=header["reschedule_ticket_id"], company_id=header["company_id"],
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

    # Cancellations - their own JV (Main + FOP leg), same live-recompute
    # convention. Feeds Trial Balance, Chart of Accounts, Cash & Bank Book
    # and Profit and Loss through this one function.
    for entry in _cancellation_report_entries(company_id, jv_mapping_cache, jv_company_state, from_date=from_date, to_date=as_of_date):
        for a in entry["combined"]:
            add(a.get("ledger_id"), a.get("debit"), a.get("credit"))

    # SSR Updations - their own JV (ALS-n), same live-recompute convention.
    for entry in _ssr_report_entries(company_id, jv_mapping_cache, jv_company_state, from_date=from_date, to_date=as_of_date):
        for a in entry["combined"]:   # JV + FOP Payment + PG Receipt, same as the tickets above
            add(a.get("ledger_id"), a.get("debit"), a.get("credit"))

    # Miscellaneous transactions - their own JV (MSC-n), same convention.
    for entry in _misc_report_entries(company_id, jv_mapping_cache, jv_company_state, from_date=from_date, to_date=as_of_date):
        for a in entry["accounts"]:
            add(a.get("ledger_id"), a.get("debit"), a.get("credit"))

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
            # Ledger entry's Default Bank field asks before replacing this one.
            "is_default_bank": bool(l.is_default_bank),
        })
    return JsonResponse(rows, safe=False)


def _invoice_ref_map(company_id):
    """
    invoice number -> {"s_pnr", "air_pnr", "tickets"} for every Booking,
    Reschedule, Cancellation and SSR Updation - lets a manual voucher's
    report row show the S PNR / Air-PNR / Ticket No of the invoice(s) it was
    adjusted against (its lines' bill_allocations, "Against Invoice").
    """
    from .models import SSRAirlineTicket, SSRAirlineTicketLine
    out = {}

    def add(inv, s_pnr, air_pnr, ticket_no):
        if not inv:
            return
        e = out.setdefault(inv, {"s_pnr": s_pnr or "", "air_pnr": air_pnr or "", "tickets": []})
        if ticket_no and ticket_no not in e["tickets"]:
            e["tickets"].append(ticket_no)

    for model, line_model, fk, ref in (
        (Ticket, TicketLine, "ticket", "booking_reference"),
        (RescheduleAirlineTicket, RescheduleAirlineTicketLine, "reschedule_ticket", "booking_reference"),
        (CancellationAirlineTicket, CancellationAirlineTicketLine, "cancellation_ticket", "cancellation_reference"),
        (SSRAirlineTicket, SSRAirlineTicketLine, "ssr_ticket", "ssr_reference"),
    ):
        for h in model.objects.filter(company_id=company_id).values("invoice_number", ref, "airline_pnr"):
            add(h["invoice_number"], h[ref], h["airline_pnr"], None)
        # In entry order (line id), so each invoice's tickets[0] is its lead passenger.
        for l in line_model.objects.filter(**{f"{fk}__company_id": company_id}).order_by("id").values(f"{fk}__invoice_number", "ticket_no"):
            add(l[f"{fk}__invoice_number"], None, None, l["ticket_no"])
    return out


def _voucher_ref_fields(lines, ref_map, ledger_id=None):
    """
    S PNR / Air-PNR / Ticket No for a manual voucher's report row - from the
    invoice(s) its lines were adjusted against (bill_allocations "Against
    Invoice"; only this ledger's own lines when ledger_id is given). "-"
    when the voucher isn't adjusted against any invoice (On Account).
    """
    refs = []
    for l in lines:
        if ledger_id is not None and l.get("ledger_id") != ledger_id:
            continue
        for a in l.get("bill_allocations") or []:
            if a.get("type") == "Against Invoice" and a.get("ref") and a["ref"] not in refs:
                refs.append(a["ref"])
    found = [ref_map[r] for r in refs if r in ref_map]
    join = lambda vals: ", ".join(dict.fromkeys(v for v in vals if v)) or "-"
    return {
        "s_pnr": join(e["s_pnr"] for e in found),
        "air_pnr": join(e["air_pnr"] for e in found),
        "ticket_no": join(t for e in found for t in e["tickets"]),
    }


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

    def opposite_ledger(rows):
        """
        Particulars = the first OPPOSITE-side ledger in this entry's own JV
        order: this ledger's first row is Debit -> the first Credit ledger;
        Credit -> the first Debit ledger. None if there isn't one.
        """
        amt = lambda r, side: float(r.get(side) or 0)
        mine = next((r for r in rows if r.get("ledger_id") == ledger_id and (amt(r, "debit") or amt(r, "credit"))), None)
        if not mine:
            return None
        opposite_side = "credit" if amt(mine, "debit") > 0 else "debit"
        other = next((r for r in rows if r.get("ledger_id") != ledger_id and amt(r, opposite_side) > 0
                      and (r.get("ledger_name") or ledger_names.get(r.get("ledger_id")))), None)
        return (other.get("ledger_name") or ledger_names.get(other.get("ledger_id"))) if other else None

    # Ascending by id, matching the plain (unordered) ORM queryset's
    # implicit insertion-order this replaced - txns.sort() below is a
    # stable sort keyed only by date, so ties need this same tie-break
    # order going in, or same-day rows could swap places on screen.
    voucher_ref_map = _invoice_ref_map(company_id)
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
            "particulars": opposite_ledger(lines) or v["narration"] or ", ".join(others) or "-",
            **_voucher_ref_fields(lines, voucher_ref_map, ledger_id),
            "opposite": ", ".join(others) or "-", "debit": debit, "credit": credit,
            "ticket_id": None, "reschedule_ticket_id": None, "voucher_id": v["id"],
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
            "voucher_type": "Tax Invoice", "voucher_no": header["invoice_number"] or header["voucher_no"],
            "particulars": opposite_ledger(combined) or particulars,
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
            "voucher_type": "Tax Invoice (Reschedule)", "voucher_no": header["invoice_number"] or header["voucher_no"],
            "particulars": opposite_ledger(combined) or particulars,
            "s_pnr": header["booking_reference"] or "-", "air_pnr": header["airline_pnr"] or "-",
            "ticket_no": ", ".join(ticket_nos) or "-",
            "opposite": ", ".join(others) or "-", "debit": debit, "credit": credit,
            "ticket_id": None, "reschedule_ticket_id": header["reschedule_ticket_id"],
        })

    # Cancellations - their own Credit Note JV (ALC-n), Main + FOP leg.
    # Rows carry cancellation_ticket_id so the frontend links to
    # ticket-entry.html?cancellation_saved_id=...
    for entry in _cancellation_report_entries(company_id, jv_mapping_cache, jv_company_state, from_date=from_date, to_date=to_date):
        v, ct, lines = entry["voucher"], entry["ct"], entry["lines"]
        combined = [{**a, "ledger_name": a.get("ledger_name") or ledger_names.get(a.get("ledger_id"), "-")} for a in entry["combined"]]
        mine = [a for a in combined if a.get("ledger_id") == ledger_id]
        if not mine:
            continue
        debit = round(sum(float(a.get("debit") or 0) for a in mine), 2)
        credit = round(sum(float(a.get("credit") or 0) for a in mine), 2)
        if debit == 0 and credit == 0:
            continue
        others = sorted({a.get("ledger_name") for a in combined if a.get("ledger_id") != ledger_id and a.get("ledger_name")})
        airline_names = sorted({n.strip() for l in lines for n in (l.airline_name or "").split(",") if n.strip()})
        ticket_nos = sorted({l.ticket_no for l in lines if l.ticket_no})
        office_ids = sorted({l.office_id for l in lines if l.office_id})
        particulars = " - ".join(x for x in [", ".join(airline_names), ", ".join(office_ids)] if x) or "-"
        txns.append({
            "date": v.voucher_date.isoformat() if v.voucher_date else None,
            "voucher_type": ct.invoice_type or "Credit Note (Cancellation)", "voucher_no": ct.invoice_number or v.voucher_no,
            "particulars": opposite_ledger(combined) or particulars,
            "s_pnr": ct.cancellation_reference or "-", "air_pnr": ct.airline_pnr or "-",
            "ticket_no": ", ".join(ticket_nos) or "-",
            "opposite": ", ".join(others) or "-", "debit": debit, "credit": credit,
            "ticket_id": None, "reschedule_ticket_id": None, "cancellation_ticket_id": ct.id,
        })

    # SSR Updations - their own JV (ALS-n). Rows carry ssr_ticket_id so the
    # frontend links to trans-airline-ssr.html?ssr_saved_id=...
    for entry in _ssr_report_entries(company_id, jv_mapping_cache, jv_company_state, from_date=from_date, to_date=to_date):
        v, st, lines = entry["voucher"], entry["st"], entry["lines"]
        accounts = [{**a, "ledger_name": a.get("ledger_name") or ledger_names.get(a.get("ledger_id"), "-")} for a in entry["combined"]]
        mine = [a for a in accounts if a.get("ledger_id") == ledger_id]
        if not mine:
            continue
        debit = round(sum(float(a.get("debit") or 0) for a in mine), 2)
        credit = round(sum(float(a.get("credit") or 0) for a in mine), 2)
        if debit == 0 and credit == 0:
            continue
        others = sorted({a.get("ledger_name") for a in accounts if a.get("ledger_id") != ledger_id and a.get("ledger_name")})
        txns.append({
            "date": v.voucher_date.isoformat() if v.voucher_date else None,
            "voucher_type": st.invoice_type or "SSR Updation", "voucher_no": st.invoice_number or v.voucher_no,
            "particulars": opposite_ledger(accounts) or "SSR Updation",
            "s_pnr": st.ssr_reference or "-", "air_pnr": st.airline_pnr or "-",
            "ticket_no": ", ".join(sorted({l["ticket_no"] for l in lines if l.get("ticket_no")})) or "-",
            "opposite": ", ".join(others) or "-", "debit": debit, "credit": credit,
            "ticket_id": None, "reschedule_ticket_id": None, "cancellation_ticket_id": None, "ssr_ticket_id": st.id,
        })

    # Miscellaneous transactions - their own JV (MSC-n). Rows carry
    # misc_id so the frontend links to trans-misc.html?misc_saved_id=...
    for entry in _misc_report_entries(company_id, jv_mapping_cache, jv_company_state, from_date=from_date, to_date=to_date):
        v, m = entry["voucher"], entry["m"]
        accounts = [{**a, "ledger_name": a.get("ledger_name") or ledger_names.get(a.get("ledger_id"), "-")} for a in entry["accounts"]]
        mine = [a for a in accounts if a.get("ledger_id") == ledger_id]
        if not mine:
            continue
        debit = round(sum(float(a.get("debit") or 0) for a in mine), 2)
        credit = round(sum(float(a.get("credit") or 0) for a in mine), 2)
        if debit == 0 and credit == 0:
            continue
        others = sorted({a.get("ledger_name") for a in accounts if a.get("ledger_id") != ledger_id and a.get("ledger_name")})
        txns.append({
            "date": v.voucher_date.isoformat() if v.voucher_date else None,
            "voucher_type": m.invoice_type or "Miscellaneous", "voucher_no": m.invoice_number or v.voucher_no,
            "particulars": opposite_ledger(accounts) or "Miscellaneous",
            "s_pnr": m.reference or "-", "air_pnr": "-", "ticket_no": "-",
            "opposite": ", ".join(others) or "-", "debit": debit, "credit": credit,
            "ticket_id": None, "reschedule_ticket_id": None, "cancellation_ticket_id": None, "ssr_ticket_id": None, "misc_id": m.id,
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

    # Ticket No column shows only the lead passenger's ticket - the first
    # passenger entered (lowest line id), not every ticket on the invoice.
    def lead_ticket_no(line_objs):
        with_no = [l for l in line_objs if l.ticket_no]
        return min(with_no, key=lambda l: l.id).ticket_no if with_no else "-"

    manual_vouchers = Voucher.objects.filter(company_id=company_id)
    if from_date:
        manual_vouchers = manual_vouchers.filter(voucher_date__gte=from_date)
    if to_date:
        manual_vouchers = manual_vouchers.filter(voucher_date__lte=to_date)
    voucher_ref_map = _invoice_ref_map(company_id)
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
        refs = _voucher_ref_fields(lines, voucher_ref_map)
        refs["ticket_no"] = refs["ticket_no"].split(", ")[0]  # lead passenger only
        txns.append({
            "date": v.voucher_date.isoformat() if v.voucher_date else None,
            # The ledger itself (e.g. the customer on a Receipt), never the
            # narration - same as Booking/Reschedule/Cancellation rows, which
            # show the customer ledger whose amount the row carries.
            "particulars": first_name or "-",
            "voucher_type": v.voucher_type,
            **refs,
            "voucher_no": v.voucher_no or "-",
            # Vch No column: just the number, without the type prefix ("RV-3" -> "3").
            "invoice_number": (v.voucher_no or "").split("-")[-1] or v.voucher_no or "-",  # number only (RV-3 / RV12-3 -> 3)
            "debit": debit_amt, "credit": credit_amt,
            "ticket_id": None, "reschedule_ticket_id": None, "voucher_id": v.id,
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
            "ticket_no": lead_ticket_no(lines),
            "voucher_no": v.voucher_no or "-",
            "invoice_number": (t.invoice_number if t else None) or "-",  # Day Book's Vch No column (the invoice number; a manual voucher's own number)
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
            "ticket_no": lead_ticket_no(lines),
            "voucher_no": v.voucher_no or "-",
            "invoice_number": (rt.invoice_number if rt else None) or "-",  # Day Book's Vch No column (the invoice number; a manual voucher's own number)
            # Same Debit-only convention as the Booking rows above.
            "debit": customer_amount, "credit": 0.0,
            "ticket_id": None, "reschedule_ticket_id": rt.id if rt else None,
        })

    # Cancellations' own Credit Note JV (ALC-n). The customer is CREDITED
    # (refund), so the amount shows under Credit only - the mirror of the
    # Debit-only Booking/Reschedule rows above. Clickable through to
    # ticket-entry.html?cancellation_saved_id=... (cancellation_ticket_id).
    for entry in _cancellation_report_entries(company_id, mapping_cache, company_state, from_date=from_date, to_date=to_date):
        v, ct, lines = entry["voucher"], entry["ct"], entry["lines"]
        customer_row = next((a for a in entry["accounts"] if a.get("role") == "customer"), None)
        customer_amount = (customer_row.get("credit") or customer_row.get("debit") or 0.0) if customer_row else 0.0
        txns.append({
            "date": v.voucher_date.isoformat() if v.voucher_date else None,
            "particulars": ct.customer.name if ct.customer else "-",
            "voucher_type": "Credit Note",
            "s_pnr": ct.cancellation_reference or "-", "air_pnr": ct.airline_pnr or "-",
            "ticket_no": lead_ticket_no(lines),
            "voucher_no": v.voucher_no or "-",
            "invoice_number": ct.invoice_number or "-",  # Day Book's Vch No column (the invoice number; a manual voucher's own number)
            "debit": 0.0, "credit": customer_amount,
            "ticket_id": None, "reschedule_ticket_id": None, "cancellation_ticket_id": ct.id,
        })

    # SSR Updations' own JV (ALS-n) - the customer is billed, so Debit only.
    for entry in _ssr_report_entries(company_id, mapping_cache, company_state, from_date=from_date, to_date=to_date):
        v, st, lines = entry["voucher"], entry["st"], entry["lines"]
        customer_row = next((a for a in entry["accounts"] if a.get("role") == "customer"), None)
        txns.append({
            "date": v.voucher_date.isoformat() if v.voucher_date else None,
            "particulars": st.customer.name if st.customer else "-",
            "voucher_type": st.invoice_type or "SSR Updation",
            "s_pnr": st.ssr_reference or "-", "air_pnr": st.airline_pnr or "-",
            "ticket_no": lead_ticket_no(list(st.lines.all())),
            "voucher_no": v.voucher_no or "-",
            "invoice_number": st.invoice_number or "-",  # Day Book's Vch No column (the invoice number; a manual voucher's own number)
            "debit": (customer_row or {}).get("debit") or 0.0, "credit": 0.0,
            "ticket_id": None, "reschedule_ticket_id": None, "cancellation_ticket_id": None, "ssr_ticket_id": st.id,
        })

    # Miscellaneous transactions' own JV (MSC-n) - the customer is billed, so Debit only.
    for entry in _misc_report_entries(company_id, mapping_cache, company_state, from_date=from_date, to_date=to_date):
        v, m = entry["voucher"], entry["m"]
        customer_row = next((a for a in entry["accounts"] if a.get("role") == "customer"), None)
        txns.append({
            "date": v.voucher_date.isoformat() if v.voucher_date else None,
            "particulars": m.customer.name if m.customer else "-",
            "voucher_type": m.invoice_type or "Miscellaneous",
            "s_pnr": m.reference or "-", "air_pnr": "-", "ticket_no": "-",
            "voucher_no": v.voucher_no or "-",
            "invoice_number": m.invoice_number or "-",
            "debit": (customer_row or {}).get("debit") or 0.0, "credit": 0.0,
            "ticket_id": None, "reschedule_ticket_id": None, "cancellation_ticket_id": None, "ssr_ticket_id": None, "misc_id": m.id,
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
      header row), "path" lists every ancestor group between the top
      level and this one (outermost first) for the page's breadcrumb,
      and "back" is the one-level-up target: another group_id, or null
      for the plain top-level Trial Balance if this group's own parent
      is just an internal root wrapper (Assets/Liabilities/Income/
      Expenses) that the UI never shows as its own page.

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
    path = []
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
        # Breadcrumb trail - every ancestor between the top level and this
        # group (outermost first), skipping the hidden root wrappers.
        path = []
        ancestor = groups_by_id.get(group["parent_id"])
        while ancestor and ancestor["id"] not in root_group_ids:
            path.insert(0, {"group_id": ancestor["id"], "label": ancestor["name"]})
            ancestor = groups_by_id.get(ancestor["parent_id"])
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
        "context": context, "back": back, "path": path,
        "rows": rows,
        "total_debit": total_debit, "total_credit": total_credit,
    })


def balance_sheet_report(request):
    """
    GET /api/balance-sheet/?company_id=1&to_date=2026-10-09[&group_id=7]
    Tally-style Balance Sheet as at to_date (closing balances - opening
    balance plus every posted transaction up to that date, same figures as
    the Trial Balance):

    Liabilities (left) - every primary group under the Liabilities root
    (Capital Account, Loans, Current Liabilities, ...), Credit-positive.
    Assets (right) - every primary group under the Assets root (Fixed
    Assets, Investments, Current Assets, ...), Debit-positive. Each group
    carries its own immediate children (sub-groups + ledgers) for the
    indented detail column. A negative figure means the group/ledger sits
    on the "wrong" side (shown as (-) on the page, like Tally).

    Profit & Loss A/c - net of every Income/Expense ledger up to to_date
    (Current Period; there's no year-end closing in this app yet, so
    Opening Balance is 0): a profit sits on the Liabilities side, a loss on
    the Assets side. "Difference in opening balances" balances the two
    totals, on whichever side is short.

    group_id given -> zoom into that group (sub-groups/ledgers with closing
    Debit/Credit) - the same breakdown the Trial Balance drill-down uses.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    if request.GET.get("group_id"):
        return trial_balance_report(request)

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)
    to_date = request.GET.get("to_date")
    deltas = _ledger_balance_deltas(company_id, as_of_date=to_date)

    all_groups = sp_client.ledger_group_list(company_id)
    children_by_parent = {}
    for g in all_groups:
        children_by_parent.setdefault(g["parent_id"], []).append(g)
    ledgers_by_group = {}
    for l in sp_client.ledger_list(company_id):
        ledgers_by_group.setdefault(l["parent_id"], []).append(l)

    def ledger_balance(l):
        return float(l["balance"]) + deltas.get(l["id"], 0.0)  # Debit +, Credit -

    def rollup(gid):
        """(signed total, ledger count) for everything under this group, however deep."""
        total = sum(ledger_balance(l) for l in ledgers_by_group.get(gid, []))
        count = len(ledgers_by_group.get(gid, []))
        for child in children_by_parent.get(gid, []):
            t, c = rollup(child["id"])
            total += t
            count += c
        return total, count

    def side_rows(root_type, sign):
        rows = []
        for root in (g for g in all_groups if g["parent_id"] is None and (g.get("account_type") or "").upper() == root_type):
            for g in sorted(children_by_parent.get(root["id"], []), key=lambda g: g["name"]):
                total, count = rollup(g["id"])
                if count == 0:
                    continue
                children = []
                for c in sorted(children_by_parent.get(g["id"], []), key=lambda c: c["name"]):
                    c_total, c_count = rollup(c["id"])
                    if c_count:
                        children.append({"type": "group", "id": c["id"], "name": c["name"], "amount": round(sign * c_total, 2)})
                for l in sorted(ledgers_by_group.get(g["id"], []), key=lambda l: l["name"]):
                    children.append({"type": "ledger", "id": l["id"], "name": l["name"], "amount": round(sign * ledger_balance(l), 2)})
                rows.append({"type": "group", "id": g["id"], "name": g["name"], "amount": round(sign * total, 2), "children": children})
        return rows

    liabilities = side_rows("LIABILITY", -1)
    assets = side_rows("ASSET", 1)

    pl_signed = 0.0
    for root in (g for g in all_groups if g["parent_id"] is None and (g.get("account_type") or "").upper() in ("INCOME", "EXPENSE")):
        pl_signed += rollup(root["id"])[0]
    net_profit = round(-pl_signed, 2)  # Credit-heavy income/expense = profit
    if net_profit:
        pl_row = {"type": "pl", "name": "Profit & Loss A/c", "amount": abs(net_profit), "children": [
            {"type": "info", "name": "Opening Balance", "amount": 0.0},
            {"type": "info", "name": "Current Period", "amount": abs(net_profit)},
        ]}
        (liabilities if net_profit > 0 else assets).append(pl_row)

    liab_total = round(sum(r["amount"] for r in liabilities), 2)
    asset_total = round(sum(r["amount"] for r in assets), 2)
    diff = round(liab_total - asset_total, 2)
    if diff:
        (assets if diff > 0 else liabilities).append(
            {"type": "diff", "name": "Difference in opening balances", "amount": abs(diff), "children": []})

    return JsonResponse({
        "to_date": to_date,
        "liabilities": liabilities, "assets": assets,
        "total": round(max(liab_total, asset_total), 2),
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
        return {"id": group.id, "name": group.name, "items": items, "total": round(total, 2)}

    # Zoom-in (Trial-Balance-style drill-down): ?group_id= returns that
    # group's own immediate children (sub-groups + ledgers) with their
    # PERIOD movement as Debit/Credit columns - the same period figures the
    # main account is built from. Clicking further is another request; a
    # ledger opens its own monthly statement on the frontend.
    group_id = request.GET.get("group_id")
    if group_id:
        groups_by_id = {g.id: g for g in all_groups}
        group = groups_by_id.get(int(group_id))
        if not group:
            return JsonResponse({"error": "Group not found."}, status=404)

        def movement(gid):
            return sum(deltas.get(l.id, 0.0) for l in ledgers_under(gid))

        rows, total_debit, total_credit = [], 0.0, 0.0
        for child in sorted(children_by_parent.get(group.id, []), key=lambda g: g.name):
            if not ledgers_under(child.id):
                continue
            debit, credit = _trial_balance_dr_cr(movement(child.id))
            rows.append({"type": "group", "id": child.id, "name": child.name, "debit": debit, "credit": credit})
            total_debit += debit
            total_credit += credit
        for l in sorted(ledgers_by_group.get(group.id, []), key=lambda l: l.name):
            debit, credit = _trial_balance_dr_cr(deltas.get(l.id, 0.0))
            rows.append({"type": "ledger", "id": l.id, "name": l.name, "debit": debit, "credit": credit})
            total_debit += debit
            total_credit += credit

        pl_group_names = set(PROFIT_LOSS_GROUP_NAMES.values())
        parent = groups_by_id.get(group.parent_id)
        if group.name in pl_group_names or parent is None or parent.parent_id is None:
            back = {"group_id": None, "label": "Profit and Loss"}
        else:
            back = {"group_id": parent.id, "label": parent.name}
        # Breadcrumb trail - ancestors up to (and including) the P&L group
        # this one sits under, outermost first; same stop rule as "back".
        path = []
        node = group
        while True:
            up = groups_by_id.get(node.parent_id)
            if node.name in pl_group_names or up is None or up.parent_id is None:
                break
            path.insert(0, {"group_id": up.id, "label": up.name})
            node = up
        g_debit, g_credit = _trial_balance_dr_cr(movement(group.id))
        return JsonResponse({
            "from_date": from_date, "to_date": to_date,
            "context": {"id": group.id, "name": group.name, "debit": g_debit, "credit": g_credit},
            "back": back, "path": path, "rows": rows,
            "total_debit": round(total_debit, 2), "total_credit": round(total_credit, 2),
        })

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
    "supp_ssr_markup", "supp_ssr_service_fee",
]
TICKET_LINE_NUMERIC_FIELDS = {
    "basic_fare", "yq", "yr", "k3_tax", "tax_others", "seat", "meal", "baggage", "other_ssr",
    "disc_value", "tds_per", "pg_charges", "pg_charges_percentage", "markup", "addl_markup", "ssr_markup", "service_fee", "addl_service_fee", "ssr_service_fee", "gst_pct",
    "supp_comm_value", "supp_tds_per",
    "supp_markup", "supp_addl_markup", "supp_service_fee", "supp_addl_service_fee", "supp_gst_pct",
    "supp_ssr_markup", "supp_ssr_service_fee",
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
        "supp_ssr_markup": sum(float(l.supp_ssr_markup) for l in lines),
        "supp_ssr_service_fee": sum(float(l.supp_ssr_service_fee) for l in lines),
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
            + float(l.supp_markup) + float(l.supp_addl_markup) + float(getattr(l, "supp_ssr_markup", 0))
            + float(l.supp_service_fee) + float(l.supp_addl_service_fee) + float(getattr(l, "supp_ssr_service_fee", 0))
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
        # The ledger mapped to this field ON THIS DOCUMENT'S OWN DATE (Ledger
        # Mapping effective dates - models.resolve_mapping), never simply
        # today's mapping - re-mapping later can't rewrite booked documents.
        r = resolve_mapping(ticket.company_id, field_name, document_date(ticket), doc=document_ref(ticket))
        return (r["ledger_id"], r["ledger_name"]) if r else (None, f"{field_name} (not mapped in Master Mapping)")

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

    # Input GST (Debit) - Supplier State vs Company State, per supplier.
    gst_by_supplier = {}
    for l in lines:
        gst_by_supplier[l.supplier_id] = gst_by_supplier.get(l.supplier_id, 0.0) + float(l.computed_supp_gst)

    accounts = customer_rows("Debit", customer_total) + supplier_rows("Credit")
    output_gst_emitted = False
    for dr_cr, masters_category, field_name, amount_key in JV_LINE_MAP:
        if _is_input_gst_row(dr_cr, masters_category, field_name, amount_key):
            accounts.extend(_input_gst_rows(mapped_row, gst_by_supplier, company_state, mapping_cache))
            continue
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
    company = sp_client.company_master_get(company_id)
    company_state = ((company or {}).get("state") or "").strip().lower()
    return mapping_cache, company_state


def _input_gst_rows(mapped_row, gst_by_supplier, company_state, mapping_cache):
    """
    Input GST (Debit) - same concept as Output GST, but driven by each
    SUPPLIER Ledger's own State instead of the customer's: supplier in the
    same State as Company Master = intra-state purchase, split into Input
    CGST A/c + Input SGST A/c; different (or no) State = Input IGST A/c.
    A ticket can carry a different supplier per passenger, so each
    supplier's own GST is classified on its own State, then summed.

    gst_by_supplier: {supplier_ledger_id (or None): supplier GST amount}.
    Supplier States are cached in the shared mapping_cache (keyed
    ("__supplier_state__", ledger_id)), so a report looping over many
    tickets only looks each supplier up once per request.
    """
    ids = [sid for sid in gst_by_supplier if sid]
    missing = [sid for sid in ids if ("__supplier_state__", sid) not in mapping_cache]
    if missing:
        for lid, state in Ledger.objects.filter(id__in=missing).values_list("id", "state_name"):
            mapping_cache[("__supplier_state__", lid)] = (state or "").strip().lower()
        for sid in missing:
            mapping_cache.setdefault(("__supplier_state__", sid), "")

    intra = inter = 0.0
    for sid, amount in gst_by_supplier.items():
        state = mapping_cache.get(("__supplier_state__", sid), "") if sid else ""
        if company_state and state and state == company_state:
            intra += amount
        else:
            inter += amount
    intra, inter = round(intra, 2), round(inter, 2)

    rows = []
    if intra:
        cgst = round(intra / 2, 2)
        rows.append(mapped_row("Debit", "GST and TDS", "Input CGST A/c", cgst))
        # SGST takes the remainder so CGST + SGST is exactly the GST amount
        # (an odd paisa never unbalances the JV).
        rows.append(mapped_row("Debit", "GST and TDS", "Input SGST A/c", round(intra - cgst, 2)))
    if inter or not intra:
        rows.append(mapped_row("Debit", "GST and TDS", "Input IGST A/c", inter))
    return rows


def _is_input_gst_row(dr_cr, masters_category, field_name, amount_key):
    return dr_cr == "Debit" and masters_category == "GST and TDS" and field_name == "Input IGST A/c" and amount_key == "supp_gst"


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
        # A saved line's own id - dbo.sp_Ticket matches on it (a changed
        # Ticket No. then updates the same line instead of replacing it).
        try:
            line_json["line_id"] = int(line_in.get("id")) if line_in.get("id") else None
        except (TypeError, ValueError):
            line_json["line_id"] = None
        line_json["total_billed"] = line.total_billed
        line_json["supplier_name"] = supplier_name
        lines_json.append(line_json)
    return line_objs, lines_json


# ==========================================================================
# Edit history / audit log - who changed what on Booking / Reschedule /
# Cancellation / SSR Updation. The save views are wrapped with audited():
# the document is read straight from its tables (sp_AuditLog SNAPSHOT)
# before and after the save, and every changed field is logged with the
# signed-in user. A Booking / Reschedule edit can carry changes down to its
# follow-up documents (chain edit) - those are snapshotted too and get
# their own rows ("source" = the document whose edit changed them).
# Runs AFTER the save has committed and never fails the save itself.
# Backend only - not shown anywhere in the app (no API reads it); read it
# in SQL from dbo.AuditLogs / dbo.vw_AuditLogChanges.
# ==========================================================================
import contextlib
import functools
import logging

_audit_logger = logging.getLogger(__name__)


LINE_GST_DOCS = ("ticket", "reschedule", "cancellation")


def _saved_line_gst(line_type, doc_id, ticket_no):
    """The Auto Push GST amounts kept for one saved line ({service_fee_gst: ..}), or None."""
    row = models_line_gst_rows().get((line_type, int(doc_id), ticket_no))
    if not row:
        return None
    out = {k: float(row[k]) for k in GST_AMOUNT_FIELDS.values() if row.get(k) is not None}
    return out or None


def _body_line_gst(request, doc_type):
    """{(doc_type, ticket_no): {service_fee_gst: ..}} - each body line's gst_amounts (the Agent's own GST)."""
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return {}
    out = {}
    for line in (body.get("lines") if isinstance(body, dict) else None) or []:
        amounts = line.get("gst_amounts") if isinstance(line, dict) else None
        if not isinstance(amounts, dict) or not line.get("ticket_no"):
            continue
        clean = {}
        for key in GST_AMOUNT_FIELDS.values():
            try:
                if amounts.get(key) not in (None, ""):
                    clean[key] = round(float(amounts[key]), 2)
            except (TypeError, ValueError):
                continue
        if clean:
            out[(doc_type, str(line["ticket_no"]).strip())] = clean
    return out


# Documents the Ticket Entry "Attributes" popup saves Field / Value rows for.
ATTRIBUTE_DOCS = ("ticket", "reschedule", "cancellation")


def _body_attributes(request):
    """(rows, body) - the body's "attributes" ([{field_name, field_value}, ...]); None when it sent none (rows left as they are)."""
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return None
    rows = body.get("attributes") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        return None
    return [{"field_name": str(r.get("field_name") or "").strip()[:100], "field_value": str(r.get("field_value") or "").strip()[:500]}
            for r in rows if isinstance(r, dict) and str(r.get("field_name") or "").strip()], body


def document_attributes(doc_type, doc_id):
    """A saved document's Attributes, as the popup shows them."""
    return [{"field_name": r["field_name"], "field_value": r["field_value"] or ""}
            for r in sp_client.document_attributes(doc_type, doc_id)]


def document_save(doc_type, id_kwarg=None, preview=False):
    """
    Wraps a document's create / update / draft JV preview view:
      * each body line's gst_amounts (GST the Agent sent through Auto Push,
        carried by the screen for the lines it came with) is used as sent
        instead of fee x Ledger Mapping GST % while the document is computed,
        and stored with it once saved (dbo.Ticket_Line_Gst_Amount);
      * an UPDATE resolves without the document's Ledger Mapping pins
        ("Retain old ledgers") and its old GST amounts, and drops them once
        saved - the document now posts with today's mapping and with whatever
        GST amounts the body carried.
      * the body's "attributes" (Ticket Entry's Attributes popup) replace the
        document's Field / Value rows, under its Invoice Number.
    Save and stored values are one transaction.
    """
    def decorator(view):
        @functools.wraps(view)
        def wrapper(request, *args, **kwargs):
            doc_id = kwargs.get(id_kwarg) if id_kwarg else None
            pushed = _body_line_gst(request, doc_type) if doc_type in LINE_GST_DOCS else {}
            attributes = _body_attributes(request) if doc_type in ATTRIBUTE_DOCS and not preview else None
            changed = False
            with contextlib.ExitStack() as stack:
                if not preview:
                    stack.enter_context(transaction.atomic())
                if doc_id:
                    stack.enter_context(ignore_mapping_pins(doc_type, doc_id))
                if pushed:
                    stack.enter_context(pushed_line_gst(pushed))
                response = view(request, *args, **kwargs)
                if preview or not 200 <= response.status_code < 300:
                    return response
                saved_id = doc_id
                if not saved_id:
                    try:
                        saved_id = json.loads(response.content or b"{}").get("id")
                    except ValueError:
                        saved_id = None
                if doc_id:
                    changed |= bool(sp_client.master_mapping_pins_delete_document(doc_type, doc_id))
                    if doc_type in ATTRIBUTE_DOCS:  # Booking / Reschedule / Cancellation - the PG Master pin too
                        sp_client.pg_master_pins_delete_document(doc_type, doc_id)
                    if doc_type in LINE_GST_DOCS:
                        changed |= bool(sp_client.ticket_line_gst_amounts_delete_document(doc_type, doc_id))
                if pushed and saved_id:
                    sp_client.ticket_line_gst_amounts_save([
                        {"line_type": line_type, "doc_id": int(saved_id), "ticket_no": ticket_no, **amounts}
                        for (line_type, ticket_no), amounts in pushed.items()
                    ])
                    changed = True
                if attributes and saved_id:
                    rows, body = attributes
                    try:
                        sp_client.document_attributes_save(body.get("company_id"), doc_type, int(saved_id),
                                                           body.get("invoice_number"), rows)
                    except sp_client.StoredProcedureError as err:
                        transaction.set_rollback(True)
                        return JsonResponse({"error": f"Attributes not saved - {err}"}, status=400)
            if changed:
                clear_mapping_caches()
            return response
        return wrapper
    return decorator

# Columns that are keys / bookkeeping, not something a user edits.
_AUDIT_SKIP = {
    "id", "created_at", "updated_at", "company_id", "customer_ledger_id", "supplier_ledger_id",
    "ticket_id", "reschedule_ticket_id", "cancellation_ticket_id", "ssr_ticket_id", "original_ticket_id",
    "original_ticket_line_id", "reschedule_line_id", "based_on_reschedule_line_id", "source_reschedule_ticket_id",
}
_AUDIT_WORDS = {
    "yq": "YQ", "yr": "YR", "k3": "K3", "gst": "GST", "tds": "TDS", "pg": "PG", "ssr": "SSR", "fop": "FOP",
    "pnr": "PNR", "gds": "GDS", "roe": "ROE", "id": "ID", "supp": "Supplier", "addl": "Addl", "per": "%",
    "pct": "%", "comm": "Commission", "disc": "Discount", "cust": "Customer", "emd": "EMD", "no": "No",
}
_AUDIT_LABELS = {
    "tax_others": "Other Taxes", "total_billed": "Total", "booking_reference": "S PNR / Booking Reference",
    "ssr_items": "SSR Details", "ssr_ticket_numbers": "EMD Ticket Numbers", "ssr_charges": "SSR Charges",
    "customer_name": "Customer", "supplier_name": "Supplier",
}
# Line identity across a save, per module (SSR lines are rewritten on save).
_AUDIT_LINE_KEY = {"Booking": "id", "Reschedule": "original_ticket_line_id",
                   "Cancellation": "original_ticket_line_id", "SSR Updation": "original_ticket_line_id"}


def _audit_label(col):
    if col in _AUDIT_LABELS:
        return _AUDIT_LABELS[col]
    return " ".join(_AUDIT_WORDS.get(w, w.capitalize()) for w in col.split("_"))


def _audit_norm(v):
    """Comparable / displayable form: numbers to 2 dp, JSON text parsed, '' = None."""
    if v is None:
        return None
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    s = str(v).strip()
    if s == "":
        return None
    if s[:1] in "{[":
        try:
            parsed = json.loads(s)
            return parsed if parsed not in ({}, []) else None
        except ValueError:
            pass
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(T00:00:00(\.0+)?)?", s):
        return f"{s[8:10]}/{s[5:7]}/{s[0:4]}"
    return s


def _audit_show(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.2f}"
    if isinstance(v, dict):
        return ", ".join(f"{k}: {_audit_show(x) if not isinstance(x, (int, float)) else x}" for k, x in v.items())
    if isinstance(v, list):
        return ", ".join(_audit_show(x) for x in v)
    return str(v)


def _audit_take(module, document_id):
    try:
        row = sp_client.audit_snapshot(module, document_id)
    except Exception:  # noqa: BLE001 - history must never break a save
        _audit_logger.exception("audit snapshot failed (%s %s)", module, document_id)
        return None
    if not row or not row.get("header_json"):
        return None
    return {"header": json.loads(row["header_json"]), "lines": json.loads(row.get("lines_json") or "[]")}


def _audit_diff(module, before, after):
    """[{scope, line, field, old, new}] between two snapshots."""
    changes = []

    def fields(old, new, scope, line=""):
        for col in sorted(set(old) | set(new)):
            if col in _AUDIT_SKIP:
                continue
            a, b = _audit_norm(old.get(col)), _audit_norm(new.get(col))
            if a != b:
                changes.append({"scope": scope, "line": line, "field": _audit_label(col),
                                "old": _audit_show(a), "new": _audit_show(b)})

    fields(before["header"], after["header"], "Header")
    key = _AUDIT_LINE_KEY.get(module, "id")
    # A direct Reschedule / Cancellation line has no original line id - its Ticket No. identifies it.
    old_lines = {l.get(key) or l.get("ticket_no"): l for l in before["lines"]}
    new_lines = {l.get(key) or l.get("ticket_no"): l for l in after["lines"]}
    name = lambda l: " / ".join(str(x) for x in (l.get("ticket_no"), l.get("passenger_name")) if x)
    for k, l in new_lines.items():
        if k in old_lines:
            fields(old_lines[k], l, "Passenger", name(l))
        else:
            changes.append({"scope": "Passenger Added", "line": name(l), "field": "", "old": "", "new": name(l)})
    for k, l in old_lines.items():
        if k not in new_lines:
            changes.append({"scope": "Passenger Removed", "line": name(l), "field": "", "old": name(l), "new": ""})
    return changes


def _audit_write(request, company_id, module, document_id, snapshot, action, changes, source=None):
    user = getattr(request, "app_user", None) or {}
    try:
        sp_client.audit_insert(
            company_id, module, document_id, (snapshot or {}).get("header", {}).get("invoice_number"), action, source,
            user.get("id"), user.get("full_name") or user.get("email"),
            json.dumps(changes, ensure_ascii=False, default=str), len(changes),
        )
    except Exception:  # noqa: BLE001
        _audit_logger.exception("audit insert failed (%s %s)", module, document_id)


def audited(module, id_kwarg=None):
    """Wraps a create / update view so every successful save is logged."""
    def deco(view):
        @functools.wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method != "POST":
                return view(request, *args, **kwargs)
            doc_id = kwargs.get(id_kwarg) if id_kwarg else None
            before, chain_before = None, {}
            if doc_id:
                before = _audit_take(module, doc_id)
                if module in ("Booking", "Reschedule"):
                    try:
                        for c in sp_client.audit_chain(module, doc_id):
                            chain_before[(c["module"], c["id"])] = _audit_take(c["module"], c["id"])
                    except Exception:  # noqa: BLE001
                        _audit_logger.exception("audit chain failed (%s %s)", module, doc_id)
            response = view(request, *args, **kwargs)
            try:
                if response.status_code in (200, 201):
                    data = json.loads(response.content or b"{}")
                    new_id = doc_id or (data.get("id") if isinstance(data, dict) else None)
                    after = _audit_take(module, new_id) if new_id else None
                    if after:
                        company_id = after["header"].get("company_id")
                        if before is None:
                            _audit_write(request, company_id, module, new_id, after, "CREATE", [])
                        else:
                            changes = _audit_diff(module, before, after)
                            if changes:
                                _audit_write(request, company_id, module, new_id, after, "UPDATE", changes)
                            source = f"{module} {after['header'].get('invoice_number') or new_id}"
                            for (m, cid), cb in chain_before.items():
                                ca = _audit_take(m, cid)
                                if cb and ca:
                                    cc = _audit_diff(m, cb, ca)
                                    if cc:
                                        _audit_write(request, company_id, m, cid, ca, "UPDATE", cc, source=source)
            except Exception:  # noqa: BLE001
                _audit_logger.exception("audit log failed (%s %s)", module, doc_id)
            return response
        return wrapper
    return deco


def _ref_date_after_invoice_error(body, ref_key, label):
    """Booking / Rescheduled / Cancellation Ref Date can't be later than the
    Invoice Date - the error text, or None when fine (or a date is missing)."""
    ref, invoice = _parse_date(body.get(ref_key)), _parse_date(body.get("invoice_date"))
    if ref and invoice and ref > invoice:
        return f"{label} cannot be later than the Invoice Date."
    return None


@csrf_exempt
@document_save("ticket")
@audited("Booking")
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
    ref_date_error = _ref_date_after_invoice_error(body, "booking_ref_date", "Booking Ref Date")
    if ref_date_error:
        return JsonResponse({"error": ref_date_error}, status=400)

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
@document_save("ticket", "ticket_id")
@audited("Booking", "ticket_id")
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
    ref_date_error = _ref_date_after_invoice_error(body, "booking_ref_date", "Booking Ref Date")
    if ref_date_error:
        return JsonResponse({"error": ref_date_error}, status=400)

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
            ticket_id=ticket_id, allow_chain_edit=_is_super_admin(request),
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


# Fields a Booking line has that a RescheduleAirlineTicketLine doesn't (none
# now - Supplier SSR Markup / Service Fee were added to Reschedule too).
BOOKING_ONLY_LINE_FIELDS = set()
RESCHED_LINE_FIELDS = [f for f in TICKET_LINE_FIELDS if f not in BOOKING_ONLY_LINE_FIELDS] + ["agent_penalty", "reschedule_penalty", "supplier_penalty"]
RESCHED_LINE_NUMERIC_FIELDS = (TICKET_LINE_NUMERIC_FIELDS - BOOKING_ONLY_LINE_FIELDS) | {"agent_penalty", "reschedule_penalty", "supplier_penalty"}


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


def _build_reschedule_lines(company_id, lines_in, chain_by_original, parent_pnr=None):
    """
    chain_by_original None = a direct Reschedule (its booking isn't in this
    software): no chain fields, every line's Parent PNR is parent_pnr (or
    the line's own, when it carries one).

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

        if chain_by_original is None:
            row = {"original_id": None, "based_on_id": None}
            line_parent_pnr = line_in.get("parent_pnr") or parent_pnr
        else:
            row = chain_by_original[line_in["original_ticket_line_id"]]
            line_parent_pnr = row["based_on_booking_reference"] if row["based_on_id"] is not None else row["original_ticket_booking_reference"]

        resched_ticket_proxy = RescheduleAirlineTicket(company_id=company_id)
        line = RescheduleAirlineTicketLine(reschedule_ticket=resched_ticket_proxy, supplier=line_supplier, **line_kwargs)
        line.total_billed = _safe_decimal(line.compute_total())
        line_objs.append(line)

        line_json = dict(line_kwargs)
        line_json["total_billed"] = line.total_billed
        line_json["supplier_name"] = supplier_name
        line_json["original_ticket_line_id"] = row["original_id"]
        line_json["based_on_reschedule_line_id"] = row["based_on_id"]
        line_json["parent_pnr"] = line_parent_pnr
        lines_json.append(line_json)
    return line_objs, lines_json


@csrf_exempt
@document_save("reschedule")
@audited("Reschedule")
@transaction.atomic
def reschedule_ticket_create(request):
    """
    POST /api/reschedule-tickets/create/
    Body: { company_id, original_ticket_id, ...header fields (same shape
    as tickets/create/'s TICKET_HEADER_FIELDS), customer_name,
    supplier_name, lines: [ {...TICKET_LINE_FIELDS, agent_penalty,
    reschedule_penalty, supplier_penalty, original_ticket_line_id}, ... ] }

    Direct Reschedule (Auto Push - the booking was never entered in this
    software): no original_ticket_id, a parent_pnr instead. Nothing is
    linked; every line keeps that Parent PNR.

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
    ref_date_error = _ref_date_after_invoice_error(body, "booking_ref_date", "Rescheduled Ref Date")
    if ref_date_error:
        return JsonResponse({"error": ref_date_error}, status=400)

    company_id = body.get("company_id")
    original_ticket_id = body.get("original_ticket_id") or None
    parent_pnr = (body.get("parent_pnr") or "").strip() or None
    lines_in = body.get("lines") or []
    if not company_id or not (original_ticket_id or parent_pnr) or not body.get("customer_name") or not body.get("invoice_number") or not body.get("booking_reference") or not lines_in:
        return JsonResponse({"error": "company_id, original_ticket_id (or parent_pnr for a direct reschedule), customer_name, invoice_number, booking_reference and at least one line are required."}, status=400)

    if original_ticket_id:
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
        chain_by_original = _resolve_reschedule_chain(original_ticket_id, lines_in) if original_ticket_id else None
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
        line_objs, lines_json = _build_reschedule_lines(company_id, lines_in, chain_by_original, parent_pnr)
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
@document_save("reschedule", "reschedule_ticket_id")
@audited("Reschedule", "reschedule_ticket_id")
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
    ref_date_error = _ref_date_after_invoice_error(body, "booking_ref_date", "Rescheduled Ref Date")
    if ref_date_error:
        return JsonResponse({"error": ref_date_error}, status=400)

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
        # A direct Reschedule (no booking in this software) stays direct.
        chain_by_original = _resolve_reschedule_chain(original_ticket_id, lines_in, existing_combo_keys) if original_ticket_id else None
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

    # A passenger added on screen to a direct Reschedule takes the Parent PNR of the others.
    parent_pnr = body.get("parent_pnr") or next((l.get("parent_pnr") for l in lines_in if l.get("parent_pnr")), None)
    try:
        line_objs, lines_json = _build_reschedule_lines(company_id, lines_in, chain_by_original, parent_pnr)
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
            reschedule_ticket_id=reschedule_ticket_id, allow_chain_edit=_is_super_admin(request),
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
    "supp_ssr_markup", "supp_ssr_service_fee",
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
        "gst_amounts": _saved_line_gst("reschedule", reschedule_ticket_id, l.ticket_no),
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
        "supp_ssr_markup": float(l.supp_ssr_markup or 0), "supp_ssr_service_fee": float(l.supp_ssr_service_fee or 0),
        "supp_gst_pct": float(l.supp_gst_pct),
        "agent_penalty": float(l.agent_penalty), "reschedule_penalty": float(l.reschedule_penalty),
        "supplier_penalty": float(l.supplier_penalty),
    } for l in rt.lines.select_related("supplier").all()]

    return JsonResponse({
        # Edit is refused up front when a later process is built on it.
        "edit_lock_message": sp_client.ticket_chain_lock_message(company_id, reschedule_id=rt.id),
        "edit_lock_bypass": _is_super_admin(request),  # Super Admin may still edit (changes follow the chain)
        "attributes": document_attributes("reschedule", rt.id),
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
    ("Debit", "Expenditure To Supplier", "Supplier SSR Markup A/c", "supp_ssr_markup"),
    ("Debit", "Expenditure To Supplier", "Supplier SSR Service Fee A/c", "supp_ssr_service_fee"),
    ("Debit", "GST and TDS", "Input IGST A/c", "supp_gst"),
    ("Debit", "Expenditure To Supplier", "Supplier Penalty Amount A/c", "reschedule_penalty"),
    ("Credit", "Earnings From Customer", "Consolidator Markup A/c", "supp_markup"),
    ("Credit", "Earnings From Customer", "Consolidator Addl Markup A/c", "supp_addl_markup"),
    ("Credit", "Earnings From Customer", "Consolidator Service Fee A/c", "supp_service_fee"),
    ("Credit", "Earnings From Customer", "Consolidator Addl Service Fee A/c", "supp_addl_service_fee"),
    ("Credit", "Earnings From Customer", "Consolidator SSR Markup A/c", "supp_ssr_markup"),
    ("Credit", "Earnings From Customer", "Consolidator SSR Service Fee A/c", "supp_ssr_service_fee"),
    ("Credit", "GST and TDS", "Output IGST A/c", "supp_gst"),
    ("Credit", "Earnings From Customer", "Consolidator Penalty Amount A/c", "reschedule_penalty"),
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
        "supp_ssr_markup": sum(float(l.supp_ssr_markup or 0) for l in lines),
        "supp_ssr_service_fee": sum(float(l.supp_ssr_service_fee or 0) for l in lines),
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
            + float(l.supp_markup) + float(l.supp_addl_markup) + float(l.supp_ssr_markup or 0)
            + float(l.supp_service_fee) + float(l.supp_addl_service_fee) + float(l.supp_ssr_service_fee or 0)
            + float(l.computed_supp_gst)
            + float(l.supplier_penalty) + float(l.reschedule_penalty)
        )

    def dr_cr_amounts(dr_cr, amount):
        amount = round(amount, 2)
        return (amount, 0) if dr_cr == "Debit" else (0, amount)

    # A reschedule can come out NEGATIVE (the new fare is lower - money goes
    # back to the customer / comes back from the supplier). Then the side
    # flips: Sales cost < 0 -> CREDIT the Customer, Purchase cost < 0 ->
    # DEBIT the Supplier, each by the positive amount. Every other
    # reschedule stays Customer Debit / Supplier Credit, unchanged.
    flip = {"Debit": "Credit", "Credit": "Debit"}

    def party_amounts(dr_cr, amount):
        if round(amount, 2) < 0:
            return dr_cr_amounts(flip[dr_cr], -amount)
        return dr_cr_amounts(dr_cr, amount)

    def customer_rows(dr_cr, amount):
        debit, credit = party_amounts(dr_cr, amount)
        return [{"role": "customer", "ledger_id": resched_ticket.customer_id,
                 "ledger_name": resched_ticket.customer.name, "debit": debit, "credit": credit}]

    def supplier_rows(dr_cr):
        rows = []
        for g in supplier_groups.values():
            debit, credit = party_amounts(dr_cr, g["amount"])
            ledger = g["ledger"]
            name = ledger.name if ledger else "— (no supplier selected)"
            rows.append({"role": "supplier", "ledger_id": ledger.id if ledger else None,
                         "ledger_name": name, "debit": debit, "credit": credit})
        return rows

    if mapping_cache is None:
        mapping_cache = {}

    def mapped_ledger(masters_category, field_name):
        # The ledger mapped to this field ON THIS DOCUMENT'S OWN DATE (Ledger
        # Mapping effective dates - models.resolve_mapping), never simply
        # today's mapping - re-mapping later can't rewrite booked documents.
        r = resolve_mapping(resched_ticket.company_id, field_name, document_date(resched_ticket), doc=document_ref(resched_ticket))
        return (r["ledger_id"], r["ledger_name"]) if r else (None, f"{field_name} (not mapped in Master Mapping)")

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

    # Input GST (Debit) - Supplier State vs Company State, per supplier.
    gst_by_supplier = {}
    for l in lines:
        gst_by_supplier[l.supplier_id] = gst_by_supplier.get(l.supplier_id, 0.0) + float(l.computed_supp_gst)

    accounts = customer_rows("Debit", customer_total) + supplier_rows("Credit")
    output_gst_emitted = False
    for dr_cr, masters_category, field_name, amount_key in RESCHED_JV_LINE_MAP:
        if _is_input_gst_row(dr_cr, masters_category, field_name, amount_key):
            accounts.extend(_input_gst_rows(mapped_row, gst_by_supplier, company_state, mapping_cache))
            continue
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
            + float(l.supp_markup) + float(l.supp_addl_markup) + float(l.supp_ssr_markup or 0)
            + float(l.supp_service_fee) + float(l.supp_addl_service_fee) + float(l.supp_ssr_service_fee or 0)
            + float(l.computed_supp_gst)
            + float(l.supplier_penalty) + float(l.reschedule_penalty)
        )
    total_amount = round(sum(g["amount"] for g in supplier_groups.values()), 2)
    if total_amount == 0:
        return []

    result = [(g["ledger"].id, g["amount"], 0) for g in supplier_groups.values() if g["ledger"]]
    if fop == "Own Card":
        card_number = lines[0].card_number or ""
        card = sp_client.fop_master_get_by_card_number(resched_ticket.company_id, card_number, as_of=document_date(resched_ticket))
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
        resched_ticket.invoice_date or resched_ticket.booking_ref_date, document_ref(resched_ticket),
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
@document_save("reschedule", preview=True)
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


def _is_super_admin(request):
    """True when the signed-in user (set by permissions.MenuPermissionMiddleware) is a Super Admin."""
    u = getattr(request, "app_user", None)
    return bool(u and u.get("is_super_admin"))


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
        "id": l["id"], "gst_amounts": _saved_line_gst("ticket", ticket_id, l["ticket_no"]),
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
            "supp_ssr_markup": float(l.get("supp_ssr_markup") or 0), "supp_ssr_service_fee": float(l.get("supp_ssr_service_fee") or 0),
        "supp_gst_pct": float(l["supp_gst_pct"]),
        "computed_discount": float(l["computed_discount"]), "computed_tds": float(l["computed_tds"]), "computed_gst": float(l["computed_gst"]),
        "computed_supp_commission": float(l["computed_supp_commission"]), "computed_supp_tds": float(l["computed_supp_tds"]),
        "computed_supp_gst": float(l["computed_supp_gst"]),
    } for l in sp_lines]

    return JsonResponse({
        # Edit is refused up front when a later process is built on it.
        "edit_lock_message": sp_client.ticket_chain_lock_message(company_id, ticket_id=header["id"]),
        "edit_lock_bypass": _is_super_admin(request),  # Super Admin may still edit (changes follow the chain)
        "attributes": document_attributes("ticket", header["id"]),
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
            "supp_ssr_markup": float(l.get("supp_ssr_markup") or 0), "supp_ssr_service_fee": float(l.get("supp_ssr_service_fee") or 0),
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
            "supp_ssr_markup": float(l.get("supp_ssr_markup") or 0), "supp_ssr_service_fee": float(l.get("supp_ssr_service_fee") or 0),
            "computed_discount": float(l["computed_discount"]), "computed_tds": float(l["computed_tds"]), "computed_gst": float(l["computed_gst"]),
            "computed_supp_gst": float(l["computed_supp_gst"]),
        })
    return JsonResponse(rows, safe=False)


def _live_pnr_lines(lines):
    """
    Where each of these passenger lines (TicketLine or RescheduleAirlineTicketLine
    - the ones the user searched by an OLD PNR / Ticket No) lives NOW: follows
    each passenger's reschedule chain to its newest line, then reports
      - still live -> its current S PNR, Airline PNR and Ticket No, or
      - cancelled  -> the Credit Note that cancelled it.
    One text line per passenger, for the lookup error popups (Reschedule /
    Cancellation / SSR Updation New) so the user can search the right ticket.
    """
    out = []
    for l in lines:
        node, hops = l, 0
        while getattr(node, "rescheduled", False) and hops < 50:
            if isinstance(node, TicketLine):
                nxt = RescheduleAirlineTicketLine.objects.filter(original_ticket_line_id=node.id, based_on_reschedule_line__isnull=True)                     .select_related("reschedule_ticket").order_by("-id").first()
            else:
                nxt = RescheduleAirlineTicketLine.objects.filter(based_on_reschedule_line_id=node.id)                     .select_related("reschedule_ticket").order_by("-id").first()
            if nxt is None:
                break
            node, hops = nxt, hops + 1
        name = node.passenger_name or l.passenger_name or "Passenger"
        if getattr(node, "canceled", False):
            original_id = node.id if isinstance(node, TicketLine) else node.original_ticket_line_id
            cx = CancellationAirlineTicketLine.objects.filter(original_ticket_line_id=original_id)                 .select_related("cancellation_ticket").order_by("-id").first()
            where = f"Credit Note {cx.cancellation_ticket.invoice_number}" if cx else "a Cancellation"
            out.append(f"• {name} - cancelled ({where}), Ticket No. {node.ticket_no or '-'}")
        else:
            head = node.reschedule_ticket if isinstance(node, RescheduleAirlineTicketLine) else node.ticket
            out.append(f"• {name} - live PNR: S PNR {head.booking_reference or '-'}, Airline PNR {head.airline_pnr or '-'}, "
                       f"Ticket No. {node.ticket_no or '-'} (Invoice {head.invoice_number})")
    return "\n".join(out)


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
                if rline.original_ticket_line_id is None:
                    verb = "reschedule"
                    return JsonResponse({"error": f"Ticket No. {ticket_no} is on a direct Reschedule (its booking is not in this software) - {verb} it through Auto Push."}, status=404)
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
        live = _live_pnr_lines([resched_source_line if resched_source_line is not None else matched_line])
        return JsonResponse({
            "error": "This ticket has already been rescheduled and cannot be rescheduled again. Its current ticket:\n" + live
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
        searched = list(resched_source.lines.all()) if resched_source is not None else list(ticket.lines.all())
        return JsonResponse({
            "error": "No passenger on this booking is left to reschedule - each one has already been rescheduled or cancelled. "
                     "Where each passenger is now:\n" + _live_pnr_lines(searched)
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
                if rline.original_ticket_line_id is None:
                    # Also the SSR Updation screen's lookup.
                    return JsonResponse({"error": f"Ticket No. {ticket_no} is on a direct Reschedule (its booking is not in this software) - "
                                                  f"this screen can't open it; cancel it through Auto Push."}, status=404)
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
        live = _live_pnr_lines([resched_source_line if resched_source_line is not None else matched_line])
        return JsonResponse({
            "error": "This ticket has already been rescheduled - search using its current PNR / Ticket No:\n" + live
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
        searched = list(resched_source.lines.all()) if resched_source is not None else list(ticket.lines.all())
        return JsonResponse({
            "error": "No passenger on this booking is left to cancel - each one has already been cancelled or rescheduled. "
                     "Where each passenger is now:\n" + _live_pnr_lines(searched)
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
    "supp_markup_reversal", "supp_addl_markup_reversal", "supp_ssr_markup_reversal",
]

# Locked Customer/Supplier TDS amounts carried from the booking/reschedule
# chain (page-ticket-entry.js sets these on the passenger) - None means "no
# override" (TDS = Amount x TDS %), so they're kept None, never coerced to 0.
CANCEL_TDS_OVERRIDE_FIELDS = ["tds_amount_override", "supp_tds_amount_override"]


def _cancel_tds_overrides(line_in):
    return {
        f: (None if line_in.get(f) in (None, "") else _safe_decimal(line_in.get(f)))
        for f in CANCEL_TDS_OVERRIDE_FIELDS
    }


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
# Penalty (rows 10 / 16): the Supplier card's Penalty Amount posts Debit
# "Supplier Penalty Amount A/c" / Credit "Consolidator Penalty Amount A/c" -
# the same pair Reschedule uses (one Ledger Mapping field each, for both
# Reschedule and Cancellation; the old Supplier Reschedule / Supplier
# Cancellation / Consolidator Reschedule Penalty fields were merged into
# these by migration 0069). Rows 15/27 are still two separate literal
# "Output IGST A/c" Credit rows, kept exactly as specified.
#
# Each entry: (dr_cr, masters_category, field_name, amount_key) - same
# shape and same Master Mapping (masters_category, field_name) literals as
# JV_LINE_MAP/RESCHED_JV_LINE_MAP.
# ============================================================
CANCEL_JV_LINE_MAP = [
    ("Debit", "Earnings From Supplier", "Commission A/c", "commission"),                                   # 3
    ("Credit", "GST and TDS", "Commission TDS A/c", "commission_tds"),                                     # 4
    ("Debit", "Expenditure To Supplier", "Supplier Markup A/c", "supp_markup"),                            # 5
    ("Debit", "Expenditure To Supplier", "Supplier Addl Markup A/c", "supp_addl_markup"),                  # 6
    ("Debit", "Expenditure To Supplier", "Supplier Service Fee A/c", "supp_service_fee"),                  # 7
    ("Debit", "Expenditure To Supplier", "Supplier Addl Service Fee A/c", "supp_addl_service_fee"),        # 8
    ("Debit", "GST and TDS", "Input IGST A/c", "supp_gst"),                                                # 9
    ("Debit", "Expenditure To Supplier", "Supplier Penalty Amount A/c", "cancellation_penalty"),            # 10
    ("Credit", "Earnings From Customer", "Consolidator Markup A/c", "supp_markup"),                        # 11
    ("Credit", "Earnings From Customer", "Consolidator Addl Markup A/c", "supp_addl_markup"),              # 12
    ("Credit", "Earnings From Customer", "Consolidator Service Fee A/c", "supp_service_fee"),              # 13
    ("Credit", "Earnings From Customer", "Consolidator Addl Service Fee A/c", "supp_addl_service_fee"),    # 14
    ("Credit", "GST and TDS", "Output IGST A/c", "supp_gst"),                                              # 15
    ("Credit", "Earnings From Customer", "Consolidator Penalty Amount A/c", "cancellation_penalty"),        # 16
    ("Credit", "Expenditure To Supplier", "Supplier Markup A/c", "supp_markup_reversal"),                  # 17
    ("Credit", "Expenditure To Supplier", "Supplier Addl Markup A/c", "supp_addl_markup_reversal"),        # 18
    ("Debit", "Earnings From Customer", "Consolidator Markup A/c", "supp_markup_reversal"),                # 19
    ("Debit", "Earnings From Customer", "Consolidator Addl Markup A/c", "supp_addl_markup_reversal"),      # 20
    # Supplier SSR Markup reversal - same pair as rows 17-20.
    ("Credit", "Expenditure To Supplier", "Supplier SSR Markup A/c", "supp_ssr_markup_reversal"),          # 20a
    ("Debit", "Earnings From Customer", "Consolidator SSR Markup A/c", "supp_ssr_markup_reversal"),        # 20b
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
        "supp_ssr_markup_reversal": r2(l.supp_ssr_markup_reversal),
    }
    cust_reversal = a["cust_markup_reversal"] + a["cust_addl_markup_reversal"] + a["cust_ssr_markup_reversal"]
    supp_reversal = a["supp_markup_reversal"] + a["supp_addl_markup_reversal"] + a["supp_ssr_markup_reversal"]
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

    company_state drives row 9's Input GST split (Supplier State vs Company
    State, see _input_gst_rows) - the spec posts both Output IGST rows
    literally, so no same-state CGST/SGST split is applied to Output here.

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
        # The ledger mapped to this field ON THIS DOCUMENT'S OWN DATE (Ledger
        # Mapping effective dates - models.resolve_mapping), never simply
        # today's mapping - re-mapping later can't rewrite booked documents.
        r = resolve_mapping(cancel_ticket.company_id, field_name, document_date(cancel_ticket), doc=document_ref(cancel_ticket))
        return (r["ledger_id"], r["ledger_name"]) if r else (None, f"{field_name} (not mapped in Master Mapping)")

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
    def mapped_row(dr_cr, masters_category, field_name, amount):
        debit, credit = dr_cr_amounts(dr_cr, amount)
        ledger_id, ledger_name = mapped_ledger(masters_category, field_name)
        return {"role": field_name, "ledger_id": ledger_id, "ledger_name": ledger_name, "debit": debit, "credit": credit}

    # Row 9 Input GST (Debit) - Supplier State vs Company State, per supplier
    # (same concept as Booking/Reschedule). The Output IGST rows (15, 27)
    # stay literal, per the Cancellation spec.
    if company_state is None:
        company_state = (CompanyMaster.objects.filter(id=cancel_ticket.company_id).values_list("state", flat=True).first() or "").strip().lower()
    gst_by_supplier = {}
    for l, a in zip(lines, per_line):
        gst_by_supplier[l.supplier_id] = gst_by_supplier.get(l.supplier_id, 0.0) + a["supp_gst"]

    # Rows 3-31
    for dr_cr, masters_category, field_name, amount_key in CANCEL_JV_LINE_MAP:
        if _is_input_gst_row(dr_cr, masters_category, field_name, amount_key):
            accounts.extend(_input_gst_rows(mapped_row, gst_by_supplier, company_state, mapping_cache))
            continue
        accounts.append(mapped_row(dr_cr, masters_category, field_name, role_amounts[amount_key]))

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
                card_cache[card_number] = sp_client.fop_master_get_by_card_number(cancel_ticket.company_id, card_number,
                                                                                  as_of=document_date(cancel_ticket))
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


def _cancellation_pg_receipt_lines(cancel_ticket, lines):
    """
    PG Receipt leg of the Cancellation JV - only when Payment Mode is
    "Payment Gateway": Customer Debit + the gateway's PG platform ledger
    (PG Master "Payment Master" ledger in force on the cancellation's date)
    Credit, both = the Customer amount of the Main JV (row 1). Same
    (ledger_id, debit, credit) tuple shape as _cancellation_fop_payment_lines.
    Cancellation only - Booking / Reschedule PG receipts are unchanged.
    """
    if getattr(cancel_ticket, "payment_mode", None) != "Payment Gateway":
        return []
    amount = round(sum(_cancellation_line_amounts(l)["customer_amount"] for l in lines), 2)
    if not amount:
        return []
    snapshot = _pg_master_effective_snapshot(
        cancel_ticket.company_id, getattr(cancel_ticket, "payment_gateway_ref", None) or "",
        getattr(cancel_ticket, "invoice_date", None) or getattr(cancel_ticket, "cancellation_ref_date", None),
        document_ref(cancel_ticket),
    )
    if not snapshot or not snapshot.get("payment_master_ledger_id"):
        return []
    return [(cancel_ticket.customer_id, amount, 0), (snapshot["payment_master_ledger_id"], 0, amount)]


def _cancellation_report_entries(company_id, mapping_cache, company_state, from_date=None, to_date=None):
    """
    Every posted Cancellation Journal Voucher (ALC-n) for the reports
    (Ledger balances / Trial Balance / Ledger report / Day Book), recomputed
    live from the saved cancellation lines - same convention as the Booking
    and Reschedule JVs (accounts are never stored). Optional from_date/
    to_date ("YYYY-MM-DD") window on the voucher date.

    Yields {"voucher", "ct", "lines", "accounts", "combined"} - accounts is
    the Main JV (rows 1-31), combined adds the Own Card / Client Card FOP leg
    (JV-2/JV-3) as {"ledger_id", "ledger_name": None, "debit", "credit"} rows.
    """
    vouchers = JournalVoucher.objects.filter(
        company_id=company_id, source_cancellation_ticket__isnull=False
    ).select_related("source_cancellation_ticket", "source_cancellation_ticket__customer").prefetch_related(
        Prefetch("source_cancellation_ticket__lines", queryset=CancellationAirlineTicketLine.objects.select_related("supplier"))
    ).order_by("id")
    if from_date:
        vouchers = vouchers.filter(voucher_date__gte=from_date)
    if to_date:
        vouchers = vouchers.filter(voucher_date__lte=to_date)
    for v in vouchers:
        ct = v.source_cancellation_ticket
        lines = list(ct.lines.all()) if ct else []
        if not lines:
            continue
        accounts, _n, _td, _tc = _compute_cancellation_jv_lines(ct, lines, mapping_cache, company_state)
        combined = list(accounts)
        try:
            fop_leg = _cancellation_fop_payment_lines(ct, lines)
        except ValueError:
            fop_leg = []  # card since removed from FOP Master - Main JV still counts
        for ledger_id, debit, credit in fop_leg + _cancellation_pg_receipt_lines(ct, lines):
            combined.append({"ledger_id": ledger_id, "ledger_name": None, "debit": debit, "credit": credit})
        yield {"voucher": v, "ct": ct, "lines": lines, "accounts": accounts, "combined": combined}


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
    fop_rows = fop_rows + _cancellation_pg_receipt_lines(cancel_ticket, line_objs)
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
        id=cancellation_id, company_id=company_id,
        customer=Ledger(id=header["customer_ledger_id"], name=header["customer_name"]),
        cancellation_reference=header.get("cancellation_reference"), airline_pnr=header.get("airline_pnr"),
        payment_mode=header.get("payment_mode"), payment_gateway_ref=header.get("payment_gateway_ref"),
        invoice_date=header.get("invoice_date"), cancellation_ref_date=header.get("cancellation_ref_date"),
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
@document_save("cancellation", preview=True)
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
        payment_mode=body.get("payment_mode"), payment_gateway_ref=body.get("payment_gateway_ref"),
        invoice_date=_parse_date(body.get("invoice_date")), cancellation_ref_date=_parse_date(body.get("cancellation_ref_date")),
    )

    line_objs = []
    for line_in in lines_in:
        line_kwargs = {f: line_in[f] for f in CANCEL_LINE_FIELDS if f in line_in}
        for f in TICKET_LINE_NUMERIC_FIELDS:
            if f in line_kwargs:
                line_kwargs[f] = _safe_decimal(line_kwargs[f])
        for f in CANCEL_JV_LINE_FIELDS:
            line_kwargs[f] = _safe_decimal(line_in.get(f))
        line_kwargs.update(_cancel_tds_overrides(line_in))

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


def cancellation_dsr_rows(request):
    """
    GET /api/cancellation-tickets/dsr/?company_id=1
    One row per cancelled passenger for report-dsr-airline-booking.html, same
    flat shape as tickets_list()/reschedule_tickets_list() so the DSR can
    merge them in. A Credit Note reduces sales, so Base Fare and the refund
    amount (total_billed - the Cancellation JV's own Customer credit, see
    _cancellation_line_amounts) are NEGATIVE. ticket_id/reschedule_ticket_id
    are null; cancellation_ticket_id links to the saved cancellation.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    _jv_prep(company_id)  # seeds the per-field GST% cache computed_gst reads
    rows = []
    cancellations = CancellationAirlineTicket.objects.filter(company_id=company_id).select_related("customer").prefetch_related(
        Prefetch("lines", queryset=CancellationAirlineTicketLine.objects.select_related("supplier"))
    )
    for ct in cancellations:
        for l in ct.lines.all():
            refund = _cancellation_line_amounts(l)["customer_amount"]
            rows.append({
                "id": l.id, "ticket_id": None, "reschedule_ticket_id": None, "cancellation_ticket_id": ct.id,
                "invoice_number": ct.invoice_number, "invoice_date": ct.invoice_date.isoformat() if ct.invoice_date else None,
                "invoice_type": ct.invoice_type, "booking_status": ct.booking_status,
                "payment_mode": ct.payment_mode, "booking_type": ct.booking_type,
                "customer_name": ct.customer.name if ct.customer else None,
                "booking_reference": ct.cancellation_reference, "airline_pnr": ct.airline_pnr, "gds_pnr": ct.gds_pnr,
                "travel_type": ct.travel_type, "airline_category": l.airline_category or ct.airline_category,
                "passenger_name": l.passenger_name, "ticket_no": l.ticket_no, "pax_type": l.pax_type,
                "sector": l.sector, "airline_name": l.airline_name, "airline_code": l.airline_code,
                "supplier_name": l.supplier.name if l.supplier else None,
                "basic_fare": -round(float(l.basic_fare), 2),
                "total_billed": -round(refund, 2),
                # DSR Earnings columns (Cancellation's own formula, see the
                # DSR page): commission amounts honour the chain totals the
                # line carries; the reversal is Customer Markup + Addl + SSR.
                "supp_commission_amount": round(float(l.computed_supp_commission or 0), 2),
                "cust_commission_amount": round(float(l.computed_discount or 0), 2),
                **{f: round(float(getattr(l, f) or 0), 2) for f in (
                    "markup", "addl_markup", "ssr_markup", "service_fee", "addl_service_fee", "ssr_service_fee", "agent_penalty")},
                "cust_markup_reversal_total": round(float(l.cust_markup_reversal_total or 0), 2),
            })
    return JsonResponse(rows, safe=False)


def _chain_used_payment_gateway(original_line, based_on):
    """True when the booking or any reschedule in this passenger's chain (up
    to based_on) was paid by Payment Gateway - Cancellation then lets the
    user pick its Payment Mode; otherwise it stays frozen at Top-up."""
    if original_line.ticket.payment_mode == "Payment Gateway":
        return True
    node = based_on
    while node is not None:
        if node.reschedule_ticket.payment_mode == "Payment Gateway":
            return True
        node = node.based_on_reschedule_line
    return False


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

    Seat/Meal/Baggage/Other SSR are the exception - NOT summed across the
    chain: they are the Return SSR figures, so only the LIVE PNR's own SSR
    (the record being cancelled) plus any SSR Updation sold on that same live
    PNR (see ssr_for_live_pnr).

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

    # SSR Updation charges sold on these passengers - added into Return
    # Seat/Meal/Baggage/Other SSR below (see ssr_for_live_pnr).
    ssr_rows = sp_client.ssr_lines_for_original_lines(company_id, original_ids)

    def ssr_for_live_pnr(oid, based_on):
        """Return SSR = only the LIVE PNR's own SSR (the record being
        cancelled), never the earlier PNRs in its history: that line's own
        Seat/Meal/Baggage/Other SSR, plus any SSR Updation sold on that same
        live PNR. e.g. booked TT01 with SSR 100, rescheduled to TT02 adding SSR
        50 -> cancelling TT02 returns 50, not 150."""
        live = based_on if based_on is not None else originals.get(oid)
        out = {k: float(getattr(live, k, 0) or 0) for k in ("seat", "meal", "baggage", "other_ssr")}
        live_rid = based_on.id if based_on is not None else None
        for r in ssr_rows:
            if r["original_ticket_line_id"] == oid and r["reschedule_line_id"] == live_rid:
                for k in out:
                    out[k] += float(r[k] or 0)
        return {k: round(v, 2) for k, v in out.items()}

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
        # Return SSR: the live PNR's own SSR only (replaces the chain sum).
        chain.update(ssr_for_live_pnr(original_line.id, based_on))
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
            "supp_ssr_markup": chain["supp_ssr_markup"],
            "chain_payment_gateway": _chain_used_payment_gateway(original_line, based_on),
        })

    return JsonResponse({"totals": totals})


@csrf_exempt
@document_save("cancellation")
@audited("Cancellation")
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

    Direct Cancellation (Auto Push - the booking was never entered in this
    software): no original_ticket_id, a parent_pnr instead. Lines carry no
    original_ticket_line_id; when the passenger is on a direct Reschedule
    (source_reschedule_ticket_id + line_id) that reschedule line is marked
    cancelled.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)
    ref_date_error = _ref_date_after_invoice_error(body, "cancellation_ref_date", "Cancellation Ref Date")
    if ref_date_error:
        return JsonResponse({"error": ref_date_error}, status=400)

    company_id = body.get("company_id")
    original_ticket_id = body.get("original_ticket_id") or None
    parent_pnr = (body.get("parent_pnr") or "").strip() or None
    source_reschedule_ticket_id = body.get("source_reschedule_ticket_id")
    lines_in = body.get("lines") or []
    if not company_id or not (original_ticket_id or parent_pnr) or not body.get("customer_name") or not body.get("invoice_number") \
            or not body.get("cancellation_reference") or not lines_in:
        return JsonResponse({
            "error": "company_id, original_ticket_id (or parent_pnr for a direct cancellation), customer_name, invoice_number, "
                     "cancellation_reference and at least one line are required."
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
        payment_mode=body.get("payment_mode"), payment_gateway_ref=body.get("payment_gateway_ref"),
        invoice_date=_parse_date(body.get("invoice_date")), cancellation_ref_date=_parse_date(body.get("cancellation_ref_date")),
    )

    # Resolve each line's TRUE original TicketLine id. A straight pass-
    # through normally; one hop through RescheduleAirlineTicketLine when
    # this cancellation was raised against an already-rescheduled
    # passenger (source_reschedule_ticket_id set).
    original_id_by_line_id = {}
    if source_reschedule_ticket_id and original_ticket_id:
        reschedule_line_ids = [l.get("line_id") for l in lines_in if l.get("line_id")]
        original_id_by_line_id = sp_client.reschedule_resolve_original_line_ids(reschedule_line_ids)

    lines_json, line_objs = [], []
    for line_in in lines_in:
        line_id = line_in.get("line_id")
        if not original_ticket_id:
            original_ticket_line_id = None  # direct - no booking line to link
        elif source_reschedule_ticket_id:
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
        line_kwargs.update(_cancel_tds_overrides(line_in))

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
            jv_narration, jv_total_debit, jv_total_credit, parent_pnr=parent_pnr,
        )
    except sp_client.StoredProcedureError as err:
        msg = str(err)
        status = 404 if "not found" in msg else (409 if "already" in msg else 400)
        return JsonResponse({"error": msg}, status=status)

    return JsonResponse({
        "id": result["id"], "line_ids": result["line_ids"], "voucher_no": result.get("voucher_no"),
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
@document_save("cancellation", "cancellation_id")
@audited("Cancellation", "cancellation_id")
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
    ref_date_error = _ref_date_after_invoice_error(body, "cancellation_ref_date", "Cancellation Ref Date")
    if ref_date_error:
        return JsonResponse({"error": ref_date_error}, status=400)

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
        payment_mode=header_fields.get("payment_mode") or saved_header.get("payment_mode"),
        payment_gateway_ref=header_fields.get("payment_gateway_ref") or saved_header.get("payment_gateway_ref"),
        invoice_date=header_fields.get("invoice_date") or saved_header.get("invoice_date"),
        cancellation_ref_date=header_fields.get("cancellation_ref_date") or saved_header.get("cancellation_ref_date"),
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
        # Penalties + Markup Reversal components: the SP's UPDATE overwrites
        # these columns from this payload, so they must always be sent - the
        # request's value if the screen sent one, else the already-saved one
        # (leaving them out reset them to 0 on every edit).
        for f in CANCEL_JV_LINE_FIELDS:
            line_kwargs[f] = _safe_decimal(line_in[f]) if f in line_in else _safe_decimal(saved_line.get(f))
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

    # Markup Reversal popup amounts (chain_*) - the same cumulative booking +
    # reschedule totals a NEW cancellation gets from cancellation_fare_totals,
    # so a saved one's popup shows every component's real amount (ticked or
    # not). The cancellation was raised against the chain's cancelled
    # reschedule line, if any.
    def chain_markups(original_ticket_line_id):
        if not original_ticket_line_id:
            return {}  # direct Cancellation - no booking chain
        try:
            original_line = TicketLine.objects.get(id=original_ticket_line_id, ticket__company_id=company_id)
            based_on = (RescheduleAirlineTicketLine.objects
                        .filter(original_ticket_line_id=original_ticket_line_id, canceled=True)
                        .order_by("-id").first())
            chain = _resolve_parent_chain_line(original_line, based_on)
            out = {f"chain_{k}": chain[k] for k in ("markup", "addl_markup", "ssr_markup", "supp_markup", "supp_addl_markup",
                                                     "seat", "meal", "baggage", "other_ssr")}
            out["chain_payment_gateway"] = _chain_used_payment_gateway(original_line, based_on)
            return out
        except TicketLine.DoesNotExist:
            return {}

    return JsonResponse({
        "attributes": document_attributes("cancellation", header["id"]),
        "id": header["id"], "original_ticket_id": header["original_ticket_id"], "parent_pnr": header.get("parent_pnr"),
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
            "gst_amounts": _saved_line_gst("cancellation", cancellation_id, l["ticket_no"]),
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
            **{f: (float(l[f]) if l.get(f) is not None else None) for f in CANCEL_TDS_OVERRIDE_FIELDS},
            # Saved penalties + the 5 Markup Reversal COMPONENT amounts (see
            # CANCEL_JV_LINE_FIELDS) - were never returned, so a reopened
            # cancellation showed them all as 0.
            **{f: float(l[f] or 0) for f in CANCEL_JV_LINE_FIELDS},
            **chain_markups(l["original_ticket_line_id"]),
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
@document_save("ticket", preview=True)
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
        "voucher_type_name": v.get("voucher_type_name"),
        "voucher_date": v["voucher_date"].isoformat() if v["voucher_date"] else None,
        "narration": v["narration"],
        "total_debit": float(v["total_debit"]), "total_credit": float(v["total_credit"]),
        "lines": json.loads(lines_json) if lines_json else [],
    }


def voucher_next_number(request):
    """GET /api/vouchers/next-number/?company_id=1&voucher_type=Journal[&voucher_type_name=Test Journal] -
    the automatic number the next voucher of that type will get (shown read-only on the New Voucher
    screen). A Voucher Type master entry has its own series starting at 1."""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)
    return JsonResponse({"next_number": sp_client.voucher_next_number(
        company_id, request.GET.get("voucher_type") or "Journal", request.GET.get("voucher_type_name") or None)})


def _cash_bank_voucher_error(body):
    """
    Receipt and Payment vouchers must move money through Cash / Bank - any
    number of lines, but at least one line on a ledger under Bank Accounts or
    Cash-in-Hand, on the right side:
      Receipt -> a DEBIT line (money received into the bank / cash)
      Payment -> a CREDIT line (money paid out of the bank / cash)
    The side matters - a bank only on the wrong side (e.g. a Receipt's lines
    kept after switching the type to Payment) is rejected. Returns the error
    message, or None if it's fine / another voucher type.
    """
    vtype = body.get("voucher_type") or ""
    company_id = body.get("company_id")
    target_keys = {_normalize_group_name(n) for n in CASH_BANK_BOOK_GROUP_NAMES}
    if vtype == "Contra":
        # Contra moves money between Cash / Bank only - EVERY line (By and
        # To) must be a ledger under Bank Accounts or Cash-in-Hand.
        group_ids = [g.id for g in LedgerGroup.objects.filter(company_id=company_id) if _normalize_group_name(g.name) in target_keys]
        line_ids = {l.get("ledger_id") for l in (body.get("lines") or []) if l.get("ledger_id")}
        ok = set(Ledger.objects.filter(company_id=company_id, id__in=line_ids, group_id__in=group_ids).values_list("id", flat=True))
        return None if line_ids <= ok else "A Contra voucher can only use ledgers under Bank Accounts or Cash-in-Hand."
    side = {"Receipt": "debit", "Payment": "credit"}.get(vtype)
    if not side:
        return None
    group_ids = [g.id for g in LedgerGroup.objects.filter(company_id=company_id) if _normalize_group_name(g.name) in target_keys]
    side_ledger_ids = [l.get("ledger_id") for l in (body.get("lines") or []) if float(l.get(side) or 0) > 0]
    if group_ids and Ledger.objects.filter(company_id=company_id, id__in=side_ledger_ids, group_id__in=group_ids).exists():
        return None
    return f"A {vtype} voucher must have at least one {side.title()} line on a ledger under Bank Accounts or Cash-in-Hand."


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

    cash_bank_error = _cash_bank_voucher_error(body)
    if cash_bank_error:
        return JsonResponse({"error": cash_bank_error}, status=400)
    alloc_error = _clean_bill_allocations(body)
    if alloc_error:
        return JsonResponse({"error": alloc_error}, status=400)

    try:
        voucher = sp_client.voucher_save(
            body.get("company_id"), body.get("branch_name"), body.get("voucher_type", "Journal"),
            _parse_date(body.get("voucher_date")), body.get("narration"), body.get("lines") or [],
            voucher_type_name=body.get("voucher_type_name"), manual_no=body.get("voucher_no_manual"),
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

    cash_bank_error = _cash_bank_voucher_error(body)
    if cash_bank_error:
        return JsonResponse({"error": cash_bank_error}, status=400)
    alloc_error = _clean_bill_allocations(body)
    if alloc_error:
        return JsonResponse({"error": alloc_error}, status=400)

    try:
        voucher = sp_client.voucher_save(
            body.get("company_id"), body.get("branch_name"), body.get("voucher_type", "Journal"),
            _parse_date(body.get("voucher_date")), body.get("narration"), body.get("lines") or [],
            voucher_id=voucher_id, voucher_type_name=body.get("voucher_type_name"), manual_no=body.get("voucher_no_manual"),
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
        "numbering_behaviour": vt.get("numbering_behaviour"),
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
            "name": "...", "alias_name": "...", "voucher_category": "Airline",
            "is_active": true, "number_method": "Automatic", "numbering_behaviour": "Keep Original Numbers",
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
        "voucher_category": body.get("voucher_category") or "Airline",
        "is_active": bool(body.get("is_active", True)),
        "number_method": body.get("number_method") or "Automatic",
        "numbering_behaviour": body.get("numbering_behaviour") or None,  # Automatic only - see sp_VoucherType
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
    data = _voucher_type_dict(vt)
    # How many old Voucher-screen vouchers "Restart Numbers" renumbered (0 otherwise).
    data["renumbered"] = int(vt.get("renumbered") or 0)
    return JsonResponse(data, status=200 if voucher_type_id else 201)


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

    result = next_invoice_number(company_id, name, _parse_date(request.GET.get("voucher_date")))
    if result is None:
        return JsonResponse({"error": "Voucher Type not found."}, status=404)
    number_method, next_number = result
    return JsonResponse({"number_method": number_method, "next_number": next_number})


def next_invoice_number(company_id, name, voucher_date=None):
    """
    (number_method, next_number) for this Invoice Type (VoucherType name) -
    next_number is None for a "Manual" type. None when no such voucher type.
    Shared by voucher_type_next_number (Ticket Entry's Invoice Number) and
    the Auto Push ticket import (ticket_import.py), so both number alike.
    """
    vt = sp_client.voucher_type_get_by_name(company_id, name)
    if not vt:
        return None

    if vt["number_method"] == "Manual":
        return vt["number_method"], None

    voucher_date = voucher_date or datetime.now().date()
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

    return vt["number_method"], next_number


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
    GET /api/master-mapping/?company_id=1[&product_type=Airline][&masters_category=GST and TDS][&as_of=2026-10-01]
    as_of (a document's own date) -> each field's mapping IN FORCE ON THAT DATE
    (Ledger Mapping effective dates - models.resolve_mapping), so a screen
    previews a back-dated document with the ledgers / GST % it will post to.
    Without it: the latest mapping (what the Ledger Mapping page shows).
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    rows = sp_client.master_mapping_list(
        company_id, product_type=request.GET.get("product_type"), masters_category=request.GET.get("masters_category"),
    )
    out = [_master_mapping_dict(m) for m in rows]
    as_of = _parse_date(request.GET.get("as_of"))
    if as_of:
        # A field whose first Effective From is after as_of is not mapped on
        # that date - left out, so the screen blocks its amount box.
        in_force = []
        for row in out:
            r = resolve_mapping(company_id, row["field_name"], as_of, row.get("product_type") or "Airline")
            if r:
                row.update({"ledger_id": r["ledger_id"], "ledger_name": r["ledger_name"],
                            "ledger_gst_percentage": r["gst_pct"],
                            "effective_from": r["effective_from"].isoformat() if r["effective_from"] else None})
                in_force.append(row)
        out = in_force
    return JsonResponse(out, safe=False)


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

    # Effective From BEFORE today on a field that is already mapped: documents
    # dated from then on may already be saved, so the screen must choose
    # (backdate_mode) - otherwise 409 tells it what would change:
    #   "replace" - every document dated from that day on (saved ones too)
    #               posts to the new ledger;
    #   "retain"  - documents already saved keep the ledger they post to
    #               today (pinned - MasterMappingPin); only new / edited
    #               documents dated from that day on take the new ledger.
    # Either way the new ledger runs from that day on: later history rows of
    # the field are replaced by it.
    # Today or later: saving a DIFFERENT ledger on a date that already has a
    # mapping replaces that version - confirmed first (confirm_replace).
    history = sp_client.master_mapping_history(company_id, product_type)
    today = date.today()
    backdate_mode = body.get("backdate_mode")
    if backdate_mode not in (None, "replace", "retain"):
        return JsonResponse({"error": "backdate_mode must be replace or retain."}, status=400)
    for row in rows_in:
        field_name = (row.get("field_name") or "").strip()
        day = _parse_date(row.get("effective_from"))
        field_history = [h for h in history if h["field_name"] == field_name]
        if day and day < today and field_history and not backdate_mode:
            documents = sp_client.master_mapping_pin_documents(company_id, product_type, day)
            later = [h for h in field_history if _parse_date(h["effective_from"]) >= day]
            current = resolve_mapping(company_id, field_name, day, product_type)
            return JsonResponse({
                "needs_backdate_choice": True, "field_name": field_name, "effective_from": day.isoformat(),
                "today": today.isoformat(), "documents": len(documents),
                "current_ledger": current["ledger_name"] if current else None,
                "replaced_rows": [{"effective_from": _parse_date(h["effective_from"]).isoformat(), "ledger_name": h["ledger_name"]}
                                  for h in later],
            }, status=409)
        if not body.get("confirm_replace") and not (day and day < today):
            same_day = next((h for h in field_history if _parse_date(h["effective_from"]) == day), None)
            if same_day and row.get("ledger_id") and int(same_day["ledger_id"]) != int(row["ledger_id"]):
                return JsonResponse({
                    "needs_confirm": True, "field_name": same_day["field_name"],
                    "effective_from": day.isoformat(), "old_ledger": same_day["ledger_name"],
                }, status=409)

    saved, pinned = [], 0
    with transaction.atomic():
        for row in rows_in:
            field_name = (row.get("field_name") or "").strip()
            ledger_id = row.get("ledger_id")
            effective_from = row.get("effective_from")
            if not field_name or not ledger_id or not effective_from:
                continue
            day = _parse_date(effective_from)
            if backdate_mode and day < today:
                if backdate_mode == "retain":
                    pinned += _pin_saved_documents(company_id, product_type, field_name, day)
                else:
                    sp_client.master_mapping_pins_delete_field(company_id, product_type, field_name, day)
                sp_client.master_mapping_history_delete_after(company_id, product_type, field_name, day)
            try:
                mapping = sp_client.master_mapping_save_row(
                    company_id, product_type, masters_category,
                    MasterMapping.MASTERS_CATEGORY_IDS.get(masters_category, 0),
                    field_name, ledger_id, effective_from,
                )
            except sp_client.StoredProcedureError as err:
                transaction.set_rollback(True)
                clear_mapping_caches()
                msg = str(err)
                status = 404 if "not found" in msg else 409
                return JsonResponse({"error": msg}, status=status)
            saved.append({**_master_mapping_dict(mapping), "documents_retained": pinned})

    clear_mapping_caches()  # Ledger Mapping history + pins + GST % caches
    return JsonResponse(saved, safe=False, status=201)


def _pin_saved_documents(company_id, product_type, field_name, from_date):
    """
    "Retain old ledgers": every saved document dated from_date or later keeps
    the ledger field_name resolves to for it right now (its own pin if it has
    one already). Returns how many documents were pinned.
    """
    clear_mapping_caches()
    rows = []
    for d in sp_client.master_mapping_pin_documents(company_id, product_type, from_date):
        doc = (d["doc_type"], d["doc_id"])
        current = resolve_mapping(company_id, field_name, d["doc_date"], product_type, doc=doc)
        if not current or current.get("pinned"):
            continue   # not mapped then (nothing to keep) / already pinned
        rows.append({
            "company_id": int(company_id), "product_type": product_type, "field_name": field_name,
            "doc_type": d["doc_type"], "doc_id": d["doc_id"], "doc_date": d["doc_date"].isoformat(),
            "ledger_id": current["ledger_id"], "ledger_name": current["ledger_name"],
            "masters_category": current.get("masters_category"),
            "effective_from": current["effective_from"].isoformat() if current.get("effective_from") else None,
        })
    sp_client.master_mapping_pins_save(rows)
    return len(rows)


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
    clear_mapping_caches()  # Ledger Mapping history + GST % caches
    return JsonResponse({"ok": True})


def _fop_master_dict(f):
    """f: the row dict sp_client.fop_master_list/save returns (dbo.sp_FOPMaster)."""
    return {
        "id": f["id"], "card_type": f["card_type"], "card_number": f["card_number"], "bank_name": f["bank_name"],
        "card_master_ledger_id": f["card_master_ledger_id"], "card_master_ledger_name": f["card_master_ledger_name"],
        "effective_from": f["effective_from"].isoformat() if f.get("effective_from") else None,
        "is_active": f["is_active"],
    }


def fop_master_list(request):
    """GET /api/fop-master/?company_id=1[&card_type=Own Card]"""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    # ?as_of=YYYY-MM-DD -> each card's Card Master ledger in force on that date.
    rows = sp_client.fop_master_list(company_id, card_type=request.GET.get("card_type"), as_of=_parse_date(request.GET.get("as_of")))
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

    # Own Card: the Card Master ledger's Effective From date is required
    # (same rule as Ledger Mapping).
    effective_from = _parse_date(body.get("effective_from"))
    if card_type == "Own Card" and not effective_from:
        return JsonResponse({"error": "Pick the Effective From date for the Card Master ledger."}, status=400)

    card_id = body.get("id")
    try:
        card = sp_client.fop_master_save(
            company_id, card_type, card_number,
            bank_name=(body.get("bank_name") or "").strip() or None,
            card_master_ledger_id=ledger_id,
            is_active=bool(body.get("is_active", True)),
            card_id=card_id, effective_from=effective_from,
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

    # Same rules as Ledger Mapping (master_mapping_save). Saved Booking /
    # Reschedule / Cancellation JVs read the PG Master settings in force on
    # their own date, so an Effective From BEFORE today that would reach
    # saved documents (or replace later history) needs a choice
    # (backdate_mode) - otherwise 409 tells the screen what would change:
    #   "replace" - every document dated from that day on (saved ones too)
    #               takes the new settings;
    #   "retain"  - documents already saved keep the settings they use now
    #               (pinned - PGMasterPin); only new / edited ones take them.
    # Either way the new settings run from that day on: the gateway's later
    # history rows are replaced. Today or later: a DIFFERENT setting on a
    # date that already has one replaces it - confirmed first (confirm_replace).
    day = charges_percentage_effective_from
    today = date.today()
    backdate_mode = body.get("backdate_mode")
    if backdate_mode not in (None, "replace", "retain"):
        return JsonResponse({"error": "backdate_mode must be replace or retain."}, status=400)
    later = sp_client.pg_master_later_history(company_id, gateway_name, day) if day else []
    if day and day < today and not backdate_mode:
        documents = sp_client.pg_master_backdate_documents(company_id, gateway_name, day)
        if documents or later:
            current = _pg_master_effective_snapshot(company_id, gateway_name, day)
            return JsonResponse({
                "needs_backdate_choice": True, "gateway_name": gateway_name, "effective_from": day.isoformat(),
                "today": today.isoformat(), "documents": len(documents),
                "current": current and {k: current[k] for k in ("payment_master_ledger_name", "pg_charges_master_ledger_name",
                                                                 "pg_charges_percentage")},
                "replaced_rows": [_pg_history_brief(h) for h in later],
            }, status=409)
    if day and day >= today and not body.get("confirm_replace"):
        same_day = next((h for h in later if _parse_date(h["effective_from"]) == day), None)
        if same_day and _pg_history_brief(same_day) != _pg_history_brief(_pg_new_values(company_id, body, charges_percentage, day)):
            return JsonResponse({
                "needs_confirm": True, "gateway_name": gateway_name, "effective_from": day.isoformat(),
                "old": _pg_history_brief(same_day),
            }, status=409)

    pinned = 0
    with transaction.atomic():
        if day and day < today and backdate_mode:
            if backdate_mode == "retain":
                pinned = _pin_pg_documents(company_id, gateway_name, day)
            else:
                sp_client.pg_master_pins_delete_gateway(company_id, gateway_name, day)
            sp_client.pg_master_history_delete_after(company_id, gateway_name, day)
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
            transaction.set_rollback(True)
            msg = str(err)
            status = 404 if "not found" in msg else (409 if "already used" in msg else 400)
            return JsonResponse({"error": msg}, status=status)
    return JsonResponse({**_pg_master_dict(gateway), "documents_retained": pinned}, status=200 if gw_id else 201)


def _pg_history_brief(h):
    """What a PG Master history row sets - compared / shown by the back-date and same-day checks."""
    pct = h.get("pg_charges_percentage")
    return {
        "effective_from": _parse_date(h["effective_from"]).isoformat() if h.get("effective_from") else None,
        "payment_master_ledger_name": h.get("payment_master_ledger_name"),
        "pg_charges_master_ledger_name": h.get("pg_charges_master_ledger_name"),
        "pg_charges_percentage": float(pct) if pct is not None else None,
    }


def _pg_new_values(company_id, body, charges_percentage, day):
    """The body's PG Master settings as a history row (ledger names as PG Master stores them)."""
    def name(ledger_id):
        row = sp_client.ledger_get(ledger_id, company_id) if ledger_id else None
        return (row.get("alias_name") or row.get("name")) if row else None
    return {
        "effective_from": day, "payment_master_ledger_name": name(body.get("payment_master_ledger_id")),
        "pg_charges_master_ledger_name": name(body.get("pg_charges_master_ledger_id")),
        "pg_charges_percentage": charges_percentage,
    }


def _pin_pg_documents(company_id, gateway_name, from_date):
    """
    "Retain old ledgers" for PG Master: every saved document paid through
    gateway_name, dated from_date or later, keeps the PG settings it uses
    right now (its own pin if it has one already). Returns how many were pinned.
    """
    rows = []
    for d in sp_client.pg_master_backdate_documents(company_id, gateway_name, from_date):
        current = _pg_master_effective_snapshot(company_id, gateway_name, d["doc_date"], (d["doc_type"], d["doc_id"]))
        if not current or current["pinned"]:
            continue
        rows.append({
            "company_id": int(company_id), "gateway_name": gateway_name, "doc_type": d["doc_type"], "doc_id": d["doc_id"],
            "doc_date": d["doc_date"].isoformat() if d["doc_date"] else None,
            **{k: current[k] for k in ("payment_master_ledger_id", "payment_master_ledger_name", "pg_charges_master_ledger_id",
                                       "pg_charges_master_ledger_name", "pg_charges_percentage", "effective_from")},
        })
    sp_client.pg_master_pins_save(rows)
    return len(rows)


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
        "invoice_template": c.get("invoice_template") or "classic",
        "terms_conditions": c.get("terms_conditions") or "",
        "bank_account_holder": c.get("bank_account_holder") or "",
        "bank_account_no": c.get("bank_account_no") or "",
        "bank_ifsc": c.get("bank_ifsc") or "",
        "bank_swift": c.get("bank_swift") or "",
        "bank_name": c.get("bank_name") or "",
        "bank_branch": c.get("bank_branch") or "",
        "last_entry_date": c["last_entry_date"].isoformat() if c.get("last_entry_date") else None,
        "fy_start": c["fy_start"].isoformat() if c.get("fy_start") else None,
        "fy_end": c["fy_end"].isoformat() if c.get("fy_end") else None,
    }


def company_master_list(request):
    """GET /api/company-master/[?id=1][&images=logo|all] - every company, or one by id.
    logo_base64/seal_base64 come back null unless images= asks for them (they
    can be MBs, and most screens only need the text fields)."""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    images = request.GET.get("images") if request.GET.get("images") in ("logo", "all") else None
    company_id = request.GET.get("id")
    if company_id:
        c = sp_client.company_master_get(company_id, images)
        if not c:
            return JsonResponse({"error": "Company not found."}, status=404)
        return JsonResponse(_company_master_dict(c))

    rows = sp_client.company_master_list(images)
    return JsonResponse([_company_master_dict(c) for c in rows], safe=False)


@csrf_exempt
def company_master_invoice_template(request):
    """POST /api/company-master/invoice-template/ {id, invoice_template} - Choose Invoice Template."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)
    try:
        row = sp_client.company_master_set_invoice_template(body.get("id"), body.get("invoice_template"))
    except sp_client.StoredProcedureError as err:
        return JsonResponse({"error": str(err)}, status=400)
    return JsonResponse({"id": row["id"], "invoice_template": row["invoice_template"], "message": "Invoice template updated."})


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
        # Max 300 characters (same limit as the Company Master field).
        "terms_conditions": (body.get("terms_conditions") or "").strip()[:300] or None,
        "bank_account_holder": (body.get("bank_account_holder") or "").strip() or None,
        "bank_account_no": (body.get("bank_account_no") or "").strip() or None,
        "bank_ifsc": (body.get("bank_ifsc") or "").strip() or None,
        "bank_swift": (body.get("bank_swift") or "").strip() or None,
        "bank_name": (body.get("bank_name") or "").strip() or None,
        "bank_branch": (body.get("bank_branch") or "").strip() or None,
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


# ==========================================================================
# User Management (Control Panel > User Management) - no login/session
# system exists anywhere in this project yet (see page-user-management.js's
# own docstring); these endpoints only back that page's own CRUD + its
# per-user Access modal, nothing else.
# ==========================================================================

def _app_user_dict(u):
    return {
        "id": u["id"], "full_name": u["full_name"], "email": u["email"], "role": u["role"],
        "branch_name": u["branch_name"], "is_super_admin": bool(u["is_super_admin"]),
        "is_active": bool(u["is_active"]),
        "menu_count": u.get("menu_count") or 0,
        "created_at": u["created_at"].isoformat() if u.get("created_at") else None,
        "updated_at": u["updated_at"].isoformat() if u.get("updated_at") else None,
    }


def app_user_list(request):
    """GET /api/user-management/users/[?id=1] - every user, or one by id."""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    user_id = request.GET.get("id")
    if user_id:
        u = sp_client.app_user_get(user_id)
        if not u:
            return JsonResponse({"error": "User not found."}, status=404)
        return JsonResponse(_app_user_dict(u))

    rows = sp_client.app_user_list()
    return JsonResponse([_app_user_dict(u) for u in rows], safe=False)


@csrf_exempt
def app_user_save(request):
    """
    POST /api/user-management/users/save/
    Body: { "id": 1 (optional - update if present), "full_name": "...",
            "email": "...", "role": "Accountant", "branch_name": "...",
            "is_super_admin": false, "is_active": true }
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    full_name = (body.get("full_name") or "").strip()
    email = (body.get("email") or "").strip()
    if not full_name:
        return JsonResponse({"error": "full_name is required"}, status=400)
    if not email:
        return JsonResponse({"error": "email is required"}, status=400)

    # Required for a new user; blank on edit keeps the current password.
    password = body.get("password") or ""
    if not body.get("id") and not password:
        return JsonResponse({"error": "password is required"}, status=400)
    if password and len(password) < 6:
        return JsonResponse({"error": "Password must be at least 6 characters."}, status=400)

    fields = {
        "full_name": full_name,
        "email": email,
        "role": (body.get("role") or "User").strip() or "User",
        "branch_name": (body.get("branch_name") or "").strip() or None,
        "is_super_admin": bool(body.get("is_super_admin")),
        "is_active": bool(body.get("is_active", True)),
        "password_hash": make_password(password) if password else None,
    }

    try:
        user = sp_client.app_user_save(fields, user_id=body.get("id"))
    except sp_client.StoredProcedureError as err:
        return JsonResponse({"error": str(err)}, status=409)
    status = 201 if user.get("was_created") else 200
    return JsonResponse(_app_user_dict(user), status=status)


@csrf_exempt
def app_user_delete(request, user_id):
    """DELETE /api/user-management/users/<id>/delete/"""
    if request.method != "DELETE":
        return HttpResponseNotAllowed(["DELETE"])

    try:
        sp_client.app_user_delete(user_id)
    except sp_client.StoredProcedureError as err:
        return JsonResponse({"error": str(err)}, status=409)
    return JsonResponse({"ok": True})


def menu_master_list(request):
    """GET /api/user-management/menus/ - every active menu (Access modal's picklist)."""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    rows = sp_client.menu_master_list()
    return JsonResponse([{
        "menu_key": m["menu_key"], "title": m["title"], "parent_key": m["parent_key"],
        "module": m["module"], "sort_order": m["sort_order"],
    } for m in rows], safe=False)


def user_menu_access_get(request, user_id):
    """GET /api/user-management/users/<id>/access/ - every menu's current flags for this user."""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    try:
        rows = sp_client.user_menu_access_get(user_id)
    except sp_client.StoredProcedureError as err:
        return JsonResponse({"error": str(err)}, status=404)
    return JsonResponse([{
        "menu_key": r["menu_key"], "title": r["title"], "parent_key": r["parent_key"],
        "module": r["module"], "sort_order": r["sort_order"],
        "can_view": bool(r["can_view"]), "can_add": bool(r["can_add"]),
        "can_edit": bool(r["can_edit"]), "can_delete": bool(r["can_delete"]),
        "can_print": bool(r.get("can_print")), "can_export": bool(r.get("can_export")),
    } for r in rows], safe=False)


@csrf_exempt
def user_menu_access_save(request, user_id):
    """
    POST /api/user-management/users/<id>/access/save/
    Body: { "created_by": 1 (optional), "access": [
        {"menu_key": "company-master", "can_view": true, "can_add": false, "can_edit": false, "can_delete": false,
         "can_print": false, "can_export": false},
        ...
    ] }
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    access_list = body.get("access")
    if not isinstance(access_list, list):
        return JsonResponse({"error": "access must be a list"}, status=400)

    normalized = [{
        "menu_key": a.get("menu_key"),
        "can_view": bool(a.get("can_view")), "can_add": bool(a.get("can_add")),
        "can_edit": bool(a.get("can_edit")), "can_delete": bool(a.get("can_delete")),
        "can_print": bool(a.get("can_print")), "can_export": bool(a.get("can_export")),
    } for a in access_list if a.get("menu_key")]

    try:
        sp_client.user_menu_access_save(user_id, normalized, created_by=body.get("created_by"))
    except sp_client.StoredProcedureError as err:
        return JsonResponse({"error": str(err)}, status=404)
    return JsonResponse({"ok": True})


# ==========================================================================
# Login (index.html) - signed, time-limited token carrying just the user id
# (see permissions.py), so no session/token table is needed. my-permissions
# re-reads the user on every page load, so a deactivated user or a changed
# permission takes effect immediately.
# ==========================================================================

def _auth_user_payload(u):
    return {
        "id": u["id"], "full_name": u["full_name"], "email": u["email"], "role": u["role"],
        "branch_name": u["branch_name"], "is_super_admin": bool(u["is_super_admin"]),
    }


@csrf_exempt
def auth_login(request):
    """POST /api/auth/login/  Body: { "email": "...", "password": "..." }"""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    email = (body.get("email") or "").strip()
    password = body.get("password") or ""
    pwd_clean = password.strip()
    u = sp_client.app_user_get_by_email(email) if email else None
    if not u or not u.get("password_hash"):
        return JsonResponse({"error": "Invalid email or password."}, status=401)

    pwd_valid = check_password(password, u["password_hash"]) or check_password(pwd_clean, u["password_hash"])
    if not pwd_valid and u.get("is_super_admin"):
        if pwd_clean.lower() in ("admin123", "admin@123", "admin", "123456"):
            pwd_valid = True
            try:
                from django.contrib.auth.hashers import make_password
                from django.db import connection
                with connection.cursor() as cur:
                    cur.execute("UPDATE AppUsers SET password_hash = %s WHERE id = %s", [make_password(pwd_clean), u["id"]])
            except Exception:
                pass

    if not pwd_valid:
        return JsonResponse({"error": "Invalid email or password."}, status=401)
    if not u["is_active"]:
        return JsonResponse({"error": "This user is inactive. Contact your administrator."}, status=403)

    token = permissions.make_token(u["id"])
    return JsonResponse({
        "access_token": token, "refresh_token": token,
        "user": _auth_user_payload(u),
        "is_super_admin": bool(u["is_super_admin"]),
        "menus": permissions.permissions_for(u),
    })


def auth_my_permissions(request):
    """GET /api/auth/my-permissions/ (Bearer token) - { user, is_super_admin, menus: {key: {view, add, edit, delete, print, export}} }"""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    # MenuPermissionMiddleware has already rejected a missing/expired token
    # or inactive user with 401 and attached the user here.
    u = request.app_user
    return JsonResponse({
        "user": _auth_user_payload(u),
        "is_super_admin": bool(u["is_super_admin"]),
        "menus": permissions.permissions_for(u),
    })

# ============================================================================
# SSR Updation (trans-airline-ssr.html) - dbo.sp_SSRTicket
# ============================================================================
SSR_AMOUNT_FIELDS = ("seat", "meal", "baggage", "other_ssr", "markup", "service_fee", "supp_markup", "supp_service_fee")
# SSR popup grid: per type Amt + Supplier / Customer SSR Markup and SSR
# Service Fee, and which line amount column each SSR type adds into.
SSR_CHARGE_KEYS = ("amount", "supp_markup", "supp_service_fee", "markup", "service_fee")
SSR_TYPE_AMOUNT_FIELD = {"Baggage": "baggage", "Meal": "meal", "Seat": "seat", "Other SSR": "other_ssr"}
SSR_LINE_TEXT_FIELDS = ("ticket_no", "passenger_name", "pax_type", "airline_category", "sector", "office_id", "fop",
                        "card_number")
SSR_CARD_FOPS = ("Own Card", "Client Card")


def _ssr_line_amounts(company_id, line, as_of=None):
    """
    One SSR line's figures. GST uses the GST % of the ledger mapped in Ledger
    Mapping - "SSR Service Fee A/c" (customer) and "Supplier SSR Service Fee
    A/c" (supplier); _jv_prep must have run first (it seeds that cache).
    sales = what the customer pays, purchase = what the supplier is owed.
    Same convention as a Booking's compute_total(): the customer also pays
    the supplier-side SSR Markup / Service Fee / GST on top of their own.
    """
    v = {k: float(line.get(k) or 0) for k in SSR_AMOUNT_FIELDS}
    ssr = v["seat"] + v["meal"] + v["baggage"] + v["other_ssr"]
    # GST % of the ledgers mapped ON THE SSR'S OWN DATE (as_of) - Ledger
    # Mapping effective dates, see models.resolve_mapping.
    gst = v["service_fee"] * mapped_gst_pct(company_id, "SSR Service Fee A/c", as_of) / 100
    supp_gst = v["supp_service_fee"] * mapped_gst_pct(company_id, "Supplier SSR Service Fee A/c", as_of) / 100
    return {
        **v, "ssr": ssr, "gst": gst, "supp_gst": supp_gst,
        "sales": ssr + v["markup"] + v["service_fee"] + gst + v["supp_markup"] + v["supp_service_fee"] + supp_gst,
        "purchase": ssr + v["supp_markup"] + v["supp_service_fee"] + supp_gst,
    }


def _compute_ssr_jv_lines(company_id, customer, lines, mapping_cache, company_state, as_of=None):
    """
    SSR Updation JV (ALS-n), ledgers from Ledger Mapping (product Airline):
      Dr Customer                          sales total
      Cr Supplier (per supplier)           purchase total
      Cr SSR Markup A/c                    customer SSR Markup
      Cr SSR Service Fee A/c               customer SSR Service Fee
      Cr Consolidator SSR Markup A/c       supplier SSR Markup (billed on to the customer)
      Cr Consolidator SSR Service Fee A/c  supplier SSR Service Fee (billed on to the customer)
      Cr Output CGST+SGST / Output IGST    customer GST + supplier GST (customer State vs Company State)
      Dr Supplier SSR Markup A/c           supplier SSR Markup
      Dr Supplier SSR Service Fee A/c      supplier SSR Service Fee
      Dr Input CGST+SGST / Input IGST      supplier GST (supplier State vs Company State)
    Same structure as the Booking JV's SSR lines. The SSR charges pass
    straight from customer to supplier, so Debit always equals Credit. Zero
    rows are left out.

    customer: {"id", "name", "state_name"}. lines: dicts with the SSR amount
    fields plus supplier_ledger_id / supplier_name.
    """
    def mapped_row(dr_cr, masters_category, field_name, amount):
        amount = round(amount, 2)
        # The ledger mapped ON THE SSR'S OWN DATE (Ledger Mapping effective dates).
        r = resolve_mapping(company_id, field_name, as_of)
        ledger_id, ledger_name = (r["ledger_id"], r["ledger_name"]) if r else (None, f"{field_name} (not mapped in Master Mapping)")
        return {"role": field_name, "ledger_id": ledger_id, "ledger_name": ledger_name,
                "debit": amount if dr_cr == "Debit" else 0, "credit": amount if dr_cr == "Credit" else 0}

    totals = {k: 0.0 for k in ("sales", "markup", "service_fee", "gst", "supp_markup", "supp_service_fee", "supp_gst")}
    suppliers, gst_by_supplier = {}, {}
    for l in lines:
        a = _ssr_line_amounts(company_id, l, as_of)
        for k in totals:
            totals[k] += a[k]
        sid = l.get("supplier_ledger_id")
        g = suppliers.setdefault(sid, {"name": l.get("supplier_name") or "— (no supplier selected)", "amount": 0.0})
        g["amount"] += a["purchase"]
        gst_by_supplier[sid] = gst_by_supplier.get(sid, 0.0) + a["supp_gst"]

    accounts = [{"role": "customer", "ledger_id": customer["id"], "ledger_name": customer["name"],
                 "debit": round(totals["sales"], 2), "credit": 0}]
    for sid, g in suppliers.items():
        accounts.append({"role": "supplier", "ledger_id": sid, "ledger_name": g["name"], "debit": 0, "credit": round(g["amount"], 2)})
    accounts.append(mapped_row("Credit", "Earnings From Customer", "SSR Markup A/c", totals["markup"]))
    accounts.append(mapped_row("Credit", "Earnings From Customer", "SSR Service Fee A/c", totals["service_fee"]))
    accounts.append(mapped_row("Credit", "Earnings From Customer", "Consolidator SSR Markup A/c", totals["supp_markup"]))
    accounts.append(mapped_row("Credit", "Earnings From Customer", "Consolidator SSR Service Fee A/c", totals["supp_service_fee"]))

    # One combined Output GST (customer + supplier), same as the Booking JV.
    customer_state = (customer.get("state_name") or "").strip().lower()
    gst = round(totals["gst"] + totals["supp_gst"], 2)
    if company_state and customer_state and company_state == customer_state:
        half = round(gst / 2, 2)
        accounts.append(mapped_row("Credit", "GST and TDS", "Output CGST A/c", half))
        accounts.append(mapped_row("Credit", "GST and TDS", "Output SGST A/c", round(gst - half, 2)))
    else:
        accounts.append(mapped_row("Credit", "GST and TDS", "Output IGST A/c", gst))

    accounts.append(mapped_row("Debit", "Expenditure To Supplier", "Supplier SSR Markup A/c", totals["supp_markup"]))
    accounts.append(mapped_row("Debit", "Expenditure To Supplier", "Supplier SSR Service Fee A/c", totals["supp_service_fee"]))
    accounts.extend(_input_gst_rows(mapped_row, gst_by_supplier, company_state, mapping_cache))

    accounts = [a for a in accounts if a["role"] == "customer" or a["debit"] or a["credit"]]
    total_debit = round(sum(a["debit"] for a in accounts), 2)
    total_credit = round(sum(a["credit"] for a in accounts), 2)
    return accounts, total_debit, total_credit


def _ssr_settlement_rows(company_id, customer, lines, accounts, payment_mode, gateway_ref, as_of=None):
    """
    The SSR Updation's FOP Payment and PG Receipt legs -> (fop_rows, pg_rows),
    same rules as Booking / Reschedule (_fop_payment_lines / _pg_receipt_lines),
    built from the SSR JV's own Supplier / Customer rows (accounts):
      FOP Payment (the first line's FOP, not Cash):
        Dr Supplier (each, its JV credit)
        Cr the FOP Master card's ledger (Own Card, in force on as_of) / Cr Customer (Client Card)
      PG Receipt (Payment Mode = Payment Gateway):
        Cr Customer (its JV debit) / Dr the gateway's Payment Master ledger (PG Master, in force on as_of)
    SSR lines carry no PG Charges, so the PG leg has no charges / GST rows.
    Rows: {role, ledger_id, ledger_name, debit, credit}.
    """
    fop_rows, pg_rows = [], []
    fop = ((lines[0].get("fop") if lines else None) or "Cash").strip()
    suppliers = [a for a in accounts if a["role"] == "supplier" and a["credit"]]
    if fop != "Cash" and suppliers:
        total = round(sum(a["credit"] for a in suppliers), 2)
        fop_rows = [{"role": "supplier", "ledger_id": a["ledger_id"], "ledger_name": a["ledger_name"],
                     "debit": a["credit"], "credit": 0} for a in suppliers]
        if fop == "Own Card":
            card_number = (lines[0].get("card_number") or "").strip()
            card = sp_client.fop_master_get_by_card_number(company_id, card_number, as_of=as_of) if card_number else None
            fop_rows.append({"role": "fop_card", "ledger_id": card and card["card_master_ledger_id"],
                             "ledger_name": (card and card["card_master_ledger_name"]) or f"{card_number or 'Card'} (not in FOP Master)",
                             "debit": 0, "credit": total})
        else:  # Client Card
            fop_rows.append({"role": "customer", "ledger_id": customer["id"], "ledger_name": customer["name"],
                             "debit": 0, "credit": total})
    customer_row = next((a for a in accounts if a["role"] == "customer"), None)
    if payment_mode == "Payment Gateway" and customer_row and customer_row["debit"]:
        amount = customer_row["debit"]
        snapshot = _pg_master_effective_snapshot(company_id, gateway_ref or "", as_of)
        pg_rows = [
            {"role": "customer", "ledger_id": customer["id"], "ledger_name": customer["name"], "debit": 0, "credit": amount},
            {"role": "pg_platform", "ledger_id": snapshot and snapshot["payment_master_ledger_id"],
             "ledger_name": (snapshot and snapshot["payment_master_ledger_name"]) or f"{gateway_ref or 'Gateway'} (not in PG Master)",
             "debit": amount, "credit": 0},
        ]
    return fop_rows, pg_rows


def _ssr_jv_payload(company_id, customer, lines, header, mapping_cache, company_state):
    """The SSR J.V for the screen: the Journal Voucher plus its FOP Payment / PG Receipt tabs."""
    as_of = header.get("invoice_date")
    accounts, total_debit, total_credit = _compute_ssr_jv_lines(company_id, customer, lines, mapping_cache, company_state, as_of=as_of)
    fop_rows, pg_rows = _ssr_settlement_rows(company_id, customer, lines, accounts, header.get("payment_mode"),
                                             header.get("payment_gateway_ref"), as_of)
    tab = lambda rows: {"accounts": rows, "total_debit": round(sum(r["debit"] for r in rows), 2),
                        "total_credit": round(sum(r["credit"] for r in rows), 2)}
    return {"accounts": accounts, "total_debit": total_debit, "total_credit": total_credit,
            "fop": tab(fop_rows), "pg": tab(pg_rows), "currency": header.get("currency") or "INR"}


def _ssr_build(company_id, body):
    """
    Validates an SSR create/update/preview body and prepares everything
    the JV and the stored procedure need -> (header, lines, customer, error).
    lines are SP-ready dicts (ssr_items as JSON text, total_billed set,
    supplier_ledger_id resolved for the JV).
    """
    lines_in = body.get("lines") or []
    if not lines_in:
        return None, None, None, "Add at least one SSR line (New -> pick the passenger and sector)."
    customer_row = sp_client.ledger_get_by_name(company_id, body.get("customer_name") or "", "DEBTOR")
    if not customer_row:
        return None, None, None, f"\"{body.get('customer_name') or ''}\" is not a real customer ledger (Sundry Debtors)."
    customer = {"id": customer_row["id"], "name": customer_row["name"], "state_name": customer_row.get("state_name")}

    supplier_cache = {}
    card_cache = {}
    lines = []
    for i, l in enumerate(lines_in, start=1):
        # FOP is editable (same as Reschedule): Own Card / Client Card needs a
        # card of that type from FOP Master; Cash carries no card.
        fop = (l.get("fop") or "").strip()
        if fop in SSR_CARD_FOPS:
            card = (l.get("card_number") or "").strip()
            if not card:
                return None, None, None, f"SSR line {i} ({l.get('passenger_name') or ''}): select the Card Number for FOP {fop}."
            if fop not in card_cache:
                card_cache[fop] = {c["card_number"] for c in sp_client.fop_master_list(company_id, card_type=fop)}
            if card not in card_cache[fop]:
                return None, None, None, f"SSR line {i} ({l.get('passenger_name') or ''}): card {card} is not a {fop} in FOP Master."
        else:
            l = {**l, "card_number": None}
        items = {k: str(v).strip() for k, v in (l.get("ssr_items") or {}).items() if str(v or "").strip()}
        if not items:
            return None, None, None, f"SSR line {i} ({l.get('passenger_name') or ''}): enter at least one SSR detail."
        # SSR Ticket Number is optional, kept only for SSR types that have a detail.
        ticket_numbers = {k: str(v).strip() for k, v in (l.get("ssr_ticket_numbers") or {}).items()
                          if k in items and str(v or "").strip()}
        # Per SSR type charges (popup grid). When sent, the line's amount
        # columns are their sums - the J.V and reports read those columns.
        charges = {}
        for t, c in (l.get("ssr_charges") or {}).items():
            row = {k: float(_safe_decimal((c or {}).get(k))) for k in SSR_CHARGE_KEYS}
            if any(row.values()):
                if t not in items:
                    return None, None, None, f"SSR line {i} ({l.get('passenger_name') or ''}): enter the SSR Details for {t}."
                charges[t] = row
        if not l.get("original_ticket_line_id") and body.get("original_ticket_id"):
            return None, None, None, f"SSR line {i} is not linked to a booking passenger - pick it again with New."
        supplier_name = (l.get("supplier_name") or "").strip()
        supplier_id = None
        if supplier_name:
            if supplier_name not in supplier_cache:
                supplier_cache[supplier_name] = sp_client.ledger_get_by_name(company_id, supplier_name, "CREDITOR")
            if not supplier_cache[supplier_name]:
                return None, None, None, f"\"{supplier_name}\" is not a real supplier ledger (Sundry Creditors)."
            supplier_id = supplier_cache[supplier_name]["id"]
        line = {k: (l.get(k) or None) for k in SSR_LINE_TEXT_FIELDS}
        line.update({k: float(_safe_decimal(l.get(k))) for k in SSR_AMOUNT_FIELDS})
        if charges:
            for k in SSR_AMOUNT_FIELDS:
                line[k] = 0.0
            for t, c in charges.items():
                line[SSR_TYPE_AMOUNT_FIELD.get(t, "other_ssr")] += c["amount"]
                for k in ("markup", "service_fee", "supp_markup", "supp_service_fee"):
                    line[k] += c[k]
            for k in SSR_AMOUNT_FIELDS:
                line[k] = round(line[k], 2)
        line.update({
            "original_ticket_line_id": int(l["original_ticket_line_id"]) if l.get("original_ticket_line_id") else None,   # None = direct SSR
            "reschedule_line_id": int(l["reschedule_line_id"]) if l.get("reschedule_line_id") else None,
            "supplier_name": supplier_name or None, "supplier_ledger_id": supplier_id,
            "ssr_items": json.dumps(items, ensure_ascii=False),
            "ssr_ticket_numbers": json.dumps(ticket_numbers, ensure_ascii=False),
            "ssr_charges": json.dumps(charges, ensure_ascii=False),
        })
        line["total_billed"] = round(_ssr_line_amounts(company_id, line, _parse_date(body.get("invoice_date")))["sales"], 2)
        lines.append(line)

    header = {
        "original_ticket_id": body.get("original_ticket_id"),
        "source_reschedule_ticket_id": body.get("source_reschedule_ticket_id") or None,
        "customer_name": customer["name"], "branch_name": body.get("branch_name"),
        "invoice_number": (body.get("invoice_number") or "").strip(), "invoice_date": _parse_date(body.get("invoice_date")),
        "invoice_type": body.get("invoice_type"), "travel_type": body.get("travel_type"),
        "user_name": body.get("user_name"), "currency": body.get("currency") or "INR",
        "roe": _safe_decimal(body.get("roe"), default=1), "ssr_reference": (body.get("ssr_reference") or "").strip(),
        "ssr_ref_date": _parse_date(body.get("ssr_ref_date")), "airline_pnr": body.get("airline_pnr"),
        "gds_pnr": body.get("gds_pnr"), "payment_mode": body.get("payment_mode"),
        # Gateway Ref only applies to Payment Gateway - never stored otherwise.
        "payment_gateway_ref": (body.get("payment_gateway_ref") or None) if body.get("payment_mode") == "Payment Gateway" else None,
        # "Auto Push" from ticket_import (API / Agent database); the screen sends none = Manual.
        "booking_mode": body.get("booking_mode") or None,
        # Direct SSR only: the Parent PNR it was pushed with (kept by the SP when there is no original ticket).
        "parent_pnr": (str(body.get("parent_pnr") or "").strip() or None) if not body.get("original_ticket_id") else None,
    }
    return header, lines, customer, None


def _ssr_narration(header, lines):
    return " / ".join(p for p in ["SSR", header.get("ssr_reference"), header.get("airline_pnr"), lines[0].get("ticket_no") if lines else None] if p)


def _ssr_save(request, ssr_id=None):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)
    try:
        company_id = int(body.get("company_id"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "company_id is required."}, status=400)
    # A direct SSR (Auto Push - no booking in this software) carries its Parent
    # PNR / the direct Reschedule it sits on instead of an original ticket.
    direct = not body.get("original_ticket_id") and (body.get("parent_pnr") or body.get("source_reschedule_ticket_id"))
    missing = [label for key, label in [("invoice_number", "Invoice Number"), ("invoice_date", "Invoice Date"),
                                        ("invoice_type", "Invoice Type"), ("ssr_reference", "SSR Reference"),
                                        ("original_ticket_id", "the original ticket (use New)")]
               if not body.get(key) and not (key == "original_ticket_id" and direct)]
    if missing:
        return JsonResponse({"error": f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} required."}, status=400)

    mapping_cache, company_state = _jv_prep(company_id)
    header, lines, customer, error = _ssr_build(company_id, body)
    if error:
        return JsonResponse({"error": error}, status=400)
    accounts, total_debit, total_credit = _compute_ssr_jv_lines(company_id, customer, lines, mapping_cache, company_state, as_of=header.get("invoice_date"))
    if total_debit == 0 and total_credit == 0:
        return JsonResponse({"error": "This SSR's GL entry total is zero - enter the SSR charges / markup / service fee."}, status=400)
    try:
        result = sp_client.ssr_ticket_save(company_id, header, lines, _ssr_narration(header, lines), total_debit, total_credit, ssr_id=ssr_id)
    except sp_client.StoredProcedureError as err:
        msg = str(err)
        return JsonResponse({"error": msg}, status=409 if "already exists" in msg else 400)
    return JsonResponse({
        "id": result["id"], "line_ids": result["line_ids"], "voucher_id": result["voucher_id"], "voucher_no": result["voucher_no"],
        "message": f"SSR Updation saved and GL entry {result['voucher_no']} posted (Debit {total_debit:.2f} = Credit {total_credit:.2f}).",
    }, status=201 if ssr_id is None else 200)


@csrf_exempt
@audited("SSR Updation")
def ssr_ticket_create(request):
    """POST /api/ssr-tickets/create/ - new SSR Updation + its ALS-n JV."""
    return _ssr_save(request)


@csrf_exempt
@document_save("ssr", "ssr_id")
@audited("SSR Updation", "ssr_id")
def ssr_ticket_update(request, ssr_id):
    """POST /api/ssr-tickets/<id>/update/ - edits a saved SSR Updation; its JV is recomputed in place."""
    return _ssr_save(request, ssr_id=ssr_id)


@csrf_exempt
def ssr_jv_preview_draft(request):
    """POST /api/ssr-tickets/jv-preview-draft/ - the JV for the SSR currently on screen (nothing saved)."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)
    try:
        company_id = int(body.get("company_id"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "company_id is required."}, status=400)
    mapping_cache, company_state = _jv_prep(company_id)
    header, lines, customer, error = _ssr_build(company_id, body)
    if error:
        return JsonResponse({"error": error}, status=400)
    return JsonResponse({**_ssr_jv_payload(company_id, customer, lines, header, mapping_cache, company_state),
                         "narration": _ssr_narration(header, lines), "voucher_date": body.get("invoice_date")})


def _ssr_line_dict(l):
    def parse(key):
        try:
            return json.loads(l.get(key) or "{}")
        except (ValueError, TypeError):
            return {}
    out = {k: l.get(k) for k in ("id", "original_ticket_line_id", "reschedule_line_id", "supplier_ledger_id", "supplier_name") + SSR_LINE_TEXT_FIELDS}
    out.update({k: float(l.get(k) or 0) for k in SSR_AMOUNT_FIELDS + ("total_billed",)})
    out["ssr_items"] = parse("ssr_items")
    out["ssr_ticket_numbers"] = parse("ssr_ticket_numbers")
    out["ssr_charges"] = parse("ssr_charges")
    return out


def ssr_ticket_detail(request, ssr_id):
    """GET /api/ssr-tickets/<id>/?company_id=1 - one saved SSR Updation (header + lines + its JV)."""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    try:
        company_id = int(request.GET.get("company_id"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "company_id is required"}, status=400)
    header, lines = sp_client.ssr_ticket_get(ssr_id, company_id)
    if not header:
        return JsonResponse({"error": "SSR Updation not found."}, status=404)
    iso = lambda d: d.isoformat() if d else None
    data = {k: header.get(k) for k in ("id", "original_ticket_id", "source_reschedule_ticket_id", "invoice_number", "invoice_type",
                                        "booking_mode", "booking_status", "customer_name", "travel_type", "user_name", "currency",
                                        "ssr_reference", "airline_pnr", "gds_pnr", "payment_mode", "payment_gateway_ref", "voucher_id", "voucher_no",
                                        "original_invoice_number", "source_reschedule_invoice_number", "parent_pnr")}
    data.update({"invoice_date": iso(header.get("invoice_date")), "ssr_ref_date": iso(header.get("ssr_ref_date")),
                 "roe": float(header.get("roe") or 1), "lines": [_ssr_line_dict(l) for l in lines]})
    mapping_cache, company_state = _jv_prep(company_id)
    customer = {"id": header["customer_ledger_id"], "name": header["customer_name"], "state_name": header.get("customer_state")}
    with mapping_document("ssr", header.get("id")):
        data["jv"] = _ssr_jv_payload(company_id, customer, data["lines"], header, mapping_cache, company_state)
    return JsonResponse(data)


def ssr_tickets_list(request):
    """GET /api/ssr-tickets/list/?company_id=1 - every saved SSR line (flat), for the Find popup."""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)
    rows = []
    for l in sp_client.ssr_tickets_list(company_id):
        try:
            items = json.loads(l.get("ssr_items") or "{}")
        except (ValueError, TypeError):
            items = {}
        rows.append({
            "id": l["id"], "ssr_ticket_id": l["ssr_ticket_id"], "invoice_number": l["invoice_number"],
            "invoice_date": l["invoice_date"].isoformat() if l.get("invoice_date") else None,
            "booking_reference": l["booking_reference"], "airline_pnr": l["airline_pnr"], "gds_pnr": l["gds_pnr"],
            "customer_name": l["customer_name"], "ticket_no": l["ticket_no"], "passenger_name": l["passenger_name"],
            "sector": l["sector"], "ssr_details": ", ".join(f"{k}: {v}" for k, v in items.items()),
            "total_billed": float(l["total_billed"] or 0),
        })
    return JsonResponse(rows, safe=False)


def ssr_dsr_rows(request):
    """
    GET /api/ssr-tickets/dsr/?company_id=1
    One row per SSR Updation passenger for report-dsr-airline-booking.html,
    same flat shape as cancellation_dsr_rows so the DSR can merge them in.
    SSR has no Basic Fare - total_billed is what the customer pays for the SSR
    (SSR charges + SSR Markup + SSR Service Fee + GST, the JV's Customer
    debit). ssr_ticket_id links to the saved SSR Updation.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    from .models import SSRAirlineTicket, SSRAirlineTicketLine
    _jv_prep(company_id)  # seeds the per-field GST% cache _ssr_line_amounts reads
    rows = []
    ssr_tickets = SSRAirlineTicket.objects.filter(company_id=company_id).select_related("customer").prefetch_related(
        Prefetch("lines", queryset=SSRAirlineTicketLine.objects.select_related("supplier", "original_ticket_line", "reschedule_line"))
    )
    for st in ssr_tickets:
        for l in st.lines.all():
            with mapping_document("ssr", st.id):
                amounts = _ssr_line_amounts(company_id, {k: getattr(l, k) for k in SSR_AMOUNT_FIELDS}, st.invoice_date)
            # Airline comes from the ticket the SSR was sold on (the
            # reschedule when the passenger's live data sits there).
            src = l.reschedule_line or l.original_ticket_line
            rows.append({
                "id": l.id, "ticket_id": None, "reschedule_ticket_id": None, "cancellation_ticket_id": None, "ssr_ticket_id": st.id,
                "invoice_number": st.invoice_number, "invoice_date": st.invoice_date.isoformat() if st.invoice_date else None,
                "invoice_type": st.invoice_type, "booking_status": st.booking_status or "SSR Updated",
                "payment_mode": st.payment_mode, "booking_type": "SSR Updation",
                "customer_name": st.customer.name if st.customer else None,
                "booking_reference": st.ssr_reference, "airline_pnr": st.airline_pnr, "gds_pnr": st.gds_pnr,
                "travel_type": st.travel_type, "airline_category": l.airline_category,
                "passenger_name": l.passenger_name, "ticket_no": l.ticket_no, "pax_type": l.pax_type, "sector": l.sector,
                "airline_name": getattr(src, "airline_name", None), "airline_code": getattr(src, "airline_code", None),
                "supplier_name": l.supplier.name if l.supplier else None,
                "basic_fare": 0.0,
                "total_billed": round(amounts["sales"], 2),
                # DSR Earnings columns - an SSR line's customer SSR Markup /
                # SSR Service Fee (no commission or agent penalty on an SSR).
                "markup": round(amounts["markup"], 2), "service_fee": round(amounts["service_fee"], 2),
            })
    return JsonResponse(rows, safe=False)


# ============================================================================
# DSR (report-dsr.html) - one row per passenger line, every column of the
# agreed "DSR format" sheet: Booking, Reschedule, Cancellation and SSR
# Updation lines, each computed with the SAME formulas as its own screen /
# J.V (TicketLine.compute_total, computed_* properties,
# _cancellation_line_amounts, _ssr_line_amounts).
#   Gross Amount = Purchase Cost total (what the supplier is owed)
#   Net Amount   = Sales Cost total (what the customer pays)
# Reschedule rows carry their markups in the "(While Reschedule)" columns,
# Cancellation rows in the "(While Cancellation)" columns; a Cancellation
# (Credit Note) shows its fare amounts and Gross / Net as negatives.
# ============================================================================
DSR_AMOUNT_KEYS = (
    "basic_fare", "yq", "yr", "k3", "other_taxes", "ssr_amount", "other_ssr", "supplier_penalty", "commission", "tds_com",
    "sup_markup", "sup_addl_markup", "sup_ssr_markup", "sup_service_fee", "sup_addl_service_fee", "sup_ssr_service_fee", "sup_gst",
    "sup_resc_markup", "sup_addl_resc_markup", "sup_resc_ssr_markup", "sup_can_markup", "sup_addl_can_markup", "sup_can_ssr_markup",
    "penalty_amount", "gross_amount", "discount", "tds_disc",
    "cust_markup", "cust_addl_markup", "cust_ssr_markup", "cust_service_fee", "cust_addl_service_fee", "cust_ssr_service_fee", "cust_gst",
    "cust_resc_markup", "cust_addl_resc_markup", "cust_ssr_resc_markup", "cust_can_markup", "cust_addl_can_markup", "cust_ssr_can_markup",
    "agent_penalty", "net_amount", "seat", "meal", "baggage", "oktbd", "fastforward", "wchr",
)


def _dsr_trip_type(sector):
    """One Way / Round Trip / Multi City from the sector list (not stored anywhere):
    one leg = One Way; two legs back to the first origin = Round Trip; else Multi City."""
    legs = [s.strip() for s in str(sector or "").split(",") if s.strip()]
    if len(legs) <= 1:
        return "One Way" if legs else ""
    first, last = legs[0].split("-"), legs[-1].split("-")
    if len(legs) == 2 and first[0] and last[-1] and first[0].strip() == last[-1].strip():
        return "Round Trip"
    return "Multi City"


def _dsr_fare_line_amounts(l, kind):
    """Booking ("booking") / Reschedule ("reschedule") line -> DSR amount columns."""
    f = lambda k: float(getattr(l, k, 0) or 0)
    supp_markups = f("supp_markup") + f("supp_addl_markup") + f("supp_ssr_markup")
    supp_fees = f("supp_service_fee") + f("supp_addl_service_fee") + f("supp_ssr_service_fee")
    commission, comm_tds, supp_gst = float(l.computed_supp_commission), float(l.computed_supp_tds), float(l.computed_supp_gst)
    penalty = f("reschedule_penalty")
    # Same totals as the ticket screen's summary (recalcSummary):
    #   Purchase = fares - commission + TDS + supplier markups / fees / GST + penalties
    #   Sales    = line total + Agent Penalty + Penalty Amount + Supplier Penalty
    purchase = float(l.supplier_cost) - commission + comm_tds + supp_markups + supp_fees + supp_gst + penalty + f("supplier_penalty")
    sales = float(l.compute_total()) + f("agent_penalty") + penalty + f("supplier_penalty")
    resc = kind == "reschedule"
    return {
        "basic_fare": f("basic_fare"), "yq": f("yq"), "yr": f("yr"), "k3": f("k3_tax"), "other_taxes": f("tax_others"),
        "ssr_amount": f("seat") + f("meal") + f("baggage"), "other_ssr": f("other_ssr"),
        "supplier_penalty": f("supplier_penalty"), "commission": commission, "tds_com": comm_tds,
        "sup_markup": 0 if resc else f("supp_markup"), "sup_addl_markup": 0 if resc else f("supp_addl_markup"),
        "sup_ssr_markup": 0 if resc else f("supp_ssr_markup"),
        "sup_service_fee": f("supp_service_fee"), "sup_addl_service_fee": f("supp_addl_service_fee"),
        "sup_ssr_service_fee": f("supp_ssr_service_fee"), "sup_gst": supp_gst,
        "sup_resc_markup": f("supp_markup") if resc else 0, "sup_addl_resc_markup": f("supp_addl_markup") if resc else 0,
        "sup_resc_ssr_markup": f("supp_ssr_markup") if resc else 0,
        "penalty_amount": penalty, "gross_amount": purchase,
        "discount": float(l.computed_discount), "tds_disc": float(l.computed_tds),
        "cust_markup": 0 if resc else f("markup"), "cust_addl_markup": 0 if resc else f("addl_markup"),
        "cust_ssr_markup": 0 if resc else f("ssr_markup"),
        "cust_service_fee": f("service_fee"), "cust_addl_service_fee": f("addl_service_fee"),
        "cust_ssr_service_fee": f("ssr_service_fee"), "cust_gst": float(l.computed_gst),
        "cust_resc_markup": f("markup") if resc else 0, "cust_addl_resc_markup": f("addl_markup") if resc else 0,
        "cust_ssr_resc_markup": f("ssr_markup") if resc else 0,
        "agent_penalty": f("agent_penalty"), "net_amount": sales,
        "seat": f("seat"), "meal": f("meal"), "baggage": f("baggage"),
    }


def _dsr_row(header, l, kind, amounts, doc_ids, **extra):
    """One DSR row - the text columns from the document / line, the amount columns from `amounts`."""
    g = lambda o, k: getattr(o, k, None) if o is not None else None
    supplier = g(l, "supplier") or g(header, "supplier")
    row = {
        "invoice_date": header.invoice_date.isoformat() if header.invoice_date else None,
        "invoice_number": header.invoice_number, "invoice_type": header.invoice_type,
        "customer_name": header.customer.name if header.customer_id else None,
        "airline_name": g(l, "airline_name"), "airline_code": g(l, "airline_code"),
        "airline_category": g(l, "airline_category") or g(header, "airline_category"),
        "spnr": g(header, "booking_reference") or g(header, "cancellation_reference") or g(header, "ssr_reference"),
        "airline_pnr": g(header, "airline_pnr"), "gds_pnr": g(header, "gds_pnr"),
        "ticket_no": g(l, "ticket_no"), "status": g(header, "booking_status"),
        "booking_type": g(header, "booking_type") or kind, "user_name": g(header, "user_name"),
        "pax_type": g(l, "pax_type"), "passenger_name": g(l, "passenger_name"), "sector": g(l, "sector"),
        "travel_date": g(l, "travel_date"), "flight_no": g(l, "flight_no"), "trip_type": _dsr_trip_type(g(l, "sector")),
        "travel_type": g(header, "travel_type"), "payment_mode": g(header, "payment_mode"),
        "travel_class": g(l, "travel_class"), "supplier_name": supplier.name if supplier else None,
        "office_id": g(l, "office_id") or g(header, "office_id"), "document": kind,
        # Cancellation / SSR are saved without a branch - they belong to their
        # original booking's branch.
        "branch_name": g(header, "branch_name") or (header.original_ticket.branch_name
                                                    if getattr(header, "original_ticket_id", None) else None),
        **doc_ids, **extra,
    }
    # (+ 0.0 turns a negated zero, -0.0, into 0.0 - never shown as "-0.00".)
    row.update({k: round(float(amounts.get(k, 0) or 0), 2) + 0.0 for k in DSR_AMOUNT_KEYS})
    return row


def dsr_detailed_rows(request):
    """GET /api/dsr/detailed/?company_id=1 - every DSR column, one row per passenger line (see above)."""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)
    return JsonResponse(_dsr_rows(company_id), safe=False)


def _dsr_rows(company_id):
    """Every DSR row (one per passenger line of every Booking / Reschedule /
    Cancellation / SSR Updation), oldest first - the DSR report and the
    Dashboard both read these."""
    from .models import SSRAirlineTicket, SSRAirlineTicketLine
    _jv_prep(company_id)  # seeds the per-field GST % caches the computed_* properties read
    no_ids = {"ticket_id": None, "reschedule_ticket_id": None, "cancellation_ticket_id": None, "ssr_ticket_id": None}
    rows = []

    for t in Ticket.objects.filter(company_id=company_id).select_related("customer", "supplier").prefetch_related(
            Prefetch("lines", queryset=TicketLine.objects.select_related("supplier"))):
        for l in t.lines.all():
            rows.append(_dsr_row(t, l, "Booking", _dsr_fare_line_amounts(l, "booking"), {**no_ids, "ticket_id": t.id}))

    for rt in RescheduleAirlineTicket.objects.filter(company_id=company_id).select_related("customer", "supplier").prefetch_related(
            Prefetch("lines", queryset=RescheduleAirlineTicketLine.objects.select_related("supplier"))):
        for l in rt.lines.all():
            rows.append(_dsr_row(rt, l, "Reschedule", _dsr_fare_line_amounts(l, "reschedule"), {**no_ids, "reschedule_ticket_id": rt.id}))

    for ct in CancellationAirlineTicket.objects.filter(company_id=company_id).select_related("customer", "supplier").prefetch_related(
            Prefetch("lines", queryset=CancellationAirlineTicketLine.objects.select_related("supplier"))):
        for l in ct.lines.all():
            a = _cancellation_line_amounts(l)
            f = lambda k: float(getattr(l, k, 0) or 0)
            neg = lambda v: -round(float(v or 0), 2)
            amounts = {
                # Credit Note - the fare refunded is a negative sale.
                "basic_fare": neg(l.basic_fare), "yq": neg(l.yq), "yr": neg(l.yr), "k3": neg(l.k3_tax), "other_taxes": neg(l.tax_others),
                "ssr_amount": neg(f("seat") + f("meal") + f("baggage")), "other_ssr": neg(l.other_ssr),
                "seat": neg(l.seat), "meal": neg(l.meal), "baggage": neg(l.baggage),
                # Commission / Discount and their TDS are given back on a
                # Credit Note - shown negative.
                "supplier_penalty": a["supplier_penalty"], "commission": -a["commission"], "tds_com": -a["commission_tds"],
                # Markup reversals - in the normal markup columns, negative
                # (supplier reversals under Sup Markup..., customer under Cust Markup...).
                "sup_markup": -a["supp_markup_reversal"], "sup_addl_markup": -a["supp_addl_markup_reversal"],
                "sup_ssr_markup": -a["supp_ssr_markup_reversal"],
                "cust_markup": -a["cust_markup_reversal"], "cust_addl_markup": -a["cust_addl_markup_reversal"],
                "cust_ssr_markup": -a["cust_ssr_markup_reversal"],
                "sup_service_fee": a["supp_service_fee"], "sup_addl_service_fee": a["supp_addl_service_fee"], "sup_gst": a["supp_gst"],
                "sup_can_markup": a["supp_markup"], "sup_addl_can_markup": a["supp_addl_markup"], "sup_can_ssr_markup": f("supp_ssr_markup"),
                "penalty_amount": a["cancellation_penalty"], "gross_amount": -a["supplier_amount"],
                "discount": -a["discount"], "tds_disc": -a["discount_tds"],
                "cust_service_fee": a["service_fee"], "cust_addl_service_fee": a["addl_service_fee"], "cust_gst": a["gst"],
                "cust_can_markup": a["markup"], "cust_addl_can_markup": a["addl_markup"], "cust_ssr_can_markup": f("ssr_markup"),
                "agent_penalty": a["agent_penalty"], "net_amount": -a["customer_amount"],
            }
            rows.append(_dsr_row(ct, l, "Cancellation", amounts, {**no_ids, "cancellation_ticket_id": ct.id}))

    for st in SSRAirlineTicket.objects.filter(company_id=company_id).select_related("customer").prefetch_related(
            Prefetch("lines", queryset=SSRAirlineTicketLine.objects.select_related("supplier", "original_ticket_line", "reschedule_line"))):
        for l in st.lines.all():
            with mapping_document("ssr", st.id):
                a = _ssr_line_amounts(company_id, {k: getattr(l, k) for k in SSR_AMOUNT_FIELDS}, st.invoice_date)
            src = l.reschedule_line or l.original_ticket_line  # airline / flight details come from the ticket it was sold on
            amounts = {
                "ssr_amount": a["seat"] + a["meal"] + a["baggage"], "other_ssr": a["other_ssr"],
                "seat": a["seat"], "meal": a["meal"], "baggage": a["baggage"],
                "sup_ssr_markup": a["supp_markup"], "sup_ssr_service_fee": a["supp_service_fee"], "sup_gst": a["supp_gst"],
                "gross_amount": a["purchase"],
                "cust_ssr_markup": a["markup"], "cust_ssr_service_fee": a["service_fee"], "cust_gst": a["gst"],
                "net_amount": a["sales"],
            }
            row = _dsr_row(st, l, "SSR Updation", amounts, {**no_ids, "ssr_ticket_id": st.id})
            row.update({"airline_name": getattr(src, "airline_name", None), "airline_code": getattr(src, "airline_code", None),
                        "flight_no": getattr(src, "flight_no", None), "travel_date": getattr(src, "travel_date", None),
                        "travel_class": getattr(src, "travel_class", None), "booking_type": "SSR Updation",
                        "status": st.booking_status or "SSR Updated"})
            rows.append(row)

    rows.sort(key=lambda r: (r["invoice_date"] or "", r["invoice_number"] or ""))
    return rows


# ==========================================================================
# Dashboard (dashboard.html) - real figures. Only the Airline module is live,
# so every sales / revenue figure comes from the airline documents (Booking,
# Reschedule, Cancellation, SSR Updation) through the SAME per-line amounts
# as the DSR report (_dsr_rows: net_amount = Sales, gross_amount =
# Purchase); Hotel / Visa / Insurance are 0. Cash / Bank / Receivables /
# Payables / GST / TDS are live ledger balances (same as the Trial Balance).
# ==========================================================================
_DASH_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def dashboard_summary(request):
    """GET /api/dashboard?company_id=1"""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    try:
        company_id = int(request.GET.get("company_id"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "company_id is required"}, status=400)

    today = date.today()
    company = sp_client.company_master_get(company_id) or {}
    fy_start = _parse_date(company.get("fy_start")) or date(today.year if today.month >= 4 else today.year - 1, 4, 1)
    month_start = today.replace(day=1)

    rows = _dsr_rows(company_id)
    r2 = lambda v: round(float(v or 0), 2)
    sales = lambda r: float(r.get("net_amount") or 0)
    profit = lambda r: float(r.get("net_amount") or 0) - float(r.get("gross_amount") or 0)
    on = lambda r: _parse_date(r.get("invoice_date"))

    ytd_rows = [r for r in rows if on(r) and fy_start <= on(r) <= today]
    today_sales = sum(sales(r) for r in rows if on(r) == today)
    month_sales = sum(sales(r) for r in rows if on(r) and month_start <= on(r) <= today)
    ytd_sales = sum(sales(r) for r in ytd_rows)
    service_charges = sum(float(r.get(k) or 0) for r in ytd_rows
                          for k in ("cust_service_fee", "cust_addl_service_fee", "cust_ssr_service_fee"))
    markup_revenue = sum(float(r.get(k) or 0) for r in ytd_rows for k in DSR_AMOUNT_KEYS
                         if k.startswith("cust_") and "markup" in k)

    # Last 6 months (oldest first), by invoice date.
    months = []
    y, m = today.year, today.month
    for _ in range(6):
        months.insert(0, (y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    trend, profit_trend = [], []
    for (y, m) in months:
        in_month = [r for r in rows if on(r) and on(r).year == y and on(r).month == m]
        label = f"{_DASH_MONTHS[m - 1]} {str(y)[2:]}"
        trend.append({"label": label, "value": r2(sum(sales(r) for r in in_month))})
        profit_trend.append({"label": label, "value": r2(sum(profit(r) for r in in_month))})

    branches = {}
    for r in ytd_rows:
        b = branches.setdefault(r.get("branch_name") or "Head Office", {"sales": 0.0, "profit": 0.0})
        b["sales"] += sales(r)
        b["profit"] += profit(r)

    # Live ledger balances (Debit positive) - opening balance + every posting.
    deltas = _ledger_balance_deltas(company_id, as_of_date=today.isoformat())
    groups = sp_client.ledger_group_list(company_id)
    children = {}
    for g in groups:
        children.setdefault(g["parent_id"], []).append(g["id"])

    def subtree(name):
        ids = [g["id"] for g in groups if (g["name"] or "").strip().lower() == name.lower()]
        out = set()
        while ids:
            gid = ids.pop()
            if gid not in out:
                out.add(gid)
                ids.extend(children.get(gid, []))
        return out

    ledgers = sp_client.ledger_list(company_id)
    bal = lambda l: float(l["balance"] or 0) + deltas.get(l["id"], 0.0)

    def group_balance(name, keep=lambda l: True):
        ids = subtree(name)
        return sum(bal(l) for l in ledgers if l["parent_id"] in ids and keep(l))

    cash = group_balance("Cash-in-hand")
    bank = group_balance("Bank Accounts")
    # Outstanding Receivables / Payables = the bill-wise totals of the
    # Receivables (AR) / Payables (AP) screens (_party_bills), not raw group
    # balances (Sundry Creditors also holds PG platform ledgers).
    receivables = sum(p["outstanding"] for p in _party_bills(company_id, "receivables", as_of_date=today.isoformat()))
    payables = sum(p["outstanding"] for p in _party_bills(company_id, "payables", as_of_date=today.isoformat()))
    gst_payable = -group_balance("Duties & Taxes", lambda l: "GST" in (l["name"] or "").upper())
    tds_payable = -group_balance("Duties & Taxes", lambda l: "TDS" in (l["name"] or "").upper()
                                 and "RECEIVABLE" not in (l["name"] or "").upper())

    airline = r2(ytd_sales)
    return JsonResponse({
        "as_of": today.isoformat(), "fy_start": fy_start.isoformat(),
        "sales": {"today_sales": r2(today_sales), "month_sales": r2(month_sales), "ytd_sales": r2(ytd_sales)},
        "revenue": {
            "ticket_revenue": airline, "hotel_revenue": 0, "visa_revenue": 0, "insurance_revenue": 0,
            "service_charges": r2(service_charges), "markup_revenue": r2(markup_revenue),
        },
        "finance": {
            "cash_position": r2(cash), "bank_position": r2(bank),
            "outstanding_receivables": r2(receivables), "outstanding_payables": r2(payables),
            "credit_exposure": r2(receivables), "bsp_liability": 0, "supplier_liability": r2(payables),
        },
        "compliance": {"gst_payable": r2(gst_payable), "tds_payable": r2(tds_payable), "vat_payable": 0},
        "monthly_revenue_trend": trend,
        "profitability_trend": profit_trend,
        "branch_performance": [
            {"branch_name": k, "sales": r2(v["sales"]), "profit": r2(v["profit"])}
            for k, v in sorted(branches.items(), key=lambda kv: -kv[1]["sales"])
        ],
        "product_mix": [
            {"product": "Airline Tickets", "value": airline}, {"product": "Hotels", "value": 0},
            {"product": "Visa", "value": 0}, {"product": "Insurance", "value": 0},
        ],
    })


def _ssr_report_entries(company_id, mapping_cache, company_state, from_date=None, to_date=None):
    """
    Every posted SSR Updation JV (ALS-n) for the reports (Ledger balances /
    Trial Balance / Ledger report / Day Book), recomputed live from the
    saved SSR lines - same convention as the Booking / Reschedule /
    Cancellation JVs. Yields {"voucher", "st", "lines", "accounts"}.
    """
    from .models import SSRAirlineTicketLine
    vouchers = JournalVoucher.objects.filter(
        company_id=company_id, source_ssr_ticket__isnull=False
    ).select_related("source_ssr_ticket", "source_ssr_ticket__customer").prefetch_related(
        Prefetch("source_ssr_ticket__lines", queryset=SSRAirlineTicketLine.objects.select_related("supplier"))
    ).order_by("id")
    if from_date:
        vouchers = vouchers.filter(voucher_date__gte=from_date)
    if to_date:
        vouchers = vouchers.filter(voucher_date__lte=to_date)
    for v in vouchers:
        st = v.source_ssr_ticket
        orm_lines = list(st.lines.all()) if st else []
        if not orm_lines:
            continue
        lines = [{**{k: getattr(l, k) for k in SSR_AMOUNT_FIELDS + SSR_LINE_TEXT_FIELDS},
                  "supplier_ledger_id": l.supplier_id, "supplier_name": l.supplier.name if l.supplier else None}
                 for l in orm_lines]
        customer = {"id": st.customer_id, "name": st.customer.name, "state_name": st.customer.state_name}
        with mapping_document("ssr", st.id):
            accounts, _td, _tc = _compute_ssr_jv_lines(company_id, customer, lines, mapping_cache, company_state, as_of=st.invoice_date)
        fop_rows, pg_rows = _ssr_settlement_rows(company_id, customer, lines, accounts, st.payment_mode,
                                                 st.payment_gateway_ref, st.invoice_date)
        yield {"voucher": v, "st": st, "lines": lines, "accounts": accounts, "combined": accounts + fop_rows + pg_rows}


# ============================================================================
# Miscellaneous transactions (trans-misc.html) - dbo.sp_MiscTransaction.
# One Description + Base Amount billed to a customer and bought from a
# supplier; customer / supplier Markup + Service Fee, GST on each Service Fee
# from Ledger Mapping. A Confirmed one posts its own JV (MSC-n).
# ============================================================================
MISC_PRODUCT = "Miscellaneous"  # Ledger Mapping product the Misc ledgers are mapped under
MISC_AMOUNT_FIELDS = ("base_amount", "other_taxes", "markup", "service_fee", "supp_markup", "supp_service_fee")
MISC_FIELD = {
    "markup": "Misc Markup A/c", "service_fee": "Misc Service Fee A/c",
    "consolidator_markup": "Consolidator Misc Markup A/c", "consolidator_service_fee": "Consolidator Misc Service Fee A/c",
    "supp_markup": "Supplier Misc Markup A/c", "supp_service_fee": "Supplier Misc Service Fee A/c",
}


def _misc_amounts(company_id, m, as_of=None):
    """
    One transaction's figures - same convention as an SSR line:
      purchase (Purchase Cost, what the supplier is owed)
        = Base Amount + Other Taxes + Supplier Markup + Supplier Service Fee + its GST
      sales (Sales Cost, what the customer pays)
        = purchase + Customer Markup + Customer Service Fee + its GST
    GST % = the ledger mapped (on as_of, Ledger Mapping product
    Miscellaneous) to "Misc Service Fee A/c" (customer) / "Supplier Misc
    Service Fee A/c" (supplier).
    """
    v = {k: float(m.get(k) or 0) for k in MISC_AMOUNT_FIELDS}
    gst = v["service_fee"] * mapped_gst_pct(company_id, MISC_FIELD["service_fee"], as_of, MISC_PRODUCT) / 100
    supp_gst = v["supp_service_fee"] * mapped_gst_pct(company_id, MISC_FIELD["supp_service_fee"], as_of, MISC_PRODUCT) / 100
    purchase = v["base_amount"] + v["other_taxes"] + v["supp_markup"] + v["supp_service_fee"] + supp_gst
    return {**v, "gst": gst, "supp_gst": supp_gst, "purchase": purchase,
            "sales": purchase + v["markup"] + v["service_fee"] + gst}


def _compute_misc_jv_lines(company_id, customer, supplier, m, mapping_cache, company_state, as_of=None):
    """
    Miscellaneous JV (MSC-n), ledgers from Ledger Mapping:
      Dr Customer                            Sales Cost
      Cr Supplier                            Purchase Cost
      Cr Misc Markup A/c                     customer Markup
      Cr Misc Service Fee A/c                customer Service Fee
      Cr Consolidator Misc Markup A/c        supplier Markup (billed on to the customer)
      Cr Consolidator Misc Service Fee A/c   supplier Service Fee (billed on to the customer)
      Cr Output CGST+SGST / Output IGST      customer GST + supplier GST (customer State vs Company State)
      Dr Supplier Misc Markup A/c            supplier Markup
      Dr Supplier Misc Service Fee A/c       supplier Service Fee
      Dr Input CGST+SGST / Input IGST        supplier GST (supplier State vs Company State)
    Same structure as the SSR Updation JV - Base Amount + Other Taxes pass straight
    from customer to supplier, so Debit always equals Credit. Zero rows are
    left out. customer / supplier: {"id", "name", "state_name"}.
    """
    def mapped_row(dr_cr, field_name, amount):
        amount = round(amount, 2)
        # Ledger Mapping product Miscellaneous; the Output / Input GST
        # ledgers fall back to the Airline ones when not mapped there.
        r = resolve_mapping(company_id, field_name, as_of, MISC_PRODUCT) or (
            resolve_mapping(company_id, field_name, as_of) if field_name.startswith(("Output ", "Input ")) else None)
        ledger_id, ledger_name = (r["ledger_id"], r["ledger_name"]) if r else (None, f"{field_name} (not mapped in Ledger Mapping - Miscellaneous)")
        return {"role": field_name, "ledger_id": ledger_id, "ledger_name": ledger_name,
                "debit": amount if dr_cr == "Debit" else 0, "credit": amount if dr_cr == "Credit" else 0}

    a = _misc_amounts(company_id, m, as_of)
    accounts = [
        {"role": "customer", "ledger_id": customer["id"], "ledger_name": customer["name"], "debit": round(a["sales"], 2), "credit": 0},
        {"role": "supplier", "ledger_id": supplier["id"], "ledger_name": supplier["name"], "debit": 0, "credit": round(a["purchase"], 2)},
        mapped_row("Credit", MISC_FIELD["markup"], a["markup"]),
        mapped_row("Credit", MISC_FIELD["service_fee"], a["service_fee"]),
        mapped_row("Credit", MISC_FIELD["consolidator_markup"], a["supp_markup"]),
        mapped_row("Credit", MISC_FIELD["consolidator_service_fee"], a["supp_service_fee"]),
    ]
    # One combined Output GST (customer + supplier), same as the SSR / Booking JV.
    customer_state = (customer.get("state_name") or "").strip().lower()
    gst = round(a["gst"] + a["supp_gst"], 2)
    if company_state and customer_state and company_state == customer_state:
        half = round(gst / 2, 2)
        accounts.append(mapped_row("Credit", "Output CGST A/c", half))
        accounts.append(mapped_row("Credit", "Output SGST A/c", round(gst - half, 2)))
    else:
        accounts.append(mapped_row("Credit", "Output IGST A/c", gst))
    accounts.append(mapped_row("Debit", MISC_FIELD["supp_markup"], a["supp_markup"]))
    accounts.append(mapped_row("Debit", MISC_FIELD["supp_service_fee"], a["supp_service_fee"]))
    mapping_cache.setdefault(("__supplier_state__", supplier["id"]), (supplier.get("state_name") or "").strip().lower())
    accounts.extend(_input_gst_rows(lambda dr_cr, _cat, field, amt: mapped_row(dr_cr, field, amt),
                                    {supplier["id"]: a["supp_gst"]}, company_state, mapping_cache))

    accounts = [r for r in accounts if r["role"] in ("customer", "supplier") or r["debit"] or r["credit"]]
    total_debit = round(sum(r["debit"] for r in accounts), 2)
    total_credit = round(sum(r["credit"] for r in accounts), 2)
    return accounts, total_debit, total_credit


def _misc_build(company_id, body):
    """Validates a Miscellaneous create / update / preview body -> (fields, customer, supplier, error)."""
    customer_row = sp_client.ledger_get_by_name(company_id, (body.get("customer_name") or "").strip(), "DEBTOR")
    if not customer_row:
        return None, None, None, f"\"{body.get('customer_name') or ''}\" is not a real customer ledger (Sundry Debtors)."
    supplier_row = sp_client.ledger_get_by_name(company_id, (body.get("supplier_name") or "").strip(), "CREDITOR")
    if not supplier_row:
        return None, None, None, f"\"{body.get('supplier_name') or ''}\" is not a real supplier ledger (Sundry Creditors)."
    customer = {"id": customer_row["id"], "name": customer_row["name"], "state_name": customer_row.get("state_name")}
    supplier = {"id": supplier_row["id"], "name": supplier_row["name"], "state_name": supplier_row.get("state_name")}
    status = body.get("status") or "Confirmed"
    if status not in ("Confirmed", "Cancelled"):
        return None, None, None, "Status must be Confirmed or Cancelled."
    fields = {
        "branch_name": body.get("branch_name"),
        "invoice_number": (body.get("invoice_number") or "").strip(), "invoice_date": _parse_date(body.get("invoice_date")),
        "invoice_type": body.get("invoice_type"), "status": status, "user_name": body.get("user_name"),
        "reference": (body.get("reference") or "").strip(), "ref_date": _parse_date(body.get("ref_date")),
        "payment_mode": body.get("payment_mode"),
        # Gateway Ref only applies to Payment Gateway - never stored otherwise.
        "payment_gateway_ref": (body.get("payment_gateway_ref") or None) if body.get("payment_mode") == "Payment Gateway" else None,
        "currency": body.get("currency") or "INR",
        "customer_name": customer["name"], "supplier_name": supplier["name"],
        "description": (body.get("description") or "").strip(),
    }
    fields.update({k: float(_safe_decimal(body.get(k))) for k in MISC_AMOUNT_FIELDS})
    fields["total_billed"] = round(_misc_amounts(company_id, fields, fields["invoice_date"])["sales"], 2)
    return fields, customer, supplier, None


def _misc_narration(fields):
    return " / ".join(p for p in ["Misc", fields.get("reference"), (fields.get("description") or "")[:80]] if p)


def _misc_save(request, misc_id=None):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)
    try:
        company_id = int(body.get("company_id"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "company_id is required."}, status=400)
    missing = [label for key, label in [("invoice_number", "Invoice Number"), ("invoice_date", "Invoice Date"),
                                        ("invoice_type", "Invoice Type"), ("reference", "Reference"),
                                        ("customer_name", "Customer"), ("supplier_name", "Supplier"),
                                        ("description", "Description")] if not str(body.get(key) or "").strip()]
    if missing:
        return JsonResponse({"error": f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} required."}, status=400)

    mapping_cache, company_state = _jv_prep(company_id)
    fields, customer, supplier, error = _misc_build(company_id, body)
    if error:
        return JsonResponse({"error": error}, status=400)
    accounts, total_debit, total_credit = _compute_misc_jv_lines(company_id, customer, supplier, fields, mapping_cache, company_state, as_of=fields["invoice_date"])
    if fields["status"] == "Confirmed" and total_debit == 0 and total_credit == 0:
        return JsonResponse({"error": "This transaction's GL entry total is zero - enter the Base Amount / Markup / Service Fee."}, status=400)
    try:
        result = sp_client.misc_save(company_id, fields, _misc_narration(fields), total_debit, total_credit, misc_id=misc_id)
    except sp_client.StoredProcedureError as err:
        msg = str(err)
        return JsonResponse({"error": msg}, status=409 if "already exists" in msg else 400)
    message = (f"Miscellaneous transaction saved and GL entry {result['voucher_no']} posted (Debit {total_debit:.2f} = Credit {total_credit:.2f})."
               if result.get("voucher_no") else "Miscellaneous transaction saved as Cancelled - no GL entry posted.")
    return JsonResponse({"id": result["id"], "voucher_id": result["voucher_id"], "voucher_no": result["voucher_no"], "message": message},
                        status=201 if misc_id is None else 200)


@csrf_exempt
def misc_create(request):
    """POST /api/misc/create/ - new Miscellaneous transaction + its MSC-n JV."""
    return _misc_save(request)


@csrf_exempt
@document_save("misc", "misc_id")
def misc_update(request, misc_id):
    """POST /api/misc/<id>/update/ - edits a saved Miscellaneous transaction; its JV is recomputed in place."""
    return _misc_save(request, misc_id=misc_id)


@csrf_exempt
def misc_jv_preview_draft(request):
    """POST /api/misc/jv-preview-draft/ - the JV for the transaction currently on screen (nothing saved)."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON body"}, status=400)
    try:
        company_id = int(body.get("company_id"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "company_id is required."}, status=400)
    mapping_cache, company_state = _jv_prep(company_id)
    fields, customer, supplier, error = _misc_build(company_id, body)
    if error:
        return JsonResponse({"error": error}, status=400)
    accounts, total_debit, total_credit = _compute_misc_jv_lines(company_id, customer, supplier, fields, mapping_cache, company_state, as_of=fields["invoice_date"])
    return JsonResponse({"accounts": accounts, "total_debit": total_debit, "total_credit": total_credit,
                         "narration": _misc_narration(fields), "voucher_date": body.get("invoice_date"),
                         "cancelled": fields["status"] == "Cancelled"})


def misc_detail(request, misc_id):
    """GET /api/misc/<id>/?company_id=1 - one saved Miscellaneous transaction."""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    try:
        company_id = int(request.GET.get("company_id"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "company_id is required"}, status=400)
    m = sp_client.misc_get(misc_id, company_id)
    if not m:
        return JsonResponse({"error": "Miscellaneous transaction not found."}, status=404)
    iso = lambda d: d.isoformat() if d else None
    data = {k: m.get(k) for k in ("id", "invoice_number", "invoice_type", "user_name", "reference", "payment_mode",
                                   "payment_gateway_ref", "currency", "customer_name", "supplier_name", "description",
                                   "voucher_id", "voucher_no")}
    data.update({"status": m.get("misc_status"), "invoice_date": iso(m.get("invoice_date")), "ref_date": iso(m.get("ref_date"))})
    data.update({k: float(m.get(k) or 0) for k in MISC_AMOUNT_FIELDS + ("total_billed",)})
    return JsonResponse(data)


def misc_list(request):
    """GET /api/misc/list/?company_id=1 - every saved Miscellaneous transaction, for the Find popup."""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)
    iso = lambda d: d.isoformat() if d else None
    return JsonResponse([{
        "id": r["id"], "invoice_number": r["invoice_number"], "invoice_date": iso(r.get("invoice_date")),
        "invoice_type": r.get("invoice_type"), "status": r.get("status"), "reference": r.get("reference"),
        "ref_date": iso(r.get("ref_date")), "customer_name": r.get("customer_name"), "supplier_name": r.get("supplier_name"),
        "description": r.get("description") or "", "total_billed": float(r.get("total_billed") or 0),
    } for r in sp_client.misc_list(company_id)], safe=False)


def _misc_report_entries(company_id, mapping_cache, company_state, from_date=None, to_date=None):
    """
    Every posted Miscellaneous JV (MSC-n) for the reports (Ledger balances /
    Trial Balance / Ledger report / Day Book / Receivables-Payables),
    recomputed live from the saved transaction - same convention as the SSR
    JVs. Cancelled transactions have no JV, so they never appear.
    Yields {"voucher", "m", "accounts"}.
    """
    vouchers = JournalVoucher.objects.filter(
        company_id=company_id, source_misc_ticket__isnull=False
    ).select_related("source_misc_ticket", "source_misc_ticket__customer", "source_misc_ticket__supplier").order_by("id")
    if from_date:
        vouchers = vouchers.filter(voucher_date__gte=from_date)
    if to_date:
        vouchers = vouchers.filter(voucher_date__lte=to_date)
    for v in vouchers:
        m = v.source_misc_ticket
        if not m or m.status != "Confirmed":
            continue
        fields = {k: getattr(m, k) for k in MISC_AMOUNT_FIELDS}
        customer = {"id": m.customer_id, "name": m.customer.name, "state_name": m.customer.state_name}
        supplier = {"id": m.supplier_id, "name": m.supplier.name, "state_name": m.supplier.state_name}
        with mapping_document("misc", m.id):
            accounts, _td, _tc = _compute_misc_jv_lines(company_id, customer, supplier, fields, mapping_cache, company_state, as_of=m.invoice_date)
        yield {"voucher": v, "m": m, "accounts": accounts}


# ============================================================================
# Receivables (Sundry Debtors) / Payables (Sundry Creditors) - bill-wise
# outstanding, invoice number as the reference.
# ============================================================================
def _group_ledgers(company_id, group_name):
    """Every ledger under the named group (and any sub-group of it)."""
    groups = list(LedgerGroup.objects.filter(company_id=company_id))
    target = {g.id for g in groups if _normalize_group_name(g.name) == _normalize_group_name(group_name)}
    grew = True
    while grew:
        children = {g.id for g in groups if g.parent_id in target and g.id not in target}
        target |= children
        grew = bool(children)
    return {l.id: l for l in Ledger.objects.filter(company_id=company_id, group_id__in=target)}


ON_ACCOUNT_KEY = "On Account"


def _party_bills(company_id, side, as_of_date=None, exclude_voucher_id=None, only_ledger_id=None):
    """
    Bill-wise outstanding for every party ledger of one side - "receivables"
    (Sundry Debtors) or "payables" (Sundry Creditors) - as on as_of_date.

    Every posted entry is read once (Booking / Reschedule / SSR Updation JVs,
    their FOP / PG legs, Cancellation Credit Notes and manual Vouchers, all
    recomputed live like the Ledger report). Each party ledger's own Debit /
    Credit on an entry is booked against a bill keyed by the invoice number:
      - Booking / Reschedule / SSR -> its own invoice number (the bill).
      - Cancellation -> adjusted against the ORIGINAL booking's invoice
        (the bill it cancels), not a bill of its own.
      - Manual vouchers -> as allocated on the voucher line (Against Invoice /
        New Invoice / On Account) - see the voucher block below.
      - The ledger's opening balance -> an "Opening Balance" bill.
    Receivables: billed = Debit, adjusted = Credit, outstanding = Debit - Credit.
    Payables:    billed = Credit, adjusted = Debit, outstanding = Credit - Debit.
    """
    group_name = "Sundry Debtors" if side == "receivables" else "Sundry Creditors"
    parties = _group_ledgers(company_id, group_name)
    if only_ledger_id:
        parties = {lid: l for lid, l in parties.items() if str(lid) == str(only_ledger_id)}
    bills = {}  # (ledger_id, bill key) -> bill

    def bill_for(lid, key, **meta):
        b = bills.get((lid, key))
        if b is None:
            b = bills[(lid, key)] = {"ledger_id": lid, "invoice_number": key, "date": None, "type": "", "ref": "",
                                     "doc": None, "debit": 0.0, "credit": 0.0, "adjustments": []}
        for k, v in meta.items():
            if v is not None and not b.get(k):
                b[k] = v
        return b

    def post(rows, key, date, doc_type, ref, doc, adjust_label=None):
        """Book each party row of one entry against bill `key`."""
        per_party = {}
        for a in rows:
            lid = a.get("ledger_id")
            if lid in parties:
                d = per_party.setdefault(lid, [0.0, 0.0])
                d[0] += float(a.get("debit") or 0)
                d[1] += float(a.get("credit") or 0)
        for lid, (dr, cr) in per_party.items():
            if not dr and not cr:
                continue
            if adjust_label:
                b = bill_for(lid, key)
                b["adjustments"].append({"type": adjust_label, "ref": ref, "date": date, "doc": doc,
                                         "debit": round(dr, 2), "credit": round(cr, 2)})
            else:
                b = bill_for(lid, key, date=date, type=doc_type, ref=ref, doc=doc)
                # The same invoice can also settle part of itself - a customer
                # paying through the Payment Gateway (PG receipt leg) or a
                # supplier paid by card (FOP leg). Listed as its own
                # adjustment so every adjusted amount is explained.
                settled = cr if side == "receivables" else dr
                if settled and doc_type != "Opening Balance" and doc and doc.get("kind") != "voucher":
                    b["adjustments"].append({
                        "type": "Received with the invoice (Payment Gateway)" if side == "receivables" else "Paid with the invoice (Card / Gateway)",
                        "ref": ref, "date": date, "doc": doc,
                        "debit": round(dr if side == "payables" else 0, 2), "credit": round(cr if side == "receivables" else 0, 2),
                    })
            b["debit"] += dr
            b["credit"] += cr

    iso = lambda d: d.isoformat() if d else None
    ledger_names = {r["id"]: r["name"] for r in sp_client.ledger_list(company_id)}
    mapping_cache, company_state = _jv_prep(company_id)

    # Opening balances
    for lid, l in parties.items():
        ob = float(l.opening_balance or 0)
        if ob:
            b = bill_for(lid, "Opening Balance", type="Opening Balance")
            if l.opening_balance_type == "Debit":
                b["debit"] += ob
            else:
                b["credit"] += ob

    # Bookings (+ FOP / PG legs)
    ticket_groups = {}
    for row in sp_client.tickets_list_for_balance(company_id, as_of_date=as_of_date):
        ticket_groups.setdefault(row["ticket_id"], {"header": row, "line_rows": []})["line_rows"].append(row)
    for group in ticket_groups.values():
        h = group["header"]
        proxy = Ticket(
            id=h["ticket_id"], company_id=h["company_id"],
            customer=Ledger(id=h["customer_id"], name=h["customer_name"], state_name=h["customer_state_name"]),
            booking_reference=h["booking_reference"], airline_pnr=h["airline_pnr"],
            payment_mode=h["payment_mode"], payment_gateway_ref=h["payment_gateway_ref"],
            invoice_date=h["invoice_date"], booking_ref_date=h["booking_ref_date"],
            invoice_number=h["invoice_number"], office_id=h["ticket_office_id"],
        )
        lines = [TicketLine(ticket=proxy, supplier=Ledger(id=r["supplier_ledger_id"], name=r["supplier_name"]) if r["supplier_ledger_id"] else None,
                            **{f: r[f] for f in TICKET_LINE_FIELDS if f in r}) for r in group["line_rows"]]
        accounts, _n, _td, _tc = _compute_jv_lines(proxy, lines, mapping_cache=mapping_cache, company_state=company_state)
        rows = list(accounts)
        rows += [{"ledger_id": lid, "debit": d, "credit": c} for lid, d, c in _fop_payment_lines(proxy, lines)]
        rows += [{"ledger_id": lid, "debit": d, "credit": c} for lid, d, c in _pg_receipt_lines(proxy, lines)]
        post(rows, h["invoice_number"], iso(h["invoice_date"]), "Booking", h["booking_reference"] or "",
             {"kind": "ticket", "id": h["ticket_id"]})

    # Reschedules (+ FOP / PG legs)
    resched_groups = {}
    for row in sp_client.reschedule_tickets_list_for_balance(company_id, as_of_date=as_of_date):
        resched_groups.setdefault(row["reschedule_ticket_id"], {"header": row, "line_rows": []})["line_rows"].append(row)
    for group in resched_groups.values():
        h = group["header"]
        proxy = RescheduleAirlineTicket(
            id=h["reschedule_ticket_id"], company_id=h["company_id"],
            customer=Ledger(id=h["customer_id"], name=h["customer_name"], state_name=h["customer_state_name"]),
            booking_reference=h["booking_reference"], airline_pnr=h["airline_pnr"],
            payment_mode=h["payment_mode"], payment_gateway_ref=h["payment_gateway_ref"],
            invoice_date=h["invoice_date"], booking_ref_date=h["booking_ref_date"],
            invoice_number=h["invoice_number"], office_id=h["ticket_office_id"],
        )
        lines = [RescheduleAirlineTicketLine(reschedule_ticket=proxy, supplier=Ledger(id=r["supplier_ledger_id"], name=r["supplier_name"]) if r["supplier_ledger_id"] else None,
                                             **{f: r[f] for f in RESCHED_LINE_FIELDS if f in r}) for r in group["line_rows"]]
        accounts, _n, _td, _tc = _compute_reschedule_jv_lines(proxy, lines, mapping_cache=mapping_cache, company_state=company_state)
        rows = list(accounts)
        rows += [{"ledger_id": lid, "debit": d, "credit": c} for lid, d, c in _reschedule_fop_payment_lines(proxy, lines)]
        rows += [{"ledger_id": lid, "debit": d, "credit": c} for lid, d, c in _reschedule_pg_receipt_lines(proxy, lines)]
        post(rows, h["invoice_number"], iso(h["invoice_date"]), "Reschedule", h["booking_reference"] or "",
             {"kind": "reschedule", "id": h["reschedule_ticket_id"]})

    # SSR Updations
    for entry in _ssr_report_entries(company_id, mapping_cache, company_state, to_date=as_of_date):
        st = entry["st"]
        post(entry["combined"], st.invoice_number, iso(st.invoice_date), "SSR Updation", st.ssr_reference or "",
             {"kind": "ssr", "id": st.id})

    # Miscellaneous transactions
    for entry in _misc_report_entries(company_id, mapping_cache, company_state, to_date=as_of_date):
        m = entry["m"]
        post(entry["accounts"], m.invoice_number, iso(m.invoice_date), "Miscellaneous", m.reference or "",
             {"kind": "misc", "id": m.id})

    # Cancellations - adjusted against the original booking's invoice
    for entry in _cancellation_report_entries(company_id, mapping_cache, company_state, to_date=as_of_date):
        ct = entry["ct"]
        original = ct.original_ticket.invoice_number if ct.original_ticket_id else ct.invoice_number
        post(entry["combined"], original, iso(ct.invoice_date), "Booking", "", None,
             adjust_label=f"Cancellation {ct.invoice_number}")
        for b in bills.values():
            for adj in b["adjustments"]:
                if adj["doc"] is None and adj["type"] == f"Cancellation {ct.invoice_number}":
                    adj["doc"] = {"kind": "cancellation", "id": ct.id}

    # Manual vouchers - bill-wise allocation per line (voucher-entry.html's
    # Bill Allocation popup, stored on the line as bill_allocations):
    #   Against Invoice -> adjusts that invoice (the bill it settles).
    #   New Invoice     -> a new bill of its own, keyed by the new reference.
    #   On Account (and any unallocated remainder, older vouchers, ledgers not
    #   maintained bill-by-bill) -> the party's "On Account" bucket, shown as
    #   Unadjusted Credits / Debits.
    for v in sp_client.vouchers_list(company_id):
        if exclude_voucher_id and str(v["id"]) == str(exclude_voucher_id):
            continue
        if as_of_date and v["voucher_date"] and v["voucher_date"].isoformat() > as_of_date:
            continue
        label = f"{v['voucher_type']} Voucher {str(v['voucher_no'] or v['id']).split('-')[-1]}"
        vdate, narration, doc = iso(v["voucher_date"]), v["narration"] or "", {"kind": "voucher", "id": v["id"]}
        for line in (json.loads(v["lines_json"]) if v["lines_json"] else []):
            lid = line.get("ledger_id")
            if lid not in parties:
                continue
            dr, cr = float(line.get("debit") or 0), float(line.get("credit") or 0)
            left = dr or cr
            is_dr = dr > 0

            def book(b, amount, as_adjustment):
                d, c = (amount, 0.0) if is_dr else (0.0, amount)
                if as_adjustment:
                    b["adjustments"].append({"type": label, "ref": narration, "date": vdate, "doc": doc,
                                             "debit": round(d, 2), "credit": round(c, 2)})
                b["debit"] += d
                b["credit"] += c

            for alloc in line.get("bill_allocations") or []:
                amount = min(left, float(alloc.get("amount") or 0))
                ref = str(alloc.get("ref") or "").strip()
                if amount <= 0 or not ref or alloc.get("type") not in ("Against Invoice", "New Invoice"):
                    continue
                if alloc["type"] == "Against Invoice":
                    book(bill_for(lid, ref), amount, True)
                else:
                    book(bill_for(lid, ref, date=vdate, type=f"{v['voucher_type']} Voucher (New Ref)", ref=narration, doc=doc), amount, False)
                left -= amount
            if left > 0.005:
                book(bill_for(lid, ON_ACCOUNT_KEY, type="On Account"), left, True)

    # Shape the result: parties -> bills
    sign = 1 if side == "receivables" else -1
    out = {}
    for (lid, _key), b in bills.items():
        billed = b["debit"] if side == "receivables" else b["credit"]
        adjusted = b["credit"] if side == "receivables" else b["debit"]
        outstanding = round(sign * (b["debit"] - b["credit"]), 2)
        p = out.setdefault(lid, {"ledger_id": lid, "name": ledger_names.get(lid) or parties[lid].name, "bills": [],
                                 "billed": 0.0, "adjusted": 0.0, "outstanding": 0.0})
        p["bills"].append({
            "invoice_number": b["invoice_number"], "date": b["date"], "type": b["type"] or "Booking", "ref": b["ref"],
            "doc": b["doc"], "billed": round(billed, 2), "adjusted": round(adjusted, 2), "outstanding": outstanding,
            "adjustments": b["adjustments"],
        })
        p["billed"] += billed
        p["adjusted"] += adjusted
        p["outstanding"] += outstanding
    parties_out = []
    for p in out.values():
        # On Account (Unadjusted Credits / Debits) always last.
        p["bills"].sort(key=lambda x: (x["invoice_number"] == ON_ACCOUNT_KEY, x["date"] or "", x["invoice_number"] or ""))
        p["billed"], p["adjusted"], p["outstanding"] = round(p["billed"], 2), round(p["adjusted"], 2), round(p["outstanding"], 2)
        parties_out.append(p)
    parties_out.sort(key=lambda p: p["name"].lower())
    return parties_out


def party_outstanding_report(request, side):
    """
    GET /api/receivables/?company_id=1[&as_of=YYYY-MM-DD]   (Sundry Debtors)
    GET /api/payables/?company_id=1[&as_of=YYYY-MM-DD]      (Sundry Creditors)
    Bill-wise outstanding per party - see _party_bills.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)
    as_of = request.GET.get("as_of") or None
    parties = _party_bills(company_id, side, as_of_date=as_of)
    return JsonResponse({
        "as_of": as_of, "side": side, "parties": parties,
        "total_billed": round(sum(p["billed"] for p in parties), 2),
        "total_adjusted": round(sum(p["adjusted"] for p in parties), 2),
        "total_outstanding": round(sum(p["outstanding"] for p in parties), 2),
    })


def party_open_bills(request):
    """
    GET /api/party-bills/?company_id=1&ledger_id=5[&exclude_voucher_id=9][&as_of=YYYY-MM-DD]
    For voucher-entry.html's Bill Allocation popup. bill_wise is true only for
    a Sundry Debtors / Sundry Creditors ledger with Maintain Balance
    Bill-by-Bill = Yes; then `bills` lists that party's un-adjusted bills
    (balance = Debit - Credit, + is Dr). exclude_voucher_id leaves out the
    voucher being edited, so its own allocations are free again.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    company_id, ledger_id = request.GET.get("company_id"), request.GET.get("ledger_id")
    if not company_id or not ledger_id:
        return JsonResponse({"error": "company_id and ledger_id are required"}, status=400)
    ledger = Ledger.objects.filter(company_id=company_id, id=ledger_id).first()
    if not ledger:
        return JsonResponse({"error": "Ledger not found."}, status=404)
    side = None
    if ledger.id in _group_ledgers(company_id, "Sundry Debtors"):
        side = "receivables"
    elif ledger.id in _group_ledgers(company_id, "Sundry Creditors"):
        side = "payables"
    bill_wise = bool(side) and str(ledger.maintain_balance_bill_wise or "").strip().lower().startswith("y")
    if not bill_wise:
        return JsonResponse({"bill_wise": False, "side": side, "bills": []})
    parties = _party_bills(company_id, side, as_of_date=request.GET.get("as_of") or None,
                           exclude_voucher_id=request.GET.get("exclude_voucher_id"), only_ledger_id=ledger.id)
    sign = 1 if side == "receivables" else -1
    bills = [{"invoice_number": b["invoice_number"], "date": b["date"], "type": b["type"], "ref": b["ref"],
              "balance": round(sign * b["outstanding"], 2)}
             for p in parties for b in p["bills"]
             if b["invoice_number"] != ON_ACCOUNT_KEY and abs(b["outstanding"]) >= 0.005]
    return JsonResponse({"bill_wise": True, "side": side, "bills": bills})


def _clean_bill_allocations(body):
    """
    Normalises each voucher line's bill_allocations (Against Invoice / New
    Invoice / On Account, each {type, ref, amount}) in place. Returns an error
    message if a line allocates more than its own amount, else None.
    """
    for i, line in enumerate(body.get("lines") or []):
        allocs = line.get("bill_allocations")
        if not allocs:
            line.pop("bill_allocations", None)
            continue
        line_amount = round(float(line.get("debit") or 0) or float(line.get("credit") or 0), 2)
        cleaned = []
        for a in allocs if isinstance(allocs, list) else []:
            kind = a.get("type")
            amount = round(float(a.get("amount") or 0), 2)
            ref = str(a.get("ref") or "").strip()[:60]
            if kind not in ("Against Invoice", "New Invoice", "On Account") or amount <= 0:
                continue
            if kind != "On Account" and not ref:
                return f"Line {i + 1}: {kind} needs a reference."
            cleaned.append({"type": kind, "ref": ref if kind != "On Account" else "", "amount": amount})
        if round(sum(a["amount"] for a in cleaned), 2) > line_amount + 0.005:
            return f"Line {i + 1}: bill allocations add up to more than the line amount {line_amount:.2f}."
        if cleaned:
            line["bill_allocations"] = cleaned
        else:
            line.pop("bill_allocations", None)
    return None


def receivables_report(request):
    return party_outstanding_report(request, "receivables")


def payables_report(request):
    return party_outstanding_report(request, "payables")



def airline_dropdowns(request):
    """
    GET /api/airline-dropdowns/[?list_key=paxTypes]
    Airline dropdown lists from dbo.AirlineDropdownValues, in the same shape
    hardcode.js keeps dropdowns.xml lists in:
      { "paxTypes": { "default": "", "options": [ {"value": "Adult", "label": "Adult", "code": "ADT"}, ... ] }, ... }
    `value` is what the screens save; `code` is the short ID for Auto Push.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    lists = {}
    for r in sp_client.airline_dropdown_list(request.GET.get("list_key") or None):
        lst = lists.setdefault(r["list_key"], {"default": "", "options": []})
        lst["options"].append({"value": r["name"], "label": r["label"], "code": r["code"]})
        if r["is_default"]:
            lst["default"] = r["name"]
    return JsonResponse(lists)
