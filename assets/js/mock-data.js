/**
 * Voyager ERP — Demo/Mock data layer
 * Provides canned responses shaped exactly like the real API so every
 * screen can be explored with zero backend and zero database connection.
 * Enabled via VoyagerAPI.Store.setMockMode(true) — see the "View demo"
 * button on the login page.
 */
(function (window) {
  const COMPANIES = [
    {
      id: 1, name: "Travel Agency India", legal_name: "Travel Agency India Pvt Ltd",
      country_code: "IN", base_currency: "INR", tax_registration_no: "33AAAAA0000A1Z5",
      bsp_code: "IN-BSP-40231", is_active: true,
      branches: [
        { id: 1, company_id: 1, name: "Chennai Branch", code: "CHE", city: "Chennai", state_or_emirate: "Tamil Nadu", is_active: true },
        { id: 2, company_id: 1, name: "Mumbai Branch", code: "MUM", city: "Mumbai", state_or_emirate: "Maharashtra", is_active: true },
        { id: 3, company_id: 1, name: "Delhi Branch", code: "DEL", city: "Delhi", state_or_emirate: "Delhi", is_active: true },
      ],
    },
    {
      id: 2, name: "Travel Agency UAE", legal_name: "Travel Agency DMCC",
      country_code: "AE", base_currency: "AED", tax_registration_no: "100234567800003",
      bsp_code: "AE-BSP-88120", is_active: true,
      branches: [
        { id: 4, company_id: 2, name: "Dubai Branch", code: "DUB", city: "Dubai", state_or_emirate: "Dubai", is_active: true },
        { id: 5, company_id: 2, name: "Abu Dhabi Branch", code: "ABU", city: "Abu Dhabi", state_or_emirate: "Abu Dhabi", is_active: true },
        { id: 6, company_id: 2, name: "Sharjah Branch", code: "SHJ", city: "Sharjah", state_or_emirate: "Sharjah", is_active: true },
      ],
    },
  ];

  const USER = { id: 1, full_name: "Ananya Krishnan (Super Admin)", email: "admin@travelagency.com", role: "Super Admin", mfa_enabled: false };

  const DASHBOARD = {
    1: {
      sales: { today_sales: 412500, month_sales: 8845000, ytd_sales: 88920000 },
      revenue: { ticket_revenue: 62400000, hotel_revenue: 14200000, visa_revenue: 3100000, insurance_revenue: 980000, service_charges: 3850000, markup_revenue: 4390000 },
      finance: { cash_position: 0, bank_position: 0, credit_exposure: 21400000, bsp_liability: 0, supplier_liability: 8650000, outstanding_receivables: 21400000, outstanding_payables: 8650000 },
      compliance: { gst_payable: 1385000, tds_payable: 214000, vat_payable: 0 },
      monthly_revenue_trend: [
        { label: "Feb", value: 6120000 }, { label: "Mar", value: 6890000 }, { label: "Apr", value: 7240000 },
        { label: "May", value: 7910000 }, { label: "Jun", value: 8320000 }, { label: "Jul", value: 8845000 },
      ],
      profitability_trend: [
        { label: "Feb", value: 918000 }, { label: "Mar", value: 1033500 }, { label: "Apr", value: 1086000 },
        { label: "May", value: 1186500 }, { label: "Jun", value: 1248000 }, { label: "Jul", value: 1326750 },
      ],
      branch_performance: [
        { branch_name: "Chennai Branch", sales: 34200000, profit: 5130000 },
        { branch_name: "Mumbai Branch", sales: 31500000, profit: 4725000 },
        { branch_name: "Delhi Branch", sales: 23220000, profit: 3483000 },
      ],
      product_mix: [
        { product: "Airline Tickets", value: 62400000 }, { product: "Hotels", value: 14200000 },
        { product: "Visa", value: 3100000 }, { product: "Insurance", value: 980000 },
      ],
    },
    2: {
      sales: { today_sales: 38500, month_sales: 742000, ytd_sales: 7480000 },
      revenue: { ticket_revenue: 5120000, hotel_revenue: 1640000, visa_revenue: 420000, insurance_revenue: 165000, service_charges: 298000, markup_revenue: 356000 },
      finance: { cash_position: 0, bank_position: 0, credit_exposure: 1620000, bsp_liability: 0, supplier_liability: 640000, outstanding_receivables: 1620000, outstanding_payables: 640000 },
      compliance: { gst_payable: 0, tds_payable: 0, vat_payable: 96500 },
      monthly_revenue_trend: [
        { label: "Feb", value: 520000 }, { label: "Mar", value: 578000 }, { label: "Apr", value: 612000 },
        { label: "May", value: 665000 }, { label: "Jun", value: 703000 }, { label: "Jul", value: 742000 },
      ],
      profitability_trend: [
        { label: "Feb", value: 78000 }, { label: "Mar", value: 86700 }, { label: "Apr", value: 91800 },
        { label: "May", value: 99750 }, { label: "Jun", value: 105450 }, { label: "Jul", value: 111300 },
      ],
      branch_performance: [
        { branch_name: "Dubai Branch", sales: 3740000, profit: 561000 },
        { branch_name: "Abu Dhabi Branch", sales: 2244000, profit: 336600 },
        { branch_name: "Sharjah Branch", sales: 1496000, profit: 224400 },
      ],
      product_mix: [
        { product: "Airline Tickets", value: 5120000 }, { product: "Hotels", value: 1640000 },
        { product: "Visa", value: 420000 }, { product: "Insurance", value: 165000 },
      ],
    },
  };

  const AIRLINES = ["Emirates", "Air India", "IndiGo", "Qatar Airways", "Etihad Airways", "flydubai", "Vistara"];
  const SECTORS = ["MAA-DXB-MAA", "BOM-DXB-BOM", "DEL-AUH-DEL", "DXB-LHR-DXB", "MAA-SIN-MAA", "DEL-DXB-DEL"];
  const PASSENGERS = ["Rahul Mehta", "Fatima Al Suwaidi", "Vikram Iyer", "Sneha Nair", "Omar Al Hashimi", "Priya Sundaram", "Arjun Reddy", "Layla Khan"];
  const STATUSES_TICKET = ["ISSUED", "ISSUED", "ISSUED", "ISSUED", "REFUNDED", "VOID"];

  function seededRows(companyId, count, gen) {
    return Array.from({ length: count }, (_, i) => gen(i, companyId));
  }

  function isoDaysAgo(n) {
    const d = new Date(); d.setDate(d.getDate() - n);
    return d.toISOString().slice(0, 10);
  }

  const TICKETS = {};
  const HOTELS = {};
  const VISA = {};
  const INSURANCE = {};
  const TOURS = {};
  [1, 2].forEach((cid) => {
    TICKETS[cid] = seededRows(cid, 14, (i) => {
      const basic = 4000 + i * 2300;
      const tax = Math.round(basic * 0.12);
      const markup = Math.round(basic * 0.05);
      const fee = 500 + i * 30;
      const base = {
        id: i + 1, pnr: `X${(1000 + i * 37).toString(36).toUpperCase()}`, ticket_no: `${cid === 1 ? "6E" : "EK"}${900000000 + i * 1234}`,
        airline_name: AIRLINES[i % AIRLINES.length], passenger_name: PASSENGERS[i % PASSENGERS.length],
        sector: SECTORS[i % SECTORS.length], issue_date: isoDaysAgo(i * 4), travel_date: isoDaysAgo(i * 4 - 14),
        basic_fare: basic, tax, commission: Math.round(basic * 0.03), markup, service_fee: fee,
        total_billed: basic + tax + markup + fee, status: STATUSES_TICKET[i % STATUSES_TICKET.length],
        customer_name: `${cid === 1 ? "Sundaram Exports" : "Al Maha Trading"} ${i + 1}`, branch_name: cid === 1 ? "Chennai Branch" : "Dubai Branch",
      };
      // One fully-filled-in demo record per company, covering every field from
      // the new Airline Ticket entry form (invoice header, booking reference,
      // fare breakup detail). Every OTHER seeded ticket keeps only the fields
      // above — the details view shows those extra fields as "—" for them,
      // since they were created before this fuller form existed.
      if (i === 0) {
        return {
          ...base,
          invoice_number: `INV-${cid === 1 ? "IN" : "AE"}-00001`,
          invoice_date: base.issue_date,
          invoice_type: "Tax Invoice",
          booking_mode: "Manual",
          booking_type: "Travel Desk",
          booking_status: "Confirmed",
          travel_type: cid === 1 ? "Domestic" : "International",
          user_name: "Ananya Krishnan",
          currency: cid === 1 ? "INR" : "AED",
          roe: cid === 1 ? 1 : 1,
          booking_given_by: "Front Office",
          booking_reference: `BREF-${cid === 1 ? "IN" : "AE"}-00001`,
          booking_ref_date: base.issue_date,
          airline_pnr: base.pnr,
          gds_pnr: `GDS${base.pnr}`,
          supplier_name: `${cid === 1 ? "IATA Consolidator" : "Gulf Air Consolidator"} 1`,
          office_id: "OFF-001",
          pax_type: "Adult",
          yq: 120, yr: 60, k3_tax: 40, tax_others: 30, seat: 25, meal: 15, baggage: 50, other_ssr: 10,
          disc_on: "Basic", disc_type: "Percentage", disc_value: 2,
          tds_per: 1, addl_markup: 0, addl_service_fee: 0, gst_pct: cid === 1 ? 5 : 0,
        };
      }
      return base;
    });
    HOTELS[cid] = seededRows(cid, 10, (i) => {
      const cost = 3500 + i * 1450;
      const billing = Math.round(cost * 1.28);
      return {
        id: i + 1, hotel_name: `${cid === 1 ? "Taj" : "Address"} ${["Coromandel", "Downtown", "Marina", "Palace", "Residency"][i % 5]}`,
        guest_name: PASSENGERS[(i + 2) % PASSENGERS.length], customer_name: `${cid === 1 ? "Sundaram Exports" : "Al Maha Trading"} ${i + 1}`,
        supplier_name: `${cid === 1 ? "Hotel Corp" : "Gulf Hospitality"} ${i + 1}`, check_in: isoDaysAgo(i * 6), check_out: isoDaysAgo(i * 6 - 3),
        nights: 3, rooms: 1 + (i % 3), supplier_cost: cost, customer_billing: billing, status: i % 8 === 0 ? "CANCELLED" : "CONFIRMED",
        branch_name: cid === 1 ? "Mumbai Branch" : "Abu Dhabi Branch",
      };
    });
    VISA[cid] = seededRows(cid, 8, (i) => {
      const sf = 2500 + i * 700;
      const cf = Math.round(sf * 1.2);
      return {
        id: i + 1, applicant_name: PASSENGERS[(i + 4) % PASSENGERS.length], customer_name: `${cid === 1 ? "Sundaram Exports" : "Al Maha Trading"} ${i + 1}`,
        destination_country: ["UAE", "UK", "Schengen", "USA", "India"][i % 5], visa_type: ["Tourist", "Business", "Transit"][i % 3],
        application_date: isoDaysAgo(i * 5), supplier_fee: sf, customer_fee: cf, service_charge: cf - sf,
        status: ["APPROVED", "APPROVED", "SUBMITTED", "REJECTED"][i % 4],
      };
    });
    INSURANCE[cid] = seededRows(cid, 7, (i) => {
      const cost = 800 + i * 210;
      return {
        id: i + 1, policy_no: `POL-${cid}${100000 + i * 17}`, insured_name: PASSENGERS[(i + 1) % PASSENGERS.length],
        customer_name: `${cid === 1 ? "Sundaram Exports" : "Al Maha Trading"} ${i + 1}`, supplier_name: `${cid === 1 ? "ICICI Lombard" : "Oman Insurance"} `,
        policy_start: isoDaysAgo(i * 20), policy_end: isoDaysAgo(i * 20 - 365), premium_cost: cost, premium_billed: Math.round(cost * 1.25),
        status: ["ACTIVE", "ACTIVE", "ACTIVE", "CANCELLED"][i % 4],
      };
    });
    TOURS[cid] = seededRows(cid, 6, (i) => {
      const scale = cid === 2 ? 0.08 : 1;
      const cost = Math.round((120000 + i * 34000) * scale);
      const revenue = Math.round(cost * 1.22);
      return {
        id: i + 1, package_name: `${["Kerala Backwaters", "Golden Triangle", "Himalayan Trek", "Dubai Desert Safari", "Abu Dhabi City Break", "Sharjah Heritage Tour"][i % 6]}`,
        customer_name: `${cid === 1 ? "Sundaram Exports" : "Al Maha Trading"} ${i + 1}`,
        package_type: i % 2 === 0 ? "GIT" : "FIT", pax_count: i % 2 === 0 ? 12 + i : 2 + (i % 3),
        start_date: isoDaysAgo(-10 - i * 7), end_date: isoDaysAgo(-16 - i * 7),
        total_cost: cost, total_revenue: revenue, status: ["CONFIRMED", "CONFIRMED", "CONFIRMED", "CANCELLED"][i % 4],
      };
    });
  });

  const COA_DEFS = [
    // --- Top-level nature groups ---
    ["1000", "Assets", "ASSET", true, null, 0],
    ["2000", "Liabilities", "LIABILITY", true, null, 0],
    ["4000", "Income", "INCOME", true, null, 0],
    ["5000", "Expenses", "EXPENSE", true, null, 0],

    // --- Primary groups under Liabilities ---
    ["2100", "Capital Account", "LIABILITY", true, "2000", 0],
    ["2200", "Loans (Liability)", "LIABILITY", true, "2000", 0],
    ["2300", "Current Liabilities", "LIABILITY", true, "2000", 0],

    // --- Primary groups under Assets ---
    ["1100", "Fixed Assets", "ASSET", true, "1000", 0],
    ["1200", "Investments", "ASSET", true, "1000", 0],
    ["1300", "Current Assets", "ASSET", true, "1000", 0],

    // --- Primary groups under Income ---
    ["4100", "Sales Accounts", "INCOME", true, "4000", 0],
    ["4200", "Direct Income", "INCOME", true, "4000", 0],
    ["4300", "Indirect Income", "INCOME", true, "4000", 0],

    // --- Primary groups under Expenses ---
    ["5100", "Purchase Accounts", "EXPENSE", true, "5000", 0],
    ["5200", "Direct Expenses", "EXPENSE", true, "5000", 0],
    ["5300", "Indirect Expenses", "EXPENSE", true, "5000", 0],

    // --- Sub-groups under Loans (Liability) ---
    ["2210", "Secured Loans", "LIABILITY", true, "2200", 0],
    ["2220", "Unsecured Loans", "LIABILITY", true, "2200", 0],

    // --- Sub-groups under Current Liabilities ---
    ["2310", "Sundry Creditors", "LIABILITY", true, "2300", 0],
    ["2320", "Duties & Taxes", "LIABILITY", true, "2300", 0],
    ["2330", "Provisions", "LIABILITY", true, "2300", 0],

    // --- Sub-groups under Current Assets ---
    ["1310", "Sundry Debtors", "ASSET", true, "1300", 0],
    ["1320", "Bank Accounts", "ASSET", true, "1300", 0],
    ["1330", "Cash-in-hand", "ASSET", true, "1300", 0],
    ["1340", "Deposits (Asset)", "ASSET", true, "1300", 0],
    ["1350", "Stock-in-hand", "ASSET", true, "1300", 0],
    ["1360", "Tax Assets", "ASSET", true, "1300", 0],

    // --- Leaf ledgers ---
    ["1331", "Cash in Hand", "ASSET", false, "1330", 185000],
    ["1321", "Bank Account - Main", "ASSET", false, "1320", 4230000],
    ["1311", "Trade Receivable", "ASSET", false, "1310", 21400000],
    ["2311", "Trade Payable - Suppliers", "LIABILITY", false, "2310", -8650000],
    ["2312", "BSP Payable", "LIABILITY", false, "2310", -1120000],
    ["2321", "GST Payable", "LIABILITY", false, "2320", -1385000],
    ["2322", "VAT Payable", "LIABILITY", false, "2320", 0],
    ["2323", "TDS Payable", "LIABILITY", false, "2320", -214000],
    ["2101", "Owner's Capital", "LIABILITY", false, "2100", -5000000],
    ["2102", "Opening Balance Equity", "LIABILITY", false, "2100", 0],
    ["4101", "Ticket Sales Revenue", "INCOME", false, "4100", -62400000],
    ["4102", "Hotel Sales Revenue", "INCOME", false, "4100", -14200000],
    ["4103", "Visa Service Revenue", "INCOME", false, "4100", -3100000],
    ["4104", "Insurance Revenue", "INCOME", false, "4100", -980000],
    ["4301", "Commission Income", "INCOME", false, "4300", -1870000],
    ["5201", "Hotel Supplier Cost", "EXPENSE", false, "5200", 11090000],
    ["5301", "Staff Salaries", "EXPENSE", false, "5300", 3840000],
    ["5302", "Office Rent", "EXPENSE", false, "5300", 1260000],
  ];

  // Maps a Group name to the ledger-entry-form behavior it should trigger.
  // This is what lets the Ledger Master infer "this is a customer/supplier/
  // bank/income/expense ledger" purely from the Group selected — no separate
  // category dropdown needed.
  const GROUP_BEHAVIOR = {
    "Sundry Debtors": "DEBTOR",
    "Bank Accounts": "BANK",
    "Sundry Creditors": "CREDITOR",
    "Sales Accounts": "INCOME",
    "Direct Income": "INCOME",
    "Indirect Income": "INCOME",
    "Purchase Accounts": "EXPENSE",
    "Direct Expenses": "EXPENSE",
    "Indirect Expenses": "EXPENSE",
    "Duties & Taxes": "DUTIES_TAXES",
  };

  function buildAccounts(scale) {
    const idFor = {};
    COA_DEFS.forEach((d, i) => (idFor[d[0]] = i + 1));
    return COA_DEFS.map((d, i) => ({
      id: i + 1, code: d[0], name: d[1], account_type: d[2], is_group: d[3],
      parent_id: d[4] ? idFor[d[4]] : null, balance: Math.round(d[5] * scale), is_master: d[3],
    }));
  }
  const ACCOUNTS = { 1: buildAccounts(1), 2: buildAccounts(0.084) };

  const VOUCHER_TYPES = ["SALES_INVOICE", "PAYMENT", "RECEIPT", "JOURNAL", "CREDIT_NOTE"];
  function buildVouchers(companyId) {
    const scale = companyId === 2 ? 0.08 : 1;
    const s = (n) => Math.round(n * scale);
    const branch = companyId === 1 ? "Chennai Branch" : "Dubai Branch";
    const taxLedger = companyId === 1 ? "GST Payable" : "VAT Payable";

    const templates = [
      { type: "SALES_INVOICE", narration: "Airline ticket sales invoice", lines: [
        { a: "Trade Receivable", d: s(112000), c: 0 }, { a: "Ticket Sales Revenue", d: 0, c: s(106000) }, { a: taxLedger, d: 0, c: s(6000) } ] },
      { type: "SALES_INVOICE", narration: "Hotel booking sales invoice", lines: [
        { a: "Trade Receivable", d: s(58000), c: 0 }, { a: "Hotel Sales Revenue", d: 0, c: s(55000) }, { a: taxLedger, d: 0, c: s(3000) } ] },
      { type: "SALES_INVOICE", narration: "Visa service invoice", lines: [
        { a: "Trade Receivable", d: s(14000), c: 0 }, { a: "Visa Service Revenue", d: 0, c: s(14000) } ] },
      { type: "SALES_INVOICE", narration: "Travel insurance premium invoice", lines: [
        { a: "Trade Receivable", d: s(4200), c: 0 }, { a: "Insurance Revenue", d: 0, c: s(4200) } ] },
      { type: "RECEIPT", narration: "Customer payment received via bank transfer", lines: [
        { a: "Bank Account - Main", d: s(85000), c: 0 }, { a: "Trade Receivable", d: 0, c: s(85000) } ] },
      { type: "RECEIPT", narration: "Customer payment received in cash", lines: [
        { a: "Cash in Hand", d: s(18500), c: 0 }, { a: "Trade Receivable", d: 0, c: s(18500) } ] },
      { type: "PAYMENT", narration: "Supplier settlement — hotel cost", lines: [
        { a: "Trade Payable - Suppliers", d: s(42000), c: 0 }, { a: "Bank Account - Main", d: 0, c: s(42000) } ] },
      { type: "PAYMENT", narration: "BSP fortnightly settlement", lines: [
        { a: "BSP Payable", d: s(95000), c: 0 }, { a: "Bank Account - Main", d: 0, c: s(95000) } ] },
      { type: "CONTRA", narration: "Cash withdrawn from bank for petty expenses", lines: [
        { a: "Cash in Hand", d: s(5000), c: 0 }, { a: "Bank Account - Main", d: 0, c: s(5000) } ] },
      { type: "JOURNAL", narration: "Hotel supplier cost accrued", lines: [
        { a: "Hotel Supplier Cost", d: s(31000), c: 0 }, { a: "Trade Payable - Suppliers", d: 0, c: s(31000) } ] },
      { type: "JOURNAL", narration: "Office rent for the month", lines: [
        { a: "Office Rent", d: s(22000), c: 0 }, { a: "Bank Account - Main", d: 0, c: s(20900) },
        ...(companyId === 1 ? [{ a: "TDS Payable", d: 0, c: s(1100) }] : []) ] },
      { type: "JOURNAL", narration: "Staff salaries for the month", lines: [
        { a: "Staff Salaries", d: s(48000), c: 0 }, { a: "Bank Account - Main", d: 0, c: s(48000) } ] },
      { type: "CREDIT_NOTE", narration: "Ticket cancellation refund adjustment", lines: [
        { a: "Ticket Sales Revenue", d: s(9500), c: 0 }, { a: "Trade Receivable", d: 0, c: s(9500) } ] },
    ];

    return templates.map((t, i) => {
      const totalDebit = t.lines.reduce((sum, l) => sum + l.d, 0);
      return {
        id: i + 1, voucher_no: `${t.type.slice(0, 3)}-202607-${1000 + i}`, voucher_type: t.type,
        voucher_date: isoDaysAgo(i * 3), narration: t.narration, branch_name: branch,
        total_debit: totalDebit, total_credit: totalDebit, is_posted: true,
        lines: t.lines.map((l) => ({ account_name: l.a, debit: l.d, credit: l.c, narration: null })),
      };
    });
  }
  const VOUCHERS = { 1: buildVouchers(1), 2: buildVouchers(2) };

  function buildCustomers(companyId) {
    const scale = companyId === 2 ? 0.08 : 1;
    return Array.from({ length: 10 }, (_, i) => ({
      id: i + 1, code: `CUST-${companyId === 1 ? "IN" : "AE"}-${(1000 + i).toString().padStart(4, "0")}`,
      name: `${companyId === 1 ? "Sundaram Exports" : "Al Maha Trading"} ${i + 1}`,
      customer_type: ["RETAIL", "CORPORATE", "AGENT"][i % 3], email: `customer${i + 1}@example.com`, phone: "+91 98765 4321" + i,
      credit_limit: Math.round([0, 50000, 100000, 250000][i % 4] * scale), credit_days: [0, 15, 30, 45][i % 4],
      outstanding: Math.round((320000 - i * 22000) * scale),
      gst_no: companyId === 1 ? `33AAAAA${(1000 + i)}A1Z${i % 9}` : `TRN10034567${i}00003`,
      address: companyId === 1 ? `${12 + i}, Anna Salai, Chennai 600002, Tamil Nadu` : `Office ${100 + i}, Sheikh Zayed Road, Dubai, UAE`,
    }));
  }
  const CUSTOMERS = { 1: buildCustomers(1), 2: buildCustomers(2) };

  function buildSuppliers(companyId) {
    const scale = companyId === 2 ? 0.08 : 1;
    return Array.from({ length: 8 }, (_, i) => ({
      id: i + 1, code: `SUPP-${companyId === 1 ? "IN" : "AE"}-${(1000 + i).toString().padStart(4, "0")}`,
      name: `${companyId === 1 ? "Hotel Corp" : "Gulf Hospitality"} ${i + 1}`,
      supplier_type: ["HOTEL", "VISA", "INSURANCE", "DMC"][i % 4], email: `supplier${i + 1}@example.com`, phone: "+91 87654 3210" + i,
      credit_days: [7, 15, 30][i % 3], outstanding: Math.round((210000 - i * 15000) * scale),
    }));
  }
  const SUPPLIERS = { 1: buildSuppliers(1), 2: buildSuppliers(2) };

  const GST_SUMMARY = [
    { hsn_sac_code: "9985", taxable_value: 8390000, cgst: 209750, sgst: 209750, igst: 0 },
    { hsn_sac_code: "9964", taxable_value: 2140000, cgst: 53500, sgst: 53500, igst: 0 },
  ];
  const VAT_SUMMARY = [
    { vat_code: "STANDARD_5", taxable_value: 1930000, vat_amount: 96500 },
  ];

  function trialBalanceFrom(accounts) {
    return accounts.filter((a) => !a.is_group).map((a) => ({
      code: a.code, name: a.name, account_type: a.account_type,
      debit: a.balance > 0 ? a.balance : 0, credit: a.balance < 0 ? -a.balance : 0,
    }));
  }

  const HOTEL_MASTER = {
    1: ["Taj Coromandel", "ITC Grand Chola", "The Leela Palace", "Oberoi Mumbai", "Trident Nariman Point"],
    2: ["Address Downtown", "Atlantis The Palm", "Jumeirah Beach Hotel", "Emirates Palace", "Address Marina"],
  };

  function nextId(arr) { return (arr.reduce((m, r) => Math.max(m, r.id), 0) || 0) + 1; }

  function getReferenceData(companyId) {
    const company = COMPANIES.find((c) => c.id === companyId);
    return {
      branches: company ? company.branches : [],
      customers: CUSTOMERS[companyId] || [],
      suppliers: SUPPLIERS[companyId] || [],
      airlines: AIRLINES,
      hotels: HOTEL_MASTER[companyId] || [],
      accounts: (ACCOUNTS[companyId] || []).filter((a) => !a.is_group),
      currency: companyId === 2 ? "AED" : "INR",
    };
  }

  function addTicket(cid, data) {
    const row = { id: nextId(TICKETS[cid]), ...data };
    TICKETS[cid].unshift(row);
    return row;
  }
  function addHotel(cid, data) {
    const row = { id: nextId(HOTELS[cid]), ...data };
    HOTELS[cid].unshift(row);
    return row;
  }
  function addVisa(cid, data) {
    const row = { id: nextId(VISA[cid]), ...data };
    VISA[cid].unshift(row);
    return row;
  }
  function addInsurance(cid, data) {
    const row = { id: nextId(INSURANCE[cid]), ...data };
    INSURANCE[cid].unshift(row);
    return row;
  }
  function addTour(cid, data) {
    const row = { id: nextId(TOURS[cid]), ...data };
    TOURS[cid].unshift(row);
    return row;
  }
  function addVoucher(cid, data) {
    const row = { id: nextId(VOUCHERS[cid]), ...data };
    VOUCHERS[cid].unshift(row);
    return row;
  }

  // --- Generic record update/get, reused by every transaction-type-specific wrapper below ---
  function _getRecord(arr, id) { return arr.find((r) => r.id === id); }
  function _updateRecord(arr, id, data) {
    const idx = arr.findIndex((r) => r.id === id);
    if (idx === -1) return { error: "Record not found" };
    arr[idx] = { ...arr[idx], ...data, id };
    return { record: arr[idx] };
  }

  function getTicket(cid, id) { return _getRecord(TICKETS[cid], id); }
  function updateTicket(cid, id, data) { return _updateRecord(TICKETS[cid], id, data); }
  function getHotel(cid, id) { return _getRecord(HOTELS[cid], id); }
  function updateHotel(cid, id, data) { return _updateRecord(HOTELS[cid], id, data); }
  function getVisaRecord(cid, id) { return _getRecord(VISA[cid], id); }
  function updateVisa(cid, id, data) { return _updateRecord(VISA[cid], id, data); }
  function getInsuranceRecord(cid, id) { return _getRecord(INSURANCE[cid], id); }
  function updateInsurance(cid, id, data) { return _updateRecord(INSURANCE[cid], id, data); }
  function getTour(cid, id) { return _getRecord(TOURS[cid], id); }
  function updateTour(cid, id, data) { return _updateRecord(TOURS[cid], id, data); }
  function getVoucher(cid, id) { return _getRecord(VOUCHERS[cid], id); }
  function updateVoucher2(cid, id, data) { return _updateRecord(VOUCHERS[cid], id, data); }

  // Transactions for a given customer/supplier — powers the Receivables/Payables zoom-in.
  function getTicketsForCustomer(cid, customerName) { return TICKETS[cid].filter((t) => t.customer_name === customerName); }
  function getHotelsForCustomer(cid, customerName) { return HOTELS[cid].filter((h) => h.customer_name === customerName); }
  function getHotelsForSupplier(cid, supplierName) { return HOTELS[cid].filter((h) => h.supplier_name === supplierName); }

  function computeLedgerBalance(cid, name) {
    let net = 0;
    VOUCHERS[cid].forEach((v) => v.lines.forEach((l) => {
      if (l.account_name === name) net += (l.debit || 0) - (l.credit || 0);
    }));
    return Math.round(net * 100) / 100;
  }

  function addAccount(cid, data) {
    const accounts = ACCOUNTS[cid];
    const parent = accounts.find((a) => a.id === data.parent_id);
    const code = parent ? `${parent.code}-${accounts.filter((a) => a.parent_id === parent.id).length + 1}` : "9999";
    const row = {
      id: nextId(accounts), code, name: data.name, account_type: parent ? parent.account_type : "ASSET",
      is_group: false, is_master: false, parent_id: data.parent_id, balance: 0,
      ledger_category: data.ledger_category, ...data,
    };
    accounts.push(row);

    if (data.opening_balance) {
      const equity = accounts.find((a) => a.name === "Opening Balance Equity") ||
        (() => {
          const capitalGroup = accounts.find((a) => a.name === "Capital Account" && a.is_group);
          const eq = { id: nextId(accounts), code: "2102", name: "Opening Balance Equity", account_type: "LIABILITY", is_group: false, parent_id: capitalGroup ? capitalGroup.id : null, balance: 0 };
          accounts.push(eq);
          return eq;
        })();
      const isDebit = data.opening_balance_type === "Debit";
      VOUCHERS[cid].unshift({
        id: nextId(VOUCHERS[cid]), voucher_no: `OB-${code}`, voucher_type: "JOURNAL", voucher_date: isoDaysAgo(0),
        narration: `Opening balance for ${data.name}`, branch_name: getReferenceData(cid).branches[0]?.name || "",
        total_debit: data.opening_balance, total_credit: data.opening_balance, is_posted: true,
        lines: [
          { account_name: data.name, debit: isDebit ? data.opening_balance : 0, credit: isDebit ? 0 : data.opening_balance },
          { account_name: "Opening Balance Equity", debit: isDebit ? 0 : data.opening_balance, credit: isDebit ? data.opening_balance : 0 },
        ],
      });
      equity.balance = computeLedgerBalance(cid, "Opening Balance Equity");
    }
    row.balance = computeLedgerBalance(cid, row.name);
    return row;
  }

  function updateLedger(cid, { id, name, parent_id, opening_balance, opening_balance_type, ...rest }) {
    const accounts = ACCOUNTS[cid];
    const account = accounts.find((a) => a.id === id && !a.is_group);
    if (!account) return { error: "Ledger not found" };
    const newParent = accounts.find((a) => a.id === parent_id && a.is_group);
    if (!newParent) return { error: "Parent group not found" };

    const oldName = account.name;
    const oldCode = account.code;

    // Rename cascades into every voucher line that referenced this ledger, so
    // historical entries and the Trial Balance keep matching by name.
    if (oldName !== name) {
      VOUCHERS[cid].forEach((v) => v.lines.forEach((l) => { if (l.account_name === oldName) l.account_name = name; }));
    }

    account.name = name;
    account.parent_id = newParent.id;
    account.account_type = newParent.account_type;
    account.ledger_category = GROUP_BEHAVIOR[newParent.name] || rest.ledger_category || "OTHER";
    Object.assign(account, rest);

    // Replace the ledger's own opening-balance voucher with a fresh one reflecting the new amount.
    const obIdx = VOUCHERS[cid].findIndex((v) => v.voucher_no === `OB-${oldCode}`);
    if (obIdx !== -1) VOUCHERS[cid].splice(obIdx, 1);
    if (opening_balance) {
      const equity = accounts.find((a) => a.name === "Opening Balance Equity");
      const isDebit = opening_balance_type === "Debit";
      VOUCHERS[cid].unshift({
        id: nextId(VOUCHERS[cid]), voucher_no: `OB-${account.code}`, voucher_type: "JOURNAL", voucher_date: isoDaysAgo(0),
        narration: `Opening balance for ${account.name}`, branch_name: getReferenceData(cid).branches[0]?.name || "",
        total_debit: opening_balance, total_credit: opening_balance, is_posted: true,
        lines: [
          { account_name: account.name, debit: isDebit ? opening_balance : 0, credit: isDebit ? 0 : opening_balance },
          { account_name: "Opening Balance Equity", debit: isDebit ? 0 : opening_balance, credit: isDebit ? opening_balance : 0 },
        ],
      });
      if (equity) equity.balance = computeLedgerBalance(cid, "Opening Balance Equity");
    }
    account.balance = computeLedgerBalance(cid, account.name);
    return { account };
  }

  function deleteLedger(cid, id) {
    const accounts = ACCOUNTS[cid];
    const account = accounts.find((a) => a.id === id && !a.is_group);
    if (!account) return { error: "Ledger not found" };

    const obVoucherNo = `OB-${account.code}`;
    const realTxnCount = VOUCHERS[cid].reduce((count, v) => {
      const touches = v.lines.some((l) => l.account_name === account.name);
      if (!touches) return count;
      return v.voucher_no === obVoucherNo ? count : count + 1;
    }, 0);
    if (realTxnCount > 0) return { error: `Cannot delete: ${realTxnCount} transaction(s) exist for this ledger` };

    const obIdx = VOUCHERS[cid].findIndex((v) => v.voucher_no === obVoucherNo);
    if (obIdx !== -1) VOUCHERS[cid].splice(obIdx, 1);

    const idx = accounts.findIndex((a) => a.id === id);
    if (idx !== -1) accounts.splice(idx, 1);
    const equity = accounts.find((a) => a.name === "Opening Balance Equity");
    if (equity) equity.balance = computeLedgerBalance(cid, "Opening Balance Equity");
    return { message: "Ledger deleted" };
  }

  function getAccountGroups(cid) {
    return (ACCOUNTS[cid] || []).filter((a) => a.is_group);
  }

  function isDescendant(accounts, candidateId, ofId) {
    let node = accounts.find((a) => a.id === candidateId);
    while (node && node.parent_id) {
      if (node.parent_id === ofId) return true;
      node = accounts.find((a) => a.id === node.parent_id);
    }
    return false;
  }

  function addGroup(cid, { name, parent_id }) {
    const accounts = ACCOUNTS[cid];
    const parent = accounts.find((a) => a.id === parent_id && a.is_group);
    if (!parent) return { error: "Parent group not found" };
    const siblingCount = accounts.filter((a) => a.parent_id === parent.id).length;
    const group = {
      id: nextId(accounts), code: `${parent.code}-G${siblingCount + 1}`, name,
      account_type: parent.account_type, is_group: true, is_master: false, parent_id: parent.id, balance: 0,
    };
    accounts.push(group);
    return { group };
  }

  function updateGroup(cid, { id, name, parent_id }) {
    const accounts = ACCOUNTS[cid];
    const group = accounts.find((a) => a.id === id && a.is_group);
    if (!group) return { error: "Group not found" };
    if (group.is_master) return { error: "This is one of the 23 master groups and cannot be modified" };
    const newParent = accounts.find((a) => a.id === parent_id && a.is_group);
    if (!newParent) return { error: "Parent group not found" };
    if (newParent.id === group.id || isDescendant(accounts, newParent.id, group.id)) {
      return { error: "Cannot move a group under itself or one of its own descendants" };
    }
    group.name = name;
    const reparented = group.parent_id !== newParent.id;
    group.parent_id = newParent.id;
    if (reparented && group.account_type !== newParent.account_type) {
      const stack = [group.id];
      while (stack.length) {
        const currentId = stack.pop();
        accounts.filter((a) => a.parent_id === currentId).forEach((child) => {
          child.account_type = newParent.account_type;
          stack.push(child.id);
        });
      }
      group.account_type = newParent.account_type;
    }
    return { group };
  }

  function deleteGroup(cid, id) {
    const accounts = ACCOUNTS[cid];
    const group = accounts.find((a) => a.id === id && a.is_group);
    if (!group) return { error: "Group not found" };
    if (group.is_master) return { error: "This is one of the 23 master groups and cannot be deleted" };

    const subtreeIds = [group.id];
    let frontier = [group.id];
    while (frontier.length) {
      const children = accounts.filter((a) => frontier.includes(a.parent_id)).map((a) => a.id);
      frontier = children;
      subtreeIds.push(...children);
    }
    const ledgerCount = accounts.filter((a) => subtreeIds.includes(a.id) && !a.is_group).length;
    if (ledgerCount > 0) return { error: `Cannot delete: ${ledgerCount} ledger(s) exist under this group` };

    subtreeIds.forEach((delId) => {
      const idx = accounts.findIndex((a) => a.id === delId);
      if (idx !== -1) accounts.splice(idx, 1);
    });
    return { deleted_count: subtreeIds.length };
  }

  function getVouchersForAccount(cid, accountName) {
    return (VOUCHERS[cid] || [])
      .filter((v) => v.lines.some((l) => l.account_name === accountName))
      .sort((a, b) => (a.voucher_date < b.voucher_date ? 1 : -1));
  }

  function getVouchersForBranch(cid, branchName) {
    return (VOUCHERS[cid] || [])
      .filter((v) => v.branch_name === branchName)
      .sort((a, b) => (a.voucher_date < b.voucher_date ? 1 : -1));
  }

  function qp(path, key) {
    const m = path.match(new RegExp(`[?&]${key}=([^&]+)`));
    return m ? decodeURIComponent(m[1]) : null;
  }

  async function handle(path, { method = "GET", body } = {}) {
    if (path.startsWith("/auth/login")) {
      return { requires_otp: false, access_token: "demo-token", refresh_token: "demo-refresh", user: USER };
    }
    if (path.startsWith("/auth/me")) return USER;
    if (path.startsWith("/auth/logout")) return { message: "Logged out" };

    if (path.startsWith("/companies")) return COMPANIES;

    const cid = Number(qp(path, "company_id")) || 1;

    if (path.startsWith("/dashboard")) return DASHBOARD[cid] || DASHBOARD[1];
    const singleMatch = path.match(/^\/travel\/(tickets|hotels|visa|insurance|tours)\/(\d+)/);
    if (singleMatch) {
      const [, kind, recId] = singleMatch;
      const getters = { tickets: getTicket, hotels: getHotel, visa: getVisaRecord, insurance: getInsuranceRecord, tours: getTour };
      const updaters = { tickets: updateTicket, hotels: updateHotel, visa: updateVisa, insurance: updateInsurance, tours: updateTour };
      if (method === "GET") {
        const rec = getters[kind](cid, Number(recId));
        return rec ? rec : Promise.reject(new Error("Record not found"));
      }
      if (method === "PUT") {
        const result = updaters[kind](cid, Number(recId), body);
        return result.error ? Promise.reject(new Error(result.error)) : result.record;
      }
    }
    if (path.startsWith("/travel/tickets")) return TICKETS[cid] || [];
    if (path.startsWith("/travel/hotels")) return HOTELS[cid] || [];
    if (path.startsWith("/travel/visa")) return VISA[cid] || [];
    if (path.startsWith("/travel/insurance")) return INSURANCE[cid] || [];
    if (path.startsWith("/travel/tours")) return TOURS[cid] || [];
    if (path.startsWith("/accounting/ledgers/")) {
      const idMatch = path.match(/\/accounting\/ledgers\/(\d+)/);
      if (method === "GET" && idMatch) {
        const account = (ACCOUNTS[cid] || []).find((a) => a.id === Number(idMatch[1]) && !a.is_group);
        return account ? account : Promise.reject(new Error("Ledger not found"));
      }
      if (method === "PUT" && idMatch) {
        const result = updateLedger(cid, { id: Number(idMatch[1]), ...body });
        return result.error ? Promise.reject(new Error(result.error)) : result.account;
      }
      if (method === "DELETE" && idMatch) {
        const result = deleteLedger(cid, Number(idMatch[1]));
        return result.error ? Promise.reject(new Error(result.error)) : result;
      }
    }
    if (path.startsWith("/accounting/accounts/groups")) {
      const idMatch = path.match(/\/accounting\/accounts\/groups\/(\d+)/);
      if (method === "POST") {
        const result = addGroup(cid, body);
        return result.error ? Promise.reject(new Error(result.error)) : result.group;
      }
      if (method === "PUT" && idMatch) {
        const result = updateGroup(cid, { id: Number(idMatch[1]), ...body });
        return result.error ? Promise.reject(new Error(result.error)) : result.group;
      }
      if (method === "DELETE" && idMatch) {
        const result = deleteGroup(cid, Number(idMatch[1]));
        return result.error ? Promise.reject(new Error(result.error)) : result;
      }
      return getAccountGroups(cid);
    }
    if (path.startsWith("/accounting/accounts")) return ACCOUNTS[cid] || [];
    const voucherMatch = path.match(/^\/accounting\/vouchers\/(\d+)/);
    if (voucherMatch) {
      const vId = Number(voucherMatch[1]);
      if (method === "GET") {
        const v = getVoucher(cid, vId);
        return v ? v : Promise.reject(new Error("Voucher not found"));
      }
      if (method === "PUT") {
        const result = updateVoucher2(cid, vId, body);
        return result.error ? Promise.reject(new Error(result.error)) : result.record;
      }
    }
    if (path.startsWith("/accounting/vouchers")) return VOUCHERS[cid] || [];
    if (path.startsWith("/parties/customers")) return CUSTOMERS[cid] || [];
    if (path.startsWith("/parties/suppliers")) return SUPPLIERS[cid] || [];
    if (path.startsWith("/reports/trial-balance")) return trialBalanceFrom(ACCOUNTS[cid] || []);
    if (path.startsWith("/reports/gst-summary")) return cid === 1 ? GST_SUMMARY : [];
    if (path.startsWith("/reports/vat-summary")) return cid === 2 ? VAT_SUMMARY : [];

    console.warn("[VoyagerMock] no mock handler for", path);
    return [];
  }

  window.VoyagerMock = {
    handle, USER, COMPANIES, getReferenceData, GROUP_BEHAVIOR,
    addTicket, addHotel, addVisa, addInsurance, addTour, addVoucher, addAccount, getAccountGroups,
    addGroup, updateGroup, deleteGroup, updateLedger, deleteLedger, computeLedgerBalance,
    getVouchersForAccount, getVouchersForBranch,
    getTicket, updateTicket, getHotel, updateHotel, getVisaRecord, updateVisa,
    getInsuranceRecord, updateInsurance, getTour, updateTour, getVoucher, updateVoucher2,
    getTicketsForCustomer, getHotelsForCustomer, getHotelsForSupplier,
  };
})(window);