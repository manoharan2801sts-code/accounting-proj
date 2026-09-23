/**
 * Voyager ERP — Hardcoded UI/Reference Data
 * ------------------------------------------------------------------
 * SINGLE source for hardcoded, non-business-transactional data:
 * sidebar/menu structure, status pill tone mapping, dashboard KPI
 * card definitions, and loader copy.
 *
 * This is separate from mock-data.js (VoyagerMock), which simulates
 * the API layer (records + CRUD) for demo/offline mode — that stays
 * where it is since it's mock business logic, not display config.
 *
 * Loaded before shell.js, util.js and dashboard.js in every page —
 * those files now read from window.VoyagerHardcode instead of
 * defining their own copies. Nothing about how they fetch, compute,
 * or render data has changed — only where the label/icon/status
 * strings come from.
 * ------------------------------------------------------------------
 */
(function (window) {
  if (!window.API_BASE) {
    window.API_BASE =
      window.location.protocol === "file:" || ((window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") && window.location.port !== "8000")
        ? "http://127.0.0.1:8000/api"
        : "/api";
  }

  // Sidebar + top pulldown menu structure.
  // Moved out of shell.js (was: local NAV_SECTIONS).
  const NAV_SECTIONS = [
    { label: "Home", items: [
      { key: "dashboard", label: "Home", href: "dashboard.html", icon: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" },
    ]},
    { label: "Masters", forceDropdown: true, items: [
      { key: "accounts", label: "Chart of Accounts", href: "accounts.html", icon: "M4 19.5A2.5 2.5 0 016.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" },
      { key: "company-master", label: "Company Master", href: "company-master.html", icon: "M3 21h18M5 21V7l7-4 7 4v14M9 9h1m4 0h1m-6 4h1m4 0h1m-6 4h1m4 0h1" },
      { key: "groups", label: "Groups", href: "groups.html", icon: "M3 3h18v6H3zM3 15h18v6H3zM3 9h18v6H3z" },
      { key: "voucher-type", label: "Voucher Type", href: "voucher-type.html", icon: "M17 3a2.85 2.85 0 114 4L7.5 20.5 2 22l1.5-5.5z" },
      { key: "supplier-master", label: "Supplier Master", href: "supplier-master.html", icon: "M1 4h22v16H1zM1 10h22" },
      { key: "master-mapping", label: "Ledger Mapping", href: "master-mapping.html", icon: "M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" },
      { key: "fop-master", label: "FOP Master", href: "fop-master.html", icon: "M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" },
      { key: "pg-master", label: "PG Master", href: "pg-master.html", icon: "M17 1l4 4-4 4M3 11V9a4 4 0 014-4h14M7 23l-4-4 4-4M21 13v2a4 4 0 01-4 4H3" },
    ]},
    { label: "Transactions", forceDropdown: true, items: [
      {
        key: "trans-airline",
        label: "Airline",
        icon: "M2 16l20-8-8 20-2-8-8-2z",
        children: [
          { key: "tickets", label: "Booking", href: "ticket-entry.html" },
          { key: "trans-airline-reschedule", label: "Reschedule", href: "trans-airline-reschedule.html" },
          { key: "trans-airline-cancellation", label: "Cancellation", href: "trans-airline-cancellation.html" },
          { key: "trans-airline-ssr", label: "SSR Updation", href: "trans-airline-ssr.html" },
        ]
      },
      {
        key: "trans-hotels",
        label: "Hotel",
        icon: "M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4",
        children: [
          { key: "trans-hotels-booking", label: "Booking", href: "trans-hotels-booking.html" },
          { key: "trans-hotels-reschedule", label: "Reschedule", href: "trans-hotels-reschedule.html" },
          { key: "trans-hotels-cancellation", label: "Cancellation", href: "trans-hotels-cancellation.html" },
        ]
      },
      {
        key: "trans-bus",
        label: "Bus",
        icon: "M8 7h8m-8 4h8m-9 5h10M5 3h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2z",
        children: [
          { key: "trans-bus-booking", label: "Booking", href: "trans-bus-booking.html" },
          { key: "trans-bus-reschedule", label: "Reschedule", href: "trans-bus-reschedule.html" },
          { key: "trans-bus-cancellation", label: "Cancellation", href: "trans-bus-cancellation.html" },
        ]
      },
      {
        key: "trans-train",
        label: "Train",
        icon: "M12 2a8 8 0 00-8 8v7a3 3 0 003 3h10a3 3 0 003-3v-7a8 8 0 00-8-8zm-4 14a1.5 1.5 0 110-3 1.5 1.5 0 010 3zm8 0a1.5 1.5 0 110-3 1.5 1.5 0 010 3z",
        children: [
          { key: "trans-train-booking", label: "Booking", href: "trans-train-booking.html" },
          { key: "trans-train-reschedule", label: "Reschedule", href: "trans-train-reschedule.html" },
          { key: "trans-train-cancellation", label: "Cancellation", href: "trans-train-cancellation.html" },
        ]
      },
      { key: "trans-visa", label: "Visa", href: "trans-visa.html", icon: "M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" },
      { key: "trans-tour-packages", label: "Tour Packages", href: "trans-tour-packages.html", icon: "M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064M21 12a9 9 0 11-18 0 9 9 0 0118 0z" },
      { key: "trans-insurance", label: "Insurance", href: "trans-insurance.html", icon: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" },
      { key: "trans-vouchers", label: "Vouchers", href: "vouchers.html", icon: "M17 3a2.85 2.85 0 114 4L7.5 20.5 2 22l1.5-5.5z" },
      { key: "trans-misc", label: "Miscellaneous", href: "trans-misc.html", icon: "M4 6h16M4 10h16M4 14h16M4 18h16" },
    ]},
    { label: "Reports", forceDropdown: true, items: [
      {
        key: "rep-dsr",
        label: "DSR",
        href: "report-dsr-airline-booking.html",
        icon: "M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z",
      },
      {
        key: "rep-accounting-book",
        label: "Accounts Book",
        icon: "M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253",
        children: [
          { key: "rep-cash-bank-book", label: "Cash & Bank Book", href: "report-cash-bank-book.html" },
          { key: "rep-day-book", label: "Day Book", href: "report-day-book.html" },
          { key: "rep-ledger-book", label: "Ledger", href: "report-ledger-book.html" },
        ]
      },
      { key: "customers", label: "Receivables (AR)", href: "customers.html", icon: "M17 1l4 4-4 4M3 11V9a4 4 0 014-4h14M7 23l-4-4 4-4M21 13v2a4 4 0 01-4 4H3" },
      { key: "suppliers", label: "Payables (AP)", href: "suppliers.html", icon: "M1 4h22v16H1zM1 10h22" },
      { key: "rep-trial-balance", label: "Trial Balance", href: "report-trial-balance.html", icon: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" },
      { key: "rep-profit-loss", label: "Profit and Loss", href: "report-profit-loss.html", icon: "M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" },
      { key: "rep-balance-sheet", label: "Balance Sheet", href: "report-balance-sheet.html", icon: "M3 6l9-4 9 4M4 10h16M4 14h16M4 18h16" },
      {
        key: "rep-statutory-reports",
        label: "Statutory Reports",
        icon: "M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z",
        children: [
          {
            key: "rep-gst-reports",
            label: "GST Reports",
            children: [
              { key: "rep-gstr-1", label: "GSTR-1", href: "report-gstr-1.html" },
              { key: "rep-gstr-3b", label: "GSTR-3B", href: "report-gstr-3b.html" },
              { key: "rep-gstr-1-recon", label: "GSTR-1 Reconciliation", href: "report-gstr-1-recon.html" },
              { key: "rep-gstr-2b-recon", label: "GSTR-2B Reconciliation", href: "report-gstr-2b-recon.html" },
            ]
          },
          { key: "rep-tds-reports", label: "TDS Reports", href: "report-tds.html" },
        ]
      }
    ]},
    { label: "Control Panel", forceDropdown: true, items: [
      { key: "user-management", label: "User Management", href: "user-management.html", icon: "M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" },
    ]},
  ];

  // Voucher/record status → pill tone. Moved out of util.js
  // (was: local STATUS_MAP inside statusPill()).
  const STATUS_MAP = {
    ISSUED: "success", CONFIRMED: "success", APPROVED: "success", ACTIVE: "success", DEDUCTED: "success",
    SUBMITTED: "warning", PENDING: "warning", RECONCILED: "warning",
    REFUNDED: "danger", VOID: "danger", CANCELLED: "danger", REJECTED: "danger", CLAIMED: "warning",
  };

  // Dashboard hero row (top 3 boarding-pass cards).
  // Moved out of dashboard.js (was: 3 hardcoded heroCard(...) calls).
  // iconKey refers to an entry in ICONS below.
  const DASHBOARD_HERO_CARDS = [
    { label: "Today's Sales", dataPath: "sales.today_sales", iconKey: "calendar" },
    { label: "Month Sales",   dataPath: "sales.month_sales",  iconKey: "plane" },
    { label: "YTD Sales",     dataPath: "sales.ytd_sales",    iconKey: "trend" },
  ];

  // Revenue-by-product-line tiles. Moved out of dashboard.js.
  const DASHBOARD_REVENUE_TILES = [
    { label: "Ticket Revenue",     dataPath: "revenue.ticket_revenue",     ledger: "Ticket Sales Revenue" },
    { label: "Hotel Revenue",      dataPath: "revenue.hotel_revenue",      ledger: "Hotel Sales Revenue" },
    { label: "Visa Revenue",       dataPath: "revenue.visa_revenue",       ledger: "Visa Service Revenue" },
    { label: "Insurance Revenue",  dataPath: "revenue.insurance_revenue",  ledger: "Insurance Revenue" },
    { label: "Service Charges",    dataPath: "revenue.service_charges",    ledger: null },
    { label: "Markup Revenue",     dataPath: "revenue.markup_revenue",     ledger: null },
  ];

  // Finance position tiles. Moved out of dashboard.js.
  const DASHBOARD_FINANCE_TILES = [
    { label: "Cash Position",              dataPath: "finance.cash_position",              ledger: "Cash in Hand" },
    { label: "Bank Position",              dataPath: "finance.bank_position",              ledger: "Bank Account - Main" },
    { label: "Outstanding Receivables",    dataPath: "finance.outstanding_receivables",    ledger: "Trade Receivable" },
    { label: "Outstanding Payables",       dataPath: "finance.outstanding_payables",       ledger: "Trade Payable - Suppliers" },
  ];

  // Shared icon paths (24x24 stroke icons), keyed for reuse across dashboard cards.
  const ICONS = {
    plane:    "M2 16l20-8-8 20-2-8-8-2z",
    calendar: "M3 4h18v16H3zM8 2v4M16 2v4M3 10h18",
    trend:    "M23 6l-9.5 9.5-5-5L1 18",
    logout:   "M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9",
    search:   "M11 11m-7 0a7 7 0 1014 0 7 7 0 10-14 0",
    bell:     "M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9",
  };

  // Loader copy shown per context — used with VoyagerLoader.show(...)
  const LOADER_MESSAGES = {
    dashboard: "Building your dashboard…",
    ledger:    "Fetching ledger entries…",
    voucher:   "Preparing voucher…",
    report:    "Compiling report…",
    default:   "Loading…",
  };

  // Currency / number formatting config (Indian numbering system per spec)
  const NUMBER_FORMAT = {
    locale: "en-IN",
    currency: "INR",
    currencySymbol: "₹",
  };

  // Airline Ticket entry form — dropdown option lists, straight from the
  // "TeSePr Accounting Software" field spec (Airline Ticket sheet, Part 1-3).
  // Kept here (not inline in the HTML) so this is the one place to edit them.
  const TICKET_FORM_OPTIONS = {
    invoiceTypes: ["Tax Invoice", "Others"],
    bookingModes: ["Manual", "Auto Push"],
    // Locked to this until the real API push is connected — see bookingModes above
    // for the full list this will switch back to being a dropdown of, later.
    defaultBookingMode: "Manual",
    bookingTypes: [
      "Travel Desk", "Indesk", "Agent", "Retrieve PNR Accounting",
      "Manual Booking", "Mobile Booking", "Travel Co-Ordinator", "SSR Updation",
    ],
    bookingStatuses: ["Confirmed", "Re-Scheduled"],
    travelTypes: ["Domestic", "International"],
    currencies: ["INR", "AED"],
    custDiscountOn: ["Basic", "Basic + YQ", "Basic + YR", "Basic + YQ + YR", "Gross"],
    custDiscountTypes: ["Percentage", "Flat"],
    paxTypes: ["Adult", "Child", "Infant"],
    paymentModes: ["Top-up", "Payment Gateway"],
    airlineCategories: ["LCC", "FSC", "OSC"],
    fopOptions: ["Own Card", "Client Card", "Cash"],
    cabinOptions: ["Economy", "Premium Economy", "Business Class", "First Class"],
    fareTypeOptions: [
      "Normal Fare", "Corporate Fare", "Retail Fare", "ECoupon Fare", "Special Fare", "SME Fare",
      "Flexi Fare", "Marine Fare", "Defence Fare", "Roundtrip Special Fare",
      "SME Corporate/Corp Connect Fare", "SME Retail Fare", "Labour Fare", "Corporate Flexi",
      "Student Fare", "Double Seat", "Senior Citizen Fare",
    ],
    // Placeholder until a real User Master exists — spec calls for a searchable
    // user dropdown backed by "User Master", not yet a separate module here.
    userNames: ["Ananya Krishnan", "Rahul Mehta", "Fatima Al Suwaidi", "Vikram Iyer"],
  };

  window.VoyagerHardcode = {
    NAV_SECTIONS,
    STATUS_MAP,
    DASHBOARD_HERO_CARDS,
    DASHBOARD_REVENUE_TILES,
    DASHBOARD_FINANCE_TILES,
    ICONS,
    LOADER_MESSAGES,
    NUMBER_FORMAT,
    TICKET_FORM_OPTIONS,
  };
})(window);