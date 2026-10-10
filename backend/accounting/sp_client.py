"""
sp_client.py — Stored Procedure client layer.

Project architecture decision (2026-10-06): every database operation in
this app goes through a SQL Server stored procedure, never direct ORM
queries/loops in views.py. exec_sp() below is the one low-level wrapper
every module-specific helper in this file is built on top of.

Pattern for every module (Ledger Groups, Ledgers, Tickets, Reschedule,
Vouchers, every report, ...):
    1. One `dbo.sp_<ModuleName>` stored procedure in StoredProcedures.sql,
       branching internally on its first parameter, @Action.
    2. One small Python helper function here, e.g.:

        def ledger_group_list(company_id):
            return exec_sp("dbo.sp_LedgerGroup", {
                "Action": "SELECT",
                "CompanyId": company_id,
            })

    3. views.py calls that helper instead of touching models.py/the ORM
       for anything this layer already covers.

Models.py is NOT being deleted — model classes still describe the
schema for Schema.sql/migrations purposes, but views.py must not do
Model.objects.filter()/.create()/.update() loops once a module has its
own stored procedure here; it calls the helper function instead.
"""
from django.db import connection


def exec_sp(proc_name, params=None):
    """
    Executes a stored procedure by name and returns its ONE result set
    as a list of plain dicts (column_name -> value) — per this project's
    "Single Result Set Rule", every procedure always returns exactly one
    populated result set for whatever @Action was requested, so callers
    never need to juggle cursor.nextset().

    proc_name: e.g. "dbo.sp_LedgerGroup"
    params: a dict of {ParamNameWithoutAt: value}, e.g.
            {"Action": "SAVE", "CompanyId": 1, "Name": "Sundry Debtors"}
            - passed through as SQL Server @ParamName=value pairs, by
            name (order never matters), so None safely becomes SQL NULL
            via the normal DB-API parameter binding.

    Returns [] for an action that returns no rows (e.g. a bare DELETE
    that doesn't SELECT anything back) rather than raising.
    """
    # Live (MySQL/TiDB) has no stored procedures: each procedure's logic is
    # reproduced in Python in accounting/sp_mysql/ (StoredProcedures.sql is
    # kept only as a reference in backend/sp_reference/).
    if connection.vendor != "microsoft":
        from .sp_mysql import exec_sp as exec_sp_mysql
        return exec_sp_mysql(proc_name, params)

    params = params or {}
    if params:
        assignments = ", ".join(f"@{name}=%s" for name in params.keys())
        sql = f"EXEC {proc_name} {assignments}"
    else:
        sql = f"EXEC {proc_name}"

    with connection.cursor() as cursor:
        cursor.execute(sql, list(params.values()))
        if cursor.description is None:
            return []
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]


def exec_sp_one(proc_name, params=None):
    """
    Same as exec_sp(), but returns just the first row (a dict) or None
    if the result set was empty — convenience for GET_BY_ID/SAVE-style
    actions that only ever return a single row.
    """
    rows = exec_sp(proc_name, params)
    return rows[0] if rows else None


class StoredProcedureError(Exception):
    """
    Raised when a stored procedure's own BEGIN CATCH block reports
    failure instead of letting the DB driver raise a raw pyodbc error -
    some SAVE/DELETE actions SELECT ERROR_MESSAGE() AS error (rather
    than using THROW) so the caller gets a clean message instead of a
    driver-level exception. Helpers that call such a procedure should
    check for an "error"/"status" column in the returned row and raise
    this instead of returning the raw dict in that case.
    """
    pass


# ==========================================================================
# Ledger Groups (dbo.sp_LedgerGroup) - see StoredProcedures.sql
# ==========================================================================

def ledger_group_list(company_id):
    """Flat list of this company's Ledger Groups - views.ledger_groups_list."""
    return exec_sp("dbo.sp_LedgerGroup", {"Action": "SELECT", "CompanyId": company_id})


def ledgers_by_group_names(company_id, name_variants):
    """Every ledger under any Ledger Group matching one of name_variants (and their whole subtree) - views.ledgers_by_group_name."""
    import json as _json
    return exec_sp("dbo.sp_LedgerGroup", {
        "Action": "LEDGERS_BY_GROUP_NAMES", "CompanyId": company_id, "NameVariantsJson": _json.dumps(list(name_variants)),
    })


def ledger_group_save(company_id, name, account_type, code=None, parent_id=None, is_group=True):
    """
    Creates a new Ledger Group - views.ledger_group_create. Raises
    StoredProcedureError with the procedure's own message if company_id/
    name/account_type validation fails inside the stored procedure.
    """
    row = exec_sp_one("dbo.sp_LedgerGroup", {
        "Action": "SAVE",
        "CompanyId": company_id,
        "Name": name,
        "Code": code,
        "AccountType": account_type,
        "ParentId": parent_id,
        "IsGroup": is_group,
    })
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not save this Ledger Group.")
    return row


# ==========================================================================
# Ledgers (dbo.sp_Ledger) - see StoredProcedures.sql
# ==========================================================================

# Maps the flat LEDGER_FIELDS payload keys (views.py) to this procedure's
# @ParamName - every field is optional/nullable on SAVE and UPDATE.
_LEDGER_FIELD_PARAMS = {
    "bank_account_no": "BankAccountNo", "bank_branch": "BankBranch",
    "ifsc_code": "IfscCode", "swift_code": "SwiftCode",
    "alias_name": "AliasName", "address_line1": "AddressLine1", "address_line2": "AddressLine2",
    "agent_id": "AgentId", "maintain_balance_bill_wise": "MaintainBalanceBillWise",
    "place_of_supply": "PlaceOfSupply",
    "city": "City", "pincode": "Pincode", "state_name": "StateName", "gst_no": "GstNo",
    "gst_registration_type": "GstRegistrationType", "pan_no": "PanNo",
    "emirate": "Emirate", "po_box_no": "PoBoxNo", "vat_trn_no": "VatTrnNo",
    "trade_license_no": "TradeLicenseNo", "trade_license_expiry": "TradeLicenseExpiry",
    "creditor_type": "CreditorType", "supplier_code": "SupplierCode", "office_id": "OfficeId",
    "tax_category": "TaxCategory", "tax_type": "TaxType",
    "gst_applicable": "GstApplicable", "gst_tax_type": "GstTaxType", "gst_percentage": "GstPercentage",
    "tds_applicable": "TdsApplicable", "tds_percentage": "TdsPercentage", "hsn_code": "HsnCode",
    "tcs_applicable": "TcsApplicable", "tcs_percentage": "TcsPercentage",
}


def ledger_list(company_id):
    """Flat list of this company's Ledgers - views.accounts_list / Chart of Accounts."""
    return exec_sp("dbo.sp_Ledger", {"Action": "LIST", "CompanyId": company_id})


def customers_list(company_id):
    """Ledgers under ledger_category='DEBTOR' - views.customers_list."""
    return exec_sp("dbo.sp_Ledger", {"Action": "LIST_CUSTOMERS", "CompanyId": company_id})


def suppliers_list(company_id):
    """Ledgers under ledger_category='CREDITOR' - views.suppliers_list."""
    return exec_sp("dbo.sp_Ledger", {"Action": "LIST_SUPPLIERS", "CompanyId": company_id})


def ledger_get(ledger_id, company_id):
    """One ledger's full field set - views.ledger_detail. None if not found."""
    return exec_sp_one("dbo.sp_Ledger", {"Action": "GET_BY_ID", "Id": ledger_id, "CompanyId": company_id})


def ledger_agent_id_available(agent_id, exclude_id=None):
    """views.ledger_agent_id_available - True if no OTHER ledger uses this agent_id."""
    row = exec_sp_one("dbo.sp_Ledger", {"Action": "CHECK_AGENT_ID", "AgentId": agent_id, "ExcludeId": exclude_id})
    return bool(row and row.get("available"))


def ledger_name_available(company_id, name, exclude_id=None):
    """views.ledger_name_available - True if no OTHER ledger in this company has this name."""
    row = exec_sp_one("dbo.sp_Ledger", {
        "Action": "CHECK_NAME", "CompanyId": company_id, "Name": name, "ExcludeId": exclude_id,
    })
    return bool(row and row.get("available"))


def ledger_save(company_id, name, parent_id, opening_balance=None, opening_balance_type=None,
                 ledger_category=None, extra_fields=None):
    """
    Creates a new Ledger - views.ledger_create. `extra_fields` is the
    LEDGER_FIELDS-keyed dict views.py already builds from the request body.
    Raises StoredProcedureError with the procedure's own message on failure
    (missing group, duplicate name, duplicate agent_id, ...).
    """
    params = {
        "Action": "SAVE", "CompanyId": company_id, "Name": name, "ParentId": parent_id,
        "OpeningBalance": opening_balance, "OpeningBalanceType": opening_balance_type,
        "LedgerCategory": ledger_category,
    }
    for key, value in (extra_fields or {}).items():
        if key in _LEDGER_FIELD_PARAMS:
            params[_LEDGER_FIELD_PARAMS[key]] = value
    row = exec_sp_one("dbo.sp_Ledger", params)
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not save this ledger.")
    return row


def ledger_update(ledger_id, company_id, name=None, parent_id=None, opening_balance=None,
                   opening_balance_type=None, ledger_category=None, extra_fields=None):
    """Updates a Ledger in place - views.ledger_update. Raises StoredProcedureError on failure."""
    params = {
        "Action": "UPDATE", "Id": ledger_id, "CompanyId": company_id, "Name": name, "ParentId": parent_id,
        "OpeningBalance": opening_balance, "OpeningBalanceType": opening_balance_type,
        "LedgerCategory": ledger_category,
    }
    extra_fields = extra_fields or {}
    for key, value in extra_fields.items():
        if key in _LEDGER_FIELD_PARAMS:
            params[_LEDGER_FIELD_PARAMS[key]] = value
    if "agent_id" in extra_fields:
        params["AgentIdProvided"] = True
    row = exec_sp_one("dbo.sp_Ledger", params)
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not update this ledger.")
    return row


def ledger_get_by_name(company_id, name, ledger_category):
    """
    Resolves a ledger by (company_id, name, ledger_category) - e.g. the
    Tickets/Reschedule write path's Customer (DEBTOR) / Supplier (CREDITOR)
    resolution. None if no such ledger exists (caller turns that into its
    own "not a real customer/supplier ledger" error message).
    """
    return exec_sp_one("dbo.sp_Ledger", {"Action": "GET_BY_NAME", "CompanyId": company_id, "Name": name, "LedgerCategory": ledger_category})


def ledger_delete(ledger_id, company_id):
    """Deletes a Ledger - views.ledger_delete. Raises StoredProcedureError if protected/not found."""
    row = exec_sp_one("dbo.sp_Ledger", {"Action": "DELETE", "Id": ledger_id, "CompanyId": company_id})
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not delete this ledger.")
    return row


# ==========================================================================
# Company Master (dbo.sp_CompanyMaster) - see StoredProcedures.sql
# ==========================================================================

_COMPANY_MASTER_FIELD_PARAMS = {
    "company_name": "CompanyName", "mailing_name": "MailingName", "address": "Address",
    "country": "Country", "state": "State", "pincode": "Pincode", "telephone": "Telephone",
    "mobile": "Mobile", "email": "Email", "financial_year_from": "FinancialYearFrom",
    "books_beginning_from": "BooksBeginningFrom", "gst_reg_type": "GstRegType", "gst_no": "GstNo",
    "pan_number": "PanNumber", "cin_number": "CinNumber", "tan_number": "TanNumber", "hsn_sac": "HsnSac",
    "currency_symbol": "CurrencySymbol", "currency_name": "CurrencyName", "decimal_places": "DecimalPlaces",
    "logo_base64": "LogoBase64", "seal_base64": "SealBase64",
}


def company_master_get(company_id):
    """One company by id - views.company_master_list's ?id= branch. None if not found."""
    return exec_sp_one("dbo.sp_CompanyMaster", {"Action": "LIST", "Id": company_id})


def company_master_list():
    """Every company, ordered by name - views.company_master_list's bare GET."""
    return exec_sp("dbo.sp_CompanyMaster", {"Action": "LIST"})


def company_master_save(fields, company_id=None):
    """
    Upserts a CompanyMaster row - views.company_master_save. `fields` is the
    already-normalized dict views.py builds (company_name, mailing_name, ...).
    Raises StoredProcedureError on validation/duplicate failure.
    """
    params = {"Action": "SAVE", "Id": company_id}
    for key, value in fields.items():
        if key in _COMPANY_MASTER_FIELD_PARAMS:
            params[_COMPANY_MASTER_FIELD_PARAMS[key]] = value
    row = exec_sp_one("dbo.sp_CompanyMaster", params)
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not save this company.")
    return row


def company_master_delete(company_id):
    """Deletes a CompanyMaster row - views.company_master_delete. Raises StoredProcedureError if not found."""
    row = exec_sp_one("dbo.sp_CompanyMaster", {"Action": "DELETE", "Id": company_id})
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not delete this company.")
    return row


# ==========================================================================
# Voucher Type (dbo.sp_VoucherType) - see StoredProcedures.sql
# ==========================================================================

_VOUCHER_TYPE_FIELD_PARAMS = {
    "name": "Name", "alias_name": "AliasName", "voucher_category": "VoucherCategory",
    "is_active": "IsActive", "number_method": "NumberMethod",
    "allow_additional_numbering": "AllowAdditionalNumbering",
    "allow_effective_dates": "AllowEffectiveDates", "allow_narration": "AllowNarration",
    "an_width_of_invoice_number": "AnWidthOfInvoiceNumber", "an_prefill_with_zero": "AnPrefillWithZero",
    "an_restart_applicable_from": "AnRestartApplicableFrom",
    "an_restart_starting_number": "AnRestartStartingNumber", "an_restart_period": "AnRestartPeriod",
    "an_prefix_details": "AnPrefixDetails", "an_suffix_details": "AnSuffixDetails",
}


def voucher_type_get_by_name(company_id, name):
    """One voucher type by name - views.voucher_type_next_number. None if not found."""
    return exec_sp_one("dbo.sp_VoucherType", {"Action": "GET_BY_NAME", "CompanyId": company_id, "Name": name})


def voucher_type_get(voucher_type_id, company_id):
    """One voucher type by id - views.voucher_type_list's ?id= branch. None if not found."""
    return exec_sp_one("dbo.sp_VoucherType", {"Action": "LIST", "Id": voucher_type_id, "CompanyId": company_id})


def voucher_type_list(company_id):
    """Every voucher type for a company, ordered by name - views.voucher_type_list's bare GET."""
    return exec_sp("dbo.sp_VoucherType", {"Action": "LIST", "CompanyId": company_id})


def voucher_type_save(company_id, fields, voucher_type_id=None):
    """Upserts a VoucherType row - views.voucher_type_save. Raises StoredProcedureError on failure."""
    params = {"Action": "SAVE", "Id": voucher_type_id, "CompanyId": company_id}
    for key, value in fields.items():
        if key in _VOUCHER_TYPE_FIELD_PARAMS:
            params[_VOUCHER_TYPE_FIELD_PARAMS[key]] = value
    row = exec_sp_one("dbo.sp_VoucherType", params)
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not save this Voucher Type.")
    return row


def voucher_type_delete(voucher_type_id, company_id):
    """Deletes a VoucherType row - views.voucher_type_delete. Raises StoredProcedureError if not found."""
    row = exec_sp_one("dbo.sp_VoucherType", {"Action": "DELETE", "Id": voucher_type_id, "CompanyId": company_id})
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not delete this Voucher Type.")
    return row


# ==========================================================================
# FOP Master (dbo.sp_FOPMaster) - see StoredProcedures.sql
# ==========================================================================

def fop_master_list(company_id, card_type=None):
    """FOPMaster rows for a company, optionally filtered by card_type - views.fop_master_list."""
    return exec_sp("dbo.sp_FOPMaster", {"Action": "LIST", "CompanyId": company_id, "CardType": card_type})


def fop_master_save(company_id, card_type, card_number, bank_name=None, card_master_ledger_id=None,
                     is_active=None, card_id=None):
    """Upserts a FOPMaster row - views.fop_master_save. Raises StoredProcedureError on failure."""
    row = exec_sp_one("dbo.sp_FOPMaster", {
        "Action": "SAVE", "Id": card_id, "CompanyId": company_id, "CardType": card_type,
        "CardNumber": card_number, "BankName": bank_name, "CardMasterLedgerId": card_master_ledger_id,
        "IsActive": is_active,
    })
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not save this card.")
    return row


def fop_master_get_by_card_number(company_id, card_number):
    """Resolves a card's own GL ledger by card_number - views._fop_payment_lines/_reschedule_fop_payment_lines's Own Card lookup."""
    return exec_sp_one("dbo.sp_FOPMaster", {"Action": "GET_BY_CARD_NUMBER", "CompanyId": company_id, "CardNumber": card_number})


def fop_master_delete(card_id, company_id):
    """Deletes a FOPMaster row - views.fop_master_delete. Raises StoredProcedureError if not found."""
    row = exec_sp_one("dbo.sp_FOPMaster", {"Action": "DELETE", "Id": card_id, "CompanyId": company_id})
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not delete this card.")
    return row


# ==========================================================================
# PG Master (dbo.sp_PGMaster) - see StoredProcedures.sql
# ==========================================================================

def pg_master_list(company_id):
    """PGMaster rows for a company, with the GST% of their charges ledger joined in - views.pg_master_list."""
    return exec_sp("dbo.sp_PGMaster", {"Action": "LIST", "CompanyId": company_id})


def pg_master_save(company_id, gateway_name, payment_master_ledger_id, pg_charges_master_ledger_id=None,
                    pg_charges_percentage=None, pg_charges_percentage_effective_from=None,
                    is_active=None, gateway_id=None):
    """
    Upserts a PGMaster row AND its PGMasterHistory snapshot (when an
    Effective From date is given) atomically - views.pg_master_save +
    _snapshot_pg_master_history. Raises StoredProcedureError on failure.
    """
    row = exec_sp_one("dbo.sp_PGMaster", {
        "Action": "SAVE", "Id": gateway_id, "CompanyId": company_id, "GatewayName": gateway_name,
        "PaymentMasterLedgerId": payment_master_ledger_id, "PgChargesMasterLedgerId": pg_charges_master_ledger_id,
        "PgChargesPercentage": pg_charges_percentage,
        "PgChargesPercentageEffectiveFrom": pg_charges_percentage_effective_from,
        "IsActive": is_active,
    })
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not save this Payment Gateway.")
    return row


def pg_master_delete(gateway_id, company_id):
    """Deletes a PGMaster row - views.pg_master_delete. Raises StoredProcedureError if not found."""
    row = exec_sp_one("dbo.sp_PGMaster", {"Action": "DELETE", "Id": gateway_id, "CompanyId": company_id})
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not delete this Payment Gateway.")
    return row


def pg_master_history_list(gateway_id, company_id):
    """Snapshots newest-first for one gateway - views.pg_master_history_list."""
    return exec_sp("dbo.sp_PGMaster", {"Action": "HISTORY_LIST", "Id": gateway_id, "CompanyId": company_id})


def pg_master_effective_snapshot(company_id, gateway_name, as_of_date=None):
    """
    The ledger/percentage snapshot in force for `gateway_name` on
    `as_of_date` - views._pg_master_effective_snapshot(). None if the
    gateway itself doesn't exist for this company.
    """
    row = exec_sp_one("dbo.sp_PGMaster", {
        "Action": "EFFECTIVE_SNAPSHOT", "CompanyId": company_id, "GatewayName": gateway_name, "AsOfDate": as_of_date,
    })
    if row and row.get("status") == "Error":
        return None
    return row


# ==========================================================================
# Supplier Commission Rules (dbo.sp_SupplierCommissionRule) - see
# StoredProcedures.sql
# ==========================================================================

_SUPPLIER_RULE_FIELD_PARAMS = {
    "office_id": "OfficeId", "supplier_name": "SupplierName", "travel_type": "TravelType",
    "airline_category": "AirlineCategory", "cabin": "Cabin", "fare_type": "FareType", "comm_on": "CommOn",
    "calc_type": "CalcType", "calc_pct": "CalcPct", "flat_amt": "FlatAmt", "valid_upto": "ValidUpto",
}


def supplier_commission_rules_list(company_id, office_id=None):
    """SupplierCommissionRules for a company, optionally narrowed to one office_id - views.supplier_commission_rules_list."""
    return exec_sp("dbo.sp_SupplierCommissionRule", {"Action": "LIST", "CompanyId": company_id, "OfficeId": office_id})


def supplier_commission_rule_save(company_id, fields):
    """Inserts a new rule (no unique key on this table) - views.supplier_commission_rule_create."""
    params = {"Action": "SAVE", "CompanyId": company_id}
    for key, value in fields.items():
        if key in _SUPPLIER_RULE_FIELD_PARAMS:
            params[_SUPPLIER_RULE_FIELD_PARAMS[key]] = value
    row = exec_sp_one("dbo.sp_SupplierCommissionRule", params)
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not save this rule.")
    return row


def supplier_commission_rule_delete(rule_id, company_id):
    """Deletes a rule - views.supplier_commission_rule_delete. Raises StoredProcedureError if not found."""
    row = exec_sp_one("dbo.sp_SupplierCommissionRule", {"Action": "DELETE", "Id": rule_id, "CompanyId": company_id})
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not delete this rule.")
    return row


# ==========================================================================
# Master Mapping (dbo.sp_MasterMapping) - see StoredProcedures.sql
# ==========================================================================

def master_mapping_list(company_id, product_type=None, masters_category=None):
    """MasterMapping rows for a company, optionally filtered - views.master_mapping_list."""
    return exec_sp("dbo.sp_MasterMapping", {
        "Action": "LIST", "CompanyId": company_id, "ProductType": product_type, "MastersCategory": masters_category,
    })


def master_mapping_save_row(company_id, product_type, masters_category, masters_category_id, field_name,
                             ledger_id, effective_from):
    """Upserts one (company_id, product_type, field_name) row - one call per row in views.master_mapping_save's loop."""
    row = exec_sp_one("dbo.sp_MasterMapping", {
        "Action": "SAVE_ROW", "CompanyId": company_id, "ProductType": product_type,
        "MastersCategory": masters_category, "MastersCategoryId": masters_category_id,
        "FieldName": field_name, "LedgerId": ledger_id, "EffectiveFrom": effective_from,
    })
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or f'Could not save "{field_name}".')
    return row


def master_mapping_delete(mapping_id, company_id):
    """Deletes a MasterMapping row - views.master_mapping_delete. Raises StoredProcedureError if not found."""
    row = exec_sp_one("dbo.sp_MasterMapping", {"Action": "DELETE", "Id": mapping_id, "CompanyId": company_id})
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not delete this mapping.")
    return row


# ==========================================================================
# Tickets (dbo.sp_Ticket) - see StoredProcedures.sql
# Read-only actions so far (LIST, GET_BY_ID) - ticket_create/ticket_update
# (the write + JV-posting path) are still ORM-based pending a SAVE/UPDATE
# action here.
# ==========================================================================

def tickets_list(company_id):
    """One row per TicketLine joined to its Ticket header - views.tickets_list."""
    return exec_sp("dbo.sp_Ticket", {"Action": "LIST", "CompanyId": company_id})


def ticket_save(company_id, customer_name, header_fields, lines, jv_narration, jv_total_debit, jv_total_credit, ticket_id=None):
    """
    Creates or updates (when ticket_id is given) a Ticket + its TicketLines
    + its auto-posted JournalVoucher, all in ONE atomic dbo.sp_Ticket SAVE
    call - views.ticket_create/ticket_update. `header_fields` is a dict
    keyed by TICKET_HEADER_FIELDS (plus branch_name/supplier_name); `lines`
    is a list of dicts keyed by TICKET_LINE_FIELDS plus total_billed
    (pre-computed by the caller) and supplier_name. The JV's own line-by-
    line amounts/narration are computed in Python (views._compute_jv_lines)
    and passed in as a ready total here - only the totals and narration are
    persisted on the JournalVoucher row (its ledger-by-ledger breakdown is
    always recomputed live, never stored - see JournalVoucher.lines_json's
    own docstring). Raises StoredProcedureError on any validation failure.
    Returns {"id", "line_ids": [..], "voucher_id", "voucher_no", "was_created"}.
    """
    import json as _json
    params = {
        "Action": "SAVE", "Id": ticket_id, "CompanyId": company_id, "CustomerName": customer_name,
        "SupplierName": header_fields.get("supplier_name"), "BranchName": header_fields.get("branch_name"),
        "InvoiceNumber": header_fields.get("invoice_number"), "InvoiceDate": header_fields.get("invoice_date"),
        "InvoiceType": header_fields.get("invoice_type"), "BookingMode": header_fields.get("booking_mode"),
        "BookingType": header_fields.get("booking_type"), "BookingStatus": header_fields.get("booking_status"),
        "TravelType": header_fields.get("travel_type"), "UserName": header_fields.get("user_name"),
        "Currency": header_fields.get("currency"), "Roe": header_fields.get("roe"),
        "BookingGivenBy": header_fields.get("booking_given_by"), "BookingReference": header_fields.get("booking_reference"),
        "BookingRefDate": header_fields.get("booking_ref_date"), "AirlinePnr": header_fields.get("airline_pnr"),
        "GdsPnr": header_fields.get("gds_pnr"), "OfficeId": header_fields.get("office_id"),
        "PaymentMode": header_fields.get("payment_mode"), "PaymentGatewayRef": header_fields.get("payment_gateway_ref"),
        "AirlineCategory": header_fields.get("airline_category"),
        "LinesJson": _json.dumps(lines, default=str),
        "JvNarration": jv_narration, "JvTotalDebit": jv_total_debit, "JvTotalCredit": jv_total_credit,
    }
    row = exec_sp_one("dbo.sp_Ticket", params)
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not save this ticket.")
    line_ids = [int(x) for x in row["line_ids"].split(",")] if row.get("line_ids") else []
    return {
        "id": row["id"], "line_ids": line_ids, "voucher_id": row["voucher_id"],
        "voucher_no": row["voucher_no"], "was_created": bool(row.get("was_created")),
    }


def reschedule_tickets_list_for_balance(company_id, as_of_date=None, from_date=None):
    """
    One row per RescheduleAirlineTicketLine (raw/uncomputed fields only)
    joined to its header's balance-relevant fields, optionally date-
    filtered - views._ledger_balance_deltas' bulk RescheduleAirlineTicket+
    Lines read, replacing RescheduleAirlineTicket.objects.filter().
    prefetch_related().
    """
    return exec_sp("dbo.sp_RescheduleTicket", {
        "Action": "LIST_FOR_BALANCE", "CompanyId": company_id, "AsOfDate": as_of_date, "FromDate": from_date,
    })


def reschedule_tickets_list(company_id):
    """One row per RescheduleAirlineTicketLine joined to its header - views.reschedule_tickets_list."""
    return exec_sp("dbo.sp_RescheduleTicket", {"Action": "LIST", "CompanyId": company_id})


def vouchers_list(company_id):
    """Manual vouchers only - views.vouchers_list."""
    return exec_sp("dbo.sp_Voucher", {"Action": "LIST", "CompanyId": company_id})


def voucher_get(voucher_id, company_id):
    """One manual voucher by id - views.voucher_detail. None if not found."""
    return exec_sp_one("dbo.sp_Voucher", {"Action": "GET_BY_ID", "Id": voucher_id, "CompanyId": company_id})


def voucher_save(company_id, branch_name, voucher_type, voucher_date, narration, lines, voucher_id=None):
    """
    Creates or updates (when voucher_id is given) a manual Voucher -
    views.voucher_create/voucher_update. `lines` is the raw submitted
    [{ledger_id, debit, credit}, ...] list - validation (balance, ledger
    existence) and resolving each line's ledger_name happen inside the
    stored procedure. Raises StoredProcedureError on any validation failure.
    """
    import json as _json
    row = exec_sp_one("dbo.sp_Voucher", {
        "Action": "SAVE", "Id": voucher_id, "CompanyId": company_id, "BranchName": branch_name,
        "VoucherType": voucher_type, "VoucherDate": voucher_date, "Narration": narration,
        "LinesJson": _json.dumps(lines),
    })
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not save this voucher.")
    return row


def reschedule_ticket_get_header(reschedule_ticket_id, company_id):
    """Minimal existence-check + current id/original_ticket_id/booking_reference/airline_pnr - views.reschedule_ticket_update."""
    return exec_sp_one("dbo.sp_RescheduleTicket", {"Action": "GET_HEADER", "Id": reschedule_ticket_id, "CompanyId": company_id})


def reschedule_ticket_line_keys(reschedule_ticket_id):
    """(original_ticket_line_id, based_on_reschedule_line_id) for every line currently on this reschedule ticket - views.reschedule_ticket_update's skip-list."""
    return exec_sp("dbo.sp_RescheduleTicket", {"Action": "GET_LINE_KEYS", "Id": reschedule_ticket_id})


def reschedule_resolve_original_line_ids(reschedule_line_ids):
    """
    Resolves a batch of Rescheduled_Al_TicketLines ids back to their TRUE
    original AL_TicketLines id - views.cancellation_ticket_create's own
    chain-aware resolution. Returns {reschedule_line_id: original_ticket_line_id}.
    """
    import json as _json
    pairs = [{"reschedule_line_id": rid} for rid in reschedule_line_ids]
    rows = exec_sp("dbo.sp_RescheduleTicket", {"Action": "RESOLVE_ORIGINAL_LINE_IDS", "PairsJson": _json.dumps(pairs)})
    return {r["reschedule_line_id"]: r["original_ticket_line_id"] for r in rows}


def reschedule_resolve_lines(original_ticket_id, pairs):
    """
    Resolves chain info for a batch of {original_ticket_line_id,
    reschedule_line_id} pairs in ONE round trip - views.
    reschedule_ticket_create/update's original_lines/based_on_lines ORM
    lookups + eligibility pre-check. `pairs` is a list of dicts with those
    two keys (reschedule_line_id may be None/absent). Returns a list of
    row dicts, one per pair, in the same order.
    """
    import json as _json
    return exec_sp("dbo.sp_RescheduleTicket", {
        "Action": "RESOLVE_LINES", "OriginalTicketId": original_ticket_id, "PairsJson": _json.dumps(pairs),
    })


def reschedule_ticket_save(company_id, customer_name, header_fields, lines, jv_narration, jv_total_debit, jv_total_credit,
                            reschedule_ticket_id=None, original_ticket_id=None):
    """
    Creates or updates (when reschedule_ticket_id is given) a
    RescheduleAirlineTicket + its lines (wholesale replace on update) + its
    auto-posted JournalVoucher, atomically - views.reschedule_ticket_create/
    update. Mirrors ticket_save()'s shape; `lines` additionally carries
    original_ticket_line_id, based_on_reschedule_line_id and parent_pnr per
    line (already resolved by the caller via reschedule_resolve_lines()).
    Raises StoredProcedureError on any validation failure. Returns
    {"id", "line_ids": [..], "voucher_id", "voucher_no", "was_created"}.
    """
    import json as _json
    params = {
        "Action": "SAVE", "Id": reschedule_ticket_id, "CompanyId": company_id, "OriginalTicketId": original_ticket_id,
        "CustomerName": customer_name, "SupplierName": header_fields.get("supplier_name"),
        "BranchName": header_fields.get("branch_name"),
        "InvoiceNumber": header_fields.get("invoice_number"), "InvoiceDate": header_fields.get("invoice_date"),
        "InvoiceType": header_fields.get("invoice_type"), "BookingMode": header_fields.get("booking_mode"),
        "BookingType": header_fields.get("booking_type"), "BookingStatus": header_fields.get("booking_status"),
        "TravelType": header_fields.get("travel_type"), "UserName": header_fields.get("user_name"),
        "Currency": header_fields.get("currency"), "Roe": header_fields.get("roe"),
        "BookingGivenBy": header_fields.get("booking_given_by"), "BookingReference": header_fields.get("booking_reference"),
        "BookingRefDate": header_fields.get("booking_ref_date"), "AirlinePnr": header_fields.get("airline_pnr"),
        "GdsPnr": header_fields.get("gds_pnr"), "OfficeId": header_fields.get("office_id"),
        "PaymentMode": header_fields.get("payment_mode"), "PaymentGatewayRef": header_fields.get("payment_gateway_ref"),
        "AirlineCategory": header_fields.get("airline_category"),
        "LinesJson": _json.dumps(lines, default=str),
        "JvNarration": jv_narration, "JvTotalDebit": jv_total_debit, "JvTotalCredit": jv_total_credit,
    }
    row = exec_sp_one("dbo.sp_RescheduleTicket", params)
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not save this reschedule ticket.")
    line_ids = [int(x) for x in row["line_ids"].split(",")] if row.get("line_ids") else []
    return {
        "id": row["id"], "line_ids": line_ids, "voucher_id": row["voucher_id"],
        "voucher_no": row["voucher_no"], "was_created": bool(row.get("was_created")),
    }


def tickets_list_for_balance(company_id, as_of_date=None, from_date=None):
    """
    One row per TicketLine (raw/uncomputed fields only) joined to its
    Ticket header's balance-relevant fields, optionally date-filtered -
    views._ledger_balance_deltas' bulk Ticket+TicketLines read, replacing
    Ticket.objects.filter().prefetch_related().
    """
    return exec_sp("dbo.sp_Ticket", {
        "Action": "LIST_FOR_BALANCE", "CompanyId": company_id, "AsOfDate": as_of_date, "FromDate": from_date,
    })


def tickets_invoice_numbers_by_type(company_id, invoice_type, from_date=None):
    """Every (invoice_number, invoice_date) under this Invoice Type, from both Tickets and RescheduleAirlineTickets - views.voucher_type_next_number."""
    return exec_sp("dbo.sp_Ticket", {
        "Action": "LIST_INVOICE_NUMBERS_BY_TYPE", "CompanyId": company_id, "InvoiceType": invoice_type, "FromDate": from_date,
    })


def ticket_get(ticket_id, company_id):
    """
    One ticket's header + its lines - views.ticket_detail. Two separate
    single-result-set calls (GET_HEADER, GET_LINES), per the house Single
    Result Set Rule. Returns (header_dict, [line_dict, ...]) or (None, None)
    if not found.
    """
    header = exec_sp_one("dbo.sp_Ticket", {"Action": "GET_HEADER", "Id": ticket_id, "CompanyId": company_id})
    if not header or header.get("status") == "Error":
        return None, None
    lines = exec_sp("dbo.sp_Ticket", {"Action": "GET_LINES", "Id": ticket_id, "CompanyId": company_id})
    return header, lines


# ==========================================================================
# Cancellation (dbo.sp_CancellationTicket) - see StoredProcedures.sql
# Since 2026-10-07 SAVE/UPDATE also post the cancellation's own separate
# Journal Voucher (category AIRLINE_CANCELLATION, ALC-n) in the same
# transaction - totals/narration computed in Python by
# views._compute_cancellation_jv_lines, passed in here.
# ==========================================================================

def cancellation_tickets_list(company_id):
    """One row per cancelled line (flat shape for the Find modal) - views.cancellation_tickets_list."""
    return exec_sp("dbo.sp_CancellationTicket", {"Action": "LIST", "CompanyId": company_id})


def cancellation_ticket_get(cancellation_id, company_id):
    """One cancellation's header + its lines - views.cancellation_ticket_detail. Returns (header, lines) or (None, None)."""
    header = exec_sp_one("dbo.sp_CancellationTicket", {"Action": "GET_HEADER", "Id": cancellation_id, "CompanyId": company_id})
    if not header or header.get("status") == "Error":
        return None, None
    lines = exec_sp("dbo.sp_CancellationTicket", {"Action": "GET_LINES", "Id": cancellation_id, "CompanyId": company_id})
    return header, lines


def cancellation_ticket_save(company_id, original_ticket_id, customer_name, header_fields, lines,
                             jv_narration, jv_total_debit, jv_total_credit):
    """
    Creates a Cancellation_AL_Tickets + its lines + its own Cancellation
    Journal Voucher, all in ONE atomic dbo.sp_CancellationTicket SAVE call -
    views.cancellation_ticket_create. `lines` is a list of dicts carrying
    every CancellationAirlineTicketLine field plus supplier_name and
    original_ticket_line_id. jv_* are the already-computed (and already
    balance-checked) JV narration/totals - Main JV + FOP leg together.
    Raises StoredProcedureError on any validation failure (bad customer/
    supplier, duplicate invoice/reference/ticket_no, a line not belonging to
    the original ticket, a line already cancelled, or an unbalanced/missing
    JV). Returns {"id", "line_ids": [..], "voucher_id", "voucher_no"}.
    """
    import json as _json
    params = {
        "Action": "SAVE", "CompanyId": company_id, "OriginalTicketId": original_ticket_id, "CustomerName": customer_name,
        "SupplierName": header_fields.get("supplier_name"), "BranchName": header_fields.get("branch_name"),
        "InvoiceNumber": header_fields.get("invoice_number"), "InvoiceDate": header_fields.get("invoice_date"),
        "InvoiceType": header_fields.get("invoice_type"), "BookingMode": header_fields.get("booking_mode"),
        "BookingType": header_fields.get("booking_type"), "BookingStatus": header_fields.get("booking_status"),
        "TravelType": header_fields.get("travel_type"), "UserName": header_fields.get("user_name"),
        "Currency": header_fields.get("currency"), "Roe": header_fields.get("roe"),
        "BookingGivenBy": header_fields.get("booking_given_by"),
        "CancellationReference": header_fields.get("cancellation_reference"),
        "CancellationRefDate": header_fields.get("cancellation_ref_date"),
        "AirlinePnr": header_fields.get("airline_pnr"), "GdsPnr": header_fields.get("gds_pnr"),
        "OfficeId": header_fields.get("office_id"), "PaymentMode": header_fields.get("payment_mode"),
        "PaymentGatewayRef": header_fields.get("payment_gateway_ref"), "AirlineCategory": header_fields.get("airline_category"),
        "LinesJson": _json.dumps(lines, default=str),
        "JvNarration": jv_narration, "JvTotalDebit": jv_total_debit, "JvTotalCredit": jv_total_credit,
    }
    row = exec_sp_one("dbo.sp_CancellationTicket", params)
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not save this cancellation.")
    line_ids = [int(x) for x in row["line_ids"].split(",")] if row.get("line_ids") else []
    return {"id": row["id"], "line_ids": line_ids, "voucher_id": row.get("voucher_id"), "voucher_no": row.get("voucher_no")}


def cancellation_ticket_update(cancellation_id, company_id, header_fields, lines,
                               jv_narration, jv_total_debit, jv_total_credit):
    """
    Edits an already-saved Cancellation - views.cancellation_ticket_update.
    Only the fields that were editable at creation time (header: Invoice
    Date/Type, User Name, Payment Mode/Gateway Ref, Cancellation
    Reference/Ref Date; `lines`: each dict keyed by its own already-saved
    Cancellation_Al_TicketLines id plus the Base Fare/Discount/Commission/
    Markup/Service Fee/penalty/Markup Reversal fields), and re-posts the
    cancellation's own Journal Voucher in place with the recomputed jv_*
    totals. Raises StoredProcedureError on any validation failure
    (cancellation not found, duplicate invoice/reference, unbalanced/missing
    JV). Returns {"id", "voucher_id", "voucher_no"}.
    """
    import json as _json
    params = {
        "Action": "UPDATE", "Id": cancellation_id, "CompanyId": company_id,
        "InvoiceNumber": header_fields.get("invoice_number"), "InvoiceDate": header_fields.get("invoice_date"),
        "InvoiceType": header_fields.get("invoice_type"), "UserName": header_fields.get("user_name"),
        "PaymentMode": header_fields.get("payment_mode"), "PaymentGatewayRef": header_fields.get("payment_gateway_ref"),
        "CancellationReference": header_fields.get("cancellation_reference"),
        "CancellationRefDate": header_fields.get("cancellation_ref_date"),
        "LinesJson": _json.dumps(lines, default=str),
        "JvNarration": jv_narration, "JvTotalDebit": jv_total_debit, "JvTotalCredit": jv_total_credit,
    }
    row = exec_sp_one("dbo.sp_CancellationTicket", params)
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not update this cancellation.")
    return {"id": row["id"], "voucher_id": row.get("voucher_id"), "voucher_no": row.get("voucher_no")}



# ==========================================================================
# User Management (dbo.sp_AppUser / sp_MenuMaster / sp_UserMenuAccess) -
# see StoredProcedures.sql. No login/session system exists yet - these
# only back the User Management page's own CRUD + per-menu Access modal.
# ==========================================================================

def app_user_get(user_id):
    """One user by id - views.app_user_list's ?id= branch. None if not found."""
    return exec_sp_one("dbo.sp_AppUser", {"Action": "LIST", "Id": user_id})


def app_user_get_by_email(email):
    """One user by email, including password_hash - views.auth_login only. None if not found."""
    return exec_sp_one("dbo.sp_AppUser", {"Action": "GET_BY_EMAIL", "Email": email})


def app_user_list():
    """Every user, ordered by name - views.app_user_list's bare GET."""
    return exec_sp("dbo.sp_AppUser", {"Action": "LIST"})


def app_user_save(fields, user_id=None):
    """
    Upserts an AppUsers row - views.app_user_save. `fields` is the
    already-normalized dict views.py builds (full_name, email, role, ...).
    Raises StoredProcedureError on validation/duplicate-email failure, or
    if this would leave zero active Super Admins.
    """
    params = {
        "Action": "SAVE", "Id": user_id,
        "FullName": fields.get("full_name"), "Email": fields.get("email"),
        "Role": fields.get("role"), "BranchName": fields.get("branch_name"),
        "IsSuperAdmin": fields.get("is_super_admin"), "IsActive": fields.get("is_active"),
        "PasswordHash": fields.get("password_hash"),
    }
    row = exec_sp_one("dbo.sp_AppUser", params)
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not save this user.")
    return row


def app_user_delete(user_id):
    """Deletes an AppUsers row - views.app_user_delete. Raises StoredProcedureError if not found or last Super Admin."""
    row = exec_sp_one("dbo.sp_AppUser", {"Action": "DELETE", "Id": user_id})
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not delete this user.")
    return row


def menu_master_list():
    """Every active menu, ordered for grouped rendering - views.menu_master_list."""
    return exec_sp("dbo.sp_MenuMaster", {"Action": "LIST"})


def user_menu_access_get(user_id):
    """
    Every active menu for one user, each with its can_view/add/edit/delete
    flags (false for any menu never explicitly granted) - views.user_menu_access_get.
    Raises StoredProcedureError if the user doesn't exist.
    """
    rows = exec_sp("dbo.sp_UserMenuAccess", {"Action": "GET", "UserId": user_id})
    if rows and rows[0].get("status") == "Error":
        raise StoredProcedureError(rows[0].get("error") or "Could not load this user's access.")
    return rows


def user_menu_access_save(user_id, access_list, created_by=None):
    """
    Upserts every {menu_key, can_view, can_add, can_edit, can_delete} row
    in `access_list` for this user, in one transaction - views.user_menu_access_save.
    Raises StoredProcedureError if the user doesn't exist.
    """
    import json as _json
    params = {
        "Action": "SAVE", "UserId": user_id, "CreatedBy": created_by,
        "AccessJson": _json.dumps(access_list, default=str),
    }
    row = exec_sp_one("dbo.sp_UserMenuAccess", params)
    if row and row.get("status") == "Error":
        raise StoredProcedureError(row.get("error") or "Could not save this user's access.")
    return row
