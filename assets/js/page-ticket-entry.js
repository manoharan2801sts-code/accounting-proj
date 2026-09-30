(async function () {
  const API_BASE = window.API_BASE || "/api";
  const OPT = window.VoyagerHardcode.TICKET_FORM_OPTIONS;
  const params = new URLSearchParams(window.location.search);
  const editId = params.get("id");
  // Both mutable - the "Saved" reschedule flow (enterSavedRescheduleMode)
  // resolves these from the saved RescheduleAirlineTicket/Line it loads
  // instead of the URL, since that flow's own URL only carries
  // reschedule_saved_id.
  let rescheduleTicketId = params.get("reschedule_ticket_id");
  let rescheduleLineId = params.get("reschedule_line_id");
  const rescheduleSavedId = params.get("reschedule_saved_id");
  let editingRescheduleId = null; // set once a SAVED reschedule ticket is loaded - routes Save Ticket to reschedule-tickets/<id>/update/ instead of create
  let activeCompanyId, activeCountry, allCustomers = [], allSuppliers = [], existingTickets = [];
  let voucherTypes = []; // active Voucher Types for the active company - drives the Invoice Type dropdown + Invoice Number auto-numbering
  const VOUCHER_TYPE_API = `${API_BASE}/voucher-type/`;
  let fopMasterCards = []; // active FOP Master cards for the active company, refreshed by populateFopOptions
  let pgMasterGateways = []; // PG Master gateways for the active company, refreshed by populatePgOptions
  const PG_MASTER_EFFECTIVE_API = `${API_BASE}/pg-master/effective/`;
  const pgEffectiveCache = new Map(); // `${gatewayName}|${asOfDateISO}` -> resolved snapshot (or null), so re-renders don't refetch
  let passengers = []; // array of passenger objects - source of truth for the register table
  let editingIndex = null;
  let viewMode = false;
  let rescheduleMode = false; // true only for the "Reschedule" pre-filled new-ticket flow - freezes fare/accounting amounts and Booking Status, and caps the register at the one carried-over passenger
  // Reschedule's fare modal shows two tabs covering the WHOLE modal (both
  // Passenger & Segment Details and Base Fare/Customer/Supplier):
  // "Parent PNR Details" (the original ticket line, frozen/non-editable,
  // shown purely for reference) and "Reschedule PNR Details" (this brand
  // new ticket's own data - starts completely blank/0.00, fully editable,
  // and IS what actually gets saved).
  let modalRescheduleTab = "parent";
  let rescheduleParentPassenger = null; // frozen clone of the original ticket line - never touched again
  let rescheduleEditPassenger = null; // this new ticket's own passenger data - mirrors passengers[0], updated whenever Save & Apply commits
  let modalSectors = []; // current passenger's multi-city sectors - {from,to,travelDate,flightNo,cabin,cls,fareType}
  let editingSectorIndex = null;

  const linesBody = document.getElementById("ticket-lines");
  const fareModal = document.getElementById("fare-breakdown-modal");
  const jvModal = document.getElementById("jv-modal");
  const findModal = document.getElementById("find-modal");
  const sectorModal = document.getElementById("sector-modal");
  const gstDetailModal = document.getElementById("gst-detail-modal");

  function fillPlain(el, values, placeholder) {
    el.innerHTML = (placeholder ? `<option value="">${placeholder}</option>` : "") +
      values.map((v) => `<option value="${v}">${v}</option>`).join("");
  }
  fillPlain(document.getElementById("invoice_type"), [], "Select...");
  fillPlain(document.getElementById("booking_type"), OPT.bookingTypes, "Select...");
  fillPlain(document.getElementById("booking_status"), OPT.bookingStatuses, "Select...");
  fillPlain(document.getElementById("travel_type"), OPT.travelTypes, "Select...");
  fillPlain(document.getElementById("payment_mode"), OPT.paymentModes, "Select...");
  // Gateway Ref stays visible next to Payment Mode always - only becomes
  // editable once "Payment Gateway" is picked; read-only for Top-up, since
  // it's not relevant there. Only clears its value on a genuine user-driven
  // Payment Mode change, not when re-syncing disabled state elsewhere (e.g.
  // loading a saved ticket, or unlocking one for editing).
  // Resolves the PG Master ledger mapping + PG Charges Percentage that was
  // actually in force for `gatewayName` on THIS ticket's own Invoice Date
  // (not necessarily whatever the gateway's row currently holds) -
  // see PGMasterHistory/_pg_master_effective_snapshot() server-side. Every
  // place that needs PG Charges/PG GST for calculation or JV posting must
  // go through this, never the raw `pgMasterGateways` cache (that's only
  // for populating the dropdown's list of active gateway names).
  async function getPgEffective(gatewayName) {
    if (!gatewayName || !activeCompanyId) return null;
    const asOfDate = toISOFromDDMMYYYY(getDateGroupValue(document.getElementById("invoice_date"))) || "";
    const cacheKey = `${gatewayName}|${asOfDate}`;
    if (pgEffectiveCache.has(cacheKey)) return pgEffectiveCache.get(cacheKey);
    let snapshot = null;
    try {
      const res = await fetch(`${PG_MASTER_EFFECTIVE_API}?company_id=${activeCompanyId}&gateway_name=${encodeURIComponent(gatewayName)}&as_of_date=${asOfDate}`);
      snapshot = res.ok ? await res.json() : null;
    } catch (err) {
      console.error("Could not load effective PG Master snapshot", err);
    }
    pgEffectiveCache.set(cacheKey, snapshot);
    return snapshot;
  }

  // PG GST - display-only, not used in any calculation (see computeFareLine/
  // computed_gst, which deliberately never reference it). Shows
  // PG Charges * whichever gateway is picked's PG Master -> PG Charges
  // Master ledger's own GST%, for reference.
  async function updatePgGstDisplay() {
    const el = document.getElementById("modal-pg-gst-pct");
    const pgChargesInput = document.getElementById("modal-pg-charges");
    if (!el || !pgChargesInput) return;
    const gatewayName = document.getElementById("payment_gateway_ref").value;
    const snapshot = await getPgEffective(gatewayName);
    const pct = snapshot ? Number(snapshot.pg_charges_master_ledger_gst_percentage) || 0 : 0;
    const pgCharges = parseFloat(pgChargesInput.value) || 0;
    el.textContent = fmtN(pgCharges * pct / 100);
  }

  // PG Charges (Passenger Fare modal) is non-editable - auto-computed as
  // this passenger's own Total Billed times the selected gateway's PG
  // Master -> PG Charges Percentage AS OF THIS TICKET'S BOOKING REF DATE
  // (pg-master.html's history), not typed by hand and not necessarily
  // today's live rate. Reads Total Billed off #modal-total-computed, which
  // recalcModalTotal() keeps current before calling this.
  async function updatePgCharges() {
    const input = document.getElementById("modal-pg-charges");
    const pctInput = document.getElementById("modal-pg-charges-pct");
    if (!input) return;
    const isGateway = document.getElementById("payment_mode").value === "Payment Gateway";
    if (!isGateway) {
      input.value = fmtN(0);
      if (pctInput) pctInput.value = "0.00%";
      await updatePgGstDisplay();
      return;
    }
    const gatewayName = document.getElementById("payment_gateway_ref").value;
    const snapshot = await getPgEffective(gatewayName);
    const pct = snapshot ? Number(snapshot.pg_charges_percentage) || 0 : 0;
    const totalBilled = parseFloat(document.getElementById("modal-total-computed").textContent) || 0;
    input.value = fmtN(totalBilled * pct / 100);
    if (pctInput) pctInput.value = `${pct.toFixed(2)}%`;
    await updatePgGstDisplay();
  }
  document.getElementById("payment_gateway_ref").addEventListener("change", updatePgCharges);
  // Invoice Date drives which PG Master snapshot applies - recompute PG
  // Charges if it changes while a gateway is already selected.
  document.getElementById("invoice_date").addEventListener("change", () => {
    if (document.getElementById("payment_gateway_ref").value) updatePgCharges();
  });

  function updateGatewayRefField() {
    const isGateway = document.getElementById("payment_mode").value === "Payment Gateway";
    document.getElementById("payment-gateway-ref-field").style.display = "contents";
    document.getElementById("payment_gateway_ref").disabled = !isGateway;
    // PG Charges (Passenger Fare modal) only makes sense - and only gets
    // saved - when this ticket is actually being paid via Payment Gateway.
    const pgChargesField = document.getElementById("modal-pg-charges-field");
    if (pgChargesField) pgChargesField.style.display = isGateway ? "" : "none";
    updatePgCharges();
  }
  document.getElementById("payment_mode").addEventListener("change", (e) => {
    updateGatewayRefField();
    if (e.target.value !== "Payment Gateway") document.getElementById("payment_gateway_ref").value = "";
    updatePgCharges();
  });
  // Runs once immediately so the field is visible (read-only) from the very
  // first load of a brand-new ticket too - not just after a "change" event
  // fires (which never happens until the user actually touches Payment Mode).
  updateGatewayRefField();
  fillPlain(document.getElementById("modal-pax-type"), OPT.paxTypes, "Select...");
  fillPlain(document.getElementById("modal-disc-on"), OPT.custDiscountOn, "Select...");
  fillPlain(document.getElementById("modal-disc-type"), OPT.custDiscountTypes, "Select...");
  fillPlain(document.getElementById("modal-supp-comm-on"), OPT.custDiscountOn, "Select...");
  fillPlain(document.getElementById("modal-supp-comm-type"), OPT.custDiscountTypes, "Select...");
  fillPlain(document.getElementById("modal-airline-category"), OPT.airlineCategories, "Select...");
  // Starts Cash-only - Own Card/Client Card only get added once we know
  // whether FOP Master actually has an active card of that type (see
  // populateFopOptions below, called from populateRefs).
  fillPlain(document.getElementById("modal-fop"), ["Cash"], null);
  fillPlain(document.getElementById("sector-cabin"), OPT.cabinOptions, "Select...");
  fillPlain(document.getElementById("sector-fare-type"), OPT.fareTypeOptions, "Select...");
  fillPlain(document.getElementById("booking_mode"), OPT.bookingModes, "Select...");
  document.getElementById("booking_mode").value = OPT.defaultBookingMode;
  // Frozen at "Manual" until the real Auto Push API integration exists - dropdown is
  // already wired with both options so this can flip to dynamic (enable it, and set
  // .value from the API response) the moment that integration is ready.
  document.getElementById("booking_mode").disabled = true;
  document.getElementById("user-name-options").innerHTML = OPT.userNames.map((v) => `<option value="${v}">`).join("");

  // ============================================================
  // Customers / Suppliers - real backend
  // ============================================================
  const CUSTOMERS_API = `${API_BASE}/customers/`;
  const SUPPLIERS_API = `${API_BASE}/suppliers/`;

  async function populateRefs(companyId) {
    const ref = window.VoyagerMock.getReferenceData(companyId);
    document.getElementById("currency").textContent = ref.currency;
    document.getElementById("bal-currency").textContent = ref.currency;
    document.querySelectorAll(".modal-currency-label").forEach((el) => (el.textContent = ref.currency));
    try {
      const [custRes, suppRes] = await Promise.all([
        fetch(`${CUSTOMERS_API}?company_id=${companyId}`), fetch(`${SUPPLIERS_API}?company_id=${companyId}`),
      ]);
      if (!custRes.ok) throw new Error(`Customers API returned ${custRes.status}`);
      if (!suppRes.ok) throw new Error(`Suppliers API returned ${suppRes.status}`);
      allCustomers = await custRes.json(); allSuppliers = await suppRes.json();
    } catch (err) {
      console.error("Could not load customers/suppliers from the Django API - is it running on localhost:8000?", err);
      voyagerAlert("Could not load customers/suppliers from the database. Is the Django backend running?", { icon: "error" });
      allCustomers = []; allSuppliers = [];
    }
    document.getElementById("customer-options").innerHTML = allCustomers.map((c) => `<option value="${c.name}">`).join("");
    document.getElementById("modal-office-id-options").innerHTML = allSuppliers
      .filter((s) => s.office_id)
      .map((s) => `<option value="${s.office_id}">`).join("");
    await populateVoucherTypeOptions(companyId);
    await populateFopOptions(companyId);
    await populatePgOptions(companyId);
    await populateMappedFieldNames(companyId);
    await populateCompanyState(companyId);
  }

  // Company Master's own State (company-master.html) - the "us" side of
  // the same-state/different-state comparison the JV's Output GST lines
  // use (see _compute_jv_lines server-side, and renderPgReceiptsTab below
  // for the PG Receipts tab's own copy of that same comparison).
  let companyState = "";
  const COMPANY_MASTER_API = `${API_BASE}/company-master/`;
  async function populateCompanyState(companyId) {
    try {
      const res = await fetch(`${COMPANY_MASTER_API}?id=${companyId}`);
      companyState = res.ok ? ((await res.json()).state || "") : "";
    } catch (err) {
      console.error("Could not load Company Master state", err);
      companyState = "";
    }
  }

  // JV account guard - fare fields whose JV posting line (see
  // jv_hardcode.py's JV_LINE_MAP) has no Ledger mapped yet in Master
  // Mapping (master-mapping.html) can't be given a value - a value there
  // would post to a JV line with no real ledger. Reverts any typed value
  // back to 0 and warns once per focus, rather than disabling the field
  // outright (so it's still obvious the field exists and why it's blocked).
  let mappedFieldNames = new Set();
  // field_name -> its mapped ledger's GST% (Ledgers Master), used to
  // compute GST Amount per-component instead of one flat GST% - see
  // computeFareLine().
  let fieldLedgerGstPct = {};
  // field_name -> its mapped ledger's display name (or a "not mapped"
  // placeholder) - used by the JV PG Receipts tab's Output CGST/SGST/IGST
  // rows (see renderPgReceiptsTab), same convention as the backend's
  // mapped_ledger() in views._compute_jv_lines.
  let mappedFieldLedgerName = {};
  const MASTER_MAPPING_API = `${API_BASE}/master-mapping/`;
  async function populateMappedFieldNames(companyId) {
    try {
      const res = await fetch(`${MASTER_MAPPING_API}?company_id=${companyId}&product_type=Airline`);
      const rows = res.ok ? await res.json() : [];
      mappedFieldNames = new Set(rows.map((r) => r.field_name));
      fieldLedgerGstPct = {};
      mappedFieldLedgerName = {};
      rows.forEach((r) => {
        fieldLedgerGstPct[r.field_name] = Number(r.ledger_gst_percentage) || 0;
        mappedFieldLedgerName[r.field_name] = r.ledger_name || `${r.field_name} (not mapped in Master Mapping)`;
      });
    } catch (err) {
      console.error("Could not load Master Mapping field list", err);
      mappedFieldNames = new Set();
      fieldLedgerGstPct = {};
      mappedFieldLedgerName = {};
    }
  }
  const JV_GUARDED_FIELDS = {
    "modal-markup": "Markup A/c", "modal-addl-markup": "Addl Markup A/c", "modal-ssr-markup": "SSR Markup A/c",
    "modal-service-fee": "Service Fee A/c", "modal-addl-service-fee": "Addl Service Fee A/c",
    "modal-ssr-service-fee": "SSR Service Fee A/c", "modal-gst-pct": "Output IGST A/c",
    "modal-supp-comm-value": "Commission A/c", "modal-supp-tds-per": "Commission TDS A/c",
    "modal-supp-markup": "Supplier Markup A/c", "modal-supp-addl-markup": "Supplier Addl Markup A/c",
    "modal-supp-service-fee": "Supplier Service Fee A/c", "modal-supp-addl-service-fee": "Supplier Addl Service Fee A/c",
    "modal-supp-gst-pct": "Input IGST A/c",
    // Reschedule PNR Details tab only - same guard, so these can't hold a
    // value either until their own Master Mapping ledger is set.
    "modal-agent-penalty": "Agent Penalty A/c",
    "modal-reschedule-penalty": "Supplier Reschedule Penalty A/c",
  };
  const jvGuardWarned = new Set();
  document.addEventListener("focusin", (e) => { jvGuardWarned.delete(e.target.id); });

  // Same guard, for the JV PG Receipts tab's auto-filled PG Charges row -
  // it's not typed by hand so it can't be reverted/blocked like
  // JV_GUARDED_FIELDS above, but it still posts against the gateway's PG
  // Charges Master ledger (PG Master), which is optional there. Warn once
  // per gateway (not on every JV refresh) if that ledger isn't mapped
  // while PG Charges holds a real amount.
  const pgLedgerWarned = new Set();
  function warnUnmappedPgLedger(gatewayName) {
    if (pgLedgerWarned.has(gatewayName)) return;
    pgLedgerWarned.add(gatewayName);
    voyagerAlert(
      `"${gatewayName}" has no PG Charges Master ledger mapped in PG Master. PG Charges is still auto-filled on this ticket, but won't post to a real ledger in the JV until one is mapped there.`,
      { icon: "warning" }
    );
  }

  // Same idea, for the PG Receipts tab's Output CGST/SGST/IGST A/c
  // line(s) (PG GST's Credit side) - these resolve via Master Mapping
  // (GST and TDS), not PG Master, so they get their own "not mapped"
  // warning, keyed by field name rather than gateway name.
  const gstFieldWarned = new Set();
  function warnUnmappedGstField(fieldName) {
    if (gstFieldWarned.has(fieldName)) return;
    gstFieldWarned.add(fieldName);
    voyagerAlert(
      `"${fieldName}" has no ledger mapped in Master Mapping (GST and TDS). PG GST is still auto-filled on this ticket, but won't post to a real ledger in the JV until one is mapped there.`,
      { icon: "warning" }
    );
  }
  document.addEventListener("input", (e) => {
    const fieldName = JV_GUARDED_FIELDS[e.target.id];
    if (!fieldName || mappedFieldNames.has(fieldName) || viewMode) return;
    if ((parseFloat(e.target.value) || 0) === 0) return;
    e.target.value = "0.00";
    if (!jvGuardWarned.has(e.target.id)) {
      jvGuardWarned.add(e.target.id);
      voyagerAlert("Required Ledger account is not mapped.");
    }
    recalcModalTotal(); recalcSuppTotal(); liveSyncSummary();
  });

  // Gateway Ref dropdown - lists PG Master's active Payment Gateway Names
  // (same idea as the FOP Card Number dropdown pulling from FOP Master).
  const PG_MASTER_API = `${API_BASE}/pg-master/`;
  async function populatePgOptions(companyId) {
    try {
      const res = await fetch(`${PG_MASTER_API}?company_id=${companyId}`);
      pgMasterGateways = res.ok ? await res.json() : [];
    } catch (err) {
      console.error("Could not load PG Master gateways", err);
      pgMasterGateways = [];
    }
    const names = pgMasterGateways.filter((g) => g.is_active).map((g) => g.gateway_name);
    fillPlain(document.getElementById("payment_gateway_ref"), names, "Select...");
    updatePgCharges();
  }

  // Invoice Type dropdown is populated from Masters > Voucher Type
  // (voucher-type.html) - only active voucher types, by name. Picking one
  // drives Invoice Number auto-numbering per that voucher type's own
  // Number Method (see applyInvoiceNumbering below).
  async function populateVoucherTypeOptions(companyId) {
    const select = document.getElementById("invoice_type");
    const current = select.value;
    try {
      const res = await fetch(`${VOUCHER_TYPE_API}?company_id=${companyId}`);
      voucherTypes = res.ok ? await res.json() : [];
    } catch (err) {
      console.error("Could not load Voucher Types", err);
      voucherTypes = [];
    }
    const activeNames = voucherTypes.filter((vt) => vt.is_active).map((vt) => vt.name);
    fillPlain(select, activeNames, "Select...");
    select.value = activeNames.includes(current) ? current : "";
  }

  // Invoice Number follows the selected Invoice Type's (=VoucherType)
  // Number Method: Manual leaves it a plain editable box, Automatic locks
  // it to the server-computed next number, Automatic & Manual Override
  // prefills that same suggestion but still lets the user change it.
  async function applyInvoiceNumbering() {
    const invoiceNumberInput = document.getElementById("invoice_number");
    const typeName = document.getElementById("invoice_type").value;
    const vt = voucherTypes.find((v) => v.name === typeName);

    if (!vt || vt.number_method === "Manual") {
      invoiceNumberInput.readOnly = false;
      return;
    }

    const dateGroup = document.getElementById("invoice_date");
    const nativeDate = dateGroup ? dateGroup.querySelector(".dg-native") : null;
    const voucherDate = nativeDate && nativeDate.value ? nativeDate.value : "";

    try {
      const qs = new URLSearchParams({ company_id: activeCompanyId, name: typeName });
      if (voucherDate) qs.set("voucher_date", voucherDate);
      const res = await fetch(`${VOUCHER_TYPE_API}next-number/?${qs}`);
      const data = await res.json();
      if (res.ok && data.next_number) {
        invoiceNumberInput.value = data.next_number;
      }
    } catch (err) {
      console.error("Could not compute the next Invoice Number", err);
    }
    invoiceNumberInput.readOnly = vt.number_method === "Automatic";
  }
  document.getElementById("invoice_type").addEventListener("change", applyInvoiceNumbering);

  // FOP dropdown starts Cash-only; "Own Card"/"Client Card" are only added
  // when FOP Master (fop-master.html) has at least one ACTIVE card of that
  // type - no active cards at all means the dropdown stays just "Cash".
  const FOP_MASTER_API = `${API_BASE}/fop-master/`;
  async function populateFopOptions(companyId) {
    const fopSelect = document.getElementById("modal-fop");
    const current = fopSelect.value;
    try {
      const res = await fetch(`${FOP_MASTER_API}?company_id=${companyId}`);
      fopMasterCards = res.ok ? await res.json() : [];
    } catch (err) {
      console.error("Could not load FOP Master cards", err);
      fopMasterCards = [];
    }
    const activeCards = fopMasterCards.filter((c) => c.is_active);
    const activeTypes = [...new Set(activeCards.map((c) => c.card_type))];
    const options = ["Cash", ...OPT.fopOptions.filter((o) => o !== "Cash" && activeTypes.includes(o))];
    fillPlain(fopSelect, options, null);
    fopSelect.value = options.includes(current) ? current : "Cash";
    updateCardNumberField();
  }

  // Card Number stays visible always - only its list (and whether it's
  // editable) changes with the FOP type picked: "Own Card" only sees active
  // Own Card numbers, "Client Card" only active Client Card numbers; for
  // Cash it's read-only (disabled) since no card applies.
  function updateCardNumberField(preselect) {
    const fopType = document.getElementById("modal-fop").value;
    document.getElementById("modal-card-number-field").style.display = "contents";
    const select = document.getElementById("modal-card-number");
    if (fopType === "Cash" || !fopType) {
      fillPlain(select, [], "Not applicable");
      select.disabled = true;
      return;
    }
    select.disabled = viewMode;
    const matching = fopMasterCards.filter((c) => c.is_active && c.card_type === fopType);
    fillPlain(select, matching.map((c) => c.card_number), "Select...");
    if (preselect && matching.some((c) => c.card_number === preselect)) select.value = preselect;
  }
  document.getElementById("modal-fop").addEventListener("change", () => updateCardNumberField());
  document.getElementById("customer").addEventListener("input", (e) => {
    const c = allCustomers.find((c) => c.name === e.target.value);
    document.getElementById("customer_code").textContent = c ? c.code : "-";
    document.getElementById("customer_agent_id").textContent = c && c.agent_id ? c.agent_id : "-";
    document.getElementById("customer_address").textContent = c && c.address ? c.address : "-";
    document.getElementById("customer_gst").textContent = c && c.gst_no ? c.gst_no : "-";
  });
  document.getElementById("modal-office-id").addEventListener("input", (e) => {
    const s = allSuppliers.find((s) => s.office_id === e.target.value);
    document.getElementById("modal-supplier").value = s ? s.name : "";
    autofillSupplierCommission();
  });

  // Supplier Master lookup - Travel Type + Airline Category + Cabin + Fare
  // Type + Office ID together must EXACTLY match one saved Supplier Master
  // Commission Rule (supplier-master.html) for it to auto-fill the Supplier
  // Commission box. Re-checked whenever any of those 5 fields changes
  // (office ID, airline category, travel type, or a sector's cabin/fare
  // type via Save in the Add Sector popup). No exact match -> the Supplier
  // Commission fields are cleared, not left showing a stale value.
  const SUPPLIER_RULES_API = `${API_BASE}/supplier-commission-rules/`;
  function clearSupplierCommissionAutofill() {
    document.getElementById("modal-supp-comm-on").value = "";
    document.getElementById("modal-supp-comm-type").value = "";
    document.getElementById("modal-supp-comm-value").value = "0.00";
    updateSuppDiscValueLabel();
    recalcSuppTotal();
  }
  async function autofillSupplierCommission() {
    const officeId = document.getElementById("modal-office-id").value.trim();
    const travelType = document.getElementById("travel_type").value;
    const airlineCategory = document.getElementById("modal-airline-category").value;
    const cabin = joinSectorField("cabin");
    const fareType = joinSectorField("fareType");
    if (!officeId || !activeCompanyId) return;
    try {
      const res = await fetch(`${SUPPLIER_RULES_API}?company_id=${activeCompanyId}&office_id=${encodeURIComponent(officeId)}`);
      if (!res.ok) return;
      const rules = await res.json();
      const rule = rules.find((r) =>
        (r.travel_type || "") === travelType &&
        (r.airline_category || "") === airlineCategory &&
        (r.cabin || "") === cabin &&
        (r.fare_type || "") === fareType
      );
      if (!rule || !rule.calc_type) {
        clearSupplierCommissionAutofill();
        return;
      }
      if (rule.comm_on) document.getElementById("modal-supp-comm-on").value = rule.comm_on;
      document.getElementById("modal-supp-comm-type").value = rule.calc_type;
      document.getElementById("modal-supp-comm-value").value = rule.calc_type === "Flat"
        ? fmtN(rule.flat_amt) : Number(rule.calc_pct).toFixed(2);
      updateSuppDiscValueLabel();
      recalcSuppTotal();
    } catch (err) {
      console.error("Could not look up Supplier Master commission rules", err);
    }
  }
  document.getElementById("travel_type").addEventListener("change", autofillSupplierCommission);
  document.getElementById("modal-airline-category").addEventListener("change", autofillSupplierCommission);

  // ============================================================
  // dd-mm-yyyy 3-box date handling (header + modal both use .date-group)
  // ============================================================
  function wireDateGroup(container) {
    if (container.querySelector(".dg-native")) return; // native <input type="date"> needs no wiring
    const dd = container.querySelector(".dg-dd"), mm = container.querySelector(".dg-mm"), yyyy = container.querySelector(".dg-yyyy");
    const segments = [dd, mm, yyyy];
    segments.forEach((el, i) => {
      el.addEventListener("input", () => {
        el.value = el.value.replace(/\D/g, "").slice(0, el.maxLength);
        if (el.value.length === el.maxLength && segments[i + 1]) segments[i + 1].focus();
      });
      el.addEventListener("keydown", (e) => {
        if (e.key === "Backspace" && el.value === "" && segments[i - 1]) {
          segments[i - 1].focus();
          const prev = segments[i - 1];
          setTimeout(() => prev.setSelectionRange(prev.value.length, prev.value.length), 0);
        }
      });
    });
  }
  function getDateGroupValue(container) {
    const native = container.querySelector(".dg-native");
    if (native) {
      if (!native.value) return "";
      const [yyyy, mm, dd] = native.value.split("-");
      return `${dd}/${mm}/${yyyy}`;
    }
    const dd = container.querySelector(".dg-dd").value, mm = container.querySelector(".dg-mm").value, yyyy = container.querySelector(".dg-yyyy").value;
    if (!dd && !mm && !yyyy) return "";
    return `${dd.padStart(2, "0")}/${mm.padStart(2, "0")}/${yyyy}`;
  }
  function setDateGroupValue(container, ddmmyyyy) {
    const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(ddmmyyyy || "");
    const native = container.querySelector(".dg-native");
    if (native) {
      native.value = m ? `${m[3]}-${m[2]}-${m[1]}` : "";
      return;
    }
    container.querySelector(".dg-dd").value = m ? m[1] : "";
    container.querySelector(".dg-mm").value = m ? m[2] : "";
    container.querySelector(".dg-yyyy").value = m ? m[3] : "";
  }
  document.querySelectorAll(".date-group").forEach(wireDateGroup);

  function parseDDMMYYYY(str) {
    const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec((str || "").trim());
    if (!m) return null;
    const [, dd, mm, yyyy] = m;
    const d = new Date(Number(yyyy), Number(mm) - 1, Number(dd));
    if (d.getFullYear() != yyyy || d.getMonth() != mm - 1 || d.getDate() != dd) return null;
    return d;
  }
  function todayDDMMYYYY() {
    const d = new Date();
    return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}/${d.getFullYear()}`;
  }
  function toISOFromDDMMYYYY(str) {
    const d = parseDDMMYYYY(str);
    return d ? `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}` : null;
  }
  function toISODate(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }
  // Clamp the Invoice Date / Booking Ref Date calendar pickers to the current
  // financial year (Apr-Mar) and never later than today, so an out-of-range
  // date can't be picked in the first place (checkNotFutureAndInFY still
  // guards submit for older browsers / typed-in values).
  (function clampFYDatePickers() {
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const fyYear = today.getMonth() >= 3 ? today.getFullYear() : today.getFullYear() - 1;
    const fyStart = new Date(fyYear, 3, 1);
    const min = toISODate(fyStart), max = toISODate(today);
    ["invoice_date", "booking_ref_date"].forEach((id) => {
      const native = document.querySelector(`#${id} .dg-native`);
      if (native) { native.min = min; native.max = max; }
    });
  })();
  function isoToDDMMYYYY(iso) {
    if (!iso) return "";
    const [y, m, d] = iso.split("-");
    return `${d}/${m}/${y}`;
  }
  function checkNotFutureAndInFY(str, label) {
    const d = parseDDMMYYYY(str);
    if (!str) return `${label} is required.`;
    if (!d) return `${label} must be a valid date.`;
    const today = new Date(); today.setHours(0, 0, 0, 0);
    if (d > today) return `${label} cannot be later than today.`;
    const fyYear = d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1;
    const fyStart = new Date(fyYear, 3, 1), fyEnd = new Date(fyYear + 1, 2, 31);
    if (d < fyStart || d > fyEnd) return `${label} must be within the current financial year (Apr-Mar).`;
    return null;
  }
  function setHint(id, msg, ok) {
    const el = document.getElementById(id);
    if (!el) return;
    el.style.display = msg ? "block" : "none";
    el.textContent = msg || "";
    el.className = "field-hint" + (msg ? (ok ? " ok" : " error") : "");
  }

  // Airline PNR / GDS PNR / Booking Reference: force capital letters as
  // the user types (cursor position preserved so it doesn't jump to the end).
  ["airline_pnr_header", "gds_pnr_header", "booking_reference"].forEach((id) => {
    const el = document.getElementById(id);
    el.addEventListener("input", () => {
      const pos = el.selectionStart;
      el.value = el.value.toUpperCase();
      el.setSelectionRange(pos, pos);
    });
  });

  // Pax Name - letters/spaces/punctuation only, no digits.
  document.getElementById("modal-pax-name").addEventListener("input", (e) => {
    const pos = e.target.selectionStart;
    const cleaned = e.target.value.replace(/[0-9]/g, "");
    if (cleaned !== e.target.value) {
      e.target.value = cleaned;
      e.target.setSelectionRange(pos - 1, pos - 1);
    }
  });

  // Invoice Number / Booking Reference must be unique across all existing
  // tickets (excluding this ticket's own rows when editing). Only checked
  // when the user clicks Save Ticket - not live while typing.
  function checkDuplicateHeaderField(fieldId, hintId, ticketField, label) {
    const value = document.getElementById(fieldId).value.trim();
    if (!value) { setHint(hintId, "", true); return true; }
    const dup = existingTickets.some((t) => (t[ticketField] || "") === value && String(t.id) !== String(editId));
    setHint(hintId, dup ? `This ${label} is already used.` : "", dup ? false : true);
    return !dup;
  }

  // ============================================================
  // Fare formula - identical to the backend's _compute_jv_lines /
  // TicketLine.compute_total(), so the numbers always match.
  // ============================================================
  function computeDiscBase(p) {
    const supplierCost = p.basic_fare + p.yq + p.yr + p.k3_tax + p.tax_others + p.seat + p.meal + p.baggage + p.other_ssr;
    const baseMap = { "Basic": p.basic_fare, "Basic + YQ": p.basic_fare + p.yq, "Basic + YR": p.basic_fare + p.yr,
      "Basic + YQ + YR": p.basic_fare + p.yq + p.yr, "Gross": supplierCost };
    return baseMap[p.disc_on] || 0;
  }
  function computeFareLine(p) {
    const supplierCost = p.basic_fare + p.yq + p.yr + p.k3_tax + p.tax_others + p.seat + p.meal + p.baggage + p.other_ssr;
    const discBase = computeDiscBase(p);
    const discount = p.disc_type === "Percentage" ? discBase * (p.disc_value / 100) : (p.disc_type === "Flat" ? p.disc_value : 0);
    const tds = discount * (p.tds_per / 100);
    // GST Amount = each Client Accounting fee component times its OWN
    // mapped ledger's GST% (Master Mapping), not one flat GST% typed on
    // the line - see fieldLedgerGstPct above. Same formula regardless of
    // Payment Mode - PG Charges never contributes to GST Amount.
    const gst = p.service_fee * ((fieldLedgerGstPct["Service Fee A/c"] || 0) / 100)
      + p.addl_service_fee * ((fieldLedgerGstPct["Addl Service Fee A/c"] || 0) / 100)
      + p.ssr_service_fee * ((fieldLedgerGstPct["SSR Service Fee A/c"] || 0) / 100);
    const suppGst = ((p.supp_service_fee || 0) + (p.supp_addl_service_fee || 0)) * ((p.supp_gst_pct || 0) / 100);
    const total = supplierCost - discount + tds + p.markup + p.addl_markup + p.ssr_markup
      + p.service_fee + p.addl_service_fee + p.ssr_service_fee + gst
      + (p.supp_markup || 0) + (p.supp_addl_markup || 0) + (p.supp_service_fee || 0) + (p.supp_addl_service_fee || 0) + suppGst;
    return { supplierCost, discount, tds, gst, total };
  }
  // Supplier Commission - same shape as the Discount calc above, but keyed
  // off supp_comm_on/supp_comm_type/supp_comm_value/supp_tds_per. Doesn't
  // feed into computeFareLine's total (commission isn't part of what the
  // client is billed), it's purely its own box's Amount/TDS Amount display.
  function computeSuppLine(p) {
    const discBase = computeDiscBase({ ...p, disc_on: p.supp_comm_on });
    const commission = p.supp_comm_type === "Percentage" ? discBase * (p.supp_comm_value / 100)
      : (p.supp_comm_type === "Flat" ? p.supp_comm_value : 0);
    const tds = commission * (p.supp_tds_per / 100);
    const gst = ((p.supp_service_fee || 0) + (p.supp_addl_service_fee || 0)) * ((p.supp_gst_pct || 0) / 100);
    return { commission, tds, gst };
  }

  // ============================================================
  // Passenger Fare & Accounting Breakdown modal
  // ============================================================
  const blankPassenger = () => ({
    airline_code: "", airline_name: "", airline_category: "", flight_no: "", ticket_no: "", passenger_name: "", pax_type: "",
    sector: "", travel_date: "", cabin: "", travel_class: "", fare_type: "", basic_fare: 0, yq: 0, yr: 0, k3_tax: 0,
    tax_others: 0, seat: 0, meal: 0,
    baggage: 0, other_ssr: 0, supplier_penalty: 0, disc_on: "", disc_type: "", disc_value: 0, tds_per: 0, pg_charges: 0, pg_charges_percentage: 0, markup: 0, addl_markup: 0, ssr_markup: 0,
    service_fee: 0, addl_service_fee: 0, ssr_service_fee: 0, gst_pct: 0, supplier_name: "", office_id: "", fop: "Cash", card_number: "",
    supp_comm_on: "", supp_comm_type: "", supp_comm_value: 0, supp_tds_per: 0,
    supp_markup: 0, supp_addl_markup: 0, supp_service_fee: 0, supp_addl_service_fee: 0, supp_gst_pct: 0,
    agent_penalty: 0, reschedule_penalty: 0,
  });

  // Money amounts only (Basic Fare, Taxes, Markup, Service Fee, GST
  // Amount, Total, etc.) - follows Company Master's "No. of Decimals".
  // Percentages (GST %, TDS %, ROE, Discount %) stay fixed at 2 decimals
  // and keep using .toFixed(2) directly - they're rates, not currency.
  function fmtN(v) { return (Number(v) || 0).toFixed(VoyagerUtil.getDecimalPlaces()); }

  function updateDiscValueLabel() {
    const type = document.getElementById("modal-disc-type").value;
    const isPct = type === "Percentage";
    const inReschedLayout = rescheduleMode && modalRescheduleTab === "reschedule";
    // Discount % and Cust Discount On stay visible always now - only
    // Percentage makes them editable (Discount % is meaningless for Flat,
    // Cust Discount On is the base % is calculated against).
    const discValueField = document.getElementById("modal-disc-value-field");
    const discValLabel = document.getElementById("modal-disc-val-label");
    if (inReschedLayout) {
      // Reschedule's Discount Amount box is a PG-Charges-style single box
      // (no visible label for the % side) - dissolving this span lets its
      // input become a true direct child of .acct-pct-box, alongside the
      // "%" suffix, so the CSS there can size/style it as one seamless box.
      discValueField.style.display = "contents";
      discValLabel.style.display = "none";
    } else {
      // Default/Parent layout: dissolves into the row's own grid so its
      // label+input become the grid's own 2 columns directly - the row's
      // 4-column layout is kept permanently (rather than collapsing to a
      // solo Amount column) since % always has a slot to sit in now.
      discValueField.style.display = "contents";
      discValLabel.style.display = "";
    }
    document.getElementById("modal-disc-value").disabled = !isPct || viewMode;
    // Flat has no meaningful percentage - show 0 rather than echoing the
    // flat Discount Amount into a field labeled "Discount %".
    if (!isPct) document.getElementById("modal-disc-value").value = "0.00";
    // Only meaningful (and only still inside .disc-amount-row) in the
    // default layout - Reschedule's own row has a fixed inline grid that
    // doesn't depend on this class at all.
    if (!inReschedLayout) {
      document.getElementById("modal-disc-computed").closest(".disc-amount-row").classList.add("pct-active");
    }
    document.getElementById("modal-disc-on-field").style.display = "";
    document.getElementById("modal-disc-on").disabled = !isPct || viewMode;
  }
  // Supplier Commission: Commission Type/% sit paired on one row; Commission
  // Amount is its own full-width row below (directly editable - see the
  // input listener further down for the two-way % <-> Amount sync).
  function updateSuppDiscValueLabel() {
    const type = document.getElementById("modal-supp-comm-type").value;
    const isPct = type === "Percentage";
    // Commission % and Supplier Commission On stay visible always now -
    // only Percentage makes them editable. In the Reschedule tab's merged
    // Commission Amount box, the % side has no visible label (just the
    // .acct-pct-box's "%" suffix) - same treatment as Discount's own box.
    const inReschedLayout = rescheduleMode && modalRescheduleTab === "reschedule";
    document.getElementById("modal-supp-comm-value-field").style.display = "contents";
    document.getElementById("modal-supp-comm-val-label").style.display = inReschedLayout ? "none" : "";
    document.getElementById("modal-supp-comm-value").disabled = !isPct || viewMode;
    document.getElementById("modal-supp-comm-on-field").style.display = "";
    document.getElementById("modal-supp-comm-on").disabled = !isPct || viewMode;
  }
  function num(id) { return parseFloat(document.getElementById(id).value) || 0; }
  // Clicking/tabbing into any fare amount field selects its current text
  // (e.g. the default "0.00") so typing straight away overwrites it,
  // instead of the user having to manually delete the 0 first.
  document.addEventListener("focus", (e) => {
    if (e.target.matches && e.target.matches('input[type="number"], .dom-amount')) e.target.select();
  }, true);
  // Every fare/markup/fee/discount/TDS/GST amount field (.dom-amount) -
  // digits and a single decimal point only, nothing else (no letters,
  // no "e"/"+"/"-" that a native type="number" input would otherwise
  // still accept). These are type="text" specifically so this filter is
  // the ONLY thing constraining what can be typed - a native
  // type="number" input can silently discard an in-progress edit back to
  // "" when what's been typed so far isn't valid IEEE-754 syntax yet
  // (e.g. "12." while still typing the fraction), which looked like the
  // field randomly resetting to 0.00.
  // Markup/Addl Markup/SSR Markup/Service Fee/Addl Service Fee/SSR
  // Service Fee/Sup.../PG Charges (.dom-max10) additionally cap the
  // integer part at 10 digits, truncating as the user types.
  document.addEventListener("input", (e) => {
    if (!e.target.matches || !e.target.matches(".dom-amount")) return;
    let v = e.target.value.replace(/[^0-9.]/g, "");
    const firstDot = v.indexOf(".");
    if (firstDot !== -1) v = v.slice(0, firstDot + 1) + v.slice(firstDot + 1).replace(/\./g, "");
    if (e.target.matches(".dom-max10")) {
      const [intPart, decPart] = v.split(".");
      const fixedInt = intPart.slice(0, 10);
      v = decPart !== undefined ? `${fixedInt}.${decPart}` : fixedInt;
    }
    if (v !== e.target.value) e.target.value = v;
  });
  function readModalPassenger() {
    return {
      airline_code: joinSectorField("airlineCode"),
      airline_name: joinSectorField("airlineName"),
      airline_category: document.getElementById("modal-airline-category").value,
      flight_no: joinSectorField("flightNo"),
      ticket_no: document.getElementById("modal-ticket-no").value.trim(),
      passenger_name: document.getElementById("modal-pax-name").value.trim(),
      pax_type: document.getElementById("modal-pax-type").value,
      sector: modalSectors.map((s) => `${s.from}-${s.to}`).join(","),
      travel_date: sectorTravelDateField(),
      cabin: joinSectorField("cabin"),
      travel_class: joinSectorField("cls"),
      fare_type: joinSectorField("fareType"),
      basic_fare: num("modal-basic-fare"), yq: num("modal-yq"), yr: num("modal-yr"), k3_tax: num("modal-k3"),
      tax_others: num("modal-tax-others"), seat: num("modal-seat"), meal: num("modal-meal"), baggage: num("modal-baggage"),
      other_ssr: num("modal-other-ssr"), supplier_penalty: num("modal-fare-supplier-penalty"),
      disc_on: document.getElementById("modal-disc-on").value,
      disc_type: document.getElementById("modal-disc-type").value,
      // Flat has no % field of its own (it's shown as 0) - the flat amount
      // is read straight from Discount Amount instead.
      disc_value: document.getElementById("modal-disc-type").value === "Flat" ? num("modal-disc-computed") : num("modal-disc-value"),
      tds_per: num("modal-tds-per"), pg_charges: num("modal-pg-charges"), pg_charges_percentage: num("modal-pg-charges-pct"), markup: num("modal-markup"), addl_markup: num("modal-addl-markup"), ssr_markup: num("modal-ssr-markup"),
      service_fee: num("modal-service-fee"), addl_service_fee: num("modal-addl-service-fee"), ssr_service_fee: num("modal-ssr-service-fee"),
      // GST % field is hidden from the UI - never send a value for it.
      gst_pct: 0,
      supplier_name: document.getElementById("modal-supplier").value,
      office_id: document.getElementById("modal-office-id").value,
      fop: document.getElementById("modal-fop").value,
      card_number: document.getElementById("modal-fop").value === "Cash" ? "" : document.getElementById("modal-card-number").value,
      supp_comm_on: document.getElementById("modal-supp-comm-on").value,
      supp_comm_type: document.getElementById("modal-supp-comm-type").value,
      supp_comm_value: num("modal-supp-comm-value"),
      supp_tds_per: num("modal-supp-tds-per"),
      supp_markup: num("modal-supp-markup"), supp_addl_markup: num("modal-supp-addl-markup"),
      supp_service_fee: num("modal-supp-service-fee"), supp_addl_service_fee: num("modal-supp-addl-service-fee"),
      supp_gst_pct: num("modal-supp-gst-pct"),
      agent_penalty: num("modal-agent-penalty"), reschedule_penalty: num("modal-reschedule-penalty"),
    };
  }
  function recalcModalTotal(opts) {
    const p = readModalPassenger();
    const r = computeFareLine(p);
    if (!opts || !opts.skipDiscAmount) {
      document.getElementById("modal-disc-computed").value = fmtN(r.discount);
    }
    document.getElementById("modal-tds-computed").textContent = fmtN(r.tds);
    document.getElementById("modal-gst-computed").textContent = fmtN(r.gst);
    // Taxable Amount - display-only, not used in any calculation.
    document.getElementById("modal-taxable-amount").textContent =
      fmtN(p.service_fee + p.addl_service_fee + p.ssr_service_fee);
    document.getElementById("modal-total-computed").textContent = fmtN(r.total);
    updatePgCharges();
    return r;
  }

  // GST Amount calculation breakdown popup - view only, purely reads
  // whatever's already on screen/already computed elsewhere, doesn't
  // feed into any calculation itself.
  function openGstDetailModal() {
    const p = readModalPassenger();
    const rows = [
      { label: "Service Fee", amount: p.service_fee, field: "Service Fee A/c" },
      { label: "Addl Service Fee", amount: p.addl_service_fee, field: "Addl Service Fee A/c" },
      { label: "SSR Service Fee", amount: p.ssr_service_fee, field: "SSR Service Fee A/c" },
    ];
    let total = 0;
    const bodyHtml = rows.map((row) => {
      const pct = fieldLedgerGstPct[row.field] || 0;
      const gstAmt = (row.amount || 0) * pct / 100;
      total += gstAmt;
      return `<tr>
        <td>${row.label}</td>
        <td>${fmtN(row.amount)}</td>
        <td>${pct.toFixed(2)}%</td>
        <td>${fmtN(gstAmt)}</td>
      </tr>`;
    }).join("") + `<tr class="dom-gst-detail-total"><td colspan="3">GST Amount</td><td>${fmtN(total)}</td></tr>`;
    document.getElementById("gst-detail-tbody").innerHTML = bodyHtml;
    gstDetailModal.classList.add("open");
  }
  function closeGstDetailModal() { gstDetailModal.classList.remove("open"); }
  document.getElementById("modal-gst-detail-btn").addEventListener("click", openGstDetailModal);
  document.getElementById("gst-detail-close-x-btn").addEventListener("click", closeGstDetailModal);
  document.getElementById("gst-detail-ok-btn").addEventListener("click", closeGstDetailModal);

  function recalcSuppTotal(opts) {
    const p = readModalPassenger();
    const r = computeSuppLine(p);
    if (!opts || !opts.skipComputed) {
      document.getElementById("modal-supp-comm-computed").value = fmtN(r.commission);
    }
    document.getElementById("modal-supp-tds-computed").textContent = fmtN(r.tds);
    document.getElementById("modal-supp-gst-computed").textContent = fmtN(r.gst);
    return r;
  }
  function writeModalPassenger(p) {
    document.getElementById("modal-airline-category").value = p.airline_category || "";
    document.getElementById("modal-ticket-no").value = p.ticket_no;
    document.getElementById("modal-pax-name").value = p.passenger_name;
    document.getElementById("modal-pax-type").value = p.pax_type;
    parseSectorsFromPassenger(p);
    document.getElementById("modal-basic-fare").value = fmtN(p.basic_fare);
    document.getElementById("modal-yq").value = fmtN(p.yq); document.getElementById("modal-yr").value = fmtN(p.yr);
    document.getElementById("modal-k3").value = fmtN(p.k3_tax); document.getElementById("modal-tax-others").value = fmtN(p.tax_others);
    document.getElementById("modal-seat").value = fmtN(p.seat); document.getElementById("modal-meal").value = fmtN(p.meal);
    document.getElementById("modal-baggage").value = fmtN(p.baggage); document.getElementById("modal-other-ssr").value = fmtN(p.other_ssr);
    document.getElementById("modal-fare-supplier-penalty").value = fmtN(p.supplier_penalty || 0);
    document.getElementById("modal-disc-on").value = p.disc_on; document.getElementById("modal-disc-type").value = p.disc_type;
    document.getElementById("modal-disc-value").value = p.disc_type === "Flat" ? "0.00" : Number(p.disc_value).toFixed(2);
    // Flat's real amount lives in Discount Amount (readModalPassenger reads
    // it from there for Flat) - seed it here so the recalcModalTotal() call
    // below doesn't derive the discount from a still-blank Amount field.
    if (p.disc_type === "Flat") document.getElementById("modal-disc-computed").value = fmtN(p.disc_value);
    document.getElementById("modal-tds-per").value = Number(p.tds_per).toFixed(2);
    // PG Charges/PG Charges % are not seeded here - both are non-editable
    // and get recomputed fresh (against whatever PG Master snapshot was
    // effective as of this ticket's own Invoice Date) by the
    // recalcModalTotal() call below, via updatePgCharges().
    document.getElementById("modal-markup").value = fmtN(p.markup); document.getElementById("modal-addl-markup").value = fmtN(p.addl_markup);
    document.getElementById("modal-ssr-markup").value = fmtN(p.ssr_markup || 0);
    document.getElementById("modal-service-fee").value = fmtN(p.service_fee); document.getElementById("modal-addl-service-fee").value = fmtN(p.addl_service_fee);
    document.getElementById("modal-ssr-service-fee").value = fmtN(p.ssr_service_fee || 0);
    document.getElementById("modal-gst-pct").value = Number(p.gst_pct).toFixed(2);
    document.getElementById("modal-supplier").value = p.supplier_name || "";
    document.getElementById("modal-office-id").value = p.office_id || "";
    document.getElementById("modal-fop").value = p.fop || "";
    updateCardNumberField(p.card_number || "");
    document.getElementById("modal-supp-comm-on").value = p.supp_comm_on || "";
    document.getElementById("modal-supp-comm-type").value = p.supp_comm_type || "";
    document.getElementById("modal-supp-comm-value").value = Number(p.supp_comm_value || 0).toFixed(2);
    document.getElementById("modal-supp-tds-per").value = Number(p.supp_tds_per || 0).toFixed(2);
    document.getElementById("modal-supp-markup").value = fmtN(p.supp_markup || 0);
    document.getElementById("modal-supp-addl-markup").value = fmtN(p.supp_addl_markup || 0);
    document.getElementById("modal-supp-service-fee").value = fmtN(p.supp_service_fee || 0);
    document.getElementById("modal-supp-addl-service-fee").value = fmtN(p.supp_addl_service_fee || 0);
    document.getElementById("modal-supp-gst-pct").value = Number(p.supp_gst_pct || 0).toFixed(2);
    document.getElementById("modal-agent-penalty").value = fmtN(p.agent_penalty || 0);
    document.getElementById("modal-reschedule-penalty").value = fmtN(p.reschedule_penalty || 0);
    // Whatever's already saved counts as a deliberate choice - don't let a
    // later Client Accounting edit silently clobber it. Only a brand-new
    // (blank) passenger starts in "follow Client Accounting" mode.
    suppCommOverridden = !!(p.supp_comm_on || p.supp_comm_type || p.supp_comm_value);
    updateDiscValueLabel();
    updateSuppDiscValueLabel();
    recalcModalTotal();
    recalcSuppTotal();
  }
  // Supplier Commission defaults to mirroring whatever's picked in Client
  // Accounting (On/Type/Value/TDS %) - but the moment the user touches a
  // Supplier Commission field directly, that link breaks for the rest of
  // this passenger's session so their manual entry isn't overwritten.
  let suppCommOverridden = false;
  const CLIENT_DISC_DRIVER_IDS = new Set(["modal-disc-on", "modal-disc-type", "modal-disc-value", "modal-tds-per"]);
  function syncSuppFromClient() {
    if (suppCommOverridden) return;
    document.getElementById("modal-supp-comm-on").value = document.getElementById("modal-disc-on").value;
    document.getElementById("modal-supp-comm-type").value = document.getElementById("modal-disc-type").value;
    document.getElementById("modal-supp-comm-value").value = document.getElementById("modal-disc-value").value;
    document.getElementById("modal-supp-tds-per").value = document.getElementById("modal-tds-per").value;
    updateSuppDiscValueLabel();
    recalcSuppTotal();
  }
  // Live-updates the bottom Summary (Purchase Cost / Sales Cost / Earnings)
  // while editing an EXISTING passenger's fare in the modal - previously it
  // only refreshed once Save & Apply closed the modal, so the Summary kept
  // showing that passenger's pre-edit amounts while you were still typing.
  // No-op for a brand-new (not-yet-saved) passenger - there's no row in
  // `passengers` yet for one of those to update.
  function liveSyncSummary() {
    if (editingIndex === null) return;
    passengers[editingIndex] = readModalPassenger();
    recalcSummary();
    maybeRefreshJvPreview();
  }
  document.querySelectorAll(".modal-calc").forEach((el) => {
    el.addEventListener("input", () => {
      recalcModalTotal(); recalcSuppTotal(); liveSyncSummary();
      if (el.id.startsWith("modal-supp-")) suppCommOverridden = true;
      else if (CLIENT_DISC_DRIVER_IDS.has(el.id)) syncSuppFromClient();
    });
    el.addEventListener("change", () => {
      updateDiscValueLabel(); updateSuppDiscValueLabel(); recalcModalTotal(); recalcSuppTotal(); liveSyncSummary();
      if (el.id.startsWith("modal-supp-")) suppCommOverridden = true;
      else if (CLIENT_DISC_DRIVER_IDS.has(el.id)) syncSuppFromClient();
    });
  });
  // Discount Amount is directly editable: Flat mode reads disc_value
  // straight from this field (see readModalPassenger), so the Discount %
  // box just stays at 0 rather than echoing the flat amount. Percentage
  // mode keeps auto-filling Amount from % (via recalcModalTotal above),
  // but typing directly into Amount back-solves the equivalent %.
  document.getElementById("modal-disc-computed").addEventListener("input", (e) => {
    const type = document.getElementById("modal-disc-type").value;
    const amount = parseFloat(e.target.value) || 0;
    if (type === "Percentage") {
      const discBase = computeDiscBase(readModalPassenger());
      document.getElementById("modal-disc-value").value = discBase > 0 ? ((amount / discBase) * 100).toFixed(4) : "0";
    }
    recalcModalTotal({ skipDiscAmount: true });
    syncSuppFromClient();
    liveSyncSummary();
  });
  // Same directly-editable-Amount behavior, mirrored for Supplier Commission.
  document.getElementById("modal-supp-comm-computed").addEventListener("input", (e) => {
    suppCommOverridden = true;
    const type = document.getElementById("modal-supp-comm-type").value;
    const amount = parseFloat(e.target.value) || 0;
    if (type === "Flat") {
      document.getElementById("modal-supp-comm-value").value = e.target.value;
    } else if (type === "Percentage") {
      const discBase = computeDiscBase({ ...readModalPassenger(), disc_on: document.getElementById("modal-supp-comm-on").value });
      document.getElementById("modal-supp-comm-value").value = discBase > 0 ? ((amount / discBase) * 100).toFixed(4) : "0";
    }
    recalcSuppTotal({ skipComputed: true });
    liveSyncSummary();
  });

  // ============================================================
  // Sector chips - multi-city segments on one passenger line, each
  // captured via the Add Sector popup (From/To/Travel Date/Flight No/
  // Cabin/Class/Fare Type). Stored on the passenger as comma-joined
  // strings (sector: "BOM-DXB,DXB-JFK", flight_no/cabin/travel_class/
  // fare_type the same, one value per sector in the same order).
  // travel_date collapses to a single value when every sector shares the
  // same date, comma-joined only when they actually differ.
  // ============================================================
  // Read-only sector detail rows shown under Card Number - ALL sectors
  // share one card (not one card per sector), each sector as its own row
  // inside it: the sector label + its Flight No/Class/Travel Date as
  // disabled text boxes (same data as the Add Sector popup, just surfaced
  // here so it's visible without reopening it).
  function renderSectorDetails() {
    const box = document.getElementById("modal-sector-details");
    if (rescheduleMode) {
      // This card's own height already caps at 112px (max-height) - always
      // reserving exactly that in Reschedule mode (visible or not) keeps
      // the whole modal's height identical whether the active tab's
      // passenger has sectors yet or not, instead of the modal visibly
      // shifting every time Parent/Reschedule gets switched.
      box.style.display = "flex";
      box.style.minHeight = "112px";
      box.style.visibility = modalSectors.length ? "visible" : "hidden";
    } else {
      box.style.display = modalSectors.length ? "flex" : "none";
      box.style.minHeight = "";
      box.style.visibility = "visible";
    }
    box.innerHTML = modalSectors.map((s, i) => `
      <div class="dom-sector-detail-row" data-idx="${i}" style="cursor:pointer;" title="${viewMode ? "Click to view this sector" : "Click to view/edit this sector"}">
        <span class="dom-sector-detail-head">${s.from}-${s.to}</span>
        <input class="dom-input dsd-flight" value="${s.flightNo || ""}" disabled placeholder="Flight No" />
        <input class="dom-input dsd-class" value="${s.cls || ""}" disabled placeholder="Class" />
        <input class="dom-input dsd-date" value="${s.travelDate || ""}" disabled placeholder="Travel Date" />
      </div>`).join("");
    box.querySelectorAll(".dom-sector-detail-row").forEach((row) => {
      row.addEventListener("click", () => { openSectorModal(Number(row.dataset.idx)); });
    });
  }
  function renderSectorChips() {
    const box = document.getElementById("modal-sector-chips");
    renderSectorDetails();
    if (modalSectors.length === 0) {
      box.innerHTML = `<span class="dom-chip-placeholder" id="modal-sector-placeholder">Click here to add sector</span>`;
      return;
    }
    box.innerHTML = modalSectors.map((s, i) => `
      <span class="dom-sector-chip" data-idx="${i}" style="cursor:pointer;" title="${viewMode ? "Click to view this sector" : "Click to view/edit this sector"}">
        <span class="dom-sector-chip-label">${s.from}-${s.to}</span>
        ${viewMode ? "" : `<button type="button" class="dom-chip-remove" data-idx="${i}" title="Remove">&times;</button>`}
      </span>`).join("");
    box.querySelectorAll(".dom-sector-chip").forEach((chip) => {
      chip.addEventListener("click", (e) => {
        if (e.target.classList.contains("dom-chip-remove")) return;
        openSectorModal(Number(chip.dataset.idx));
      });
    });
    box.querySelectorAll(".dom-chip-remove").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        modalSectors.splice(Number(btn.dataset.idx), 1);
        renderSectorChips();
        autofillSupplierCommission();
      });
    });
  }
  function openSectorModal(index) {
    editingSectorIndex = index;
    const s = index === null
      ? { from: "", to: "", airlineCode: "", airlineName: "", travelDate: "", flightNo: "", cabin: "", cls: "", fareType: "" }
      : modalSectors[index];
    document.getElementById("sector-from").value = s.from;
    document.getElementById("sector-to").value = s.to;
    document.getElementById("sector-airline-code").value = s.airlineCode || "";
    document.getElementById("sector-airline-name").value = s.airlineName || "";
    setDateGroupValue(document.getElementById("sector-travel-date"), s.travelDate);
    document.getElementById("sector-flight-no").value = s.flightNo;
    document.getElementById("sector-cabin").value = s.cabin;
    document.getElementById("sector-class").value = s.cls;
    document.getElementById("sector-fare-type").value = s.fareType;

    // Read-only when the ticket itself is being viewed, not edited -
    // clicking a sector chip/detail row here should just let the user see
    // its full breakdown, never let them change it outside Edit mode.
    ["sector-from", "sector-to", "sector-airline-code", "sector-airline-name", "sector-flight-no", "sector-class", "sector-cabin", "sector-fare-type"]
      .forEach((id) => { document.getElementById(id).disabled = viewMode; });
    document.getElementById("sector-travel-date").querySelector(".dg-native").disabled = viewMode;
    document.getElementById("sector-modal-title").textContent = viewMode ? "Sector Details" : (index === null ? "Add Sector" : "Edit Sector");
    document.getElementById("sector-save-btn").style.display = viewMode ? "none" : "";
    document.getElementById("sector-cancel-btn").textContent = viewMode ? "Close" : "Cancel";

    sectorModal.classList.add("open");
    if (!viewMode) setTimeout(() => document.getElementById("sector-from").focus(), 50);
  }
  function closeSectorModal() { sectorModal.classList.remove("open"); editingSectorIndex = null; }
  document.getElementById("modal-sector-box").addEventListener("click", (e) => {
    if (viewMode) return;
    if (e.target.closest(".dom-sector-chip") || e.target.closest("#modal-sector-add-btn")) return;
    openSectorModal(null);
  });
  document.getElementById("modal-sector-add-btn").addEventListener("click", () => { if (!viewMode) openSectorModal(null); });
  document.getElementById("sector-close-x-btn").addEventListener("click", closeSectorModal);
  document.getElementById("sector-cancel-btn").addEventListener("click", closeSectorModal);
  document.getElementById("sector-save-btn").addEventListener("click", () => {
    const from = document.getElementById("sector-from").value.trim().toUpperCase();
    const to = document.getElementById("sector-to").value.trim().toUpperCase();
    if (!from || !to) { voyagerAlert("Sector From and To are both required."); return; }
    const entry = {
      from, to,
      airlineCode: document.getElementById("sector-airline-code").value.trim().toUpperCase(),
      airlineName: document.getElementById("sector-airline-name").value.trim(),
      travelDate: getDateGroupValue(document.getElementById("sector-travel-date")),
      flightNo: document.getElementById("sector-flight-no").value.trim(),
      cabin: document.getElementById("sector-cabin").value,
      cls: document.getElementById("sector-class").value.trim(),
      fareType: document.getElementById("sector-fare-type").value,
    };
    if (editingSectorIndex === null) modalSectors.push(entry);
    else modalSectors[editingSectorIndex] = entry;
    renderSectorChips();
    closeSectorModal();
    autofillSupplierCommission();
  });
  function joinSectorField(key) {
    return modalSectors.map((s) => s[key] || "").join(",");
  }
  function sectorTravelDateField() {
    const dates = modalSectors.map((s) => s.travelDate || "");
    const unique = [...new Set(dates.filter((d) => d))];
    return unique.length <= 1 ? (unique[0] || "") : dates.join(",");
  }
  function parseSectorsFromPassenger(p) {
    const pairs = (p.sector || "").split(",").map((s) => s.trim()).filter(Boolean);
    const airlineCodes = (p.airline_code || "").split(",");
    const airlineNames = (p.airline_name || "").split(",");
    const flightNos = (p.flight_no || "").split(",");
    const cabins = (p.cabin || "").split(",");
    const classes = (p.travel_class || "").split(",");
    const fareTypes = (p.fare_type || "").split(",");
    const dates = (p.travel_date || "").split(",").map((d) => d.trim());
    modalSectors = pairs.map((pair, i) => {
      const [from, to] = pair.split("-");
      return {
        from: (from || "").trim(), to: (to || "").trim(),
        airlineCode: (airlineCodes[i] || "").trim(), airlineName: (airlineNames[i] || "").trim(),
        flightNo: (flightNos[i] || "").trim(), cabin: (cabins[i] || "").trim(),
        cls: (classes[i] || "").trim(), fareType: (fareTypes[i] || "").trim(),
        travelDate: (dates.length === 1 ? dates[0] : (dates[i] || "")).trim(),
      };
    });
    renderSectorChips();
  }

  function openFareModal(index) {
    editingIndex = index;
    const isNew = index === null;
    document.getElementById("modal-pax-display").textContent = isNew ? `New Passenger #${passengers.length + 1}` : `Passenger #${index + 1}`;
    // Blanket enable/disable runs BEFORE writeModalPassenger, not after -
    // writeModalPassenger's own updateDiscValueLabel/updateSuppDiscValueLabel/
    // updateCardNumberField calls set the correct per-field disabled state
    // (e.g. Discount % only enabled when Discount Type = Percentage) as
    // their last step, so they need to run last and win, not get wiped back
    // to "everything enabled" by this blanket pass.
    document.querySelectorAll("#fare-breakdown-modal input, #fare-breakdown-modal select").forEach((el) => (el.disabled = viewMode));
    writeModalPassenger(isNew ? blankPassenger() : passengers[index]);
    document.getElementById("modal-save-btn").style.display = viewMode ? "none" : "";
    document.getElementById("modal-sector-add-btn").style.display = viewMode ? "none" : "";
    // Reschedule's tab bar replaces the plain titlebar entirely (it carries
    // its own close X) rather than sitting awkwardly under it.
    document.querySelector("#fare-breakdown-modal .dom-modal-titlebar").style.display = rescheduleMode ? "none" : "";
    document.getElementById("reschedule-tab-bar").style.display = rescheduleMode ? "" : "none";
    if (rescheduleMode) applyRescheduleTab("reschedule");
    fareModal.classList.add("open");
  }
  // Moves the REAL Discount %/Discount Amount/TDS %/TDS Amount/Taxable
  // Amount/GST Amount elements (never duplicated - same ids, same
  // listeners) between the default layout (Parent PNR Details + every
  // normal, non-reschedule ticket) and the Reschedule tab's own merged-row
  // layout. Since only the DOM parent changes, readModalPassenger()/
  // writeModalPassenger()/recalcModalTotal() etc. never need to know or
  // care which layout is currently showing.
  function layoutAcctFieldsForReschedule(isResched) {
    const discPctField = document.getElementById("modal-disc-value-field");
    const discAmt = document.getElementById("modal-disc-computed");
    const tdsPct = document.getElementById("modal-tds-per");
    const tdsAmt = document.getElementById("modal-tds-computed");
    const taxable = document.getElementById("modal-taxable-amount");
    const gstAmt = document.getElementById("modal-gst-computed");
    const gstBtn = document.getElementById("modal-gst-detail-btn");
    const suppCommPctField = document.getElementById("modal-supp-comm-value-field");
    const suppCommAmt = document.getElementById("modal-supp-comm-computed");
    const suppTdsPct = document.getElementById("modal-supp-tds-per");
    const suppTdsAmt = document.getElementById("modal-supp-tds-computed");
    const suppGstPct = document.getElementById("modal-supp-gst-pct");
    const suppGstAmt = document.getElementById("modal-supp-gst-computed");
    // In the default layout these are sized by their own grid column
    // (64px/70px/90px/1fr etc, via CSS on the row) - the Reschedule row is
    // a plain flexbox instead (like PG Charges' own dual box), which gives
    // every child its natural/auto width unless told otherwise, so the %
    // box and the Amount box need explicit sizing here or they render
    // as one indistinguishable blob instead of two visible boxes.
    if (isResched) {
      // % box itself is sized/styled by the .acct-pct-box wrapper CSS
      // (fits "0.00%") - only the Amount box needs explicit sizing here so
      // it fills whatever space that frees up.
      // flex:1 alone isn't quite enough for true pixel-parity between an
      // <input> (Commission/Discount Amount, editable) and a <div> (TDS/
      // GST Amount, computed/readonly) sharing the same flex row - each
      // element type has its own intrinsic sizing quirks, so width:100% +
      // border-box is set explicitly on all of them to force identical
      // actual widths regardless of tag/content.
      [discAmt, tdsAmt, suppCommAmt, suppTdsAmt, suppGstAmt].forEach((el) => {
        el.style.flex = "1"; el.style.minWidth = "0"; el.style.width = "100%";
        el.style.boxSizing = "border-box"; el.style.textAlign = "right";
      });
      document.getElementById("resched-disc-pct-slot").append(discPctField);
      document.getElementById("resched-disc-amt-slot").append(discAmt);
      document.getElementById("resched-tds-pct-slot").append(tdsPct);
      document.getElementById("resched-tds-amt-slot").append(tdsAmt);
      document.getElementById("resched-taxable-slot").append(taxable);
      document.getElementById("resched-gst-slot").append(gstAmt, gstBtn);
      document.getElementById("resched-supp-comm-pct-slot").append(suppCommPctField);
      document.getElementById("resched-supp-comm-amt-slot").append(suppCommAmt);
      document.getElementById("resched-supp-tds-pct-slot").append(suppTdsPct);
      document.getElementById("resched-supp-tds-amt-slot").append(suppTdsAmt);
      document.getElementById("resched-supp-gst-pct-slot").append(suppGstPct);
      document.getElementById("resched-supp-gst-amt-slot").append(suppGstAmt);
      document.getElementById("acct-default-disc-row").style.display = "none";
      document.getElementById("acct-default-taxable-row").style.display = "none";
      document.getElementById("acct-default-tds-row").style.display = "none";
      document.getElementById("acct-default-supp-comm-row").style.display = "none";
      document.getElementById("acct-default-supp-tds-row").style.display = "none";
      document.getElementById("acct-default-supp-gst-row").style.display = "none";
      document.getElementById("acct-resched-disc-row").style.display = "";
      document.getElementById("acct-resched-agent-row").style.display = "";
      document.getElementById("acct-resched-supp-row").style.display = "";
      document.getElementById("acct-resched-supp-gst-row").style.display = "";
    } else {
      [discAmt, tdsAmt, suppCommAmt, suppTdsAmt, suppGstAmt].forEach((el) => {
        el.style.flex = ""; el.style.minWidth = ""; el.style.width = "";
        el.style.boxSizing = ""; el.style.textAlign = "";
      });
      document.getElementById("default-disc-pct-slot").append(discPctField);
      document.getElementById("default-disc-amt-slot").append(discAmt);
      document.getElementById("default-tdspct-slot").append(tdsPct);
      document.getElementById("default-tdsamt-slot").append(tdsAmt);
      document.getElementById("default-taxable-slot").append(taxable);
      document.getElementById("default-gst-slot").append(gstAmt, gstBtn);
      document.getElementById("default-supp-comm-pct-slot").append(suppCommPctField);
      document.getElementById("default-supp-comm-amt-slot").append(suppCommAmt);
      document.getElementById("default-supp-tdspct-slot").append(suppTdsPct);
      document.getElementById("default-supp-tdsamt-slot").append(suppTdsAmt);
      document.getElementById("default-supp-gstpct-slot").append(suppGstPct);
      document.getElementById("default-supp-gstamt-slot").append(suppGstAmt);
      document.getElementById("acct-default-disc-row").style.display = "";
      document.getElementById("acct-default-taxable-row").style.display = "";
      document.getElementById("acct-default-tds-row").style.display = "";
      document.getElementById("acct-default-supp-comm-row").style.display = "";
      document.getElementById("acct-default-supp-tds-row").style.display = "";
      document.getElementById("acct-default-supp-gst-row").style.display = "";
      document.getElementById("acct-resched-disc-row").style.display = "none";
      document.getElementById("acct-resched-agent-row").style.display = "none";
      document.getElementById("acct-resched-supp-row").style.display = "none";
      document.getElementById("acct-resched-supp-gst-row").style.display = "none";
    }
  }
  // Switches the fare modal between the frozen original ticket line
  // (Parent) and this brand new ticket's own blank/editable data
  // (Reschedule) - covers the whole modal, both columns.
  function applyRescheduleTab(tab) {
    modalRescheduleTab = tab;
    layoutAcctFieldsForReschedule(tab === "reschedule");
    const isParent = tab === "parent";
    // Reschedule PNR Details is only actually editable when viewMode is
    // off (a saved reschedule ticket opens read-only first, same as any
    // other saved ticket, until Edit is clicked) - Parent PNR Details
    // stays frozen/read-only regardless, same as always.
    const readOnly = isParent || viewMode;
    document.querySelectorAll("#fare-breakdown-modal input, #fare-breakdown-modal select").forEach((el) => (el.disabled = readOnly));
    writeModalPassenger(isParent ? rescheduleParentPassenger : rescheduleEditPassenger);
    // Supplier Penalty (Base Fare & Tax Components card) is a
    // RescheduleAirlineTicketLines-only column - TicketLines has no such
    // field, so it never shows on Parent PNR Details.
    document.getElementById("modal-fare-supplier-penalty-field").style.display = isParent ? "none" : "";
    document.getElementById("modal-sector-add-btn").style.display = readOnly ? "none" : "";
    // visibility (not display) - keeps their row's height reserved on the
    // Parent tab too, so switching tabs doesn't shrink/jump the modal.
    document.getElementById("modal-cancel-btn").style.visibility = readOnly ? "hidden" : "";
    document.getElementById("modal-save-btn").style.visibility = readOnly ? "hidden" : "";
    document.querySelectorAll(".reschedule-tab-btn").forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === tab));
  }
  document.querySelectorAll(".reschedule-tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => applyRescheduleTab(btn.dataset.tab));
  });
  function closeFareModal() { fareModal.classList.remove("open"); }
  document.getElementById("modal-close-x-btn").addEventListener("click", closeFareModal);
  document.getElementById("reschedule-tab-close-btn").addEventListener("click", closeFareModal);
  document.getElementById("modal-cancel-btn").addEventListener("click", closeFareModal);

  // Proceed is gated on the booking header being complete - these fields
  // are all needed before a passenger/fare can meaningfully be added
  // (Customer for billing, Payment Mode for the FOP/PG tabs, etc).
  const PROCEED_REQUIRED_FIELDS = [
    ["invoice_number", "Invoice Number"], ["invoice_type", "Invoice Type"], ["booking_type", "Booking Type"],
    ["customer", "Customer Name"], ["travel_type", "Travel Type"], ["user_name", "User Name"],
    ["booking_reference", "Booking Reference"], ["payment_mode", "Payment Mode"],
  ];
  function validateHeaderRequiredFields() {
    const missingEntries = PROCEED_REQUIRED_FIELDS.filter(([id]) => !document.getElementById(id).value.trim());
    const missing = missingEntries.map(([, label]) => label);
    const bookingRefDateMissing = !getDateGroupValue(document.getElementById("booking_ref_date"));
    if (bookingRefDateMissing) missing.push("Booking Ref Date");
    if (missing.length) {
      // Focus the first missing field from PROCEED_REQUIRED_FIELDS (in the
      // order listed there), falling back to Booking Ref Date only if
      // every other required field is already filled.
      const firstMissingId = missingEntries.length ? missingEntries[0][0] : null;
      const focusEl = firstMissingId
        ? document.getElementById(firstMissingId)
        : document.querySelector("#booking_ref_date .dg-native");
      voyagerAlert(`Please fill the following required field(s) before proceeding: ${missing.join(", ")}.`, { focusEl });
      return false;
    }
    return true;
  }
  document.getElementById("proceed-btn").addEventListener("click", () => {
    if (!validateHeaderRequiredFields()) return;
    openFareModal(null);
  });
  const MAX_PASSENGERS = 9;
  document.getElementById("add-line-btn").addEventListener("click", () => {
    if (passengers.length >= MAX_PASSENGERS) { voyagerAlert(`Maximum ${MAX_PASSENGERS} passengers allowed per ticket.`); return; }
    openFareModal(null);
  });
  document.getElementById("add-line-btn-bot").addEventListener("click", () => {
    if (passengers.length >= MAX_PASSENGERS) { voyagerAlert(`Maximum ${MAX_PASSENGERS} passengers allowed per ticket.`); return; }
    openFareModal(null);
  });

  document.getElementById("modal-save-btn").addEventListener("click", () => {
    const p = readModalPassenger();
    if (!p.ticket_no) { voyagerAlert("Ticket No. is required."); return; }
    if (p.ticket_no.length < 10) { voyagerAlert("Ticket No. must be at least 10 characters."); return; }
    if (!p.passenger_name) { voyagerAlert("Pax Name is required."); return; }
    const dupInList = passengers.some((x, i) => x.ticket_no === p.ticket_no && i !== editingIndex);
    const dupExisting = existingTickets.some((t) => t.ticket_no === p.ticket_no && String(t.id) !== String(editId));
    if (dupInList || dupExisting) { voyagerAlert("This Ticket Number is already used."); return; }

    if (editingIndex === null) {
      if (passengers.length >= MAX_PASSENGERS) { voyagerAlert(`Maximum ${MAX_PASSENGERS} passengers allowed per ticket.`); return; }
      passengers.push(p);
    } else {
      passengers[editingIndex] = p;
    }
    // Remembers what was just applied so the Reschedule tab shows these
    // same values (not reset back to blank) next time this modal reopens -
    // Save & Apply is only reachable from that tab anyway (Parent hides it).
    if (rescheduleMode) rescheduleEditPassenger = p;
    closeFareModal();
    renderPaxTable();
  });

  // ============================================================
  // Register table - rendered from the `passengers` array
  // ============================================================
  // Adding a passenger from the inline "+" row - validates the booking
  // header first only when this is the very first passenger (same gate the
  // old standalone "Proceed" button used to apply).
  function addPaxFromRow() {
    if (passengers.length === 0 && !validateHeaderRequiredFields()) return;
    if (passengers.length >= MAX_PASSENGERS) { voyagerAlert(`Maximum ${MAX_PASSENGERS} passengers allowed per ticket.`); return; }
    openFareModal(null);
  }

  function renderPaxTable() {
    const ccy = document.getElementById("currency").textContent || "INR";
    const atCap = passengers.length >= MAX_PASSENGERS;
    // Reschedule locks the register to exactly the one carried-over
    // passenger - no Remove, no adding more, so the whole Action column
    // is pointless and hidden entirely.
    const actionTh = document.getElementById("pax-action-th");
    if (actionTh) actionTh.style.display = rescheduleMode ? "none" : "";

    const rowsHtml = passengers.map((p, i) => {
      const r = computeFareLine(p);
      const rs = computeSuppLine(p);
      // Other Taxes = everything besides Basic/YQ/K3/SSR (those already
      // have their own columns) - YR + Tax & Others, both Supplier and
      // Customer's Markup/Addl Markup/Service Fee/Addl Service Fee/GST,
      // Customer's SSR Markup/SSR Service Fee, Customer TDS minus Customer
      // Discount, plus Supplier Penalty + Reschedule Penalty + Agent Penalty.
      const penalties = (p.supplier_penalty || 0) + (p.reschedule_penalty || 0) + (p.agent_penalty || 0);
      const allTaxes = p.yr + p.tax_others
        + (p.supp_markup || 0) + (p.supp_addl_markup || 0) + (p.supp_service_fee || 0) + (p.supp_addl_service_fee || 0) + rs.gst
        + p.markup + p.addl_markup + (p.ssr_markup || 0) + p.service_fee + p.addl_service_fee + (p.ssr_service_fee || 0)
        + r.gst - r.discount + r.tds + penalties;
      // Total = the fare-line total plus those same 3 penalties, so
      // Basic+YQ+K3+SSR+Other Taxes still always equals this Total exactly.
      const lineTotal = r.total + penalties;
      const z = (v) => fmtN(v);
      return `<tr class="pax-row" data-idx="${i}" title="${viewMode ? "Double-click to view" : "Double-click to edit"}">
        <td style="text-align:center;">${i + 1}</td><td>${p.ticket_no}</td><td>${p.airline_name || p.airline_code || "-"}</td>
        <td>${p.card_number || "-"}</td>
        <td>${p.passenger_name} <span style="color:#94A3B8;">(${p.pax_type || "-"})</span></td>
        <td class="num">${z(p.basic_fare)}</td><td class="num">${z(p.yq)}</td><td class="num">${z(p.k3_tax)}</td>
        <td class="num">${z(p.seat + p.meal + p.baggage + p.other_ssr)}</td>
        <td class="num">${z(allTaxes)}</td><td class="num" style="font-weight:700;">${z(lineTotal)}</td>
        ${rescheduleMode ? "" : `<td style="text-align:center;">
          ${viewMode ? "" : `<button type="button" class="pax-circle-btn pax-circle-remove pax-remove-btn" data-idx="${i}" title="Remove passenger">REMOVE</button>`}
        </td>`}
      </tr>`;
    }).join("");

    // Trailing empty row - always present (unless in view mode, reschedule
    // mode, or at the 9-passenger cap) with a round "+" to add the next
    // passenger. This is the only place the "+" appears; once a passenger
    // is added the row it came from turns into a normal data row above
    // (its "+" is gone, only "-" remains) and this empty row shifts down
    // for the next one.
    const addRowHtml = (!viewMode && !rescheduleMode && !atCap) ? `<tr class="pax-row pax-add-row">
        <td colspan="11" style="text-align:center; padding:14px; font-size:11.5px;">
          ${passengers.length === 0
            ? 'No passengers added yet. Fill booking details above, then click <strong style="color:#3B6DB5;">ADD</strong> to add a passenger.'
            : "Click ADD to add another passenger."}
        </td>
        <td style="text-align:center;">
          <button type="button" class="pax-circle-btn pax-circle-add" id="pax-add-row-btn" title="Add passenger">ADD</button>
        </td>
      </tr>` : "";

    linesBody.innerHTML = rowsHtml + addRowHtml || `<tr id="no-pax-row"><td colspan="12" style="text-align:center; padding:18px; color:#64748B; font-size:11.5px;">No passengers to show.</td></tr>`;

    // Double-click to view/edit a row's passenger & fare details works in
    // both view mode (read-only) and edit mode.
    document.querySelectorAll(".pax-row[data-idx]").forEach((row) => {
      row.addEventListener("dblclick", () => openFareModal(Number(row.dataset.idx)));
    });
    if (!viewMode) {
      const addBtn = document.getElementById("pax-add-row-btn");
      if (addBtn) addBtn.addEventListener("click", addPaxFromRow);
      document.querySelectorAll(".pax-remove-btn").forEach((btn) => btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const idx = Number(btn.dataset.idx);
        const ok = await voyagerConfirm(
          `Remove passenger "${passengers[idx].passenger_name}" from this ticket?`,
          { title: "Remove Passenger", confirmLabel: "Delete", icon: "delete" }
        );
        if (!ok) return;
        passengers.splice(idx, 1);
        renderPaxTable();
      }));
    }

    // The old standalone Proceed/Add Passenger buttons are superseded by
    // the inline "+" row above.
    document.getElementById("proceed-btn").style.display = "none";
    document.getElementById("add-line-btn").style.display = "none";
    document.getElementById("add-line-btn-bot").style.display = "none";

    recalcSummary();
    maybeRefreshJvPreview();
  }

  function recalcSummary() {
    let basic = 0, taxes = 0, ssr = 0, discount = 0, tds = 0, markup = 0, serviceFee = 0, gst = 0, total = 0;
    let suppCommission = 0, suppTds = 0, suppMarkup = 0, suppServiceFee = 0, suppGst = 0;
    let agentPenalty = 0, reschedulePenalty = 0, supplierPenaltyField = 0;
    passengers.forEach((p) => {
      const r = computeFareLine(p);
      const rs = computeSuppLine(p);
      basic += p.basic_fare;
      taxes += p.yq + p.yr + p.k3_tax + p.tax_others;
      ssr += p.seat + p.meal + p.baggage + p.other_ssr;
      discount += r.discount; tds += r.tds;
      markup += p.markup + p.addl_markup + (p.ssr_markup || 0);
      serviceFee += p.service_fee + p.addl_service_fee + (p.ssr_service_fee || 0); gst += r.gst; total += r.total;
      suppCommission += rs.commission; suppTds += rs.tds;
      suppMarkup += (p.supp_markup || 0) + (p.supp_addl_markup || 0);
      suppServiceFee += (p.supp_service_fee || 0) + (p.supp_addl_service_fee || 0);
      suppGst += rs.gst;
      agentPenalty += (p.agent_penalty || 0); reschedulePenalty += (p.reschedule_penalty || 0);
      // p.supplier_penalty is the Base Fare & Tax Components card's own
      // field (distinct from reschedule_penalty above, the Supplier
      // accounting card's field).
      supplierPenaltyField += (p.supplier_penalty || 0);
    });
    const purchaseTotal = basic + taxes + ssr - suppCommission + suppTds + suppMarkup + suppServiceFee + suppGst;
    // Purchase/Sales Cost's Other Taxes/Total columns fold in the
    // penalties (per the project owner's explicit formula); Earnings
    // below stays on the un-penalized purchaseTotal/total, same as always.
    const pcTaxesDisplay = taxes + supplierPenaltyField;
    const scTaxesDisplay = taxes + supplierPenaltyField;
    const pcTotalDisplay = purchaseTotal + reschedulePenalty + supplierPenaltyField;
    // Sales Cost Total = the per-line total (already folds in every
    // Supplier AND Customer fare component - see computeFareLine's own
    // `total`) plus Agent Penalty + Reschedule Penalty + Supplier Penalty.
    const scTotalDisplay = total + agentPenalty + reschedulePenalty + supplierPenaltyField;
    const z = (v) => fmtN(v);

    document.getElementById("pc-basic").textContent = z(basic);
    document.getElementById("pc-taxes").textContent = z(pcTaxesDisplay);
    document.getElementById("pc-ssr").textContent = z(ssr);
    document.getElementById("pc-disc").textContent = z(suppCommission);
    document.getElementById("pc-tds").textContent = z(suppTds);
    // Purchase Cost's Markup column additionally folds in Reschedule Penalty.
    document.getElementById("pc-markup").textContent = z(suppMarkup + reschedulePenalty);
    document.getElementById("pc-sfee").textContent = z(suppServiceFee);
    document.getElementById("pc-gst").textContent = z(suppGst);
    document.getElementById("pc-total").textContent = z(pcTotalDisplay);

    document.getElementById("sc-basic").textContent = z(basic);
    document.getElementById("sc-taxes").textContent = z(scTaxesDisplay);
    document.getElementById("sc-ssr").textContent = z(ssr);
    document.getElementById("sc-disc").textContent = z(discount);
    document.getElementById("sc-tds").textContent = z(tds);
    // Sales Cost's Markup/Service Fee/GST Amount columns additionally fold
    // in the Purchase Cost side's own Markup/Service Fee/GST (plus Agent
    // Penalty on Markup).
    document.getElementById("sc-markup").textContent = z(markup + suppMarkup + reschedulePenalty + agentPenalty);
    document.getElementById("sc-sfee").textContent = z(serviceFee + suppServiceFee);
    document.getElementById("sc-gst").textContent = z(gst + suppGst);
    document.getElementById("sc-total").textContent = z(scTotalDisplay);

    // Earnings = Sales Cost Total - Purchase Cost Total - Sales Cost GST
    // Amount - Sales Cost TDS Amount + Purchase Cost TDS Amount.
    const earnings = total - purchaseTotal - gst - tds + suppTds;
    document.getElementById("invoice_total").textContent = z(earnings);
  }
  document.getElementById("refresh-total-btn").addEventListener("click", recalcSummary);

  // Builds the exact same body shape tickets/create/ and the draft JV
  // preview both expect - travel_date is plain text now (TicketLine.travel_date),
  // not a real date column, since multi-city sectors can carry different
  // dates, comma-joined.
  function buildTicketPayload() {
    // Reschedule saves post to reschedule-tickets/create-or-update instead
    // (see the submit handler) - that endpoint needs to know which
    // original ticket line each new line was rescheduled from, since it
    // deliberately doesn't duplicate Parent PNR Details' own columns. A
    // saved reschedule's passenger already carries its own
    // original_ticket_line_id (from enterSavedRescheduleMode); a
    // brand-new one falls back to the URL's reschedule_line_id.
    const lines = passengers.map((p) => ({
      ...p,
      ...(rescheduleMode ? { original_ticket_line_id: p.original_ticket_line_id || Number(rescheduleLineId) } : {}),
    }));
    return {
      company_id: activeCompanyId,
      ...(rescheduleMode ? { original_ticket_id: Number(rescheduleTicketId) } : {}),
      invoice_number: document.getElementById("invoice_number").value.trim(),
      invoice_date: toISOFromDDMMYYYY(getDateGroupValue(document.getElementById("invoice_date"))),
      invoice_type: document.getElementById("invoice_type").value,
      booking_mode: document.getElementById("booking_mode").value,
      booking_type: document.getElementById("booking_type").value,
      booking_status: document.getElementById("booking_status").value,
      customer_name: document.getElementById("customer").value,
      travel_type: document.getElementById("travel_type").value,
      user_name: document.getElementById("user_name").value,
      currency: document.getElementById("currency").textContent,
      roe: parseFloat(document.getElementById("roe").value) || 1,
      booking_given_by: document.getElementById("booking_given_by").value,
      booking_reference: document.getElementById("booking_reference").value.trim(),
      booking_ref_date: toISOFromDDMMYYYY(getDateGroupValue(document.getElementById("booking_ref_date"))),
      airline_pnr: document.getElementById("airline_pnr_header").value,
      gds_pnr: document.getElementById("gds_pnr_header").value,
      payment_mode: document.getElementById("payment_mode").value,
      payment_gateway_ref: document.getElementById("payment_gateway_ref").value.trim(),
      branch_name: (window.VoyagerMock.getReferenceData(activeCompanyId).branches[0] || {}).name,
      lines,
    };
  }

  // ============================================================
  // JV modal - reuses the real backend jv-preview endpoint for an
  // already-saved ticket (editId set); for a ticket still being composed
  // (no editId yet), hits the draft preview endpoint instead, which runs
  // the current in-browser form + passenger data through the exact same
  // _compute_jv_lines formula without saving anything. While the modal is
  // open, every fare edit (see liveSyncSummary/renderPaxTable) re-requests
  // this so the JV stays in sync with whatever was last typed.
  // ============================================================
  async function renderJvPreview(jv) {
    // Before the ticket is actually posted (draft preview), show the
    // Invoice Number as the stand-in Voucher No - a real voucher_no only
    // exists once Save Ticket auto-posts the JV.
    const displayVno = jv.voucher_no || document.getElementById("invoice_number").value.trim() || "Preview";
    document.getElementById("jv-meta-vno").textContent = displayVno;
    document.getElementById("jv-meta-date").textContent = jv.voucher_date ? isoToDDMMYYYY(jv.voucher_date) : "-";
    document.getElementById("jv-meta-currency").textContent = jv.currency || document.getElementById("currency").textContent;
    document.getElementById("jv-table-body").innerHTML = jv.accounts
      .filter((a) => a.debit || a.credit)
      .map((a, i) => `
      <tr style="border-bottom:1px solid #E2E8F0;">
        <td style="padding:5px 8px; text-align:center;">${i + 1}</td>
        <td style="padding:5px 8px;">${a.ledger_name || "-"}</td>
        <td style="padding:5px 8px; text-align:right; font-family:var(--font-mono,monospace);">${a.debit ? fmtN(a.debit) : ""}</td>
        <td style="padding:5px 8px; text-align:right; font-family:var(--font-mono,monospace);">${a.credit ? fmtN(a.credit) : ""}</td>
      </tr>`).join("");
    document.getElementById("jv-total-debit").textContent = fmtN(jv.total_debit);
    document.getElementById("jv-total-credit").textContent = fmtN(jv.total_credit);
    document.getElementById("jv-narration-text").textContent = jv.narration || "-";
    const verifyBox = jvModal.querySelector(".dom-modal-footer div[style*='color:#16A34A']");
    if (verifyBox) {
      const balanced = Math.abs(jv.total_debit - jv.total_credit) < 0.01;
      if (!balanced) {
        verifyBox.innerHTML = `<span style="color:#DC2626;">X Unbalanced - Debit ${fmtN(jv.total_debit)} != Credit ${fmtN(jv.total_credit)}</span>`;
      } else if (jv.posted) {
        verifyBox.innerHTML = `<span>OK Double-Entry Verification: Balanced (Posted ${jv.voucher_no})</span>`;
      } else {
        verifyBox.innerHTML = `<span style="color:#D97706;">Computed - not yet posted (live preview)</span>`;
      }
    }
    renderFopPaymentTab(jv);
    await renderPgReceiptsTab(jv);
  }

  // Switches the J.V modal to the given tab (voucher/fop/pg) - shared by
  // the tab strip's click handler and the auto-fallback when the active
  // tab's content disappears (e.g. FOP switches to Cash while the FOP
  // Payment tab is open).
  function switchJvTab(name) {
    document.querySelectorAll("#jv-tabs .dom-tab").forEach((t) => t.classList.toggle("active", t.dataset.jvTab === name));
    document.querySelectorAll(".jv-tab-panel").forEach((panel) => {
      panel.style.display = panel.id === `jv-tab-panel-${name}` ? "" : "none";
    });
  }
  // Hides/shows a tab button in the strip; if the tab being hidden is the
  // active one, falls back to the Journal Voucher tab so the modal never
  // ends up on a blank, tab-less panel.
  function setJvTabVisible(name, visible) {
    const btn = document.getElementById(`jv-tab-btn-${name}`);
    btn.style.display = visible ? "" : "none";
    if (!visible && btn.classList.contains("active")) switchJvTab("voucher");
  }

  function jvRowHtml(i, ledgerName, debit, credit) {
    return `
      <tr style="border-bottom:1px solid #E2E8F0;">
        <td style="padding:5px 8px; text-align:center;">${i}</td>
        <td style="padding:5px 8px;">${ledgerName || "-"}</td>
        <td style="padding:5px 8px; text-align:right; font-family:var(--font-mono,monospace);">${debit ? fmtN(debit) : ""}</td>
        <td style="padding:5px 8px; text-align:right; font-family:var(--font-mono,monospace);">${credit ? fmtN(credit) : ""}</td>
      </tr>`;
  }

  // FOP Payment tab - only posts when FOP != Cash (FOP is per passenger
  // line; the first line's FOP is used as the ticket's representative FOP,
  // same convention the backend uses for the JV itself). Own Card credits
  // the FOP Master card's own ledger; Client Card credits Customer instead
  // (the client's own card was charged directly, not an internal card).
  // Amount is the same supplier total already computed for the JV's
  // Supplier row(s).
  function renderFopPaymentTab(jv) {
    const table = document.getElementById("jv-tab-panel-fop").querySelector("table").parentElement;
    const empty = document.getElementById("jv-fop-empty");
    const p = passengers[0];
    const fopType = p ? (p.fop || "Cash") : "Cash";
    const supplierRows = (jv.accounts || []).filter((a) => a.role === "supplier");

    if (fopType === "Cash" || supplierRows.length === 0) {
      table.style.display = "none";
      empty.style.display = "";
      setJvTabVisible("fop", false);
      return;
    }
    setJvTabVisible("fop", true);
    table.style.display = "";
    empty.style.display = "none";

    let creditLedgerName;
    if (fopType === "Own Card") {
      const cardNumber = p.card_number || "";
      const card = fopMasterCards.find((c) => c.card_number === cardNumber);
      creditLedgerName = card ? (card.card_master_ledger_name || cardNumber) : (cardNumber || "FOP Card");
    } else {
      const customerRow = (jv.accounts || []).find((a) => a.role === "customer");
      creditLedgerName = customerRow ? customerRow.ledger_name : "Customer";
    }

    let i = 0;
    const debitRowsHtml = supplierRows.map((a) => jvRowHtml(++i, a.ledger_name, a.credit, 0)).join("");
    const totalAmount = supplierRows.reduce((sum, a) => sum + (a.credit || 0), 0);
    const creditRowHtml = jvRowHtml(++i, creditLedgerName, 0, totalAmount);
    document.getElementById("jv-fop-table-body").innerHTML = debitRowsHtml + creditRowHtml;
    document.getElementById("jv-fop-total-debit").textContent = fmtN(totalAmount);
    document.getElementById("jv-fop-total-credit").textContent = fmtN(totalAmount);
  }

  // PG Receipts tab - only posts when Payment Mode = "Payment Gateway".
  // Amount is the same customer total already computed for the JV's
  // Customer row.
  async function renderPgReceiptsTab(jv) {
    const table = document.getElementById("jv-tab-panel-pg").querySelector("table").parentElement;
    const empty = document.getElementById("jv-pg-empty");
    const paymentMode = document.getElementById("payment_mode").value;
    const customerRow = (jv.accounts || []).find((a) => a.role === "customer");

    if (paymentMode !== "Payment Gateway" || !customerRow) {
      table.style.display = "none";
      empty.style.display = "";
      setJvTabVisible("pg", false);
      return;
    }
    setJvTabVisible("pg", true);
    table.style.display = "";
    empty.style.display = "none";

    const gatewayRef = document.getElementById("payment_gateway_ref").value;
    // Resolved as of THIS ticket's own Invoice Date - see
    // getPgEffective()/PGMasterHistory - so the preview matches exactly
    // what the backend will actually post, even if the gateway's rate/
    // ledger has since been edited with a later Effective From date.
    const gateway = await getPgEffective(gatewayRef);
    const pgLedgerName = gateway ? (gateway.payment_master_ledger_name || gatewayRef) : (gatewayRef || "PG Platform");

    const creditAmount = customerRow.debit || 0;
    // PG Charges - the gateway's own cut, only entered per passenger when
    // Payment Mode = "Payment Gateway".
    const pgChargesTotal = passengers.reduce((sum, p) => sum + (p.pg_charges || 0), 0);
    const pgChargesLedgerName = gateway ? (gateway.pg_charges_master_ledger_name || "PG Charges") : "PG Charges";
    // PG GST - same value as the read-only "PG GST" field in the
    // Passenger Fare modal (PG Charges * that gateway's PG Charges
    // Master ledger GST%). Display-only, same convention as PG Charges -
    // not folded into GST Amount/computeFareLine itself.
    const pgGstPct = gateway ? Number(gateway.pg_charges_master_ledger_gst_percentage) || 0 : 0;
    const pgGstTotal = Math.round(pgChargesTotal * pgGstPct / 100 * 100) / 100;

    // These are auto-filled straight into the JV, not typed - so if the
    // gateway has no PG Charges Master ledger mapped, warn instead of
    // silently posting them under the literal "PG Charges"/"PG GST" text.
    if ((pgChargesTotal > 0 || pgGstTotal > 0) && gateway && !gateway.pg_charges_master_ledger_id) {
      warnUnmappedPgLedger(gatewayRef);
    }

    // PG Platform Debit = Total Billed (computeFareLine's own `total`,
    // which already includes Sup Markup/Sup Addl Markup/Sup Service
    // Fee/Sup Addl Service Fee/Sup GST Amount) + PG Charges + PG GST.
    const debitAmount = passengers.reduce((sum, p) => {
      const r = computeFareLine(p);
      const pgCharges = p.pg_charges || 0;
      const pgGst = Math.round(pgCharges * pgGstPct / 100 * 100) / 100;
      return sum + r.total + pgCharges + pgGst;
    }, 0);

    const pgLedgerUnmapped = gateway && !gateway.pg_charges_master_ledger_id;
    const unmappedSuffix = ' <span style="color:#DC2626; font-weight:700;" title="No PG Charges Master ledger mapped in PG Master">(unmapped)</span>';

    // PG GST's Credit line(s) - same Company State vs Customer State
    // (Ledger Master) comparison the main Journal Voucher tab's Output GST
    // uses (see _compute_jv_lines server-side): same state = split
    // half/half into Output CGST A/c + Output SGST A/c, different state =
    // one combined Output IGST A/c line. Resolved via Master Mapping
    // (same "GST and TDS" ledgers the main tab posts to) - NOT PG
    // Master's own PG Charges Master ledger, which is only for the
    // separate PG Charges row above.
    const custLedger = allCustomers.find((c) => c.name === document.getElementById("customer").value);
    const customerState = (custLedger && custLedger.state_name) || "";
    const sameState = !!companyState && !!customerState
      && companyState.trim().toLowerCase() === customerState.trim().toLowerCase();
    function gstMappedName(fieldName) {
      if (!mappedFieldNames.has(fieldName)) warnUnmappedGstField(fieldName);
      return mappedFieldLedgerName[fieldName] || `${fieldName} (not mapped in Master Mapping)`;
    }

    let rowsHtml = jvRowHtml(1, customerRow.ledger_name, 0, creditAmount) + jvRowHtml(2, pgLedgerName, debitAmount, 0);
    let totalDebit = debitAmount;
    let totalCredit = creditAmount;
    let rowNum = 2;
    if (pgChargesTotal > 0) {
      rowsHtml += jvRowHtml(++rowNum, pgChargesLedgerName + (pgLedgerUnmapped ? unmappedSuffix : ""), 0, pgChargesTotal);
      totalCredit += pgChargesTotal;
    }
    if (pgGstTotal > 0) {
      if (sameState) {
        const half = Math.round(pgGstTotal / 2 * 100) / 100;
        rowsHtml += jvRowHtml(++rowNum, gstMappedName("Output CGST A/c"), 0, half);
        rowsHtml += jvRowHtml(++rowNum, gstMappedName("Output SGST A/c"), 0, half);
        totalCredit += half * 2;
      } else {
        rowsHtml += jvRowHtml(++rowNum, gstMappedName("Output IGST A/c"), 0, pgGstTotal);
        totalCredit += pgGstTotal;
      }
    }
    document.getElementById("jv-pg-table-body").innerHTML = rowsHtml;
    document.getElementById("jv-pg-total-debit").textContent = fmtN(totalDebit);
    document.getElementById("jv-pg-total-credit").textContent = fmtN(totalCredit);
  }

  // J.V modal tab strip - Journal Voucher / FOP Payment / PG Receipts.
  document.getElementById("jv-tabs").addEventListener("click", (e) => {
    const tab = e.target.closest(".dom-tab");
    if (!tab || tab.style.display === "none") return;
    switchJvTab(tab.dataset.jvTab);
  });

  // Voucher No/Date show the Invoice Number/Date as soon as the modal
  // opens, regardless of whether the JV can actually be computed yet (e.g.
  // no passengers added). Once a real JV (draft or posted) comes back,
  // renderJvPreview overwrites these with its own values as usual.
  function primeJvHeaderFromInvoice() {
    const invoiceNo = document.getElementById("invoice_number").value.trim();
    const invoiceDateStr = getDateGroupValue(document.getElementById("invoice_date"));
    const display = invoiceNo || "Preview";
    document.getElementById("jv-meta-vno").textContent = display;
    document.getElementById("jv-meta-date").textContent = invoiceDateStr || "-";
    document.getElementById("jv-meta-currency").textContent = document.getElementById("currency").textContent;
  }

  async function loadJvPreview(showLoading) {
    primeJvHeaderFromInvoice();
    if (showLoading) {
      document.getElementById("jv-table-body").innerHTML = `<tr><td colspan="4" style="padding:10px;">Loading...</td></tr>`;
    }
    try {
      let res;
      if (editId) {
        res = await fetch(`${API_BASE}/tickets/${editId}/jv-preview/?company_id=${activeCompanyId}`);
      } else {
        if (passengers.length === 0) throw new Error("Add at least one passenger (via Proceed ->) to preview the JV.");
        res = await fetch(`${API_BASE}/tickets/jv-preview-draft/`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(buildTicketPayload()),
        });
      }
      const jv = await res.json();
      if (!res.ok) throw new Error(jv.error || "Could not compute JV.");
      await renderJvPreview(jv);
    } catch (err) {
      document.getElementById("jv-table-body").innerHTML = `<tr><td colspan="4" style="padding:10px; color:#DC2626;">${err.message}</td></tr>`;
    }
  }
  document.getElementById("jv-btn").addEventListener("click", () => {
    jvModal.classList.add("open");
    switchJvTab("voucher");
    loadJvPreview(true);
  });
  // Called after every passenger add/edit/delete/live-fare-edit - no-op
  // unless the JV modal is actually open, and skips the "Loading..." flicker
  // since it's re-fetching in the background while the user keeps typing.
  function maybeRefreshJvPreview() {
    if (jvModal.classList.contains("open")) loadJvPreview(false);
  }
  document.getElementById("jv-close-x-btn").addEventListener("click", () => jvModal.classList.remove("open"));
  document.getElementById("jv-ok-btn").addEventListener("click", () => jvModal.classList.remove("open"));

  // ============================================================
  // Find Ticket modal - filter by Invoice No / Booking Ref / Airline PNR / GDS PNR
  // ============================================================
  // travel_date is plain dd/mm/yyyy text now (multi-city sectors, comma-joined
  // when dates differ) - issue_date is still a real ISO date from Ticket.invoice_date.
  // Converts each candidate date to ISO before comparing against the date-range
  // filter, and matches if ANY of a multi-city line's dates falls in range.
  function rowMatchesDateFilter(r, dateType, dateFrom, dateTo) {
    if (!dateFrom && !dateTo) return true;
    const raw = r[dateType] || "";
    if (!raw) return false;
    const candidates = dateType === "travel_date"
      ? raw.split(",").map((d) => toISOFromDDMMYYYY(d.trim())).filter(Boolean)
      : [raw];
    return candidates.some((iso) => (!dateFrom || iso >= dateFrom) && (!dateTo || iso <= dateTo));
  }
  async function runFindSearch() {
    const resultsBody = document.getElementById("find-results-body");
    const invoiceQ = document.getElementById("find-invoice-number").value.trim().toLowerCase();
    const bookingQ = document.getElementById("find-booking-ref").value.trim().toLowerCase();
    const airlinePnrQ = document.getElementById("find-airline-pnr").value.trim().toLowerCase();
    const gdsPnrQ = document.getElementById("find-gds-pnr").value.trim().toLowerCase();
    const ticketNoQ = document.getElementById("find-ticket-no").value.trim().toLowerCase();
    const customerQ = document.getElementById("find-customer-name").value.trim().toLowerCase();
    const airlineCodeQ = document.getElementById("find-airline-code").value.trim().toLowerCase();
    const dateType = document.getElementById("find-date-type").dataset.value;
    const dateFrom = document.getElementById("find-date-from").value;
    const dateTo = document.getElementById("find-date-to").value;

    resultsBody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:14px; color:#64748B;">Searching...</td></tr>`;
    let rows = [];
    try {
      const res = await fetch(`${API_BASE}/tickets/?company_id=${activeCompanyId}`);
      rows = res.ok ? await res.json() : [];
    } catch (_) { rows = []; }

    const filtered = rows.filter((r) =>
      (!invoiceQ || (r.invoice_number || "").toLowerCase().includes(invoiceQ)) &&
      (!bookingQ || (r.booking_reference || "").toLowerCase().includes(bookingQ)) &&
      (!airlinePnrQ || (r.airline_pnr || "").toLowerCase().includes(airlinePnrQ)) &&
      (!gdsPnrQ || (r.gds_pnr || "").toLowerCase().includes(gdsPnrQ)) &&
      (!ticketNoQ || (r.ticket_no || "").toLowerCase().includes(ticketNoQ)) &&
      (!customerQ || (r.customer_name || "").toLowerCase().includes(customerQ)) &&
      (!airlineCodeQ || (r.airline_code || "").toLowerCase().includes(airlineCodeQ)) &&
      rowMatchesDateFilter(r, dateType, dateFrom, dateTo)
    );

    // One row per TICKET, not per passenger line - show the first passenger
    // added (lowest TicketLine id) as the representative row, so a ticket
    // with several passengers doesn't repeat its Invoice No/Booking Ref/
    // PNR/Ticket No for every one of them.
    const byTicket = new Map();
    filtered.forEach((r) => {
      const existing = byTicket.get(r.ticket_id);
      if (!existing || r.id < existing.id) byTicket.set(r.ticket_id, r);
    });
    const deduped = Array.from(byTicket.values());

    if (deduped.length === 0) {
      resultsBody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:14px; color:#64748B;">No matching tickets found.</td></tr>`;
      return;
    }
    resultsBody.innerHTML = deduped.map((r) => `
      <tr class="find-result-row" data-id="${r.ticket_id}" style="cursor:pointer;">
        <td style="padding:4px 8px;">${r.invoice_number || "-"}</td>
        <td style="padding:4px 8px;">${r.booking_reference || "-"}</td>
        <td style="padding:4px 8px;">${r.airline_pnr || "-"}</td>
        <td style="padding:4px 8px;">${r.gds_pnr || "-"}</td>
        <td style="padding:4px 8px;">${r.ticket_no || "-"}</td>
        <td style="padding:4px 8px;">${r.passenger_name || "-"}</td>
        <td style="padding:4px 8px; text-align:right;">${fmtN(r.total_billed || 0)}</td>
      </tr>`).join("");
    document.querySelectorAll(".find-result-row").forEach((row) => {
      row.addEventListener("click", () => {
        window.location.href = `ticket-entry.html?id=${row.dataset.id}`;
      });
    });
  }
  document.getElementById("find-btn").addEventListener("click", () => {
    findModal.classList.add("open");
    document.getElementById("find-results-body").innerHTML = `<tr><td colspan="7" style="text-align:center; padding:14px; color:#64748B;">Enter a filter above and click Search.</td></tr>`;
  });
  document.getElementById("find-close-x-btn").addEventListener("click", () => findModal.classList.remove("open"));
  document.getElementById("find-search-btn").addEventListener("click", runFindSearch);
  document.querySelectorAll(".dom-date-type-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".dom-date-type-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById("find-date-type").dataset.value = btn.dataset.value;
    });
  });
  ["find-invoice-number", "find-booking-ref", "find-airline-pnr", "find-gds-pnr", "find-ticket-no",
    "find-customer-name", "find-airline-code", "find-date-from", "find-date-to"].forEach((id) => {
    document.getElementById(id).addEventListener("keydown", (e) => { if (e.key === "Enter") runFindSearch(); });
  });

  // ============================================================
  // View mode - load a saved ticket read-only
  // ============================================================
  async function enterViewMode(t) {
    viewMode = true;
    document.getElementById("page-title").textContent = `View Airline Ticket - ${t.lines[0]?.ticket_no || t.invoice_number} (${t.lines[0]?.passenger_name || ""})`;
    document.getElementById("invoice_number").value = t.invoice_number;
    setDateGroupValue(document.getElementById("invoice_date"), isoToDDMMYYYY(t.invoice_date));
    document.getElementById("invoice_type").value = t.invoice_type || "";
    document.getElementById("booking_mode").value = t.booking_mode || "";
    document.getElementById("customer").value = t.customer_name || "";
    document.getElementById("booking_reference").value = t.booking_reference || "";
    setDateGroupValue(document.getElementById("booking_ref_date"), isoToDDMMYYYY(t.booking_ref_date));
    document.getElementById("booking_given_by").value = t.booking_given_by || "";
    document.getElementById("booking_type").value = t.booking_type || "";
    document.getElementById("booking_status").value = t.booking_status || "";
    document.getElementById("travel_type").value = t.travel_type || "";
    document.getElementById("user_name").value = t.user_name || "";
    document.getElementById("payment_mode").value = t.payment_mode || "";
    document.getElementById("payment_gateway_ref").value = t.payment_gateway_ref || "";
    updateGatewayRefField();
    document.getElementById("roe").value = t.roe;
    document.getElementById("airline_pnr_header").value = t.airline_pnr || "";
    document.getElementById("gds_pnr_header").value = t.gds_pnr || "";
    document.getElementById("customer").dispatchEvent(new Event("input"));

    passengers = t.lines.map((l) => ({
      airline_code: l.airline_code, airline_name: l.airline_name, airline_category: l.airline_category,
      flight_no: l.flight_no, ticket_no: l.ticket_no,
      passenger_name: l.passenger_name, pax_type: l.pax_type, sector: l.sector, travel_date: l.travel_date,
      cabin: l.cabin, travel_class: l.travel_class, fare_type: l.fare_type,
      basic_fare: l.basic_fare, yq: l.yq, yr: l.yr, k3_tax: l.k3_tax, tax_others: l.tax_others, seat: l.seat, meal: l.meal,
      baggage: l.baggage, other_ssr: l.other_ssr, disc_on: l.disc_on, disc_type: l.disc_type, disc_value: l.disc_value,
      tds_per: l.tds_per, pg_charges: l.pg_charges || 0, pg_charges_percentage: l.pg_charges_percentage != null ? l.pg_charges_percentage : 0, markup: l.markup, addl_markup: l.addl_markup, ssr_markup: l.ssr_markup || 0, service_fee: l.service_fee,
      addl_service_fee: l.addl_service_fee, ssr_service_fee: l.ssr_service_fee || 0, gst_pct: l.gst_pct,
      supplier_name: l.supplier_name, office_id: l.office_id, fop: l.fop, card_number: l.card_number || "",
      supp_comm_on: l.supp_comm_on, supp_comm_type: l.supp_comm_type,
      supp_comm_value: l.supp_comm_value, supp_tds_per: l.supp_tds_per,
      supp_markup: l.supp_markup || 0, supp_addl_markup: l.supp_addl_markup || 0,
      supp_service_fee: l.supp_service_fee || 0, supp_addl_service_fee: l.supp_addl_service_fee || 0,
      supp_gst_pct: l.supp_gst_pct || 0,
    }));
    renderPaxTable();

    document.querySelectorAll(".dom-form-grid input, .dom-form-grid select").forEach((el) => (el.disabled = true));
    document.getElementById("proceed-btn").style.display = "none";
    document.getElementById("submit-btn").style.display = "none";
    // When this ticket was opened by clicking a row on a report (Day
    // Book, Ledger, DSR), send "Back" to that report instead of always
    // reloading a blank ticket-entry.html - document.referrer holds
    // wherever the browser actually navigated here from.
    const REPORT_BACK_TARGETS = [
      { match: "report-day-book.html", label: "Day Book" },
      { match: "report-ledger-book.html", label: "Ledger" },
      { match: "report-dsr-airline-booking.html", label: "DSR" },
    ];
    const backTarget = REPORT_BACK_TARGETS.find((r) => document.referrer.includes(r.match));
    const cancelLink = document.getElementById("cancel-link");
    if (backTarget) {
      cancelLink.textContent = `<- Back to ${backTarget.label}`;
      cancelLink.setAttribute("href", document.referrer);
    } else {
      cancelLink.textContent = "<- Back to Tickets";
    }
    document.getElementById("edit-ticket-btn").style.display = "";
  }

  // Builds the frozen "Parent PNR Details" passenger object from an
  // original TicketLine (as returned by tickets/<id>/) - shared by both
  // enterRescheduleMode (brand-new reschedule) and enterSavedRescheduleMode
  // (re-opening an already-saved one), so the two flows can never drift
  // out of sync on what Parent PNR Details actually shows.
  function buildParentPassengerFromLine(l) {
    return {
      airline_code: l.airline_code, airline_name: l.airline_name, airline_category: l.airline_category,
      flight_no: l.flight_no, ticket_no: l.ticket_no,
      passenger_name: l.passenger_name, pax_type: l.pax_type, sector: l.sector, travel_date: l.travel_date,
      cabin: l.cabin, travel_class: l.travel_class, fare_type: l.fare_type,
      basic_fare: l.basic_fare, yq: l.yq, yr: l.yr, k3_tax: l.k3_tax, tax_others: l.tax_others, seat: l.seat, meal: l.meal,
      baggage: l.baggage, other_ssr: l.other_ssr, disc_on: l.disc_on, disc_type: l.disc_type, disc_value: l.disc_value,
      tds_per: l.tds_per, pg_charges: l.pg_charges || 0, pg_charges_percentage: l.pg_charges_percentage != null ? l.pg_charges_percentage : 0, markup: l.markup, addl_markup: l.addl_markup, ssr_markup: l.ssr_markup || 0, service_fee: l.service_fee,
      addl_service_fee: l.addl_service_fee, ssr_service_fee: l.ssr_service_fee || 0, gst_pct: l.gst_pct,
      supplier_name: l.supplier_name, office_id: l.office_id, fop: l.fop, card_number: l.card_number || "",
      supp_comm_on: l.supp_comm_on, supp_comm_type: l.supp_comm_type,
      supp_comm_value: l.supp_comm_value, supp_tds_per: l.supp_tds_per,
      supp_markup: l.supp_markup || 0, supp_addl_markup: l.supp_addl_markup || 0,
      supp_service_fee: l.supp_service_fee || 0, supp_addl_service_fee: l.supp_addl_service_fee || 0,
      supp_gst_pct: l.supp_gst_pct || 0,
    };
  }

  // Pre-fills a brand-new ticket from an existing one's data, for the
  // Reschedule flow (trans-airline-reschedule.html) - unlike enterViewMode,
  // this leaves Invoice Number blank and defaults both dates to today (this
  // is a new ticket being created, not the original being reopened), keeps
  // every field editable, and only carries over the ONE passenger line the
  // user picked on the reschedule screen rather than the whole ticket.
  async function enterRescheduleMode(t, lineId) {
    rescheduleMode = true;
    document.getElementById("page-title").textContent = "Reschedule";
    // These two fields now track the reschedule's own reference/date, not
    // the original ticket's, so their labels say so.
    document.getElementById("booking_reference_label").innerHTML = 'Rescheduled Ref<span class="dom-req">*</span>';
    document.getElementById("booking_ref_date_label").innerHTML = 'Rescheduled Ref Date<span class="dom-req">*</span>';
    document.getElementById("booking_reference").style.flex = "0 0 120px";
    // Parent PNR carries the ORIGINAL ticket's Booking Reference forward
    // for a visible trail back to it - Booking Reference itself is left
    // blank so the user enters this reschedule's own new reference.
    document.getElementById("parent-pnr-field").style.display = "";
    document.getElementById("parent_pnr").textContent = t.booking_reference || "—";
    document.getElementById("invoice_type").value = t.invoice_type || "";
    document.getElementById("booking_mode").value = t.booking_mode || "";
    document.getElementById("customer").value = t.customer_name || "";
    document.getElementById("booking_reference").value = "";
    document.getElementById("booking_given_by").value = t.booking_given_by || "";
    document.getElementById("booking_type").value = t.booking_type || "";
    // Frozen to Re-Scheduled regardless of the original ticket's own
    // status - this new ticket only exists because of the reschedule.
    document.getElementById("booking_status").value = "Re-Scheduled";
    document.getElementById("booking_status").disabled = true;
    document.getElementById("travel_type").value = t.travel_type || "";
    document.getElementById("user_name").value = t.user_name || "";
    // Payment Mode is left unset ("Select...") rather than copied from the
    // original ticket - the reschedule may be settled through a different
    // mode, so the user picks it fresh.
    document.getElementById("payment_mode").value = "";
    document.getElementById("payment_gateway_ref").value = "";
    updateGatewayRefField();
    document.getElementById("roe").value = t.roe;
    document.getElementById("airline_pnr_header").value = t.airline_pnr || "";
    document.getElementById("gds_pnr_header").value = t.gds_pnr || "";
    document.getElementById("customer").dispatchEvent(new Event("input"));

    const l = t.lines.find((ln) => String(ln.id) === String(lineId)) || t.lines[0];
    if (l) {
      // Parent PNR Details tab - the ORIGINAL ticket line, untouched, shown
      // purely as a frozen reference (including its real FOP/Card Number,
      // unlike the old behaviour that used to default FOP to Cash here).
      rescheduleParentPassenger = buildParentPassengerFromLine(l);
      // Reschedule PNR Details tab - this brand new ticket's own data,
      // starts fully blank/0.00 (like any other new passenger) and IS what
      // the register/Summary/save payload actually reflect until filled in.
      passengers = [blankPassenger()];
      rescheduleEditPassenger = passengers[0];
    }
    renderPaxTable();
  }

  // Re-opens an ALREADY-SAVED RescheduleAirlineTicket (the lookup screen's
  // "Saved" radio) - unlike enterRescheduleMode above, every field (header
  // + the one passenger line) is filled from what was actually saved, not
  // blank, and Save Ticket goes on to UPDATE this same record (see
  // editingRescheduleId) instead of creating a new one.
  async function enterSavedRescheduleMode(rt, originalTicket) {
    rescheduleMode = true;
    editingRescheduleId = rt.id;
    rescheduleTicketId = rt.original_ticket_id;
    // Opens read-only first, same as any other saved ticket (enterViewMode)
    // - the "Edit" button unlocks it, rather than landing straight in an
    // editable form the way a brand-new reschedule (enterRescheduleMode)
    // does.
    viewMode = true;
    document.getElementById("page-title").textContent =
      `View Reschedule - ${rt.lines[0]?.ticket_no || rt.invoice_number} (${rt.lines[0]?.passenger_name || ""})`;
    document.getElementById("booking_reference_label").innerHTML = 'Rescheduled Ref<span class="dom-req">*</span>';
    document.getElementById("booking_ref_date_label").innerHTML = 'Rescheduled Ref Date<span class="dom-req">*</span>';
    document.getElementById("booking_reference").style.flex = "0 0 120px";
    document.getElementById("parent-pnr-field").style.display = "";
    document.getElementById("parent_pnr").textContent = originalTicket.booking_reference || "—";
    document.getElementById("invoice_number").value = rt.invoice_number || "";
    setDateGroupValue(document.getElementById("invoice_date"), rt.invoice_date ? isoToDDMMYYYY(rt.invoice_date) : todayDDMMYYYY());
    document.getElementById("invoice_type").value = rt.invoice_type || "";
    document.getElementById("booking_mode").value = rt.booking_mode || "";
    document.getElementById("customer").value = rt.customer_name || "";
    document.getElementById("booking_reference").value = rt.booking_reference || "";
    document.getElementById("booking_given_by").value = rt.booking_given_by || "";
    document.getElementById("booking_type").value = rt.booking_type || "";
    document.getElementById("booking_status").value = "Re-Scheduled";
    document.getElementById("booking_status").disabled = true;
    document.getElementById("travel_type").value = rt.travel_type || "";
    document.getElementById("user_name").value = rt.user_name || "";
    document.getElementById("payment_mode").value = rt.payment_mode || "";
    document.getElementById("payment_gateway_ref").value = rt.payment_gateway_ref || "";
    updateGatewayRefField();
    document.getElementById("roe").value = rt.roe;
    document.getElementById("airline_pnr_header").value = rt.airline_pnr || "";
    document.getElementById("gds_pnr_header").value = rt.gds_pnr || "";
    setDateGroupValue(document.getElementById("booking_ref_date"), rt.booking_ref_date ? isoToDDMMYYYY(rt.booking_ref_date) : todayDDMMYYYY());
    document.getElementById("customer").dispatchEvent(new Event("input"));

    const savedLine = rt.lines[0];
    const parentLine = savedLine
      ? originalTicket.lines.find((ln) => String(ln.id) === String(savedLine.original_ticket_line_id))
      : null;
    if (parentLine) rescheduleParentPassenger = buildParentPassengerFromLine(parentLine);
    passengers = savedLine ? [{ ...blankPassenger(), ...savedLine }] : [blankPassenger()];
    rescheduleEditPassenger = passengers[0];
    renderPaxTable();

    document.querySelectorAll(".dom-form-grid input, .dom-form-grid select").forEach((el) => (el.disabled = true));
    document.getElementById("proceed-btn").style.display = "none";
    document.getElementById("submit-btn").style.display = "none";
    document.getElementById("cancel-link").textContent = "<- Back to Reschedule";
    document.getElementById("cancel-link").setAttribute("href", "trans-airline-reschedule.html");
    document.getElementById("edit-ticket-btn").style.display = "";
  }

  // Unlocks a loaded/saved ticket for editing - re-enables every header
  // field, brings back Save Ticket, and re-renders the passenger table so
  // rows show Edit/Del again instead of View-only. Save Ticket then hits
  // tickets/<id>/update/ instead of tickets/create/ since editId is set.
  document.getElementById("edit-ticket-btn").addEventListener("click", () => {
    viewMode = false;
    document.querySelectorAll(".dom-form-grid input, .dom-form-grid select").forEach((el) => (el.disabled = false));
    document.getElementById("booking_mode").disabled = true; // stays frozen at Manual regardless of mode
    // A saved Reschedule ticket keeps Booking Status frozen at
    // Re-Scheduled even once unlocked for editing (same as when it was
    // first created - see enterSavedRescheduleMode/enterRescheduleMode).
    if (rescheduleMode) document.getElementById("booking_status").disabled = true;
    updateGatewayRefField(); // re-applies its own read-only/editable rule, not just "everything enabled"
    document.getElementById("submit-btn").style.display = "";
    document.getElementById("edit-ticket-btn").style.display = "none";
    document.getElementById("cancel-link").textContent = "Discard";
    // Discard from Edit mode must return to THIS ticket's own view state,
    // not wherever cancel-link's href was left pointing from enterViewMode
    // (document.referrer, or the "Back to Tickets" default) - re-loading
    // this same ?id=/?reschedule_saved_id= is what actually discards the
    // in-progress edits.
    document.getElementById("cancel-link").setAttribute("href",
      rescheduleMode ? `ticket-entry.html?reschedule_saved_id=${editingRescheduleId}` : `ticket-entry.html?id=${editId}`);
    renderPaxTable(); // recomputes proceed/add-line-btn visibility + Edit/Del per row now that viewMode is false
  });

  // Discard / Exit both navigate away from this ticket - confirm first so
  // an accidental click doesn't silently lose whatever's been entered.
  // Listener is on the anchor itself (not delegated on document) and
  // stops propagation so it runs before shell.js's own document-level
  // link-click SPA handler.
  [["cancel-link", "Discard"], ["exit-btn", "Exit"]].forEach(([id, action]) => {
    document.getElementById(id).addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const href = e.currentTarget.getAttribute("href");
      voyagerConfirm(
        action === "Discard"
          ? "Discard this ticket and any unsaved changes?"
          : "Exit without saving? Any unsaved changes will be lost.",
        { title: `Confirm ${action}`, confirmLabel: action, icon: action === "Discard" ? "warning" : "exit" }
      ).then((confirmed) => {
        if (confirmed) window.VoyagerShell.navigateTo(href);
      });
    });
  });

  // ============================================================
  // Save (create mode)
  // ============================================================
  document.getElementById("ticket-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const invErr = checkNotFutureAndInFY(getDateGroupValue(document.getElementById("invoice_date")), "Invoice Date");
    if (invErr) { setHint("invoice_date_hint", invErr, false); voyagerAlert(invErr); return; }
    const refErr = checkNotFutureAndInFY(getDateGroupValue(document.getElementById("booking_ref_date")), "Booking Ref Date");
    if (refErr) { setHint("booking_ref_date_hint", refErr, false); voyagerAlert(refErr); return; }
    if (!document.getElementById("invoice_number").value.trim()) { voyagerAlert("Invoice Number is required."); return; }
    if (!checkDuplicateHeaderField("invoice_number", "invoice_number_hint", "invoice_number", "Invoice Number")) {
      voyagerAlert("This Invoice Number is already used."); return;
    }
    if (!document.getElementById("customer").value.trim() || !allCustomers.some((c) => c.name === document.getElementById("customer").value)) { voyagerAlert("Pick a valid Customer from the list."); return; }
    if (!document.getElementById("booking_reference").value.trim()) { voyagerAlert("Booking Reference is required."); return; }
    if (!checkDuplicateHeaderField("booking_reference", "booking_reference_hint", "booking_reference", "Booking Reference")) {
      voyagerAlert("This Booking Reference is already used."); return;
    }
    if (passengers.length === 0) { voyagerAlert("Add at least one passenger via Proceed ->."); return; }

    const payload = buildTicketPayload();
    const url = rescheduleMode
      ? (editingRescheduleId
          ? `${API_BASE}/reschedule-tickets/${editingRescheduleId}/update/`
          : `${API_BASE}/reschedule-tickets/create/`)
      : editId
      ? `${API_BASE}/tickets/${editId}/update/`
      : `${API_BASE}/tickets/create/`;

    try {
      const res = await fetch(url, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      let result;
      try { result = await res.json(); }
      catch (_) { throw new Error(`The server returned an unexpected response (status ${res.status}). Check the Django terminal.`); }
      if (!res.ok) throw new Error(result.error || "Could not save this ticket.");
      window.VoyagerEntry.showToast(result.message || `${payload.lines.length} ticket(s) saved.`, "ticket-entry.html");
    } catch (err) {
      voyagerAlert(err.message || "Could not save this ticket. Is the Django backend running?", { icon: "error" });
    }
  });

  // ============================================================
  // Init
  // ============================================================
  if (!editId) {
    setDateGroupValue(document.getElementById("invoice_date"), todayDDMMYYYY());
    setDateGroupValue(document.getElementById("booking_ref_date"), todayDDMMYYYY());
  }
  let active = null;
  try {
    active = await VoyagerShell.init({ activeKey: "tickets", onCompanyChange: (id, country) => { activeCompanyId = Number(id); activeCountry = country; VoyagerUtil.loadDecimalPlaces(activeCompanyId); populateRefs(activeCompanyId); } });
  } catch (err) {
    console.error("Shell init failed", err);
  }
  if (active) {
    activeCompanyId = Number(active.id); activeCountry = active.country;
    // Company Master's "No. of Decimals" - every fmtN() call below reads
    // this, so it must resolve before the first render (blank register/
    // Summary/modal) rather than racing it.
    await VoyagerUtil.loadDecimalPlaces(activeCompanyId);
    if (editId) {
      // Ticket fetch runs alongside populateRefs (not after it) - halves
      // the wait before enterViewMode can start, since neither depends on
      // the other; enterViewMode itself still only runs once both are
      // done, since it needs populateRefs' dropdown options in place.
      try {
        const [, res] = await Promise.all([
          populateRefs(activeCompanyId),
          fetch(`${API_BASE}/tickets/${editId}/?company_id=${activeCompanyId}`),
        ]);
        const ticket = await res.json();
        if (!res.ok) throw new Error(ticket.error || "Ticket not found.");
        await enterViewMode(ticket);
      } catch (err) {
        voyagerAlert(err.message || "Could not load this ticket. Is the Django backend running?", { icon: "error" });
      }
    } else {
      await populateRefs(activeCompanyId);
      try {
        const res = await fetch(`${API_BASE}/tickets/?company_id=${activeCompanyId}`);
        existingTickets = res.ok ? await res.json() : [];
      } catch (_) { existingTickets = []; }
      if (rescheduleSavedId) {
        try {
          const res = await fetch(`${API_BASE}/reschedule-tickets/${rescheduleSavedId}/?company_id=${activeCompanyId}`);
          const rt = await res.json();
          if (!res.ok) throw new Error(rt.error || "Saved reschedule ticket not found.");
          const origRes = await fetch(`${API_BASE}/tickets/${rt.original_ticket_id}/?company_id=${activeCompanyId}`);
          const originalTicket = await origRes.json();
          if (!origRes.ok) throw new Error(originalTicket.error || "Original ticket not found.");
          await enterSavedRescheduleMode(rt, originalTicket);
        } catch (err) {
          voyagerAlert(err.message || "Could not load this saved reschedule ticket. Is the Django backend running?", { icon: "error" });
          renderPaxTable();
        }
      } else if (rescheduleTicketId) {
        try {
          const res = await fetch(`${API_BASE}/tickets/${rescheduleTicketId}/?company_id=${activeCompanyId}`);
          const ticket = await res.json();
          if (!res.ok) throw new Error(ticket.error || "Ticket not found.");
          await enterRescheduleMode(ticket, rescheduleLineId);
        } catch (err) {
          voyagerAlert(err.message || "Could not load the original ticket for reschedule. Is the Django backend running?", { icon: "error" });
          renderPaxTable();
        }
      } else {
        renderPaxTable();
      }
    }
  } else {
    voyagerAlert("Could not load the active company. Check your connection and reload the page.", { icon: "error" });
  }
})();