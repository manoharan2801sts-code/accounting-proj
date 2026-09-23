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
from datetime import datetime
from django.http import JsonResponse, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt
from django.forms.models import model_to_dict
from django.db import transaction, IntegrityError
from django.db.models import ProtectedError, Q

from .models import LedgerGroup, Ledger, Ticket, TicketLine, Voucher, JournalVoucher, SupplierCommissionRule, MasterMapping, FOPMaster, PGMaster, CompanyMaster
from .jv_hardcode import JV_LINE_MAP


def ledger_groups_list(request):
    """
    GET /api/ledger-groups/?company_id=1
    Returns a FLAT list (id, name, code, account_type, parent_id, is_group,
    is_system) — same shape the frontend's renderGroupOptions() already
    expects, so swapping the data source doesn't require rewriting the
    tree-building logic in page-ledger-entry.js.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    groups = LedgerGroup.objects.filter(company_id=company_id).order_by("id")
    data = [
        {
            "id": g.id,
            "name": g.name,
            "code": g.code,
            "account_type": g.account_type,
            "parent_id": g.parent_id,
            "is_group": g.is_group,
            "is_system": g.is_system,
        }
        for g in groups
    ]
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

    group = LedgerGroup.objects.create(
        company_id=body["company_id"],
        name=body["name"],
        code=body.get("code"),
        account_type=body["account_type"],
        parent_id=body.get("parent_id"),
        is_group=body.get("is_group", True),
    )
    return JsonResponse(model_to_dict(group), status=201)


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

    try:
        group = LedgerGroup.objects.get(id=body["parent_id"], company_id=body["company_id"])
    except LedgerGroup.DoesNotExist:
        return JsonResponse({"error": "That group doesn't exist for this company."}, status=400)

    if Ledger.objects.filter(company_id=body["company_id"], name=body["name"]).exists():
        return JsonResponse({"error": f"A ledger named \"{body['name']}\" already exists."}, status=409)

    extra = {f: body[f] for f in LEDGER_FIELDS if f in body}
    if extra.get("agent_id") == "":
        extra["agent_id"] = None
    if extra.get("agent_id") and Ledger.objects.filter(agent_id=extra["agent_id"]).exists():
        return JsonResponse({"error": f"Agent ID \"{extra['agent_id']}\" is already used by another ledger."}, status=409)

    ledger = Ledger.objects.create(
        company_id=body["company_id"],
        name=body["name"],
        group=group,
        account_type=group.account_type,
        ledger_category=body.get("ledger_category", "OTHER"),
        opening_balance=body.get("opening_balance", 0) or 0,
        opening_balance_type=body.get("opening_balance_type", "Debit"),
        **extra,
    )
    return JsonResponse(
        {"id": ledger.id, "name": ledger.name, "group_id": ledger.group_id, "message": "Ledger created."},
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
        ledger = Ledger.objects.get(id=ledger_id, company_id=company_id)
    except Ledger.DoesNotExist:
        return JsonResponse({"error": "Ledger not found."}, status=404)

    try:
        ledger.delete()
    except ProtectedError:
        return JsonResponse(
            {"error": f"\"{ledger.name}\" is used by one or more tickets and can't be deleted."}, status=409
        )
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

    customers = Ledger.objects.filter(company_id=company_id, ledger_category="DEBTOR")
    data = []
    for c in customers:
        india_parts = [p for p in [c.address_line1, c.address_line2, c.city, c.state_name, c.pincode] if p]
        uae_parts = [p for p in [c.address_line1, c.address_line2, c.emirate, c.po_box_no] if p]
        address = ", ".join(india_parts) or ", ".join(uae_parts) or None
        data.append({
            "id": c.id,
            "name": c.name,
            "code": f"LED-{c.id:05d}",
            "gst_no": c.gst_no or c.vat_trn_no,
            "address": address,
            "agent_id": c.agent_id,
        })
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

    try:
        l = Ledger.objects.get(id=ledger_id, company_id=company_id)
    except Ledger.DoesNotExist:
        return JsonResponse({"error": "Ledger not found."}, status=404)

    data = {"id": l.id, "name": l.name, "parent_id": l.group_id, "opening_balance": float(l.opening_balance),
             "balance": float(l.signed_balance), "opening_balance_type": l.opening_balance_type,
             "ledger_category": l.ledger_category}
    for f in LEDGER_FIELDS:
        v = getattr(l, f)
        data[f] = v.isoformat() if hasattr(v, "isoformat") else v
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

    try:
        ledger = Ledger.objects.get(id=ledger_id, company_id=company_id)
    except Ledger.DoesNotExist:
        return JsonResponse({"error": "Ledger not found."}, status=404)

    if "name" in body and Ledger.objects.filter(company_id=company_id, name=body["name"]).exclude(id=ledger_id).exists():
        return JsonResponse({"error": f"A ledger named \"{body['name']}\" already exists."}, status=409)

    if "agent_id" in body and body["agent_id"] == "":
        body["agent_id"] = None
    if body.get("agent_id") and Ledger.objects.filter(agent_id=body["agent_id"]).exclude(id=ledger_id).exists():
        return JsonResponse({"error": f"Agent ID \"{body['agent_id']}\" is already used by another ledger."}, status=409)

    if "name" in body:
        ledger.name = body["name"]
    if "parent_id" in body:
        try:
            ledger.group = LedgerGroup.objects.get(id=body["parent_id"], company_id=company_id)
            ledger.account_type = ledger.group.account_type
        except LedgerGroup.DoesNotExist:
            return JsonResponse({"error": "That group doesn't exist for this company."}, status=400)
    if "opening_balance" in body:
        ledger.opening_balance = body["opening_balance"] or 0
    if "opening_balance_type" in body:
        ledger.opening_balance_type = body["opening_balance_type"]
    if "ledger_category" in body:
        ledger.ledger_category = body["ledger_category"]
    for f in LEDGER_FIELDS:
        if f in body:
            setattr(ledger, f, body[f])
    ledger.save()
    return JsonResponse({"id": ledger.id, "message": "Ledger updated."})


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
    qs = Ledger.objects.filter(agent_id__iexact=agent_id)
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    return JsonResponse({"available": not qs.exists()})


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
    qs = Ledger.objects.filter(company_id=company_id, name__iexact=name)
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    return JsonResponse({"available": not qs.exists()})


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

    suppliers = Ledger.objects.filter(company_id=company_id, ledger_category="CREDITOR")
    data = [
        {"id": s.id, "name": s.name, "code": s.supplier_code or f"LED-{s.id:05d}", "office_id": s.office_id}
        for s in suppliers
    ]
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
        card = FOPMaster.objects.filter(company_id=ticket.company_id, card_number=card_number).first()
        if card:
            result.append((card.card_master_ledger_id, 0, total_amount))
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
    gateway = PGMaster.objects.filter(company_id=ticket.company_id, gateway_name=ticket.payment_gateway_ref or "").select_related("pg_charges_master_ledger").first()
    if gateway:
        pg_charges_total = round(sum(float(l.pg_charges or 0) for l in lines), 2)
        pg_gst_pct = float(gateway.pg_charges_master_ledger.gst_percentage) if gateway.pg_charges_master_ledger_id else 0.0
        pg_gst_total = round(pg_charges_total * pg_gst_pct / 100, 2)

        gateway_debit_total = round(customer_total + pg_charges_total + pg_gst_total, 2)
        result.append((gateway.payment_master_ledger_id, gateway_debit_total, 0))
        if pg_charges_total and gateway.pg_charges_master_ledger_id:
            result.append((gateway.pg_charges_master_ledger_id, pg_charges_total, 0))
            result.append((gateway.payment_master_ledger_id, 0, pg_charges_total))
        if pg_gst_total:
            result.append((gateway.payment_master_ledger_id, 0, pg_gst_total))
    return result


def _ledger_balance_deltas(company_id, as_of_date=None):
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
    """
    deltas = {}

    def add(ledger_id, debit, credit):
        if not ledger_id:
            return
        deltas[ledger_id] = deltas.get(ledger_id, 0.0) + float(debit or 0) - float(credit or 0)

    vouchers = Voucher.objects.filter(company_id=company_id)
    if as_of_date:
        vouchers = vouchers.filter(voucher_date__lte=as_of_date)
    for v in vouchers:
        for line in (v.lines_json or []):
            add(line.get("ledger_id"), line.get("debit"), line.get("credit"))

    tickets = Ticket.objects.filter(company_id=company_id).select_related("customer", "supplier").prefetch_related("lines")
    if as_of_date:
        tickets = tickets.filter(invoice_date__lte=as_of_date)
    for t in tickets:
        lines = list(t.lines.select_related("supplier").all())
        if not lines:
            continue
        accounts, _narration, _total_debit, _total_credit = _compute_jv_lines(t, lines)
        for a in accounts:
            add(a.get("ledger_id"), a.get("debit"), a.get("credit"))
        for ledger_id, debit, credit in _fop_payment_lines(t, lines):
            add(ledger_id, debit, credit)
        for ledger_id, debit, credit in _pg_receipt_lines(t, lines):
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
    for l in Ledger.objects.filter(company_id=company_id).select_related("group"):
        in_use = Ticket.objects.filter(customer_id=l.id).exists() or Ticket.objects.filter(supplier_id=l.id).exists()
        rows.append({
            "id": l.id, "code": l.group.code or "", "name": l.name,
            "account_type": l.account_type, "is_group": False,
            "parent_id": f"g{l.group_id}",
            "balance": float(l.signed_balance) + deltas.get(l.id, 0.0),
            "is_in_use": in_use,
        })
    return JsonResponse(rows, safe=False)


def ledger_book_report(request):
    """
    GET /api/ledger-book/?company_id=1&ledger_id=42[&from_date&to_date]
    Tally-style ledger statement for ONE real leaf Ledger: opening balance,
    then one row per posted transaction that actually touches it (date,
    voucher type, voucher no, opposite account(s), debit, credit, running
    balance) — pulled from the exact same sources _ledger_balance_deltas
    uses (manual Vouchers' lines_json, plus every Ticket's Journal Voucher
    + FOP Payment + PG Receipts tabs, recomputed live), not a separately
    stored ledger-transaction table. Each row that came from a Ticket
    carries ticket_id, so the frontend can jump straight to that ticket
    (view mode) when the row is clicked.
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

    ledger_names = {l.id: (l.alias_name or l.name) for l in Ledger.objects.filter(company_id=company_id)}
    company = CompanyMaster.objects.filter(id=company_id).first()
    txns = []

    for v in Voucher.objects.filter(company_id=company_id):
        if from_date and v.voucher_date and v.voucher_date.isoformat() < from_date:
            continue
        if to_date and v.voucher_date and v.voucher_date.isoformat() > to_date:
            continue
        lines = v.lines_json or []
        mine = [l for l in lines if l.get("ledger_id") == ledger_id]
        if not mine:
            continue
        debit = round(sum(float(l.get("debit") or 0) for l in mine), 2)
        credit = round(sum(float(l.get("credit") or 0) for l in mine), 2)
        others = sorted({l.get("ledger_name") for l in lines if l.get("ledger_id") != ledger_id and l.get("ledger_name")})
        txns.append({
            "date": v.voucher_date.isoformat() if v.voucher_date else None,
            "voucher_type": v.voucher_type, "voucher_no": v.voucher_no or "-",
            "particulars": v.narration or ", ".join(others) or "-",
            "s_pnr": "-", "air_pnr": "-", "ticket_no": "-",
            "opposite": ", ".join(others) or "-", "debit": debit, "credit": credit,
            "ticket_id": None,
        })

    tickets = Ticket.objects.filter(company_id=company_id).select_related("customer", "supplier").prefetch_related("lines")
    if from_date:
        tickets = tickets.filter(invoice_date__gte=from_date)
    if to_date:
        tickets = tickets.filter(invoice_date__lte=to_date)
    for t in tickets:
        lines = list(t.lines.select_related("supplier").all())
        if not lines:
            continue
        accounts, _narration, _td, _tc = _compute_jv_lines(t, lines)
        combined = list(accounts)
        for lid, debit, credit in _fop_payment_lines(t, lines):
            combined.append({"ledger_id": lid, "ledger_name": ledger_names.get(lid, "-"), "debit": debit, "credit": credit})
        for lid, debit, credit in _pg_receipt_lines(t, lines):
            combined.append({"ledger_id": lid, "ledger_name": ledger_names.get(lid, "-"), "debit": debit, "credit": credit})

        mine = [a for a in combined if a.get("ledger_id") == ledger_id]
        if not mine:
            continue
        debit = round(sum(float(a.get("debit") or 0) for a in mine), 2)
        credit = round(sum(float(a.get("credit") or 0) for a in mine), 2)
        if debit == 0 and credit == 0:
            continue
        others = sorted({a.get("ledger_name") for a in combined if a.get("ledger_id") != ledger_id and a.get("ledger_name")})
        voucher = JournalVoucher.objects.filter(source_ticket=t).first()
        airline_names = sorted({n.strip() for l in lines for n in (l.airline_name or "").split(",") if n.strip()})
        ticket_nos = sorted({l.ticket_no for l in lines if l.ticket_no})
        particulars = " - ".join(x for x in [", ".join(airline_names), t.office_id] if x) or "-"
        txns.append({
            "date": t.invoice_date.isoformat() if t.invoice_date else None,
            "voucher_type": "Tax Invoice", "voucher_no": voucher.voucher_no if voucher else t.invoice_number,
            "particulars": particulars,
            "s_pnr": t.booking_reference or "-", "air_pnr": t.airline_pnr or "-",
            "ticket_no": ", ".join(ticket_nos) or "-",
            "opposite": ", ".join(others) or "-", "debit": debit, "credit": credit,
            "ticket_id": t.id,
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

    return JsonResponse({
        "ledger_id": ledger.id, "ledger_name": ledger.alias_name or ledger.name,
        "company_name": company.company_name if company else "",
        "from_date": from_date, "to_date": to_date,
        "opening_balance": round(opening, 2),
        "closing_balance": round(running, 2),
        "total_debit": round(total_debit, 2), "total_credit": round(total_credit, 2),
        "transactions": txns,
    })


def day_book_report(request):
    """
    GET /api/day-book/?company_id=1[&from_date&to_date]
    Tally-style Day Book: one row per posted voucher (every manual
    Voucher + every ticket-driven JournalVoucher) within the date range,
    each already carrying its own resolved total_debit/total_credit —
    unlike the Ledger report this does not re-explode a voucher into its
    individual ledger lines, it lists the voucher itself. Ticket-driven
    rows also surface S PNR / Air-PNR / Ticket No and are clickable
    through to that ticket (ticket_id), same convention as the Ledger
    report. Manual Vouchers and ticket-driven JournalVoucher rows now
    live in two separate tables (split 2026-09-22), so this merges both
    querysets into one chronological list rather than filtering one table.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    from_date = request.GET.get("from_date")
    to_date = request.GET.get("to_date")
    company = CompanyMaster.objects.filter(id=company_id).first()

    txns = []

    manual_vouchers = Voucher.objects.filter(company_id=company_id)
    if from_date:
        manual_vouchers = manual_vouchers.filter(voucher_date__gte=from_date)
    if to_date:
        manual_vouchers = manual_vouchers.filter(voucher_date__lte=to_date)
    for v in manual_vouchers:
        lines = v.lines_json or []
        # Particulars = the OPPOSITE ledger(s), not every ledger on the
        # voucher - a simple 1-debit/N-credit (or N-debit/1-credit) entry
        # shows just the other side, same convention as Tally's Day Book,
        # instead of joining every line's ledger name together.
        debit_lines = [l for l in lines if float(l.get("debit") or 0) > 0]
        credit_lines = [l for l in lines if float(l.get("credit") or 0) > 0]
        if len(debit_lines) == 1:
            opposite = credit_lines
        elif len(credit_lines) == 1:
            opposite = debit_lines
        else:
            opposite = lines
        others = sorted({l.get("ledger_name") for l in opposite if l.get("ledger_name")})
        txns.append({
            "date": v.voucher_date.isoformat() if v.voucher_date else None,
            "particulars": v.narration or ", ".join(others) or "-",
            "voucher_type": v.voucher_type,
            "s_pnr": "-", "air_pnr": "-", "ticket_no": "-",
            "voucher_no": v.voucher_no or "-",
            "debit": float(v.total_debit), "credit": float(v.total_credit),
            "ticket_id": None,
        })

    journal_vouchers = JournalVoucher.objects.filter(company_id=company_id).select_related(
        "source_ticket", "source_ticket__customer"
    )
    if from_date:
        journal_vouchers = journal_vouchers.filter(voucher_date__gte=from_date)
    if to_date:
        journal_vouchers = journal_vouchers.filter(voucher_date__lte=to_date)
    for v in journal_vouchers:
        t = v.source_ticket
        lines = list(t.lines.all()) if t else []
        ticket_nos = sorted({l.ticket_no for l in lines if l.ticket_no})
        txns.append({
            "date": v.voucher_date.isoformat() if v.voucher_date else None,
            "particulars": t.customer.name if t and t.customer else "-",
            "voucher_type": v.voucher_type,
            "s_pnr": (t.booking_reference if t else "") or "-", "air_pnr": (t.airline_pnr if t else "") or "-",
            "ticket_no": ", ".join(ticket_nos) or "-",
            "voucher_no": v.voucher_no or "-",
            "debit": float(v.total_debit), "credit": float(v.total_credit),
            "ticket_id": t.id if t else None,
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
            ledger_rows.append({"id": l.id, "name": l.alias_name or l.name, "closing_balance": bal})
            group_total += bal
        group_total = round(group_total, 2)
        groups_out.append({"group_name": g.name, "closing_balance": group_total, "ledgers": ledger_rows})
        grand_total += group_total

    return JsonResponse({
        "from_date": from_date, "to_date": to_date,
        "groups": groups_out, "grand_total": round(grand_total, 2),
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
    "baggage", "other_ssr", "disc_on", "disc_type", "disc_value", "tds_per", "pg_charges",
    "markup", "addl_markup", "ssr_markup", "service_fee", "addl_service_fee", "ssr_service_fee", "gst_pct", "status",
    "office_id", "fop", "card_number", "supp_comm_on", "supp_comm_type", "supp_comm_value", "supp_tds_per",
    "supp_markup", "supp_addl_markup", "supp_service_fee", "supp_addl_service_fee", "supp_gst_pct",
]
TICKET_LINE_NUMERIC_FIELDS = {
    "basic_fare", "yq", "yr", "k3_tax", "tax_others", "seat", "meal", "baggage", "other_ssr",
    "disc_value", "tds_per", "pg_charges", "markup", "addl_markup", "ssr_markup", "service_fee", "addl_service_fee", "ssr_service_fee", "gst_pct",
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


def _compute_jv_lines(ticket, lines):
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
                 "ledger_name": ticket.customer.alias_name or ticket.customer.name,
                 "debit": debit, "credit": credit}]

    def supplier_rows(dr_cr):
        rows = []
        for g in supplier_groups.values():
            debit, credit = dr_cr_amounts(dr_cr, g["amount"])
            ledger = g["ledger"]
            name = (ledger.alias_name or ledger.name) if ledger else "— (no supplier selected)"
            rows.append({
                "role": "supplier",
                "ledger_id": ledger.id if ledger else None,
                "ledger_name": name,
                "debit": debit, "credit": credit,
            })
        return rows

    # Cache Master Mapping lookups — several JV_LINE_MAP entries share the
    # same (masters_category, field_name) (e.g. the two "Markup A/c" Credit
    # lines), no need to hit the DB twice for the same one.
    mapping_cache = {}
    def mapped_ledger(masters_category, field_name):
        key = (masters_category, field_name)
        if key not in mapping_cache:
            m = MasterMapping.objects.filter(
                company_id=ticket.company_id, product_type="Airline",
                masters_category=masters_category, field_name=field_name,
            ).select_related("ledger").first()
            mapping_cache[key] = (
                (m.ledger_id, m.ledger.alias_name or m.ledger.name) if m
                else (None, f"{field_name} (not mapped in Master Mapping)")
            )
        return mapping_cache[key]

    def mapped_row(dr_cr, masters_category, field_name, amount):
        debit, credit = dr_cr_amounts(dr_cr, amount)
        ledger_id, ledger_name = mapped_ledger(masters_category, field_name)
        return {"role": field_name, "ledger_id": ledger_id, "ledger_name": ledger_name, "debit": debit, "credit": credit}

    accounts = customer_rows("Debit", customer_total) + supplier_rows("Credit")
    for dr_cr, masters_category, field_name, amount_key in JV_LINE_MAP:
        accounts.append(mapped_row(dr_cr, masters_category, field_name, role_amounts[amount_key]))

    narration = " / ".join([p for p in [ticket.booking_reference, ticket.airline_pnr, lines[0].ticket_no] if p])
    total_debit = round(sum(a["debit"] for a in accounts), 2)
    total_credit = round(sum(a["credit"] for a in accounts), 2)
    return accounts, narration, total_debit, total_credit


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

    # Invoice Type / Booking Type / Booking Status are Mandatory per the form spec, but the
    # Ticket model keeps them null=True (older tickets predate this rule) — so a browser bypass
    # (Postman, a stale frontend build, Antigravity script) could still slip a NULL through
    # without this explicit re-check, same reasoning as the customer_name/invoice_number check above.
    missing_required = [
        label for key, label in
        [("invoice_type", "Invoice Type"), ("booking_type", "Booking Type"), ("booking_status", "Booking Status")]
        if not body.get(key)
    ]
    if missing_required:
        verb = "is" if len(missing_required) == 1 else "are"
        return JsonResponse({"error": f"{', '.join(missing_required)} {verb} required."}, status=400)

    try:
        customer = Ledger.objects.get(company_id=company_id, name=body["customer_name"], ledger_category="DEBTOR")
    except Ledger.DoesNotExist:
        return JsonResponse({"error": f"\"{body['customer_name']}\" is not a real customer ledger (Sundry Debtors)."}, status=400)

    supplier = None
    if body.get("supplier_name"):
        try:
            supplier = Ledger.objects.get(company_id=company_id, name=body["supplier_name"], ledger_category="CREDITOR")
        except Ledger.DoesNotExist:
            return JsonResponse({"error": f"\"{body['supplier_name']}\" is not a real supplier ledger (Sundry Creditors)."}, status=400)

    if Ticket.objects.filter(company_id=company_id, invoice_number=body["invoice_number"]).exists():
        return JsonResponse({"error": f"Invoice Number \"{body['invoice_number']}\" already exists."}, status=409)
    if body.get("booking_reference") and Ticket.objects.filter(company_id=company_id, booking_reference=body["booking_reference"]).exists():
        return JsonResponse({"error": f"Booking Reference \"{body['booking_reference']}\" already exists."}, status=409)

    ticket_nos = [l.get("ticket_no") for l in lines_in]
    if len(ticket_nos) != len(set(ticket_nos)):
        return JsonResponse({"error": "Duplicate Ticket Number within this submission."}, status=409)
    existing = TicketLine.objects.filter(ticket_no__in=ticket_nos)
    if existing.exists():
        return JsonResponse({"error": f"Ticket Number \"{existing.first().ticket_no}\" already exists."}, status=409)

    header_kwargs = {f: body[f] for f in TICKET_HEADER_FIELDS if f in body}
    header_kwargs["invoice_date"] = _parse_date(header_kwargs.get("invoice_date"))
    header_kwargs["booking_ref_date"] = _parse_date(header_kwargs.get("booking_ref_date"))
    if "roe" in header_kwargs:
        header_kwargs["roe"] = _safe_decimal(header_kwargs["roe"], default=1)

    ticket = Ticket.objects.create(company_id=company_id, customer=customer, supplier=supplier, **header_kwargs)

    created_lines = []
    line_objs = []
    for line_in in lines_in:
        line_kwargs = {f: line_in[f] for f in TICKET_LINE_FIELDS if f in line_in}
        # travel_date is plain text on TicketLine (multi-city sectors can carry
        # different dates, comma-joined) — no _parse_date() here, unlike the
        # Ticket header's real DateFields.
        for f in TICKET_LINE_NUMERIC_FIELDS:
            if f in line_kwargs:
                line_kwargs[f] = _safe_decimal(line_kwargs[f])

        line_supplier = None
        if line_in.get("supplier_name"):
            try:
                line_supplier = Ledger.objects.get(company_id=company_id, name=line_in["supplier_name"], ledger_category="CREDITOR")
            except Ledger.DoesNotExist:
                transaction.set_rollback(True)
                return JsonResponse({
                    "error": f"\"{line_in['supplier_name']}\" (Ticket No. {line_in.get('ticket_no', '?')}) is not a real supplier ledger (Sundry Creditors)."
                }, status=400)

        line = TicketLine(ticket=ticket, supplier=line_supplier, **line_kwargs)
        line.total_billed = _safe_decimal(line.compute_total())
        line.save()
        created_lines.append(line.id)
        line_objs.append(line)

    # Auto-post the JV immediately — no separate "Post Voucher" step. Every
    # account head/ledger here is hardcoded (jv_hardcode.py) — customer and
    # supplier are the only two backed by a real Ledger row, and both are
    # already validated to exist earlier above, so there's no "missing
    # system ledger" case left to guard against.
    accounts, narration, total_debit, total_credit = _compute_jv_lines(ticket, line_objs)
    total_debit, total_credit = round(total_debit, 2), round(total_credit, 2)
    if total_debit == 0 and total_credit == 0:
        transaction.set_rollback(True)
        return JsonResponse({"error": "This ticket's GL entry total is zero — check the fare fields."}, status=400)

    voucher = JournalVoucher.objects.create(
        company_id=company_id, branch_name=ticket.branch_name or "Chennai Branch",
        voucher_type="Tax Invoice", voucher_date=ticket.invoice_date, narration=narration,
        source_ticket=ticket, total_debit=total_debit, total_credit=total_credit,
        category="AIRLINE", voucher_no=_next_voucher_no(JournalVoucher, company_id, "AIRLINE"),
    )

    balanced = abs(total_debit - total_credit) < 0.01
    status_note = f"Balanced ✓ (Debit {total_debit:.2f} = Credit {total_credit:.2f})" \
        if balanced else f"⚠ Debit {total_debit:.2f} ≠ Credit {total_credit:.2f} — check the JV tab"
    return JsonResponse({
        "id": ticket.id, "line_ids": created_lines, "voucher_id": voucher.id, "voucher_no": voucher.voucher_no,
        "message": f"Ticket saved and GL entry {voucher.voucher_no} posted — {status_note}.",
    }, status=201)


@csrf_exempt
@transaction.atomic
def ticket_update(request, ticket_id):
    """
    POST /api/tickets/<id>/update/
    Body: same shape as tickets/create/. Used by the New Ticket form's
    "Edit" button on an already-saved ticket — same validation as create,
    except uniqueness checks (Invoice Number/Booking Reference/Ticket No)
    exclude this ticket's own existing rows. Replaces this ticket's
    TicketLines wholesale (delete + recreate) rather than diffing them,
    same as how the JV is always recomputed fresh rather than patched —
    simpler and just as correct since the whole line set is resubmitted
    every time. Updates the existing Voucher in place instead of posting
    a second one for the same ticket.
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

    try:
        ticket = Ticket.objects.get(id=ticket_id, company_id=company_id)
    except Ticket.DoesNotExist:
        return JsonResponse({"error": "Ticket not found."}, status=404)

    missing_required = [
        label for key, label in
        [("invoice_type", "Invoice Type"), ("booking_type", "Booking Type"), ("booking_status", "Booking Status")]
        if not body.get(key)
    ]
    if missing_required:
        verb = "is" if len(missing_required) == 1 else "are"
        return JsonResponse({"error": f"{', '.join(missing_required)} {verb} required."}, status=400)

    try:
        customer = Ledger.objects.get(company_id=company_id, name=body["customer_name"], ledger_category="DEBTOR")
    except Ledger.DoesNotExist:
        return JsonResponse({"error": f"\"{body['customer_name']}\" is not a real customer ledger (Sundry Debtors)."}, status=400)

    supplier = None
    if body.get("supplier_name"):
        try:
            supplier = Ledger.objects.get(company_id=company_id, name=body["supplier_name"], ledger_category="CREDITOR")
        except Ledger.DoesNotExist:
            return JsonResponse({"error": f"\"{body['supplier_name']}\" is not a real supplier ledger (Sundry Creditors)."}, status=400)

    if Ticket.objects.filter(company_id=company_id, invoice_number=body["invoice_number"]).exclude(id=ticket.id).exists():
        return JsonResponse({"error": f"Invoice Number \"{body['invoice_number']}\" already exists."}, status=409)
    if body.get("booking_reference") and Ticket.objects.filter(company_id=company_id, booking_reference=body["booking_reference"]).exclude(id=ticket.id).exists():
        return JsonResponse({"error": f"Booking Reference \"{body['booking_reference']}\" already exists."}, status=409)

    ticket_nos = [l.get("ticket_no") for l in lines_in]
    if len(ticket_nos) != len(set(ticket_nos)):
        return JsonResponse({"error": "Duplicate Ticket Number within this submission."}, status=409)
    existing_line = TicketLine.objects.filter(ticket_no__in=ticket_nos).exclude(ticket_id=ticket.id).first()
    if existing_line:
        return JsonResponse({"error": f"Ticket Number \"{existing_line.ticket_no}\" already exists."}, status=409)

    header_kwargs = {f: body[f] for f in TICKET_HEADER_FIELDS if f in body}
    header_kwargs["invoice_date"] = _parse_date(header_kwargs.get("invoice_date"))
    header_kwargs["booking_ref_date"] = _parse_date(header_kwargs.get("booking_ref_date"))
    if "roe" in header_kwargs:
        header_kwargs["roe"] = _safe_decimal(header_kwargs["roe"], default=1)

    ticket.customer = customer
    ticket.supplier = supplier
    for f, v in header_kwargs.items():
        setattr(ticket, f, v)
    ticket.save()

    ticket.lines.all().delete()
    updated_lines = []
    line_objs = []
    for line_in in lines_in:
        line_kwargs = {f: line_in[f] for f in TICKET_LINE_FIELDS if f in line_in}
        for f in TICKET_LINE_NUMERIC_FIELDS:
            if f in line_kwargs:
                line_kwargs[f] = _safe_decimal(line_kwargs[f])

        line_supplier = None
        if line_in.get("supplier_name"):
            try:
                line_supplier = Ledger.objects.get(company_id=company_id, name=line_in["supplier_name"], ledger_category="CREDITOR")
            except Ledger.DoesNotExist:
                transaction.set_rollback(True)
                return JsonResponse({
                    "error": f"\"{line_in['supplier_name']}\" (Ticket No. {line_in.get('ticket_no', '?')}) is not a real supplier ledger (Sundry Creditors)."
                }, status=400)

        line = TicketLine(ticket=ticket, supplier=line_supplier, **line_kwargs)
        line.total_billed = _safe_decimal(line.compute_total())
        line.save()
        updated_lines.append(line.id)
        line_objs.append(line)

    accounts, narration, total_debit, total_credit = _compute_jv_lines(ticket, line_objs)
    total_debit, total_credit = round(total_debit, 2), round(total_credit, 2)
    if total_debit == 0 and total_credit == 0:
        transaction.set_rollback(True)
        return JsonResponse({"error": "This ticket's GL entry total is zero — check the fare fields."}, status=400)

    voucher = JournalVoucher.objects.filter(source_ticket_id=ticket.id).first()
    if voucher:
        voucher.branch_name = ticket.branch_name or "Chennai Branch"
        voucher.voucher_date = ticket.invoice_date
        voucher.narration = narration
        voucher.total_debit = total_debit
        voucher.total_credit = total_credit
        voucher.save()
    else:
        voucher = JournalVoucher.objects.create(
            company_id=company_id, branch_name=ticket.branch_name or "Chennai Branch",
            voucher_type="Tax Invoice", voucher_date=ticket.invoice_date, narration=narration,
            source_ticket=ticket, total_debit=total_debit, total_credit=total_credit,
            category="AIRLINE", voucher_no=_next_voucher_no(JournalVoucher, company_id, "AIRLINE"),
        )

    balanced = abs(total_debit - total_credit) < 0.01
    status_note = f"Balanced ✓ (Debit {total_debit:.2f} = Credit {total_credit:.2f})" \
        if balanced else f"⚠ Debit {total_debit:.2f} ≠ Credit {total_credit:.2f} — check the JV tab"
    return JsonResponse({
        "id": ticket.id, "line_ids": updated_lines, "voucher_id": voucher.id, "voucher_no": voucher.voucher_no,
        "message": f"Ticket updated and GL entry {voucher.voucher_no} re-posted — {status_note}.",
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
    try:
        t = Ticket.objects.select_related("customer", "supplier").get(id=ticket_id, company_id=company_id)
    except Ticket.DoesNotExist:
        return JsonResponse({"error": "Ticket not found."}, status=404)

    lines = [{
        "airline_code": l.airline_code, "airline_name": l.airline_name, "airline_category": l.airline_category,
        "flight_no": l.flight_no,
        "ticket_no": l.ticket_no, "passenger_name": l.passenger_name, "pax_type": l.pax_type,
        "sector": l.sector, "travel_date": l.travel_date,
        "cabin": l.cabin, "travel_class": l.travel_class, "fare_type": l.fare_type,
        "basic_fare": float(l.basic_fare), "yq": float(l.yq), "yr": float(l.yr), "k3_tax": float(l.k3_tax),
        "tax_others": float(l.tax_others), "seat": float(l.seat), "meal": float(l.meal),
        "baggage": float(l.baggage), "other_ssr": float(l.other_ssr), "disc_on": l.disc_on,
        "disc_type": l.disc_type, "disc_value": float(l.disc_value), "tds_per": float(l.tds_per),
        "pg_charges": float(l.pg_charges or 0),
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
        "computed_discount": float(l.computed_discount), "computed_tds": float(l.computed_tds), "computed_gst": float(l.computed_gst),
        "computed_supp_commission": float(l.computed_supp_commission), "computed_supp_tds": float(l.computed_supp_tds),
        "computed_supp_gst": float(l.computed_supp_gst),
    } for l in t.lines.select_related("supplier").all()]

    return JsonResponse({
        "id": t.id, "invoice_number": t.invoice_number, "invoice_date": t.invoice_date.isoformat() if t.invoice_date else None,
        "invoice_type": t.invoice_type, "booking_mode": t.booking_mode, "booking_type": t.booking_type,
        "booking_status": t.booking_status, "customer_name": t.customer.name, "travel_type": t.travel_type,
        "user_name": t.user_name, "currency": t.currency, "roe": float(t.roe), "booking_given_by": t.booking_given_by,
        "booking_reference": t.booking_reference, "booking_ref_date": t.booking_ref_date.isoformat() if t.booking_ref_date else None,
        "airline_pnr": t.airline_pnr, "gds_pnr": t.gds_pnr, "supplier_name": t.supplier.name if t.supplier else None,
        "office_id": t.office_id, "payment_mode": t.payment_mode, "payment_gateway_ref": t.payment_gateway_ref,
        "airline_category": t.airline_category,
        "branch_name": t.branch_name, "lines": lines,
    })


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
    lines = TicketLine.objects.filter(ticket__company_id=company_id).select_related("ticket", "ticket__customer", "ticket__supplier", "supplier").order_by("-id")
    for l in lines:
        t = l.ticket
        rows.append({
            "id": l.id, "ticket_id": t.id,
            "pnr": t.airline_pnr or t.gds_pnr or t.booking_reference,
            "ticket_no": l.ticket_no, "airline_name": l.airline_name, "airline_code": l.airline_code,
            "flight_no": l.flight_no, "passenger_name": l.passenger_name, "pax_type": l.pax_type,
            "sector": l.sector, "issue_date": t.invoice_date.isoformat() if t.invoice_date else None,
            "travel_date": l.travel_date,
            "basic_fare": float(l.basic_fare), "markup": float(l.markup), "total_billed": float(l.total_billed),
            "status": l.status,
            "invoice_number": t.invoice_number, "invoice_date": t.invoice_date.isoformat() if t.invoice_date else None,
            "invoice_type": t.invoice_type, "booking_mode": t.booking_mode, "booking_type": t.booking_type,
            "booking_status": t.booking_status, "customer_name": t.customer.name,
            "travel_type": t.travel_type, "user_name": t.user_name, "currency": t.currency, "roe": float(t.roe),
            "booking_given_by": t.booking_given_by, "payment_mode": t.payment_mode, "airline_category": l.airline_category,
            "booking_reference": t.booking_reference, "booking_ref_date": t.booking_ref_date.isoformat() if t.booking_ref_date else None,
            "airline_pnr": t.airline_pnr, "gds_pnr": t.gds_pnr, "supplier_name": l.supplier.name if l.supplier else None,
            "office_id": l.office_id, "fop": l.fop, "card_number": l.card_number,
            "yq": float(l.yq), "yr": float(l.yr), "k3_tax": float(l.k3_tax), "tax_others": float(l.tax_others),
            "seat": float(l.seat), "meal": float(l.meal), "baggage": float(l.baggage), "other_ssr": float(l.other_ssr),
            "disc_on": l.disc_on, "disc_type": l.disc_type, "disc_value": float(l.disc_value), "tds_per": float(l.tds_per),
            "addl_markup": float(l.addl_markup), "ssr_markup": float(l.ssr_markup), "service_fee": float(l.service_fee),
            "addl_service_fee": float(l.addl_service_fee), "ssr_service_fee": float(l.ssr_service_fee), "gst_pct": float(l.gst_pct),
            "supp_comm_on": l.supp_comm_on, "supp_comm_type": l.supp_comm_type,
            "supp_comm_value": float(l.supp_comm_value), "supp_tds_per": float(l.supp_tds_per),
        })
    return JsonResponse(rows, safe=False)


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
def _validate_and_resolve_voucher_body(body):
    """
    Shared by voucher_create and voucher_update — parses+validates the
    body and resolves each line's ledger_id into a real Ledger, so create
    and update can never drift apart on what "a valid voucher" means.
    Returns (error_response_or_None, total_debit, total_credit, resolved_lines).
    """
    company_id = body.get("company_id")
    lines_in = body.get("lines") or []
    if not company_id or not body.get("voucher_date") or len(lines_in) < 2:
        return JsonResponse({"error": "company_id, voucher_date, and at least 2 lines are required."}, status=400), None, None, None

    total_debit = sum(float(l.get("debit") or 0) for l in lines_in)
    total_credit = sum(float(l.get("credit") or 0) for l in lines_in)
    if round(total_debit, 2) != round(total_credit, 2):
        return JsonResponse({
            "error": f"Voucher is unbalanced: total debit {total_debit:.2f} does not equal total credit {total_credit:.2f}."
        }, status=400), None, None, None
    if round(total_debit, 2) == 0:
        return JsonResponse({"error": "Voucher total cannot be zero."}, status=400), None, None, None

    resolved_lines = []
    for i, l in enumerate(lines_in):
        if not l.get("ledger_id"):
            return JsonResponse({"error": f"Line {i + 1} is missing a ledger — check that all system ledgers exist."}, status=400), None, None, None
        try:
            ledger_name = Ledger.objects.get(id=l["ledger_id"]).name
        except Ledger.DoesNotExist:
            return JsonResponse({"error": f"Line {i + 1} references a ledger that doesn't exist."}, status=400), None, None, None
        resolved_lines.append({
            "ledger_id": l["ledger_id"], "ledger_name": ledger_name,
            "debit": float(l.get("debit") or 0), "credit": float(l.get("credit") or 0),
        })

    return None, total_debit, total_credit, resolved_lines


def _voucher_dict(v):
    return {
        "id": v.id, "voucher_no": v.voucher_no, "branch_name": v.branch_name, "voucher_type": v.voucher_type,
        "voucher_date": v.voucher_date.isoformat() if v.voucher_date else None,
        "narration": v.narration,
        "total_debit": float(v.total_debit), "total_credit": float(v.total_credit),
        "lines": v.lines_json or [],
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

    error, total_debit, total_credit, resolved_lines = _validate_and_resolve_voucher_body(body)
    if error:
        return error

    voucher = Voucher.objects.create(
        company_id=body.get("company_id"),
        branch_name=body.get("branch_name"),
        voucher_type=body.get("voucher_type", "Journal"),
        voucher_date=_parse_date(body.get("voucher_date")),
        narration=body.get("narration"),
        total_debit=total_debit,
        total_credit=total_credit,
        category="MANUAL", voucher_no=_next_voucher_no(Voucher, body.get("company_id"), "MANUAL"),
        lines_json=resolved_lines,
    )

    return JsonResponse({"id": voucher.id, "message": "Voucher posted."}, status=201)


def voucher_detail(request, voucher_id):
    """GET /api/vouchers/<id>/?company_id=1 — one manual Voucher, for the Edit form to prefill from."""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    try:
        voucher = Voucher.objects.get(id=voucher_id, company_id=company_id)
    except Voucher.DoesNotExist:
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
        voucher = Voucher.objects.get(id=voucher_id, company_id=body.get("company_id"))
    except Voucher.DoesNotExist:
        return JsonResponse({"error": "Voucher not found."}, status=404)

    error, total_debit, total_credit, resolved_lines = _validate_and_resolve_voucher_body(body)
    if error:
        return error

    voucher.branch_name = body.get("branch_name")
    voucher.voucher_type = body.get("voucher_type", "Journal")
    voucher.voucher_date = _parse_date(body.get("voucher_date"))
    voucher.narration = body.get("narration")
    voucher.total_debit = total_debit
    voucher.total_credit = total_credit
    voucher.lines_json = resolved_lines
    voucher.save()

    return JsonResponse({"id": voucher.id, "message": "Voucher updated."})


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

    vouchers = Voucher.objects.filter(company_id=company_id).order_by("-voucher_date", "-id")
    return JsonResponse([_voucher_dict(v) for v in vouchers], safe=False)


SUPPLIER_RULE_FIELDS = [
    "office_id", "supplier_name", "travel_type", "airline_category", "cabin", "fare_type", "comm_on",
    "calc_type", "calc_pct", "flat_amt", "valid_upto",
]


def _supplier_rule_dict(r):
    return {
        "id": r.id, "type": r.rule_type,
        "office_id": r.office_id, "supplier_name": r.supplier_name,
        "travel_type": r.travel_type, "airline_category": r.airline_category,
        "cabin": r.cabin, "fare_type": r.fare_type, "comm_on": r.comm_on,
        "calc_type": r.calc_type, "calc_pct": float(r.calc_pct), "flat_amt": float(r.flat_amt),
        # valid_upto is a real date once re-fetched from the DB, but right
        # after .save() on a freshly-built instance it's still whatever raw
        # string was set on it (Django's DateField doesn't coerce on assign,
        # only at the DB layer) — handle both shapes.
        "valid_upto": r.valid_upto.isoformat() if hasattr(r.valid_upto, "isoformat") else (r.valid_upto or None),
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

    rules = SupplierCommissionRule.objects.filter(company_id=company_id)
    office_id = request.GET.get("office_id")
    if office_id:
        rules = rules.filter(office_id=office_id)
    rules = rules.order_by("-id")
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

    rule = SupplierCommissionRule(company_id=company_id, office_id=office_id)
    for f in SUPPLIER_RULE_FIELDS:
        if f == "office_id":
            continue
        if f in body and body[f] not in (None, ""):
            setattr(rule, f, body[f])
    rule.save()
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
        rule = SupplierCommissionRule.objects.get(id=rule_id, company_id=company_id)
    except SupplierCommissionRule.DoesNotExist:
        return JsonResponse({"error": "Rule not found."}, status=404)

    rule.delete()
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

    name_query = Q()
    for v in variants:
        name_query |= Q(name__iexact=v)
    candidates = LedgerGroup.objects.filter(company_id=company_id).filter(name_query)
    group_ids = set(candidates.values_list("id", flat=True))
    frontier = list(group_ids)
    while frontier:
        children = list(
            LedgerGroup.objects.filter(company_id=company_id, parent_id__in=frontier)
            .exclude(id__in=group_ids)
            .values_list("id", flat=True)
        )
        group_ids.update(children)
        frontier = children

    ledgers = Ledger.objects.filter(company_id=company_id, group_id__in=group_ids).order_by("name")
    return JsonResponse([{"id": l.id, "name": l.alias_name or l.name} for l in ledgers], safe=False)


def _master_mapping_dict(m):
    return {
        "id": m.id, "product_type": m.product_type,
        "masters_category": m.masters_category, "masters_category_id": m.masters_category_id,
        "field_name": m.field_name, "ledger_id": m.ledger_id, "ledger_name": m.ledger_name,
        "ledger_gst_percentage": float(m.ledger.gst_percentage) if m.ledger_id else 0,
        "effective_from": m.effective_from.isoformat() if hasattr(m.effective_from, "isoformat") else (m.effective_from or None),
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

    rows = MasterMapping.objects.filter(company_id=company_id).select_related("ledger")
    product_type = request.GET.get("product_type")
    if product_type:
        rows = rows.filter(product_type=product_type)
    masters_category = request.GET.get("masters_category")
    if masters_category:
        rows = rows.filter(masters_category=masters_category)
    rows = rows.order_by("product_type", "masters_category", "id")
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
            ledger = Ledger.objects.get(id=ledger_id, company_id=company_id)
        except Ledger.DoesNotExist:
            return JsonResponse({"error": f"Ledger {ledger_id} not found."}, status=404)

        try:
            mapping, _created = MasterMapping.objects.update_or_create(
                company_id=company_id, product_type=product_type, field_name=field_name,
                defaults={
                    "masters_category": masters_category,
                    "masters_category_id": MasterMapping.MASTERS_CATEGORY_IDS.get(masters_category, 0),
                    "ledger": ledger, "ledger_name": ledger.alias_name or ledger.name,
                    "effective_from": effective_from,
                },
            )
        except IntegrityError as exc:
            return JsonResponse({
                "error": f"Could not save \"{field_name}\" — the database rejected it "
                         f"(likely the MasterMapping table's CHECK constraints are out of date "
                         f"for the \"{masters_category}\" category; re-run the ALTER statements "
                         f"from backend/Schema.sql against Accounting_DB). Detail: {exc}",
            }, status=409)
        saved.append(_master_mapping_dict(mapping))

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
        mapping = MasterMapping.objects.get(id=mapping_id, company_id=company_id)
    except MasterMapping.DoesNotExist:
        return JsonResponse({"error": "Mapping not found."}, status=404)

    mapping.delete()
    return JsonResponse({"ok": True})


def _fop_master_dict(f):
    return {
        "id": f.id, "card_type": f.card_type, "card_number": f.card_number, "bank_name": f.bank_name,
        "card_master_ledger_id": f.card_master_ledger_id, "card_master_ledger_name": f.card_master_ledger_name,
        "is_active": f.is_active,
    }


def fop_master_list(request):
    """GET /api/fop-master/?company_id=1[&card_type=Own Card]"""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    rows = FOPMaster.objects.filter(company_id=company_id)
    card_type = request.GET.get("card_type")
    if card_type:
        rows = rows.filter(card_type=card_type)
    rows = rows.order_by("card_type", "card_number")
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
    # Card Master is Own Card only - Client Card has no ledger link.
    if card_type == "Own Card" and not ledger_id:
        return JsonResponse({"error": "card_master_ledger_id is required for Own Card"}, status=400)

    ledger = None
    if ledger_id:
        try:
            ledger = Ledger.objects.get(id=ledger_id, company_id=company_id)
        except Ledger.DoesNotExist:
            return JsonResponse({"error": f"Ledger {ledger_id} not found."}, status=404)

    dup = FOPMaster.objects.filter(company_id=company_id, card_number=card_number).exclude(id=body.get("id")).exists()
    if dup:
        return JsonResponse({"error": f"Card Number \"{card_number}\" is already used."}, status=409)

    ledger_name = (ledger.alias_name or ledger.name) if ledger else None

    card_id = body.get("id")
    if card_id:
        try:
            card = FOPMaster.objects.get(id=card_id, company_id=company_id)
            card.card_type = card_type
            card.card_number = card_number
            card.bank_name = (body.get("bank_name") or "").strip() or None
            card.card_master_ledger = ledger
            card.card_master_ledger_name = ledger_name
            card.is_active = bool(body.get("is_active", True))
            card.save()
            return JsonResponse(_fop_master_dict(card), status=200)
        except FOPMaster.DoesNotExist:
            return JsonResponse({"error": f"Card {card_id} not found."}, status=404)

    card, _created = FOPMaster.objects.update_or_create(
        company_id=company_id, card_number=card_number,
        defaults={
            "card_type": card_type, "bank_name": (body.get("bank_name") or "").strip() or None,
            "card_master_ledger": ledger, "card_master_ledger_name": ledger_name,
            "is_active": bool(body.get("is_active", True)),
        },
    )
    return JsonResponse(_fop_master_dict(card), status=201)


@csrf_exempt
def fop_master_delete(request, card_id):
    """DELETE /api/fop-master/<id>/delete/?company_id=1"""
    if request.method != "DELETE":
        return HttpResponseNotAllowed(["DELETE"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    try:
        card = FOPMaster.objects.get(id=card_id, company_id=company_id)
    except FOPMaster.DoesNotExist:
        return JsonResponse({"error": "Card not found."}, status=404)

    card.delete()
    return JsonResponse({"ok": True})


def _pg_master_dict(p):
    return {
        "id": p.id, "gateway_name": p.gateway_name,
        "payment_master_ledger_id": p.payment_master_ledger_id, "payment_master_ledger_name": p.payment_master_ledger_name,
        "pg_charges_master_ledger_id": p.pg_charges_master_ledger_id, "pg_charges_master_ledger_name": p.pg_charges_master_ledger_name,
        "pg_charges_master_ledger_gst_percentage": float(p.pg_charges_master_ledger.gst_percentage) if p.pg_charges_master_ledger_id else 0,
        "is_active": p.is_active,
    }


def pg_master_list(request):
    """GET /api/pg-master/?company_id=1"""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    rows = PGMaster.objects.filter(company_id=company_id).select_related("pg_charges_master_ledger").order_by("gateway_name")
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

    try:
        ledger = Ledger.objects.get(id=ledger_id, company_id=company_id)
    except Ledger.DoesNotExist:
        return JsonResponse({"error": f"Ledger {ledger_id} not found."}, status=404)

    charges_ledger_id = body.get("pg_charges_master_ledger_id")
    charges_ledger = None
    if charges_ledger_id:
        try:
            charges_ledger = Ledger.objects.get(id=charges_ledger_id, company_id=company_id)
        except Ledger.DoesNotExist:
            return JsonResponse({"error": f"Ledger {charges_ledger_id} not found."}, status=404)

    dup = PGMaster.objects.filter(company_id=company_id, gateway_name=gateway_name).exclude(id=body.get("id")).exists()
    if dup:
        return JsonResponse({"error": f"Payment Gateway Name \"{gateway_name}\" is already used."}, status=409)

    gw_id = body.get("id")
    if gw_id:
        try:
            gateway = PGMaster.objects.get(id=gw_id, company_id=company_id)
            gateway.gateway_name = gateway_name
            gateway.payment_master_ledger = ledger
            gateway.payment_master_ledger_name = ledger.alias_name or ledger.name
            gateway.pg_charges_master_ledger = charges_ledger
            gateway.pg_charges_master_ledger_name = (charges_ledger.alias_name or charges_ledger.name) if charges_ledger else None
            gateway.is_active = bool(body.get("is_active", True))
            gateway.save()
            return JsonResponse(_pg_master_dict(gateway), status=200)
        except PGMaster.DoesNotExist:
            return JsonResponse({"error": f"Payment Gateway {gw_id} not found."}, status=404)

    gateway, _created = PGMaster.objects.update_or_create(
        company_id=company_id, gateway_name=gateway_name,
        defaults={
            "payment_master_ledger": ledger, "payment_master_ledger_name": ledger.alias_name or ledger.name,
            "pg_charges_master_ledger": charges_ledger,
            "pg_charges_master_ledger_name": (charges_ledger.alias_name or charges_ledger.name) if charges_ledger else None,
            "is_active": bool(body.get("is_active", True)),
        },
    )
    return JsonResponse(_pg_master_dict(gateway), status=201)


@csrf_exempt
def pg_master_delete(request, gateway_id):
    """DELETE /api/pg-master/<id>/delete/?company_id=1"""
    if request.method != "DELETE":
        return HttpResponseNotAllowed(["DELETE"])

    company_id = request.GET.get("company_id")
    if not company_id:
        return JsonResponse({"error": "company_id is required"}, status=400)

    try:
        gateway = PGMaster.objects.get(id=gateway_id, company_id=company_id)
    except PGMaster.DoesNotExist:
        return JsonResponse({"error": "Payment Gateway not found."}, status=404)

    gateway.delete()
    return JsonResponse({"ok": True})


def _company_master_dict(c):
    return {
        "id": c.id, "company_name": c.company_name, "mailing_name": c.mailing_name,
        "address": c.address, "country": c.country, "state": c.state, "pincode": c.pincode,
        "telephone": c.telephone, "mobile": c.mobile, "email": c.email,
        "financial_year_from": c.financial_year_from.isoformat() if c.financial_year_from else None,
        "books_beginning_from": c.books_beginning_from.isoformat() if c.books_beginning_from else None,
        "gst_reg_type": c.gst_reg_type, "gst_no": c.gst_no, "cin_number": c.cin_number,
        "tan_number": c.tan_number, "hsn_sac": c.hsn_sac, "description": c.description,
    }


def company_master_list(request):
    """GET /api/company-master/[?id=1] - every company, or one by id."""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])

    company_id = request.GET.get("id")
    if company_id:
        try:
            c = CompanyMaster.objects.get(id=company_id)
        except CompanyMaster.DoesNotExist:
            return JsonResponse({"error": "Company not found."}, status=404)
        return JsonResponse(_company_master_dict(c))

    rows = CompanyMaster.objects.all().order_by("company_name")
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
            "gst_no": "...", "cin_number": "...", "tan_number": "...",
            "hsn_sac": "...", "description": "..." }
    Upserts by company_name (the table's unique key) unless "id" is given.
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
        "financial_year_from": body.get("financial_year_from") or None,
        "books_beginning_from": body.get("books_beginning_from") or None,
        "gst_reg_type": body.get("gst_reg_type") or "Regular",
        "gst_no": (body.get("gst_no") or "").strip().upper() or None,
        "cin_number": (body.get("cin_number") or "").strip().upper() or None,
        "tan_number": (body.get("tan_number") or "").strip().upper() or None,
        "hsn_sac": (body.get("hsn_sac") or "").strip() or None,
        "description": (body.get("description") or "").strip() or None,
    }

    dup = CompanyMaster.objects.filter(company_name=company_name).exclude(id=body.get("id")).exists()
    if dup:
        return JsonResponse({"error": f"Company \"{company_name}\" already exists."}, status=409)

    company_id = body.get("id")
    if company_id:
        try:
            company = CompanyMaster.objects.get(id=company_id)
        except CompanyMaster.DoesNotExist:
            return JsonResponse({"error": f"Company {company_id} not found."}, status=404)
        for key, value in fields.items():
            setattr(company, key, value)
        company.save()
        return JsonResponse(_company_master_dict(company), status=200)

    company = CompanyMaster.objects.create(**fields)
    return JsonResponse(_company_master_dict(company), status=201)


@csrf_exempt
def company_master_delete(request, company_id):
    """DELETE /api/company-master/<id>/delete/"""
    if request.method != "DELETE":
        return HttpResponseNotAllowed(["DELETE"])

    try:
        company = CompanyMaster.objects.get(id=company_id)
    except CompanyMaster.DoesNotExist:
        return JsonResponse({"error": "Company not found."}, status=404)

    company.delete()
    return JsonResponse({"ok": True})