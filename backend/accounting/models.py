"""
Ledger_Groups — Django model
-----------------------------------------------------------------
Stores the Chart of Accounts GROUP hierarchy only (Assets, Current
Assets, Sundry Debtors, etc.) — not individual ledgers. This mirrors
what's shown under "Chart of Accounts" in the UI: a tree of group
nodes, each optionally nested under a parent group.

Requires a Django MSSQL backend, since Django has no native MSSQL
driver. Install and configure ONE of:
    pip install mssql-django      (actively maintained, recommended)
    pip install django-pyodbc-azure
and set ENGINE = "mssql" in settings.py DATABASES, plus a working
ODBC Driver 17/18 for SQL Server installed on the machine running
Django.

Usage once wired into an app (e.g. `accounting`):
    python manage.py makemigrations accounting
    python manage.py migrate accounting
Since you're creating the table manually from schema.sql instead,
run migrations with --fake after creating the table by hand, so
Django's migration history matches without re-running the DDL:
    python manage.py migrate accounting --fake
"""
from decimal import Decimal
from django.db import models

# Process-wide cache for TicketLine.computed_gst's per-(company, field_name)
# Master-Mapping-ledger GST% lookup — without it, a Chart-of-Accounts/Cash-
# Bank-Book balance recompute across every ticket in a company re-queries
# the same handful of mappings once per line (twice, since compute_total()
# also calls computed_gst), which is negligible against local MySQL but
# times out gunicorn's worker against TiDB Cloud's network round-trip once
# there are more than a few dozen tickets. Cleared from views.py whenever
# Master Mapping or a mapped Ledger's own gst_percentage is edited.
_gst_pct_cache = {}


def clear_gst_pct_cache():
    _gst_pct_cache.clear()


class LedgerGroup(models.Model):
    ACCOUNT_TYPE_CHOICES = [
        ("ASSET", "Asset"),
        ("LIABILITY", "Liability"),
        ("INCOME", "Income"),
        ("EXPENSE", "Expense"),
        ("EQUITY", "Equity"),
    ]

    id = models.AutoField(primary_key=True)

    # Multi-company support (India entity, UAE entity, etc.) — every group
    # belongs to exactly one company, same pattern as the rest of the app.
    company_id = models.IntegerField()

    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, null=True, blank=True)

    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES)

    # Self-referencing FK builds the tree: Assets -> Current Assets -> Sundry Debtors.
    # null=True means top-level groups (Assets, Liabilities, Income, Expenses, Equity)
    # have no parent.
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,   # block deleting a group that still has children
        null=True,
        blank=True,
        related_name="children",
        db_column="parent_id",
    )

    # True for group/header nodes (Assets, Current Assets). Kept even though this
    # table is groups-only, in case a later migration merges groups + ledgers into
    # one Chart-of-Accounts table — matches the pattern already used elsewhere.
    is_group = models.BooleanField(default=True)

    # Seeded/system groups (Assets, Liabilities, etc.) that shouldn't be
    # deleted or renamed by users, matches the app's existing "is_system" idea.
    is_system = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "Ledger_Groups"
        # A group name should be unique within its own company + parent,
        # so you can't accidentally create two "Sundry Debtors" under Assets.
        constraints = [
            models.UniqueConstraint(
                fields=["company_id", "parent", "name"],
                name="uq_ledger_group_company_parent_name",
            )
        ]
        indexes = [
            models.Index(fields=["company_id"]),
            models.Index(fields=["parent"]),
        ]
        ordering = ["company_id", "parent_id", "name"]

    def __str__(self):
        return self.name

    def is_descendant_of(self, other_id):
        """Cycle guard — prevents a group being reparented under its own
        descendant. Call this before saving a parent change."""
        node = self.parent
        while node is not None:
            if node.id == other_id:
                return True
            node = node.parent
        return False


class Ledger(models.Model):
    """
    The actual leaf accounts created via the "New Ledger" form — e.g. an
    individual customer under Sundry Debtors, a bank account under Bank
    Accounts, a supplier under Sundry Creditors. Always sits under a
    LedgerGroup via `group`.

    One wide table with every category-specific field nullable, matching
    the flat payload shape the frontend's page-ledger-entry.js already
    builds (bank fields, debtor/India fields, debtor/UAE fields, creditor
    fields, duties & taxes fields, income/expense tax-settings fields).
    Only the fields relevant to whichever group category was picked get
    filled in; the rest stay NULL.
    """
    ACCOUNT_TYPE_CHOICES = LedgerGroup.ACCOUNT_TYPE_CHOICES
    BALANCE_TYPE_CHOICES = [("Debit", "Debit"), ("Credit", "Credit")]

    id = models.AutoField(primary_key=True)
    company_id = models.IntegerField()

    name = models.CharField(max_length=150)
    group = models.ForeignKey(
        LedgerGroup, on_delete=models.PROTECT, related_name="ledgers", db_column="group_id"
    )
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES)
    ledger_category = models.CharField(max_length=20)  # BANK / DEBTOR / CREDITOR / INCOME / EXPENSE / DUTIES_TAXES / OTHER

    opening_balance = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    opening_balance_type = models.CharField(max_length=10, choices=BALANCE_TYPE_CHOICES, default="Debit")

    # Bank
    bank_account_no = models.CharField(max_length=40, null=True, blank=True)
    bank_branch = models.CharField(max_length=100, null=True, blank=True)
    ifsc_code = models.CharField(max_length=15, null=True, blank=True)
    swift_code = models.CharField(max_length=15, null=True, blank=True)

    # Debtor — shared
    alias_name = models.CharField(max_length=100, null=True, blank=True)
    address_line1 = models.CharField(max_length=150, null=True, blank=True)
    address_line2 = models.CharField(max_length=150, null=True, blank=True)
    agent_id = models.CharField(max_length=30, null=True, blank=True)
    maintain_balance_bill_wise = models.CharField(max_length=5, null=True, blank=True)  # "Yes" / "No"
    place_of_supply = models.CharField(max_length=60, null=True, blank=True)

    # Credit terms — customer_type/credit_limit are Debtor-only (Customers
    # page); credit_days applies to either side (Customers AND Suppliers
    # pages both show it).
    CUSTOMER_TYPE_CHOICES = [("RETAIL", "Retail"), ("CORPORATE", "Corporate"), ("AGENT", "Agent")]
    customer_type = models.CharField(max_length=20, choices=CUSTOMER_TYPE_CHOICES, null=True, blank=True)
    credit_limit = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, default=0)
    credit_days = models.IntegerField(null=True, blank=True, default=0)

    # Debtor — India
    city = models.CharField(max_length=60, null=True, blank=True)
    pincode = models.CharField(max_length=10, null=True, blank=True)
    state_name = models.CharField(max_length=60, null=True, blank=True)
    gst_no = models.CharField(max_length=20, null=True, blank=True)
    gst_registration_type = models.CharField(max_length=20, null=True, blank=True)
    pan_no = models.CharField(max_length=15, null=True, blank=True)

    # Debtor — UAE
    emirate = models.CharField(max_length=30, null=True, blank=True)
    po_box_no = models.CharField(max_length=20, null=True, blank=True)
    vat_trn_no = models.CharField(max_length=20, null=True, blank=True)
    trade_license_no = models.CharField(max_length=30, null=True, blank=True)
    trade_license_expiry = models.DateField(null=True, blank=True)

    # Creditor
    creditor_type = models.CharField(max_length=30, null=True, blank=True)
    supplier_code = models.CharField(max_length=30, null=True, blank=True)
    office_id = models.CharField(max_length=30, null=True, blank=True)

    # Duties & Taxes
    tax_category = models.CharField(max_length=10, null=True, blank=True)  # GST / TDS / Others
    tax_type = models.CharField(max_length=10, null=True, blank=True)      # IGST / CGST / SGST

    # Income / Expense tax settings
    gst_applicable = models.BooleanField(default=False)
    gst_tax_type = models.CharField(max_length=10, null=True, blank=True)
    gst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tds_applicable = models.BooleanField(default=False)
    tds_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    hsn_code = models.CharField(max_length=15, null=True, blank=True)
    tcs_applicable = models.BooleanField(default=False)
    tcs_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "Ledgers"
        constraints = [
            models.UniqueConstraint(fields=["company_id", "name"], name="uq_ledger_company_name"),
            models.UniqueConstraint(
                fields=["agent_id"], name="uq_ledger_agent_id",
                condition=models.Q(agent_id__isnull=False),
            ),
        ]
        indexes = [
            models.Index(fields=["company_id"]),
            models.Index(fields=["group"]),
        ]

    def __str__(self):
        return self.name

    @property
    def signed_balance(self):
        """Positive for Debit, negative for Credit — matches the sign
        convention the frontend already uses to redisplay balance type."""
        return self.opening_balance if self.opening_balance_type == "Debit" else -self.opening_balance


class Ticket(models.Model):
    """The invoice/booking header — Part 1 + Part 2 of the New Ticket form."""

    BOOKING_MODE_CHOICES = [("Manual", "Manual"), ("Auto Push", "Auto Push")]
    BOOKING_STATUS_CHOICES = [("Confirmed", "Confirmed"), ("Re-Scheduled", "Re-Scheduled")]
    TRAVEL_TYPE_CHOICES = [("Domestic", "Domestic"), ("International", "International")]
    PAYMENT_MODE_CHOICES = [("Top-up", "Top-up"), ("Payment Gateway", "Payment Gateway")]
    AIRLINE_CATEGORY_CHOICES = [("LCC", "LCC"), ("FSC", "FSC"), ("OSC", "OSC")]

    id = models.AutoField(primary_key=True)
    company_id = models.IntegerField()
    branch_name = models.CharField(max_length=100, null=True, blank=True)

    invoice_number = models.CharField(max_length=20)
    invoice_date = models.DateField()
    # Free text, matched against VoucherType.name (Masters > Voucher Type) -
    # no longer a fixed choices list, since the dropdown is now populated
    # from whatever voucher types the company has defined there.
    invoice_type = models.CharField(max_length=100, null=True, blank=True)
    booking_mode = models.CharField(max_length=20, choices=BOOKING_MODE_CHOICES, default="Manual")
    booking_type = models.CharField(max_length=30, null=True, blank=True)
    booking_status = models.CharField(max_length=20, choices=BOOKING_STATUS_CHOICES, null=True, blank=True)

    customer = models.ForeignKey(
        Ledger, on_delete=models.PROTECT, related_name="tickets_as_customer", db_column="customer_ledger_id"
    )
    supplier = models.ForeignKey(
        Ledger, on_delete=models.PROTECT, related_name="tickets_as_supplier",
        null=True, blank=True, db_column="supplier_ledger_id"
    )

    travel_type = models.CharField(max_length=20, choices=TRAVEL_TYPE_CHOICES, null=True, blank=True)
    user_name = models.CharField(max_length=100, null=True, blank=True)
    currency = models.CharField(max_length=5, default="INR")
    roe = models.DecimalField(max_digits=10, decimal_places=4, default=1)
    booking_given_by = models.CharField(max_length=25, null=True, blank=True)

    booking_reference = models.CharField(max_length=30)
    booking_ref_date = models.DateField(null=True, blank=True)
    airline_pnr = models.CharField(max_length=13, null=True, blank=True)
    gds_pnr = models.CharField(max_length=13, null=True, blank=True)
    office_id = models.CharField(max_length=30, null=True, blank=True)

    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES, null=True, blank=True)
    # Only meaningful when payment_mode == "Payment Gateway" — the gateway's
    # own transaction/reference number for this booking.
    payment_gateway_ref = models.CharField(max_length=60, null=True, blank=True)
    airline_category = models.CharField(max_length=5, choices=AIRLINE_CATEGORY_CHOICES, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "Tickets"
        constraints = [
            models.UniqueConstraint(fields=["company_id", "invoice_number"], name="uq_ticket_company_invoice_no"),
            models.UniqueConstraint(fields=["company_id", "booking_reference"], name="uq_ticket_company_booking_ref"),
        ]
        indexes = [models.Index(fields=["company_id"])]

    def __str__(self):
        return self.invoice_number


class TicketLine(models.Model):
    """One passenger/ticket within a Ticket's booking — Part 3, repeatable grid."""

    PAX_TYPE_CHOICES = [("Adult", "Adult"), ("Child", "Child"), ("Infant", "Infant")]
    DISC_TYPE_CHOICES = [("Percentage", "Percentage"), ("Flat", "Flat")]
    STATUS_CHOICES = [
        ("ISSUED", "Issued"), ("REFUNDED", "Refunded"), ("VOID", "Void"), ("EXCHANGED", "Exchanged"),
    ]
    FOP_CHOICES = [("Own Card", "Own Card"), ("Client Card", "Client Card"), ("Cash", "Cash")]

    id = models.AutoField(primary_key=True)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="lines", db_column="ticket_id")

    # Moved into the Add Sector popup — airline can differ per sector on a
    # multi-city booking, not just once per passenger line, same reasoning
    # as flight_no/cabin/travel_class/fare_type below: comma-joined, one
    # value per sector, in the same order as `sector`.
    airline_code = models.CharField(max_length=200, null=True, blank=True)
    airline_name = models.CharField(max_length=200, null=True, blank=True)
    # Moved here from the Ticket header — airline category (LCC/FSC/OSC) can differ
    # per passenger segment, not just once per booking. Reuses Ticket's choice list.
    airline_category = models.CharField(max_length=5, choices=Ticket.AIRLINE_CATEGORY_CHOICES, null=True, blank=True)
    # Multi-city: one passenger line can carry several sectors, each captured
    # via the Add Sector popup on the frontend and comma-joined here in the
    # same order — e.g. sector "BOM-DXB,DXB-JFK", flight_no "5259,EK202" one
    # value per sector. travel_date is plain text (not a real DateField)
    # for the same reason: multi-city segments can have different dates,
    # comma-joined when they differ, a single value when they don't — a
    # DateField can't hold that, so no date-type validation happens here,
    # only on each per-sector value the frontend enters via its date-group.
    flight_no = models.CharField(max_length=200, null=True, blank=True)
    ticket_no = models.CharField(max_length=30)
    passenger_name = models.CharField(max_length=50)
    pax_type = models.CharField(max_length=10, choices=PAX_TYPE_CHOICES, default="Adult")
    sector = models.CharField(max_length=200, null=True, blank=True)
    travel_date = models.CharField(max_length=200, null=True, blank=True)
    cabin = models.CharField(max_length=200, null=True, blank=True)
    travel_class = models.CharField(max_length=200, null=True, blank=True)
    fare_type = models.CharField(max_length=300, null=True, blank=True)

    # Fare breakup
    basic_fare = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    yq = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    yr = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    k3_tax = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_others = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    seat = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    meal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    baggage = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    other_ssr = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    # Customer discount
    disc_on = models.CharField(max_length=20, null=True, blank=True)
    disc_type = models.CharField(max_length=12, choices=DISC_TYPE_CHOICES, null=True, blank=True)
    disc_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tds_per = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    # PG Charges - only shown/entered when Payment Mode = "Payment Gateway".
    # Posts as a Debit against whichever gateway's PG Master -> PG Charges
    # Master ledger is mapped, netted against that same gateway's own
    # ledger credit - see _pg_receipt_lines() in views.py.
    pg_charges = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    # Markup / service fee / GST
    markup = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    addl_markup = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    ssr_markup = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    service_fee = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    addl_service_fee = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    ssr_service_fee = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    gst_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    # Supplier commission (mirrors customer discount, but against the supplier)
    supp_comm_on = models.CharField(max_length=20, null=True, blank=True)
    supp_comm_type = models.CharField(max_length=12, choices=DISC_TYPE_CHOICES, null=True, blank=True)
    supp_comm_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    supp_tds_per = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    # Markup / service fee / GST on the Supplier Commission side — mirrors
    # the Client Accounting fields above, but tracked separately since they
    # apply against the supplier commission, not the customer bill.
    supp_markup = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    supp_addl_markup = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    supp_service_fee = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    supp_addl_service_fee = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    supp_gst_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    # Computed at save time server-side (never trust the client's total)
    total_billed = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="ISSUED")

    # Moved here from the Ticket header — each passenger/segment can be sourced from
    # a different supplier (Sundry Creditor ledger), so this is now per-line, not
    # once per booking. Nullable: a line can be saved before a supplier is picked;
    # see _compute_jv_lines() in views.py for how an unpicked supplier is handled
    # in the auto-posted JV.
    supplier = models.ForeignKey(
        Ledger, on_delete=models.PROTECT, related_name="ticketlines_as_supplier",
        null=True, blank=True, db_column="supplier_ledger_id"
    )
    office_id = models.CharField(max_length=30, null=True, blank=True)
    fop = models.CharField(max_length=20, choices=FOP_CHOICES, null=True, blank=True)
    # Which specific FOP Master card (Own Card/Client Card) was used — only
    # meaningful when fop isn't "Cash". Free text, not an FK: FOP Master
    # cards can be edited/deactivated later without breaking old tickets'
    # historical record of which card number was charged at the time.
    card_number = models.CharField(max_length=40, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "TicketLines"
        constraints = [
            models.UniqueConstraint(fields=["ticket_no"], name="uq_ticketline_ticket_no"),
        ]
        indexes = [models.Index(fields=["ticket"])]

    def __str__(self):
        return self.ticket_no

    def compute_total(self):
        """Same formula as the frontend's computeFareLine() — recomputed
        here so the server never trusts whatever total the browser sent.
        Every term explicitly floated - computed_gst always returns a
        plain float (see its own docstring), so mixing it in unfloated
        with the rest of this instance's fields would raise a Decimal/
        float TypeError whenever this runs on an already-saved (DB-
        fetched) instance, where every other field here is a Decimal."""
        return float(self.supplier_cost) - float(self.computed_discount) + float(self.computed_tds) \
            + float(self.markup) + float(self.addl_markup) + float(self.ssr_markup) \
            + float(self.service_fee) + float(self.addl_service_fee) + float(self.ssr_service_fee) + float(self.computed_gst) \
            + float(self.supp_markup) + float(self.supp_addl_markup) \
            + float(self.supp_service_fee) + float(self.supp_addl_service_fee) + float(self.computed_supp_gst)

    @property
    def supplier_cost(self):
        """The raw fare components with no markup/fee/tax/discount — what
        the airline/supplier is actually owed. Used as the Supplier credit
        line on the auto-generated JV."""
        return (self.basic_fare + self.yq + self.yr + self.k3_tax + self.tax_others
                + self.seat + self.meal + self.baggage + self.other_ssr)

    @property
    def computed_discount(self):
        base_map = {
            "Basic": self.basic_fare,
            "Basic + YQ": self.basic_fare + self.yq,
            "Basic + YR": self.basic_fare + self.yr,
            "Basic + YQ + YR": self.basic_fare + self.yq + self.yr,
            "Gross": self.supplier_cost,
        }
        disc_base = base_map.get(self.disc_on, 0)
        if self.disc_type == "Percentage":
            return disc_base * (self.disc_value / 100)
        if self.disc_type == "Flat":
            return self.disc_value
        return 0

    @property
    def computed_tds(self):
        return self.computed_discount * (self.tds_per / 100)

    @property
    def computed_gst(self):
        """
        GST Amount = each Client Accounting fee component times its OWN
        mapped ledger's GST% (set on that Ledger, resolved via Master
        Mapping), not a single flat percentage typed on the line:
          (Service Fee * Service Fee A/c's ledger GST%)
          + (Addl Service Fee * Addl Service Fee A/c's ledger GST%)
          + (SSR Service Fee * SSR Service Fee A/c's ledger GST%)
        Same formula regardless of Payment Mode - PG Charges never
        contributes to GST Amount (even when Payment Mode = "Payment
        Gateway"). gst_pct itself is unused now (kept, always 0 - the
        field was removed from the UI) - see page-ticket-entry.js.
        """
        company_id = self.ticket.company_id

        def field_ledger_gst_pct(field_name):
            cache_key = (company_id, field_name)
            if cache_key not in _gst_pct_cache:
                m = MasterMapping.objects.filter(
                    company_id=company_id, product_type="Airline", field_name=field_name
                ).select_related("ledger").first()
                # Cast to float - self.service_fee etc. are plain Python floats
                # before this line has ever been saved (ticket_create/
                # ticket_update build the instance from _safe_decimal() floats,
                # not Decimals) but real Decimals once re-fetched from the DB
                # (e.g. _compute_jv_lines/_ledger_balance_deltas iterating
                # saved TicketLines) - mixing a Decimal ledger.gst_percentage
                # with whichever this instance currently holds raises
                # "unsupported operand type(s) for *: 'float'/'decimal.Decimal'
                # and 'decimal.Decimal'/'float'" depending on which side it is,
                # so every operand here is explicitly floated first.
                _gst_pct_cache[cache_key] = float(m.ledger.gst_percentage) if m and m.ledger_id else 0.0
            return _gst_pct_cache[cache_key]

        return (
            float(self.service_fee) * field_ledger_gst_pct("Service Fee A/c") / 100
            + float(self.addl_service_fee) * field_ledger_gst_pct("Addl Service Fee A/c") / 100
            + float(self.ssr_service_fee) * field_ledger_gst_pct("SSR Service Fee A/c") / 100
        )

    @property
    def computed_supp_commission(self):
        base_map = {
            "Basic": self.basic_fare,
            "Basic + YQ": self.basic_fare + self.yq,
            "Basic + YR": self.basic_fare + self.yr,
            "Basic + YQ + YR": self.basic_fare + self.yq + self.yr,
            "Gross": self.supplier_cost,
        }
        comm_base = base_map.get(self.supp_comm_on, 0)
        if self.supp_comm_type == "Percentage":
            return comm_base * (self.supp_comm_value / 100)
        if self.supp_comm_type == "Flat":
            return self.supp_comm_value
        return 0

    @property
    def computed_supp_tds(self):
        return self.computed_supp_commission * (self.supp_tds_per / 100)

    @property
    def computed_supp_gst(self):
        return (self.supp_service_fee + self.supp_addl_service_fee) * (self.supp_gst_pct / 100)


class JournalVoucher(models.Model):
    """
    The auto-posted GL entry for a Ticket's JV (Airline/Hotel/Visa/
    Insurance/Tour) — one row per Ticket, created/updated by
    ticket_create/ticket_update alongside the ticket itself. Ticket-driven
    ONLY (source_ticket is always set); manual double-entry vouchers
    (Journal/Contra/Payment/Receipt/Debit Note/Credit Note via
    voucher-entry.html) live in their own separate `Voucher` table/model
    instead - this table was originally named "Vouchers" and shared both
    purposes, split apart (2026-09-22) once real double-entry postings
    started coming from voucher-entry.html too, so ticket JV rows and
    manual voucher rows don't sit in the same table doing two different jobs.
    """
    CATEGORY_PREFIX = {
        "AIRLINE": "AL", "HOTEL": "HTL", "VISA": "VSA", "INSURANCE": "INS", "TOUR": "TUR",
    }

    id = models.AutoField(primary_key=True)
    company_id = models.IntegerField()
    branch_name = models.CharField(max_length=100, null=True, blank=True)
    voucher_type = models.CharField(max_length=20, default="Tax Invoice")
    voucher_date = models.DateField()
    narration = models.CharField(max_length=250, null=True, blank=True)

    # Category-prefixed sequential number — AL-1, AL-2 for Airline,
    # HTL-1 for Hotel, etc. Unique per company+category, assigned once
    # at creation and never reused, even if an earlier voucher is deleted.
    category = models.CharField(max_length=20, default="AIRLINE")
    voucher_no = models.CharField(max_length=20, null=True, blank=True)

    source_ticket = models.ForeignKey(
        Ticket, on_delete=models.SET_NULL, null=True, blank=True, related_name="vouchers", db_column="source_ticket_id"
    )

    total_debit = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_credit = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    # Always empty for this table - a Ticket's JV lines are computed live
    # from its TicketLines every time (see _compute_jv_lines), never
    # stored. Kept only so the column layout matches Voucher's (manual
    # vouchers DO use this), simplifying shared report code.
    lines_json = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "JournalVoucher"
        constraints = [models.UniqueConstraint(fields=["company_id", "voucher_no"], name="uq_journal_voucher_company_no")]
        indexes = [
            models.Index(fields=["company_id"], name="journal_voucher_company_idx"),
            models.Index(fields=["source_ticket"], name="journal_voucher_ticket_idx"),
        ]

    def __str__(self):
        return f"{self.voucher_type} #{self.id}"


class Voucher(models.Model):
    """
    A real double-entry voucher (Journal/Contra/Payment/Receipt/Debit
    Note/Credit Note) created manually via voucher-entry.html - never
    ticket-driven (see JournalVoucher for that). Its own separate table
    from JournalVoucher, split apart (2026-09-22) so a page like this
    listing real user-entered postings never mixes in ticket JV rows.
    """
    VOUCHER_TYPE_CHOICES = [
        ("Journal", "Journal"), ("Contra", "Contra"), ("Payment", "Payment"),
        ("Receipt", "Receipt"), ("Debit Note", "Debit Note"), ("Credit Note", "Credit Note"),
    ]
    CATEGORY_PREFIX = {"MANUAL": "VCH"}

    id = models.AutoField(primary_key=True)
    company_id = models.IntegerField()
    branch_name = models.CharField(max_length=100, null=True, blank=True)
    voucher_type = models.CharField(max_length=20, choices=VOUCHER_TYPE_CHOICES, default="Journal")
    voucher_date = models.DateField()
    narration = models.CharField(max_length=250, null=True, blank=True)

    # Category-prefixed sequential number — VCH-1, VCH-2, ... Unique per
    # company+category, assigned once at creation and never reused, even
    # if an earlier voucher is deleted.
    category = models.CharField(max_length=20, default="MANUAL")
    voucher_no = models.CharField(max_length=20, null=True, blank=True)

    total_debit = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    total_credit = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    # Free-form debit/credit lines as JSON —
    # [{"ledger_id": 5, "ledger_name": "...", "debit": 100, "credit": 0}, ...].
    lines_json = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "Vouchers"
        constraints = [models.UniqueConstraint(fields=["company_id", "voucher_no"], name="uq_voucher_company_no")]
        indexes = [models.Index(fields=["company_id"], name="voucher_company_idx")]

    def __str__(self):
        return f"{self.voucher_type} #{self.id}"


class VoucherType(models.Model):
    """
    Masters > Voucher Type page (voucher-type.html) — one row per voucher
    type a company defines (Sales, Petty Cash Payment, etc). "Additional
    Numbering Details" is a set of columns on this same row (an_ prefix),
    not a separate table, since it's a 1:1 sub-block of one voucher type,
    only meaningful when allow_additional_numbering is True.
    """
    CATEGORY_CHOICES = [
        ("General", "General"), ("Journal", "Journal"), ("Payment", "Payment"),
        ("Receipt", "Receipt"), ("Debit Note", "Debit Note"), ("Credit Note", "Credit Note"),
    ]
    NUMBER_METHOD_CHOICES = [
        ("Automatic", "Automatic"), ("Manual", "Manual"),
        ("Automatic & Manual Override", "Automatic & Manual Override"),
    ]
    PERIOD_CHOICES = [
        ("Daily", "Daily"), ("Weekly", "Weekly"), ("Monthly", "Monthly"),
        ("Yearly", "Yearly"), ("None", "None"),
    ]

    company_id = models.IntegerField()

    name = models.CharField(max_length=100)
    alias_name = models.CharField(max_length=100, null=True, blank=True)

    voucher_category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="General")
    is_active = models.BooleanField(default=True)
    number_method = models.CharField(max_length=30, choices=NUMBER_METHOD_CHOICES, default="Automatic")

    allow_additional_numbering = models.BooleanField(default=False)
    allow_effective_dates = models.BooleanField(default=False)
    allow_zero_value_transaction = models.BooleanField(default=False)
    allow_narration = models.BooleanField(default=True)
    allow_narration_in_each_ledger = models.BooleanField(default=False)

    # Additional Numbering Details popup — only meaningful when
    # allow_additional_numbering is True.
    an_width_of_invoice_number = models.IntegerField(null=True, blank=True)
    an_prefill_with_zero = models.BooleanField(default=False)
    an_restart_applicable_from = models.DateField(null=True, blank=True)
    an_restart_starting_number = models.IntegerField(null=True, blank=True)
    an_restart_period = models.CharField(max_length=10, choices=PERIOD_CHOICES, default="None")
    an_prefix_details = models.CharField(max_length=20, null=True, blank=True)
    an_suffix_details = models.CharField(max_length=20, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "VoucherType"
        constraints = [models.UniqueConstraint(fields=["company_id", "name"], name="uq_voucher_type_company_name")]
        indexes = [models.Index(fields=["company_id"], name="voucher_type_company_idx")]

    def __str__(self):
        return self.name


class SupplierCommissionRule(models.Model):
    """
    Supplier Master — Commission Rules grid (supplier-master.html). Each row
    is a standalone commission rule for one Office ID, matched against a
    combination of Travel Type / Airline Category / Cabin / Fare Type.

    Looked up by the New Ticket form's Passenger Fare & Accounting
    Breakdown modal: entering an Office ID there auto-fills the Supplier
    Commission Type/Value from the matching rule here (see
    supplier_commission_rules_lookup in views.py).
    """
    CALC_TYPE_CHOICES = [("Percentage", "Percentage"), ("Flat", "Flat")]

    company_id = models.IntegerField()
    rule_type = models.CharField(max_length=20, default="Commission")
    office_id = models.CharField(max_length=30)
    supplier_name = models.CharField(max_length=200, null=True, blank=True)
    travel_type = models.CharField(max_length=20, null=True, blank=True)
    airline_category = models.CharField(max_length=10, null=True, blank=True)
    cabin = models.CharField(max_length=30, null=True, blank=True)
    fare_type = models.CharField(max_length=60, null=True, blank=True)
    comm_on = models.CharField(max_length=20, null=True, blank=True)
    calc_type = models.CharField(max_length=12, choices=CALC_TYPE_CHOICES, null=True, blank=True)
    calc_pct = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    flat_amt = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    valid_upto = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "SupplierCommissionRules"
        indexes = [models.Index(fields=["company_id", "office_id"])]

    def __str__(self):
        return f"{self.office_id} — {self.calc_type}"


class MasterMapping(models.Model):
    """
    Master Mapping page (master-mapping.html) — maps each accounting field
    (Markup A/c, Commission A/c, IGST A/c, ...) for a given Product
    (Airline/Hotel/Bus/Visa/Insurance/Rail) to a real Ledger, effective from
    a given date. Fields are grouped into 4 "Masters" categories in the UI
    (Earnings From Customer/Earnings From Supplier/Expenditure To Customer/
    GST and TDS) — masters_category is kept as its own column so the page
    can filter/group without re-deriving it from field_name.

    One row per (company, product_type, field_name) — see the unique
    constraint below; saving the same field again updates that row instead
    of creating a duplicate (the page always upserts a whole Masters
    category's fields together).
    """
    PRODUCT_TYPE_CHOICES = [
        ("Airline", "Airline"), ("Hotel", "Hotel"), ("Bus", "Bus"),
        ("Visa", "Visa"), ("Insurance", "Insurance"), ("Rail", "Rail"),
    ]
    MASTERS_CATEGORY_CHOICES = [
        ("Earnings From Customer", "Earnings From Customer"),
        ("Earnings From Supplier", "Earnings From Supplier"),
        ("Expenditure To Customer", "Expenditure To Customer"),
        ("Expenditure To Supplier", "Expenditure To Supplier"),
        ("GST and TDS", "GST and TDS"),
    ]
    # Fixed numeric id per Masters category — Earnings From Customer=1,
    # Earnings From Supplier=2, Expenditure To Customer=3, GST and TDS=4,
    # Expenditure To Supplier=5 (added later, kept out of numeric sequence
    # so existing rows' ids never need renumbering).
    MASTERS_CATEGORY_IDS = {
        "Earnings From Customer": 1,
        "Earnings From Supplier": 2,
        "Expenditure To Customer": 3,
        "GST and TDS": 4,
        "Expenditure To Supplier": 5,
    }

    company_id = models.IntegerField()
    product_type = models.CharField(max_length=20, choices=PRODUCT_TYPE_CHOICES)
    masters_category = models.CharField(max_length=40, choices=MASTERS_CATEGORY_CHOICES)
    masters_category_id = models.SmallIntegerField(default=1)
    field_name = models.CharField(max_length=60)

    ledger = models.ForeignKey(
        Ledger, on_delete=models.PROTECT, related_name="master_mappings", db_column="ledger_id"
    )
    ledger_name = models.CharField(max_length=200, null=True, blank=True)

    effective_from = models.DateField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "MasterMapping"
        constraints = [
            models.UniqueConstraint(fields=["company_id", "product_type", "field_name"], name="uq_master_mapping_field")
        ]
        indexes = [models.Index(fields=["company_id", "product_type", "masters_category"])]

    def __str__(self):
        return f"{self.product_type} — {self.field_name}"


class FOPMaster(models.Model):
    """
    FOP Master page (fop-master.html) — one row per physical card (Own Card
    or Client Card), each linked to its GL ledger (chosen from the "Current
    Liabilities" group) and an Active/Inactive status. Same table-as-entry-
    and-list structure as MasterMapping: a row starts editable with a Save
    action, locks once saved (Edit/Del), and Card Number is the natural
    unique key (no duplicates) — see the constraint below.
    """
    CARD_TYPE_CHOICES = [("Own Card", "Own Card"), ("Client Card", "Client Card")]

    company_id = models.IntegerField()
    card_type = models.CharField(max_length=20, choices=CARD_TYPE_CHOICES)
    card_number = models.CharField(max_length=40)
    # Client Card only — the card issuer's bank name. Blank for Own Card.
    bank_name = models.CharField(max_length=100, null=True, blank=True)

    # Own Card only — Client Card rows have no Card Master ledger link.
    card_master_ledger = models.ForeignKey(
        Ledger, on_delete=models.PROTECT, related_name="fop_master_rows", db_column="card_master_ledger_id",
        null=True, blank=True,
    )
    card_master_ledger_name = models.CharField(max_length=200, null=True, blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "FOPMaster"
        constraints = [
            models.UniqueConstraint(fields=["company_id", "card_number"], name="uq_fop_master_card_number")
        ]
        indexes = [models.Index(fields=["company_id", "card_type"])]

    def __str__(self):
        return f"{self.card_type} — {self.card_number}"


class PGMaster(models.Model):
    """
    PG Master page (pg-master.html) — one row per Payment Gateway, each
    linked to its GL ledger (chosen from the "Current Liabilities" group)
    and an Active/Inactive status. Same table-as-entry-and-list structure
    as FOPMaster/MasterMapping. Payment Gateway Name is the natural unique
    key (no duplicates).
    """
    company_id = models.IntegerField()
    gateway_name = models.CharField(max_length=100)

    payment_master_ledger = models.ForeignKey(
        Ledger, on_delete=models.PROTECT, related_name="pg_master_rows", db_column="payment_master_ledger_id"
    )
    payment_master_ledger_name = models.CharField(max_length=200, null=True, blank=True)

    # PG Charges Master - the GL ledger PG transaction charges post to,
    # chosen from the "Expenses" group. Optional (existing rows predate it).
    pg_charges_master_ledger = models.ForeignKey(
        Ledger, on_delete=models.PROTECT, null=True, blank=True,
        related_name="pg_master_charges_rows", db_column="pg_charges_master_ledger_id"
    )
    pg_charges_master_ledger_name = models.CharField(max_length=200, null=True, blank=True)

    # The gateway's own transaction charge rate (e.g. Razorpay's 2%) - a
    # plain number set here, separate from pg_charges_master_ledger's GST%
    # (which is the ledger's tax rate, not the gateway's fee rate).
    pg_charges_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "PGMaster"
        constraints = [
            models.UniqueConstraint(fields=["company_id", "gateway_name"], name="uq_pg_master_gateway_name")
        ]
        indexes = [models.Index(fields=["company_id"])]

    def __str__(self):
        return self.gateway_name


class CompanyMaster(models.Model):
    """
    Company Master page (company-master.html) — one row per
    company/entity set up in this system. Unlike every other *Master
    table above (which take a company_id referencing an external
    company), this table IS the company: its own `id` is what those
    other tables' company_id fields point at.
    """
    GST_REG_TYPE_CHOICES = [
        ("Regular", "Regular"), ("Composition", "Composition"),
        ("Unregistered", "Unregistered"), ("SEZ", "SEZ"),
    ]

    company_name = models.CharField(max_length=200)
    mailing_name = models.CharField(max_length=200, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    country = models.CharField(max_length=100, default="India")
    state = models.CharField(max_length=100, null=True, blank=True)
    pincode = models.CharField(max_length=6, null=True, blank=True)
    telephone = models.CharField(max_length=20, null=True, blank=True)
    mobile = models.CharField(max_length=10, null=True, blank=True)
    email = models.EmailField(max_length=200, null=True, blank=True)
    financial_year_from = models.DateField(null=True, blank=True)
    books_beginning_from = models.DateField(null=True, blank=True)
    gst_reg_type = models.CharField(max_length=20, choices=GST_REG_TYPE_CHOICES, default="Regular")
    gst_no = models.CharField(max_length=15, null=True, blank=True)
    cin_number = models.CharField(max_length=25, null=True, blank=True)
    tan_number = models.CharField(max_length=15, null=True, blank=True)
    hsn_sac = models.CharField(max_length=20, null=True, blank=True)
    description = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "CompanyMaster"
        constraints = [
            models.UniqueConstraint(fields=["company_name"], name="uq_company_master_name")
        ]

    def __str__(self):
        return self.company_name