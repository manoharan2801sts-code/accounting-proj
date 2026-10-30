/* ==========================================================================
   TRAVEL AGENCY Accounting — full schema (single consolidated file)
   --------------------------------------------------------------------------
   Creates the database, every table backing the `accounting` Django app
   (Ledger_Groups, Ledgers, AL_Tickets, AL_TicketLines, JournalVoucher, Vouchers,
   SupplierCommissionRules, MasterMapping, FOPMaster, PGMaster,
   CompanyMaster) — matches
   backend/accounting/models.py exactly, column for column, constraint for
   constraint — and seeds the standard Chart-of-Accounts group hierarchy
   that the app's own features (Master Mapping, FOP Master, PG Master,
   Ledger creation) look up by name (Current Liabilities, Sundry Debtors,
   Sundry Creditors, Duties & Taxes, ...).

   No ticket/passenger/supplier sample data is included — only the base
   structure a brand-new environment needs to be usable.

   Run this whole file once, top to bottom, in SQL Server Management
   Studio (or sqlcmd), against a FRESH environment only.

   *** WARNING — DESTRUCTIVE ***
   Section 1 does `DROP DATABASE Accounting_DB_beta` if it already exists, then
   recreates it empty. Do NOT run this against a database that already has
   real data (e.g. the shared/live server) — it will wipe everything. This
   file is for spinning up a brand-new environment only. If you just need
   new columns/tables on an existing database, run the ALTER/CREATE
   statements from the relevant migration files under
   backend/accounting/migrations/ instead, then
   `python manage.py migrate accounting --fake`.
   ========================================================================== */

-- --------------------------------------------------------------------------
-- 1. Database
-- --------------------------------------------------------------------------
USE master;
GO

IF EXISTS (SELECT name FROM sys.databases WHERE name = N'Accounting_DB_beta')
BEGIN
    ALTER DATABASE Accounting_DB_beta SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE Accounting_DB_beta;
END
GO

CREATE DATABASE Accounting_DB_beta;
GO

USE Accounting_DB_beta;
GO

-- --------------------------------------------------------------------------
-- 2. Ledger_Groups — Chart of Accounts GROUP hierarchy
-- --------------------------------------------------------------------------
CREATE TABLE Ledger_Groups (
    id              INT IDENTITY(1,1) PRIMARY KEY,

    company_id      INT NOT NULL,

    name            NVARCHAR(100) NOT NULL,
    code            NVARCHAR(20)  NULL,

    account_type    NVARCHAR(20)  NOT NULL
        CONSTRAINT ck_ledger_groups_account_type
        CHECK (account_type IN ('ASSET', 'LIABILITY', 'INCOME', 'EXPENSE', 'EQUITY')),

    parent_id       INT NULL,

    is_group        BIT NOT NULL DEFAULT 1,
    is_system       BIT NOT NULL DEFAULT 0,

    created_at      DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at      DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),

    CONSTRAINT fk_ledger_groups_parent
        FOREIGN KEY (parent_id) REFERENCES Ledger_Groups(id)
        ON DELETE NO ACTION,

    CONSTRAINT uq_ledger_groups_company_parent_name
        UNIQUE (company_id, parent_id, name)
);
GO

CREATE INDEX ix_ledger_groups_company_id ON Ledger_Groups(company_id);
CREATE INDEX ix_ledger_groups_parent_id  ON Ledger_Groups(parent_id);
GO

CREATE TRIGGER trg_ledger_groups_updated_at
ON Ledger_Groups
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE lg
    SET updated_at = SYSUTCDATETIME()
    FROM Ledger_Groups lg
    INNER JOIN inserted i ON lg.id = i.id;
END;
GO

-- --------------------------------------------------------------------------
-- 3. Ledgers — leaf accounts (customers, suppliers, banks, ...) under a group
-- --------------------------------------------------------------------------
CREATE TABLE Ledgers (
    id                          INT IDENTITY(1,1) PRIMARY KEY,

    company_id                  INT NOT NULL,
    name                        NVARCHAR(150) NOT NULL,
    group_id                    INT NOT NULL,

    account_type                NVARCHAR(20) NOT NULL
        CONSTRAINT ck_ledgers_account_type
        CHECK (account_type IN ('ASSET', 'LIABILITY', 'INCOME', 'EXPENSE', 'EQUITY')),

    -- BANK / DEBTOR / CREDITOR / INCOME / EXPENSE / DUTIES_TAXES / OTHER
    ledger_category             NVARCHAR(20) NOT NULL,

    opening_balance             DECIMAL(18,2) NOT NULL DEFAULT 0,
    opening_balance_type        NVARCHAR(10) NOT NULL DEFAULT 'Debit'
        CONSTRAINT ck_ledgers_opening_balance_type
        CHECK (opening_balance_type IN ('Debit', 'Credit')),

    -- Bank
    bank_account_no             NVARCHAR(40) NULL,
    bank_branch                 NVARCHAR(100) NULL,
    ifsc_code                   NVARCHAR(15) NULL,
    swift_code                  NVARCHAR(15) NULL,
    is_default_bank             BIT NOT NULL DEFAULT 0,

    -- Debtor — shared
    alias_name                  NVARCHAR(100) NULL,
    address_line1               NVARCHAR(150) NULL,
    address_line2               NVARCHAR(150) NULL,
    agent_id                    NVARCHAR(30) NULL,
    maintain_balance_bill_wise  NVARCHAR(5) NULL,   -- "Yes" / "No"
    place_of_supply             NVARCHAR(60) NULL,

    -- Debtor — India
    city                        NVARCHAR(60) NULL,
    pincode                     NVARCHAR(10) NULL,
    state_name                  NVARCHAR(60) NULL,
    gst_no                      NVARCHAR(20) NULL,
    gst_registration_type       NVARCHAR(20) NULL,
    pan_no                      NVARCHAR(15) NULL,

    -- Debtor — UAE
    emirate                     NVARCHAR(30) NULL,
    po_box_no                   NVARCHAR(20) NULL,
    vat_trn_no                  NVARCHAR(20) NULL,
    trade_license_no            NVARCHAR(30) NULL,
    trade_license_expiry        DATE NULL,

    -- Creditor
    creditor_type                NVARCHAR(30) NULL,
    supplier_code                NVARCHAR(30) NULL,
    office_id                    NVARCHAR(30) NULL,

    -- Duties & Taxes
    tax_category                 NVARCHAR(10) NULL,  -- GST / TDS / Others
    tax_type                     NVARCHAR(10) NULL,  -- IGST / CGST / SGST

    -- Income / Expense tax settings
    gst_applicable                BIT NOT NULL DEFAULT 0,
    gst_tax_type                  NVARCHAR(10) NULL,
    gst_percentage                DECIMAL(5,2) NOT NULL DEFAULT 0,
    tds_applicable                 BIT NOT NULL DEFAULT 0,
    tds_percentage                 DECIMAL(5,2) NOT NULL DEFAULT 0,
    hsn_code                       NVARCHAR(15) NULL,
    tcs_applicable                 BIT NOT NULL DEFAULT 0,
    tcs_percentage                 DECIMAL(5,2) NOT NULL DEFAULT 0,

    is_system                      BIT NOT NULL DEFAULT 0,
    created_at                     DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at                     DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),

    CONSTRAINT fk_ledgers_group
        FOREIGN KEY (group_id) REFERENCES Ledger_Groups(id)
        ON DELETE NO ACTION,

    CONSTRAINT uq_ledger_company_name
        UNIQUE (company_id, name)
);
GO

-- Filtered unique index — matches Django's UniqueConstraint(fields=['agent_id'],
-- condition=Q(agent_id__isnull=False)): agent_id must be unique only when set.
CREATE UNIQUE INDEX uq_ledger_agent_id ON Ledgers(agent_id) WHERE agent_id IS NOT NULL;
GO

CREATE INDEX ix_ledgers_company_id ON Ledgers(company_id);
CREATE INDEX ix_ledgers_group_id   ON Ledgers(group_id);
GO

CREATE TRIGGER trg_ledgers_updated_at
ON Ledgers
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE l
    SET updated_at = SYSUTCDATETIME()
    FROM Ledgers l
    INNER JOIN inserted i ON l.id = i.id;
END;
GO

-- --------------------------------------------------------------------------
-- 4. Tickets — invoice/booking header (Part 1 + Part 2 of New Ticket form)
-- --------------------------------------------------------------------------
CREATE TABLE AL_Tickets (
    id                    INT IDENTITY(1,1) PRIMARY KEY,

    company_id            INT NOT NULL,

    invoice_number        NVARCHAR(20) NOT NULL,
    invoice_date          DATE NOT NULL,
    -- Free text, matched against VoucherType.name (Masters > Voucher Type) -
    -- widened from NVARCHAR(20) and its old fixed CHECK dropped (2026-09-23)
    -- since the Invoice Type dropdown is now driven by whatever voucher
    -- types the company has defined there, not a fixed list.
    invoice_type          NVARCHAR(100) NULL,
    booking_mode          NVARCHAR(20) NOT NULL DEFAULT 'Manual'
        CONSTRAINT ck_tickets_booking_mode
        CHECK (booking_mode IN ('Manual', 'Auto Push')),
    booking_type          NVARCHAR(50) NULL,
    booking_status        NVARCHAR(20) NULL
        CONSTRAINT ck_tickets_booking_status
        CHECK (booking_status IN ('Confirmed', 'Re-Scheduled', 'Normal Cancelled')),

    customer_ledger_id    INT NOT NULL,
    supplier_ledger_id    INT NULL,

    travel_type           NVARCHAR(20) NULL
        CONSTRAINT ck_tickets_travel_type
        CHECK (travel_type IN ('Domestic', 'International')),
    user_name              NVARCHAR(100) NULL,
    currency                NVARCHAR(5) NOT NULL DEFAULT 'INR',
    roe                     DECIMAL(10,4) NOT NULL DEFAULT 1,
    booking_given_by        NVARCHAR(25) NULL,

    booking_reference        NVARCHAR(30) NOT NULL,
    booking_ref_date         DATE NULL,
    airline_pnr               NVARCHAR(13) NULL,
    gds_pnr                    NVARCHAR(13) NULL,
    office_id                   NVARCHAR(30) NULL,

    payment_mode                 NVARCHAR(20) NULL
        CONSTRAINT ck_tickets_payment_mode
        CHECK (payment_mode IN ('Top-up', 'Payment Gateway')),
    payment_gateway_ref           NVARCHAR(60) NULL,
    airline_category               NVARCHAR(5) NULL
        CONSTRAINT ck_tickets_airline_category
        CHECK (airline_category IN ('LCC', 'FSC', 'OSC')),

    created_at                       DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at                       DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),

    CONSTRAINT fk_tickets_customer
        FOREIGN KEY (customer_ledger_id) REFERENCES Ledgers(id)
        ON DELETE NO ACTION,
    CONSTRAINT fk_tickets_supplier
        FOREIGN KEY (supplier_ledger_id) REFERENCES Ledgers(id)
        ON DELETE NO ACTION,

    CONSTRAINT uq_ticket_company_invoice_no
        UNIQUE (company_id, invoice_number),
    CONSTRAINT uq_ticket_company_booking_ref
        UNIQUE (company_id, booking_reference)
);
GO

CREATE INDEX ix_tickets_company_id ON AL_Tickets(company_id);
GO

CREATE TRIGGER trg_tickets_updated_at
ON AL_Tickets
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE t
    SET updated_at = SYSUTCDATETIME()
    FROM AL_Tickets t
    INNER JOIN inserted i ON t.id = i.id;
END;
GO

-- --------------------------------------------------------------------------
-- 5. TicketLines — one passenger/segment row per Ticket (repeatable grid)
-- --------------------------------------------------------------------------
CREATE TABLE AL_TicketLines (
    id                    INT IDENTITY(1,1) PRIMARY KEY,

    ticket_id             INT NOT NULL,

    airline_code          NVARCHAR(200) NULL,
    airline_name          NVARCHAR(200) NULL,
    airline_category      NVARCHAR(5) NULL
        CONSTRAINT ck_ticketlines_airline_category
        CHECK (airline_category IN ('LCC', 'FSC', 'OSC')),
    -- Multi-city: one line can carry several sectors (Add Sector popup),
    -- comma-joined in the same order — e.g. sector 'BOM-DXB,DXB-JFK',
    -- flight_no/cabin/travel_class/fare_type one value per sector.
    -- travel_date is plain text, not DATE, since multi-city segments can
    -- have different dates (comma-joined when they differ).
    flight_no             NVARCHAR(200) NULL,
    ticket_no             NVARCHAR(30) NOT NULL,
    passenger_name        NVARCHAR(50) NOT NULL,
    pax_type              NVARCHAR(10) NOT NULL DEFAULT 'Adult'
        CONSTRAINT ck_ticketlines_pax_type
        CHECK (pax_type IN ('Adult', 'Child', 'Infant')),
    sector                NVARCHAR(200) NULL,
    travel_date           NVARCHAR(200) NULL,
    cabin                 NVARCHAR(200) NULL,
    travel_class          NVARCHAR(200) NULL,
    fare_type             NVARCHAR(300) NULL,

    -- Fare breakup
    basic_fare            DECIMAL(14,2) NOT NULL DEFAULT 0,
    yq                    DECIMAL(14,2) NOT NULL DEFAULT 0,
    yr                    DECIMAL(14,2) NOT NULL DEFAULT 0,
    k3_tax                DECIMAL(14,2) NOT NULL DEFAULT 0,
    tax_others            DECIMAL(14,2) NOT NULL DEFAULT 0,
    seat                  DECIMAL(14,2) NOT NULL DEFAULT 0,
    meal                  DECIMAL(14,2) NOT NULL DEFAULT 0,
    baggage               DECIMAL(14,2) NOT NULL DEFAULT 0,
    other_ssr              DECIMAL(14,2) NOT NULL DEFAULT 0,

    -- Customer discount
    disc_on               NVARCHAR(20) NULL,
    disc_type             NVARCHAR(12) NULL
        CONSTRAINT ck_ticketlines_disc_type
        CHECK (disc_type IN ('Percentage', 'Flat')),
    disc_value            DECIMAL(14,2) NOT NULL DEFAULT 0,
    tds_per                DECIMAL(5,2) NOT NULL DEFAULT 0,
    pg_charges              DECIMAL(14,2) NOT NULL DEFAULT 0,
    -- The PG Master -> PG Charges Percentage actually applied to compute
    -- pg_charges above (the PGMasterHistory snapshot effective as of this
    -- ticket's own Booking Ref Date) - stored so it can be shown later
    -- even after newer History snapshots are added.
    pg_charges_percentage  DECIMAL(5,2) NULL,

    -- Markup / service fee / GST
    markup                DECIMAL(14,2) NOT NULL DEFAULT 0,
    addl_markup           DECIMAL(14,2) NOT NULL DEFAULT 0,
    ssr_markup             DECIMAL(14,2) NOT NULL DEFAULT 0,
    service_fee            DECIMAL(14,2) NOT NULL DEFAULT 0,
    addl_service_fee       DECIMAL(14,2) NOT NULL DEFAULT 0,
    ssr_service_fee        DECIMAL(14,2) NOT NULL DEFAULT 0,
    gst_pct                 DECIMAL(5,2) NOT NULL DEFAULT 0,

    -- Supplier commission
    supp_comm_on            NVARCHAR(20) NULL,
    supp_comm_type          NVARCHAR(12) NULL
        CONSTRAINT ck_ticketlines_supp_comm_type
        CHECK (supp_comm_type IN ('Percentage', 'Flat')),
    supp_comm_value          DECIMAL(14,2) NOT NULL DEFAULT 0,
    supp_tds_per              DECIMAL(5,2) NOT NULL DEFAULT 0,
    supp_markup               DECIMAL(14,2) NOT NULL DEFAULT 0,
    supp_addl_markup          DECIMAL(14,2) NOT NULL DEFAULT 0,
    supp_service_fee          DECIMAL(14,2) NOT NULL DEFAULT 0,
    supp_addl_service_fee     DECIMAL(14,2) NOT NULL DEFAULT 0,
    supp_gst_pct              DECIMAL(5,2)  NOT NULL DEFAULT 0,

    -- Computed at save time server-side (never trust the client's total)
    total_billed          DECIMAL(14,2) NOT NULL DEFAULT 0,

    status                NVARCHAR(15) NOT NULL DEFAULT 'ISSUED'
        CONSTRAINT ck_ticketlines_status
        CHECK (status IN ('ISSUED', 'REFUNDED', 'VOID', 'EXCHANGED')),

    -- Set once this line is cancelled via the Cancellation screen
    -- (dbo.sp_CancellationTicket's SAVE action) - 0 = Active, 1 = Cancelled.
    -- Never flipped back, never deletes the row; checked before allowing
    -- the same line to be cancelled again.
    canceled              BIT NOT NULL DEFAULT 0,

    supplier_ledger_id    INT NULL,
    office_id             NVARCHAR(30) NULL,
    fop                   NVARCHAR(20) NULL
        CONSTRAINT ck_ticketlines_fop
        CHECK (fop IN ('Own Card', 'Client Card', 'Cash')),
    card_number           NVARCHAR(40) NULL,

    -- Reschedule flag (added 2026-10-03, renamed + inverted 2026-10-07 -
    -- was is_reschedule_eligible BIT NOT NULL DEFAULT 1) - 0 (default) =
    -- not yet rescheduled; 1 = already has a RescheduleAirlineTicketLine
    -- against it (see that table's original_ticket_line_id), can never be
    -- rescheduled again.
    rescheduled           BIT NOT NULL DEFAULT 0,

    created_at            DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at            DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),

    CONSTRAINT fk_ticketlines_ticket
        FOREIGN KEY (ticket_id) REFERENCES AL_Tickets(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_ticketlines_supplier
        FOREIGN KEY (supplier_ledger_id) REFERENCES Ledgers(id)
        ON DELETE NO ACTION,

    CONSTRAINT uq_ticketline_ticket_no
        UNIQUE (ticket_no)
);
GO

CREATE INDEX ix_ticketlines_ticket_id ON AL_TicketLines(ticket_id);
GO

CREATE TRIGGER trg_ticketlines_updated_at
ON AL_TicketLines
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE tl
    SET updated_at = SYSUTCDATETIME()
    FROM AL_TicketLines tl
    INNER JOIN inserted i ON tl.id = i.id;
END;
GO

-- --------------------------------------------------------------------------
-- 5a. RescheduleAirlineTickets / 5b. RescheduleAirlineTicketLines — a
-- rescheduled Airline ticket's own header/lines (trans-airline-reschedule.html
-- -> ticket-entry.html's "Reschedule PNR Details" tab). Mirror Tickets/
-- TicketLines column-for-column - NOT including any column that just
-- duplicates data the original ticket/line already holds ("Parent PNR
-- Details" is reconstructed live from original_ticket_id/
-- original_ticket_line_id instead) - plus agent_penalty/reschedule_penalty,
-- which have no equivalent on TicketLines.
-- --------------------------------------------------------------------------
CREATE TABLE Rescheduled_Al_Ticket (
    id                    INT IDENTITY(1,1) PRIMARY KEY,

    company_id            INT NOT NULL,

    -- The ticket this reschedule was raised against - "Parent PNR" and
    -- every other Parent-tab field comes from here, not a stored copy.
    original_ticket_id    INT NULL,      -- NULL = direct Reschedule (no booking in the software)

    invoice_number        NVARCHAR(20) NOT NULL,
    invoice_date          DATE NOT NULL,
    invoice_type          NVARCHAR(100) NULL,
    booking_mode          NVARCHAR(20) NOT NULL DEFAULT 'Manual'
        CONSTRAINT ck_resched_tickets_booking_mode
        CHECK (booking_mode IN ('Manual', 'Auto Push')),
    booking_type          NVARCHAR(50) NULL,
    -- Always 'Re-Scheduled' in practice (frozen by enterRescheduleMode() in
    -- page-ticket-entry.js) - kept as a real column, same choices as Tickets.
    booking_status        NVARCHAR(20) NULL
        CONSTRAINT ck_resched_tickets_booking_status
        CHECK (booking_status IN ('Confirmed', 'Re-Scheduled', 'Normal Cancelled')),

    customer_ledger_id    INT NOT NULL,
    supplier_ledger_id    INT NULL,

    travel_type           NVARCHAR(20) NULL
        CONSTRAINT ck_resched_tickets_travel_type
        CHECK (travel_type IN ('Domestic', 'International')),
    user_name             NVARCHAR(100) NULL,
    currency              NVARCHAR(5) NOT NULL DEFAULT 'INR',
    roe                   DECIMAL(10,4) NOT NULL DEFAULT 1,
    booking_given_by      NVARCHAR(25) NULL,

    -- "Rescheduled Reference" / "Rescheduled Ref Date" in the UI - this new
    -- ticket's OWN reference, not the parent's.
    booking_reference     NVARCHAR(30) NOT NULL,
    booking_ref_date      DATE NULL,
    airline_pnr           NVARCHAR(13) NULL,
    gds_pnr                NVARCHAR(13) NULL,
    office_id              NVARCHAR(30) NULL,

    payment_mode           NVARCHAR(20) NULL
        CONSTRAINT ck_resched_tickets_payment_mode
        CHECK (payment_mode IN ('Top-up', 'Payment Gateway')),
    payment_gateway_ref     NVARCHAR(60) NULL,
    airline_category         NVARCHAR(5) NULL
        CONSTRAINT ck_resched_tickets_airline_category
        CHECK (airline_category IN ('LCC', 'FSC', 'OSC')),

    created_at              DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at              DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),

    CONSTRAINT fk_resched_tickets_original_ticket
        FOREIGN KEY (original_ticket_id) REFERENCES AL_Tickets(id)
        ON DELETE NO ACTION,
    CONSTRAINT fk_resched_tickets_customer
        FOREIGN KEY (customer_ledger_id) REFERENCES Ledgers(id)
        ON DELETE NO ACTION,
    CONSTRAINT fk_resched_tickets_supplier
        FOREIGN KEY (supplier_ledger_id) REFERENCES Ledgers(id)
        ON DELETE NO ACTION,

    CONSTRAINT uq_resched_ticket_company_invoice_no
        UNIQUE (company_id, invoice_number),
    CONSTRAINT uq_resched_ticket_company_booking_ref
        UNIQUE (company_id, booking_reference)
);
GO

CREATE INDEX ix_resched_tickets_company_id ON Rescheduled_Al_Ticket(company_id);
GO
CREATE INDEX ix_resched_tickets_original_ticket_id ON Rescheduled_Al_Ticket(original_ticket_id);
GO

CREATE TRIGGER trg_resched_tickets_updated_at
ON Rescheduled_Al_Ticket
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE t
    SET updated_at = SYSUTCDATETIME()
    FROM Rescheduled_Al_Ticket t
    INNER JOIN inserted i ON t.id = i.id;
END;
GO

CREATE TABLE Rescheduled_Al_TicketLines (
    id                    INT IDENTITY(1,1) PRIMARY KEY,

    reschedule_ticket_id  INT NOT NULL,
    -- The exact original passenger line this reschedule was raised for -
    -- ALWAYS the true original TicketLine, even when chained off a
    -- previous reschedule (based_on_reschedule_line_id below).
    original_ticket_line_id INT NULL,    -- NULL = direct Reschedule
    -- Set only when this reschedule was created by rescheduling an
    -- ALREADY-RESCHEDULED ticket again (chaining) - points at the
    -- previous reschedule's own line; "Parent PNR Details" is
    -- reconstructed from here instead of original_ticket_line_id when set.
    based_on_reschedule_line_id INT NULL,
    -- Renamed + inverted 2026-10-07 (was is_reschedule_eligible BIT NOT
    -- NULL DEFAULT 1) - 0 (default) = this reschedule's own line hasn't
    -- itself been rescheduled again yet; 1 = it has (see
    -- chained_reschedule_lines) and can't be a second time. Independent
    -- of the original line's own flag.
    rescheduled           BIT NOT NULL DEFAULT 0,
    -- Stored (not dynamically re-derived) Parent PNR - the Booking
    -- Reference this line was actually rescheduled FROM, captured once at
    -- creation and never recomputed afterwards.
    parent_pnr            NVARCHAR(30) NULL,

    airline_code          NVARCHAR(200) NULL,
    airline_name          NVARCHAR(200) NULL,
    airline_category      NVARCHAR(5) NULL
        CONSTRAINT ck_resched_ticketlines_airline_category
        CHECK (airline_category IN ('LCC', 'FSC', 'OSC')),
    flight_no             NVARCHAR(200) NULL,
    ticket_no             NVARCHAR(30) NOT NULL,
    passenger_name        NVARCHAR(50) NOT NULL,
    pax_type              NVARCHAR(10) NOT NULL DEFAULT 'Adult'
        CONSTRAINT ck_resched_ticketlines_pax_type
        CHECK (pax_type IN ('Adult', 'Child', 'Infant')),
    sector                NVARCHAR(200) NULL,
    travel_date           NVARCHAR(200) NULL,
    cabin                 NVARCHAR(200) NULL,
    travel_class          NVARCHAR(200) NULL,
    fare_type             NVARCHAR(300) NULL,

    -- Fare breakup
    basic_fare            DECIMAL(14,2) NOT NULL DEFAULT 0,
    yq                    DECIMAL(14,2) NOT NULL DEFAULT 0,
    yr                    DECIMAL(14,2) NOT NULL DEFAULT 0,
    k3_tax                DECIMAL(14,2) NOT NULL DEFAULT 0,
    tax_others            DECIMAL(14,2) NOT NULL DEFAULT 0,
    seat                  DECIMAL(14,2) NOT NULL DEFAULT 0,
    meal                  DECIMAL(14,2) NOT NULL DEFAULT 0,
    baggage               DECIMAL(14,2) NOT NULL DEFAULT 0,
    other_ssr             DECIMAL(14,2) NOT NULL DEFAULT 0,
    -- New to the Reschedule flow only - shown in the Base Fare & Tax
    -- Components card, Reschedule PNR Details tab only. Distinct from
    -- reschedule_penalty further down (Supplier accounting card).
    supplier_penalty      DECIMAL(14,2) NOT NULL DEFAULT 0,

    -- Customer discount
    disc_on               NVARCHAR(20) NULL,
    disc_type             NVARCHAR(12) NULL
        CONSTRAINT ck_resched_ticketlines_disc_type
        CHECK (disc_type IN ('Percentage', 'Flat')),
    disc_value            DECIMAL(14,2) NOT NULL DEFAULT 0,
    tds_per               DECIMAL(5,2) NOT NULL DEFAULT 0,
    pg_charges            DECIMAL(14,2) NOT NULL DEFAULT 0,
    pg_charges_percentage DECIMAL(5,2) NULL,

    -- Markup / service fee / GST
    markup                DECIMAL(14,2) NOT NULL DEFAULT 0,
    addl_markup           DECIMAL(14,2) NOT NULL DEFAULT 0,
    ssr_markup            DECIMAL(14,2) NOT NULL DEFAULT 0,
    service_fee           DECIMAL(14,2) NOT NULL DEFAULT 0,
    addl_service_fee      DECIMAL(14,2) NOT NULL DEFAULT 0,
    ssr_service_fee       DECIMAL(14,2) NOT NULL DEFAULT 0,
    gst_pct               DECIMAL(5,2) NOT NULL DEFAULT 0,

    -- Supplier commission
    supp_comm_on          NVARCHAR(20) NULL,
    supp_comm_type        NVARCHAR(12) NULL
        CONSTRAINT ck_resched_ticketlines_supp_comm_type
        CHECK (supp_comm_type IN ('Percentage', 'Flat')),
    supp_comm_value       DECIMAL(14,2) NOT NULL DEFAULT 0,
    supp_tds_per          DECIMAL(5,2) NOT NULL DEFAULT 0,
    supp_markup           DECIMAL(14,2) NOT NULL DEFAULT 0,
    supp_addl_markup      DECIMAL(14,2) NOT NULL DEFAULT 0,
    supp_service_fee      DECIMAL(14,2) NOT NULL DEFAULT 0,
    supp_addl_service_fee DECIMAL(14,2) NOT NULL DEFAULT 0,
    supp_gst_pct          DECIMAL(5,2) NOT NULL DEFAULT 0,

    -- New to the Reschedule flow only - TicketLines has no equivalent
    -- column. Folded into the Reschedule screen's Other Taxes/Purchase
    -- Cost/Sales Cost Markup/Total figures.
    agent_penalty         DECIMAL(14,2) NOT NULL DEFAULT 0,
    reschedule_penalty    DECIMAL(14,2) NOT NULL DEFAULT 0,

    -- Computed at save time server-side (never trust the client's total)
    total_billed          DECIMAL(14,2) NOT NULL DEFAULT 0,

    status                NVARCHAR(15) NOT NULL DEFAULT 'ISSUED'
        CONSTRAINT ck_resched_ticketlines_status
        CHECK (status IN ('ISSUED', 'REFUNDED', 'VOID', 'EXCHANGED')),

    -- Same reasoning as AL_TicketLines.canceled - set once THIS specific
    -- reschedule line is cancelled, independent of the original line's own flag.
    canceled              BIT NOT NULL DEFAULT 0,

    supplier_ledger_id    INT NULL,
    office_id             NVARCHAR(30) NULL,
    fop                   NVARCHAR(20) NULL
        CONSTRAINT ck_resched_ticketlines_fop
        CHECK (fop IN ('Own Card', 'Client Card', 'Cash')),
    card_number           NVARCHAR(40) NULL,

    created_at            DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at            DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),

    CONSTRAINT fk_resched_ticketlines_reschedule_ticket
        FOREIGN KEY (reschedule_ticket_id) REFERENCES Rescheduled_Al_Ticket(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_resched_ticketlines_original_line
        FOREIGN KEY (original_ticket_line_id) REFERENCES AL_TicketLines(id)
        ON DELETE NO ACTION,
    CONSTRAINT fk_resched_ticketlines_based_on
        FOREIGN KEY (based_on_reschedule_line_id) REFERENCES Rescheduled_Al_TicketLines(id)
        ON DELETE NO ACTION,
    CONSTRAINT fk_resched_ticketlines_supplier
        FOREIGN KEY (supplier_ledger_id) REFERENCES Ledgers(id)
        ON DELETE NO ACTION,

    CONSTRAINT uq_resched_ticketline_ticket_no
        UNIQUE (ticket_no)
);
GO

CREATE INDEX ix_resched_ticketlines_reschedule_ticket_id ON Rescheduled_Al_TicketLines(reschedule_ticket_id);
GO
CREATE INDEX ix_resched_ticketlines_original_ticket_line_id ON Rescheduled_Al_TicketLines(original_ticket_line_id);
GO
CREATE INDEX ix_resched_ticketlines_based_on_reschedule_line_id ON Rescheduled_Al_TicketLines(based_on_reschedule_line_id);
GO

CREATE TRIGGER trg_resched_ticketlines_updated_at
ON Rescheduled_Al_TicketLines
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE tl
    SET updated_at = SYSUTCDATETIME()
    FROM Rescheduled_Al_TicketLines tl
    INNER JOIN inserted i ON tl.id = i.id;
END;
GO

-- --------------------------------------------------------------------------
-- 6a. JournalVoucher — the auto-posted GL entry for a Ticket's JV (Airline/
-- Hotel/Visa/Insurance/Tour). Ticket-driven ONLY, one row per Ticket -
-- source_ticket_id is always set. Split apart from the old combined
-- "Vouchers" table (2026-09-22) so ticket JV rows and manually entered
-- vouchers (see 6b below) don't share one table doing two different jobs;
-- this table was literally renamed from "Vouchers" (its existing rows
-- preserved), not recreated.
-- --------------------------------------------------------------------------
CREATE TABLE JournalVoucher (
    id                INT IDENTITY(1,1) PRIMARY KEY,

    company_id        INT NOT NULL,

    voucher_type      NVARCHAR(20) NOT NULL DEFAULT 'Tax Invoice',
    voucher_date      DATE NOT NULL,
    narration         NVARCHAR(250) NULL,

    -- Category-prefixed sequential number — AL-1, HTL-1, ALR-1 (Airline
    -- Reschedule), etc.
    category          NVARCHAR(20) NOT NULL DEFAULT 'AIRLINE',
    voucher_no        NVARCHAR(20) NULL,

    source_ticket_id  INT NULL,
    -- Exactly one of source_ticket_id/source_reschedule_ticket_id/
    -- source_cancellation_ticket_id is set per row - Reschedule's own JV
    -- (reschedule_ticket_create/update) and Cancellation's own JV
    -- (cancellation_ticket_create/update, added 2026-10-07 - see
    -- dbo.sp_CancellationTicket's SAVE/UPDATE actions and
    -- views._compute_cancellation_jv_lines) are each entirely
    -- separate/additive from the original ticket's own row.
    source_reschedule_ticket_id INT NULL,
    source_cancellation_ticket_id INT NULL,

    total_debit       DECIMAL(16,2) NOT NULL DEFAULT 0,
    total_credit      DECIMAL(16,2) NOT NULL DEFAULT 0,

    -- Always empty here - a Ticket's JV lines are always computed live
    -- from its TicketLines instead (see _compute_jv_lines), never stored.
    lines_json        NVARCHAR(MAX) NOT NULL DEFAULT '[]',

    created_at        DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at        DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),

    CONSTRAINT fk_journal_voucher_source_ticket
        FOREIGN KEY (source_ticket_id) REFERENCES AL_Tickets(id)
        ON DELETE SET NULL,
    CONSTRAINT fk_journal_voucher_source_reschedule_ticket
        FOREIGN KEY (source_reschedule_ticket_id) REFERENCES Rescheduled_Al_Ticket(id)
        ON DELETE SET NULL,
    -- No FK constraint here to Cancellation_AL_Tickets - that table (and
    -- Cancellation_Al_TicketLines) were never given their own CREATE TABLE
    -- block in this file when migration 0030 first added them (2026-10-06),
    -- a pre-existing documentation gap from before this column existed, not
    -- something this change introduces. The live DB (built via Django
    -- migrations, not this script) has the real FK - see models.py's
    -- JournalVoucher.source_cancellation_ticket and migration 0034.

    CONSTRAINT uq_journal_voucher_company_no
        UNIQUE (company_id, voucher_no)
);
GO

CREATE INDEX journal_voucher_company_idx ON JournalVoucher(company_id);
CREATE INDEX journal_voucher_ticket_idx  ON JournalVoucher(source_ticket_id);
CREATE INDEX journal_voucher_rtid_idx    ON JournalVoucher(source_reschedule_ticket_id);
CREATE INDEX journal_voucher_ctid_idx    ON JournalVoucher(source_cancellation_ticket_id);
GO

CREATE TRIGGER trg_journal_voucher_updated_at
ON JournalVoucher
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE v
    SET updated_at = SYSUTCDATETIME()
    FROM JournalVoucher v
    INNER JOIN inserted i ON v.id = i.id;
END;
GO

-- --------------------------------------------------------------------------
-- 6b. Vouchers — manually created double-entry Journal/Contra/Payment/
-- Receipt/Debit/Credit Note (voucher-entry.html). Never ticket-driven -
-- see JournalVoucher above for that. Its own fresh table, separate from
-- JournalVoucher (split 2026-09-22).
-- --------------------------------------------------------------------------
CREATE TABLE Vouchers (
    id                INT IDENTITY(1,1) PRIMARY KEY,

    company_id        INT NOT NULL,

    voucher_type      NVARCHAR(20) NOT NULL DEFAULT 'Journal'
        CONSTRAINT ck_vouchers_voucher_type
        CHECK (voucher_type IN ('Journal', 'Contra', 'Payment', 'Receipt', 'Debit Note', 'Credit Note')),
    voucher_type_name NVARCHAR(100) NULL,   -- Voucher Type master entry picked (migration 0052)
    voucher_date      DATE NOT NULL,
    narration         NVARCHAR(250) NULL,

    -- Category-prefixed sequential number — always VCH-1, VCH-2, ...
    category          NVARCHAR(20) NOT NULL DEFAULT 'MANUAL',
    voucher_no        NVARCHAR(20) NULL,

    total_debit       DECIMAL(16,2) NOT NULL DEFAULT 0,
    total_credit      DECIMAL(16,2) NOT NULL DEFAULT 0,

    -- Free-form debit/credit lines as JSON.
    lines_json        NVARCHAR(MAX) NOT NULL DEFAULT '[]',

    created_at        DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at        DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),

    -- voucher_no is a plain number (1, 2, 3 ...) - unique within its series
    -- (voucher type + master type name).
    CONSTRAINT uq_voucher_company_series_no
        UNIQUE (company_id, voucher_type, voucher_type_name, voucher_no)
);
GO

CREATE INDEX voucher_company_idx ON Vouchers(company_id);
GO

CREATE TRIGGER trg_vouchers_updated_at
ON Vouchers
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE v
    SET updated_at = SYSUTCDATETIME()
    FROM Vouchers v
    INNER JOIN inserted i ON v.id = i.id;
END;
GO

-- --------------------------------------------------------------------------
-- 6c. VoucherType — Masters > Voucher Type (voucher-type.html). One row per
-- voucher type a company defines. "Additional Numbering Details" is kept
-- as columns on this SAME table (an_ prefix below), not a separate table,
-- since it's a 1:1 sub-block of one voucher type, not a repeating list.
-- --------------------------------------------------------------------------
CREATE TABLE VoucherType (
    id                              INT IDENTITY(1,1) PRIMARY KEY,

    company_id                      INT NOT NULL,

    name                            NVARCHAR(100) NOT NULL,
    alias_name                      NVARCHAR(100) NULL,

    voucher_category                NVARCHAR(20) NOT NULL CONSTRAINT df_voucher_type_category DEFAULT 'Airline'
        CONSTRAINT ck_voucher_type_category
        CHECK (voucher_category IN ('Airline', 'Journal', 'Payment', 'Receipt', 'Contra', 'Debit Note', 'Credit Note', 'Miscellaneous')),

    is_active                       BIT NOT NULL DEFAULT 1,

    number_method                   NVARCHAR(30) NOT NULL DEFAULT 'Automatic'
        CONSTRAINT ck_voucher_type_number_method
        CHECK (number_method IN ('Automatic', 'Manual', 'Automatic & Manual Override')),
    -- Automatic numbering only (NULL otherwise) - migration 0053.
    numbering_behaviour             NVARCHAR(30) NULL
        CONSTRAINT ck_voucher_type_numbering_behaviour
        CHECK (numbering_behaviour IN ('Restart Numbers', 'Keep Original Numbers')),

    allow_additional_numbering      BIT NOT NULL DEFAULT 0,
    allow_effective_dates           BIT NOT NULL DEFAULT 0,
    allow_narration                 BIT NOT NULL DEFAULT 1,

    -- Additional Numbering Details popup (only meaningful when
    -- allow_additional_numbering = 1).
    an_width_of_invoice_number      INT NULL,
    an_prefill_with_zero            BIT NOT NULL DEFAULT 0,
    an_restart_applicable_from      DATE NULL,
    an_restart_starting_number      INT NULL,
    an_restart_period               NVARCHAR(10) NOT NULL DEFAULT 'None'
        CONSTRAINT ck_voucher_type_an_restart_period
        CHECK (an_restart_period IN ('Daily', 'Weekly', 'Monthly', 'Yearly', 'None')),
    an_prefix_details                NVARCHAR(20) NULL,
    an_suffix_details                NVARCHAR(20) NULL,

    created_at                      DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at                      DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),

    CONSTRAINT uq_voucher_type_company_name
        UNIQUE (company_id, name)
);
GO

CREATE INDEX voucher_type_company_idx ON VoucherType(company_id);
GO

CREATE TRIGGER trg_voucher_type_updated_at
ON VoucherType
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE v
    SET updated_at = SYSUTCDATETIME()
    FROM VoucherType v
    INNER JOIN inserted i ON v.id = i.id;
END;
GO

-- --------------------------------------------------------------------------
-- 7. SupplierCommissionRules — Supplier Master's Commission Rules grid
-- --------------------------------------------------------------------------
CREATE TABLE SupplierCommissionRules (
    id                INT IDENTITY(1,1) PRIMARY KEY,
    company_id        INT NOT NULL,
    rule_type         NVARCHAR(20) NOT NULL DEFAULT 'Commission',
    office_id         NVARCHAR(30) NOT NULL,
    supplier_name     NVARCHAR(200) NULL,
    travel_type       NVARCHAR(20) NULL,
    airline_category  NVARCHAR(10) NULL,
    cabin             NVARCHAR(30) NULL,
    fare_type         NVARCHAR(60) NULL,
    comm_on           NVARCHAR(20) NULL,
    calc_type         NVARCHAR(12) NULL
        CONSTRAINT ck_supp_comm_rule_calc_type
        CHECK (calc_type IN ('Percentage', 'Flat')),
    calc_pct          DECIMAL(14,2) NOT NULL DEFAULT 0,
    flat_amt          DECIMAL(14,2) NOT NULL DEFAULT 0,
    valid_upto        DATE NULL,
    created_at        DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at        DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

CREATE INDEX ix_supp_comm_rules_company_office ON SupplierCommissionRules(company_id, office_id);
GO

CREATE TRIGGER trg_supplier_commission_rules_updated_at
ON SupplierCommissionRules
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE r
    SET updated_at = SYSUTCDATETIME()
    FROM SupplierCommissionRules r
    INNER JOIN inserted i ON r.id = i.id;
END;
GO

-- --------------------------------------------------------------------------
-- 8. MasterMapping — Master Mapping page (Product/Masters -> Ledger)
-- --------------------------------------------------------------------------
CREATE TABLE MasterMapping (
    id                INT IDENTITY(1,1) PRIMARY KEY,
    company_id        INT NOT NULL,
    product_type      NVARCHAR(20) NOT NULL
        CONSTRAINT ck_master_mapping_product_type
        CHECK (product_type IN ('Airline', 'Hotel', 'Bus', 'Visa', 'Insurance', 'Rail', 'Miscellaneous')),
    masters_category  NVARCHAR(40) NOT NULL
        CONSTRAINT ck_master_mapping_masters_category
        CHECK (masters_category IN (
            'Earnings From Customer', 'Earnings From Supplier',
            'Expenditure To Customer', 'Expenditure To Supplier', 'GST and TDS'
        )),
    masters_category_id TINYINT NOT NULL
        CONSTRAINT ck_master_mapping_masters_category_id
        CHECK (masters_category_id BETWEEN 1 AND 5),
    field_name        NVARCHAR(60) NOT NULL,
    ledger_id         INT NOT NULL,
    ledger_name       NVARCHAR(200) NULL,
    effective_from    DATE NOT NULL,
    created_at        DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at        DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT fk_master_mapping_ledger FOREIGN KEY (ledger_id) REFERENCES Ledgers(id),
    CONSTRAINT uq_master_mapping_field UNIQUE (company_id, product_type, field_name)
);
GO

CREATE INDEX ix_master_mapping_company_product ON MasterMapping(company_id, product_type, masters_category);
GO

CREATE TRIGGER trg_master_mapping_updated_at
ON MasterMapping
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE m
    SET updated_at = SYSUTCDATETIME()
    FROM MasterMapping m
    INNER JOIN inserted i ON m.id = i.id;
END;
GO

-- --------------------------------------------------------------------------
-- 9. FOPMaster — FOP Master page (Own Card / Client Card registry)
-- --------------------------------------------------------------------------
CREATE TABLE FOPMaster (
    id                      INT IDENTITY(1,1) PRIMARY KEY,
    company_id              INT NOT NULL,
    card_type               NVARCHAR(20) NOT NULL
        CONSTRAINT ck_fop_master_card_type
        CHECK (card_type IN ('Own Card', 'Client Card')),
    card_number             NVARCHAR(40) NOT NULL,
    bank_name               NVARCHAR(100) NULL,
    card_master_ledger_id   INT NULL, -- Own Card only; Client Card rows have no ledger link
    card_master_ledger_name NVARCHAR(200) NULL,
    is_active               BIT NOT NULL DEFAULT 1,
    created_at              DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at              DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT fk_fop_master_ledger FOREIGN KEY (card_master_ledger_id) REFERENCES Ledgers(id),
    CONSTRAINT uq_fop_master_card_number UNIQUE (company_id, card_number)
);
GO

CREATE INDEX ix_fop_master_company_type ON FOPMaster(company_id, card_type);
GO

CREATE TRIGGER trg_fop_master_updated_at
ON FOPMaster
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE f
    SET updated_at = SYSUTCDATETIME()
    FROM FOPMaster f
    INNER JOIN inserted i ON f.id = i.id;
END;
GO

-- --------------------------------------------------------------------------
-- 10. PGMaster — PG Master page (Payment Gateway registry)
-- --------------------------------------------------------------------------
CREATE TABLE PGMaster (
    id                          INT IDENTITY(1,1) PRIMARY KEY,
    company_id                  INT NOT NULL,
    gateway_name                NVARCHAR(100) NOT NULL,
    payment_master_ledger_id    INT NOT NULL,
    payment_master_ledger_name  NVARCHAR(200) NULL,
    pg_charges_master_ledger_id    INT NULL,
    pg_charges_master_ledger_name  NVARCHAR(200) NULL,
    -- The gateway's own transaction charge rate (e.g. Razorpay's 2%) -
    -- separate from pg_charges_master_ledger's own GST%.
    pg_charges_percentage       DECIMAL(5,2) NULL,
    -- The date this rate/ledger mapping takes effect from - every save
    -- also snapshots into PGMasterHistory keyed by this date, so tickets
    -- always calculate PG Charges using whichever snapshot was effective
    -- as of their own Booking Ref Date (see PGMasterHistory below).
    pg_charges_percentage_effective_from DATE NULL,
    is_active                   BIT NOT NULL DEFAULT 1,
    created_at                  DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at                  DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT fk_pg_master_ledger FOREIGN KEY (payment_master_ledger_id) REFERENCES Ledgers(id),
    CONSTRAINT fk_pg_master_charges_ledger FOREIGN KEY (pg_charges_master_ledger_id) REFERENCES Ledgers(id),
    CONSTRAINT uq_pg_master_gateway_name UNIQUE (company_id, gateway_name)
);
GO

CREATE INDEX ix_pg_master_company ON PGMaster(company_id);
GO

CREATE TRIGGER trg_pg_master_updated_at
ON PGMaster
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE p
    SET updated_at = SYSUTCDATETIME()
    FROM PGMaster p
    INNER JOIN inserted i ON p.id = i.id;
END;
GO

-- --------------------------------------------------------------------------
-- 10b. PGMasterHistory — one snapshot per (gateway, Effective From date)
-- --------------------------------------------------------------------------
-- Written every time PGMaster is saved with an Effective From date set.
-- Lets a ticket's PG Charges/JV posting resolve the ledger + percentage
-- that was actually in force on its own Booking Ref Date, instead of
-- always using whatever PGMaster currently holds (which would silently
-- rewrite already-booked tickets' calculation/ledger whenever the
-- gateway is edited later with a new rate).
CREATE TABLE PGMasterHistory (
    id                              INT IDENTITY(1,1) PRIMARY KEY,
    pg_master_id                    INT NOT NULL,
    company_id                      INT NOT NULL,
    gateway_name                    NVARCHAR(100) NOT NULL,
    payment_master_ledger_id        INT NULL,
    payment_master_ledger_name      NVARCHAR(200) NULL,
    pg_charges_master_ledger_id     INT NULL,
    pg_charges_master_ledger_name   NVARCHAR(200) NULL,
    pg_charges_percentage           DECIMAL(5,2) NULL,
    effective_from                  DATE NOT NULL,
    created_at                      DATETIMEOFFSET NOT NULL DEFAULT SYSDATETIMEOFFSET(),
    CONSTRAINT fk_pg_master_history_pg_master FOREIGN KEY (pg_master_id) REFERENCES PGMaster(id),
    CONSTRAINT uq_pg_master_history_effective_from UNIQUE (pg_master_id, effective_from)
);
GO

CREATE INDEX ix_pg_master_history_pg_master_effective ON PGMasterHistory(pg_master_id, effective_from);
GO

-- --------------------------------------------------------------------------
-- 10a. CompanyMaster — Company Master page (company-master.html)
-- --------------------------------------------------------------------------
-- Unlike every other *Master table above (which take a company_id
-- referencing an external company), this table IS the company - its own
-- id is what those other tables' company_id columns point at.
CREATE TABLE CompanyMaster (
    id                      INT IDENTITY(1,1) PRIMARY KEY,
    company_name            NVARCHAR(200) NOT NULL,
    mailing_name            NVARCHAR(200) NULL,
    address                 NVARCHAR(MAX) NULL,
    country                 NVARCHAR(100) NOT NULL DEFAULT 'India',
    state                   NVARCHAR(100) NULL,
    pincode                 NVARCHAR(6) NULL,
    telephone               NVARCHAR(20) NULL,
    mobile                  NVARCHAR(10) NULL,
    email                   NVARCHAR(200) NULL,
    financial_year_from     DATE NULL,
    books_beginning_from    DATE NULL,
    gst_reg_type            NVARCHAR(20) NOT NULL DEFAULT 'Regular'
        CONSTRAINT ck_company_master_gst_reg_type
        CHECK (gst_reg_type IN ('Regular', 'Composition', 'Unregistered', 'SEZ')),
    gst_no                  NVARCHAR(15) NULL,
    pan_number              NVARCHAR(10) NULL,
    cin_number              NVARCHAR(25) NULL,
    tan_number              NVARCHAR(15) NULL,
    hsn_sac                 NVARCHAR(20) NULL,
    currency_symbol         NVARCHAR(5) NULL,
    currency_name           NVARCHAR(50) NULL,
    decimal_places          SMALLINT NULL DEFAULT 2
        CONSTRAINT ck_company_master_decimal_places CHECK (decimal_places >= 0),
    logo_base64             NVARCHAR(MAX) NULL,
    seal_base64             NVARCHAR(MAX) NULL,
    created_at              DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at              DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT uq_company_master_name UNIQUE (company_name)
);
GO

CREATE TRIGGER trg_company_master_updated_at
ON CompanyMaster
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    UPDATE c
    SET updated_at = SYSUTCDATETIME()
    FROM CompanyMaster c
    INNER JOIN inserted i ON c.id = i.id;
END;
GO

/* ==========================================================================
   11. Basic seed data — standard Chart-of-Accounts group hierarchy
   --------------------------------------------------------------------------
   Not sample/demo transaction data — this is the base group structure the
   app's own features assume exists (Ledger creation's Group picker, Master
   Mapping's "Incomes"/"Expenses"/"Duties and Taxes" lookups, FOP/PG
   Master's "Current Liabilities" lookup). Seeded for both companies
   (1 = Travel Agency India, 2 = Travel Agency UAE). No leaf ledgers, no
   opening balances, no tickets/vouchers — just the groups. Everything the
   backend looks up by group name tolerates minor wording differences
   (see ledgers_by_group_name in accounting/views.py), so renaming any of
   these afterwards through the Groups page is safe.
   ========================================================================== */
DECLARE @companies TABLE (company_id INT);
INSERT INTO @companies VALUES (1), (2);   -- 1 = India, 2 = UAE

-- Level 1 — top-level groups
INSERT INTO Ledger_Groups (company_id, name, code, account_type, parent_id, is_group, is_system)
SELECT c.company_id, v.name, v.code, v.account_type, NULL, 1, 1
FROM @companies c
CROSS JOIN (VALUES
    (N'Assets',      N'1000', N'ASSET'),
    (N'Liabilities', N'2000', N'LIABILITY'),
    (N'Income',      N'4000', N'INCOME'),
    (N'Expenses',    N'5000', N'EXPENSE')
) AS v(name, code, account_type);

-- Level 2 — primary sub-groups
INSERT INTO Ledger_Groups (company_id, name, code, account_type, parent_id, is_group, is_system)
SELECT c.company_id, v.name, v.code, v.account_type, p.id, 1, 1
FROM @companies c
CROSS JOIN (VALUES
    (N'Capital Account',      N'2100', N'LIABILITY', N'Liabilities'),
    (N'Loans (Liability)',    N'2200', N'LIABILITY', N'Liabilities'),
    (N'Current Liabilities',  N'2300', N'LIABILITY', N'Liabilities'),
    (N'Fixed Assets',         N'1100', N'ASSET',     N'Assets'),
    (N'Investments',          N'1200', N'ASSET',     N'Assets'),
    (N'Current Assets',       N'1300', N'ASSET',     N'Assets'),
    (N'Sales Accounts',       N'4100', N'INCOME',    N'Income'),
    (N'Direct Income',        N'4200', N'INCOME',    N'Income'),
    (N'Indirect Income',      N'4300', N'INCOME',    N'Income'),
    (N'Purchase Accounts',    N'5100', N'EXPENSE',   N'Expenses'),
    (N'Direct Expenses',      N'5200', N'EXPENSE',   N'Expenses'),
    (N'Indirect Expenses',    N'5300', N'EXPENSE',   N'Expenses')
) AS v(name, code, account_type, parent_name)
INNER JOIN Ledger_Groups p ON p.company_id = c.company_id AND p.name = v.parent_name AND p.parent_id IS NULL;

-- Level 3 — sub-groups under Loans (Liability) / Current Liabilities / Current Assets
INSERT INTO Ledger_Groups (company_id, name, code, account_type, parent_id, is_group, is_system)
SELECT c.company_id, v.name, v.code, v.account_type, p.id, 1, 1
FROM @companies c
CROSS JOIN (VALUES
    (N'Secured Loans',    N'2210', N'LIABILITY', N'Loans (Liability)'),
    (N'Unsecured Loans',  N'2220', N'LIABILITY', N'Loans (Liability)'),
    (N'Sundry Creditors', N'2310', N'LIABILITY', N'Current Liabilities'),
    (N'Duties & Taxes',   N'2320', N'LIABILITY', N'Current Liabilities'),
    (N'Provisions',       N'2330', N'LIABILITY', N'Current Liabilities'),
    (N'Sundry Debtors',   N'1310', N'ASSET',     N'Current Assets'),
    (N'Bank Accounts',    N'1320', N'ASSET',     N'Current Assets'),
    (N'Cash-in-hand',     N'1330', N'ASSET',     N'Current Assets'),
    (N'Deposits (Asset)', N'1340', N'ASSET',     N'Current Assets'),
    (N'Stock-in-hand',    N'1350', N'ASSET',     N'Current Assets'),
    (N'Tax Assets',       N'1360', N'ASSET',     N'Current Assets')
) AS v(name, code, account_type, parent_name)
INNER JOIN Ledger_Groups p ON p.company_id = c.company_id AND p.name = v.parent_name AND p.parent_id IS NOT NULL;
GO

-- --------------------------------------------------------------------------
-- 11.2 Base Leaf Ledgers (System accounts required by MasterMapping, FOP, PG)
-- --------------------------------------------------------------------------
-- Seed standard leaf ledgers for each company linking dynamically to groups
INSERT INTO Ledgers (
    company_id, name, group_id, account_type, ledger_category, 
    opening_balance, opening_balance_type, is_system
)
SELECT 
    c.company_id, v.name, g.id, v.account_type, v.ledger_category, 0, 'DEBIT', 1
FROM (VALUES (1), (2)) AS c(company_id)
CROSS JOIN (VALUES
    (N'Markup A/c',                  N'Direct Income',       N'INCOME',    N'GENERAL'),
    (N'Addl Markup A/c',             N'Direct Income',       N'INCOME',    N'GENERAL'),
    (N'SSR Markup A/c',              N'Direct Income',       N'INCOME',    N'GENERAL'),
    (N'Service Fee A/c',             N'Direct Income',       N'INCOME',    N'GENERAL'),
    (N'Addl Service Fee A/c',        N'Direct Income',       N'INCOME',    N'GENERAL'),
    (N'Commission A/c',              N'Indirect Income',     N'INCOME',    N'GENERAL'),
    (N'Discount A/c',                N'Indirect Expenses',   N'EXPENSE',   N'GENERAL'),
    (N'IGST A/c',                    N'Duties & Taxes',      N'LIABILITY', N'TAX'),
    (N'CGST A/c',                    N'Duties & Taxes',      N'LIABILITY', N'TAX'),
    (N'SGST A/c',                    N'Duties & Taxes',      N'LIABILITY', N'TAX'),
    (N'Discount TDS A/c',            N'Duties & Taxes',      N'LIABILITY', N'TAX'),
    (N'Commission TDS A/c',          N'Duties & Taxes',      N'LIABILITY', N'TAX'),
    (N'HDFC Corporate Credit Card',  N'Current Liabilities', N'LIABILITY', N'BANK'),
    (N'ICICI Business Card',         N'Current Liabilities', N'LIABILITY', N'BANK'),
    (N'SBI Commercial Card',         N'Current Liabilities', N'LIABILITY', N'BANK'),
    (N'Axis Corporate Card',         N'Current Liabilities', N'LIABILITY', N'BANK'),
    (N'Amex Business Card',          N'Current Liabilities', N'LIABILITY', N'BANK'),
    (N'IndiGo Airlines',             N'Sundry Creditors',    N'LIABILITY', N'SUPPLIER'),
    (N'Air India',                   N'Sundry Creditors',    N'LIABILITY', N'SUPPLIER'),
    (N'SpiceJet',                    N'Sundry Creditors',    N'LIABILITY', N'SUPPLIER'),
    (N'Emirates',                    N'Sundry Creditors',    N'LIABILITY', N'SUPPLIER'),
    (N'ABC Travels',                 N'Sundry Debtors',      N'ASSET',     N'CUSTOMER')
) AS v(name, group_name, account_type, ledger_category)
INNER JOIN Ledger_Groups g 
    ON g.company_id = c.company_id AND g.name = v.group_name
WHERE NOT EXISTS (
    SELECT 1 FROM Ledgers l WHERE l.company_id = c.company_id AND l.name = v.name
);
GO

-- --------------------------------------------------------------------------
-- 11.3 MasterMapping — Airline Product Mappings
-- --------------------------------------------------------------------------
INSERT INTO MasterMapping (
    company_id, product_type, masters_category, masters_category_id, 
    field_name, ledger_id, ledger_name, effective_from
)
SELECT 
    c.company_id, N'Airline', m.masters_category, m.masters_category_id, 
    m.field_name, l.id, l.name, CAST(SYSUTCDATETIME() AS DATE)
FROM (VALUES (1), (2)) AS c(company_id)
CROSS JOIN (VALUES
    (N'Earnings From Customer', 1, N'Markup A/c',                  N'Markup A/c'),
    (N'Earnings From Customer', 1, N'Addl Markup A/c',             N'Addl Markup A/c'),
    (N'Earnings From Customer', 1, N'SSR Markup A/c',              N'SSR Markup A/c'),
    (N'Earnings From Customer', 1, N'Service Fee A/c',             N'Service Fee A/c'),
    (N'Earnings From Customer', 1, N'Addl Service Fee A/c',        N'Addl Service Fee A/c'),
    (N'Earnings From Customer', 1, N'SSR Service Fee A/c',         N'Service Fee A/c'),
    (N'Earnings From Supplier', 2, N'Commission A/c',              N'Commission A/c'),
    (N'Expenditure To Customer', 3, N'Discount A/c',               N'Discount A/c'),
    (N'Expenditure To Supplier', 4, N'Supplier Markup A/c',        N'Markup A/c'),
    (N'Expenditure To Supplier', 4, N'Supplier Addl Markup A/c',   N'Addl Markup A/c'),
    (N'Expenditure To Supplier', 4, N'Supplier Service Fee A/c',   N'Service Fee A/c'),
    (N'Expenditure To Supplier', 4, N'Supplier Addl Service Fee A/c', N'Addl Service Fee A/c'),
    (N'GST and TDS',             5, N'Output IGST A/c',            N'IGST A/c'),
    (N'GST and TDS',             5, N'Output CGST A/c',            N'CGST A/c'),
    (N'GST and TDS',             5, N'Output SGST A/c',            N'SGST A/c'),
    (N'GST and TDS',             5, N'Discount TDS A/c',           N'Discount TDS A/c'),
    (N'GST and TDS',             5, N'Commission TDS A/c',         N'Commission TDS A/c'),
    (N'GST and TDS',             5, N'Input IGST A/c',             N'IGST A/c'),
    (N'GST and TDS',             5, N'Input CGST A/c',             N'CGST A/c'),
    (N'GST and TDS',             5, N'Input SGST A/c',             N'SGST A/c')
) AS m(masters_category, masters_category_id, field_name, match_ledger_name)
INNER JOIN Ledgers l 
    ON l.company_id = c.company_id AND l.name = m.match_ledger_name
WHERE NOT EXISTS (
    SELECT 1 FROM MasterMapping mm 
    WHERE mm.company_id = c.company_id AND mm.product_type = N'Airline' AND mm.field_name = m.field_name
);
GO

-- --------------------------------------------------------------------------
-- 11.4 FOPMaster — Form of Payment Cards Registry
-- --------------------------------------------------------------------------
INSERT INTO FOPMaster (company_id, card_type, card_number, bank_name, card_master_ledger_id, card_master_ledger_name, is_active)
SELECT 
    c.company_id, card.card_type, card.card_number, card.bank_name, l.id, l.name, 1
FROM (VALUES (1), (2)) AS c(company_id)
CROSS JOIN (VALUES
    (N'Own Card',    N'4111-2222-3333-4444', N'HDFC Bank',   N'HDFC Corporate Credit Card'),
    (N'Own Card',    N'5200-8888-9999-1111', N'ICICI Bank',  N'ICICI Business Card'),
    (N'Own Card',    N'4532-7777-6666-5555', N'SBI Bank',    N'SBI Commercial Card'),
    (N'Own Card',    N'4386-3333-2222-1111', N'Axis Bank',   N'Axis Corporate Card'),
    (N'Own Card',    N'3782-8224-6310-0050', N'Amex',        N'Amex Business Card'),
    (N'Client Card', N'4000-1234-5678-9010', N'Client Bank', N'HDFC Corporate Credit Card')
) AS card(card_type, card_number, bank_name, match_ledger_name)
INNER JOIN Ledgers l 
    ON l.company_id = c.company_id AND l.name = card.match_ledger_name
WHERE NOT EXISTS (
    SELECT 1 FROM FOPMaster f WHERE f.company_id = c.company_id AND f.card_number = card.card_number
);
GO

-- --------------------------------------------------------------------------
-- 11.5 PGMaster — Payment Gateways Registry
-- --------------------------------------------------------------------------
INSERT INTO PGMaster (company_id, gateway_name, payment_master_ledger_id, payment_master_ledger_name, is_active)
SELECT 
    c.company_id, pg.gateway_name, l.id, l.name, 1
FROM (VALUES (1), (2)) AS c(company_id)
CROSS JOIN (VALUES
    (N'Razorpay', N'HDFC Corporate Credit Card'),
    (N'PayU',     N'ICICI Business Card'),
    (N'Stripe',   N'Axis Corporate Card'),
    (N'CCAvenue', N'SBI Commercial Card')
) AS pg(gateway_name, match_ledger_name)
INNER JOIN Ledgers l 
    ON l.company_id = c.company_id AND l.name = pg.match_ledger_name
WHERE NOT EXISTS (
    SELECT 1 FROM PGMaster p WHERE p.company_id = c.company_id AND p.gateway_name = pg.gateway_name
);
GO

-- --------------------------------------------------------------------------
-- 11.6 SupplierCommissionRules — Supplier Master Commission Rules
-- --------------------------------------------------------------------------
INSERT INTO SupplierCommissionRules (
    company_id, rule_type, office_id, supplier_name, travel_type, 
    airline_category, cabin, fare_type, comm_on, calc_type, 
    calc_pct, flat_amt, valid_upto
)
SELECT 
    c.company_id, r.rule_type, r.office_id, r.supplier_name, r.travel_type,
    r.airline_category, r.cabin, r.fare_type, r.comm_on, r.calc_type,
    r.calc_pct, r.flat_amt, CAST(r.valid_upto AS DATE)
FROM (VALUES (1), (2)) AS c(company_id)
CROSS JOIN (VALUES
    (N'Commission', N'DEL123', N'IndiGo Airlines', N'DOM', N'LCC', N'Economy',  N'Normal', N'Basic + YQ', N'Percentage', 3.50, 0,      N'2026-12-31'),
    (N'Commission', N'BOM456', N'Air India',       N'INT', N'FSC', N'Economy',  N'Flexi',  N'Basic',      N'Percentage', 4.00, 0,      N'2026-12-31'),
    (N'Commission', N'DXB789', N'Emirates',        N'INT', N'FSC', N'Business', N'Flexi',  N'Basic',      N'Percentage', 5.00, 0,      N'2026-12-31'),
    (N'Commission', N'DEL123', N'SpiceJet',        N'DOM', N'LCC', N'Economy',  N'Normal', N'Basic',      N'Flat',       0.00, 250.00, N'2026-12-31')
) AS r(rule_type, office_id, supplier_name, travel_type, airline_category, cabin, fare_type, comm_on, calc_type, calc_pct, flat_amt, valid_upto)
WHERE NOT EXISTS (
    SELECT 1 FROM SupplierCommissionRules scr 
    WHERE scr.company_id = c.company_id AND scr.office_id = r.office_id AND scr.supplier_name = r.supplier_name
);
GO

-- --------------------------------------------------------------------------
-- 11.8 User Management - AppUsers / MenuMaster / UserMenuAccess
--      (migrations 0035-0037). Idempotent - safe to run on an existing DB.
--      The seeded Super Admin has no password here - set one from User
--      Management (or via the API) before signing in.
-- --------------------------------------------------------------------------
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'AppUsers')
BEGIN
    CREATE TABLE dbo.AppUsers (
        id              INT IDENTITY(1,1) PRIMARY KEY,
        full_name       NVARCHAR(150) NOT NULL,
        email           NVARCHAR(200) NOT NULL,
        role            NVARCHAR(50)  NOT NULL DEFAULT 'User',
        is_super_admin  BIT NOT NULL DEFAULT 0,
        is_active       BIT NOT NULL DEFAULT 1,
        created_at      DATETIMEOFFSET NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at      DATETIMEOFFSET NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT uq_app_user_email UNIQUE (email)
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'MenuMaster')
BEGIN
    CREATE TABLE dbo.MenuMaster (
        id          INT IDENTITY(1,1) PRIMARY KEY,
        menu_key    NVARCHAR(60)  NOT NULL,
        title       NVARCHAR(100) NOT NULL,
        parent_key  NVARCHAR(60)  NULL,
        module      NVARCHAR(20)  NOT NULL,
        sort_order  INT NOT NULL DEFAULT 0,
        is_active   BIT NOT NULL DEFAULT 1,
        CONSTRAINT uq_menu_master_key UNIQUE (menu_key)
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'UserMenuAccess')
BEGIN
    CREATE TABLE dbo.UserMenuAccess (
        id              INT IDENTITY(1,1) PRIMARY KEY,
        user_id         INT NOT NULL REFERENCES dbo.AppUsers(id),
        menu_key        NVARCHAR(60) NOT NULL REFERENCES dbo.MenuMaster(menu_key),
        can_view        BIT NOT NULL DEFAULT 0,
        can_add         BIT NOT NULL DEFAULT 0,
        can_edit        BIT NOT NULL DEFAULT 0,
        can_delete      BIT NOT NULL DEFAULT 0,
        created_by_id   INT NULL REFERENCES dbo.AppUsers(id),
        created_at      DATETIMEOFFSET NOT NULL DEFAULT SYSUTCDATETIME(),
        updated_at      DATETIMEOFFSET NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT uq_user_menu_access UNIQUE (user_id, menu_key)
    );
    CREATE INDEX UserMenuAcc_user_id_9d1265_idx ON dbo.UserMenuAccess(user_id);
END
GO

-- User Management Print / Export Excel flags (migration 0091).
IF COL_LENGTH('dbo.UserMenuAccess', 'can_print') IS NULL
BEGIN
    ALTER TABLE dbo.UserMenuAccess ADD can_print BIT NOT NULL CONSTRAINT df_uma_can_print DEFAULT 0;
    ALTER TABLE dbo.UserMenuAccess ADD can_export BIT NOT NULL CONSTRAINT df_uma_can_export DEFAULT 0;
    -- Existing users keep printing / exporting every menu they can view.
    EXEC (N'UPDATE dbo.UserMenuAccess SET can_print = can_view, can_export = can_view;');
END
GO

-- Login password (migration 0037) - Django PBKDF2 hash, never plain text.
IF COL_LENGTH('dbo.AppUsers', 'password_hash') IS NULL
    ALTER TABLE dbo.AppUsers ADD password_hash NVARCHAR(256) NULL;
GO

-- Completed menus only (hardcode.js NAV_SECTIONS keys).
MERGE dbo.MenuMaster AS t
USING (VALUES
    ('company-master', 'Company Master', NULL, 'Masters', 1),
    ('groups', 'Groups', NULL, 'Masters', 2),
    ('accounts', 'Ledger Master', NULL, 'Masters', 3),
    ('voucher-type', 'Voucher Type', NULL, 'Masters', 4),
    ('supplier-master', 'Supplier Master', NULL, 'Masters', 5),
    ('master-mapping', 'Ledger Mapping', NULL, 'Masters', 6),
    ('fop-master', 'FOP Master', NULL, 'Masters', 7),
    ('pg-master', 'PG Master', NULL, 'Masters', 8),
    ('tickets', 'Booking', 'trans-airline', 'Transactions', 1),
    ('trans-airline-reschedule', 'Reschedule', 'trans-airline', 'Transactions', 2),
    ('trans-airline-cancellation', 'Cancellation', 'trans-airline', 'Transactions', 3),
    ('trans-airline-ssr', 'SSR Updation', 'trans-airline', 'Transactions', 4),
    ('trans-misc', 'Miscellaneous', NULL, 'Transactions', 5),
    ('rep-dsr', 'Returns', NULL, 'Reports', 0),
    ('rep-dsr-report', 'DSR', NULL, 'Reports', 1),
    ('rep-cash-bank-book', 'Cash & Bank Book', 'rep-accounting-book', 'Reports', 2),
    ('rep-day-book', 'Day Book', 'rep-accounting-book', 'Reports', 3),
    ('rep-ledger-book', 'Ledger', 'rep-accounting-book', 'Reports', 4),
    ('customers', 'Receivables (AR)', NULL, 'Reports', 5),
    ('suppliers', 'Payables (AP)', NULL, 'Reports', 6),
    ('rep-trial-balance', 'Trial Balance', NULL, 'Reports', 7),
    ('rep-profit-loss', 'Profit and Loss', NULL, 'Reports', 8),
    ('rep-balance-sheet', 'Balance Sheet', NULL, 'Reports', 9),
    ('user-management', 'User Management', NULL, 'Control Panel', 1)
) AS s(menu_key, title, parent_key, module, sort_order)
ON t.menu_key = s.menu_key
WHEN MATCHED THEN UPDATE SET title = s.title, parent_key = s.parent_key, module = s.module, sort_order = s.sort_order
WHEN NOT MATCHED THEN INSERT (menu_key, title, parent_key, module, sort_order, is_active)
    VALUES (s.menu_key, s.title, s.parent_key, s.module, s.sort_order, 1);
GO

-- User Management is Super-Admin-only (migration 0038) - not grantable.
UPDATE dbo.MenuMaster SET is_active = 0 WHERE menu_key = 'user-management';
GO

-- One initial Super Admin, only if none exists yet.
IF NOT EXISTS (SELECT 1 FROM dbo.AppUsers WHERE is_super_admin = 1)
    INSERT INTO dbo.AppUsers (full_name, email, role, is_super_admin, is_active)
    VALUES ('Ananya Krishnan', 'ananya.krishnan@travelagency.com', 'Administrator', 1, 1);
GO

-- --------------------------------------------------------------------------
-- 11.9 Cancellation lines - locked Customer/Supplier TDS amounts carried
--      from the booking/reschedule chain (migration 0039). NULL = no
--      override (TDS = Amount x TDS %). Idempotent.
-- --------------------------------------------------------------------------
IF COL_LENGTH('dbo.Cancellation_Al_TicketLines', 'tds_amount_override') IS NULL
    ALTER TABLE dbo.Cancellation_Al_TicketLines ADD tds_amount_override DECIMAL(14,2) NULL;
GO
IF COL_LENGTH('dbo.Cancellation_Al_TicketLines', 'supp_tds_amount_override') IS NULL
    ALTER TABLE dbo.Cancellation_Al_TicketLines ADD supp_tds_amount_override DECIMAL(14,2) NULL;
GO
-- Default Bank flag on ledgers (migration 0051) - for databases created
-- before it was added to the Ledgers table above.
IF COL_LENGTH('dbo.Ledgers', 'is_default_bank') IS NULL
    ALTER TABLE dbo.Ledgers ADD is_default_bank BIT NOT NULL
        CONSTRAINT df_ledgers_is_default_bank DEFAULT 0;
GO
-- Voucher Type master entry picked on the Voucher screen + Contra as a
-- Voucher Type category (migration 0052) - for databases created earlier.
IF COL_LENGTH('dbo.Vouchers', 'voucher_type_name') IS NULL
    ALTER TABLE dbo.Vouchers ADD voucher_type_name NVARCHAR(100) NULL;
GO
IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'ck_voucher_type_category'
           AND definition NOT LIKE '%Contra%')
BEGIN
    ALTER TABLE dbo.VoucherType DROP CONSTRAINT ck_voucher_type_category;
    ALTER TABLE dbo.VoucherType ADD CONSTRAINT ck_voucher_type_category
        CHECK (voucher_category IN ('General', 'Journal', 'Payment', 'Receipt', 'Contra', 'Debit Note', 'Credit Note'));
END
GO
-- Voucher Type category "General" renamed to "Airline" (migration 0055).
IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'ck_voucher_type_category'
           AND definition LIKE '%General%')
BEGIN
    ALTER TABLE dbo.VoucherType DROP CONSTRAINT ck_voucher_type_category;
    UPDATE dbo.VoucherType SET voucher_category = 'Airline' WHERE voucher_category = 'General';
    DECLARE @df SYSNAME = (SELECT dc.name FROM sys.default_constraints dc
        JOIN sys.columns c ON c.object_id = dc.parent_object_id AND c.column_id = dc.parent_column_id
        WHERE dc.parent_object_id = OBJECT_ID('dbo.VoucherType') AND c.name = 'voucher_category');
    IF @df IS NOT NULL EXEC('ALTER TABLE dbo.VoucherType DROP CONSTRAINT [' + @df + ']');
    ALTER TABLE dbo.VoucherType ADD CONSTRAINT df_voucher_type_category DEFAULT 'Airline' FOR voucher_category;
    ALTER TABLE dbo.VoucherType ADD CONSTRAINT ck_voucher_type_category
        CHECK (voucher_category IN ('Airline', 'Journal', 'Payment', 'Receipt', 'Contra', 'Debit Note', 'Credit Note'));
END
GO
-- Voucher Type "Numbering" for Automatic numbering (migration 0053).
IF COL_LENGTH('dbo.VoucherType', 'numbering_behaviour') IS NULL
    ALTER TABLE dbo.VoucherType ADD numbering_behaviour NVARCHAR(30) NULL
        CONSTRAINT ck_voucher_type_numbering_behaviour CHECK (numbering_behaviour IN ('Restart Numbers', 'Keep Original Numbers'));
GO
-- Ledger Mapping with Effective From dates (migration 0054) - one row per
-- (company, product, field, Effective From); written by sp_MasterMapping
-- SAVE_ROW. Seeded once from each existing MasterMapping row.
IF OBJECT_ID('dbo.MasterMappingHistory', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.MasterMappingHistory (
        id                INT IDENTITY(1,1) PRIMARY KEY,
        company_id        INT NOT NULL,
        product_type      NVARCHAR(20) NOT NULL,
        masters_category  NVARCHAR(40) NOT NULL,
        field_name        NVARCHAR(60) NOT NULL,
        ledger_id         INT NOT NULL,
        ledger_name       NVARCHAR(200) NULL,
        effective_from    DATE NOT NULL,
        created_at        DATETIMEOFFSET NOT NULL,
        updated_at        DATETIMEOFFSET NOT NULL,
        CONSTRAINT uq_master_mapping_history_effective_from UNIQUE (company_id, product_type, field_name, effective_from)
    );
    INSERT INTO dbo.MasterMappingHistory (company_id, product_type, masters_category, field_name, ledger_id, ledger_name, effective_from, created_at, updated_at)
    SELECT company_id, product_type, masters_category, field_name, ledger_id, ledger_name, effective_from, SYSUTCDATETIME(), SYSUTCDATETIME()
    FROM dbo.MasterMapping;
END
GO
-- Supplier SSR Markup reversal (Markup Reversal popup, migration 0050).
IF COL_LENGTH('dbo.Cancellation_Al_TicketLines', 'supp_ssr_markup_reversal') IS NULL
    ALTER TABLE dbo.Cancellation_Al_TicketLines ADD supp_ssr_markup_reversal NUMERIC(14,2) NOT NULL
        CONSTRAINT df_cancel_line_supp_ssr_markup_reversal DEFAULT 0;
GO

-- --------------------------------------------------------------------------
-- 11.10 Booking lines - Supplier side SSR Markup / SSR Service Fee
--       (migration 0041). Idempotent.
-- --------------------------------------------------------------------------
IF COL_LENGTH('dbo.AL_TicketLines', 'supp_ssr_markup') IS NULL
    ALTER TABLE dbo.AL_TicketLines ADD supp_ssr_markup DECIMAL(14,2) NOT NULL CONSTRAINT df_al_ticketlines_supp_ssr_markup DEFAULT 0;
GO
IF COL_LENGTH('dbo.AL_TicketLines', 'supp_ssr_service_fee') IS NULL
    ALTER TABLE dbo.AL_TicketLines ADD supp_ssr_service_fee DECIMAL(14,2) NOT NULL CONSTRAINT df_al_ticketlines_supp_ssr_service_fee DEFAULT 0;
GO

-- --------------------------------------------------------------------------
-- 11.11 SSR Updation (trans-airline-ssr.html) - header + lines, and the
--       JournalVoucher link for its own ALS-n JV (migration 0043).
--       Written only through dbo.sp_SSRTicket. Idempotent.
-- --------------------------------------------------------------------------
IF OBJECT_ID('dbo.SSR_AL_Tickets', 'U') IS NULL
CREATE TABLE dbo.SSR_AL_Tickets (
    id                          INT IDENTITY(1,1) PRIMARY KEY,
    company_id                  INT NOT NULL,
    original_ticket_id          INT NULL REFERENCES dbo.AL_Tickets(id),   -- NULL = direct SSR (migration 0090)
    source_reschedule_ticket_id INT NULL REFERENCES dbo.Rescheduled_Al_Ticket(id),
    invoice_number              NVARCHAR(20) NOT NULL,
    invoice_date                DATE NOT NULL,
    invoice_type                NVARCHAR(100) NULL,
    booking_mode                NVARCHAR(20) NOT NULL DEFAULT 'Manual',
    booking_status              NVARCHAR(20) NOT NULL DEFAULT 'SSR Updated',
    customer_ledger_id          INT NOT NULL REFERENCES dbo.Ledgers(id),
    travel_type                 NVARCHAR(20) NULL,
    user_name                   NVARCHAR(100) NULL,
    currency                    NVARCHAR(5) NOT NULL DEFAULT 'INR',
    roe                         NUMERIC(10,4) NOT NULL DEFAULT 1,
    ssr_reference               NVARCHAR(30) NOT NULL,
    ssr_ref_date                DATE NULL,
    airline_pnr                 NVARCHAR(13) NULL,
    gds_pnr                     NVARCHAR(13) NULL,
    payment_mode                NVARCHAR(20) NULL,
    payment_gateway_ref         NVARCHAR(60) NULL,
    created_at                  DATETIMEOFFSET NOT NULL,
    updated_at                  DATETIMEOFFSET NOT NULL,
    CONSTRAINT uq_ssr_ticket_company_invoice_no UNIQUE (company_id, invoice_number)
    -- SSR Reference is NOT unique: one S PNR can have several SSR Updations (migration 0088)
);
GO
-- Gateway Ref (migration 0048) - added after the table first shipped.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ssr_ticket_ssr_ref_idx')
    CREATE INDEX ssr_ticket_ssr_ref_idx ON dbo.SSR_AL_Tickets (company_id, ssr_reference);
IF COL_LENGTH('dbo.SSR_AL_Tickets', 'payment_gateway_ref') IS NULL
    ALTER TABLE dbo.SSR_AL_Tickets ADD payment_gateway_ref NVARCHAR(60) NULL;
-- Direct SSR Updation (migration 0090): the Parent PNR it was pushed with.
IF COL_LENGTH('dbo.SSR_AL_Tickets', 'parent_pnr') IS NULL
    ALTER TABLE dbo.SSR_AL_Tickets ADD parent_pnr NVARCHAR(30) NULL;
-- Direct SSR Updation (migration 0090): the Parent PNR it was pushed with.
IF COL_LENGTH('dbo.SSR_AL_Tickets', 'parent_pnr') IS NULL
    ALTER TABLE dbo.SSR_AL_Tickets ADD parent_pnr NVARCHAR(30) NULL;
-- Direct SSR Updation (migration 0090): the Parent PNR it was pushed with.
IF COL_LENGTH('dbo.SSR_AL_Tickets', 'parent_pnr') IS NULL
    ALTER TABLE dbo.SSR_AL_Tickets ADD parent_pnr NVARCHAR(30) NULL;
GO
IF OBJECT_ID('dbo.SSR_AL_TicketLines', 'U') IS NULL
CREATE TABLE dbo.SSR_AL_TicketLines (
    id                      INT IDENTITY(1,1) PRIMARY KEY,
    ssr_ticket_id           INT NOT NULL REFERENCES dbo.SSR_AL_Tickets(id),
    original_ticket_line_id INT NULL REFERENCES dbo.AL_TicketLines(id),   -- NULL = direct SSR (migration 0090)
    reschedule_line_id      INT NULL REFERENCES dbo.Rescheduled_Al_TicketLines(id),
    ticket_no               NVARCHAR(20) NULL,
    passenger_name          NVARCHAR(100) NULL,
    pax_type                NVARCHAR(10) NULL,
    airline_category        NVARCHAR(5) NULL,
    sector                  NVARCHAR(20) NULL,
    office_id               NVARCHAR(30) NULL,
    supplier_ledger_id      INT NULL REFERENCES dbo.Ledgers(id),
    fop                     NVARCHAR(20) NULL,
    card_number             NVARCHAR(40) NULL,     -- FOP Own Card / Client Card (FOP Master), migration 0087
    ssr_items               NVARCHAR(MAX) NULL,
    ssr_ticket_numbers      NVARCHAR(MAX) NULL,
    ssr_charges             NVARCHAR(MAX) NULL,
    seat                    NUMERIC(14,2) NOT NULL DEFAULT 0,
    meal                    NUMERIC(14,2) NOT NULL DEFAULT 0,
    baggage                 NUMERIC(14,2) NOT NULL DEFAULT 0,
    other_ssr               NUMERIC(14,2) NOT NULL DEFAULT 0,
    markup                  NUMERIC(14,2) NOT NULL DEFAULT 0,
    service_fee             NUMERIC(14,2) NOT NULL DEFAULT 0,
    supp_markup             NUMERIC(14,2) NOT NULL DEFAULT 0,
    supp_service_fee        NUMERIC(14,2) NOT NULL DEFAULT 0,
    total_billed            NUMERIC(14,2) NOT NULL DEFAULT 0
);
GO
IF COL_LENGTH('dbo.JournalVoucher', 'source_ssr_ticket_id') IS NULL
    ALTER TABLE dbo.JournalVoucher ADD source_ssr_ticket_id INT NULL REFERENCES dbo.SSR_AL_Tickets(id);
GO
-- SSR Ticket Number per SSR type (migration 0049) - added after the table first shipped.
IF COL_LENGTH('dbo.SSR_AL_TicketLines', 'ssr_ticket_numbers') IS NULL
    ALTER TABLE dbo.SSR_AL_TicketLines ADD ssr_ticket_numbers NVARCHAR(MAX) NULL;
GO
-- Per SSR type charges from the SSR popup grid (migration 0068).
IF COL_LENGTH('dbo.SSR_AL_TicketLines', 'ssr_charges') IS NULL
    ALTER TABLE dbo.SSR_AL_TicketLines ADD ssr_charges NVARCHAR(MAX) NULL;
GO

-- --------------------------------------------------------------------------
-- Miscellaneous transactions (trans-misc.html, migrations 0056 / 0057) - one
-- Description + Base Amount billed to a customer and bought from a supplier,
-- with customer / supplier Markup and Service Fee. A Confirmed one posts its
-- own JournalVoucher (category MISC, MSC-n, source_misc_ticket_id).
-- --------------------------------------------------------------------------
IF OBJECT_ID('dbo.Misc_Transactions', 'U') IS NULL
CREATE TABLE dbo.Misc_Transactions (
    id                  INT IDENTITY(1,1) PRIMARY KEY,
    company_id          INT NOT NULL,
    invoice_number      NVARCHAR(20) NOT NULL,
    invoice_date        DATE NOT NULL,
    invoice_type        NVARCHAR(100) NULL,
    status              NVARCHAR(20) NOT NULL DEFAULT 'Confirmed'
        CONSTRAINT ck_misc_status CHECK (status IN ('Confirmed', 'Cancelled')),
    user_name           NVARCHAR(100) NULL,
    reference           NVARCHAR(30) NOT NULL,
    ref_date            DATE NULL,
    payment_mode        NVARCHAR(20) NULL,
    payment_gateway_ref NVARCHAR(60) NULL,
    currency            NVARCHAR(5) NOT NULL DEFAULT 'INR',
    customer_ledger_id  INT NOT NULL REFERENCES dbo.Ledgers(id),
    supplier_ledger_id  INT NOT NULL REFERENCES dbo.Ledgers(id),
    description         NVARCHAR(MAX) NULL,
    base_amount         NUMERIC(14,2) NOT NULL DEFAULT 0,
    other_taxes         NUMERIC(14,2) NOT NULL DEFAULT 0,
    markup              NUMERIC(14,2) NOT NULL DEFAULT 0,
    service_fee         NUMERIC(14,2) NOT NULL DEFAULT 0,
    supp_markup         NUMERIC(14,2) NOT NULL DEFAULT 0,
    supp_service_fee    NUMERIC(14,2) NOT NULL DEFAULT 0,
    total_billed        NUMERIC(14,2) NOT NULL DEFAULT 0,
    created_at          DATETIMEOFFSET NOT NULL,
    updated_at          DATETIMEOFFSET NOT NULL,
    CONSTRAINT uq_misc_company_invoice_no UNIQUE (company_id, invoice_number),
    CONSTRAINT uq_misc_company_reference UNIQUE (company_id, reference)
);
GO
IF COL_LENGTH('dbo.JournalVoucher', 'source_misc_ticket_id') IS NULL
    ALTER TABLE dbo.JournalVoucher ADD source_misc_ticket_id INT NULL REFERENCES dbo.Misc_Transactions(id);
GO
-- Voucher numbers stored as plain 1, 2, 3 (no PV- / RV- / JV21- prefix) - migration 0062.
IF EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = 'uq_voucher_company_no')
BEGIN
    ALTER TABLE dbo.Vouchers DROP CONSTRAINT uq_voucher_company_no;
    UPDATE dbo.Vouchers SET voucher_no = RIGHT(voucher_no, CHARINDEX('-', REVERSE(voucher_no)) - 1)
    WHERE category = 'MANUAL' AND CHARINDEX('-', voucher_no) > 0;
    ALTER TABLE dbo.Vouchers ADD CONSTRAINT uq_voucher_company_series_no
        UNIQUE (company_id, voucher_type, voucher_type_name, voucher_no);
END
GO
-- Voucher Type category "Miscellaneous" - invoice types for trans-misc.html (migration 0061).
IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'ck_voucher_type_category'
           AND definition NOT LIKE '%Miscellaneous%')
BEGIN
    ALTER TABLE dbo.VoucherType DROP CONSTRAINT ck_voucher_type_category;
    ALTER TABLE dbo.VoucherType ADD CONSTRAINT ck_voucher_type_category
        CHECK (voucher_category IN ('Airline', 'Journal', 'Payment', 'Receipt', 'Contra', 'Debit Note', 'Credit Note', 'Miscellaneous'));
END
GO
-- FOP Master - Card Master ledger Effective From history (migration 0067),
-- same rules as Ledger Mapping (MasterMappingHistory).
IF COL_LENGTH('dbo.FOPMaster', 'effective_from') IS NULL
    ALTER TABLE dbo.FOPMaster ADD effective_from DATE NULL;
GO
IF OBJECT_ID('dbo.FOPMasterHistory', 'U') IS NULL
CREATE TABLE dbo.FOPMasterHistory (
    id                      INT IDENTITY(1,1) PRIMARY KEY,
    company_id              INT NOT NULL,
    fop_master_id           INT NOT NULL REFERENCES dbo.FOPMaster(id),
    card_master_ledger_id   INT NOT NULL REFERENCES dbo.Ledgers(id),
    card_master_ledger_name NVARCHAR(200) NULL,
    effective_from          DATE NOT NULL,
    created_at              DATETIMEOFFSET NOT NULL,
    updated_at              DATETIMEOFFSET NOT NULL,
    CONSTRAINT uq_fop_history_card_date UNIQUE (fop_master_id, effective_from)
);
GO
-- Ledger Mapping product "Miscellaneous" - the Misc ledgers (migration 0060).
IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'ck_master_mapping_product_type'
           AND definition NOT LIKE '%Miscellaneous%')
BEGIN
    ALTER TABLE dbo.MasterMapping DROP CONSTRAINT ck_master_mapping_product_type;
    ALTER TABLE dbo.MasterMapping ADD CONSTRAINT ck_master_mapping_product_type
        CHECK (product_type IN ('Airline', 'Hotel', 'Bus', 'Visa', 'Insurance', 'Rail', 'Miscellaneous'));
END
GO
-- Other Taxes (migration 0059) - added after the table first shipped.
IF COL_LENGTH('dbo.Misc_Transactions', 'other_taxes') IS NULL
    ALTER TABLE dbo.Misc_Transactions ADD other_taxes NUMERIC(14,2) NOT NULL CONSTRAINT df_misc_other_taxes DEFAULT 0;
GO

-- --------------------------------------------------------------------------
-- 11.12 Company Master - chosen invoice print template (migration 0044).
-- --------------------------------------------------------------------------
IF COL_LENGTH('dbo.CompanyMaster', 'invoice_template') IS NULL
    ALTER TABLE dbo.CompanyMaster ADD invoice_template NVARCHAR(20) NOT NULL
        CONSTRAINT df_companymaster_invoice_template DEFAULT 'classic';
GO
-- Terms and Conditions printed on every invoice (migration 0045).
IF COL_LENGTH('dbo.CompanyMaster', 'terms_conditions') IS NULL
    ALTER TABLE dbo.CompanyMaster ADD terms_conditions NVARCHAR(MAX) NULL;
GO
-- Bank details, printed in the Payment Invoice's Bank Info row (migration 0046).
IF COL_LENGTH('dbo.CompanyMaster', 'bank_account_holder') IS NULL
    ALTER TABLE dbo.CompanyMaster ADD bank_account_holder NVARCHAR(100) NULL;
GO
IF COL_LENGTH('dbo.CompanyMaster', 'bank_account_no') IS NULL
    ALTER TABLE dbo.CompanyMaster ADD bank_account_no NVARCHAR(30) NULL;
GO
IF COL_LENGTH('dbo.CompanyMaster', 'bank_ifsc') IS NULL
    ALTER TABLE dbo.CompanyMaster ADD bank_ifsc NVARCHAR(15) NULL;
GO
IF COL_LENGTH('dbo.CompanyMaster', 'bank_swift') IS NULL
    ALTER TABLE dbo.CompanyMaster ADD bank_swift NVARCHAR(15) NULL;
GO
IF COL_LENGTH('dbo.CompanyMaster', 'bank_name') IS NULL
    ALTER TABLE dbo.CompanyMaster ADD bank_name NVARCHAR(100) NULL;
GO
IF COL_LENGTH('dbo.CompanyMaster', 'bank_branch') IS NULL
    ALTER TABLE dbo.CompanyMaster ADD bank_branch NVARCHAR(100) NULL;
GO

-- --------------------------------------------------------------------------
-- 11.7 Django Migrations Table Sync (Ensures python manage.py migrate is clean)
-- --------------------------------------------------------------------------
IF EXISTS (SELECT * FROM sys.tables WHERE name = 'django_migrations')
BEGIN
    INSERT INTO django_migrations (app, name, applied)
    SELECT 'accounting', v.name, SYSUTCDATETIME()
    FROM (VALUES
        -- Consolidated to one migration file per table (was 32 files) -
        -- see migrations_backup_* for the original pre-consolidation set.
        ('0001_companymaster'),
        ('0002_ledgergroup'),
        ('0003_ledger'),
        ('0004_ticket'),
        ('0005_ticketline'),
        ('0006_journalvoucher'),
        ('0007_voucher'),
        ('0008_vouchertype'),
        ('0009_suppliercommissionrule'),
        ('0010_mastermapping'),
        ('0011_fopmaster'),
        ('0012_pgmaster'),
        ('0013_pgmaster_pg_charges_percentage_effective_from'),
        ('0014_pgmasterhistory_and_more'),
        ('0015_ticketline_pg_charges_percentage'),
        ('0016_remove_companymaster_description'),
        ('0017_companymaster_pan_number'),
        ('0018_companymaster_currency_name_and_more'),
        ('0019_companymaster_logo_base64_companymaster_seal_base64'),
        ('0020_remove_vouchertype_allow_narration_in_each_ledger_and_more'),
        ('0021_rescheduleairlineticket_rescheduleairlineticketline_and_more'),
        ('0022_rename_supplier_penalty_rescheduleairlineticketline_reschedule_penalty'),
        ('0023_rescheduleairlineticketline_supplier_penalty'),
        ('0024_journalvoucher_source_reschedule_ticket_and_more'),
        ('0025_ticketline_is_reschedule_eligible'),
        ('0026_rescheduleairlineticketline_based_on_reschedule_line_and_more'),
        ('0027_rescheduleairlineticketline_parent_pnr'),
        ('0028_ticket_booking_status_normal_cancelled'),
        ('0029_rename_ticket_reschedule_tables'),
        ('0030_cancellation_airline_ticket'),
        ('0031_rename_tickets_company_e95274_idx_al_tickets_company_023cd9_idx_and_more'),
        ('0032_rename_tickets_company_e95274_idx_al_tickets_company_023cd9_idx_and_more'),
        ('0033_rename_tickets_company_e95274_idx_al_tickets_company_023cd9_idx_and_more'),
        ('0034_cancellation_journal_voucher'),
        ('0035_appuser_menumaster_usermenuaccess_and_more'),
        ('0036_seed_menu_master'),
        ('0037_appuser_password_hash'),
        ('0038_menu_master_user_management_super_admin_only'),
        ('0039_cancellation_line_tds_amount_override'),
        ('0040_menu_master_balance_sheet'),
        ('0041_ticketline_supp_ssr_markup_service_fee'),
        ('0042_ticketline_supp_ssr_db_default'),
        ('0043_ssr_airline_ticket'),
        ('0044_companymaster_invoice_template'),
        ('0045_companymaster_terms_conditions'),
        ('0046_companymaster_bank_details')
    ) AS v(name)
    WHERE NOT EXISTS (
        SELECT 1 FROM django_migrations WHERE app = 'accounting' AND name = v.name
    );
END
GO

-- --------------------------------------------------------------------------
-- 12. Quick sanity check
-- --------------------------------------------------------------------------
SELECT name AS table_name FROM sys.tables ORDER BY name;
SELECT company_id, COUNT(*) AS group_count FROM Ledger_Groups GROUP BY company_id ORDER BY company_id;
SELECT company_id, COUNT(*) AS ledger_count FROM Ledgers GROUP BY company_id ORDER BY company_id;
SELECT company_id, COUNT(*) AS master_mapping_count FROM MasterMapping GROUP BY company_id ORDER BY company_id;
SELECT company_id, COUNT(*) AS fop_count FROM FOPMaster GROUP BY company_id ORDER BY company_id;
SELECT company_id, COUNT(*) AS journal_voucher_count FROM JournalVoucher GROUP BY company_id ORDER BY company_id;
SELECT company_id, COUNT(*) AS voucher_count FROM Vouchers GROUP BY company_id ORDER BY company_id;
SELECT company_id, COUNT(*) AS pg_count FROM PGMaster GROUP BY company_id ORDER BY company_id;
SELECT company_id, COUNT(*) AS rule_count FROM SupplierCommissionRules GROUP BY company_id ORDER BY company_id;
SELECT company_id, COUNT(*) AS voucher_type_count FROM VoucherType GROUP BY company_id ORDER BY company_id;
SELECT COUNT(*) AS app_user_count FROM AppUsers;
SELECT module, COUNT(*) AS menu_count FROM MenuMaster GROUP BY module ORDER BY module;
GO

-- Airline dropdown lists with short codes (migration 0070).
IF OBJECT_ID('dbo.AirlineDropdownValues', 'U') IS NULL
CREATE TABLE dbo.AirlineDropdownValues (
    id            INT IDENTITY(1,1) PRIMARY KEY,
    list_key      NVARCHAR(50)  NOT NULL,   -- e.g. paxTypes (same key the screens use)
    code          NVARCHAR(10)  NOT NULL,   -- short ID for Auto Push / import, e.g. ADT
    name          NVARCHAR(100) NOT NULL,   -- value saved on the transaction, e.g. Adult
    display_label NVARCHAR(100) NULL,       -- text shown when it differs from name
    sort_order    INT NOT NULL DEFAULT 0,
    is_default    BIT NOT NULL DEFAULT 0,
    is_active     BIT NOT NULL DEFAULT 1,
    created_at    DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    updated_at    DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT uq_airline_dd_code UNIQUE (list_key, code),
    CONSTRAINT uq_airline_dd_name UNIQUE (list_key, name)
);
GO
MERGE dbo.AirlineDropdownValues AS t
USING (VALUES
    (N'bookingModes', N'MAN', N'Manual', NULL, 10, 1),
    (N'bookingModes', N'AUTO', N'Auto Push', NULL, 20, 0),
    (N'bookingTypes', N'TDB', N'Travel Desk Booking', NULL, 10, 0),
    (N'bookingTypes', N'MB', N'Manual Booking', NULL, 20, 0),
    (N'bookingTypes', N'RPA', N'Retrieve PNR Accounting', NULL, 30, 0),
    (N'bookingTypes', N'RPTI', N'Retrieve PNR Ticketing (I)', NULL, 40, 0),
    (N'bookingTypes', N'RPTQ', N'Retrieve PNR Ticketing (Q)', NULL, 50, 0),
    (N'bookingTypes', N'APIB', N'API Booking', NULL, 60, 0),
    (N'bookingTypes', N'ABW', N'Agent Booking (Web)', NULL, 70, 0),
    (N'bookingTypes', N'TC', N'Travel Co-ordinator', NULL, 80, 0),
    (N'bookingTypes', N'TCBM', N'Travel Co-ordinator Booking (Mobile)', NULL, 90, 0),
    (N'bookingTypes', N'EBSBT', N'Employee Booking (SBT)', NULL, 100, 0),
    (N'bookingTypes', N'MOB', N'Mobile Booking', NULL, 110, 0),
    (N'bookingTypes', N'IB', N'Indesk Booking', NULL, 120, 0),
    (N'bookingTypes', N'SUB', N'Super User Booking', NULL, 130, 0),
    (N'bookingTypes', N'MWB', N'Mobile Web Booking', NULL, 140, 0),
    (N'bookingTypes', N'EBM', N'Employee Booking (Mobile)', NULL, 150, 0),
    (N'bookingTypes', N'VTAMB', N'VTA - Mail Booking', NULL, 160, 0),
    (N'bookingTypes', N'SSR', N'SSR Updation', NULL, 170, 0),
    (N'bookingStatuses', N'C', N'Confirmed', NULL, 10, 0),
    (N'bookingStatuses', N'R', N'Re-Scheduled', NULL, 20, 0),
    (N'bookingStatuses', N'X', N'Normal Cancelled', NULL, 30, 0),
    (N'bookingStatuses', N'SSR', N'SSR Updated', NULL, 40, 0),
    (N'travelTypes', N'D', N'Domestic', NULL, 10, 0),
    (N'travelTypes', N'I', N'International', NULL, 20, 0),
    (N'custDiscountOn', N'BAS', N'Basic', NULL, 10, 0),
    (N'custDiscountOn', N'BYQ', N'Basic + YQ', NULL, 20, 0),
    (N'custDiscountOn', N'BYR', N'Basic + YR', NULL, 30, 0),
    (N'custDiscountOn', N'BYQYR', N'Basic + YQ + YR', NULL, 40, 0),
    (N'custDiscountOn', N'GRS', N'Gross', NULL, 50, 0),
    (N'custDiscountTypes', N'PCT', N'Percentage', NULL, 10, 0),
    (N'custDiscountTypes', N'FLT', N'Flat', NULL, 20, 0),
    (N'paxTypes', N'ADT', N'Adult', NULL, 10, 0),
    (N'paxTypes', N'CHLD', N'Child', NULL, 20, 0),
    (N'paxTypes', N'IFT', N'Infant', NULL, 30, 0),
    (N'paymentModes', N'1', N'Top-up', NULL, 10, 0),
    (N'paymentModes', N'2', N'Payment Gateway', NULL, 20, 0),
    (N'airlineCategories', N'LCC', N'LCC', NULL, 10, 0),
    (N'airlineCategories', N'FSC', N'FSC', NULL, 20, 0),
    (N'airlineCategories', N'OSC', N'OSC', NULL, 30, 0),
    (N'fopOptions', N'2', N'Own Card', NULL, 10, 0),
    (N'fopOptions', N'3', N'Client Card', NULL, 20, 0),
    (N'fopOptions', N'1', N'Cash', NULL, 30, 0),
    (N'cardTypes', N'2', N'Own Card', NULL, 10, 0),
    (N'cardTypes', N'3', N'Client Card', NULL, 20, 0),
    (N'cabinOptions', N'E', N'Economy', NULL, 10, 0),
    (N'cabinOptions', N'PE', N'Premium Economy', NULL, 20, 0),
    (N'cabinOptions', N'BC', N'Business Class', NULL, 30, 0),
    (N'cabinOptions', N'FC', N'First Class', NULL, 40, 0),
    (N'fareTypeOptions', N'NF', N'Normal Fare', NULL, 10, 0),
    (N'fareTypeOptions', N'CF', N'Corporate Fare', NULL, 20, 0),
    (N'fareTypeOptions', N'RF', N'Retail Fare', NULL, 30, 0),
    (N'fareTypeOptions', N'ECF', N'ECoupon Fare', NULL, 40, 0),
    (N'fareTypeOptions', N'SF', N'Special Fare', NULL, 50, 0),
    (N'fareTypeOptions', N'SMEF', N'SME Fare', NULL, 60, 0),
    (N'fareTypeOptions', N'FF', N'Flexi Fare', NULL, 70, 0),
    (N'fareTypeOptions', N'MF', N'Marine Fare', NULL, 80, 0),
    (N'fareTypeOptions', N'DF', N'Defence Fare', NULL, 90, 0),
    (N'fareTypeOptions', N'RTF', N'Roundtrip Special Fare', NULL, 100, 0),
    (N'fareTypeOptions', N'SCCF', N'SME Corporate/Corp Connect Fare', NULL, 110, 0),
    (N'fareTypeOptions', N'SMERF', N'SME Retail Fare', NULL, 120, 0),
    (N'fareTypeOptions', N'LF', N'Labour Fare', NULL, 130, 0),
    (N'fareTypeOptions', N'CFX', N'Corporate Flexi', NULL, 140, 0),
    (N'fareTypeOptions', N'STF', N'Student Fare', NULL, 150, 0),
    (N'fareTypeOptions', N'DS', N'Double Seat', NULL, 160, 0),
    (N'fareTypeOptions', N'SCF', N'Senior Citizen Fare', NULL, 170, 0),
    (N'dsrStatuses', N'CON', N'Confirmed', NULL, 10, 0),
    (N'dsrStatuses', N'RES', N'Re-Scheduled', N'Reschedule', 20, 0),
    (N'dsrStatuses', N'CAN', N'Normal Cancelled', N'Cancellation', 30, 0),
    (N'dsrStatuses', N'SSR', N'SSR Updated', N'SSR Updation', 40, 0),
    (N'ssrTypes', N'BAG', N'Baggage', NULL, 10, 0),
    (N'ssrTypes', N'MEAL', N'Meal', NULL, 20, 0),
    (N'ssrTypes', N'SEAT', N'Seat', NULL, 30, 0),
    (N'ssrTypes', N'OTH', N'Other SSR', NULL, 40, 0)
) AS s (list_key, code, name, display_label, sort_order, is_default)
ON t.list_key = s.list_key AND t.code = s.code
WHEN NOT MATCHED THEN
    INSERT (list_key, code, name, display_label, sort_order, is_default, is_active, created_at, updated_at)
    VALUES (s.list_key, s.code, s.name, s.display_label, s.sort_order, s.is_default, 1, SYSUTCDATETIME(), SYSUTCDATETIME());
GO

-- Edit history of Booking / Reschedule / Cancellation / SSR Updation (migration 0071).
IF OBJECT_ID('dbo.AuditLogs', 'U') IS NULL
CREATE TABLE dbo.AuditLogs (
    id           INT IDENTITY(1,1) PRIMARY KEY,
    company_id   INT NOT NULL,
    module       NVARCHAR(30)  NOT NULL,   -- Booking / Reschedule / Cancellation / SSR Updation
    document_id  INT NOT NULL,
    document_no  NVARCHAR(50)  NULL,       -- Invoice Number at the time of the change
    action       NVARCHAR(20)  NOT NULL,   -- CREATE / UPDATE
    source       NVARCHAR(150) NULL,       -- set when the change came from another document's edit
    user_id      INT NULL,
    user_name    NVARCHAR(150) NULL,
    change_count INT NOT NULL DEFAULT 0,
    changes      NVARCHAR(MAX) NULL,       -- JSON [{scope, line, field, old, new}]
    changed_at   DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_audit_logs_document')
    CREATE INDEX ix_audit_logs_document ON dbo.AuditLogs (company_id, module, document_id);
GO

-- Edit history, one row per changed field (migration 0072) - backend only.
CREATE OR ALTER VIEW dbo.vw_AuditLogChanges AS
-- Edit history of the airline entries (Booking / Reschedule / Cancellation /
-- SSR Updation), one row per changed field - backend only, e.g.
--   SELECT * FROM dbo.vw_AuditLogChanges WHERE document_no = 'TA/TAX/00012/26-27' ORDER BY changed_at_ist DESC;
--   SELECT * FROM dbo.vw_AuditLogChanges WHERE user_name = 'Rahul Mehta' ORDER BY changed_at_ist DESC;
SELECT a.id AS log_id, a.company_id, a.module, a.document_id, a.document_no,
       a.action, a.source, a.user_id, a.user_name,
       CAST(SWITCHOFFSET(a.changed_at, '+05:30') AS DATETIME2(0)) AS changed_at_ist,   -- stored in UTC; shown in India time
       j.scope, j.line AS passenger, j.field, j.old AS old_value, j.new AS new_value
FROM dbo.AuditLogs a
OUTER APPLY OPENJSON(NULLIF(a.changes, '[]')) WITH (
    scope NVARCHAR(40) '$.scope', line NVARCHAR(200) '$.line', field NVARCHAR(100) '$.field',
    old NVARCHAR(MAX) '$.old', new NVARCHAR(MAX) '$.new'
) j;
GO


-- Airline ticket Auto Push import (migration 0074) - staging table + run log.
-- See accounting/ticket_import.py.
IF OBJECT_ID('dbo.Ticket_Import_Staging', 'U') IS NULL
CREATE TABLE dbo.Ticket_Import_Staging (
    staging_id                  BIGINT IDENTITY(1,1) PRIMARY KEY,

    -- Source identity. doc_ref groups the passengers of one invoice;
    -- source_system + source_record_id (one passenger) is never imported twice.
    batch_id                    NVARCHAR(50)   NULL,
    source_system               NVARCHAR(50)   NOT NULL,
    doc_ref                     NVARCHAR(60)   NOT NULL,
    source_record_id            NVARCHAR(100)  NOT NULL,
    received_at                 DATETIME2      NOT NULL CONSTRAINT df_tis_received DEFAULT SYSUTCDATETIME(),

    -- Decides the target: Confirmed -> AL_Tickets, Rescheduled -> Rescheduled_Al_Ticket,
    -- Cancelled -> Cancellation_AL_Tickets (each + its lines + its Journal Voucher).
    ticket_status               NVARCHAR(20)   NOT NULL
        CONSTRAINT ck_tis_ticket_status CHECK (ticket_status IN ('Confirmed', 'Rescheduled', 'Cancelled', 'SSR')),
    company_id                  INT            NOT NULL,
    doc_key AS (ticket_status + N'|' + CAST(company_id AS NVARCHAR(10)) + N'|' + source_system + N'|' + doc_ref) PERSISTED,

    /* ---- Header ---- */
    invoice_number              NVARCHAR(20)   NULL,      -- blank = generated from the Invoice Type's numbering
    invoice_date                DATE           NULL,
    invoice_type                NVARCHAR(100)  NULL,
    booking_mode                NVARCHAR(20)   NULL,
    booking_type                NVARCHAR(50)   NULL,
    booking_status              NVARCHAR(20)   NULL,
    customer_name               NVARCHAR(150)  NULL,
    supplier_name               NVARCHAR(150)  NULL,
    travel_type                 NVARCHAR(20)   NULL,
    user_name                   NVARCHAR(100)  NULL,
    currency                    NVARCHAR(5)    NULL,
    roe                         DECIMAL(10,4)  NULL,
    booking_given_by            NVARCHAR(25)   NULL,
    booking_reference           NVARCHAR(30)   NULL,      -- S PNR (Cancelled -> cancellation_reference)
    booking_ref_date            DATE           NULL,      -- (Cancelled -> cancellation_ref_date)
    airline_pnr                 NVARCHAR(13)   NULL,
    gds_pnr                     NVARCHAR(13)   NULL,
    office_id                   NVARCHAR(30)   NULL,
    payment_mode                NVARCHAR(20)   NULL,
    payment_gateway_ref         NVARCHAR(60)   NULL,
    airline_category            NVARCHAR(5)    NULL,

    /* ---- Passenger line ---- */
    original_ticket_no          NVARCHAR(30)   NULL,      -- Rescheduled / Cancelled: the passenger's current live Ticket No.
    airline_code                NVARCHAR(200)  NULL,
    airline_name                NVARCHAR(200)  NULL,
    line_airline_category       NVARCHAR(5)    NULL,
    flight_no                   NVARCHAR(200)  NULL,      -- multi-city: comma-joined, same order as sector
    ticket_no                   NVARCHAR(30)   NULL,
    passenger_name              NVARCHAR(50)   NULL,
    pax_type                    NVARCHAR(10)   NULL,
    sector                      NVARCHAR(200)  NULL,      -- e.g. MAA-DXB,DXB-MAA
    travel_date                 NVARCHAR(200)  NULL,      -- dd/mm/yyyy, comma-joined per sector
    cabin                       NVARCHAR(200)  NULL,
    travel_class                NVARCHAR(200)  NULL,
    fare_type                   NVARCHAR(300)  NULL,
    line_supplier_name          NVARCHAR(150)  NULL,
    line_office_id              NVARCHAR(30)   NULL,
    fop                         NVARCHAR(20)   NULL,
    card_number                 NVARCHAR(40)   NULL,
    line_status                 NVARCHAR(15)   NULL,

    /* ---- Fares ---- */
    basic_fare                  DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_basic DEFAULT 0,
    yq                          DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_yq DEFAULT 0,
    yr                          DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_yr DEFAULT 0,
    k3_tax                      DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_k3 DEFAULT 0,
    tax_others                  DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_taxo DEFAULT 0,
    seat                        DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_seat DEFAULT 0,
    meal                        DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_meal DEFAULT 0,
    baggage                     DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_bag DEFAULT 0,
    other_ssr                   DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_ossr DEFAULT 0,

    /* ---- Customer side ---- */
    disc_on                     NVARCHAR(20)   NULL,
    disc_type                   NVARCHAR(12)   NULL,
    disc_value                  DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_discv DEFAULT 0,
    tds_per                     DECIMAL(5,2)   NOT NULL CONSTRAINT df_tis_tds DEFAULT 0,
    pg_charges                  DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_pg DEFAULT 0,
    pg_charges_percentage       DECIMAL(5,2)   NOT NULL CONSTRAINT df_tis_pgp DEFAULT 0,
    markup                      DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_mk DEFAULT 0,
    addl_markup                 DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_amk DEFAULT 0,
    ssr_markup                  DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_smk DEFAULT 0,
    service_fee                 DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_sf DEFAULT 0,
    addl_service_fee            DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_asf DEFAULT 0,
    ssr_service_fee             DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_ssf DEFAULT 0,
    gst_pct                     DECIMAL(5,2)   NOT NULL CONSTRAINT df_tis_gst DEFAULT 0,

    /* ---- Supplier side ---- */
    supp_comm_on                NVARCHAR(20)   NULL,
    supp_comm_type              NVARCHAR(12)   NULL,
    supp_comm_value             DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_scv DEFAULT 0,
    supp_tds_per                DECIMAL(5,2)   NOT NULL CONSTRAINT df_tis_stds DEFAULT 0,
    supp_markup                 DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_smku DEFAULT 0,
    supp_addl_markup            DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_samk DEFAULT 0,
    supp_ssr_markup             DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_ssmk DEFAULT 0,
    supp_service_fee            DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_ssfe DEFAULT 0,
    supp_addl_service_fee       DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_sasf DEFAULT 0,
    supp_ssr_service_fee        DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_sssf DEFAULT 0,
    supp_gst_pct                DECIMAL(5,2)   NOT NULL CONSTRAINT df_tis_sgst DEFAULT 0,

    /* ---- Rescheduled / Cancelled ---- */
    agent_penalty               DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_agp DEFAULT 0,
    reschedule_penalty          DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_rsp DEFAULT 0,
    supplier_penalty            DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_spp DEFAULT 0,
    cancellation_penalty        DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_cxp DEFAULT 0,
    cust_markup_reversal        DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_cmr DEFAULT 0,
    cust_addl_markup_reversal   DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_camr DEFAULT 0,
    cust_ssr_markup_reversal    DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_csmr DEFAULT 0,
    supp_markup_reversal        DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_smr DEFAULT 0,
    supp_addl_markup_reversal   DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_samr DEFAULT 0,
    supp_ssr_markup_reversal    DECIMAL(14,2)  NOT NULL CONSTRAINT df_tis_ssmr DEFAULT 0,
    tds_amount_override         DECIMAL(14,2)  NULL,
    supp_tds_amount_override    DECIMAL(14,2)  NULL,

    total_billed                DECIMAL(14,2)  NULL,      -- as sent by the source
    raw_payload                 NVARCHAR(MAX)  NULL,      -- {"header": {...}, "passenger": {...}} exactly as received

    /* ---- Processing ---- */
    process_status              NVARCHAR(20)   NOT NULL CONSTRAINT df_tis_pstatus DEFAULT 'Pending'
        CONSTRAINT ck_tis_process_status CHECK (process_status IN ('Pending', 'Processing', 'Imported', 'Error', 'Skipped')),
    retry_count                 INT            NOT NULL CONSTRAINT df_tis_retry DEFAULT 0,
    error_message               NVARCHAR(1000) NULL,
    run_id                      BIGINT         NULL,
    picked_at                   DATETIME2      NULL,
    processed_at                DATETIME2      NULL,
    target_header_id            INT            NULL,      -- AL_Tickets.id / Rescheduled_Al_Ticket.id / Cancellation_AL_Tickets.id
    saved_invoice_number        NVARCHAR(20)   NULL,      -- the Invoice / Credit Note number it was saved under
    saved_voucher_no            NVARCHAR(30)   NULL,      -- the Journal Voucher posted with it

    CONSTRAINT uq_tis_source_record UNIQUE (source_system, source_record_id)
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_tis_doc_key' AND object_id = OBJECT_ID('dbo.Ticket_Import_Staging'))
    CREATE INDEX ix_tis_doc_key ON dbo.Ticket_Import_Staging (doc_key) INCLUDE (process_status);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_tis_pending' AND object_id = OBJECT_ID('dbo.Ticket_Import_Staging'))
    CREATE INDEX ix_tis_pending ON dbo.Ticket_Import_Staging (process_status, company_id, staging_id);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_tis_ticket_no' AND object_id = OBJECT_ID('dbo.Ticket_Import_Staging'))
    CREATE INDEX ix_tis_ticket_no ON dbo.Ticket_Import_Staging (company_id, ticket_no);
GO
IF OBJECT_ID('dbo.Ticket_Import_Run_Log', 'U') IS NULL
CREATE TABLE dbo.Ticket_Import_Run_Log (
    run_id          BIGINT IDENTITY(1,1) PRIMARY KEY,
    company_id      INT            NULL,
    started_at      DATETIME2      NOT NULL CONSTRAINT df_tirl_started DEFAULT SYSUTCDATETIME(),
    finished_at     DATETIME2      NULL,
    rows_picked     INT            NOT NULL CONSTRAINT df_tirl_picked DEFAULT 0,
    docs_imported   INT            NOT NULL CONSTRAINT df_tirl_imported DEFAULT 0,
    docs_failed     INT            NOT NULL CONSTRAINT df_tirl_failed DEFAULT 0,
    message         NVARCHAR(1000) NULL
);
GO

-- Auto Push validation (migration 0078): error log + the Invoice Type picked per Booking Status.
IF OBJECT_ID('dbo.Ticket_Import_Error_Log', 'U') IS NULL
CREATE TABLE dbo.Ticket_Import_Error_Log (
    error_log_id        BIGINT IDENTITY(1,1) PRIMARY KEY,
    logged_at           DATETIME2      NOT NULL CONSTRAINT df_tiel_logged DEFAULT SYSUTCDATETIME(),
    company_id          INT            NULL,
    source_system       NVARCHAR(50)   NULL,
    batch_id            NVARCHAR(50)   NULL,
    doc_key             NVARCHAR(200)  NULL,      -- Ticket_Import_Staging.doc_key when it could be worked out
    booking_status      NVARCHAR(20)   NULL,      -- as received (C / R / X)
    booking_reference   NVARCHAR(60)   NULL,
    parent_pnr          NVARCHAR(60)   NULL,
    passenger_no        INT            NULL,      -- 1-based position in passengers[]; NULL = invoice level
    ticket_no           NVARCHAR(60)   NULL,
    passenger_name      NVARCHAR(100)  NULL,
    field_name          NVARCHAR(100)  NULL,      -- API parameter, e.g. card_number
    field_label         NVARCHAR(100)  NULL,      -- screen name, e.g. Card Number
    received_value      NVARCHAR(500)  NULL,
    expected_value      NVARCHAR(500)  NULL,
    error_type          NVARCHAR(30)   NOT NULL,  -- Missing / Invalid Format / Not Mapped / Mismatch / Not Allowed / Duplicate / Unknown Field / Save Failed
    severity            NVARCHAR(10)   NOT NULL CONSTRAINT df_tiel_severity DEFAULT 'Error',   -- Error / Warning
    stage               NVARCHAR(20)   NOT NULL,  -- Validation (push rejected) / Import (save refused)
    error_message       NVARCHAR(1000) NOT NULL,
    is_resolved         BIT            NOT NULL CONSTRAINT df_tiel_resolved DEFAULT 0,
    resolved_at         DATETIME2      NULL,
    resolved_note       NVARCHAR(200)  NULL
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_tiel_company_logged')
    CREATE INDEX ix_tiel_company_logged ON dbo.Ticket_Import_Error_Log (company_id, logged_at DESC);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_tiel_doc_key')
    CREATE INDEX ix_tiel_doc_key ON dbo.Ticket_Import_Error_Log (doc_key) WHERE doc_key IS NOT NULL;
GO
IF OBJECT_ID('dbo.Ticket_Import_Invoice_Type', 'U') IS NULL
CREATE TABLE dbo.Ticket_Import_Invoice_Type (
    id                  INT IDENTITY(1,1) PRIMARY KEY,
    company_id          INT            NOT NULL,
    ticket_status       NVARCHAR(20)   NOT NULL
        CONSTRAINT ck_tiit_ticket_status CHECK (ticket_status IN ('Confirmed', 'Rescheduled', 'Cancelled', 'SSR')),
    voucher_type_id     INT            NOT NULL
        CONSTRAINT fk_tiit_voucher_type REFERENCES dbo.VoucherType (id) ON DELETE CASCADE,
    updated_at          DATETIME2      NOT NULL CONSTRAINT df_tiit_updated DEFAULT SYSUTCDATETIME(),
    CONSTRAINT uq_tiit_company_status UNIQUE (company_id, ticket_status)
);
GO

-- Booking Status SSR (migration 0089) on databases created before it.
IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'ck_tis_ticket_status'
           AND definition NOT LIKE '%SSR%')
BEGIN
    ALTER TABLE dbo.Ticket_Import_Staging DROP CONSTRAINT ck_tis_ticket_status;
    ALTER TABLE dbo.Ticket_Import_Staging ADD CONSTRAINT ck_tis_ticket_status
        CHECK (ticket_status IN ('Confirmed', 'Rescheduled', 'Cancelled', 'SSR'));
END
IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'ck_tiit_ticket_status'
           AND definition NOT LIKE '%SSR%')
BEGIN
    ALTER TABLE dbo.Ticket_Import_Invoice_Type DROP CONSTRAINT ck_tiit_ticket_status;
    ALTER TABLE dbo.Ticket_Import_Invoice_Type ADD CONSTRAINT ck_tiit_ticket_status
        CHECK (ticket_status IN ('Confirmed', 'Rescheduled', 'Cancelled', 'SSR'));
END
GO

-- Ledger Mapping pins (migration 0079): "Retain old ledgers" on a back-dated mapping.
IF OBJECT_ID('dbo.MasterMappingPin', 'U') IS NULL
CREATE TABLE dbo.MasterMappingPin (
    id                  INT IDENTITY(1,1) PRIMARY KEY,
    company_id          INT            NOT NULL,
    product_type        NVARCHAR(20)   NOT NULL,
    field_name          NVARCHAR(100)  NOT NULL,
    doc_type            NVARCHAR(20)   NOT NULL
        CONSTRAINT ck_mmp_doc_type CHECK (doc_type IN ('ticket', 'reschedule', 'cancellation', 'ssr', 'misc')),
    doc_id              INT            NOT NULL,
    doc_date            DATE           NOT NULL,
    ledger_id           INT            NOT NULL CONSTRAINT fk_mmp_ledger REFERENCES dbo.Ledgers (id),
    ledger_name         NVARCHAR(200)  NULL,
    masters_category    NVARCHAR(40)   NULL,
    effective_from      DATE           NULL,      -- Effective From of the mapping the document was pinned to
    created_at          DATETIME2      NOT NULL CONSTRAINT df_mmp_created DEFAULT SYSUTCDATETIME(),
    CONSTRAINT uq_mmp_doc_field UNIQUE (company_id, product_type, field_name, doc_type, doc_id)
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_mmp_doc')
    CREATE INDEX ix_mmp_doc ON dbo.MasterMappingPin (doc_type, doc_id);
GO

-- Auto Push GST amounts (migration 0080): the Agent's own GST, used as sent.
IF OBJECT_ID('dbo.Ticket_Line_Gst_Amount', 'U') IS NULL
CREATE TABLE dbo.Ticket_Line_Gst_Amount (
    line_type                   NVARCHAR(20)   NOT NULL
        CONSTRAINT ck_tlga_line_type CHECK (line_type IN ('ticket', 'reschedule', 'cancellation')),
    doc_id                      INT            NOT NULL,      -- AL_Tickets / Rescheduled_Al_Ticket / Cancellation_AL_Tickets id
    ticket_no                   NVARCHAR(30)   NOT NULL,      -- the line's own Ticket No.
    service_fee_gst             DECIMAL(14,2)  NULL,          -- NULL = worked out from Ledger Mapping GST %
    addl_service_fee_gst        DECIMAL(14,2)  NULL,
    ssr_service_fee_gst         DECIMAL(14,2)  NULL,
    supp_service_fee_gst        DECIMAL(14,2)  NULL,
    supp_addl_service_fee_gst   DECIMAL(14,2)  NULL,
    supp_ssr_service_fee_gst    DECIMAL(14,2)  NULL,
    source                      NVARCHAR(30)   NOT NULL CONSTRAINT df_tlga_source DEFAULT 'Auto Push',
    created_at                  DATETIME2      NOT NULL CONSTRAINT df_tlga_created DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_tlga PRIMARY KEY (line_type, doc_id, ticket_no)
);
GO

-- Direct Reschedule / Direct Cancellation (migration 0081): a Reschedule or
-- Cancellation whose booking was never entered in this software has no
-- original_ticket_id / original_ticket_line_id - only its Parent PNR.
-- Each column: plain indexes and FK dropped and put back around ALTER COLUMN;
-- the cancellation line's UNIQUE becomes a filtered unique index.
DECLARE @t SYSNAME, @c SYSNAME, @drop NVARCHAR(MAX), @create NVARCHAR(MAX);
DECLARE cols CURSOR LOCAL FAST_FORWARD FOR
    SELECT t, c FROM (VALUES
        ('Rescheduled_Al_Ticket', 'original_ticket_id'),
        ('Rescheduled_Al_TicketLines', 'original_ticket_line_id'),
        ('Cancellation_AL_Tickets', 'original_ticket_id'),
        ('Cancellation_Al_TicketLines', 'original_ticket_line_id')) v (t, c);
OPEN cols;
FETCH NEXT FROM cols INTO @t, @c;
WHILE @@FETCH_STATUS = 0
BEGIN
    IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.' + @t) AND name = @c AND is_nullable = 0)
    BEGIN
        SELECT @drop = N'', @create = N'';
        SELECT @drop += CASE WHEN i.is_unique_constraint = 1
                             THEN N'ALTER TABLE dbo.' + QUOTENAME(@t) + N' DROP CONSTRAINT ' + QUOTENAME(i.name) + N'; '
                             ELSE N'DROP INDEX ' + QUOTENAME(i.name) + N' ON dbo.' + QUOTENAME(@t) + N'; ' END,
               @create += CASE WHEN i.is_unique = 1 THEN N''
                               ELSE N'CREATE INDEX ' + QUOTENAME(i.name) + N' ON dbo.' + QUOTENAME(@t) + N' (' + QUOTENAME(@c) + N'); ' END
        FROM sys.indexes i
        INNER JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
        INNER JOIN sys.columns cc ON cc.object_id = ic.object_id AND cc.column_id = ic.column_id
        WHERE i.object_id = OBJECT_ID('dbo.' + @t) AND cc.name = @c AND i.is_primary_key = 0;
        SELECT @drop += N'ALTER TABLE dbo.' + QUOTENAME(@t) + N' DROP CONSTRAINT ' + QUOTENAME(fk.name) + N'; ',
               @create += N'ALTER TABLE dbo.' + QUOTENAME(@t) + N' ADD CONSTRAINT ' + QUOTENAME(fk.name) + N' FOREIGN KEY ('
                          + QUOTENAME(@c) + N') REFERENCES dbo.' + QUOTENAME(OBJECT_NAME(fk.referenced_object_id)) + N' (id); '
        FROM sys.foreign_keys fk
        INNER JOIN sys.foreign_key_columns fc ON fc.constraint_object_id = fk.object_id
        INNER JOIN sys.columns cc ON cc.object_id = fc.parent_object_id AND cc.column_id = fc.parent_column_id
        WHERE fk.parent_object_id = OBJECT_ID('dbo.' + @t) AND cc.name = @c;
        EXEC (@drop);
        EXEC (N'ALTER TABLE dbo.' + @t + N' ALTER COLUMN ' + @c + N' INT NULL;');
        EXEC (@create);
    END
    FETCH NEXT FROM cols INTO @t, @c;
END
CLOSE cols;
DEALLOCATE cols;
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.Cancellation_Al_TicketLines') AND name = 'uq_cancel_line_original_line')
    CREATE UNIQUE INDEX uq_cancel_line_original_line ON dbo.Cancellation_Al_TicketLines (original_ticket_line_id)
        WHERE original_ticket_line_id IS NOT NULL;
IF COL_LENGTH('dbo.Cancellation_AL_Tickets', 'parent_pnr') IS NULL
    ALTER TABLE dbo.Cancellation_AL_Tickets ADD parent_pnr NVARCHAR(30) NULL;
IF COL_LENGTH('dbo.Cancellation_Al_TicketLines', 'reschedule_line_id') IS NULL
    ALTER TABLE dbo.Cancellation_Al_TicketLines ADD reschedule_line_id INT NULL;
GO

-- Ticket Entry Attributes popup (migration 0083): Field / Value pairs saved with a
-- Booking / Reschedule / Cancellation under its Invoice Number.
IF OBJECT_ID('dbo.Ticket_Document_Attribute', 'U') IS NULL
CREATE TABLE dbo.Ticket_Document_Attribute (
    attribute_id    INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_tda PRIMARY KEY,
    company_id      INT            NOT NULL,
    doc_type        NVARCHAR(20)   NOT NULL
        CONSTRAINT ck_tda_doc_type CHECK (doc_type IN ('ticket', 'reschedule', 'cancellation')),
    doc_id          INT            NOT NULL,      -- AL_Tickets / Rescheduled_Al_Ticket / Cancellation_AL_Tickets id
    invoice_number  NVARCHAR(20)   NULL,          -- the document's Invoice Number when saved
    sort_order      INT            NOT NULL,      -- row # in the popup
    field_name      NVARCHAR(100)  NOT NULL,
    field_value     NVARCHAR(500)  NULL,
    created_at      DATETIME2      NOT NULL CONSTRAINT df_tda_created DEFAULT SYSUTCDATETIME()
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_tda_doc')
    CREATE INDEX ix_tda_doc ON dbo.Ticket_Document_Attribute (doc_type, doc_id);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_tda_invoice')
    CREATE INDEX ix_tda_invoice ON dbo.Ticket_Document_Attribute (company_id, invoice_number);
GO

-- PG Master back-dated change, "Retain old ledgers" (migration 0084): a saved
-- document kept on the PG settings it used.
IF OBJECT_ID('dbo.PGMasterPin', 'U') IS NULL
CREATE TABLE dbo.PGMasterPin (
    pin_id                          INT IDENTITY(1,1) NOT NULL CONSTRAINT pk_pgmp PRIMARY KEY,
    company_id                      INT            NOT NULL,
    gateway_name                    NVARCHAR(100)  NOT NULL,
    doc_type                        NVARCHAR(20)   NOT NULL
        CONSTRAINT ck_pgmp_doc_type CHECK (doc_type IN ('ticket', 'reschedule', 'cancellation')),
    doc_id                          INT            NOT NULL,      -- AL_Tickets / Rescheduled_Al_Ticket / Cancellation_AL_Tickets id
    doc_date                        DATE           NULL,
    payment_master_ledger_id        INT            NULL,
    payment_master_ledger_name      NVARCHAR(200)  NULL,
    pg_charges_master_ledger_id     INT            NULL,
    pg_charges_master_ledger_name   NVARCHAR(200)  NULL,
    pg_charges_percentage           DECIMAL(5,2)   NULL,
    effective_from                  DATE           NULL,          -- Effective From of the snapshot the document was pinned to
    created_at                      DATETIME2      NOT NULL CONSTRAINT df_pgmp_created DEFAULT SYSUTCDATETIME(),
    CONSTRAINT uq_pgmp_doc UNIQUE (company_id, doc_type, doc_id)
);
GO

-- Automated Database Scheduler (migration 0085): one row per run that fetched
-- rows from the Airline_Agent database (agent_db_scheduler.py).
IF OBJECT_ID('dbo.Agent_DB_Scheduler_Log', 'U') IS NULL
CREATE TABLE dbo.Agent_DB_Scheduler_Log (
    log_id              BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_adsl PRIMARY KEY,
    run_started_at      DATETIME2      NOT NULL,      -- UTC; listed in IST
    run_finished_at     DATETIME2      NULL,
    source_database     NVARCHAR(128)  NULL,          -- AGENT_DB_NAME  (.env)
    source_table        NVARCHAR(128)  NULL,          -- AGENT_DB_TABLE (.env)
    records_fetched     INT            NOT NULL,      -- passenger rows picked up
    invoices_fetched    INT            NOT NULL,      -- invoices they make up
    imported_count      INT            NOT NULL CONSTRAINT df_adsl_imported DEFAULT 0,   -- rows saved as invoices
    pending_count       INT            NOT NULL CONSTRAINT df_adsl_pending DEFAULT 0,    -- rows queued (waiting for their parent ticket)
    error_count         INT            NOT NULL CONSTRAINT df_adsl_error DEFAULT 0,      -- rows Rejected / Duplicate / Error
    message             NVARCHAR(1000) NULL
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_adsl_started')
    CREATE INDEX ix_adsl_started ON dbo.Agent_DB_Scheduler_Log (run_started_at);
GO

-- Automated Database Scheduler (migration 0086): one row per Agent row
-- (passenger) picked up - its status, invoice and error. The Agent's own
-- table (Airline_Agent) holds only the Agent's data.
IF OBJECT_ID('dbo.Agent_DB_Ticket_Log', 'U') IS NULL
CREATE TABLE dbo.Agent_DB_Ticket_Log (
    ticket_log_id       BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_adtl PRIMARY KEY,
    source_database     NVARCHAR(128)  NOT NULL,      -- AGENT_DB_NAME  (.env)
    source_table        NVARCHAR(128)  NOT NULL,      -- AGENT_DB_TABLE (.env)
    agent_row_id        BIGINT         NOT NULL,      -- the Agent row (one passenger)
    scheduler_log_id    BIGINT         NULL,          -- Agent_DB_Scheduler_Log run that picked it up
    company_id          INT            NULL,
    booking_status      NVARCHAR(100)  NULL,          -- as the Agent sent it (C / R / X)
    booking_reference   NVARCHAR(100)  NULL,
    ticket_no           NVARCHAR(100)  NULL,
    pax_name            NVARCHAR(100)  NULL,
    process_status      NVARCHAR(20)   NOT NULL
        CONSTRAINT ck_adtl_status CHECK (process_status IN ('Processing', 'Imported', 'Pending', 'Rejected', 'Duplicate', 'Error')),
    processing_at       DATETIME2      NOT NULL CONSTRAINT df_adtl_processing DEFAULT SYSUTCDATETIME(),   -- picked up (UTC)
    processed_at        DATETIME2      NULL,          -- result written (UTC)
    invoice_number      NVARCHAR(30)   NULL,
    voucher_no          NVARCHAR(30)   NULL,
    import_doc_key      NVARCHAR(200)  NULL,          -- Ticket_Import_Staging.doc_key
    error_message       NVARCHAR(2000) NULL,
    CONSTRAINT uq_adtl_agent_row UNIQUE (source_database, source_table, agent_row_id)
);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_adtl_status')
    CREATE INDEX ix_adtl_status ON dbo.Agent_DB_Ticket_Log (process_status, import_doc_key);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_adtl_run')
    CREATE INDEX ix_adtl_run ON dbo.Agent_DB_Ticket_Log (scheduler_log_id);
GO

-- Branch removed from the application (migration 0093).
IF COL_LENGTH('dbo.AL_Tickets', 'branch_name') IS NOT NULL ALTER TABLE dbo.AL_Tickets DROP COLUMN branch_name;
IF COL_LENGTH('dbo.Rescheduled_Al_Ticket', 'branch_name') IS NOT NULL ALTER TABLE dbo.Rescheduled_Al_Ticket DROP COLUMN branch_name;
IF COL_LENGTH('dbo.Cancellation_AL_Tickets', 'branch_name') IS NOT NULL ALTER TABLE dbo.Cancellation_AL_Tickets DROP COLUMN branch_name;
IF COL_LENGTH('dbo.SSR_AL_Tickets', 'branch_name') IS NOT NULL ALTER TABLE dbo.SSR_AL_Tickets DROP COLUMN branch_name;
IF COL_LENGTH('dbo.Misc_Transactions', 'branch_name') IS NOT NULL ALTER TABLE dbo.Misc_Transactions DROP COLUMN branch_name;
IF COL_LENGTH('dbo.JournalVoucher', 'branch_name') IS NOT NULL ALTER TABLE dbo.JournalVoucher DROP COLUMN branch_name;
IF COL_LENGTH('dbo.Vouchers', 'branch_name') IS NOT NULL ALTER TABLE dbo.Vouchers DROP COLUMN branch_name;
IF COL_LENGTH('dbo.AppUsers', 'branch_name') IS NOT NULL ALTER TABLE dbo.AppUsers DROP COLUMN branch_name;
IF COL_LENGTH('dbo.Ticket_Import_Staging', 'branch_name') IS NOT NULL ALTER TABLE dbo.Ticket_Import_Staging DROP COLUMN branch_name;
GO
