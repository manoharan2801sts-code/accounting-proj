"""
JV field map — driven by Master Mapping now (project owner's update,
2026-09-18): every JV line's ledger is resolved from Master Mapping's
Ledger Name (Master) for the given (masters_category, field_name), except
Customer and Supplier, which resolve to the ticket's own chosen Ledger (the
one existing "resolve to a real Ledger row" logic, unchanged). Payment Mode
/ FOP no longer change which lines post or their formulas — every
combination produces the exact same JV structure (superseded the old
PAYMENT_MODE_SETTLEMENT / FOP_SETTLEMENT / PAYMENT_INSTRUMENT_LEDGERS
hardcode this file used to hold).

Per the project owner's explicit instruction (2026-09-18): the two
Markup/Service Fee Credit lines below (once fed by the Sup-side amount,
once by the customer-side amount) are intentional, kept as written even
though the resulting JV will not debit-credit balance — do not merge or
drop either line. Per a later instruction (2026-09-24), the Sup-side one
of that pair no longer reuses the SAME "Markup A/c" / "Addl Markup A/c" /
"Service Fee A/c" / "Addl Service Fee A/c" field names as the customer-side
one — it now resolves via its own separate "Consolidator Markup A/c" /
"Consolidator Addl Markup A/c" / "Consolidator Service Fee A/c" /
"Consolidator Addl Service Fee A/c" fields instead (masters_category is
still "Earnings From Customer" - see the "Consolidator Earnings"
sub-heading on Master Mapping's Customer tab, master-mapping.html), so the
two lines can be mapped to two genuinely different income ledgers.

The two Credit "Output IGST A/c" entries below (amount_key "supp_gst" and
"gst") are the ONE exception to that — per a later instruction
(2026-09-23), views._compute_jv_lines() does NOT emit them as two
separate/duplicate "Output IGST A/c" rows. It combines both amounts into
one Output GST total and posts that as a single set of lines, either one
combined "Output IGST A/c" Credit line (customer's State != Company
Master's State) or a half/half "Output CGST A/c" + "Output SGST A/c"
Credit pair (same State) — see that function for the actual logic. These
two entries stay in this list only so their amount_keys are still picked
up by that special-cased branch.

Each entry: (dr_cr, masters_category, field_name, amount_key). amount_key
looks up its total in the role_amounts dict built in
views._compute_jv_lines(); the ledger itself is looked up per line via
MasterMapping(company_id, product_type="Airline", masters_category,
field_name).
"""

JV_LINE_MAP = [
    ("Credit", "Earnings From Supplier", "Commission A/c", "commission"),
    ("Debit", "GST and TDS", "Commission TDS A/c", "commission_tds"),
    ("Debit", "Expenditure To Supplier", "Supplier Markup A/c", "supp_markup"),
    ("Debit", "Expenditure To Supplier", "Supplier Addl Markup A/c", "supp_addl_markup"),
    ("Debit", "Expenditure To Supplier", "Supplier Service Fee A/c", "supp_service_fee"),
    ("Debit", "Expenditure To Supplier", "Supplier Addl Service Fee A/c", "supp_addl_service_fee"),
    ("Debit", "GST and TDS", "Input IGST A/c", "supp_gst"),
    ("Credit", "Earnings From Customer", "Consolidator Markup A/c", "supp_markup"),
    ("Credit", "Earnings From Customer", "Consolidator Addl Markup A/c", "supp_addl_markup"),
    ("Credit", "Earnings From Customer", "Consolidator Service Fee A/c", "supp_service_fee"),
    ("Credit", "Earnings From Customer", "Consolidator Addl Service Fee A/c", "supp_addl_service_fee"),
    ("Credit", "GST and TDS", "Output IGST A/c", "supp_gst"),
    ("Debit", "Expenditure To Customer", "Discount A/c", "discount"),
    ("Credit", "GST and TDS", "Discount TDS A/c", "discount_tds"),
    ("Credit", "Earnings From Customer", "Markup A/c", "markup"),
    ("Credit", "Earnings From Customer", "Addl Markup A/c", "addl_markup"),
    ("Credit", "Earnings From Customer", "SSR Markup A/c", "ssr_markup"),
    ("Credit", "Earnings From Customer", "Service Fee A/c", "service_fee"),
    ("Credit", "Earnings From Customer", "Addl Service Fee A/c", "addl_service_fee"),
    ("Credit", "Earnings From Customer", "SSR Service Fee A/c", "ssr_service_fee"),
    ("Credit", "GST and TDS", "Output IGST A/c", "gst"),
]
