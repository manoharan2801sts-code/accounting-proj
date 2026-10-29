"""
Airline ticket Auto Push import
-----------------------------------------------------------------
An external booking system (the Agent) pushes tickets to
POST /api/import/tickets/push/ - the parameters of the "Accounting API
Details" sheet (API_PARAMETERS below):

  1. Every value is checked against our own masters before anything is
     saved: dropdown codes against dbo.AirlineDropdownValues (Booking Status
     C/R/X/SSR, Booking Type, Travel Type, Payment Mode, Airline Category, Pax
     Type, Cabin, Fare Type, FOP), Customer ID against the Agent ID of a
     Sundry Debtors ledger, Office ID against a Creditor ledger, Gateway Ref
     against PG Master, Card Number against FOP Master (same card type),
     Airline Code / Sector against assets/data/Airlinenames.xml /
     cityairport_lst.xml. The Service Fee GST Amounts are the Agent's own
     figures: saved as sent (only checked to be numbers) and used instead of
     fee x Ledger Mapping GST % - that % calculation is for manual entry
     (models.gst_part, dbo.Ticket_Line_Gst_Amount). Every problem
     (missing, invalid format, not mapped, mismatch, not allowed, duplicate,
     unknown field) goes to dbo.Ticket_Import_Error_Log - the /error_log/
     page shows it.
  2. A clean invoice is translated to the values the screens save (codes ->
     names, Customer ID -> customer ledger, Office ID -> supplier ...) and
     staged in dbo.Ticket_Import_Staging, one row per passenger. Pushing the
     same invoice again never creates a second invoice.
  3. Staged invoices are saved right away, and again by the scheduler
     (manage.py run_ticket_import) for retries and for a Reschedule /
     Cancellation still waiting on the ticket it changes. Saving goes through
     the SAME views Ticket Entry's own Save button uses - ticket_create /
     reschedule_ticket_create / cancellation_ticket_create, and the SSR
     Updation screen's ssr_ticket_create for Booking Status SSR - so the Journal
     Voucher, the audit log and every report treat an imported ticket exactly
     like a typed one. booking_mode is saved as "Auto Push", the Invoice Date
     is the push date, the Invoice Type is the one the admin picked for that
     Booking Status (Voucher Type page) and the Invoice Number comes from its
     numbering. A save the views refuse is logged too (stage Import).
"""
import hashlib
import json
import logging
import math
import re
import threading
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import cached_property
from pathlib import Path

from django.conf import settings
from django.http import HttpResponseNotAllowed, HttpResponseRedirect, JsonResponse
from django.test import RequestFactory
from django.views.decorators.csrf import csrf_exempt

from . import models, permissions, sp_client, views

logger = logging.getLogger(__name__)

TICKET_STATUSES = ("Confirmed", "Rescheduled", "Cancelled", "SSR")
# Document kind -> the Booking Status the screens save (bookingStatuses list names).
BOOKING_STATUS = {"Confirmed": "Confirmed", "Rescheduled": "Re-Scheduled", "Cancelled": "Normal Cancelled",
                  "SSR": "SSR Updated"}
STATUS_BY_NAME = {name: kind for kind, name in BOOKING_STATUS.items()}
# Push body keys that belong to the push itself, not to the invoice.
PUSH_KEYS = ("company_id", "source_system", "batch_id", "process_now")
MAX_DOCUMENTS_PER_PUSH = 500

# ---------------------------------------------------------------------------
# The API parameters (Accounting API Details sheet) -> screen label.
# ---------------------------------------------------------------------------
HEADER_PARAMS = {
    "booking_status": "Booking Status", "booking_type": "Booking Type", "customer_id": "Customer ID",
    "travel_type": "Travel Type", "user_name": "User Name", "booking_given_by": "Booking Given By",
    "booking_reference": "Booking Reference", "booking_ref_date": "Booking Ref Date", "airline_pnr": "Airline PNR",
    "gds_pnr": "GDS PNR", "payment_mode": "Payment Mode", "gateway_ref": "Gateway Ref",
    # FOP / Card Number: once per invoice - every passenger takes the same
    # (the FOP Payment JV pays the whole invoice from one card).
    "fop": "FOP", "card_number": "Card Number",
    "parent_pnr": "Parent PNR", "passengers": "Passengers",
}
# Sent at the invoice level only - refused inside a passenger.
INVOICE_ONLY_PARAMS = ("fop", "card_number")
PAX_TEXT_PARAMS = {
    "ticket_no": "Ticket No", "original_ticket_no": "Original Ticket No", "pax_name": "Pax Name",
    "pax_type": "Pax Type", "airline_category": "Airline Category", "sector": "Sector", "airline_code": "Airline Code",
    "travel_date": "Travel Date", "flight_no": "Flight No", "cabin": "Cabin", "class": "Class",
    "fare_type": "Fare Type", "office_id": "Office ID",
}
# SSR Updation (Booking Status SSR) - per SSR type: (EMD Ticket No, SSR Details)
# parameters, and the charge parameter of that type. Saved on the SSR line as
# ssr_ticket_numbers / ssr_items ({"Baggage": ...}) - the SSR screen's popup.
SSR_PARAMS = {
    "Baggage": ("emd_ticket_no_baggage", "ssr_baggage_details", "baggage_charges"),
    "Meal": ("emd_ticket_no_meal", "ssr_meal_details", "meal_charges"),
    "Seat": ("emd_ticket_no_seat", "ssr_seat_details", "seat_charges"),
    "Other SSR": ("emd_ticket_no_other_ssr", "ssr_other_details", "other_ssr"),
}
SSR_TEXT_PARAMS = {
    "emd_ticket_no_baggage": "EMD Ticket No Baggage", "emd_ticket_no_meal": "EMD Ticket No Meal",
    "emd_ticket_no_seat": "EMD Ticket No Seat", "emd_ticket_no_other_ssr": "EMD Ticket No Other SSR",
    "ssr_baggage_details": "SSR Baggage Details", "ssr_meal_details": "SSR Meal Details",
    "ssr_seat_details": "SSR Seat Details", "ssr_other_details": "SSR Other Details",
}
PAX_TEXT_PARAMS.update(SSR_TEXT_PARAMS)
# Amount parameter -> (label, the line field it is saved in; None = worked out below).
AMOUNT_PARAMS = {
    "basic_fare": ("Basic Fare", "basic_fare"),
    "yq_tax": ("YQ Tax", "yq"),
    "yr_tax": ("YR Tax", "yr"),
    "k3_tax": ("K3 Tax", "k3_tax"),
    "tax_others": ("Tax & Others", "tax_others"),
    "seat_charges": ("Seat Charges", "seat"),
    "meal_charges": ("Meal Charges", "meal"),
    "baggage_charges": ("Baggage", "baggage"),
    "other_ssr": ("Other SSR", "other_ssr"),
    "cust_discount_amount": ("Customer Discount Amount", None),
    "cust_tds_amount": ("Customer TDS Amount", None),
    "cust_markup": ("Customer Markup", "markup"),
    "cust_addl_markup": ("Customer Additional Markup", "addl_markup"),
    "cust_ssr_markup": ("Customer SSR Markup", "ssr_markup"),
    "cust_service_fee": ("Customer Service Fee", "service_fee"),
    "cust_addl_service_fee": ("Customer Additional Service Fee", "addl_service_fee"),
    "cust_ssr_service_fee": ("Customer SSR Service Fee", "ssr_service_fee"),
    "cust_service_fee_gst": ("Customer Service Fee GST Amount", None),
    "cust_ssr_service_fee_gst": ("Customer SSR Service Fee GST Amount", None),
    "cust_addl_service_fee_gst": ("Customer Additional Service Fee GST Amount", None),
    "supp_commission_amount": ("Supplier Commission Amount", None),
    "supp_tds_amount": ("Supplier TDS Amount", None),
    "supp_markup": ("Supplier Markup", "supp_markup"),
    "supp_addl_markup": ("Supplier Additional Markup", "supp_addl_markup"),
    "supp_ssr_markup": ("Supplier SSR Markup", "supp_ssr_markup"),
    "supp_service_fee": ("Supplier Service Fee", "supp_service_fee"),
    "supp_addl_service_fee": ("Supplier Additional Service Fee", "supp_addl_service_fee"),
    "supp_ssr_service_fee": ("Supplier SSR Service Fee", "supp_ssr_service_fee"),
    "supp_service_fee_gst": ("Supplier Service Fee GST Amount", None),
    "supp_ssr_service_fee_gst": ("Supplier SSR Service Fee GST Amount", None),
    "supp_addl_service_fee_gst": ("Supplier Additional Service Fee GST Amount", None),
    "supplier_penalty": ("Supplier Penalty", "supplier_penalty"),
    "agent_penalty": ("Agent Penalty", "agent_penalty"),
    "penalty_amount": ("Penalty Amount", None),   # Rescheduled -> reschedule_penalty, Cancelled -> cancellation_penalty
    "cust_markup_reversal": ("Customer Markup Reversal", "cust_markup_reversal"),
    "cust_addl_markup_reversal": ("Customer Additional Markup Reversal", "cust_addl_markup_reversal"),
    "cust_ssr_markup_reversal": ("Customer SSR Markup Reversal", "cust_ssr_markup_reversal"),
    "supp_markup_reversal": ("Supplier Markup Reversal", "supp_markup_reversal"),
    "supp_addl_markup_reversal": ("Supplier Additional Markup Reversal", "supp_addl_markup_reversal"),
    "supp_ssr_markup_reversal": ("Supplier SSR Markup Reversal", "supp_ssr_markup_reversal"),
}
PENALTY_PARAMS = ("supplier_penalty", "agent_penalty", "penalty_amount")
REVERSAL_PARAMS = (
    "cust_markup_reversal", "cust_addl_markup_reversal", "cust_ssr_markup_reversal",
    "supp_markup_reversal", "supp_addl_markup_reversal", "supp_ssr_markup_reversal",
)
# The Agent's own GST amounts -> the line's GST amount names
# (models.GST_AMOUNT_FIELDS). Saved as sent, never re-checked against the
# Ledger Mapping GST % (that check is for manual entry); left "" = the
# software works it out from the % as usual.
GST_AMOUNTS = {
    "cust_service_fee_gst": "service_fee_gst", "cust_addl_service_fee_gst": "addl_service_fee_gst",
    "cust_ssr_service_fee_gst": "ssr_service_fee_gst", "supp_service_fee_gst": "supp_service_fee_gst",
    "supp_addl_service_fee_gst": "supp_addl_service_fee_gst", "supp_ssr_service_fee_gst": "supp_ssr_service_fee_gst",
}
# One parameter list for all three Booking Statuses: a Reschedule /
# Cancellation carries its own full values, exactly like a Confirm -
# nothing is copied from the ticket it changes (that ticket is only used to
# check the push and to link the passenger). A value that does not apply is
# sent as "".
_REQUIRED_HEADER_ALL = ("booking_type", "customer_id", "travel_type", "booking_reference", "booking_ref_date",
                        "airline_pnr", "payment_mode", "fop")
REQUIRED_HEADER = {
    "Confirmed": _REQUIRED_HEADER_ALL,
    "Rescheduled": _REQUIRED_HEADER_ALL + ("parent_pnr",),
    "Cancelled": _REQUIRED_HEADER_ALL + ("parent_pnr",),
}
_REQUIRED_PAX_ALL = ("ticket_no", "pax_name", "pax_type", "airline_category", "sector", "airline_code", "travel_date",
                     "flight_no", "cabin", "fare_type", "office_id", "basic_fare")
REQUIRED_PAX = {status: _REQUIRED_PAX_ALL for status in ("Confirmed", "Rescheduled", "Cancelled")}
# SSR Updation: extra SSR sold on a ticket. parent_pnr = the Booking Reference
# of that ticket's live booking / reschedule (a ticket not in this software
# = a direct SSR, saved with that Parent PNR, like a direct Reschedule);
# booking_reference = the SSR's own reference (SSR Reference on the screen -
# may repeat); ticket_no = the ticket the SSR is for, one row per passenger +
# sector. Flight details (airline_code, travel_date, ...) are optional - the
# SSR line keeps only the sector. At least one SSR Details is required.
REQUIRED_HEADER["SSR"] = ("customer_id", "travel_type", "booking_reference", "booking_ref_date", "airline_pnr",
                          "payment_mode", "fop", "parent_pnr")
REQUIRED_PAX["SSR"] = ("ticket_no", "pax_name", "pax_type", "airline_category", "sector", "office_id")
# Parameters that belong to another Booking Status - a value (other than
# blank / 0) is refused, so it is never silently dropped.
NOT_ALLOWED = {
    "Confirmed": ("parent_pnr", "original_ticket_no") + PENALTY_PARAMS + REVERSAL_PARAMS,
    "Rescheduled": REVERSAL_PARAMS,
    "Cancelled": ("original_ticket_no",),
    # SSR line amounts are only the SSR charges + SSR Markup / Service Fee (+ their GST).
    "SSR": ("original_ticket_no", "basic_fare", "yq_tax", "yr_tax", "k3_tax", "tax_others",
            "cust_discount_amount", "cust_tds_amount", "cust_markup", "cust_addl_markup", "cust_service_fee",
            "cust_addl_service_fee", "cust_service_fee_gst", "cust_addl_service_fee_gst",
            "supp_commission_amount", "supp_tds_amount", "supp_markup", "supp_addl_markup", "supp_service_fee",
            "supp_addl_service_fee", "supp_service_fee_gst", "supp_addl_service_fee_gst") + PENALTY_PARAMS + REVERSAL_PARAMS,
}
# SSR line field <- the passenger's SSR Markup / Service Fee (AMOUNT_PARAMS field).
SSR_LINE_AMOUNTS = {"seat": "seat", "meal": "meal", "baggage": "baggage", "other_ssr": "other_ssr",
                    "markup": "ssr_markup", "service_fee": "ssr_service_fee",
                    "supp_markup": "supp_ssr_markup", "supp_service_fee": "supp_ssr_service_fee"}
# The SSR GST the Agent sends must be the SSR Service Fee x the mapped ledger's GST %
# (the SSR Updation J.V always works it out from that %).
SSR_GST = (("ssr_service_fee", "ssr_service_fee_gst", "cust_ssr_service_fee_gst", "SSR Service Fee A/c"),
           ("supp_ssr_service_fee", "supp_ssr_service_fee_gst", "supp_ssr_service_fee_gst", "Supplier SSR Service Fee A/c"))

# ---------------------------------------------------------------------------
# What the screens save (internal field names - Ticket Entry / staging).
# ---------------------------------------------------------------------------
HEADER_TEXT = {
    "branch_name": 100, "invoice_number": 20, "invoice_type": 100, "booking_type": 50,
    "customer_name": 150, "supplier_name": 150, "travel_type": 20, "user_name": 100, "currency": 5,
    "booking_given_by": 25, "booking_reference": 30, "airline_pnr": 13, "gds_pnr": 13, "office_id": 30,
    "payment_mode": 20, "payment_gateway_ref": 60, "airline_category": 5,
}
HEADER_DATES = ("invoice_date", "booking_ref_date")
HEADER_NUMBERS = ("roe",)
PAX_TEXT = {
    "original_ticket_no": 30, "airline_code": 200, "airline_name": 200, "airline_category": 5, "flight_no": 200,
    "ticket_no": 30, "passenger_name": 50, "pax_type": 10, "sector": 200, "travel_date": 200, "cabin": 200,
    "travel_class": 200, "fare_type": 300, "supplier_name": 150, "office_id": 30, "fop": 20, "card_number": 40,
    "status": 15, "disc_on": 20, "disc_type": 12, "supp_comm_on": 20, "supp_comm_type": 12,
    "source_record_id": 100,
}
PAX_AMOUNTS = (
    "basic_fare", "yq", "yr", "k3_tax", "tax_others", "seat", "meal", "baggage", "other_ssr",
    "disc_value", "tds_per", "pg_charges", "pg_charges_percentage", "markup", "addl_markup", "ssr_markup",
    "service_fee", "addl_service_fee", "ssr_service_fee", "gst_pct",
    "supp_comm_value", "supp_tds_per", "supp_markup", "supp_addl_markup", "supp_ssr_markup",
    "supp_service_fee", "supp_addl_service_fee", "supp_ssr_service_fee", "supp_gst_pct",
    "agent_penalty", "reschedule_penalty", "supplier_penalty", "cancellation_penalty",
    "cust_markup_reversal", "cust_addl_markup_reversal", "cust_ssr_markup_reversal",
    "supp_markup_reversal", "supp_addl_markup_reversal", "supp_ssr_markup_reversal",
)
PAX_OPTIONAL_AMOUNTS = ("tds_amount_override", "supp_tds_amount_override", "total_billed")
# Passenger fields kept in a differently named staging column (the header has one of the same name).
PAX_TO_STAGING = {
    "airline_category": "line_airline_category", "office_id": "line_office_id",
    "supplier_name": "line_supplier_name", "status": "line_status",
}

# Markup Reversal -> the markup charged on the ticket it reverses (chain totals).
REVERSAL_LIMITS = {
    "cust_markup_reversal": ("markup", "Customer Markup"),
    "cust_addl_markup_reversal": ("addl_markup", "Customer Additional Markup"),
    "cust_ssr_markup_reversal": ("ssr_markup", "Customer SSR Markup"),
    "supp_markup_reversal": ("supp_markup", "Supplier Markup"),
    "supp_addl_markup_reversal": ("supp_addl_markup", "Supplier Additional Markup"),
    "supp_ssr_markup_reversal": ("supp_ssr_markup", "Supplier SSR Markup"),
}

DATA_DIR = Path(settings.BASE_DIR).parent / "assets" / "data"
ALNUM = re.compile(r"^[A-Za-z0-9]+$")
SECTOR_PAIR = re.compile(r"^([A-Z]{3})-([A-Z]{3})$")
FLIGHT_NO = re.compile(r"^[A-Za-z0-9]{2,3}[ -]?[0-9]{1,5}[A-Za-z]?$")
CLASS_TEXT = re.compile(r"^[A-Za-z][A-Za-z ]{0,19}$")
DATE_DMY = re.compile(r"^\d{2}/\d{2}/\d{4}$")


class ImportRejected(Exception):
    """The document itself is wrong (bad data / missing master) - retrying won't help.
    problems: error-log entries (see _Problems.add); error_type: for a plain message."""

    def __init__(self, message, problems=None, error_type="Save Failed"):
        super().__init__(message)
        self.problems = problems or []
        self.error_type = error_type


# ==========================================================================
# 1. Masters the values are checked against
# ==========================================================================

_xml_cache = {}


def _xml_records(filename, record_tag, fields):
    """[(field values...)] from one of assets/data/*.xml - re-read only when the file changes."""
    path = DATA_DIR / filename
    stamp = path.stat().st_mtime
    hit = _xml_cache.get(filename)
    if hit and hit[0] == stamp:
        return hit[1]
    records = [
        tuple((el.findtext(f) or "").strip() for f in fields)
        for el in ET.parse(path).getroot().iter(record_tag)
    ]
    _xml_cache[filename] = (stamp, records)
    return records


def _airline_names():
    """{airline code: name} - Airlinenames.xml, the same list (and clean-up) as the Sector modal."""
    out = {}
    for code, name in _xml_records("Airlinenames.xml", "AIRLINEDET", ("_CODE", "_NAME")):
        code = code.upper().rstrip("*")
        if code and name and code not in out:
            out[code] = name
    return out


def _airport_codes():
    return {code.upper() for (code,) in _xml_records("cityairport_lst.xml", "AIR", ("ID",)) if code}


def _ssr_doc_ref(reference, doc):
    """
    doc_ref of an SSR invoice: its Booking Reference may repeat (several SSR
    Updations on one booking), so the reference + a fingerprint of what the SSR
    is (ticket, sector, EMD Ticket Nos, SSR Details). The same SSR pushed again
    is then a duplicate; another SSR with the same reference is a new invoice.
    """
    parts = []
    for pax in doc.get("passengers") or []:
        if isinstance(pax, dict):
            parts.append("|".join(str(pax.get(k) or "").strip().upper()
                                  for k in ("ticket_no", "sector", *SSR_TEXT_PARAMS)))
    digest = hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()[:10].upper()
    return f"{reference}-{digest}"


def _norm_card(value):
    return re.sub(r"[\s-]", "", str(value or "")).upper()


class _Masters:
    """One company's masters, read once per push."""

    def __init__(self, company_id):
        self.company_id = company_id

    @cached_property
    def dropdowns(self):
        """{list_key: {CODE: name}} - AirlineDropdownValues (active values)."""
        out = {}
        for r in sp_client.airline_dropdown_list():
            if r.get("code"):
                out.setdefault(r["list_key"], {})[str(r["code"]).strip().upper()] = r["name"]
        return out

    @cached_property
    def customers(self):
        return {str(r["agent_id"]).strip().upper(): r for r in sp_client.customers_list(self.company_id) if r.get("agent_id")}

    @cached_property
    def suppliers(self):
        out = {}
        for r in sp_client.suppliers_list(self.company_id):
            if (r.get("office_id") or "").strip():
                out.setdefault(r["office_id"].strip().upper(), []).append(r)
        return out

    @cached_property
    def gateways(self):
        return {r["gateway_name"].strip().upper(): r for r in sp_client.pg_master_list(self.company_id)}

    @cached_property
    def cards(self):
        out = {}
        for r in sp_client.fop_master_list(self.company_id):
            out.setdefault(_norm_card(r["card_number"]), []).append(r)
        return out

    @cached_property
    def invoice_types(self):
        return sp_client.ticket_import_invoice_types(self.company_id)

    @cached_property
    def airlines(self):
        return _airline_names()

    @cached_property
    def airports(self):
        return _airport_codes()

    def mapping(self, field_name, on_date):
        return models.resolve_mapping(self.company_id, field_name, on_date)


# ==========================================================================
# 2. Checking one pushed invoice
# ==========================================================================

def _blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _shown(value):
    """A received value as text, for messages and the error log."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, float):
        return f"{value:.2f}" if value == round(value, 2) else repr(value)
    return json.dumps(value, default=str)


def _money(value):
    return f"{value:,.2f}"


def _round2(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class _Problems:
    """Problems found in one invoice - each becomes an error log row."""

    def __init__(self):
        self.items = []

    def add(self, error_type, field, label, message, received=None, expected=None, pax=None, severity="Error"):
        self.items.append({
            "passenger_no": pax, "field_name": field, "field_label": label, "received_value": _shown(received),
            "expected_value": _shown(expected), "error_type": error_type, "severity": severity, "error_message": message,
        })

    @property
    def errors(self):
        return [p for p in self.items if p["severity"] == "Error"]


class _DocumentCheck:
    """
    Checks one pushed invoice (header + passengers) against the masters and
    builds the values the screens save. cleaned is None when there is any
    error; problems lists every error / warning found (all of them, not just
    the first).
    """

    def __init__(self, doc, masters, today):
        self.doc, self.masters, self.today = doc, masters, today
        self.problems = _Problems()
        self.status = None
        self.context = {}
        self.common_fop = {}

    # ---- single values -------------------------------------------------
    def _text(self, src, key, label, max_len, pax=None, pattern=None, rule=None):
        value = src.get(key)
        if _blank(value):
            return None
        if isinstance(value, (dict, list, bool)):
            self.problems.add("Invalid Format", key, label, f"{label} must be text.", value, rule, pax)
            return None
        text = str(value).strip()
        if len(text) > max_len:
            self.problems.add("Invalid Format", key, label, f"{label} \"{text}\" is longer than {max_len} characters.",
                              value, f"at most {max_len} characters", pax)
            return None
        if pattern and not pattern.match(text):
            self.problems.add("Invalid Format", key, label, f"{label} \"{text}\" is not valid - {rule}.", value, rule, pax)
            return None
        return text

    def _code_text(self, value):
        if isinstance(value, bool) or isinstance(value, (dict, list)):
            return None
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return str(value).strip()

    def _codes(self, src, key, label, list_key, pax=None, exclude=()):
        """Names of the comma-separated codes in src[key] (one code -> one name), or None."""
        value = src.get(key)
        if _blank(value):
            return None
        text = self._code_text(value)
        valid = {c: n for c, n in self.masters.dropdowns.get(list_key, {}).items() if c not in exclude}
        listing = ", ".join(f"{c} = {n}" for c, n in valid.items())
        if text is None:
            self.problems.add("Invalid Format", key, label, f"{label} must be a code ({listing}).", value, listing, pax)
            return None
        names = []
        for code in [c.strip() for c in text.split(",")]:
            name = valid.get(code.upper())
            if name is None:
                self.problems.add(
                    "Not Mapped", key, label,
                    f"{label} code \"{code}\" is not in our {label} drop down (AirlineDropdownValues) - valid codes: {listing}.",
                    code, listing, pax,
                )
                return None
            names.append(name)
        return names

    def _code(self, src, key, label, list_key, pax=None, exclude=()):
        value = src.get(key)
        if not _blank(value) and "," in (self._code_text(value) or ""):
            self.problems.add("Invalid Format", key, label, f"{label} takes one code only.", value, None, pax)
            return None
        names = self._codes(src, key, label, list_key, pax, exclude)
        return names[0] if names else None

    def _date(self, src, key, label, pax=None):
        value = src.get(key)
        if _blank(value):
            return None
        text = str(value).strip()
        try:
            if not DATE_DMY.match(text):
                raise ValueError
            return datetime.strptime(text, "%d/%m/%Y").date()
        except ValueError:
            self.problems.add("Invalid Format", key, label,
                              f"{label} \"{text}\" is not a valid date - send dd/mm/yyyy (e.g. 26/10/2026).",
                              value, "dd/mm/yyyy", pax)
            return None

    def _amount(self, src, key, label, pax=None):
        value = src.get(key)
        if _blank(value):
            return None
        rule = "a number, 0 or more, at most 2 decimals"
        if isinstance(value, (bool, dict, list)):
            self.problems.add("Invalid Format", key, label, f"{label} must be a number only.", value, rule, pax)
            return None
        try:
            number = Decimal(str(value).strip())
            if not number.is_finite():
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            self.problems.add("Invalid Format", key, label, f"{label} \"{value}\" is not a number - send numbers only.",
                              value, rule, pax)
            return None
        if number < 0:
            self.problems.add("Invalid Format", key, label, f"{label} {value} is negative - send 0 or more.", value, rule, pax)
            return None
        if number != number.quantize(Decimal("0.01")):
            self.problems.add("Invalid Format", key, label, f"{label} {value} has more than 2 decimals.", value, rule, pax)
            return None
        if number >= Decimal("1000000000000"):
            self.problems.add("Invalid Format", key, label, f"{label} {value} is too large.", value, rule, pax)
            return None
        return float(number)

    def _missing(self, key, label, pax=None, why=""):
        self.problems.add("Missing", key, label, f"{label} is missing{why}.", None, "a value (required)", pax)

    def _not_allowed(self, src, keys, labels, why, pax=None):
        for key in keys:
            value = src.get(key)
            if _blank(value) or (key in AMOUNT_PARAMS and self._is_zero(value)):
                continue
            label = labels.get(key) or AMOUNT_PARAMS[key][0]
            self.problems.add("Not Allowed", key, label, f"{label} is not allowed {why} - send it empty.", value, "empty", pax)

    @staticmethod
    def _is_zero(value):
        try:
            return Decimal(str(value).strip()) == 0
        except (InvalidOperation, ValueError):
            return False

    # ---- the invoice ----------------------------------------------------
    def run(self):
        doc = self.doc
        if not isinstance(doc, dict):
            self.problems.add("Invalid Format", None, "Invoice", "Each invoice must be a JSON object.", doc)
            return None
        self.context = {
            "booking_status": _shown(doc.get("booking_status")), "booking_reference": _shown(doc.get("booking_reference")),
            "parent_pnr": _shown(doc.get("parent_pnr")), "customer_id": _shown(doc.get("customer_id")),
        }
        for key, value in doc.items():
            if key not in HEADER_PARAMS:
                self.problems.add("Unknown Field", key, key,
                                  f"\"{key}\" is not an Auto Push parameter - it was ignored (check the spelling).",
                                  value, None, None, "Warning")

        if _blank(doc.get("booking_status")):
            self._missing("booking_status", "Booking Status")
        name = self._code(doc, "booking_status", "Booking Status", "bookingStatuses")
        self.status = STATUS_BY_NAME.get(name)
        if not self.status:
            return None   # what is required depends on it

        header = self._header(doc)
        passengers = self._passengers(doc, header)
        if self.problems.errors:
            return None
        doc_ref = header.get("booking_reference") if self.status != "Cancelled" else passengers[0]["original_ticket_no"]
        if self.status == "SSR":
            doc_ref = _ssr_doc_ref(doc_ref, doc)
        return {"ticket_status": self.status, "doc_ref": doc_ref, "header": header, "passengers": passengers}

    def doc_ref_guess(self):
        """doc_ref of an invoice that was rejected - to tie its error log rows to a later good push."""
        if not self.status or not isinstance(self.doc, dict):
            return None
        if self.status == "Cancelled":
            pax = (self.doc.get("passengers") or [None])[0]
            return _shown(pax.get("ticket_no")) if isinstance(pax, dict) and not _blank(pax.get("ticket_no")) else None
        ref = self.doc.get("booking_reference")
        if _blank(ref) or not ALNUM.match(str(ref).strip()):
            return None
        return _ssr_doc_ref(str(ref).strip(), self.doc) if self.status == "SSR" else str(ref).strip()

    def _header(self, doc):
        status, header = self.status, {}
        for key in REQUIRED_HEADER[status]:
            if _blank(doc.get(key)):
                self._missing(key, HEADER_PARAMS[key], why=f" - it is required for a {status} ticket")
        self._not_allowed(doc, [k for k in NOT_ALLOWED[status] if k in HEADER_PARAMS], HEADER_PARAMS,
                          f"for a {status} ticket")

        booking_type = self._code(doc, "booking_type", "Booking Type", "bookingTypes", exclude=("SSR",))
        if booking_type:
            header["booking_type"] = booking_type

        customer_id = self._text(doc, "customer_id", "Customer ID", 30)
        if customer_id:
            customer = self.masters.customers.get(customer_id.upper())
            if customer is None:
                self.problems.add("Not Mapped", "customer_id", "Customer ID",
                                  f"Customer ID \"{customer_id}\" is not mapped to any customer ledger under Sundry Debtors "
                                  f"(Agent ID in the Customer master).", customer_id, "Agent ID of a Sundry Debtors ledger")
            else:
                header["customer_name"] = customer["name"]

        travel_type = self._code(doc, "travel_type", "Travel Type", "travelTypes")
        if travel_type:
            header["travel_type"] = travel_type
        for key, max_len in (("user_name", 100), ("booking_given_by", 25)):
            text = self._text(doc, key, HEADER_PARAMS[key], max_len)
            if text:
                header[key] = text

        alnum_rule = "letters and numbers only, at most {} characters"
        reference = self._text(doc, "booking_reference", "Booking Reference", 10, pattern=ALNUM, rule=alnum_rule.format(10))
        if reference:
            header["booking_reference"] = reference
        parent_pnr = self._text(doc, "parent_pnr", "Parent PNR", 10, pattern=ALNUM, rule=alnum_rule.format(10))
        if status == "Rescheduled" and reference and parent_pnr and reference.upper() == parent_pnr.upper():
            self.problems.add("Mismatch", "booking_reference", "Booking Reference",
                              f"Booking Reference \"{reference}\" is the same as the Parent PNR - a reschedule needs its own new "
                              f"Booking Reference.", reference, f"a new reference, not {parent_pnr}")
        self.context["parent_pnr_clean"] = parent_pnr

        ref_date = self._date(doc, "booking_ref_date", "Booking Ref Date")
        if ref_date and ref_date > self.today:
            self.problems.add("Invalid Format", "booking_ref_date", "Booking Ref Date",
                              f"Booking Ref Date {ref_date:%d/%m/%Y} is after today ({self.today:%d/%m/%Y}).",
                              doc.get("booking_ref_date"), f"on or before {self.today:%d/%m/%Y}")
        elif ref_date:
            header["booking_ref_date"] = ref_date.isoformat()
        for key in ("airline_pnr", "gds_pnr"):
            text = self._text(doc, key, HEADER_PARAMS[key], 13, pattern=ALNUM, rule=alnum_rule.format(13))
            if text:
                header[key] = text

        self._payment(doc, header)
        # FOP / Card Number - one for the whole invoice, given to every passenger.
        self.common_fop = {}
        self._fop(doc, None, self.common_fop)

        chosen = self.masters.invoice_types.get(status)
        if chosen is None:
            self.problems.add("Not Mapped", "invoice_type", "Invoice Type",
                              f"No Invoice Type is selected for Auto Push {status} tickets - pick one in Masters > Voucher Type "
                              f"(Auto Push Invoice For).", None, "an Invoice Type picked for this Booking Status")
        elif not chosen["is_active"]:
            self.problems.add("Not Mapped", "invoice_type", "Invoice Type",
                              f"Invoice Type \"{chosen['voucher_type_name']}\" picked for Auto Push {status} tickets is "
                              f"inactive in Masters > Voucher Type.", chosen["voucher_type_name"], "an active Invoice Type")
        else:
            header["invoice_type"] = chosen["voucher_type_name"]
        header["invoice_date"] = self.today.isoformat()
        return header

    def _payment(self, doc, header):
        mode = self._code(doc, "payment_mode", "Payment Mode", "paymentModes")
        gateway_ref = doc.get("gateway_ref")
        if mode:
            header["payment_mode"] = mode
        if mode == "Payment Gateway":
            if _blank(gateway_ref):
                self._missing("gateway_ref", "Gateway Ref", why=" - it is required when Payment Mode is Payment Gateway (2)")
                return
            text = self._text(doc, "gateway_ref", "Gateway Ref", 60)
            if not text:
                return
            gateway = self.masters.gateways.get(text.upper())
            names = ", ".join(r["gateway_name"] for r in self.masters.gateways.values() if r["is_active"])
            if gateway is None:
                self.problems.add("Not Mapped", "gateway_ref", "Gateway Ref",
                                  f"Gateway Ref \"{text}\" is not mapped to any Payment Gateway in PG Master (name must match "
                                  f"exactly) - PG Master has: {names or 'none'}.", text, names)
            elif not gateway["is_active"]:
                self.problems.add("Not Mapped", "gateway_ref", "Gateway Ref",
                                  f"Payment Gateway \"{gateway['gateway_name']}\" is inactive in PG Master.", text, names)
            else:
                header["payment_gateway_ref"] = gateway["gateway_name"]
        elif mode and not _blank(gateway_ref):
            self.problems.add("Not Allowed", "gateway_ref", "Gateway Ref",
                              f"Gateway Ref is not allowed when Payment Mode is {mode} - send it empty.", gateway_ref, "empty")

    def _passengers(self, doc, header):
        passengers = doc.get("passengers")
        if not isinstance(passengers, list) or not passengers:
            if _blank(passengers) or passengers == []:
                self._missing("passengers", "Passengers", why=" - send at least one passenger")
            else:
                self.problems.add("Invalid Format", "passengers", "Passengers", "Passengers must be a list of passengers.",
                                  passengers, "a non-empty list")
            return []
        out, seen_tickets = [], set()
        for n, pax in enumerate(passengers, 1):
            if not isinstance(pax, dict):
                self.problems.add("Invalid Format", "passengers", "Passengers", f"Passenger {n} must be an object.", pax, None, n)
                continue
            clean = self._passenger(pax, n)
            ticket = (clean.get("original_ticket_no") or "").upper()
            if ticket and self.status == "SSR":
                ticket = f"{ticket}|{clean.get('sector') or ''}"
            if ticket and ticket in seen_tickets:
                self.problems.add("Duplicate", "ticket_no", "Ticket No",
                                  f"Ticket No \"{clean['original_ticket_no']}\" is sent twice in this invoice"
                                  + (f" for sector {clean.get('sector')}." if self.status == "SSR" else "."),
                                  clean["original_ticket_no"], "one row per ticket" + (" and sector" if self.status == "SSR" else ""), n)
            seen_tickets.add(ticket)
            out.append(clean)
        # The invoice header carries the first passenger's Office ID / supplier and Airline Category.
        first = out[0] if out else {}
        for field in ("office_id", "supplier_name", "airline_category"):
            if first.get(field):
                header[field] = first[field]
        return out

    def _passenger(self, pax, n):
        status = self.status
        labels = {**PAX_TEXT_PARAMS, **{k: v[0] for k, v in AMOUNT_PARAMS.items()}}
        for key, value in pax.items():
            if key in INVOICE_ONLY_PARAMS:
                if not _blank(value):
                    self.problems.add("Not Allowed", key, HEADER_PARAMS[key],
                                      f"{HEADER_PARAMS[key]} is sent once for the whole invoice (top level, next to "
                                      f"payment_mode) - the same for every passenger, not inside a passenger.",
                                      value, "top level", n)
            elif key not in labels:
                self.problems.add("Unknown Field", key, key,
                                  f"\"{key}\" is not an Auto Push passenger parameter - it was ignored (check the spelling).",
                                  value, None, n, "Warning")
        for key in REQUIRED_PAX[status]:
            if _blank(pax.get(key)):
                self._missing(key, labels[key], n, f" - it is required for a {status} ticket")
        self._not_allowed(pax, [k for k in NOT_ALLOWED[status] if k in labels], labels, f"for a {status} ticket", n)

        line = {}
        ticket_no = self._text(pax, "ticket_no", "Ticket No", 30, n)
        original = self._text(pax, "original_ticket_no", "Original Ticket No", 30, n)
        if status == "Confirmed":
            line["ticket_no"] = ticket_no
        elif status == "Rescheduled":
            # ticket_no = the new ticket; original_ticket_no = the ticket being
            # rescheduled (left out = the same number).
            line["ticket_no"] = ticket_no
            line["original_ticket_no"] = original or ticket_no
        else:
            # the ticket being cancelled / the ticket the SSR is sold on
            line["original_ticket_no"] = ticket_no
        name = self._text(pax, "pax_name", "Pax Name", 50, n)
        if name:
            line["passenger_name"] = name
        pax_type = self._code(pax, "pax_type", "Pax Type", "paxTypes", n)
        if pax_type:
            line["pax_type"] = pax_type
        category = self._code(pax, "airline_category", "Airline Category", "airlineCategories", n)
        if category:
            line["airline_category"] = category

        self._segments(pax, n, line)
        self._supplier(pax, n, line)
        line.update(self.common_fop)
        self._amounts(pax, n, line)
        if status == "SSR":
            self._ssr(pax, n, line)
        else:
            for key, label in SSR_TEXT_PARAMS.items():
                if not _blank(pax.get(key)):
                    self.problems.add("Not Allowed", key, label,
                                      f"{label} is used only for an SSR Updation (Booking Status SSR) - it was ignored "
                                      f"for this {status} ticket.", pax.get(key), "empty", n, "Warning")
        return {k: v for k, v in line.items() if v is not None}

    def _ssr(self, pax, n, line):
        """SSR Updation: one sector per row, SSR Details per type (+ its EMD Ticket No), at least one."""
        if "," in (line.get("sector") or ""):
            self.problems.add("Invalid Format", "sector", "Sector",
                              f"Sector \"{line['sector']}\" has more than one segment - an SSR Updation row is one passenger "
                              f"on ONE sector: send one row per sector.", pax.get("sector"), "one sector, e.g. MAA-DEL", n)
        items, numbers, problems_before = {}, {}, len(self.problems.errors)
        for ssr_type, (emd_key, detail_key, charge_key) in SSR_PARAMS.items():
            detail = self._text(pax, detail_key, SSR_TEXT_PARAMS[detail_key], 100, n)
            emd = self._text(pax, emd_key, SSR_TEXT_PARAMS[emd_key], 30, n)
            if detail:
                items[ssr_type] = detail
            if emd:
                numbers[ssr_type] = emd
            charged = not _blank(pax.get(charge_key)) and not self._is_zero(pax.get(charge_key))
            if not detail and _blank(pax.get(detail_key)) and (emd or charged):
                why = f"{SSR_TEXT_PARAMS[emd_key]} is sent" if emd else f"{AMOUNT_PARAMS[charge_key][0]} is sent"
                self._missing(detail_key, SSR_TEXT_PARAMS[detail_key], n, f" - {why} for {ssr_type}")
        if not items and len(self.problems.errors) == problems_before:
            self._missing("ssr_baggage_details", "SSR Details", n,
                          " - send at least one: ssr_baggage_details, ssr_meal_details, ssr_seat_details or ssr_other_details")
        line["ssr_items"] = items
        line["ssr_ticket_numbers"] = numbers

    def _segments(self, pax, n, line):
        """Sector + the per-segment fields (comma separated, same order as the sectors)."""
        segments = None
        raw = pax.get("sector")
        if not _blank(raw):
            text = self._text(pax, "sector", "Sector", 200, n)
            if text:
                segments = []
                for part in [s.strip().upper() for s in text.split(",")]:
                    match = SECTOR_PAIR.match(part)
                    if not match or match.group(1) == match.group(2):
                        self.problems.add("Invalid Format", "sector", "Sector",
                                          f"Sector \"{part}\" is not valid - send Origin-Destination airport codes, e.g. "
                                          f"MAA-DEL (comma for a connecting trip: MAA-DEL,DEL-BOM).", raw, "AAA-BBB", n)
                        segments = None
                        break
                    unknown = [c for c in match.groups() if c not in self.masters.airports]
                    if unknown:
                        self.problems.add("Not Mapped", "sector", "Sector",
                                          f"Airport code {', '.join(unknown)} in Sector \"{part}\" is not in our airport list "
                                          f"(cityairport_lst.xml).", raw, "a 3-letter airport code from the list", n)
                        segments = None
                        break
                    segments.append(part)
        if segments:
            line["sector"] = ",".join(segments)
        count = len(segments) if segments else None

        def per_segment(key, label, values, allow_single):
            """values (one per segment), expanded from a single value when allowed - or None."""
            if values is None:
                return None
            if count and len(values) != count and not (allow_single and len(values) == 1):
                self.problems.add("Mismatch", key, label,
                                  f"{label} has {len(values)} value(s) but Sector has {count} segment(s) - send one per "
                                  f"segment, comma separated, in the same order.", pax.get(key), f"{count} value(s)", n)
                return None
            if count and len(values) == 1 and allow_single:
                values = values * count
            return values

        codes = None
        if not _blank(pax.get("airline_code")):
            text = self._text(pax, "airline_code", "Airline Code", 200, n)
            if text:
                codes = [c.strip().upper() for c in text.split(",")]
                unknown = [c for c in codes if c not in self.masters.airlines]
                if unknown:
                    self.problems.add("Not Mapped", "airline_code", "Airline Code",
                                      f"Airline Code {', '.join(unknown)} is not in our airline list (Airlinenames.xml).",
                                      pax.get("airline_code"), "an airline code from the list", n)
                    codes = None
        codes = per_segment("airline_code", "Airline Code", codes, True)
        if codes:
            line["airline_code"] = ",".join(codes)
            line["airline_name"] = ",".join(self.masters.airlines[c] for c in codes)

        dates = None
        if not _blank(pax.get("travel_date")):
            dates = []
            for part in str(pax.get("travel_date")).split(","):
                day = self._date({"travel_date": part.strip()}, "travel_date", "Travel Date", n)
                if day is None:
                    dates = None
                    break
                dates.append(day)
        dates = per_segment("travel_date", "Travel Date", dates, True)
        if dates:
            shown = [d.strftime("%d/%m/%Y") for d in dates]
            # Same as the Sector modal saves it: one date when every segment shares it.
            line["travel_date"] = shown[0] if len(set(shown)) == 1 else ",".join(shown)

        flights = None
        if not _blank(pax.get("flight_no")):
            text = self._text(pax, "flight_no", "Flight No", 200, n)
            if text:
                flights = [f.strip() for f in text.split(",")]
                bad = [f for f in flights if not FLIGHT_NO.match(f)]
                if bad:
                    self.problems.add("Invalid Format", "flight_no", "Flight No",
                                      f"Flight No \"{bad[0]}\" is not valid - send the airline code and number, e.g. 6E 1478.",
                                      pax.get("flight_no"), "e.g. 6E 1478, IX299", n)
                    flights = None
        flights = per_segment("flight_no", "Flight No", flights, False)
        if flights:
            line["flight_no"] = ",".join(flights)

        cabins = per_segment("cabin", "Cabin", self._codes(pax, "cabin", "Cabin", "cabinOptions", n), True)
        if cabins:
            line["cabin"] = ",".join(cabins)
        fares = per_segment("fare_type", "Fare Type", self._codes(pax, "fare_type", "Fare Type", "fareTypeOptions", n), True)
        if fares:
            line["fare_type"] = ",".join(fares)

        classes = None
        if not _blank(pax.get("class")):
            text = self._text(pax, "class", "Class", 200, n)
            if text:
                classes = [c.strip() for c in text.split(",")]
                bad = [c for c in classes if not CLASS_TEXT.match(c)]
                if bad:
                    self.problems.add("Invalid Format", "class", "Class",
                                      f"Class \"{bad[0]}\" is not valid - letters only (e.g. Y).", pax.get("class"), "letters", n)
                    classes = None
        classes = per_segment("class", "Class", classes, True)
        if classes:
            line["travel_class"] = ",".join(classes)

    def _supplier(self, pax, n, line):
        office_id = self._text(pax, "office_id", "Office ID", 30, n)
        if not office_id:
            return
        found = self.masters.suppliers.get(office_id.upper(), [])
        if not found:
            self.problems.add("Not Mapped", "office_id", "Office ID",
                              f"Office ID \"{office_id}\" is not mapped to any supplier ledger under Sundry Creditors "
                              f"(Office ID in Supplier Master).", office_id, "Office ID of a Sundry Creditors ledger", n)
        elif len(found) > 1:
            self.problems.add("Not Mapped", "office_id", "Office ID",
                              f"Office ID \"{office_id}\" is on more than one supplier ledger "
                              f"({', '.join(r['name'] for r in found)}) - keep it on one only.", office_id, "one ledger", n)
        else:
            line["office_id"] = found[0]["office_id"]
            line["supplier_name"] = found[0]["name"]

    def _fop(self, pax, n, line):
        fop = self._code(pax, "fop", "FOP", "fopOptions", n)
        card = pax.get("card_number")
        if fop:
            line["fop"] = fop
        if fop == "Cash":
            if not _blank(card):
                self.problems.add("Not Allowed", "card_number", "Card Number",
                                  "Card Number is not allowed when FOP is Cash (1) - send it empty.", card, "empty", n)
            return
        if fop not in ("Own Card", "Client Card"):
            return
        if _blank(card):
            self._missing("card_number", "Card Number", n, f" - it is required when FOP is {fop}")
            return
        text = self._text(pax, "card_number", "Card Number", 40, n)
        if not text:
            return
        rows = self.masters.cards.get(_norm_card(text), [])
        same_type = [r for r in rows if r["card_type"] == fop]
        on_file = ", ".join(r["card_number"] for r in sum(self.masters.cards.values(), []) if r["card_type"] == fop and r["is_active"])
        if not rows:
            self.problems.add("Not Mapped", "card_number", "Card Number",
                              f"Card Number \"{text}\" is not mapped in FOP Master - add it under {fop} first (FOP Master "
                              f"{fop}s: {on_file or 'none'}).", text, on_file, n)
        elif not same_type:
            self.problems.add("Mismatch", "card_number", "Card Number",
                              f"Card Number \"{text}\" is saved as {rows[0]['card_type']} in FOP Master, but FOP is {fop} - "
                              f"the card type must match.", text, f"a card saved as {fop} in FOP Master", n)
        elif not same_type[0]["is_active"]:
            self.problems.add("Not Mapped", "card_number", "Card Number",
                              f"Card Number \"{text}\" ({fop}) is inactive in FOP Master.", text, "an active card", n)
        else:
            line["card_number"] = same_type[0]["card_number"]

    def _amounts(self, pax, n, line):
        status = self.status
        amounts = {}
        for key, (label, _field) in AMOUNT_PARAMS.items():
            value = self._amount(pax, key, label, n)
            if value is not None:
                amounts[key] = value
        for key, (_label, field) in AMOUNT_PARAMS.items():
            if field and key in amounts:
                line[field] = amounts[key]
        if "penalty_amount" in amounts:
            line["reschedule_penalty" if status == "Rescheduled" else "cancellation_penalty"] = amounts["penalty_amount"]

        self._discount_and_tds(amounts, n, line, "cust_discount_amount", "Customer Discount Amount", "cust_tds_amount",
                               "Customer TDS Amount", "disc_type", "disc_value", "tds_per", "tds_amount_override")
        self._discount_and_tds(amounts, n, line, "supp_commission_amount", "Supplier Commission Amount", "supp_tds_amount",
                               "Supplier TDS Amount", "supp_comm_type", "supp_comm_value", "supp_tds_per",
                               "supp_tds_amount_override")
        pushed = {GST_AMOUNTS[k]: amounts[k] for k in GST_AMOUNTS if k in amounts}
        if pushed:
            line["gst_amounts"] = pushed

    def _discount_and_tds(self, amounts, n, line, base_key, base_label, tds_key, tds_label, type_field, value_field,
                          pct_field, override_field):
        """
        Discount / Commission Amount -> a Flat value (Discount On stays "Select").
        TDS Amount -> the TDS % of that amount (what Booking / Reschedule
        lines store); a Cancellation keeps the amount itself, like the screen.
        """
        base = amounts.get(base_key)
        tds = amounts.get(tds_key)
        if base:
            line[type_field] = "Flat"
            line[value_field] = base
        if not tds:
            if tds == 0 and self.status != "Cancelled":
                line[pct_field] = 0
            return
        if self.status == "Cancelled":
            line[override_field] = tds
            return
        if not base:
            self.problems.add("Mismatch", tds_key, tds_label,
                              f"{tds_label} {_money(tds)} is sent but {base_label} is 0 - TDS is worked out on the "
                              f"{base_label.split(' Amount')[0].lower()}.", tds, f"0 (no {base_label})", n)
            return
        if tds > base:
            self.problems.add("Mismatch", tds_key, tds_label,
                              f"{tds_label} {_money(tds)} is more than the {base_label} {_money(base)}.", tds,
                              f"at most {_money(base)}", n)
            return
        pct = _round2(tds / base * 100)
        if abs(_round2(base * pct / 100) - tds) > 0.01:
            self.problems.add("Mismatch", tds_key, tds_label,
                              f"{tds_label} {_money(tds)} is not a TDS % (2 decimals) of the {base_label} {_money(base)} - "
                              f"e.g. {pct}% gives {_money(_round2(base * pct / 100))}.", tds,
                              _money(_round2(base * pct / 100)), n)
            return
        line[pct_field] = pct


def _doc_key(company_id, source_system, status, doc_ref):
    """Same formula as Ticket_Import_Staging.doc_key."""
    return f"{status}|{company_id}|{source_system}|{doc_ref}"


def _staging_rows(company_id, source_system, doc, context, request_doc):
    rows = []
    request_passengers = request_doc.get("passengers") or []
    for i, pax in enumerate(doc["passengers"], 1):
        row = {
            "source_system": source_system, "doc_ref": doc["doc_ref"], "ticket_status": doc["ticket_status"],
            "company_id": company_id, **doc["header"],
            "raw_payload": json.dumps({
                "context": context, "header": doc["header"], "passenger": pax,
                "request_passenger": request_passengers[i - 1] if i <= len(request_passengers) else None,
            }, default=str),
        }
        for key, value in pax.items():
            if key not in ("gst_amounts", "ssr_items", "ssr_ticket_numbers"):   # kept in raw_payload only
                row[PAX_TO_STAGING.get(key, key)] = value
        row["source_record_id"] = f"{doc['ticket_status']}|{doc['doc_ref']}|{i}"
        rows.append(row)
    return rows


# ==========================================================================
# 3. Error log (dbo.Ticket_Import_Error_Log)
# ==========================================================================

def _log_problems(problems, base, stage):
    """Writes problems to the error log; base = the invoice's own details. Never fails the push."""
    rows = []
    for p in problems:
        pax_no = p.get("passenger_no")
        pax = (base.get("passengers") or {}).get(pax_no) or {}
        rows.append({
            "company_id": base.get("company_id"), "source_system": base.get("source_system"),
            "batch_id": base.get("batch_id"), "doc_key": base.get("doc_key"),
            "booking_status": base.get("booking_status"), "booking_reference": base.get("booking_reference"),
            "parent_pnr": base.get("parent_pnr"), "passenger_no": pax_no,
            "ticket_no": pax.get("ticket_no"), "passenger_name": pax.get("passenger_name"),
            "stage": stage, **p,
        })
    try:
        return sp_client.ticket_import_error_log_insert(rows)
    except Exception:  # noqa: BLE001 - the log must never stop the push itself
        logger.exception("could not write the ticket import error log")
        return 0


def _request_passengers(doc):
    """{1-based passenger no: {ticket_no, passenger_name}} as the Agent sent them - for the error log."""
    out = {}
    passengers = doc.get("passengers") if isinstance(doc, dict) else None
    for n, pax in enumerate(passengers if isinstance(passengers, list) else [], 1):
        if isinstance(pax, dict):
            out[n] = {"ticket_no": _shown(pax.get("ticket_no")), "passenger_name": _shown(pax.get("pax_name"))}
    return out


def _response_errors(problems):
    return [
        {"passenger_no": p["passenger_no"], "field": p["field_name"], "error_type": p["error_type"], "message": p["error_message"]}
        for p in problems
    ]


# ==========================================================================
# 4. Saving staged documents through the Ticket Entry views
# ==========================================================================

def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _drop_empty(value):
    """Removes None / "" keys at every level, so each view applies its own defaults for them."""
    if isinstance(value, dict):
        return {k: _drop_empty(v) for k, v in value.items() if v is not None and v != ""}
    if isinstance(value, list):
        return [_drop_empty(v) for v in value]
    return value


def _header(row):
    header = {f: row.get(f) for f in HEADER_TEXT}
    for f in HEADER_DATES + HEADER_NUMBERS:
        header[f] = row.get(f)
    return header


def _line(row):
    line = {f: row.get(PAX_TO_STAGING.get(f, f)) for f in PAX_TEXT if f != "source_record_id"}
    for f in PAX_AMOUNTS + PAX_OPTIONAL_AMOUNTS:
        line[f] = row.get(f)
    return line


def _payload(row):
    try:
        return json.loads(row.get("raw_payload") or "{}")
    except ValueError:
        return {}


def _inherit(target, source, keys, prefix=""):
    for k in keys:
        if target.get(k) in (None, ""):
            target[k] = source.get(prefix + k)


def _finish_header(header, ticket_status):
    header["invoice_date"] = header.get("invoice_date") or date.today()
    header["currency"] = header.get("currency") or "INR"
    header["roe"] = header.get("roe") or 1
    header["booking_mode"] = "Auto Push"
    header["booking_status"] = BOOKING_STATUS[ticket_status]


def _parents(company_id, rows, verb):
    """
    Live line of every passenger's original_ticket_no; all must be on one original booking.
    Returns (parents, original_ticket_id):
      ({}, None)       - a direct Reschedule / Cancellation: none of the tickets was ever in
                         this software (booked before it, or elsewhere) - saved on its own
                         with the Parent PNR it was sent with.
      (parents, None)  - the tickets are on a direct Reschedule (no booking in the software).
    A ticket that is here but no longer live (already rescheduled / cancelled) is refused.
    """
    wanted = [r["original_ticket_no"] for r in rows]
    parents = sp_client.ticket_import_resolve_parents(company_id, wanted)
    missing = [(i, t) for i, t in enumerate(wanted, 1) if t not in parents]
    if missing:
        known = sp_client.ticket_import_known_tickets(company_id, [t for _, t in missing])
        if not parents and not known:
            return {}, None
        problems = _Problems()
        for i, ticket in missing:
            field = "ticket_no" if verb == "cancel" else "original_ticket_no"
            if known.get(ticket) == "Cancellation":
                problems.add("Not Mapped", field, "Ticket No", f"Ticket No {ticket} is already cancelled - nothing to {verb}.",
                             ticket, "a live ticket", i)
            elif ticket in known:
                problems.add("Not Mapped", field, "Ticket No",
                             f"Ticket No {ticket} is no longer live (already rescheduled or cancelled) - nothing to {verb}. "
                             f"Send the ticket it was rescheduled to.", ticket, "a live ticket", i)
            else:
                problems.add("Not Mapped", field, "Ticket No",
                             f"Ticket No {ticket} is not in the software, but the other passengers' tickets are - send it "
                             f"as a separate document (it is then saved as a direct {verb}).", ticket, "a separate document", i)
        raise ImportRejected(" ".join(p["error_message"] for p in problems.items), problems.items, "Not Mapped")
    originals = {parents[t]["original_ticket_id"] for t in wanted}
    if len(originals) > 1:
        raise ImportRejected("These passengers belong to different original bookings - send one document per booking.",
                             error_type="Mismatch")
    original_ticket_id = originals.pop()
    if original_ticket_id is None and len({parents[t]["reschedule_ticket_id"] for t in wanted}) > 1:
        raise ImportRejected("These passengers are on different Reschedules - send one document per Reschedule.",
                             error_type="Mismatch")
    return parents, original_ticket_id


def _parent_pnr(rows):
    """The Parent PNR the document was sent with (kept on a direct Reschedule / Cancellation)."""
    return (_payload(rows[0]).get("context") or {}).get("parent_pnr_clean")


def _check_against_parent(rows, parents, verb):
    """Parent PNR and Customer ID sent with a Reschedule / Cancellation must be the ticket's own."""
    problems = _Problems()
    context = _payload(rows[0]).get("context") or {}
    header = _payload(rows[0]).get("header") or {}
    parent_pnr = context.get("parent_pnr_clean")
    for i, r in enumerate(rows, 1):
        parent = parents[r["original_ticket_no"]]
        live_ref = parent.get("h_booking_reference") or ""
        if parent_pnr and parent_pnr.upper() != live_ref.upper():
            problems.add("Mismatch", "parent_pnr", "Parent PNR",
                         f"Parent PNR \"{parent_pnr}\" does not match ticket {r['original_ticket_no']} - it is on Booking "
                         f"Reference \"{live_ref}\" (the ticket being {verb}d).", parent_pnr, live_ref, i)
        if header.get("customer_name") and header["customer_name"] != parent.get("h_customer_name"):
            problems.add("Mismatch", "customer_id", "Customer ID",
                         f"Customer ID \"{context.get('customer_id')}\" is customer \"{header['customer_name']}\", but ticket "
                         f"{r['original_ticket_no']} belongs to \"{parent.get('h_customer_name')}\".",
                         context.get("customer_id"), parent.get("h_customer_name"), i)
    if problems.items:
        raise ImportRejected(" ".join(p["error_message"] for p in problems.items), problems.items, "Mismatch")


def _cancellation_chain_totals(company_id, parents):
    """{original_ticket_line_id: chain totals} - the same cancellation_fare_totals call the Cancellation screen makes."""
    status_code, data = _call_view(views.cancellation_fare_totals, {
        "company_id": company_id,
        "lines": [{
            "original_ticket_line_id": p["original_ticket_line_id"],
            "reschedule_line_id": p["live_line_id"] if p["parent_kind"] == "Reschedule" else None,
        } for p in parents],
    }, None)
    if status_code != 200:
        raise ImportRejected(data.get("error") or "Could not read the fares of the ticket being cancelled.")
    totals = {}
    for t in data.get("totals", []):
        if t.get("error"):
            raise ImportRejected(t["error"])
        totals[t["original_ticket_line_id"]] = t
    return totals


def _cancellation_total(company_id, on_date, line, pushed_gst=None):
    """Total of a cancelled passenger - the Cancellation screen's own computeFareLine formula
    (each GST: the amount the Agent sent, else fee x mapped GST %)."""
    pushed_gst = pushed_gst or {}

    def num(field):
        return float(line.get(field) or 0)

    def gst_of(fee_field, field_name):
        sent = pushed_gst.get(models.GST_AMOUNT_FIELDS[fee_field])
        if sent is not None:
            return float(sent)
        return num(fee_field) * models.mapped_gst_pct(company_id, field_name, on_date) / 100

    supplier_cost = sum(num(f) for f in ("basic_fare", "yq", "yr", "k3_tax", "tax_others", "seat", "meal", "baggage", "other_ssr"))
    discount = num("disc_value") if line.get("disc_type") == "Flat" else 0
    tds = num("tds_amount_override") if line.get("tds_amount_override") is not None else discount * num("tds_per") / 100
    gst = (gst_of("service_fee", "Service Fee A/c") + gst_of("addl_service_fee", "Addl Service Fee A/c")
           + gst_of("ssr_service_fee", "SSR Service Fee A/c"))
    # Same terms as CancellationAirlineTicketLine.computed_supp_gst.
    supp_gst = gst_of("supp_service_fee", "Supplier Service Fee A/c") + gst_of("supp_addl_service_fee", "Supplier Addl Service Fee A/c")
    total = (supplier_cost - discount + tds + num("markup") + num("addl_markup") + num("ssr_markup")
             + num("service_fee") + num("addl_service_fee") + num("ssr_service_fee") + gst
             + num("supp_markup") + num("supp_addl_markup") + num("supp_ssr_markup")
             + num("supp_service_fee") + num("supp_addl_service_fee") + num("supp_ssr_service_fee") + supp_gst)
    return _round2(total)


def _booking_payload(company_id, rows):
    header = _header(rows[0])
    _finish_header(header, "Confirmed")
    lines = []
    for r in rows:
        line = _line(r)
        _inherit(line, header, ("airline_category", "office_id", "supplier_name"))
        lines.append(line)
    return views.ticket_create, {"company_id": company_id, **header, "lines": lines}


def _reschedule_payload(company_id, rows):
    """
    Every value from the push itself; the live ticket only links each passenger (and is checked against).
    No booking in the software = a direct Reschedule: nothing to link, the Parent PNR sent is kept.
    """
    parents, original_ticket_id = _parents(company_id, rows, "reschedule")
    if parents:
        _check_against_parent(rows, parents, "reschedule")
    header = _header(rows[0])
    _finish_header(header, "Rescheduled")
    lines = []
    for r in rows:
        line = _line(r)
        _inherit(line, header, ("airline_category", "office_id", "supplier_name"))
        line["ticket_no"] = line.get("ticket_no") or r["original_ticket_no"]
        if original_ticket_id:
            # Same ids the Reschedule screen sends: the TRUE original booking
            # line, plus the live reschedule line when this one chains off it.
            parent = parents[r["original_ticket_no"]]
            line["original_ticket_line_id"] = parent["original_ticket_line_id"]
            line["reschedule_line_id"] = parent["live_line_id"] if parent["parent_kind"] == "Reschedule" else None
        lines.append(line)
    if not original_ticket_id:
        return views.reschedule_ticket_create, {
            "company_id": company_id, "parent_pnr": _parent_pnr(rows), **header, "lines": lines,
        }
    return views.reschedule_ticket_create, {
        "company_id": company_id, "original_ticket_id": original_ticket_id, **header, "lines": lines,
    }


def _cancellation_payload(company_id, rows):
    """
    Every value from the push itself. No booking in the software = a direct Cancellation:
    the Parent PNR sent is kept (and, when the ticket is on a direct Reschedule, that
    reschedule line is marked cancelled).
    """
    parents, original_ticket_id = _parents(company_id, rows, "cancel")
    first = None
    if parents:
        _check_against_parent(rows, parents, "cancel")
        sources = {parents[r["original_ticket_no"]]["reschedule_ticket_id"] for r in rows}
        if len(sources) > 1:
            raise ImportRejected(
                "Some of these passengers are on a reschedule and some on the original booking - send them as separate documents.",
                error_type="Mismatch",
            )
        first = parents[rows[0]["original_ticket_no"]]
    header = _header(rows[0])
    _finish_header(header, "Cancelled")
    cancellation_reference = header.pop("booking_reference")
    cancellation_ref_date = header.pop("booking_ref_date")

    # Every value from the push itself. The chain totals (what the ticket
    # carried over booking + reschedules) are read only to check the reversals.
    # (Direct: there is no booking to read - the reversals are taken as sent.)
    chain_totals = _cancellation_chain_totals(company_id, [parents[r["original_ticket_no"]] for r in rows]) if original_ticket_id else {}
    problems = _Problems()
    lines = []
    for i, r in enumerate(rows, 1):
        parent = parents.get(r["original_ticket_no"])
        line = _line(r)
        _inherit(line, header, ("airline_category", "office_id", "supplier_name"))
        line["ticket_no"] = r["original_ticket_no"]
        line["total_billed"] = _cancellation_total(company_id, header["invoice_date"], line, _pushed_gst(r))
        if parent:
            # The live line's own id (a reschedule line when the passenger was
            # rescheduled) - the same "line_id" the Cancellation screen sends.
            line["line_id"] = parent["live_line_id"]
        lines.append(line)
        if not original_ticket_id:
            continue
        totals = chain_totals[parent["original_ticket_line_id"]]
        # A Markup Reversal can't reverse more than the markup charged on the ticket.
        for field, (charged_field, charged_label) in REVERSAL_LIMITS.items():
            reversal, charged = float(line.get(field) or 0), float(totals.get(charged_field) or 0)
            if reversal > charged + 0.005:
                label = AMOUNT_PARAMS[field][0]
                problems.add("Mismatch", field, label,
                             f"{label} {_money(reversal)} is more than the {charged_label} charged on ticket "
                             f"{r['original_ticket_no']} ({_money(charged)}).", reversal, f"at most {_money(charged)}", i)
    if problems.items:
        raise ImportRejected(" ".join(p["error_message"] for p in problems.items), problems.items, "Mismatch")
    return views.cancellation_ticket_create, {
        "company_id": company_id, "original_ticket_id": original_ticket_id, "parent_pnr": _parent_pnr(rows),
        "source_reschedule_ticket_id": first["reschedule_ticket_id"] if first else None, **header,
        "cancellation_reference": cancellation_reference, "cancellation_ref_date": cancellation_ref_date,
        "lines": lines,
    }


def _ssr_parents(company_id, rows):
    """
    The live line of every SSR passenger's ticket, like _parents(): a ticket
    rescheduled here links to its live reschedule line. Returns {} for a direct
    SSR - none of the tickets was ever in this software (booked before it, or
    elsewhere): saved with the Parent PNR it was sent with. A ticket on a direct
    Reschedule links to that reschedule line (no original booking).
    """
    wanted = list(dict.fromkeys(r["original_ticket_no"] for r in rows))
    parents = sp_client.ticket_import_resolve_parents(company_id, wanted)
    problems = _Problems()
    missing = [t for t in wanted if t not in parents]
    known = sp_client.ticket_import_known_tickets(company_id, missing) if missing else {}
    if missing and not parents and not known:
        return {}
    for i, r in enumerate(rows, 1):
        ticket = r["original_ticket_no"]
        if ticket in parents:
            continue
        elif known.get(ticket) == "Cancellation":
            problems.add("Not Mapped", "ticket_no", "Ticket No", f"Ticket No {ticket} is cancelled - no SSR can be added.",
                         ticket, "a live ticket", i)
        elif ticket in known:
            problems.add("Not Mapped", "ticket_no", "Ticket No",
                         f"Ticket No {ticket} is no longer live (already rescheduled) - send the ticket it was rescheduled to.",
                         ticket, "a live ticket", i)
        else:
            problems.add("Not Mapped", "ticket_no", "Ticket No",
                         f"Ticket No {ticket} is not in the software, but the other passengers' tickets are - send it as a "
                         f"separate document (it is then saved as a direct SSR).", ticket, "a separate document", i)
    if problems.items:
        raise ImportRejected(" ".join(p["error_message"] for p in problems.items), problems.items, "Not Mapped")
    if len({parents[t]["original_ticket_id"] for t in wanted}) > 1:
        raise ImportRejected("These passengers belong to different original bookings - send one SSR document per booking.",
                             error_type="Mismatch")
    if len({parents[t]["reschedule_ticket_id"] for t in wanted}) > 1:   # one source per SSR header
        raise ImportRejected("Some of these passengers are on a reschedule and some on the original booking - send them as "
                             "separate SSR documents.", error_type="Mismatch")
    return parents


def _ssr_payload(company_id, rows):
    """
    SSR Updation - saved through the SSR screen's own view (ssr_ticket_create):
    every value from the push; the live ticket links each line (its reschedule
    line when the ticket was rescheduled) and is checked against. Direct SSR
    (ticket not in this software): nothing to link, the Parent PNR sent is kept.
    """
    parents = _ssr_parents(company_id, rows)
    if parents:
        _check_against_parent(rows, parents, "update")
    header = _header(rows[0])
    _finish_header(header, "SSR")
    problems = _Problems()
    lines = []
    for i, r in enumerate(rows, 1):
        parent = parents.get(r["original_ticket_no"])
        line = _line(r)
        _inherit(line, header, ("airline_category", "office_id", "supplier_name"))
        live_sectors = [s.strip().upper() for s in ((parent or {}).get("sector") or "").split(",") if s.strip()]
        if parent and line.get("sector") and line["sector"].upper() not in live_sectors:
            problems.add("Mismatch", "sector", "Sector",
                         f"Sector {line['sector']} is not on ticket {r['original_ticket_no']} - its sectors are "
                         f"{', '.join(live_sectors) or 'none'}.", line["sector"], ", ".join(live_sectors), i)
        pushed = _pushed_gst(r)
        for fee_field, gst_field, param, ledger in SSR_GST:
            if pushed.get(gst_field) is None:
                continue
            expected = _round2(float(line.get(fee_field) or 0) * models.mapped_gst_pct(company_id, ledger, header["invoice_date"]) / 100)
            if abs(float(pushed[gst_field]) - expected) > 0.01:
                label = AMOUNT_PARAMS[param][0]
                problems.add("Mismatch", param, label,
                             f"{label} {_money(float(pushed[gst_field]))} does not match the GST % of \"{ledger}\" on the "
                             f"{AMOUNT_PARAMS[param.replace('_gst', '')][0]} ({_money(expected)}).", pushed[gst_field],
                             _money(expected), i)
        passenger = _payload(r).get("passenger") or {}
        lines.append({
            "original_ticket_line_id": parent["original_ticket_line_id"] if parent else None,
            # Same ids the SSR screen sends: the live reschedule line when the ticket was rescheduled.
            "reschedule_line_id": parent["live_line_id"] if parent and parent["parent_kind"] == "Reschedule" else None,
            "ticket_no": r["original_ticket_no"],
            **{k: line.get(k) for k in ("passenger_name", "pax_type", "airline_category", "sector", "office_id",
                                        "supplier_name", "fop", "card_number")},
            "ssr_items": passenger.get("ssr_items") or {},
            "ssr_ticket_numbers": passenger.get("ssr_ticket_numbers") or {},
            **{k: line.get(f) or 0 for k, f in SSR_LINE_AMOUNTS.items()},
        })
    if problems.items:
        raise ImportRejected(" ".join(p["error_message"] for p in problems.items), problems.items, "Mismatch")
    first = parents.get(rows[0]["original_ticket_no"]) or {}
    return views.ssr_ticket_create, {
        "company_id": company_id, "original_ticket_id": first.get("original_ticket_id"),
        "source_reschedule_ticket_id": first.get("reschedule_ticket_id"),
        # No booking in this software (direct SSR, or one on a direct Reschedule): keep the Parent PNR sent.
        "parent_pnr": _parent_pnr(rows) if not first.get("original_ticket_id") else None,
        **{k: header.get(k) for k in ("customer_name", "branch_name", "invoice_number", "invoice_date", "invoice_type",
                                      "travel_type", "user_name", "currency", "roe", "airline_pnr", "gds_pnr",
                                      "payment_mode", "payment_gateway_ref", "booking_mode")},
        "ssr_reference": header.get("booking_reference"), "ssr_ref_date": header.get("booking_ref_date"),
        "lines": lines,
    }


PAYLOAD_BUILDERS = {"Confirmed": _booking_payload, "Rescheduled": _reschedule_payload, "Cancelled": _cancellation_payload,
                    "SSR": _ssr_payload}


def _invoice_number(company_id, invoice_type, invoice_date):
    if isinstance(invoice_date, str):
        invoice_date = views._parse_date(invoice_date)
    result = views.next_invoice_number(company_id, invoice_type, invoice_date)
    if result is None:
        raise ImportRejected(f"Invoice Type \"{invoice_type}\" is not a Voucher Type of this company.", error_type="Not Mapped")
    number_method, next_number = result
    if not next_number:
        raise ImportRejected(
            f"Invoice Type \"{invoice_type}\" uses {number_method} numbering - an Auto Push Invoice Type needs Automatic "
            f"numbering (Masters > Voucher Type).", error_type="Not Mapped",
        )
    return next_number


_request_factory = RequestFactory()


def _call_view(view, payload, acting_user):
    request = _request_factory.post(
        "/api/import/tickets/", data=json.dumps(_drop_empty(payload), default=_plain), content_type="application/json",
    )
    request.app_user = acting_user or permissions.API_KEY_USER
    response = view(request)
    try:
        data = json.loads(response.content or b"{}")
    except ValueError:
        data = {}
    return response.status_code, data


def _import_log_base(doc_key, rows):
    first = rows[0]
    payload = _payload(first)
    context = payload.get("context") or {}
    passengers = {}
    for i, r in enumerate(rows, 1):
        request = _payload(r).get("request_passenger") or {}
        passengers[i] = {"ticket_no": _shown(request.get("ticket_no")) or r.get("ticket_no") or r.get("original_ticket_no"),
                         "passenger_name": _shown(request.get("pax_name")) or r.get("passenger_name")}
    return {
        "company_id": first["company_id"], "source_system": first["source_system"], "batch_id": first.get("batch_id"),
        "doc_key": doc_key, "booking_status": context.get("booking_status") or first["ticket_status"],
        "booking_reference": context.get("booking_reference") or first.get("booking_reference"),
        "parent_pnr": context.get("parent_pnr"), "passengers": passengers,
    }


def _pushed_gst(row):
    """The GST amounts the Agent sent for this passenger ({} = none - worked out from the % as usual)."""
    return (_payload(row).get("passenger") or {}).get("gst_amounts") or {}


def _save(view, payload, rows, acting_user):
    """
    Saves the document through its Ticket Entry view. Each line carries the
    Agent's own GST amounts (gst_amounts) - the view's document_save wrapper
    uses them as sent and stores them with the document, the same way the
    screen re-saves them.
    """
    for line, r in zip(payload["lines"], rows):
        if _pushed_gst(r) and view is not views.ssr_ticket_create:
            line["gst_amounts"] = _pushed_gst(r)
    return _call_view(view, payload, acting_user)


def _import_document(doc_key, rows, acting_user):
    first = rows[0]
    result = {
        "doc_key": doc_key, "doc_ref": first["doc_ref"], "ticket_status": first["ticket_status"], "passengers": len(rows),
    }
    try:
        view, payload = PAYLOAD_BUILDERS[first["ticket_status"]](first["company_id"], rows)
        if not payload.get("invoice_type"):
            raise ImportRejected(
                f"No Invoice Type is selected for Auto Push {first['ticket_status']} tickets - pick one in Masters > "
                f"Voucher Type (Auto Push Invoice For).", error_type="Not Mapped",
            )
        auto_number = not payload.get("invoice_number")
        for attempt in range(3):
            if auto_number:
                payload["invoice_number"] = _invoice_number(first["company_id"], payload["invoice_type"], payload["invoice_date"])
            status_code, data = _save(view, payload, rows, acting_user)
            if status_code in (200, 201):
                break
            error = data.get("error") or f"Save failed (HTTP {status_code})."
            # Another save took the generated number first - take the next one.
            if not (auto_number and error.startswith("Invoice Number") and "already exists" in error) or attempt == 2:
                raise ImportRejected(error, error_type="Duplicate" if "already exists" in error else "Save Failed")
    except ImportRejected as err:
        sp_client.ticket_import_mark_error(doc_key, str(err), max_retry=1)
        problems = err.problems or [{
            "passenger_no": None, "field_name": None, "field_label": None, "received_value": None, "expected_value": None,
            "error_type": err.error_type, "severity": "Error", "error_message": str(err),
        }]
        _log_problems(problems, _import_log_base(doc_key, rows), "Import")
        return {**result, "process_status": "Error", "error": str(err), "errors": _response_errors(problems)}
    except Exception as err:  # noqa: BLE001 - unexpected (DB down etc.): retried by the next runs
        logger.exception("ticket import failed (%s)", doc_key)
        message = f"Unexpected error: {err}"
        status = sp_client.ticket_import_mark_error(doc_key, message, max_retry=3)
        if status == "Error":   # out of retries - parked
            _log_problems([{
                "passenger_no": None, "field_name": None, "field_label": None, "received_value": None,
                "expected_value": None, "error_type": "Save Failed", "severity": "Error", "error_message": message,
            }], _import_log_base(doc_key, rows), "Import")
        return {**result, "process_status": status, "error": message}

    sp_client.ticket_import_mark_imported(doc_key, data.get("id"), payload["invoice_number"], data.get("voucher_no"))
    try:
        sp_client.ticket_import_error_log_resolve(doc_key, f"Imported as invoice {payload['invoice_number']}")
    except Exception:  # noqa: BLE001
        logger.exception("could not resolve the error log of %s", doc_key)
    return {
        **result, "process_status": "Imported", "invoice_number": payload["invoice_number"],
        "invoice_type": payload["invoice_type"], "target_header_id": data.get("id"), "voucher_no": data.get("voucher_no"),
        "message": data.get("message"),
    }


_run_lock = threading.Lock()


def process_pending(company_id=None, batch_size=50, acting_user=None, max_passes=10):
    """
    One import run: saves every staged document that is ready, in dependency
    order (Confirmed, then Rescheduled, then Cancelled). Several passes, so a
    Reschedule pushed together with its booking is saved in the same run,
    right after that booking.
    """
    with _run_lock:
        models.clear_mapping_caches()   # the scheduler is a long-running process - read masters fresh each run
        run_id = sp_client.ticket_import_start_run(company_id)
        stuck_reset = sp_client.ticket_import_reset_stuck(company_id)
        documents = []
        for _ in range(max_passes):
            rows = sp_client.ticket_import_fetch_pending(company_id, run_id, batch_size)
            if not rows:
                break
            by_doc = {}
            for row in rows:
                by_doc.setdefault(row["doc_key"], []).append(row)
            for doc_key, doc_rows in by_doc.items():
                documents.append(_import_document(doc_key, doc_rows, acting_user))
        imported = sum(1 for d in documents if d["process_status"] == "Imported")
        failed = len(documents) - imported
        sp_client.ticket_import_finish_run(run_id, imported, failed, f"{imported} imported, {failed} failed.")
    return {
        "run_id": run_id, "documents_processed": len(documents), "imported": imported, "failed": failed,
        "stuck_rows_reset": stuck_reset, "documents": documents,
    }


# ==========================================================================
# 5. API endpoints (urls.py: /api/import/tickets/...)
#    Auth: X-Api-Key header (TICKET_IMPORT_API_KEY in .env), or a signed-in
#    user's Bearer token with Add rights on Ticket Entry.
# ==========================================================================

def _body(request):
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _int(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _status_dict(row):
    return {
        "doc_key": row["doc_key"], "doc_ref": row["doc_ref"], "booking_status": BOOKING_STATUS[row["ticket_status"]],
        "source_system": row["source_system"], "batch_id": row["batch_id"], "passengers": row["passengers"],
        "process_status": row["process_status"], "invoice_number": row["invoice_number"], "invoice_type": row["invoice_type"],
        "voucher_no": row["voucher_no"], "target_header_id": row["target_header_id"], "retry_count": row["retry_count"],
        "error": row["error_message"] if row["process_status"] != "Imported" else None,
        "received_at": row["received_at"], "processed_at": row["processed_at"],
    }


def _push_error(message, http_status, company_id=None, source_system=None, batch_id=None, field=None, received=None):
    """A push refused as a whole (no invoice looked at) - logged too."""
    _log_problems([{
        "passenger_no": None, "field_name": field, "field_label": field, "received_value": _shown(received),
        "expected_value": None, "error_type": "Missing" if received is None and field else "Invalid Format",
        "severity": "Error", "error_message": message,
    }], {"company_id": company_id, "source_system": source_system, "batch_id": batch_id}, "Validation")
    return JsonResponse({"process_status": "Rejected", "error": message}, status=http_status)


@csrf_exempt
def push(request):
    """
    POST /api/import/tickets/push/
    One invoice:  { company_id, booking_status, ...header, passengers: [ {...}, ... ] }
    Several:      { company_id, source_system, batch_id, process_now (default true),
                    documents: [ { booking_status, ...header, passengers: [...] }, ... ] }
    booking_status (C / R / X / SSR) decides what is saved. Each invoice comes back
    as Rejected (bad data - nothing staged, "errors" lists every problem),
    Imported (saved - invoice_number / voucher_no), Error (refused while
    saving), or Pending (queued for the scheduler). Every problem is also
    written to the error log. A one-invoice push gets that one result as the
    whole response.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    body = _body(request)
    if body is None:
        return _push_error("The body must be a JSON object.", 400)

    company_id = _int(body.get("company_id"))
    source_system = str(body.get("source_system") or "API").strip()[:50] or "API"
    batch_id = str(body.get("batch_id")).strip()[:50] if not _blank(body.get("batch_id")) else None
    if not company_id or not sp_client.company_master_get(company_id):
        return _push_error("company_id is missing or is not an existing company.", 400, None, source_system, batch_id,
                           "company_id", body.get("company_id"))
    single = "documents" not in body
    documents = [{k: v for k, v in body.items() if k not in PUSH_KEYS}] if single else body.get("documents")
    if not isinstance(documents, list) or not documents:
        return _push_error("documents must be a non-empty list.", 400, company_id, source_system, batch_id, "documents",
                           body.get("documents"))
    if len(documents) > MAX_DOCUMENTS_PER_PUSH:
        return _push_error(f"At most {MAX_DOCUMENTS_PER_PUSH} documents per push.", 400, company_id, source_system, batch_id)

    try:
        results, run = receive_documents(company_id, source_system, batch_id, documents,
                                         process_now=body.get("process_now", True) is not False,
                                         acting_user=getattr(request, "app_user", None))
    except sp_client.StoredProcedureError as err:
        return JsonResponse({"error": f"Could not stage the tickets: {err}"}, status=500)

    counts = {}
    for r in results:
        counts[r.get("process_status") or "Pending"] = counts.get(r.get("process_status") or "Pending", 0) + 1
    all_ok = all(r.get("process_status") in ("Imported", "Pending", "Processing") and not r.get("duplicate") for r in results)
    if single:
        # One invoice: its own result is the response. 200 saved / queued,
        # 400 bad data (nothing saved), 409 already received (the saved
        # invoice number is in the response), 422 refused while saving.
        r = {k: v for k, v in results[0].items() if k not in ("index", "duplicate")}
        http = (200 if all_ok else 400 if r.get("process_status") == "Rejected"
                else 409 if results[0].get("duplicate") else 422)
        return JsonResponse({"company_id": company_id, "source_system": source_system, **r}, status=http)
    return JsonResponse({
        "company_id": company_id, "source_system": source_system, "batch_id": batch_id,
        "summary": {"documents": len(results), **counts},
        "documents": results,
        "run_id": run["run_id"] if run else None,
    }, status=200 if all_ok else 207)


def receive_documents(company_id, source_system, batch_id, documents, process_now=True, acting_user=None):
    """
    The Auto Push pipeline for a list of invoices - used by push() (API) and
    by agent_db_scheduler (the Airline_Agent database): every invoice is
    checked (problems -> error log, process_status "Rejected"), the clean
    ones staged and - process_now - saved through the Ticket Entry views.
    Returns (results, run): one result per invoice, in order (process_status,
    invoice_number, voucher_no, doc_key, errors, duplicate ...), and the
    import run (None when nothing was staged or process_now is False).
    Raises sp_client.StoredProcedureError when staging itself fails.
    """
    masters, today = _Masters(company_id), date.today()
    results, rows, seen_docs, log_bases = [], [], set(), {}
    for n, doc in enumerate(documents, 1):
        check = _DocumentCheck(doc, masters, today)
        cleaned = check.run()
        problems = check.problems
        doc_ref = cleaned["doc_ref"] if cleaned else check.doc_ref_guess()
        key = _doc_key(company_id, source_system, check.status, doc_ref) if check.status and doc_ref else None
        context = check.context
        result = {"index": n, "booking_status": context.get("booking_status"), "booking_reference": context.get("booking_reference")}
        if check.status == "Cancelled" and doc_ref:
            result["ticket_no"] = doc_ref
        if cleaned and key in seen_docs:
            problems.add("Duplicate", "booking_reference", "Booking Reference",
                         "The same invoice (Booking Status + Booking Reference / Ticket No) appears twice in this push.",
                         doc_ref, "once per push")
            cleaned = None
        base = {
            "company_id": company_id, "source_system": source_system, "batch_id": batch_id, "doc_key": key,
            "passengers": _request_passengers(doc), **{k: context.get(k) for k in ("booking_status", "booking_reference", "parent_pnr")},
        }
        warnings = [p for p in problems.items if p["severity"] == "Warning"]
        if not cleaned:
            logged = _log_problems(problems.items, base, "Validation")
            results.append({
                **result, "process_status": "Rejected", "errors": _response_errors(problems.errors),
                "warnings": _response_errors(warnings), "error_log_rows": logged,
            })
            continue
        _log_problems(warnings, base, "Validation")
        seen_docs.add(key)
        log_bases[key] = base
        rows.extend(_staging_rows(company_id, source_system, cleaned, context, doc))
        results.append({**result, "doc_key": key, "passengers": len(cleaned["passengers"]),
                        "warnings": _response_errors(warnings)})

    run = None
    if rows:
        outcomes = sp_client.ticket_import_stage(batch_id, rows)
        outcome_by_doc = {}
        for o in outcomes:
            outcome_by_doc.setdefault(o["doc_key"], set()).add(o["outcome"])
        if process_now:
            run = process_pending(company_id, acting_user=acting_user)
        run_docs = {d["doc_key"]: d for d in (run or {}).get("documents", [])}
        statuses = {
            s["doc_key"]: s for s in sp_client.ticket_import_doc_status(
                company_id, doc_keys=[r["doc_key"] for r in results if r.get("doc_key")], top=MAX_DOCUMENTS_PER_PUSH,
            )
        }
        for r in results:
            if not r.get("doc_key"):
                continue
            seen = outcome_by_doc.get(r["doc_key"], set())
            duplicate = not (seen & {"Inserted", "Refreshed"})
            r["received"] = (
                "New" if "Inserted" in seen and "Refreshed" not in seen
                else "Updated (replaced the earlier push still waiting)" if not duplicate
                else "Duplicate - this invoice was already received and is not saved again"
            )
            status = statuses.get(r["doc_key"])
            if status:
                s = _status_dict(status)
                r.update({k: s[k] for k in ("process_status", "invoice_number", "invoice_type", "voucher_no", "target_header_id", "error")})
                if s["process_status"] == "Pending":
                    r["message"] = "Queued - the scheduler imports it (it may be waiting for the ticket it changes)."
            if r["doc_key"] in run_docs and run_docs[r["doc_key"]].get("errors"):
                r["errors"] = run_docs[r["doc_key"]]["errors"]
            if duplicate:
                what = (f"imported as invoice {r.get('invoice_number')}" if r.get("process_status") == "Imported"
                        else f"still {str(r.get('process_status') or 'Pending').lower()}")
                message = (f"This invoice was already received ({what}) - the same push is not saved again. "
                           f"Send a new Booking Reference for a new invoice.")
                _log_problems([{
                    "passenger_no": None, "field_name": "booking_reference", "field_label": "Booking Reference",
                    "received_value": r.get("booking_reference") or r.get("ticket_no"), "expected_value": "a new invoice",
                    "error_type": "Duplicate", "severity": "Error", "error_message": message,
                }], log_bases[r["doc_key"]], "Validation")
                r["errors"] = [{"passenger_no": None, "field": "booking_reference", "error_type": "Duplicate", "message": message}]
                r["duplicate"] = True
    return results, run


@csrf_exempt
def process(request):
    """POST /api/import/tickets/process/  Body (optional): { company_id, batch_size } - what the scheduler runs."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    body = _body(request) or {}
    result = process_pending(
        _int(body.get("company_id")), batch_size=_int(body.get("batch_size")) or 50,
        acting_user=getattr(request, "app_user", None),
    )
    return JsonResponse(result)


@csrf_exempt
def retry(request):
    """
    POST /api/import/tickets/retry/  Body: { company_id, doc_keys (optional - all Error documents when left out) }
    Puts Error documents back in the queue (after fixing the master data /
    payload) and imports them again straight away.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    body = _body(request) or {}
    company_id = _int(body.get("company_id"))
    doc_keys = body.get("doc_keys") or None
    if doc_keys is not None and not (isinstance(doc_keys, list) and all(isinstance(k, str) for k in doc_keys)):
        return JsonResponse({"error": "doc_keys must be a list of doc_key strings."}, status=400)
    requeued = sp_client.ticket_import_requeue(company_id, doc_keys)
    result = process_pending(company_id, acting_user=getattr(request, "app_user", None))
    return JsonResponse({"rows_requeued": requeued, **result})


def status(request):
    """GET /api/import/tickets/status/?company_id=1[&batch_id=&doc_ref=&source_system=&process_status=&top=]"""
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    q = request.GET
    rows = sp_client.ticket_import_doc_status(
        _int(q.get("company_id")), batch_id=q.get("batch_id") or None, source_system=q.get("source_system") or None,
        doc_ref=q.get("doc_ref") or None, process_status=q.get("process_status") or None,
        top=min(_int(q.get("top")) or 200, 1000),
    )
    return JsonResponse({"documents": [_status_dict(r) for r in rows]})


def error_log(request):
    """
    GET /api/import/tickets/error-log/?company_id=1[&source=API|AGENT_DB&from_date=&to_date=&booking_status=
                                        &error_type=&stage=&resolved=0|1&search=&top=]
    The error log grid (/error_log/ page). Dates are IST, YYYY-MM-DD.
    source: API = API Push tab, AGENT_DB = Automated Database Scheduler tab.
    """
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    q = request.GET
    resolved = {"0": False, "1": True}.get(q.get("resolved") or "")
    rows = sp_client.ticket_import_error_log_list(
        _int(q.get("company_id")), from_date=q.get("from_date") or None, to_date=q.get("to_date") or None,
        booking_status=q.get("booking_status") or None, error_type=q.get("error_type") or None,
        stage=q.get("stage") or None, resolved=resolved, search=(q.get("search") or "").strip() or None,
        top=min(_int(q.get("top")) or 500, 5000), source=(q.get("source") or "").upper() or None,
    )
    return JsonResponse({"rows": rows, "count": len(rows)})


@csrf_exempt
def invoice_types(request):
    """
    GET  /api/import/tickets/invoice-types/?company_id=1
         -> { "invoice_types": [ {ticket_status, voucher_type_id, voucher_type_name, ...}, ... ] }
    POST { company_id, voucher_type_id, booking_statuses: ["Confirmed", "Rescheduled", "Cancelled"] }
         The Voucher Type page's "Auto Push Invoice For" - that voucher type
         becomes the Invoice Type of exactly these Booking Statuses.
    """
    if request.method == "GET":
        company_id = _int(request.GET.get("company_id"))
        return JsonResponse({"invoice_types": list(sp_client.ticket_import_invoice_types(company_id).values())})
    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])
    body = _body(request) or {}
    company_id, voucher_type_id = _int(body.get("company_id")), _int(body.get("voucher_type_id"))
    statuses = body.get("booking_statuses") or []
    if not company_id or not voucher_type_id:
        return JsonResponse({"error": "company_id and voucher_type_id are required."}, status=400)
    if not isinstance(statuses, list) or any(s not in TICKET_STATUSES for s in statuses):
        return JsonResponse({"error": "booking_statuses must be a list of Confirmed / Rescheduled / Cancelled."}, status=400)
    try:
        sp_client.ticket_import_invoice_type_set(company_id, voucher_type_id, statuses)
    except sp_client.StoredProcedureError as err:
        return JsonResponse({"error": str(err)}, status=400)
    return JsonResponse({"invoice_types": list(sp_client.ticket_import_invoice_types(company_id).values())})


def error_log_page(request):
    """GET /error_log/ on the backend port -> the Error Log page of the frontend (same host, port 8080)."""
    host = request.get_host().split(":")[0]
    return HttpResponseRedirect(f"http://{host}:8080/error_log/")
