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
  // Chaining - this "New" reschedule was found via a PREVIOUS reschedule
  // (rescheduling an already-rescheduled ticket again), not the original
  // ticket. parentRescheduleId says which reschedule to build "Parent PNR
  // Details" from instead of the original; basedOnRescheduleLineId is the
  // chain link reschedule_ticket_create needs (which reschedule line to
  // flip ineligible on save) - sent as each line's own reschedule_line_id
  // in buildTicketPayload().
  const parentRescheduleId = params.get("parent_reschedule_id");
  const basedOnRescheduleLineId = params.get("parent_reschedule_line_id");
  // Reschedule's own menu item now lands here directly (no more separate
  // trans-airline-reschedule.html search page) - this flags that blank
  // "awaiting a pick" shell (see enterBlankRescheduleShell), reached
  // before any original ticket/passenger has been chosen yet.
  const rescheduleNew = params.get("reschedule_new") === "1";
  // Cancellation's own menu item, same pattern as Reschedule above - UI
  // shell only for now (see enterBlankCancellationShell): title +
  // Booking Status + bottom toolbar, no real lookup/save logic wired
  // yet.
  const cancellationNew = params.get("cancellation_new") === "1";
  // Set when a Cancellation's own "Find" result is clicked (see
  // runFindSearch's cancellationMode branch) - loads that saved
  // Cancellation's own header + lines, read-only (2026-10-06).
  const cancellationSavedId = params.get("cancellation_saved_id");
  const rescheduleActiveKey = (rescheduleTicketId || rescheduleSavedId || rescheduleNew)
    ? "trans-airline-reschedule" : ((cancellationNew || cancellationSavedId) ? "trans-airline-cancellation" : "tickets");
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
  let cancellationMode = false; // true only for Cancellation's own blank shell (see enterBlankCancellationShell) - UI only for now, no save/lookup logic wired yet
  // Reschedule's fare modal shows two tabs covering the WHOLE modal (both
  // Passenger & Segment Details and Base Fare/Customer/Supplier):
  // "Parent PNR Details" (the original ticket line, frozen/non-editable,
  // shown purely for reference) and "Reschedule PNR Details" (this brand
  // new ticket's own data - starts completely blank/0.00, fully editable,
  // and IS what actually gets saved).
  let modalRescheduleTab = "parent";
  // One entry per picked passenger, same index as `passengers` - each
  // passenger rescheduled together can have its own Parent (e.g. two
  // different original lines, or two different points in a chain), so
  // this can no longer be a single shared object.
  let rescheduleParentPassengers = [];
  // One array PER picked passenger (same index as `passengers`), each
  // holding that passenger's own chain_levels from the backend - one
  // entry per ancestor PNR (nearest first), each a modal-ready passenger
  // object (via buildParentPassengerFromLine) showing THAT level's own
  // standalone data, never summed. Sits alongside rescheduleParentPassengers
  // (the cumulative total) rather than replacing it - extra tab buttons
  // are built from this in renderAncestorTabs.
  let rescheduleAncestorLevels = [];
  let modalSectors = []; // current passenger's multi-city sectors - {from,to,travelDate,flightNo,cabin,cls,fareType}
  let editingSectorIndex = null;

  const linesBody = document.getElementById("ticket-lines");
  const fareModal = document.getElementById("fare-breakdown-modal");
  const jvModal = document.getElementById("jv-modal");
  const findModal = document.getElementById("find-modal");
  const sectorModal = document.getElementById("sector-modal");
  const gstDetailModal = document.getElementById("gst-detail-modal");
  const markupReversalModal = document.getElementById("markup-reversal-modal");

  function fillPlain(el, values, placeholder) {
    el.innerHTML = (placeholder ? `<option value="">${placeholder}</option>` : "") +
      values.map((v) => `<option value="${v}">${v}</option>`).join("");
  }
  fillPlain(document.getElementById("invoice_type"), [], "Select...");
  fillPlain(document.getElementById("booking_type"), OPT.bookingTypes, "Select...");
  fillPlain(document.getElementById("booking_status"), OPT.bookingStatuses, "Select...");
  // Booking Status defaults to a fixed value per screen, frozen (never
  // user-editable) everywhere - "Confirmed" here for a plain New Ticket;
  // Reschedule/Cancellation each override both the value and the disabled
  // state to their own fixed status a bit further down (enterBlankReschedule
  // Shell/enterRescheduleMode/enterSavedRescheduleMode -> "Re-Scheduled",
  // enterBlankCancellationShell/enterCancellationMode/enterSavedCancellation
  // Mode -> "Normal Cancelled") once this page knows which mode it's in -
  // this is just the New Ticket default, applied first.
  document.getElementById("booking_status").value = "Confirmed";
  document.getElementById("booking_status").disabled = true;
  fillPlain(document.getElementById("travel_type"), OPT.travelTypes, "Select...");
  fillPlain(document.getElementById("payment_mode"), OPT.paymentModes, "Select...");

  // Airline Code/Name on the Sector modal load from a real XML master at
  // runtime (assets/data/Airlinenames.xml, same convention as
  // india-states.xml) - feeds the two datalists so typing a letter in
  // either field shows matching airlines, and picking/typing an exact
  // code or name auto-fills the other (see sector-airline-code/name
  // "input" listeners below).
  let airlineList = []; // [{code, name}], deduped by code
  async function loadAirlinesFromXml() {
    const codeOptions = document.getElementById("sector-airline-code-options");
    const nameOptions = document.getElementById("sector-airline-name-options");
    try {
      const res = await fetch("assets/data/Airlinenames.xml");
      if (!res.ok) throw new Error(`Could not fetch Airlinenames.xml (${res.status})`);
      const xmlText = await res.text();
      const xml = new DOMParser().parseFromString(xmlText, "application/xml");
      if (xml.querySelector("parsererror")) throw new Error("Airlinenames.xml is not valid XML");
      const seen = new Set();
      airlineList = Array.from(xml.querySelectorAll("AIRLINEDET")).reduce((acc, el) => {
        const code = (el.querySelector("_CODE")?.textContent || "").trim().toUpperCase().replace(/\*$/, "");
        const name = (el.querySelector("_NAME")?.textContent || "").trim();
        if (code && name && !seen.has(code)) { seen.add(code); acc.push({ code, name }); }
        return acc;
      }, []).sort((a, b) => a.code.localeCompare(b.code));
      codeOptions.innerHTML = airlineList.map((a) => `<option value="${a.code}">${a.name}</option>`).join("");
      nameOptions.innerHTML = airlineList.map((a) => `<option value="${a.name}">${a.code}</option>`).join("");
    } catch (err) {
      console.error("Could not load airlines from XML:", err);
    }
  }
  await loadAirlinesFromXml();
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
    // Five independent lookups, each its own fetch into its own
    // module-level variable/DOM - no cross-dependency, so they used to run
    // one after another (5 round trips back to back) for no reason. Now
    // parallel, same technique as the customers/suppliers fetch above -
    // this runs on every ticket-entry.html load (New Ticket/Reschedule/
    // Cancellation alike), so it was real, repeated dead time on every one.
    await Promise.all([
      populateVoucherTypeOptions(companyId),
      populateFopOptions(companyId),
      populatePgOptions(companyId),
      populateMappedFieldNames(companyId),
      populateCompanyState(companyId),
    ]);
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
    // modal-reschedule-penalty deliberately NOT listed here - it's one
    // shared DOM input repurposed for two genuinely different Master
    // Mapping fields depending on mode (Reschedule's own "Supplier
    // Reschedule Penalty A/c" vs Cancellation's own separate "Supplier
    // Cancellation Penalty A/c" - scoped to the Cancellation page only,
    // 2026-10-07), so a single static field-name string here can't cover
    // both - handled inline in the "input" listener below instead.
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
    const fieldName = e.target.id === "modal-reschedule-penalty"
      ? (cancellationMode ? "Supplier Cancellation Penalty A/c" : "Supplier Reschedule Penalty A/c")
      : JV_GUARDED_FIELDS[e.target.id];
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
    // Cancellation only ever posts against a Credit Note - narrow the
    // dropdown to just that category in that mode (New Ticket/Reschedule
    // keep seeing every active voucher type, same as before).
    const activeNames = voucherTypes
      .filter((vt) => vt.is_active)
      .filter((vt) => !cancellationMode || vt.voucher_category === "Credit Note")
      .map((vt) => vt.name);
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
      if (rule.calc_type === "Flat") {
        // % field stays at 0 (set by updateSuppDiscValueLabel below) - the
        // flat amount itself goes straight into Commission Amount, same
        // split as everywhere else Flat is handled.
        document.getElementById("modal-supp-comm-computed").value = fmtN(rule.flat_amt);
      } else {
        document.getElementById("modal-supp-comm-value").value = Number(rule.calc_pct).toFixed(2);
      }
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
  // Clamp the Invoice Date / Booking Ref Date calendar pickers to the
  // active company's current financial year (Apr-Mar for India, Jan-Dec
  // for everywhere else, e.g. UAE - see activeCountry) and never later
  // than today, so an out-of-range date can't be picked in the first
  // place (checkNotFutureAndInFY still guards submit for older browsers /
  // typed-in values). Runs once immediately (activeCountry isn't known
  // yet at this point, so it assumes India - corrected below the moment
  // the real company/country resolves) and again on every company switch.
  function isCalendarYearCountry() {
    return !!activeCountry && activeCountry !== "IN";
  }
  // Jan-Dec countries: the FY "year" is just the date's own year. Apr-Mar
  // (India, default): a date in Jan-Mar belongs to the FY that started
  // the PREVIOUS calendar year.
  function fyYearFor(d) {
    if (isCalendarYearCountry()) return d.getFullYear();
    return d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1;
  }
  function fyStartForYear(fyYear) {
    return isCalendarYearCountry() ? new Date(fyYear, 0, 1) : new Date(fyYear, 3, 1);
  }
  function applyFYDatePickerLimits() {
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const fyStart = fyStartForYear(fyYearFor(today));
    const min = toISODate(fyStart), max = toISODate(today);
    ["invoice_date", "booking_ref_date"].forEach((id) => {
      const native = document.querySelector(`#${id} .dg-native`);
      if (native) { native.min = min; native.max = max; }
    });
  }
  applyFYDatePickerLimits();
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
    const fyYear = fyYearFor(d);
    const fyStart = fyStartForYear(fyYear);
    const fyEnd = isCalendarYearCountry() ? new Date(fyYear, 11, 31) : new Date(fyYear + 1, 2, 31);
    if (d < fyStart || d > fyEnd) {
      return `${label} must be within the current financial year (${isCalendarYearCountry() ? "Jan-Dec" : "Apr-Mar"}).`;
    }
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
    // Cancellation's cumulative TDS across a reschedule chain isn't a
    // single rate x amount (each level had its own rate - see
    // views._resolve_parent_chain_line) - when set, this already-summed
    // real amount overrides the normal Amount x Rate derivation below.
    const tds = p.tds_amount_override != null ? p.tds_amount_override : discount * (p.tds_per / 100);
    // GST Amount = each Client Accounting fee component times its OWN
    // mapped ledger's GST% (Master Mapping), not one flat GST% typed on
    // the line - see fieldLedgerGstPct above. Same formula regardless of
    // Payment Mode - PG Charges never contributes to GST Amount.
    const gst = p.service_fee * ((fieldLedgerGstPct["Service Fee A/c"] || 0) / 100)
      + p.addl_service_fee * ((fieldLedgerGstPct["Addl Service Fee A/c"] || 0) / 100)
      + p.ssr_service_fee * ((fieldLedgerGstPct["SSR Service Fee A/c"] || 0) / 100);
    // Supplier GST Amount - same convention as Customer GST Amount above
    // (2026-10-07): each Supplier fee component times its OWN mapped
    // ledger's GST% (Master Mapping - "Supplier Service Fee A/c"/
    // "Supplier Addl Service Fee A/c"), not one flat rate hand-typed on
    // the line. supp_gst_pct is no longer read here - see computeSuppLine.
    const suppGst = (p.supp_service_fee || 0) * ((fieldLedgerGstPct["Supplier Service Fee A/c"] || 0) / 100)
      + (p.supp_addl_service_fee || 0) * ((fieldLedgerGstPct["Supplier Addl Service Fee A/c"] || 0) / 100);
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
    // Same cumulative-chain override as computeFareLine's own TDS above.
    const tds = p.supp_tds_amount_override != null ? p.supp_tds_amount_override : commission * (p.supp_tds_per / 100);
    const gst = (p.supp_service_fee || 0) * ((fieldLedgerGstPct["Supplier Service Fee A/c"] || 0) / 100)
      + (p.supp_addl_service_fee || 0) * ((fieldLedgerGstPct["Supplier Addl Service Fee A/c"] || 0) / 100);
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
    agent_penalty: 0, reschedule_penalty: 0, cancellation_penalty: 0,
  });

  // Money amounts only (Basic Fare, Taxes, Markup, Service Fee, GST
  // Amount, Total, etc.) - follows Company Master's "No. of Decimals".
  // Percentages (GST %, TDS %, ROE, Discount %) stay fixed at 2 decimals
  // and keep using .toFixed(2) directly - they're rates, not currency.
  function fmtN(v) { return (Number(v) || 0).toFixed(VoyagerUtil.getDecimalPlaces()); }

  function updateDiscValueLabel() {
    const type = document.getElementById("modal-disc-type").value;
    const isPct = type === "Percentage";
    // Both tabs now use the same merged/compact DOM layout (see
    // applyRescheduleTab/layoutAcctFieldsForReschedule, always called with
    // true in reschedule mode) - this used to only be true for the
    // Reschedule tab specifically, back when Parent PNR Details still used
    // the separate "default" layout. Leaving this gated on the active tab
    // left Parent PNR Details showing its redundant "Discount %"/
    // "Commission %" label crammed into the tiny %-box meant for just a
    // number, overflowing and squeezing the real Amount/TDS/Taxable/GST
    // boxes next to it out of view. Cancellation mode uses this same
    // merged layout too (see openFareModal) - same reasoning applies.
    const inReschedLayout = rescheduleMode || cancellationMode;
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
    // Both tabs share this merged layout now - see the same note in
    // updateDiscValueLabel() above. Cancellation mode too.
    const inReschedLayout = rescheduleMode || cancellationMode;
    document.getElementById("modal-supp-comm-value-field").style.display = "contents";
    document.getElementById("modal-supp-comm-val-label").style.display = inReschedLayout ? "none" : "";
    document.getElementById("modal-supp-comm-value").disabled = !isPct || viewMode;
    // Flat has no meaningful percentage - show 0 rather than echoing the
    // flat Commission Amount into a field labeled "Commission %" (same
    // reasoning as Discount's own equivalent reset above).
    if (!isPct) document.getElementById("modal-supp-comm-value").value = "0.00";
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
      // Flat has no % field of its own (it's shown as 0, same as
      // Discount) - the flat amount is read straight from Commission
      // Amount instead.
      supp_comm_value: document.getElementById("modal-supp-comm-type").value === "Flat"
        ? num("modal-supp-comm-computed") : num("modal-supp-comm-value"),
      supp_tds_per: num("modal-supp-tds-per"),
      supp_markup: num("modal-supp-markup"), supp_addl_markup: num("modal-supp-addl-markup"),
      supp_service_fee: num("modal-supp-service-fee"), supp_addl_service_fee: num("modal-supp-addl-service-fee"),
      supp_gst_pct: num("modal-supp-gst-pct"),
      agent_penalty: num("modal-agent-penalty"),
      // Same one input, repurposed - see openFareModal's cancellationMode
      // branch. Only one of these two is ever actually shown/meaningful
      // at a time (the two modes are mutually exclusive), the other
      // always reads 0 so neither gets double-counted in the Total.
      reschedule_penalty: cancellationMode ? 0 : num("modal-reschedule-penalty"),
      cancellation_penalty: cancellationMode ? num("modal-reschedule-penalty") : 0,
      // original_ticket_line_id/reschedule_line_id have no modal field of
      // their own - carry them forward from whatever THIS passenger
      // (passengers[editingIndex]) already had (set by
      // enterRescheduleMode/enterSavedRescheduleMode when the modal first
      // opened), so editing a passenger's fare via Save & Apply never
      // drops its link back to its own original ticket line / chain
      // position - each passenger can point at a different line, so this
      // must read the ONE being edited, not a single shared value.
      ...(rescheduleMode && passengers[editingIndex] ? {
        original_ticket_line_id: passengers[editingIndex].original_ticket_line_id,
        reschedule_line_id: passengers[editingIndex].reschedule_line_id,
      } : {}),
      // No DOM field holds these (auto-fetched cumulative TDS across the
      // cancelled chain, see enterCancellationMode/computeFareLine) - carry
      // them forward from the stored passenger so every live recalc here
      // keeps using the real summed amount, not the disabled 0% rate.
      ...(cancellationMode && passengers[editingIndex] ? {
        // No DOM field either - THE critical one. Base Fare/Markup/
        // Service Fee are now editable in Cancellation mode (see
        // openFareModal's cancellationMode branch), so Save & Apply here
        // is a real, expected action now, not a rare edge case - without
        // carrying `id` forward, modal-save-btn's own `passengers[
        // editingIndex] = p` (below) would silently wipe out this
        // passenger's own id, and the final Cancellation save payload's
        // `line_id: p.id` would come out undefined, producing exactly
        // the "Could not resolve the original ticket line" error.
        id: passengers[editingIndex].id,
        original_ticket_line_id: passengers[editingIndex].original_ticket_line_id,
        tds_amount_override: passengers[editingIndex].tds_amount_override,
        supp_tds_amount_override: passengers[editingIndex].supp_tds_amount_override,
        // No DOM field either (set only by the Markup Reversal popup's
        // own Apply button, see openMarkupReversalModal) - needed here so
        // computeCancellationTotal always sees the latest committed sum.
        cust_markup_reversal: passengers[editingIndex].cust_markup_reversal,
        supp_markup_reversal: passengers[editingIndex].supp_markup_reversal,
        // Also no DOM field (informational-only chain totals feeding the
        // Markup Reversal popup's own checkbox amounts, plus the checkbox
        // state itself) - without carrying these forward too, clicking
        // Save & Apply on ANY field replaces passengers[editingIndex]
        // with this object (see modal-save-btn below), silently dropping
        // them so the popup shows 0.00/unchecked on the next open.
        chain_markup: passengers[editingIndex].chain_markup,
        chain_addl_markup: passengers[editingIndex].chain_addl_markup,
        chain_ssr_markup: passengers[editingIndex].chain_ssr_markup,
        chain_supp_markup: passengers[editingIndex].chain_supp_markup,
        chain_supp_addl_markup: passengers[editingIndex].chain_supp_addl_markup,
        cust_markup_reversal_checked: passengers[editingIndex].cust_markup_reversal_checked,
        supp_markup_reversal_checked: passengers[editingIndex].supp_markup_reversal_checked,
      } : {}),
    };
  }
  // Cancellation's own Total formula (2026-10-06 explicit spec) - a
  // refund/reversal view, not a billing total, so it's structured very
  // differently from computeFareLine's own `total` (which ADDS Markup/
  // Service Fee/GST since those are billed to the customer on a live
  // booking): everything the customer/supplier side would have earned
  // (Markup, Addl Markup, Service Fee, Addl Service Fee, GST Amount,
  // Agent/Cancellation Penalty) is SUBTRACTED back out, then whatever the
  // user picked via the Markup Reversal popups is added back on top.
  // Customer SSR Markup/SSR Service Fee are correctly absent (removed
  // from Cancellation entirely - see Progress update 14), and Supplier
  // Commission/Supplier TDS are correctly absent too (never part of
  // computeFareLine's own total either - commission isn't billed to the
  // customer). Only ever called in cancellationMode.
  function computeCancellationTotal(p) {
    const r = computeFareLine(p);
    const rs = computeSuppLine(p);
    return r.supplierCost
      - (p.supplier_penalty || 0)
      - r.discount + r.tds
      - (p.markup || 0) - (p.addl_markup || 0)
      - (p.service_fee || 0) - (p.addl_service_fee || 0)
      - (p.agent_penalty || 0)
      - r.gst
      - (p.supp_markup || 0) - (p.supp_addl_markup || 0)
      - (p.supp_service_fee || 0) - (p.supp_addl_service_fee || 0)
      - rs.gst
      - (p.cancellation_penalty || 0)
      + (p.cust_markup_reversal || 0) + (p.supp_markup_reversal || 0);
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
    if (cancellationMode) {
      document.getElementById("modal-total-computed").textContent = fmtN(computeCancellationTotal(p));
      updatePgCharges();
      return r;
    }
    // Same 4 penalties the pax table's own row Total already folds in
    // (see renderPaxTable's lineTotal) - only ever non-zero in reschedule/
    // cancellation mode, so this is a no-op for a normal, non-reschedule/
    // non-cancellation ticket.
    const penalties = (p.supplier_penalty || 0) + (p.reschedule_penalty || 0) + (p.agent_penalty || 0) + (p.cancellation_penalty || 0);
    document.getElementById("modal-total-computed").textContent = fmtN(r.total + penalties);
    updatePgCharges();
    return r;
  }

  // GST Amount calculation breakdown popup - view only, purely reads
  // whatever's already on screen/already computed elsewhere, doesn't
  // feed into any calculation itself. side picks Customer's 3 fee rows
  // (Service/Addl/SSR Service Fee) or Supplier's 2 (no SSR Service Fee
  // exists on the supplier side) - same shared modal/table, different rows,
  // same pattern as openMarkupReversalModal's own side param.
  function openGstDetailModal(side) {
    const p = readModalPassenger();
    const rows = side === "supplier" ? [
      { label: "Supplier Service Fee", amount: p.supp_service_fee, field: "Supplier Service Fee A/c" },
      { label: "Supplier Addl Service Fee", amount: p.supp_addl_service_fee, field: "Supplier Addl Service Fee A/c" },
    ] : [
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
  document.getElementById("modal-gst-detail-btn").addEventListener("click", () => openGstDetailModal("customer"));
  document.getElementById("modal-supp-gst-detail-btn").addEventListener("click", () => openGstDetailModal("supplier"));
  document.getElementById("gst-detail-close-x-btn").addEventListener("click", closeGstDetailModal);
  document.getElementById("gst-detail-ok-btn").addEventListener("click", closeGstDetailModal);

  // ============================================================
  // Cancellation mode ONLY - Markup Reversal selection popup. Unlike the
  // GST Amount popup above (pure view, never feeds back into anything),
  // this one lets the user pick which Markup components to reverse -
  // the checked rows' CUMULATIVE chain amounts (original booking + every
  // reschedule, see enterCancellationMode/views.cancellation_fare_totals)
  // sum into the Customer/Supplier Markup Reversal field back on the
  // main form. Shared by both eye icons - side ("customer"/"supplier")
  // picks which row set and which passenger field to target.
  // ============================================================
  let markupReversalSide = null;
  const MARKUP_REVERSAL_ROWS = {
    customer: [
      { key: "markup", label: "Customer Markup", amountField: "chain_markup" },
      { key: "addl_markup", label: "Customer Additional Markup", amountField: "chain_addl_markup" },
      { key: "ssr_markup", label: "Customer SSR Markup", amountField: "chain_ssr_markup" },
    ],
    supplier: [
      { key: "supp_markup", label: "Supplier Markup", amountField: "chain_supp_markup" },
      { key: "supp_addl_markup", label: "Supplier Additional Markup", amountField: "chain_supp_addl_markup" },
    ],
  };
  const markupReversalCheckedKey = (side) => (side === "customer" ? "cust_markup_reversal_checked" : "supp_markup_reversal_checked");
  const markupReversalTotalKey = (side) => (side === "customer" ? "cust_markup_reversal" : "supp_markup_reversal");
  const markupReversalFieldId = (side) => (side === "customer" ? "modal-cust-markup-reversal" : "modal-supp-markup-reversal");

  function computeMarkupReversalTotal(p, side) {
    const checked = p[markupReversalCheckedKey(side)] || {};
    return MARKUP_REVERSAL_ROWS[side].reduce((sum, row) => sum + (checked[row.key] ? (p[row.amountField] || 0) : 0), 0);
  }

  // Per-COMPONENT Markup Reversal amounts for the Cancellation Journal
  // Voucher backend (2026-10-07) - NOT the same thing as p.cust_markup_
  // reversal/p.supp_markup_reversal, which have meant the COMBINED total
  // (all checked rows summed, see computeMarkupReversalTotal/
  // computeCancellationTotal/the Summary grid's Markup Reversal column)
  // since this popup was first built - Cancellation_Al_TicketLines' own
  // cust_markup_reversal/supp_markup_reversal columns instead hold just
  // the "Markup" row's own amount (addl/SSR get their own separate
  // columns), one ledger-postable amount per JV line (see
  // views.CANCEL_JV_LINE_MAP rows 17-20/29-31). Used ONLY when building
  // the outgoing save/update payload below - never assigned onto the
  // passenger object itself, so every existing combined-total reader
  // (Total, Summary grid, pax table) is completely unaffected.
  function markupReversalComponents(p) {
    const custChecked = p.cust_markup_reversal_checked || {};
    const suppChecked = p.supp_markup_reversal_checked || {};
    return {
      cust_markup_reversal: custChecked.markup ? (p.chain_markup || 0) : 0,
      cust_addl_markup_reversal: custChecked.addl_markup ? (p.chain_addl_markup || 0) : 0,
      cust_ssr_markup_reversal: custChecked.ssr_markup ? (p.chain_ssr_markup || 0) : 0,
      supp_markup_reversal: suppChecked.supp_markup ? (p.chain_supp_markup || 0) : 0,
      supp_addl_markup_reversal: suppChecked.supp_addl_markup ? (p.chain_supp_addl_markup || 0) : 0,
    };
  }

  function openMarkupReversalModal(side) {
    markupReversalSide = side;
    const p = passengers[editingIndex];
    if (!p) return;
    const checked = p[markupReversalCheckedKey(side)] || {};
    document.getElementById("markup-reversal-title").textContent =
      side === "customer" ? "Customer Markup Reversal" : "Supplier Markup Reversal";
    document.getElementById("markup-reversal-tbody").innerHTML = MARKUP_REVERSAL_ROWS[side].map((row) => `
      <tr>
        <td>${row.label}</td>
        <td>${fmtN(p[row.amountField] || 0)}</td>
        <td style="text-align:center;"><input type="checkbox" class="markup-reversal-check" data-key="${row.key}" ${checked[row.key] ? "checked" : ""} /></td>
      </tr>
    `).join("");
    markupReversalModal.classList.add("open");
  }
  function closeMarkupReversalModal() { markupReversalModal.classList.remove("open"); }
  document.getElementById("modal-cust-markup-reversal-btn").addEventListener("click", () => openMarkupReversalModal("customer"));
  document.getElementById("modal-supp-markup-reversal-btn").addEventListener("click", () => openMarkupReversalModal("supplier"));
  document.getElementById("markup-reversal-close-x-btn").addEventListener("click", closeMarkupReversalModal);
  document.getElementById("markup-reversal-cancel-btn").addEventListener("click", closeMarkupReversalModal);
  document.getElementById("markup-reversal-apply-btn").addEventListener("click", () => {
    const side = markupReversalSide;
    const p = passengers[editingIndex];
    if (!p || !side) { closeMarkupReversalModal(); return; }
    const checked = {};
    document.querySelectorAll("#markup-reversal-tbody .markup-reversal-check").forEach((cb) => { checked[cb.dataset.key] = cb.checked; });
    p[markupReversalCheckedKey(side)] = checked;
    p[markupReversalTotalKey(side)] = computeMarkupReversalTotal(p, side);
    document.getElementById(markupReversalFieldId(side)).textContent = fmtN(p[markupReversalTotalKey(side)]);
    // Feeds into computeCancellationTotal - re-run so the modal's own
    // Total reflects the just-applied reversal immediately.
    recalcModalTotal();
    closeMarkupReversalModal();
  });

  function recalcSuppTotal(opts) {
    const p = readModalPassenger();
    const r = computeSuppLine(p);
    if (!opts || !opts.skipComputed) {
      document.getElementById("modal-supp-comm-computed").value = fmtN(r.commission);
    }
    document.getElementById("modal-supp-tds-computed").textContent = fmtN(r.tds);
    document.getElementById("modal-supp-gst-computed").textContent = fmtN(r.gst);
    // Taxable Amount - display-only, not used in any calculation. Same
    // convention as the Customer card's own modal-taxable-amount.
    document.getElementById("modal-supp-taxable-amount").textContent =
      fmtN((p.supp_service_fee || 0) + (p.supp_addl_service_fee || 0));
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
    // Cancellation mode ONLY - see openMarkupReversalModal. Harmless to
    // always set (their rows stay hidden outside Cancellation mode).
    document.getElementById("modal-cust-markup-reversal").textContent = fmtN(p.cust_markup_reversal || 0);
    document.getElementById("modal-supp-markup-reversal").textContent = fmtN(p.supp_markup_reversal || 0);
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
    document.getElementById("modal-supp-comm-value").value = p.supp_comm_type === "Flat" ? "0.00" : Number(p.supp_comm_value || 0).toFixed(2);
    // Flat's real amount lives in Commission Amount (same reasoning as
    // Discount's own Flat handling above) - seed it here so recalcSuppTotal()
    // below doesn't derive the commission from a still-blank Amount field.
    if (p.supp_comm_type === "Flat") document.getElementById("modal-supp-comm-computed").value = fmtN(p.supp_comm_value || 0);
    document.getElementById("modal-supp-tds-per").value = Number(p.supp_tds_per || 0).toFixed(2);
    document.getElementById("modal-supp-markup").value = fmtN(p.supp_markup || 0);
    document.getElementById("modal-supp-addl-markup").value = fmtN(p.supp_addl_markup || 0);
    document.getElementById("modal-supp-service-fee").value = fmtN(p.supp_service_fee || 0);
    document.getElementById("modal-supp-addl-service-fee").value = fmtN(p.supp_addl_service_fee || 0);
    document.getElementById("modal-supp-gst-pct").value = Number(p.supp_gst_pct || 0).toFixed(2);
    document.getElementById("modal-agent-penalty").value = fmtN(p.agent_penalty || 0);
    // Same one input, repurposed for Cancellation Penalty in cancellation
    // mode - see openFareModal/readModalPassenger.
    document.getElementById("modal-reschedule-penalty").value = fmtN(cancellationMode ? (p.cancellation_penalty || 0) : (p.reschedule_penalty || 0));
    // Whatever's already saved counts as a deliberate choice - don't let a
    // later Client Accounting edit silently clobber it. Only a brand-new
    // (blank) passenger starts in "follow Client Accounting" mode.
    suppCommOverridden = !!(p.supp_comm_on || p.supp_comm_type || p.supp_comm_value);
    updateDiscValueLabel();
    updateSuppDiscValueLabel();
    recalcModalTotal();
    recalcSuppTotal();
  }
  // Auto-fills a brand-new passenger's FARE fields only (Base Fare & Tax
  // Components + Customer/Supplier accounting cards) from the FIRST
  // existing passenger of the same Pax Type already in the register -
  // e.g. the 2nd Adult copies the 1st Adult's fares, the 2nd Child copies
  // the 1st Child's (not the Adult's). Deliberately leaves every non-fare
  // field alone (Pax Name, Ticket No, Sector, Office ID, Supplier, FOP,
  // Card Number, Airline Category - those are set once when the modal first
  // opens, see openFareModal's own newPaxDefaults) - those still need
  // entering/confirming once per passenger, not per Pax Type pick. Only
  // runs for a brand-new passenger (never while editing an already-saved
  // one) - covers both Booking and Reschedule now (2026-10-07; previously
  // excluded Reschedule entirely).
  function applyFareTemplate(t) {
    document.getElementById("modal-basic-fare").value = fmtN(t.basic_fare);
    document.getElementById("modal-yq").value = fmtN(t.yq); document.getElementById("modal-yr").value = fmtN(t.yr);
    document.getElementById("modal-k3").value = fmtN(t.k3_tax); document.getElementById("modal-tax-others").value = fmtN(t.tax_others);
    document.getElementById("modal-seat").value = fmtN(t.seat); document.getElementById("modal-meal").value = fmtN(t.meal);
    document.getElementById("modal-baggage").value = fmtN(t.baggage); document.getElementById("modal-other-ssr").value = fmtN(t.other_ssr);
    document.getElementById("modal-disc-on").value = t.disc_on; document.getElementById("modal-disc-type").value = t.disc_type;
    document.getElementById("modal-disc-value").value = t.disc_type === "Flat" ? "0.00" : Number(t.disc_value).toFixed(2);
    if (t.disc_type === "Flat") document.getElementById("modal-disc-computed").value = fmtN(t.disc_value);
    document.getElementById("modal-tds-per").value = Number(t.tds_per).toFixed(2);
    document.getElementById("modal-markup").value = fmtN(t.markup); document.getElementById("modal-addl-markup").value = fmtN(t.addl_markup);
    document.getElementById("modal-ssr-markup").value = fmtN(t.ssr_markup || 0);
    document.getElementById("modal-service-fee").value = fmtN(t.service_fee); document.getElementById("modal-addl-service-fee").value = fmtN(t.addl_service_fee);
    document.getElementById("modal-ssr-service-fee").value = fmtN(t.ssr_service_fee || 0);
    document.getElementById("modal-supp-comm-on").value = t.supp_comm_on || "";
    document.getElementById("modal-supp-comm-type").value = t.supp_comm_type || "";
    document.getElementById("modal-supp-comm-value").value = t.supp_comm_type === "Flat" ? "0.00" : Number(t.supp_comm_value || 0).toFixed(2);
    if (t.supp_comm_type === "Flat") document.getElementById("modal-supp-comm-computed").value = fmtN(t.supp_comm_value || 0);
    document.getElementById("modal-supp-tds-per").value = Number(t.supp_tds_per || 0).toFixed(2);
    document.getElementById("modal-supp-markup").value = fmtN(t.supp_markup || 0);
    document.getElementById("modal-supp-addl-markup").value = fmtN(t.supp_addl_markup || 0);
    document.getElementById("modal-supp-service-fee").value = fmtN(t.supp_service_fee || 0);
    document.getElementById("modal-supp-addl-service-fee").value = fmtN(t.supp_addl_service_fee || 0);
    document.getElementById("modal-supp-gst-pct").value = Number(t.supp_gst_pct || 0).toFixed(2);
    suppCommOverridden = !!(t.supp_comm_on || t.supp_comm_type || t.supp_comm_value);
    updateDiscValueLabel();
    updateSuppDiscValueLabel();
    recalcModalTotal();
    recalcSuppTotal();
  }
  document.getElementById("modal-pax-type").addEventListener("change", (e) => {
    if (cancellationMode || editingIndex !== null) return;
    // Always reacts, even when no passenger of the newly-picked type exists
    // yet (or the dropdown is cleared back to "Select...") - falls back to
    // blankPassenger() (all-zero/blank) rather than silently leaving
    // whatever the PREVIOUS Pax Type's fare figures were sitting there.
    // That "frozen at the first type ever picked" staleness was the exact
    // bug reported: picking Adult correctly pulled the 1st Adult's fares,
    // but switching to Child then left those Adult figures in place instead
    // of clearing/refetching, since the old code only ever acted when a
    // real match was found.
    const template = e.target.value ? passengers.find((p) => p.pax_type === e.target.value) : null;
    applyFareTemplate(template || blankPassenger());
  });
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
    // Flat's real amount lives in the Amount field now, not the % field
    // (see updateSuppDiscValueLabel/readModalPassenger) - without this,
    // syncing Flat from Client Accounting would leave Commission Amount
    // pointing at whatever stale value it had before, not Discount's.
    if (document.getElementById("modal-disc-type").value === "Flat") {
      document.getElementById("modal-supp-comm-computed").value = document.getElementById("modal-disc-computed").value;
    }
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
    // Flat reads straight from this Amount field (see readModalPassenger)
    // - the % field just stays at 0, same as Discount's own equivalent
    // listener never echoes the flat amount back into its % field either.
    if (type === "Percentage") {
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
  // Keeps the Reschedule fare modal's right column (Base Fare + Customer/
  // Supplier cards) the SAME overall height on both the Parent and
  // Reschedule tabs, so switching tabs never visibly shrinks/grows the
  // popup - measured live off the actual rendered content instead of a
  // hand-picked spacer height (which drifts out of sync every time a
  // field gets added/removed from either tab's layout). Tracks the
  // tallest height seen so far for THIS modal session (reset in
  // openFareModal) and clamps both tabs to it.
  let modalMinColHeight = 0;
  function syncModalHeight() {
    if (!rescheduleMode) return;
    const col = document.querySelector("#fare-breakdown-modal .dom-modal-col-right");
    if (!col) return;
    col.style.minHeight = "";
    const h = col.scrollHeight;
    if (h > modalMinColHeight) modalMinColHeight = h;
    col.style.minHeight = `${modalMinColHeight}px`;
  }

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
    syncModalHeight();
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
    // Travel Date can never be earlier than Booking Ref Date - the ticket
    // is issued against that booking reference, so travel can't predate
    // it. Blocks picking an earlier date in the calendar itself (checked
    // again at Save for a typed-in value - see sector-save-btn below).
    const travelDateNative = document.getElementById("sector-travel-date").querySelector(".dg-native");
    const bookingRefIso = toISOFromDDMMYYYY(getDateGroupValue(document.getElementById("booking_ref_date")));
    if (travelDateNative) travelDateNative.min = bookingRefIso || "";
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
  // Auto-fill the other field once the typed value exactly matches a
  // known airline (via the datalist pick, or a typed-then-matched code/
  // name) - case-insensitive on code, exact on name since names repeat
  // less predictably in casing.
  document.getElementById("sector-airline-code").addEventListener("input", (e) => {
    const match = airlineList.find((a) => a.code === e.target.value.trim().toUpperCase());
    if (match) document.getElementById("sector-airline-name").value = match.name;
  });
  document.getElementById("sector-airline-name").addEventListener("input", (e) => {
    const typed = e.target.value.trim().toLowerCase();
    const match = airlineList.find((a) => a.name.toLowerCase() === typed);
    if (match) document.getElementById("sector-airline-code").value = match.code;
  });
  document.getElementById("modal-sector-box").addEventListener("click", (e) => {
    if (viewMode) return;
    if (e.target.closest(".dom-sector-chip") || e.target.closest("#modal-sector-add-btn")) return;
    openSectorModal(null);
  });
  document.getElementById("modal-sector-add-btn").addEventListener("click", () => { if (!viewMode) openSectorModal(null); });
  document.getElementById("sector-close-x-btn").addEventListener("click", closeSectorModal);
  document.getElementById("sector-cancel-btn").addEventListener("click", closeSectorModal);
  // Origin/Destination's CSS text-transform:uppercase is visual only - the
  // actual typed value stays lowercase until save()'s own .toUpperCase().
  // Forcing it live here keeps the real value capital the whole time it's
  // being typed, not just after Save.
  ["sector-from", "sector-to"].forEach((id) => {
    document.getElementById(id).addEventListener("input", (e) => {
      const pos = e.target.selectionStart;
      e.target.value = e.target.value.toUpperCase();
      e.target.setSelectionRange(pos, pos);
    });
  });
  document.getElementById("sector-save-btn").addEventListener("click", () => {
    const from = document.getElementById("sector-from").value.trim().toUpperCase();
    const to = document.getElementById("sector-to").value.trim().toUpperCase();
    if (!from || !to) { voyagerAlert("Sector From and To are both required."); return; }
    const travelDate = getDateGroupValue(document.getElementById("sector-travel-date"));
    // Backstop for a typed-in value - the calendar's own min (set in
    // openSectorModal) already blocks picking an earlier date, but a
    // native date input still lets someone type past that.
    const bookingRefDate = getDateGroupValue(document.getElementById("booking_ref_date"));
    const travelD = parseDDMMYYYY(travelDate), refD = parseDDMMYYYY(bookingRefDate);
    if (travelD && refD && travelD < refD) {
      voyagerAlert("Travel Date cannot be earlier than Booking Ref Date.");
      return;
    }
    const entry = {
      from, to,
      airlineCode: document.getElementById("sector-airline-code").value.trim().toUpperCase(),
      airlineName: document.getElementById("sector-airline-name").value.trim(),
      travelDate,
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
    // Fresh per passenger - a short passenger's Reschedule tab shouldn't be
    // forced to match a DIFFERENT, longer passenger's height from earlier
    // in this same session.
    modalMinColHeight = 0;
    document.getElementById("modal-pax-display").textContent = isNew ? `New Passenger #${passengers.length + 1}` : `Passenger #${index + 1}`;
    // Blanket enable/disable runs BEFORE writeModalPassenger, not after -
    // writeModalPassenger's own updateDiscValueLabel/updateSuppDiscValueLabel/
    // updateCardNumberField calls set the correct per-field disabled state
    // (e.g. Discount % only enabled when Discount Type = Percentage) as
    // their last step, so they need to run last and win, not get wiped back
    // to "everything enabled" by this blanket pass.
    document.querySelectorAll("#fare-breakdown-modal input, #fare-breakdown-modal select").forEach((el) => (el.disabled = viewMode));
    // A brand-new passenger (Booking/Reschedule only - Cancellation's own
    // passengers always come from the picked ticket, never hand-added)
    // starts as a copy of the FIRST already-entered passenger for the
    // flight/office/supplier fields only (Airline Category, Sector(s),
    // Office ID, Supplier, FOP, Card Number) - those are shared across the
    // whole booking regardless of who's travelling. Ticket No./Pax Name/
    // Pax Type and every FARE figure stay BLANK here on purpose - Pax Type
    // has no sensible single default (Adult/Child/Infant fares genuinely
    // differ) and the fare fields are instead filled dynamically the
    // moment a Pax Type is picked, by the existing modal-pax-type "change"
    // listener below (applyFareTemplate, keyed off the matching pax_type,
    // not just passenger #1 - see that listener for why it also now reacts
    // when no matching passenger exists yet). Still just a starting
    // default, not locked - every field stays fully editable afterward.
    const newPaxDefaults = (isNew && !cancellationMode && passengers.length > 0)
      ? {
          ...blankPassenger(),
          airline_code: passengers[0].airline_code, airline_name: passengers[0].airline_name,
          airline_category: passengers[0].airline_category, flight_no: passengers[0].flight_no,
          sector: passengers[0].sector, travel_date: passengers[0].travel_date,
          cabin: passengers[0].cabin, travel_class: passengers[0].travel_class, fare_type: passengers[0].fare_type,
          office_id: passengers[0].office_id, supplier_name: passengers[0].supplier_name,
          fop: passengers[0].fop, card_number: passengers[0].card_number,
        }
      : blankPassenger();
    writeModalPassenger(isNew ? newPaxDefaults : passengers[index]);
    document.getElementById("modal-save-btn").style.display = viewMode ? "none" : "";
    document.getElementById("modal-sector-add-btn").style.display = viewMode ? "none" : "";
    // Reschedule's tab bar replaces the plain titlebar entirely (it carries
    // its own close X) rather than sitting awkwardly under it.
    document.querySelector("#fare-breakdown-modal .dom-modal-titlebar").style.display = rescheduleMode ? "none" : "";
    document.getElementById("reschedule-tab-bar").style.display = rescheduleMode ? "" : "none";
    if (rescheduleMode) {
      renderAncestorTabs(index);
      applyRescheduleTab("reschedule");
    } else if (cancellationMode) {
      // No Parent/Reschedule tab bar here (cancellation has just the one
      // view, no chain to show) - just the same merged "resched" row
      // layout and the same penalty fields reused, since this is "like
      // Reschedule popup" per the request. Reschedule Penalty's own
      // label+field is repurposed as Cancellation Penalty here (see
      // readModalPassenger/writeModalPassenger) rather than adding a
      // separate field - the two modes are mutually exclusive, so the
      // one slot never needs to mean both at once.
      layoutAcctFieldsForReschedule(true);
      document.getElementById("modal-fare-supplier-penalty-field").style.display = "";
      document.getElementById("modal-reschedule-penalty-label").textContent = "Penalty Amount";
      // Customer Discount and Supplier Commission (incl. both their own
      // TDS) are auto-fetched from the booking/reschedule chain and stay
      // locked - re-opening this modal must never silently overwrite
      // these with the normal live Amount x Rate derivation (see
      // computeFareLine/computeSuppLine's own tds_amount_override/
      // supp_tds_amount_override handling, which assumes these are never
      // hand-edited). Both disabled (blocks focus/typing entirely) AND
      // readonly (belt-and-suspenders backup) are set - a select has no
      // readonly attribute, so setAttribute no-ops harmlessly there.
      //
      // Base Fare & Tax Components (incl. Supplier Penalty) are still
      // auto-fetched/summed the same way (see enterCancellationMode), but
      // 2026-10-06 (explicit follow-up) they're deliberately NOT locked -
      // the fetched total is only a starting default the user can
      // override by hand if the real cancellation amount differs.
      ["modal-disc-type", "modal-disc-on", "modal-disc-value", "modal-disc-computed", "modal-tds-per",
        "modal-supp-comm-type", "modal-supp-comm-on", "modal-supp-comm-value", "modal-supp-comm-computed",
        "modal-supp-tds-per"].forEach((id) => {
        const el = document.getElementById(id);
        el.disabled = true;
        el.setAttribute("readonly", "readonly");
      });
      // Markup Reversal rows - Cancellation only, hidden by default in
      // every other mode (see ticket-entry.html).
      document.getElementById("cx-cust-markup-reversal-row").style.display = "";
      document.getElementById("cx-supp-markup-reversal-row").style.display = "";
      // SSR Markup/SSR Service Fee are removed from Cancellation's fare
      // popup only (2026-10-06 request) - Booking/Reschedule still show
      // them, so these are hidden here rather than deleted from the
      // shared HTML. No supplier-side equivalent exists (Supplier's own
      // Markup/Service Fee rows are already just a dual, not a triple).
      ["modal-ssr-markup-label", "modal-ssr-markup", "modal-ssr-service-fee-label", "modal-ssr-service-fee"].forEach((id) => {
        document.getElementById(id).style.display = "none";
      });
      // With SSR Markup/SSR Service Fee hidden, their parent rows' 3rd
      // grid column pair sits empty (the shared .dom-acct-field-triple
      // CSS still reserves that track width), leaving a lopsided gap on
      // the right - re-flowing them to a 2-pair template here (same look
      // as every other dual row in this card) keeps the remaining
      // Markup/Addl Markup and Service Fee/Addl Service Fee fields filling
      // the row evenly, without moving them or any other row's position.
      ["cust-markup-row", "cust-service-fee-row"].forEach((id) => {
        document.getElementById(id).style.gridTemplateColumns = "84px 1fr 84px 1fr";
      });
    }
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
    const suppTaxable = document.getElementById("modal-supp-taxable-amount");
    const suppGstBtn = document.getElementById("modal-supp-gst-detail-btn");
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
      [discAmt, tdsAmt, suppCommAmt, suppTdsAmt].forEach((el) => {
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
      // modal-supp-gst-pct is intentionally left wherever it last was (its
      // original static HTML spot, hidden) - no longer shown/editable in
      // Reschedule/Cancellation mode either, same as the default layout.
      document.getElementById("resched-supp-taxable-slot").append(suppTaxable);
      document.getElementById("resched-supp-gst-slot").append(suppGstAmt, suppGstBtn);
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
      [discAmt, tdsAmt, suppCommAmt, suppTdsAmt].forEach((el) => {
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
      // modal-supp-gst-pct is intentionally left wherever it last was
      // (its original static HTML spot, hidden) - no longer shown/editable
      // anywhere, see acct-default-supp-gst-row.
      document.getElementById("default-supp-taxable-slot").append(suppTaxable);
      document.getElementById("default-supp-gst-slot").append(suppGstAmt, suppGstBtn);
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
  // Builds the extra per-ancestor-PNR tab buttons (one per entry in
  // rescheduleAncestorLevels[index], alongside the fixed Reschedule/Parent
  // ones already in the HTML) - rebuilt every time the modal opens since
  // a different passenger can have a different chain depth. Marked with
  // .reschedule-ancestor-tab-btn so old ones are easy to find and remove
  // before adding this passenger's own set.
  function renderAncestorTabs(index) {
    const bar = document.getElementById("reschedule-tab-bar");
    bar.querySelectorAll(".reschedule-ancestor-tab-btn").forEach((btn) => btn.remove());
    const levels = rescheduleAncestorLevels[index] || [];
    const closeBtn = document.getElementById("reschedule-tab-close-btn");
    levels.forEach((lvl, i) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "reschedule-tab-btn reschedule-ancestor-tab-btn";
      btn.dataset.tab = `ancestor-${i}`;
      btn.textContent = lvl.pnr || `Ancestor ${i + 1}`;
      bar.insertBefore(btn, closeBtn);
    });
  }
  function applyRescheduleTab(tab) {
    modalRescheduleTab = tab;
    // Both tabs now use the same "resched" layout (Supplier Penalty/Agent
    // Penalty/Reschedule Penalty rows included) - Parent PNR Details on a
    // chained (2nd+) reschedule carries real cumulative penalty totals
    // too (see _resolve_parent_chain_line on the backend), so it needs
    // the same fields visible as Reschedule PNR Details, not the plain
    // "default" layout a normal, non-reschedule ticket still uses.
    layoutAcctFieldsForReschedule(true);
    const isParent = tab === "parent";
    const ancestorMatch = /^ancestor-(\d+)$/.exec(tab);
    const ancestorLevel = ancestorMatch ? (rescheduleAncestorLevels[editingIndex] || [])[Number(ancestorMatch[1])] : null;
    const isAncestor = !!ancestorLevel;
    // Reschedule PNR Details is only actually editable when viewMode is
    // off (a saved reschedule ticket opens read-only first, same as any
    // other saved ticket, until Edit is clicked) - Parent PNR Details and
    // every per-ancestor-PNR tab stay frozen/read-only regardless, same
    // as always (both are a frozen reference, never what gets saved).
    const readOnly = isParent || isAncestor || viewMode;
    document.querySelectorAll("#fare-breakdown-modal input, #fare-breakdown-modal select").forEach((el) => (el.disabled = readOnly));
    // Whichever passenger row is currently open in the modal
    // (editingIndex, set by openFareModal) - each one can have its own
    // Parent/ancestor levels (see rescheduleParentPassengers/
    // rescheduleAncestorLevels).
    writeModalPassenger(isAncestor ? ancestorLevel.passenger : (isParent ? rescheduleParentPassengers[editingIndex] : passengers[editingIndex]));
    // Chained (2nd+) reschedule only - writeModalPassenger's own
    // recalcModalTotal/recalcSuppTotal above just derived TDS Amount from
    // Amount x tds_per (0 here, no single rate produced the true sum), so
    // it needs overriding with the real cumulative TDS the backend sent
    // instead (see buildParentPassengerFromLine/_resolve_parent_chain_line).
    // Never applies to an ancestor tab - each one's own standalone data
    // already carries its own real tds_per/tds_amount: null, so the
    // normal live Amount x Rate derivation above is already correct.
    if (isParent) {
      const pp = rescheduleParentPassengers[editingIndex];
      if (pp && pp.tds_amount != null) {
        document.getElementById("modal-tds-computed").textContent = fmtN(pp.tds_amount);
        // Bottom Total was computed with Customer TDS = 0 (tds_per is 0
        // here) - add back the real amount just applied above so Total
        // stays correct instead of understating it by this same amount.
        const totalEl = document.getElementById("modal-total-computed");
        totalEl.textContent = fmtN((parseFloat(totalEl.textContent) || 0) + pp.tds_amount);
      }
      if (pp && pp.supp_tds_amount != null) document.getElementById("modal-supp-tds-computed").textContent = fmtN(pp.supp_tds_amount);
    }
    // Supplier Penalty (Base Fare & Tax Components card) now shows on
    // every tab - on a first-ever reschedule, Parent PNR Details simply
    // shows 0.00 (the true original TicketLine has no such column), same
    // as Agent/Reschedule Penalty below.
    document.getElementById("modal-fare-supplier-penalty-field").style.display = "";
    document.getElementById("modal-sector-add-btn").style.display = readOnly ? "none" : "";
    // visibility (not display) - keeps their row's height reserved on the
    // Parent tab too, so switching tabs doesn't shrink/jump the modal.
    document.getElementById("modal-cancel-btn").style.visibility = readOnly ? "hidden" : "";
    document.getElementById("modal-save-btn").style.visibility = readOnly ? "hidden" : "";
    document.querySelectorAll(".reschedule-tab-btn").forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === tab));
    // Re-measure AFTER every visibility toggle above (Supplier Penalty
    // field, Add Sector/Cancel/Save buttons) - writeModalPassenger's own
    // syncModalHeight call (via renderSectorDetails) runs before these,
    // so it can't account for them.
    syncModalHeight();
  }
  // Event delegation (not a per-button listener) - the ancestor PNR
  // buttons are created fresh by renderAncestorTabs every time the modal
  // opens, so a one-time querySelectorAll+addEventListener pass at page
  // load would never see them.
  document.getElementById("reschedule-tab-bar").addEventListener("click", (e) => {
    const btn = e.target.closest(".reschedule-tab-btn");
    if (btn) applyRescheduleTab(btn.dataset.tab);
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
    // A real airline ticket number is exactly 10 digits - the BASE
    // number only, before any "-1"/"-2" passenger suffix this app
    // appends (e.g. "2204849820-1" is valid: base "2204849820" is 10,
    // the "-1" isn't counted against that limit).
    const ticketNoBase = p.ticket_no.includes("-") ? p.ticket_no.slice(0, p.ticket_no.lastIndexOf("-")) : p.ticket_no;
    if (ticketNoBase.length !== 10) { voyagerAlert("Ticket No. must be exactly 10 characters (not counting any -1/-2 passenger suffix)."); return; }
    if (!p.passenger_name) { voyagerAlert("Pax Name is required."); return; }
    // Mandatory in both New Ticket and Reschedule's own "Reschedule PNR
    // Details" tab (this same Save & Apply handler covers both flows) -
    // Supplier only ever gets filled via a valid Office ID lookup, so an
    // empty Supplier here means Office ID never actually matched one.
    if (!p.office_id) { voyagerAlert("Office ID is required."); return; }
    if (!p.supplier_name) { voyagerAlert("Supplier is required - enter a valid Office ID."); return; }
    const dupInList = passengers.some((x, i) => x.ticket_no === p.ticket_no && i !== editingIndex);
    // Cancellation mode deliberately carries the ORIGINAL ticket's own
    // ticket_no straight through (see enterCancellationMode - the whole
    // point of a cancellation line is that it matches the ticket being
    // cancelled), so it will always show up in existingTickets - that's
    // correct, not a real duplicate. This cross-check against the global
    // ticket list only makes sense for New Ticket/Reschedule, where a
    // passenger's ticket_no is expected to be genuinely new.
    const dupExisting = !cancellationMode && existingTickets.some((t) => t.ticket_no === p.ticket_no && String(t.id) !== String(editId));
    if (dupInList || dupExisting) { voyagerAlert("This Ticket Number is already used."); return; }

    if (editingIndex === null) {
      if (passengers.length >= MAX_PASSENGERS) { voyagerAlert(`Maximum ${MAX_PASSENGERS} passengers allowed per ticket.`); return; }
      passengers.push(p);
    } else {
      passengers[editingIndex] = p;
    }
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
    // is pointless and hidden entirely. Cancellation's own blank shell
    // has the same locked-register look (nothing to add/remove here
    // either, at least for this UI-only pass).
    // Viewing a saved ticket read-only has nothing to Remove either - same
    // reasoning as Reschedule/Cancellation above (2026-10-07).
    const actionTh = document.getElementById("pax-action-th");
    if (actionTh) actionTh.style.display = (rescheduleMode || cancellationMode || viewMode) ? "none" : "";

    const rowsHtml = passengers.map((p, i) => {
      const r = computeFareLine(p);
      const rs = computeSuppLine(p);
      // Other Taxes = everything besides Basic/YQ/K3/SSR (those already
      // have their own columns) - YR + Tax & Others, both Supplier and
      // Customer's Markup/Addl Markup/Service Fee/Addl Service Fee/GST,
      // Customer's SSR Markup/SSR Service Fee, Customer TDS minus Customer
      // Discount, plus Supplier/Reschedule/Agent/Cancellation Penalty.
      const penalties = (p.supplier_penalty || 0) + (p.reschedule_penalty || 0) + (p.agent_penalty || 0) + (p.cancellation_penalty || 0);
      let allTaxes, lineTotal;
      if (cancellationMode) {
        // Cancellation's own Other Taxes/Total formula (2026-10-06 explicit
        // spec) - a refund/reversal view, not a billing total (see
        // computeCancellationTotal's own comment for the full reasoning).
        // Other Taxes here is just that same Total minus the 4 fields that
        // already have their own dedicated columns (Basic Fare/YQ/K3/SSR),
        // so Basic+YQ+K3+SSR+Other Taxes still always equals Total exactly,
        // same invariant Booking/Reschedule's own formula below keeps.
        lineTotal = computeCancellationTotal(p);
        allTaxes = lineTotal - p.basic_fare - p.yq - p.k3_tax - (p.seat + p.meal + p.baggage + p.other_ssr);
      } else {
        allTaxes = p.yr + p.tax_others
          + (p.supp_markup || 0) + (p.supp_addl_markup || 0) + (p.supp_service_fee || 0) + (p.supp_addl_service_fee || 0) + rs.gst
          + p.markup + p.addl_markup + (p.ssr_markup || 0) + p.service_fee + p.addl_service_fee + (p.ssr_service_fee || 0)
          + r.gst - r.discount + r.tds + penalties;
        // Total = the fare-line total plus those same 3 penalties, so
        // Basic+YQ+K3+SSR+Other Taxes still always equals this Total exactly.
        lineTotal = r.total + penalties;
      }
      const z = (v) => fmtN(v);
      // Status column (2026-10-07) - Cancelled wins if a line is somehow
      // both (the two flags are independent, never mutually exclusive by a
      // DB constraint). Neither flag set (including New Ticket's own
      // still-unsaved rows and Reschedule/Cancellation's own passenger
      // objects, which carry neither at all) reads as "Live" (renamed from
      // "Confirmed" the same day, to not collide with Booking Status'
      // own "Confirmed" option - this column is about what's happened to
      // the LINE itself, not a copy of that header field).
      const statusLabel = p.canceled ? "Cancelled" : p.rescheduled ? "Rescheduled" : "Live";
      const statusColor = p.canceled ? "#DC2626" : p.rescheduled ? "#B45309" : "#16A34A";
      return `<tr class="pax-row" data-idx="${i}" title="${viewMode ? "Double-click to view" : "Double-click to edit"}">
        <td style="text-align:center;">${i + 1}</td><td>${p.ticket_no}</td><td>${p.airline_name || p.airline_code || "-"}</td>
        <td>${p.card_number || "-"}</td>
        <td>${p.passenger_name} <span style="color:#94A3B8;">(${p.pax_type || "-"})</span></td>
        <td style="color:${statusColor}; font-weight:700;">${statusLabel}</td>
        <td class="num">${z(p.basic_fare)}</td><td class="num">${z(p.yq)}</td><td class="num">${z(p.k3_tax)}</td>
        <td class="num">${z(p.seat + p.meal + p.baggage + p.other_ssr)}</td>
        <td class="num">${z(allTaxes)}</td><td class="num" style="font-weight:700;">${z(lineTotal)}</td>
        ${(rescheduleMode || cancellationMode || viewMode) ? "" : `<td style="text-align:center;">
          <button type="button" class="pax-circle-btn pax-circle-remove pax-remove-btn" data-idx="${i}" title="Remove passenger">REMOVE</button>
        </td>`}
      </tr>`;
    }).join("");

    // Trailing empty row - always present (unless in view mode, reschedule
    // mode, or at the 9-passenger cap) with a round "+" to add the next
    // passenger. This is the only place the "+" appears; once a passenger
    // is added the row it came from turns into a normal data row above
    // (its "+" is gone, only "-" remains) and this empty row shifts down
    // for the next one.
    const addRowHtml = (!viewMode && !rescheduleMode && !cancellationMode && !atCap) ? `<tr class="pax-row pax-add-row">
        <td colspan="12" style="text-align:center; padding:14px; font-size:11.5px;">
          ${passengers.length === 0
            ? 'No passengers added yet. Fill booking details above, then click <strong style="color:#3B6DB5;">ADD</strong> to add a passenger.'
            : "Click ADD to add another passenger."}
        </td>
        <td style="text-align:center;">
          <button type="button" class="pax-circle-btn pax-circle-add" id="pax-add-row-btn" title="Add passenger">ADD</button>
        </td>
      </tr>` : "";

    // Reschedule/Cancellation's own blank "awaiting a pick" shell (see
    // enterBlankRescheduleShell/enterBlankCancellationShell) - nothing to
    // show yet since no ticket has been picked, points at the "New"
    // button instead of the generic fallback message below.
    const blankRescheduleHtml = (rescheduleMode && !passengers.length)
      ? `<tr id="no-pax-row"><td colspan="12" style="text-align:center; padding:18px; color:#64748B; font-size:11.5px;">Click <strong style="color:#3B6DB5;">New</strong> below to find the ticket/passenger to reschedule.</td></tr>`
      : (cancellationMode && !passengers.length)
      ? `<tr id="no-pax-row"><td colspan="12" style="text-align:center; padding:18px; color:#64748B; font-size:11.5px;">Click <strong style="color:#3B6DB5;">New</strong> below to find the ticket/passenger to cancel.</td></tr>`
      : "";
    linesBody.innerHTML = rowsHtml + addRowHtml || blankRescheduleHtml || `<tr id="no-pax-row"><td colspan="13" style="text-align:center; padding:18px; color:#64748B; font-size:11.5px;">No passengers to show.</td></tr>`;

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
    updateDiscardButtonState();
  }

  // Discard has nothing to actually discard on a brand-new, still-empty
  // form (New Ticket/Reschedule/Cancellation alike, before the first
  // passenger is added) - blurred/disabled-looking (not just styling -
  // pointer-events:none via the same class also blocks the click) until
  // then, same "nothing to act on yet" signal already used elsewhere (see
  // addPaxFromRow's own passengers.length === 0 check). Re-evaluated
  // every renderPaxTable() call, so it un-blurs the moment a passenger is
  // added and re-blurs if the last one is removed.
  function updateDiscardButtonState() {
    const discardBtn = document.getElementById("cancel-link");
    if (!discardBtn) return;
    discardBtn.classList.toggle("is-disabled", passengers.length === 0);
  }

  function recalcSummary() {
    let basic = 0, taxes = 0, ssr = 0, discount = 0, tds = 0, markup = 0, serviceFee = 0, gst = 0, total = 0;
    let suppCommission = 0, suppTds = 0, suppMarkup = 0, suppServiceFee = 0, suppGst = 0;
    let agentPenalty = 0, reschedulePenalty = 0, supplierPenaltyField = 0;
    // Cancellation's own Purchase Cost formula (2026-10-06) needs the raw,
    // un-combined Supplier Markup/Addl Markup/Service Fee/Addl Service Fee
    // and Cancellation Penalty - Booking/Reschedule's own formula below
    // only ever needs them already summed together (suppMarkup/
    // suppServiceFee above).
    let suppMarkupRaw = 0, suppAddlMarkupRaw = 0, suppServiceFeeRaw = 0, suppAddlServiceFeeRaw = 0, cancellationPenalty = 0;
    // Same reasoning, Customer side - Cancellation's own Sales Cost
    // formula needs these un-combined too.
    let customerMarkupRaw = 0, customerAddlMarkupRaw = 0, customerServiceFeeRaw = 0, customerAddlServiceFeeRaw = 0;
    // Cancellation's own Purchase Cost/Sales Cost TOTAL (2026-10-06) are
    // each a per-passenger refund/reversal formula summed across every
    // passenger - not derivable from the other accumulators above (which
    // are themselves already column-specific sums), so each line's own
    // total is computed directly here, per passenger, using that same
    // passenger's own `r`/`rs` (computeFareLine/computeSuppLine - already
    // honor the chain's cumulative TDS override from update 11). Sales
    // Cost's own line here is exactly computeCancellationTotal(p) (update
    // 18) - same formula, just summed across every passenger instead of
    // shown per-row.
    let pcCancellationTotal = 0, scCancellationTotal = 0;
    // Summary grid's own "Markup Reversal" column (2026-10-06, Cancellation
    // only) - Purchase Cost's own row shows Supplier Markup Reversal alone,
    // Sales Cost's shows Customer Markup Reversal alone (2026-10-06
    // correction - NOT combined with Supplier's, unlike the Total
    // formula's own "+ Customer + Supplier" sum - see pc-markup-reversal/
    // sc-markup-reversal below).
    let supplierMarkupReversalTotal = 0, customerMarkupReversalTotal = 0;
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
      suppMarkupRaw += (p.supp_markup || 0); suppAddlMarkupRaw += (p.supp_addl_markup || 0);
      suppServiceFeeRaw += (p.supp_service_fee || 0); suppAddlServiceFeeRaw += (p.supp_addl_service_fee || 0);
      customerMarkupRaw += p.markup; customerAddlMarkupRaw += p.addl_markup;
      customerServiceFeeRaw += p.service_fee; customerAddlServiceFeeRaw += p.addl_service_fee;
      agentPenalty += (p.agent_penalty || 0); reschedulePenalty += (p.reschedule_penalty || 0);
      cancellationPenalty += (p.cancellation_penalty || 0);
      // p.supplier_penalty is the Base Fare & Tax Components card's own
      // field (distinct from reschedule_penalty above, the Supplier
      // accounting card's field).
      supplierPenaltyField += (p.supplier_penalty || 0);
      pcCancellationTotal += r.supplierCost
        - rs.commission + rs.tds
        - (p.supplier_penalty || 0)
        - (p.supp_markup || 0) - (p.supp_addl_markup || 0)
        - (p.supp_service_fee || 0) - (p.supp_addl_service_fee || 0)
        - rs.gst
        - (p.cancellation_penalty || 0)
        + (p.supp_markup_reversal || 0);
      scCancellationTotal += computeCancellationTotal(p);
      supplierMarkupReversalTotal += (p.supp_markup_reversal || 0);
      customerMarkupReversalTotal += (p.cust_markup_reversal || 0);
    });
    const purchaseTotal = basic + taxes + ssr - suppCommission + suppTds + suppMarkup + suppServiceFee + suppGst;
    // Purchase/Sales Cost's Other Taxes/Total columns fold in the
    // penalties (per the project owner's explicit formula); Earnings
    // below stays on the un-penalized purchaseTotal/total, same as always.
    // Cancellation's own Purchase Cost AND Sales Cost Other Taxes both
    // SUBTRACT Supplier Penalty instead of adding it (2026-10-06 spec,
    // confirmed the same formula applies to both rows).
    const pcTaxesDisplay = cancellationMode ? (taxes - supplierPenaltyField) : (taxes + supplierPenaltyField);
    const scTaxesDisplay = cancellationMode ? (taxes - supplierPenaltyField) : (taxes + supplierPenaltyField);
    // Cancellation's own Purchase Cost/Sales Cost Total (2026-10-06) are
    // each their own explicit refund/reversal formula (pcCancellationTotal/
    // scCancellationTotal, accumulated per-passenger above) - a completely
    // different shape from Booking/Reschedule's own Total (built from
    // already-column-summed accumulators), so these replace the whole
    // expression rather than adding one more term to it.
    const pcTotalDisplay = cancellationMode ? pcCancellationTotal : (purchaseTotal + reschedulePenalty + supplierPenaltyField);
    // Sales Cost Total = the per-line total (already folds in every
    // Supplier AND Customer fare component - see computeFareLine's own
    // `total`) plus Agent Penalty + Reschedule Penalty + Supplier Penalty.
    const scTotalDisplay = cancellationMode ? scCancellationTotal : (total + agentPenalty + reschedulePenalty + supplierPenaltyField);
    const z = (v) => fmtN(v);

    document.getElementById("pc-basic").textContent = z(basic);
    document.getElementById("pc-taxes").textContent = z(pcTaxesDisplay);
    document.getElementById("pc-ssr").textContent = z(ssr);
    document.getElementById("pc-disc").textContent = z(suppCommission);
    document.getElementById("pc-tds").textContent = z(suppTds);
    // Purchase Cost's Markup column additionally folds in Reschedule
    // Penalty for Booking/Reschedule - Cancellation's own formula
    // (2026-10-06, sign corrected from an earlier same-day revision -
    // Supplier Addl Markup is ADDED, not subtracted) folds in Cancellation
    // Penalty instead (not Reschedule Penalty, which is always 0 in
    // Cancellation mode anyway - see readModalPassenger).
    document.getElementById("pc-markup").textContent = z(
      cancellationMode ? (suppMarkupRaw + suppAddlMarkupRaw + cancellationPenalty) : (suppMarkup + reschedulePenalty)
    );
    // Cancellation's own Service Fee (sign corrected, same as Markup above
    // - Supplier Addl Service Fee is ADDED).
    document.getElementById("pc-sfee").textContent = z(cancellationMode ? (suppServiceFeeRaw + suppAddlServiceFeeRaw) : suppServiceFee);
    document.getElementById("pc-gst").textContent = z(suppGst);
    document.getElementById("pc-markup-reversal").textContent = z(supplierMarkupReversalTotal);
    document.getElementById("pc-total").textContent = z(pcTotalDisplay);

    document.getElementById("sc-basic").textContent = z(basic);
    document.getElementById("sc-taxes").textContent = z(scTaxesDisplay);
    document.getElementById("sc-ssr").textContent = z(ssr);
    document.getElementById("sc-disc").textContent = z(discount);
    document.getElementById("sc-tds").textContent = z(tds);
    // Sales Cost's Markup/Service Fee/GST Amount columns additionally fold
    // in the Purchase Cost side's own Markup/Service Fee/GST (plus Agent
    // Penalty on Markup) for Booking/Reschedule. Cancellation's own
    // formula (2026-10-06, sign corrected from an earlier same-day
    // revision - every Addl Markup/Addl Service Fee term is ADDED, not
    // subtracted) swaps Reschedule Penalty for Cancellation Penalty
    // (Reschedule Penalty is always 0 in Cancellation mode anyway - see
    // readModalPassenger) - GST Amount is unchanged either way (Supplier
    // GST + Customer GST is exactly `suppGst + gst` already, nothing to
    // branch).
    document.getElementById("sc-markup").textContent = z(
      cancellationMode
        ? (suppMarkupRaw + suppAddlMarkupRaw + cancellationPenalty + customerMarkupRaw + customerAddlMarkupRaw + agentPenalty)
        : (markup + suppMarkup + reschedulePenalty + agentPenalty)
    );
    document.getElementById("sc-sfee").textContent = z(
      cancellationMode
        ? (suppServiceFeeRaw + suppAddlServiceFeeRaw + customerServiceFeeRaw + customerAddlServiceFeeRaw)
        : (serviceFee + suppServiceFee)
    );
    document.getElementById("sc-gst").textContent = z(gst + suppGst);
    // Sales Cost's own Markup Reversal column is Customer Markup Reversal
    // ALONE (2026-10-06 correction) - not combined with Supplier's, unlike
    // the Total formula's own "+ Customer + Supplier" (update 31/32).
    document.getElementById("sc-markup-reversal").textContent = z(customerMarkupReversalTotal);
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
    // reschedule_line_id (chaining - this reschedule is itself based on a
    // PREVIOUS reschedule, not the original ticket) follows the same
    // pattern: a saved chained reschedule already carries its own from
    // reschedule_ticket_detail, a brand-new one falls back to the URL's
    // parent_reschedule_line_id (basedOnRescheduleLineId) - null/undefined
    // for an ordinary (non-chained) reschedule either way.
    const lines = passengers.map((p) => ({
      ...p,
      ...(rescheduleMode ? {
        original_ticket_line_id: p.original_ticket_line_id || Number(rescheduleLineId),
        reschedule_line_id: p.reschedule_line_id || (basedOnRescheduleLineId ? Number(basedOnRescheduleLineId) : null),
      } : {}),
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

  // ============================================================
  // Reschedule-only Journal Voucher (project owner's fixed 26-field spec,
  // 2026-09-30) - a completely separate preview path from loadJvPreview/
  // renderJvPreview above (Booking's own JV), which this never touches or
  // reuses data from. JV-1..JV-5 per Payment Mode + FOP:
  //   Topup+Cash -> JV-1 (Main only)
  //   Payment Gateway+Cash -> JV-2 (Main + PG Receipt)
  //   Topup+Own Card -> JV-3 (Main + FOP Payment)
  //   Topup+Client Card -> JV-4 (Main + FOP Payment)
  //   Payment Gateway+Own Card -> JV-5 (Main + PG Receipt)
  // Any other combination (e.g. Payment Gateway+Client Card, not covered
  // by the spec) shows Main only, same as JV-1.
  // ============================================================
  function jvTabForPaymentFop(paymentMode, fop) {
    if (paymentMode === "Topup" && fop === "Cash") return null;
    if (paymentMode === "Payment Gateway" && fop === "Cash") return "pg";
    if (paymentMode === "Topup" && fop === "Own Card") return "fop";
    if (paymentMode === "Topup" && fop === "Client Card") return "fop";
    if (paymentMode === "Payment Gateway" && fop === "Own Card") return "pg";
    return null;
  }

  // Main JV - now filters out zero-amount rows the same way renderJvPreview
  // (Booking's own) does, rather than always showing all 26 Main JV
  // fields even at zero. Still never shows the Booking JV's own
  // Balanced/Posted badge wording (a Reschedule JV is never "posted" -
  // no JournalVoucher is created for a reschedule ticket yet).
  async function renderRescheduleJvPreview(jv) {
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

    const paymentMode = document.getElementById("payment_mode").value;
    const p = passengers[0];
    const fop = p ? (p.fop || "Cash") : "Cash";
    const tab = jvTabForPaymentFop(paymentMode, fop);
    if (tab === "fop") {
      setJvTabVisible("pg", false);
      renderRescheduleFopPaymentTab(jv, fop, p);
      setJvTabVisible("fop", true);
    } else if (tab === "pg") {
      setJvTabVisible("fop", false);
      await renderReschedulePgReceiptTab(jv, p);
      setJvTabVisible("pg", true);
    } else {
      setJvTabVisible("fop", false);
      setJvTabVisible("pg", false);
    }
  }

  // FOP Payment tab (JV-3 Own Card / JV-4 Client Card) - Supplier's amount
  // already includes Supplier Penalty + Reschedule Penalty (see
  // _compute_reschedule_jv_lines' own supplier formula), reused as-is via
  // jv.accounts' "supplier" role rows. JV-3 credits the FOP Card's own
  // ledger; JV-4 credits Customer instead - both per spec.
  function renderRescheduleFopPaymentTab(jv, fopType, p) {
    const supplierRows = (jv.accounts || []).filter((a) => a.role === "supplier");
    let creditLedgerName;
    if (fopType === "Own Card") {
      const cardNumber = (p && p.card_number) || "";
      const card = fopMasterCards.find((c) => c.card_number === cardNumber);
      creditLedgerName = card ? (card.card_master_ledger_name || cardNumber) : (cardNumber || "FOP Card");
    } else {
      const customerRow = (jv.accounts || []).find((a) => a.role === "customer");
      creditLedgerName = customerRow ? customerRow.ledger_name : "Customer";
    }
    let i = 0;
    const debitRowsHtml = supplierRows.length
      ? supplierRows.map((a) => jvRowHtml(++i, a.ledger_name, a.credit, 0)).join("")
      : jvRowHtml(++i, "— (no supplier selected)", 0, 0);
    const totalAmount = supplierRows.reduce((sum, a) => sum + (a.credit || 0), 0);
    const creditRowHtml = jvRowHtml(++i, creditLedgerName, 0, totalAmount);
    document.getElementById("jv-fop-table-body").innerHTML = debitRowsHtml + creditRowHtml;
    document.getElementById("jv-fop-total-debit").textContent = fmtN(totalAmount);
    document.getElementById("jv-fop-total-credit").textContent = fmtN(totalAmount);
    document.getElementById("jv-tab-panel-fop").querySelector("table").parentElement.style.display = "";
    document.getElementById("jv-fop-empty").style.display = "none";
  }

  // PG Receipt tab (JV-2/JV-5) - per spec: Customer Credit, PG Charges
  // Credit, GST Credit (one row - no same/different-state CGST/SGST
  // split, that's a Booking-only convention), PG Platform Debit =
  // Customer + PG Charges + GST. Always shows all 4 rows even at zero.
  async function renderReschedulePgReceiptTab(jv, p) {
    const customerRow = (jv.accounts || []).find((a) => a.role === "customer");
    const creditAmount = customerRow ? (customerRow.debit || 0) : 0;
    const gatewayRef = document.getElementById("payment_gateway_ref").value;
    const gateway = await getPgEffective(gatewayRef);
    const pgLedgerName = gateway ? (gateway.payment_master_ledger_name || gatewayRef) : (gatewayRef || "PG Platform");
    const pgChargesLedgerName = gateway ? (gateway.pg_charges_master_ledger_name || "PG Charges") : "PG Charges";

    const pgChargesTotal = p ? (p.pg_charges || 0) : 0;
    const pgGstPct = gateway ? Number(gateway.pg_charges_master_ledger_gst_percentage) || 0 : 0;
    const pgGstTotal = Math.round(pgChargesTotal * pgGstPct / 100 * 100) / 100;
    if ((pgChargesTotal > 0 || pgGstTotal > 0) && gateway && !gateway.pg_charges_master_ledger_id) {
      warnUnmappedPgLedger(gatewayRef);
    }
    const debitAmount = creditAmount + pgChargesTotal + pgGstTotal;

    const rowsHtml =
      jvRowHtml(1, customerRow ? customerRow.ledger_name : "Customer", 0, creditAmount) +
      jvRowHtml(2, pgChargesLedgerName, 0, pgChargesTotal) +
      jvRowHtml(3, pgChargesLedgerName, 0, pgGstTotal) +
      jvRowHtml(4, pgLedgerName, debitAmount, 0);
    document.getElementById("jv-pg-table-body").innerHTML = rowsHtml;
    document.getElementById("jv-pg-total-debit").textContent = fmtN(debitAmount);
    document.getElementById("jv-pg-total-credit").textContent = fmtN(creditAmount + pgChargesTotal + pgGstTotal);
    document.getElementById("jv-tab-panel-pg").querySelector("table").parentElement.style.display = "";
    document.getElementById("jv-pg-empty").style.display = "none";
  }

  async function loadRescheduleJvPreview(showLoading) {
    primeJvHeaderFromInvoice();
    if (showLoading) {
      document.getElementById("jv-table-body").innerHTML = `<tr><td colspan="4" style="padding:10px;">Loading...</td></tr>`;
    }
    try {
      let res;
      if (editingRescheduleId) {
        res = await fetch(`${API_BASE}/reschedule-tickets/${editingRescheduleId}/jv-preview/?company_id=${activeCompanyId}`);
      } else {
        if (passengers.length === 0) throw new Error("Fill in the Reschedule PNR Details passenger to preview the JV.");
        res = await fetch(`${API_BASE}/reschedule-tickets/jv-preview-draft/`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(buildTicketPayload()),
        });
      }
      const jv = await res.json();
      if (!res.ok) throw new Error(jv.error || "Could not compute JV.");
      await renderRescheduleJvPreview(jv);
    } catch (err) {
      document.getElementById("jv-table-body").innerHTML = `<tr><td colspan="4" style="padding:10px; color:#DC2626;">${err.message}</td></tr>`;
    }
  }

  // ============================================================
  // Cancellation-only Journal Voucher (2026-10-07 explicit spec) - its own
  // separate preview path, same pattern as loadRescheduleJvPreview above
  // (which this never touches or reuses data from). JV-1/JV-2/JV-3 per
  // each line's own FOP (payment_mode is always "Top-up" on this screen):
  //   Cash        -> JV-1 (Main only)
  //   Own Card    -> JV-2 (Main + FOP Payment)
  //   Client Card -> JV-3 (Main + FOP Payment)
  // ============================================================
  function buildCancellationPreviewPayload() {
    return {
      company_id: activeCompanyId,
      customer_name: document.getElementById("customer").value,
      cancellation_reference: document.getElementById("booking_reference").value,
      cancellation_ref_date: toISOFromDDMMYYYY(getDateGroupValue(document.getElementById("booking_ref_date"))),
      invoice_date: toISOFromDDMMYYYY(getDateGroupValue(document.getElementById("invoice_date"))),
      airline_pnr: document.getElementById("airline_pnr_header").value,
      lines: passengers.map((p) => ({ ...p, line_id: p.id, ...markupReversalComponents(p) })),
    };
  }
  async function loadCancellationJvPreview(showLoading) {
    primeJvHeaderFromInvoice();
    if (showLoading) {
      document.getElementById("jv-table-body").innerHTML = `<tr><td colspan="4" style="padding:10px;">Loading...</td></tr>`;
    }
    try {
      let res;
      if (cxEditSavedCancellationId) {
        res = await fetch(`${API_BASE}/cancellation-tickets/${cxEditSavedCancellationId}/jv-preview/?company_id=${activeCompanyId}`);
      } else {
        if (passengers.length === 0) throw new Error("Pick a passenger (via New ->) to preview the JV.");
        res = await fetch("${API_BASE}/cancellation-tickets/jv-preview-draft/", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(buildCancellationPreviewPayload()),
        });
      }
      const jv = await res.json();
      if (!res.ok) throw new Error(jv.error || "Could not compute JV.");
      await renderCancellationJvPreview(jv);
    } catch (err) {
      document.getElementById("jv-table-body").innerHTML = `<tr><td colspan="4" style="padding:10px; color:#DC2626;">${err.message}</td></tr>`;
    }
  }

  // Main JV tab - same zero-row filtering as Booking/Reschedule's own
  // renderJvPreview/renderRescheduleJvPreview. Never shows the "Posted"
  // badge wording unless a real Cancellation Journal Voucher already
  // exists for this cancellation (jv.posted, from cancellation_jv_preview's
  // own JournalVoucher lookup).
  async function renderCancellationJvPreview(jv) {
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

    setJvTabVisible("pg", false); // Cancellation never has a PG Receipts tab - payment_mode is always Top-up here
    const fop = jv.fop || "Cash";
    if (fop === "Own Card" || fop === "Client Card") {
      renderCancellationFopPaymentTab(jv, fop, passengers[0]);
      setJvTabVisible("fop", true);
    } else {
      setJvTabVisible("fop", false);
    }
  }

  // FOP Payment tab (JV-2 Own Card / JV-3 Client Card) - per spec, the
  // Supplier role row(s) from the Main tab (jv.accounts, already the exact
  // Supplier formula amount, held in their own "debit" field since
  // Cancellation's Main JV posts Supplier as a DEBIT - the opposite of
  // Booking/Reschedule's own Credit convention) get CREDITED here instead
  // (netting the Main's own Debit to zero), while the FOP Card's own ledger
  // (Own Card) or Customer (Client Card) is DEBITED for the same total -
  // the exact mirror of renderRescheduleFopPaymentTab's Dr/Cr placement.
  function renderCancellationFopPaymentTab(jv, fopType, p) {
    const supplierRows = (jv.accounts || []).filter((a) => a.role === "supplier");
    let debitLedgerName;
    if (fopType === "Own Card") {
      const cardNumber = (p && p.card_number) || "";
      const card = fopMasterCards.find((c) => c.card_number === cardNumber);
      debitLedgerName = card ? (card.card_master_ledger_name || cardNumber) : (cardNumber || "FOP Card");
    } else {
      const customerRow = (jv.accounts || []).find((a) => a.role === "customer");
      debitLedgerName = customerRow ? customerRow.ledger_name : "Customer";
    }
    const totalAmount = supplierRows.reduce((sum, a) => sum + (a.debit || 0), 0);
    let i = 0;
    const debitRowHtml = jvRowHtml(++i, debitLedgerName, totalAmount, 0);
    const creditRowsHtml = supplierRows.length
      ? supplierRows.map((a) => jvRowHtml(++i, a.ledger_name, 0, a.debit)).join("")
      : jvRowHtml(++i, "— (no supplier selected)", 0, 0);
    document.getElementById("jv-fop-table-body").innerHTML = debitRowHtml + creditRowsHtml;
    document.getElementById("jv-fop-total-debit").textContent = fmtN(totalAmount);
    document.getElementById("jv-fop-total-credit").textContent = fmtN(totalAmount);
    document.getElementById("jv-tab-panel-fop").querySelector("table").parentElement.style.display = "";
    document.getElementById("jv-fop-empty").style.display = "none";
  }

  document.getElementById("jv-btn").addEventListener("click", () => {
    jvModal.classList.add("open");
    switchJvTab("voucher");
    if (cancellationMode) loadCancellationJvPreview(true);
    else if (rescheduleMode) loadRescheduleJvPreview(true);
    else loadJvPreview(true);
  });
  // Called after every passenger add/edit/delete/live-fare-edit - no-op
  // unless the JV modal is actually open, and skips the "Loading..." flicker
  // since it's re-fetching in the background while the user keeps typing.
  function maybeRefreshJvPreview() {
    if (!jvModal.classList.contains("open")) return;
    if (cancellationMode) loadCancellationJvPreview(false);
    else if (rescheduleMode) loadRescheduleJvPreview(false);
    else loadJvPreview(false);
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
    // Reschedule's own Find (opened from rescheduleMode, whether the
    // blank "awaiting a pick" shell or an already-loaded reschedule)
    // searches saved RescheduleAirlineTickets instead of plain Tickets -
    // same filter fields, different backend list, so picking a result
    // opens that reschedule, not the original booking it came from.
    // Cancellation's own Find (2026-10-06 request) searches saved
    // Cancellations instead - the whole point is to show ONLY already-
    // cancelled tickets here, not the full tickets list.
    const findApi = rescheduleMode
      ? `${API_BASE}/reschedule-tickets/list/?company_id=${activeCompanyId}`
      : cancellationMode
      ? `${API_BASE}/cancellation-tickets/list/?company_id=${activeCompanyId}`
      : `${API_BASE}/tickets/?company_id=${activeCompanyId}`;
    let rows = [];
    try {
      const res = await fetch(findApi);
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

    // One row per TICKET (or per reschedule ticket, in rescheduleMode),
    // not per passenger line - show the first passenger added (lowest
    // line id) as the representative row, so a ticket with several
    // passengers doesn't repeat its Invoice No/Booking Ref/PNR/Ticket No
    // for every one of them. reschedule_tickets_list rows all carry
    // ticket_id: null, so grouping by that alone would collapse every
    // reschedule into one row - reschedule_ticket_id is the real key here.
    const byTicket = new Map();
    filtered.forEach((r) => {
      const key = rescheduleMode ? r.reschedule_ticket_id : cancellationMode ? r.cancellation_ticket_id : r.ticket_id;
      const existing = byTicket.get(key);
      if (!existing || r.id < existing.id) byTicket.set(key, r);
    });
    const deduped = Array.from(byTicket.values());

    if (deduped.length === 0) {
      resultsBody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:14px; color:#64748B;">No matching ${rescheduleMode ? "reschedules" : cancellationMode ? "cancellations" : "tickets"} found.</td></tr>`;
      return;
    }
    // Clicking a Cancellation result (2026-10-06) opens that saved
    // Cancellation's own read-only view (enterSavedCancellationMode) - same
    // "click a Find row to open it" convention as Booking/Reschedule.
    resultsBody.innerHTML = deduped.map((r) => `
      <tr class="find-result-row" data-id="${rescheduleMode ? r.reschedule_ticket_id : cancellationMode ? r.cancellation_ticket_id : r.ticket_id}" style="cursor:pointer;">
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
        window.location.href = rescheduleMode
          ? `ticket-entry.html?reschedule_saved_id=${row.dataset.id}`
          : cancellationMode
          ? `ticket-entry.html?cancellation_saved_id=${row.dataset.id}`
          : `ticket-entry.html?id=${row.dataset.id}`;
      });
    });
  }
  document.getElementById("find-btn").addEventListener("click", () => {
    findModal.querySelector(".dom-modal-titlebar > div").textContent =
      rescheduleMode ? "Find Reschedule" : cancellationMode ? "Find Cancellation" : "Find Ticket";
    findModal.classList.add("open");
    document.getElementById("find-results-body").innerHTML = `<tr><td colspan="7" style="text-align:center; padding:14px; color:#64748B;">Enter a filter above and click Search.</td></tr>`;
  });
  document.getElementById("find-close-x-btn").addEventListener("click", () => findModal.classList.remove("open"));
  document.getElementById("find-search-btn").addEventListener("click", runFindSearch);
  // Scoped to whichever .dom-date-type-toggle group the clicked button
  // actually belongs to (not hardcoded to "find-date-type") - this page
  // now has 3 of these (Find, Reschedule's and Cancellation's own "New"
  // lookup modals, see runLookupModalSearch below), each needs its own
  // independent active-state/dataset.
  document.querySelectorAll(".dom-date-type-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const group = btn.closest(".dom-date-type-toggle");
      group.querySelectorAll(".dom-date-type-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      group.dataset.value = btn.dataset.value;
    });
  });
  ["find-invoice-number", "find-booking-ref", "find-airline-pnr", "find-gds-pnr", "find-ticket-no",
    "find-customer-name", "find-airline-code", "find-date-from", "find-date-to"].forEach((id) => {
    document.getElementById(id).addEventListener("keydown", (e) => { if (e.key === "Enter") runFindSearch(); });
  });

  // ============================================================
  // Shared by Cancellation's and Reschedule's own "New" lookup modal -
  // same full filter set as the generic Find modal above, but always
  // searches plain Tickets (the whole point here is finding the ORIGINAL
  // ticket to reschedule/cancel, never a saved Reschedule/Cancellation
  // itself). 2026-10-07 follow-up request: NO intermediate results grid -
  // clicking the button resolves the filters straight to the matching
  // ticket and goes directly to the next popup (onPick, the existing
  // rsLookupTicketForReschedule/cxLookupTicketForCancellation - those
  // already read their own ticket_no field, which this sets first) rather
  // than listing matches for the user to click one.
  // ============================================================
  async function runLookupModalSearch(prefix, onPick) {
    const invoiceQ = document.getElementById(`${prefix}-f-invoice-number`).value.trim().toLowerCase();
    const bookingQ = document.getElementById(`${prefix}-search-spnr`).value.trim().toLowerCase();
    const airlinePnrQ = document.getElementById(`${prefix}-search-airline-pnr`).value.trim().toLowerCase();
    const gdsPnrQ = document.getElementById(`${prefix}-f-gds-pnr`).value.trim().toLowerCase();
    const ticketNoQ = document.getElementById(`${prefix}-search-ticket-no`).value.trim().toLowerCase();
    const customerQ = document.getElementById(`${prefix}-f-customer-name`).value.trim().toLowerCase();
    const airlineCodeQ = document.getElementById(`${prefix}-f-airline-code`).value.trim().toLowerCase();
    const dateType = document.getElementById(`${prefix}-f-date-type`).dataset.value;
    const dateFrom = document.getElementById(`${prefix}-f-date-from`).value;
    const dateTo = document.getElementById(`${prefix}-f-date-to`).value;

    // Unlike the generic Find modal, an entirely empty search here would
    // just match every ticket in the company - at least one filter is
    // required.
    if (!invoiceQ && !bookingQ && !airlinePnrQ && !gdsPnrQ && !ticketNoQ && !customerQ && !airlineCodeQ && !dateFrom && !dateTo) {
      voyagerAlert("Enter at least one filter before searching.");
      return;
    }

    // Original tickets AND saved reschedules - a passenger already
    // rescheduled once lives on the reschedule now, so its own new Booking
    // Ref/PNR must be searchable too (chained reschedule/cancellation).
    let rows = [];
    try {
      const [tRes, rRes] = await Promise.all([
        fetch(`${API_BASE}/tickets/?company_id=${activeCompanyId}`),
        fetch(`${API_BASE}/reschedule-tickets/list/?company_id=${activeCompanyId}`),
      ]);
      const tRows = tRes.ok ? await tRes.json() : [];
      const rRows = rRes.ok ? await rRes.json() : [];
      rows = [...tRows, ...rRows];
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

    // One match per ticket/reschedule (keyed so a ticket and a reschedule
    // never collide), with a passenger count for the results grid.
    const byTicket = new Map();
    filtered.forEach((r) => {
      const key = r.reschedule_ticket_id ? `r${r.reschedule_ticket_id}` : `t${r.ticket_id}`;
      const existing = byTicket.get(key);
      if (!existing) byTicket.set(key, { row: r, paxCount: 1 });
      else {
        existing.paxCount += 1;
        if (r.id < existing.row.id) existing.row = r;
      }
    });
    const deduped = Array.from(byTicket.values());

    const wrap = document.getElementById(`${prefix}-results-wrap`);
    const body = document.getElementById(`${prefix}-results-body`);
    wrap.style.display = "none";
    body.innerHTML = "";

    if (deduped.length === 0) {
      voyagerAlert("No matching ticket found.");
      return;
    }

    // Ticket No as the ONLY filter typed identifies one specific passenger
    // (show just that one); anything else resolves to a whole ticket and
    // shows every passenger on it.
    const ticketNoOnly = !!ticketNoQ && !invoiceQ && !bookingQ && !airlinePnrQ && !gdsPnrQ && !customerQ && !airlineCodeQ && !dateFrom && !dateTo;
    // Looks the picked ticket up by its own Booking Ref (unique per ticket/
    // reschedule, and the backend's S PNR search returns every eligible
    // passenger on it) - or by Ticket No when that was the only filter.
    const pick = (row) => onPick({
      sPnr: ticketNoOnly ? "" : (row.booking_reference || ""),
      airlinePnr: "",
      ticketNo: ticketNoOnly ? (row.ticket_no || "") : "",
      ticketNoOnly,
    });

    if (deduped.length === 1) {
      pick(deduped[0].row);
      return;
    }

    body.innerHTML = deduped.map(({ row, paxCount }, i) => `
      <tr class="lookup-result-row" data-idx="${i}" style="cursor:pointer; border-bottom:1px solid #E2E8F0;">
        <td style="padding:5px 8px;">${row.invoice_number || "-"}</td>
        <td style="padding:5px 8px;">${row.booking_reference || "-"}</td>
        <td style="padding:5px 8px;">${row.airline_pnr || "-"}</td>
        <td style="padding:5px 8px;">${row.customer_name || "-"}</td>
        <td style="padding:5px 8px;">${row.airline_name || row.airline_code || "-"}</td>
        <td style="padding:5px 8px;">${paxCount}</td>
      </tr>`).join("");
    body.querySelectorAll(".lookup-result-row").forEach((tr) => {
      tr.addEventListener("mouseenter", () => { tr.style.background = "#E0EAF8"; });
      tr.addEventListener("mouseleave", () => { tr.style.background = ""; });
      tr.addEventListener("click", () => pick(deduped[Number(tr.dataset.idx)].row));
    });
    wrap.style.display = "";
  }
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
      // Status column (renderPaxTable) - this explicit field list never
      // included these two, so they were always undefined here even
      // though views.ticket_detail has sent them correctly all along -
      // the Status column showed "-" for every line regardless of its
      // real state (2026-10-07 bug fix).
      rescheduled: l.rescheduled, canceled: l.canceled,
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
    applyReportBackLink("Tickets");
    document.getElementById("edit-ticket-btn").style.display = "";
  }

  // Wherever a saved ticket/reschedule was opened FROM (a report row, the
  // Reschedule lookup screen, or nowhere in particular) is where "Discard"
  // should go back TO, rather than always landing on the same hardcoded
  // place regardless of entry point. document.referrer is whatever page
  // actually navigated here - checked against every report this can be
  // opened from; falls back to defaultLabel/defaultHref when it doesn't
  // match any of them (e.g. opened fresh from a bookmark, or via the
  // Reschedule lookup screen's own "Saved" radio).
  const REPORT_BACK_TARGETS = [
    { match: "report-day-book.html", label: "Day Book" },
    { match: "report-ledger-book.html", label: "Ledger" },
    { match: "report-dsr-airline-booking.html", label: "DSR" },
  ];
  function applyReportBackLink(defaultLabel, defaultHref) {
    const backTarget = REPORT_BACK_TARGETS.find((r) => document.referrer.includes(r.match));
    const cancelLink = document.getElementById("cancel-link");
    if (backTarget) {
      cancelLink.textContent = `<- Back to ${backTarget.label}`;
      cancelLink.setAttribute("href", document.referrer);
    } else {
      cancelLink.textContent = `<- Back to ${defaultLabel}`;
      if (defaultHref) cancelLink.setAttribute("href", defaultHref);
    }
  }

  // Reschedule's own menu item lands here directly now (reschedule_new=1),
  // not on a separate search page - this is that blank "awaiting a pick"
  // shell: Booking Status frozen at Re-Scheduled, nothing else fillable
  // until "New" below is used to actually find a ticket/passenger.
  function enterBlankRescheduleShell() {
    rescheduleMode = true;
    document.getElementById("page-title").textContent = "Reschedule";
    document.getElementById("booking_status").value = "Re-Scheduled";
    document.getElementById("booking_status").disabled = true;
    // Nothing can actually be entered yet - there's no ticket to attach
    // any of this to until "New" picks one (confirmed 2026-10-07: this
    // was meant to be locked from the start, but the blank shell never
    // actually disabled anything before now - only booking_status above).
    document.querySelectorAll(".dom-form-grid input, .dom-form-grid select").forEach((el) => (el.disabled = true));
    document.getElementById("proceed-btn").style.display = "none";
    document.getElementById("submit-btn").style.display = "none";
    document.getElementById("reschedule-new-btn").style.display = "";
    renderPaxTable();
  }

  // Cancellation's own menu item lands here directly too (cancellation_
  // new=1), same blank "awaiting a pick" shell pattern as Reschedule
  // above - UI only for now (explicitly scoped this way): title, frozen
  // Booking Status, and the bottom toolbar's own "New" button all show
  // correctly, but that button has no real lookup/save logic wired yet.
  function enterBlankCancellationShell() {
    cancellationMode = true;
    document.getElementById("page-title").textContent = "Cancellation";
    document.getElementById("booking_status").value = "Normal Cancelled";
    document.getElementById("booking_status").disabled = true;
    // Re-render now that cancellationMode is true, so the dropdown only
    // offers Credit Note voucher types (see populateVoucherTypeOptions).
    if (activeCompanyId) populateVoucherTypeOptions(activeCompanyId);
    document.getElementById("payment_mode").value = "Top-up";
    document.getElementById("booking_reference_label").innerHTML = 'Cancellation Reference<span class="dom-req">*</span>';
    document.getElementById("booking_ref_date_label").innerHTML = 'Cancellation Ref Date<span class="dom-req">*</span>';
    document.getElementById("proceed-btn").style.display = "none";
    document.getElementById("submit-btn").style.display = "none";
    document.getElementById("cancellation-new-btn").style.display = "";
    document.getElementById("cancellation-save-btn").style.display = "none";
    // Summary grid's own Markup Reversal column - Cancellation only,
    // hidden by default in the shared HTML (see ticket-entry.html).
    document.querySelectorAll(".cx-summary-col").forEach((el) => { el.style.display = ""; });
    // Nothing can actually be entered yet - there's no ticket to attach
    // any of this to until "New" picks one (same fix as Reschedule's own
    // blank shell just above - confirmed 2026-10-07 this was meant to be
    // locked from the start, but never actually was).
    document.querySelectorAll(".dom-form-grid input, .dom-form-grid select").forEach((el) => (el.disabled = true));
    renderPaxTable();
  }
  // ============================================================
  // Cancellation "New" Lookup Modal - same pattern as the Reschedule
  // lookup modal below, opened via the "New" button on
  // enterBlankCancellationShell's empty form above. Finds the real
  // ticket to cancel by S PNR / Airline PNR / Ticket No, via its own
  // lookup-for-cancellation endpoint (no reschedule-eligibility
  // filtering - irrelevant for cancellation). Picking a passenger here
  // doesn't do anything beyond confirming the pick yet - the actual
  // cancel/save flow is a separate follow-up step, same as
  // enterBlankCancellationShell's own "New" button was before this.
  // ============================================================
  let cxLookupPassengers = [];
  let cxLookupMatchedLineId = null;
  let cxLookupTicketId = null;
  // Set only when the lookup matched a reschedule rather than the
  // original ticket (chaining - same convention as the reschedule
  // screen's own lookupSourceRescheduleId) - the frontend fetches full
  // details from THAT record instead of the original once this is set.
  let cxLookupSourceRescheduleId = null;
  const cancellationLookupModal = document.getElementById("cancellation-lookup-modal");
  // Separate popup (2026-10-07 request) for the Pax/Sector picker, opened
  // on top of cancellationLookupModal once a search result is picked -
  // previously grew inline inside that same search popup.
  const cancellationPaxModal = document.getElementById("cancellation-pax-modal");

  function openCancellationLookupModal() {
    ["cx-f-invoice-number", "cx-search-spnr", "cx-search-airline-pnr", "cx-f-gds-pnr", "cx-search-ticket-no",
      "cx-f-customer-name", "cx-f-airline-code", "cx-f-date-from", "cx-f-date-to"].forEach((id) => { document.getElementById(id).value = ""; });
    cxLookupPassengers = []; cxLookupMatchedLineId = null; cxLookupTicketId = null; cxLookupSourceRescheduleId = null;
    document.getElementById("cx-results-wrap").style.display = "none";
    document.getElementById("cx-results-body").innerHTML = "";
    cancellationPaxModal.classList.remove("open");
    cancellationLookupModal.classList.add("open");
  }
  function closeCancellationLookupModal() { cancellationLookupModal.classList.remove("open"); }
  document.getElementById("cancellation-new-btn").addEventListener("click", openCancellationLookupModal);
  document.getElementById("cx-lookup-close-x-btn").addEventListener("click", closeCancellationLookupModal);
  document.getElementById("cx-pax-close-x-btn").addEventListener("click", () => cancellationPaxModal.classList.remove("open"));

  async function cxLookupTicketForCancellation({ sPnr, airlinePnr, ticketNo, ticketNoOnly }) {
    if (!activeCompanyId) {
      voyagerAlert("Could not determine the active company. Check your connection and try Get again.");
      return;
    }
    if (!sPnr && !airlinePnr && !ticketNo) {
      voyagerAlert("Enter S PNR, Airline PNR or Ticket No to search.");
      return;
    }
    try {
      const params = new URLSearchParams({ company_id: activeCompanyId, s_pnr: sPnr, airline_pnr: airlinePnr, ticket_no: ticketNo });
      const res = await fetch(`${API_BASE}/tickets/lookup-for-cancellation/?${params}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Ticket not found.");
      cxLookupTicketId = data.ticket_id || null;
      cxLookupMatchedLineId = data.matched_line_id || null;
      cxLookupSourceRescheduleId = data.source_reschedule_ticket_id || null;
      // Same ticketNoOnly reasoning as rsLookupTicketForReschedule's own
      // copy of this comment - see there for the full explanation.
      cxLookupPassengers = (ticketNoOnly && cxLookupMatchedLineId)
        ? (data.passengers || []).filter((p) => p.line_id === cxLookupMatchedLineId)
        : (data.passengers || []);
      renderCxPassengers();
      // Opens as its own popup on top of the search modal (2026-10-07
      // request) instead of growing inline inside it.
      cancellationLookupModal.classList.remove("open");
      cancellationPaxModal.classList.add("open");
    } catch (err) {
      voyagerAlert(err.message || "Could not search for this ticket. Is the Django backend running?", { icon: "error" });
    }
  }
  document.getElementById("cx-get-btn").addEventListener("click", () => runLookupModalSearch("cx", cxLookupTicketForCancellation));
  ["cx-f-invoice-number", "cx-search-spnr", "cx-search-airline-pnr", "cx-f-gds-pnr", "cx-search-ticket-no",
    "cx-f-customer-name", "cx-f-airline-code", "cx-f-date-from", "cx-f-date-to"].forEach((id) => {
    document.getElementById(id).addEventListener("keydown", (e) => { if (e.key === "Enter") runLookupModalSearch("cx", cxLookupTicketForCancellation); });
  });

  function renderCxPassengers() {
    const tbody = document.getElementById("cx-pax-tbody");
    if (!cxLookupPassengers.length) {
      tbody.innerHTML = `<tr><td colspan="3" style="text-align:center; padding:1rem; color:#64748B;">No passengers on this ticket.</td></tr>`;
      renderCxSectors();
      return;
    }
    tbody.innerHTML = cxLookupPassengers.map((p, i) => `
      <tr>
        <td style="padding:4px 8px;"><input type="checkbox" class="cx-pax-check" data-idx="${i}" /></td>
        <td style="padding:4px 8px;">${p.pax_type || "-"}</td>
        <td style="padding:4px 8px;">${p.passenger_name || "-"}</td>
      </tr>
    `).join("");
    tbody.querySelectorAll(".cx-pax-check").forEach((cb) => cb.addEventListener("change", updateCxCancelButtonState));
    renderCxSectors();
  }
  // Shows every passenger's sectors right away, independent of the Pax
  // checkboxes - those only mark who's selected for cancellation, they
  // don't gate what's visible here.
  // Deduped by (sector, flight no, class, date) - same reasoning as
  // renderRsSectors' own copy of this fix (page-ticket-entry.js, 2026-10-07):
  // several passengers sharing the same sector showed it once per
  // passenger before, now once. Safe to dedupe - this checkbox list is
  // only a "have you reviewed the sector" gate (see updateCxCancelButtonState),
  // never read per-sector.
  function renderCxSectors() {
    const tbody = document.getElementById("cx-sector-tbody");
    const seen = new Set();
    const rows = [];
    cxLookupPassengers.forEach((p) => {
      (p.sectors || []).forEach((s) => {
        const key = `${s.sector || ""}|${s.flight_no || ""}|${s.travel_class || ""}|${s.travel_date || ""}`;
        if (seen.has(key)) return;
        seen.add(key);
        rows.push(`
          <tr>
            <td style="padding:4px 8px;"><input type="checkbox" class="cx-sector-check" /></td>
            <td style="padding:4px 8px;">${s.sector || "-"}</td>
            <td style="padding:4px 8px;">${s.flight_no || "-"}</td>
            <td style="padding:4px 8px;">${s.travel_class || "-"}</td>
            <td style="padding:4px 8px;">${s.travel_date || "-"}</td>
          </tr>
        `);
      });
    });
    tbody.innerHTML = rows.length
      ? rows.join("")
      : `<tr><td colspan="5" style="text-align:center; padding:1rem; color:#64748B;">Select a passenger to see their sectors.</td></tr>`;
    tbody.querySelectorAll(".cx-sector-check").forEach((cb) => cb.addEventListener("change", updateCxCancelButtonState));
    // A single passenger with a single sector is unambiguous - nothing
    // left to actually choose between, so both checkboxes are ticked
    // automatically instead of making the user click two checkboxes that
    // only ever have one possible answer. Multiple passengers and/or
    // multiple sectors still require a manual pick, same as before.
    if (cxLookupPassengers.length === 1 && rows.length === 1) {
      const onlyPaxCheck = document.querySelector(".cx-pax-check");
      if (onlyPaxCheck) onlyPaxCheck.checked = true;
      const onlySectorCheck = tbody.querySelector(".cx-sector-check");
      if (onlySectorCheck) onlySectorCheck.checked = true;
    }
    updateCxCancelButtonState();
  }
  // Cancel only makes sense once at least one passenger AND one of
  // their sectors is actually picked.
  function updateCxCancelButtonState() {
    const anyPax = document.querySelectorAll(".cx-pax-check:checked").length > 0;
    const anySector = document.querySelectorAll(".cx-sector-check:checked").length > 0;
    document.getElementById("cx-cancel-btn").disabled = !(anyPax && anySector);
  }
  document.getElementById("cx-cancel-btn").addEventListener("click", async () => {
    const checkedPax = Array.from(document.querySelectorAll(".cx-pax-check:checked"))
      .map((cb) => cxLookupPassengers[Number(cb.dataset.idx)]);
    if (!cxLookupTicketId || !checkedPax.length) return;
    const ticketId = cxLookupTicketId;
    const sourceRescheduleId = cxLookupSourceRescheduleId;
    closeCancellationLookupModal();
    cancellationPaxModal.classList.remove("open");
    await enterCancellationMode(ticketId, checkedPax, sourceRescheduleId);
  });

  // Set once enterCancellationMode loads a picked ticket - cxSaveTicketId
  // is always the TRUE original Ticket's own id (ticket_lookup_for_
  // cancellation already resolves this regardless of chaining), while
  // cxSaveSourceRescheduleId carries the reschedule id through to the
  // save payload so the backend can resolve each picked line's own TRUE
  // original_ticket_line_id when the passenger's live data actually came
  // from a reschedule instead.
  let cxSaveTicketId = null;
  let cxSaveSourceRescheduleId = null;
  // Set once enterSavedCancellationMode loads an already-saved Cancellation
  // (clicked from Find, see runFindSearch) - routes the save button to
  // cancellation-tickets/<id>/update/ instead of create/, and the Discard
  // link back to this same saved record instead of a blank shell.
  let cxEditSavedCancellationId = null;
  // Header fields that are genuinely this cancellation's OWN data - stay
  // editable both at creation (enterCancellationMode) and when editing an
  // already-saved one (the edit-ticket-btn handler below) - everything
  // else (Customer, original ticket link, etc.) is frozen either way.
  const CX_EDITABLE_HEADER_FIELD_IDS = new Set(["invoice_type", "payment_mode", "user_name", "booking_reference"]);

  // Loads the real picked ticket's own header + the picked passenger(s)
  // only (not every passenger on the ticket, same convention as
  // Reschedule's own picker) into the still-blank Cancellation form,
  // read-only - a frozen reference view, same as opening any saved
  // ticket to view, except for the handful of fields that are genuinely
  // this cancellation's own data (see the editable exclusion list below).
  // sourceRescheduleId (optional) - set when the lookup matched a
  // reschedule rather than the original ticket (chaining, any depth) -
  // fetches that record's own live data instead of the stale original.
  async function enterCancellationMode(ticketId, pickedPax, sourceRescheduleId) {
    try {
      const url = sourceRescheduleId
        ? `${API_BASE}/reschedule-tickets/${sourceRescheduleId}/?company_id=${activeCompanyId}`
        : `${API_BASE}/tickets/${ticketId}/?company_id=${activeCompanyId}`;
      const res = await fetch(url);
      const t = await res.json();
      if (!res.ok) throw new Error(t.error || "Ticket not found.");

      document.getElementById("invoice_number").value = t.invoice_number || "";
      // Invoice Date is the CANCELLATION date, not the original ticket's -
      // defaults to today and stays user-editable (see the exclusion list
      // below), same reasoning as Invoice Type/Payment Mode/User Name.
      setDateGroupValue(document.getElementById("invoice_date"), todayDDMMYYYY());
      // Not copied from the original ticket - that ticket's own Invoice
      // Type is never a Credit Note, which is all this dropdown now offers
      // (see populateVoucherTypeOptions) - left blank for a manual pick.
      document.getElementById("invoice_type").value = "";
      document.getElementById("booking_mode").value = t.booking_mode || "";
      document.getElementById("customer").value = t.customer_name || "";
      // Cancellation Reference/Ref Date are THIS cancellation's own new
      // reference and date, not the original booking's (which is why both
      // are marked required), but both stay EDITABLE (see the exclusion
      // list below) so the user can override either one. Reference
      // defaults to the original ticket's own Booking Reference as a
      // starting point (2026-10-06 - reversed from an earlier same-day
      // "leave blank" decision); Ref Date defaults to today (same
      // reasoning as Invoice Date, unchanged).
      document.getElementById("booking_reference").value = t.booking_reference || "";
      document.getElementById("booking_given_by").value = t.booking_given_by || "";
      document.getElementById("booking_type").value = t.booking_type || "";
      document.getElementById("travel_type").value = t.travel_type || "";
      // User Name is a manual choice for Cancellation, never auto-filled
      // from the original ticket.
      document.getElementById("user_name").value = "";
      document.getElementById("payment_mode").value = "Top-up";
      // Not copied from the original ticket - Payment Mode defaults to
      // Top-up (never Payment Gateway) here, so there's no gateway this
      // value would even apply to; updateGatewayRefField() below disables
      // the field accordingly.
      document.getElementById("payment_gateway_ref").value = "";
      updateGatewayRefField();
      document.getElementById("roe").value = t.roe;
      document.getElementById("airline_pnr_header").value = t.airline_pnr || "";
      document.getElementById("gds_pnr_header").value = t.gds_pnr || "";
      setDateGroupValue(document.getElementById("booking_ref_date"), todayDDMMYYYY());
      document.getElementById("customer").dispatchEvent(new Event("input"));
      // Frozen to Normal Cancelled regardless of the ticket's own current
      // status - same convention enterBlankCancellationShell already set,
      // just reasserted here since the blanket disable below would
      // otherwise re-enable it along with everything else.
      document.getElementById("booking_status").value = "Normal Cancelled";
      document.getElementById("booking_reference_label").innerHTML = 'Cancellation Reference<span class="dom-req">*</span>';
      document.getElementById("booking_ref_date_label").innerHTML = 'Cancellation Ref Date<span class="dom-req">*</span>';

      const pickedIds = new Set(pickedPax.map((p) => p.line_id));
      passengers = t.lines.filter((l) => pickedIds.has(l.id)).map((l) => ({ ...blankPassenger(), ...l }));

      // Base Fare & Tax Components, Customer Discount and Supplier
      // Commission (incl. their own TDS) must all show the CUMULATIVE
      // total across the whole chain being cancelled (original booking +
      // every reschedule up to and including the one picked), not just
      // this one record's own standalone figures - see
      // views.cancellation_fare_totals/_resolve_parent_chain_line.
      // Supplier Penalty is excluded from this auto-fetch (always 0),
      // per the explicit 2026-10-06 spec.
      try {
        const totalsReq = passengers.map((p) => ({
          original_ticket_line_id: sourceRescheduleId ? p.original_ticket_line_id : p.id,
          reschedule_line_id: sourceRescheduleId ? p.id : null,
        }));
        const totalsRes = await fetch("${API_BASE}/cancellation-tickets/fare-totals/", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ company_id: activeCompanyId, lines: totalsReq }),
        });
        const totalsData = await totalsRes.json();
        if (totalsRes.ok) {
          const totalsByOriginalId = new Map((totalsData.totals || []).map((x) => [x.original_ticket_line_id, x]));
          passengers = passengers.map((p) => {
            const key = sourceRescheduleId ? p.original_ticket_line_id : p.id;
            const tot = totalsByOriginalId.get(key);
            if (!tot || tot.error) return p;
            return {
              ...p, basic_fare: tot.basic_fare, yq: tot.yq, yr: tot.yr, k3_tax: tot.k3_tax,
              tax_others: tot.tax_others, seat: tot.seat, meal: tot.meal, baggage: tot.baggage,
              other_ssr: tot.other_ssr,
              disc_on: tot.disc_on, disc_type: tot.disc_type, disc_value: tot.disc_value,
              tds_per: tot.tds_per, tds_amount_override: tot.tds_amount,
              supp_comm_on: tot.supp_comm_on, supp_comm_type: tot.supp_comm_type, supp_comm_value: tot.supp_comm_value,
              supp_tds_per: tot.supp_tds_per, supp_tds_amount_override: tot.supp_tds_amount,
              // Informational only - feeds the Markup Reversal popup's
              // checkbox amounts (see openMarkupReversalModal). NOT shown
              // directly on any field - Markup/Addl Markup/SSR Markup
              // themselves are reset to 0 below, same as a fresh entry.
              chain_markup: tot.markup, chain_addl_markup: tot.addl_markup, chain_ssr_markup: tot.ssr_markup,
              chain_supp_markup: tot.supp_markup, chain_supp_addl_markup: tot.supp_addl_markup,
            };
          });
        }
      } catch (err) {
        // Non-fatal - falls back to the picked line's own standalone
        // Base Fare/Discount/Commission figures (still correct for a
        // never-rescheduled ticket) - the zero-reset below still applies
        // regardless.
      }

      // Markup/Addl Markup/SSR Markup/Service Fee/Addl Service Fee/SSR
      // Service Fee/Agent Penalty (customer side) and Markup/Addl Markup/
      // Service Fee/Addl Service Fee/GST %/Cancellation Penalty (supplier
      // side) are a fresh provisional entry for Cancellation, same as a
      // brand-new passenger - NOT carried over from the booking/reschedule
      // being cancelled (unlike Base Fare & Tax Components and Discount/
      // Commission above, which DO carry over/sum). Taxable Amount and
      // both GST Amounts are derived from these, so zeroing them here is
      // enough to zero those displays too - no separate reset needed.
      // Cancellation Penalty has no backend field of its own (never
      // populated from the fetched ticket/reschedule to begin with - see
      // readModalPassenger) but reschedule_penalty/supplier_penalty DO
      // exist on a fetched reschedule line, so those still need an
      // explicit reset. Scoped to Cancellation only - Booking/Reschedule
      // are untouched.
      passengers = passengers.map((p) => ({
        ...p,
        markup: 0, addl_markup: 0, ssr_markup: 0, service_fee: 0, addl_service_fee: 0, ssr_service_fee: 0, agent_penalty: 0,
        supp_markup: 0, supp_addl_markup: 0, supp_service_fee: 0, supp_addl_service_fee: 0, supp_gst_pct: 0,
        supplier_penalty: 0, reschedule_penalty: 0, cancellation_penalty: 0,
        // Markup Reversal - unchecked/zero until the user picks something
        // via the eye icon popup (see openMarkupReversalModal).
        cust_markup_reversal_checked: {}, cust_markup_reversal: 0,
        supp_markup_reversal_checked: {}, supp_markup_reversal: 0,
      }));
      renderPaxTable();

      // Frozen/read-only reference, same as any saved ticket opened to
      // view - except the handful of fields that are genuinely this
      // cancellation's OWN data (Invoice Date, Invoice Type, Payment Mode,
      // User Name, Cancellation Reference/Ref Date), which stay editable
      // for the user to fill in themselves.
      // Explicit true/false either way (not just adding disables) - undoes
      // enterBlankCancellationShell's own blanket disable (nothing was
      // editable while still "awaiting a pick"), same reasoning as
      // enterRescheduleMode's own re-enable.
      document.querySelectorAll(".dom-form-grid input, .dom-form-grid select").forEach((el) => {
        el.disabled = !CX_EDITABLE_HEADER_FIELD_IDS.has(el.id);
      });
      document.querySelector("#invoice_date .dg-native").disabled = false;
      document.querySelector("#booking_ref_date .dg-native").disabled = false;

      cxSaveTicketId = ticketId;
      cxSaveSourceRescheduleId = sourceRescheduleId || null;
      document.getElementById("cancellation-save-btn").style.display = "";
      // Once a ticket/passenger is picked, re-opening the lookup to pick
      // a DIFFERENT one mid-flow would leave the form in a confusing,
      // half-swapped state (register still showing the old pick's lines) -
      // hidden until Discard starts the whole page over, same reasoning
      // "New" being hidden after a Ticket/Reschedule is saved already has.
      document.getElementById("cancellation-new-btn").style.display = "none";
    } catch (err) {
      voyagerAlert(err.message || "Could not load this ticket. Is the Django backend running?", { icon: "error" });
    }
  }

  // Saves the Cancellation record via its own independent endpoint -
  // record-keeping only, no Journal Voucher is posted (unlike Reschedule's
  // own auto-posted JV) - see views.cancellation_ticket_create.
  document.getElementById("cancellation-save-btn").addEventListener("click", async () => {
    // Editing an already-saved Cancellation (Edit button unlocked it -
    // see edit-ticket-btn's own cancellationMode branch) hits update/
    // instead of create/, same "same button, different endpoint" pattern
    // Booking/Reschedule's own Save Ticket already uses.
    if (cxEditSavedCancellationId) {
      const invoiceType = document.getElementById("invoice_type").value.trim();
      if (!invoiceType) { voyagerAlert("Pick an Invoice Type (Credit Note) before saving."); return; }
      if (!document.getElementById("user_name").value.trim()) { voyagerAlert("Pick a User Name before saving."); return; }
      const payload = {
        company_id: activeCompanyId,
        invoice_number: document.getElementById("invoice_number").value,
        invoice_date: toISOFromDDMMYYYY(getDateGroupValue(document.getElementById("invoice_date"))),
        invoice_type: invoiceType,
        user_name: document.getElementById("user_name").value,
        payment_mode: document.getElementById("payment_mode").value,
        payment_gateway_ref: document.getElementById("payment_gateway_ref").value,
        cancellation_reference: document.getElementById("booking_reference").value,
        cancellation_ref_date: toISOFromDDMMYYYY(getDateGroupValue(document.getElementById("booking_ref_date"))),
        lines: passengers.map((p) => ({ ...p, id: p.id, ...markupReversalComponents(p) })),
      };
      try {
        const res = await fetch(`${API_BASE}/cancellation-tickets/${cxEditSavedCancellationId}/update/`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
        });
        const result = await res.json();
        if (!res.ok) throw new Error(result.error || "Could not update this cancellation.");
        window.location.href = `ticket-entry.html?cancellation_saved_id=${cxEditSavedCancellationId}`;
      } catch (err) {
        voyagerAlert(err.message || "Could not update this cancellation. Is the Django backend running?", { icon: "error" });
      }
      return;
    }

    if (!cxSaveTicketId || !passengers.length) return;
    const invoiceType = document.getElementById("invoice_type").value.trim();
    if (!invoiceType) { voyagerAlert("Pick an Invoice Type (Credit Note) before saving."); return; }
    if (!document.getElementById("user_name").value.trim()) { voyagerAlert("Pick a User Name before saving."); return; }

    const payload = {
      company_id: activeCompanyId,
      original_ticket_id: cxSaveTicketId,
      source_reschedule_ticket_id: cxSaveSourceRescheduleId,
      customer_name: document.getElementById("customer").value,
      invoice_number: document.getElementById("invoice_number").value,
      invoice_date: toISOFromDDMMYYYY(getDateGroupValue(document.getElementById("invoice_date"))),
      invoice_type: invoiceType,
      booking_mode: document.getElementById("booking_mode").value,
      booking_type: document.getElementById("booking_type").value,
      booking_status: "Normal Cancelled",
      travel_type: document.getElementById("travel_type").value,
      user_name: document.getElementById("user_name").value,
      booking_given_by: document.getElementById("booking_given_by").value,
      cancellation_reference: document.getElementById("booking_reference").value,
      cancellation_ref_date: toISOFromDDMMYYYY(getDateGroupValue(document.getElementById("booking_ref_date"))),
      airline_pnr: document.getElementById("airline_pnr_header").value,
      gds_pnr: document.getElementById("gds_pnr_header").value,
      payment_mode: document.getElementById("payment_mode").value,
      payment_gateway_ref: document.getElementById("payment_gateway_ref").value,
      lines: passengers.map((p) => ({ ...p, line_id: p.id, ...markupReversalComponents(p) })),
    };

    try {
      const res = await fetch("${API_BASE}/cancellation-tickets/create/", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      const result = await res.json();
      if (!res.ok) throw new Error(result.error || "Could not save this cancellation.");
      window.VoyagerEntry.showToast(result.message || "Cancellation saved.", "ticket-entry.html");
    } catch (err) {
      voyagerAlert(err.message || "Could not save this cancellation. Is the Django backend running?", { icon: "error" });
    }
  });

  // Loads an already-saved Cancellation (clicked from Cancellation's own
  // "Find" popup, see runFindSearch's cancellationMode branch) - read-only
  // first (Edit unlocks the same fields editable at creation time), same
  // spirit as enterSavedRescheduleMode but much simpler (no chain/Parent
  // PNR Details to reconstruct).
  function enterSavedCancellationMode(ct) {
    cancellationMode = true;
    viewMode = true;
    cxEditSavedCancellationId = ct.id;
    const extraPaxSuffix = ct.lines.length > 1 ? ` +${ct.lines.length - 1} more` : "";
    document.getElementById("page-title").textContent =
      `View Cancellation - ${ct.lines[0]?.ticket_no || ct.invoice_number} (${ct.lines[0]?.passenger_name || ""})${extraPaxSuffix}`;
    document.getElementById("booking_reference_label").innerHTML = "Cancellation Reference";
    document.getElementById("booking_ref_date_label").innerHTML = "Cancellation Ref Date";
    document.getElementById("invoice_number").value = ct.invoice_number || "";
    setDateGroupValue(document.getElementById("invoice_date"), ct.invoice_date ? isoToDDMMYYYY(ct.invoice_date) : "");
    document.getElementById("invoice_type").value = ct.invoice_type || "";
    document.getElementById("booking_mode").value = ct.booking_mode || "";
    document.getElementById("customer").value = ct.customer_name || "";
    document.getElementById("booking_reference").value = ct.cancellation_reference || "";
    document.getElementById("booking_given_by").value = ct.booking_given_by || "";
    document.getElementById("booking_type").value = ct.booking_type || "";
    document.getElementById("booking_status").value = "Normal Cancelled";
    document.getElementById("travel_type").value = ct.travel_type || "";
    document.getElementById("user_name").value = ct.user_name || "";
    document.getElementById("payment_mode").value = ct.payment_mode || "";
    document.getElementById("payment_gateway_ref").value = ct.payment_gateway_ref || "";
    updateGatewayRefField();
    document.getElementById("roe").value = ct.roe;
    document.getElementById("airline_pnr_header").value = ct.airline_pnr || "";
    document.getElementById("gds_pnr_header").value = ct.gds_pnr || "";
    setDateGroupValue(document.getElementById("booking_ref_date"), ct.cancellation_ref_date ? isoToDDMMYYYY(ct.cancellation_ref_date) : "");
    document.getElementById("customer").dispatchEvent(new Event("input"));

    passengers = ct.lines.map((l) => ({ ...blankPassenger(), ...l, supplier_penalty: 0 }));
    if (!passengers.length) passengers = [blankPassenger()];
    renderPaxTable();

    document.querySelectorAll(".dom-form-grid input, .dom-form-grid select").forEach((el) => (el.disabled = true));
    document.getElementById("proceed-btn").style.display = "none";
    document.getElementById("submit-btn").style.display = "none";
    document.getElementById("cancellation-new-btn").style.display = "none";
    document.getElementById("cancellation-save-btn").style.display = "none";
    applyReportBackLink("Cancellation", "ticket-entry.html?cancellation_new=1");
    document.getElementById("edit-ticket-btn").style.display = "";
  }

  // ============================================================
  // Reschedule "New" Lookup Modal - replaces the old separate
  // trans-airline-reschedule.html search page, opened via the "New"
  // button on enterBlankRescheduleShell's empty form above. Finds the
  // real ticket to reschedule by S PNR / Airline PNR / Ticket No (same
  // lookup endpoint/picker the old page used), then reloads this same
  // page with the right reschedule_ticket_id/reschedule_line_id params -
  // the exact URL the old page's own "Reschedule" button used to build,
  // so it lands on the same already-proven enterRescheduleMode flow.
  // ============================================================
  let rsLookupPassengers = [];
  let rsLookupMatchedLineId = null;
  let rsLookupTicketId = null;
  let rsLookupSourceRescheduleId = null;
  const rescheduleLookupModal = document.getElementById("reschedule-lookup-modal");
  // Separate popup (2026-10-07 request) for the Pax/Sector picker, opened
  // on top of rescheduleLookupModal once a search result is picked -
  // previously grew inline inside that same search popup.
  const reschedulePaxModal = document.getElementById("reschedule-pax-modal");

  function openRescheduleLookupModal() {
    ["rs-f-invoice-number", "rs-search-spnr", "rs-search-airline-pnr", "rs-f-gds-pnr", "rs-search-ticket-no",
      "rs-f-customer-name", "rs-f-airline-code", "rs-f-date-from", "rs-f-date-to"].forEach((id) => { document.getElementById(id).value = ""; });
    rsLookupPassengers = []; rsLookupMatchedLineId = null; rsLookupTicketId = null; rsLookupSourceRescheduleId = null;
    document.getElementById("rs-results-wrap").style.display = "none";
    document.getElementById("rs-results-body").innerHTML = "";
    reschedulePaxModal.classList.remove("open");
    rescheduleLookupModal.classList.add("open");
  }
  function closeRescheduleLookupModal() { rescheduleLookupModal.classList.remove("open"); }
  document.getElementById("reschedule-new-btn").addEventListener("click", openRescheduleLookupModal);
  document.getElementById("rs-lookup-close-x-btn").addEventListener("click", closeRescheduleLookupModal);
  document.getElementById("rs-pax-close-x-btn").addEventListener("click", () => reschedulePaxModal.classList.remove("open"));

  async function rsLookupTicketForReschedule({ sPnr, airlinePnr, ticketNo, ticketNoOnly }) {
    if (!activeCompanyId) {
      voyagerAlert("Could not determine the active company. Check your connection and try Get again.");
      return;
    }
    if (!sPnr && !airlinePnr && !ticketNo) {
      voyagerAlert("Enter S PNR, Airline PNR or Ticket No to search.");
      return;
    }
    try {
      const params = new URLSearchParams({ company_id: activeCompanyId, s_pnr: sPnr, airline_pnr: airlinePnr, ticket_no: ticketNo });
      const res = await fetch(`${API_BASE}/tickets/lookup-for-reschedule/?${params}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Ticket not found.");
      rsLookupTicketId = data.ticket_id || null;
      rsLookupMatchedLineId = data.matched_line_id || null;
      rsLookupSourceRescheduleId = data.source_reschedule_ticket_id || null;
      // A search where Ticket No was the ONLY filter typed identifies
      // exactly ONE passenger, not the whole booking - only show that one.
      // Every other search (S PNR/Airline PNR/Invoice Number/etc, even
      // though runLookupModalSearch always resolves and fills in a
      // ticket_no internally to run this same lookup) still shows every
      // eligible passenger on the ticket - checking ticketNoOnly here
      // (not just whether matched_line_id came back) is what makes that
      // distinction; matched_line_id alone is always set once ANY
      // ticket_no reaches the backend, regardless of why.
      rsLookupPassengers = (ticketNoOnly && rsLookupMatchedLineId)
        ? (data.passengers || []).filter((p) => p.line_id === rsLookupMatchedLineId)
        : (data.passengers || []);
      renderRsPassengers();
      // Opens as its own popup on top of the search modal (2026-10-07
      // request) instead of growing inline inside it.
      rescheduleLookupModal.classList.remove("open");
      reschedulePaxModal.classList.add("open");
    } catch (err) {
      voyagerAlert(err.message || "Could not search for this ticket. Is the Django backend running?", { icon: "error" });
    }
  }
  document.getElementById("rs-get-btn").addEventListener("click", () => runLookupModalSearch("rs", rsLookupTicketForReschedule));
  ["rs-f-invoice-number", "rs-search-spnr", "rs-search-airline-pnr", "rs-f-gds-pnr", "rs-search-ticket-no",
    "rs-f-customer-name", "rs-f-airline-code", "rs-f-date-from", "rs-f-date-to"].forEach((id) => {
    document.getElementById(id).addEventListener("keydown", (e) => { if (e.key === "Enter") runLookupModalSearch("rs", rsLookupTicketForReschedule); });
  });

  function renderRsPassengers() {
    const tbody = document.getElementById("rs-pax-tbody");
    if (!rsLookupPassengers.length) {
      tbody.innerHTML = `<tr><td colspan="3" style="text-align:center; padding:1rem; color:#64748B;">No passengers on this ticket.</td></tr>`;
      renderRsSectors();
      return;
    }
    // Pax checkboxes start unchecked - they're purely for marking who's
    // actually being rescheduled, not for controlling whether sectors are
    // shown (see renderRsSectors below, which always shows every
    // passenger's sectors regardless of checkbox state).
    tbody.innerHTML = rsLookupPassengers.map((p, i) => `
      <tr>
        <td style="padding:4px 8px;"><input type="checkbox" class="rs-pax-check" data-idx="${i}" /></td>
        <td style="padding:4px 8px;">${p.pax_type || "-"}</td>
        <td style="padding:4px 8px;">${p.passenger_name || "-"}</td>
      </tr>
    `).join("");
    tbody.querySelectorAll(".rs-pax-check").forEach((cb) => cb.addEventListener("change", updateRsRescheduleButtonState));
    renderRsSectors();
  }
  // Shows every passenger's sectors right away, independent of the Pax
  // checkboxes - those only mark who's selected for the Reschedule
  // action, they don't gate what's visible here. Deduped by (sector,
  // flight no, class, date) - when several passengers share the exact
  // same sector (the normal case, one flight for the whole booking), it
  // showed once per PASSENGER before (e.g. the same MAA-DXB/EK 529 row
  // twice for 2 passengers) - now shown once. Safe to dedupe: this
  // checkbox list is only ever a "have you reviewed the sector" gate for
  // enabling Reschedule (see updateRsRescheduleButtonState/rs-reschedule-
  // btn's own click handler, which reads ONLY the Pax checkboxes, never
  // which specific sector row was ticked) - it was never read per-sector.
  function renderRsSectors() {
    const tbody = document.getElementById("rs-sector-tbody");
    const seen = new Set();
    const rows = [];
    rsLookupPassengers.forEach((p) => {
      (p.sectors || []).forEach((s) => {
        const key = `${s.sector || ""}|${s.flight_no || ""}|${s.travel_class || ""}|${s.travel_date || ""}`;
        if (seen.has(key)) return;
        seen.add(key);
        rows.push(`
          <tr>
            <td style="padding:4px 8px;"><input type="checkbox" class="rs-sector-check" /></td>
            <td style="padding:4px 8px;">${s.sector || "-"}</td>
            <td style="padding:4px 8px;">${s.flight_no || "-"}</td>
            <td style="padding:4px 8px;">${s.travel_class || "-"}</td>
            <td style="padding:4px 8px;">${s.travel_date || "-"}</td>
          </tr>
        `);
      });
    });
    tbody.innerHTML = rows.length
      ? rows.join("")
      : `<tr><td colspan="5" style="text-align:center; padding:1rem; color:#64748B;">Select a passenger to see their sectors.</td></tr>`;
    tbody.querySelectorAll(".rs-sector-check").forEach((cb) => cb.addEventListener("change", updateRsRescheduleButtonState));
    updateRsRescheduleButtonState();
  }
  // Reschedule only makes sense once at least one passenger AND one of
  // their sectors is actually picked.
  function updateRsRescheduleButtonState() {
    const anyPax = document.querySelectorAll(".rs-pax-check:checked").length > 0;
    const anySector = document.querySelectorAll(".rs-sector-check:checked").length > 0;
    document.getElementById("rs-reschedule-btn").disabled = !(anyPax && anySector);
  }
  document.getElementById("rs-reschedule-btn").addEventListener("click", () => {
    const checkedPax = Array.from(document.querySelectorAll(".rs-pax-check:checked"))
      .map((cb) => rsLookupPassengers[Number(cb.dataset.idx)]);
    if (!rsLookupTicketId || !checkedPax.length) return;
    // One new reschedule ticket, carrying EVERY checked passenger -
    // passed via sessionStorage (not the URL) same as the old page did,
    // since enterRescheduleMode's own init-flow reader already expects it
    // there.
    sessionStorage.setItem("reschedule_picked_lines", JSON.stringify(
      checkedPax.map((p) => ({ line_id: p.line_id, reschedule_line_id: p.reschedule_line_id || null }))
    ));
    let url = `ticket-entry.html?reschedule_ticket_id=${rsLookupTicketId}&reschedule_line_id=${checkedPax[0].line_id}`;
    if (rsLookupSourceRescheduleId) {
      url += `&parent_reschedule_id=${rsLookupSourceRescheduleId}`;
      if (checkedPax[0].reschedule_line_id) url += `&parent_reschedule_line_id=${checkedPax[0].reschedule_line_id}`;
    }
    window.location.href = url;
  });

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
      // Only ever non-zero once the cumulative chain fetch in
      // enterRescheduleMode/enterSavedRescheduleMode below has replaced
      // the single-line fallback - a plain TicketLine (the very first
      // reschedule's own Parent PNR Details) has no such fields at all.
      agent_penalty: l.agent_penalty || 0, reschedule_penalty: l.reschedule_penalty || 0,
      supplier_penalty: l.supplier_penalty || 0,
      // Set only by the parent-chain-line endpoint for a CHAINED (2nd+)
      // reschedule - the true cumulative TDS Amount (sum of each chain
      // level's own TDS, not "summed Amount x one rate"), applied as a
      // direct display override in applyRescheduleTab since tds_per is 0
      // here (no single real rate produced that sum).
      tds_amount: l.tds_amount != null ? l.tds_amount : null,
      supp_tds_amount: l.supp_tds_amount != null ? l.supp_tds_amount : null,
    };
  }

  // Pre-fills a brand-new ticket from an existing one's data, for the
  // Reschedule flow (trans-airline-reschedule.html) - unlike enterViewMode,
  // this leaves Invoice Number blank and defaults both dates to today (this
  // is a new ticket being created, not the original being reopened), keeps
  // every field editable, and carries over every passenger line the user
  // checked on the reschedule screen (pickedLines - an array of
  // {line_id, reschedule_line_id}, one per checked passenger) rather than
  // the whole ticket.
  //
  // parentSource (optional) - set only when CHAINING: this reschedule was
  // found via a PREVIOUS reschedule (trans-airline-reschedule.html matched
  // the search against an already-rescheduled ticket, not the original),
  // so "Parent PNR Details" and the header defaults below should reflect
  // that reschedule's own (most recent) state instead of the several-
  // steps-back original. It's the JSON from reschedule-tickets/<id>/,
  // same booking_reference/lines[] shape as `t` itself, so it's used as a
  // drop-in substitute wherever `t` would otherwise be read from. All
  // checked passengers come from the SAME lookup result, so they always
  // share this one parentSource (and one lookupSourceRescheduleId) -
  // trans-airline-reschedule.html never mixes original-ticket and
  // reschedule-matched passengers in a single lookup.
  async function enterRescheduleMode(t, pickedLines, parentSource) {
    rescheduleMode = true;
    // Undoes enterBlankRescheduleShell's own blanket disable (nothing was
    // editable while still "awaiting a pick") - picking a real
    // ticket/passenger via New unlocks the whole header for entering this
    // new reschedule's own data. booking_status/booking_mode are
    // explicitly re-locked again below/immediately after - the latter is
    // frozen at "Manual" everywhere, every mode, until a future Auto Push
    // API integration exists (see the one-time page-init disable near the
    // top of this file), not something this function should ever unlock.
    document.querySelectorAll(".dom-form-grid input, .dom-form-grid select").forEach((el) => (el.disabled = false));
    document.getElementById("booking_mode").disabled = true;
    document.getElementById("page-title").textContent = "Reschedule";
    // These two fields now track the reschedule's own reference/date, not
    // the original ticket's, so their labels say so.
    document.getElementById("booking_reference_label").innerHTML = 'Rescheduled Ref<span class="dom-req">*</span>';
    document.getElementById("booking_ref_date_label").innerHTML = 'Rescheduled Ref Date<span class="dom-req">*</span>';
    document.getElementById("booking_reference").style.flex = "0 0 120px";
    // Parent PNR carries the PARENT's (original ticket, or the previous
    // reschedule when chaining) Booking Reference forward for a visible
    // trail back to it - Booking Reference itself is left blank so the
    // user enters this reschedule's own new reference.
    const parentHeader = parentSource || t;
    document.getElementById("parent-pnr-field").style.display = "";
    document.getElementById("parent_pnr").textContent = parentHeader.booking_reference || "—";
    document.getElementById("invoice_type").value = parentHeader.invoice_type || "";
    // Setting .value directly doesn't fire a "change" event, so the
    // auto-numbering this Invoice Type triggers on a real user pick (see
    // applyInvoiceNumbering) never ran - Invoice Number stayed blank even
    // though Invoice Type showed correctly pre-selected.
    applyInvoiceNumbering();
    document.getElementById("booking_mode").value = parentHeader.booking_mode || "";
    document.getElementById("customer").value = parentHeader.customer_name || "";
    document.getElementById("booking_reference").value = "";
    document.getElementById("booking_given_by").value = parentHeader.booking_given_by || "";
    document.getElementById("booking_type").value = parentHeader.booking_type || "";
    // Frozen to Re-Scheduled regardless of the original ticket's own
    // status - this new ticket only exists because of the reschedule.
    document.getElementById("booking_status").value = "Re-Scheduled";
    document.getElementById("booking_status").disabled = true;
    document.getElementById("travel_type").value = parentHeader.travel_type || "";
    // User Name is left unset (2026-10-07 request) rather than copied from
    // the original ticket - the person doing the reschedule may not be the
    // same one who made the original booking, so it's picked fresh here,
    // same reasoning as Payment Mode just below.
    document.getElementById("user_name").value = "";
    // Payment Mode is left unset ("Select...") rather than copied from the
    // original ticket - the reschedule may be settled through a different
    // mode, so the user picks it fresh.
    document.getElementById("payment_mode").value = "";
    document.getElementById("payment_gateway_ref").value = "";
    updateGatewayRefField();
    document.getElementById("roe").value = parentHeader.roe;
    document.getElementById("airline_pnr_header").value = parentHeader.airline_pnr || "";
    document.getElementById("gds_pnr_header").value = parentHeader.gds_pnr || "";
    document.getElementById("customer").dispatchEvent(new Event("input"));

    passengers = [];
    rescheduleParentPassengers = [];
    rescheduleAncestorLevels = [];
    for (const picked of pickedLines) {
      const pickedLineId = picked.line_id;
      const pickedBasedOnId = picked.reschedule_line_id || null;
      // Resolved per-passenger, by THIS passenger's own reschedule_line_id
      // - parentSource can itself carry several lines (a previous
      // reschedule that also rescheduled multiple passengers at once), so
      // always matching parentSource.lines[0] regardless of which
      // passenger this is would silently mix up whose Parent is whose.
      const l = (parentSource && pickedBasedOnId)
        ? (parentSource.lines.find((ln) => String(ln.id) === String(pickedBasedOnId)) || parentSource.lines[0])
        : (t.lines.find((ln) => String(ln.id) === String(pickedLineId)) || t.lines[0]);
      if (!l) continue;

      // Parent PNR Details tab - starts from this single line as a
      // fallback, then (below) is replaced with the CUMULATIVE total
      // across the whole chain (original + every intermediate reschedule)
      // once that's fetched, since a chained reschedule's own standalone
      // fare figures alone understate what's actually owed so far.
      let parentPassenger = buildParentPassengerFromLine(l);
      let ancestorLevels = [];
      try {
        const chainUrl =
          `${API_BASE}/reschedule-tickets/parent-chain-line/?company_id=${activeCompanyId}&original_ticket_line_id=${pickedLineId}` +
          (pickedBasedOnId ? `&based_on_reschedule_line_id=${pickedBasedOnId}` : "");
        const chainRes = await fetch(chainUrl);
        if (chainRes.ok) {
          const chainData = await chainRes.json();
          parentPassenger = buildParentPassengerFromLine(chainData);
          // One extra tab per ancestor PNR (nearest first), each its own
          // standalone (never summed) fare data - alongside the combined
          // Parent PNR Details tab above, not instead of it.
          ancestorLevels = (chainData.chain_levels || []).map((lvl) => ({
            pnr: lvl.pnr,
            passenger: buildParentPassengerFromLine(lvl),
          }));
        }
      } catch (_) { /* keep the single-line fallback above */ }
      rescheduleParentPassengers.push(parentPassenger);
      rescheduleAncestorLevels.push(ancestorLevels);

      // Reschedule PNR Details tab - this brand new ticket's own data,
      // starts blank/0.00 for every fare figure (like any other new
      // passenger), but a handful of Passenger & Segment Details fields
      // are pre-filled from the Parent line as a starting point the user
      // can freely overwrite: Airline Category, Pax Name, Pax Type, and
      // (inside the Sector popup) Origin/Destination, Airline Code/Name -
      // Flight No/Travel Date/Cabin/Class/Fare Type stay blank since
      // those genuinely change on a reschedule. Office ID/Supplier are
      // also carried over - auto-filling Office ID re-triggers the same
      // Supplier lookup a manual Office ID entry would.
      passengers.push({
        ...blankPassenger(),
        airline_category: l.airline_category || "",
        passenger_name: l.passenger_name || "",
        pax_type: l.pax_type || "",
        sector: l.sector || "", airline_code: l.airline_code || "", airline_name: l.airline_name || "",
        office_id: l.office_id || "", supplier_name: l.supplier_name || "",
        // Set directly on each passenger (rather than relying on a single
        // shared URL param) since every checked passenger can point at a
        // DIFFERENT original/chain line.
        original_ticket_line_id: pickedLineId,
        reschedule_line_id: pickedBasedOnId,
      });
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
    const extraPaxSuffix = rt.lines.length > 1 ? ` +${rt.lines.length - 1} more` : "";
    document.getElementById("page-title").textContent =
      `View Reschedule - ${rt.lines[0]?.ticket_no || rt.invoice_number} (${rt.lines[0]?.passenger_name || ""})${extraPaxSuffix}`;
    document.getElementById("booking_reference_label").innerHTML = 'Rescheduled Ref<span class="dom-req">*</span>';
    document.getElementById("booking_ref_date_label").innerHTML = 'Rescheduled Ref Date<span class="dom-req">*</span>';
    document.getElementById("booking_reference").style.flex = "0 0 120px";
    document.getElementById("parent-pnr-field").style.display = "";
    // Stored on the saved line itself (parent_pnr - set once at creation,
    // never recomputed), not re-derived from originalTicket every time -
    // this was ALWAYS wrong for a chained reschedule (rescheduling an
    // already-rescheduled ticket again), since it unconditionally showed
    // the true original's own Booking Reference instead of whichever
    // reschedule this one was actually made from.
    document.getElementById("parent_pnr").textContent = (rt.lines[0] && rt.lines[0].parent_pnr) || originalTicket.booking_reference || "—";
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

    // Every saved line belongs to this one reschedule ticket - loop over
    // ALL of them (not just rt.lines[0]) so a reschedule that carried
    // several passengers at once re-opens showing every one of them, each
    // with its own correctly-matched Parent PNR Details.
    passengers = [];
    rescheduleParentPassengers = [];
    rescheduleAncestorLevels = [];
    for (const savedLine of rt.lines) {
      const parentLine = originalTicket.lines.find((ln) => String(ln.id) === String(savedLine.original_ticket_line_id));
      let parentPassenger = parentLine ? buildParentPassengerFromLine(parentLine) : null;
      let ancestorLevels = [];
      // Same cumulative-chain total as enterRescheduleMode, but reading
      // back THIS saved line's own stored chain pointers
      // (original_ticket_line_id/reschedule_line_id) instead of fresh
      // lookup-screen params, so re-opening a chained reschedule later
      // still shows the correct running total, not just the single-line
      // fallback above.
      try {
        const chainUrl =
          `${API_BASE}/reschedule-tickets/parent-chain-line/?company_id=${activeCompanyId}&original_ticket_line_id=${savedLine.original_ticket_line_id}` +
          (savedLine.reschedule_line_id ? `&based_on_reschedule_line_id=${savedLine.reschedule_line_id}` : "");
        const chainRes = await fetch(chainUrl);
        if (chainRes.ok) {
          const chainData = await chainRes.json();
          parentPassenger = buildParentPassengerFromLine(chainData);
          ancestorLevels = (chainData.chain_levels || []).map((lvl) => ({
            pnr: lvl.pnr,
            passenger: buildParentPassengerFromLine(lvl),
          }));
        }
      } catch (_) { /* keep the single-line fallback above */ }
      rescheduleParentPassengers.push(parentPassenger);
      rescheduleAncestorLevels.push(ancestorLevels);
      passengers.push({ ...blankPassenger(), ...savedLine });
    }
    if (!passengers.length) passengers = [blankPassenger()];
    renderPaxTable();

    document.querySelectorAll(".dom-form-grid input, .dom-form-grid select").forEach((el) => (el.disabled = true));
    document.getElementById("proceed-btn").style.display = "none";
    document.getElementById("submit-btn").style.display = "none";
    applyReportBackLink("Reschedule", "ticket-entry.html?reschedule_new=1");
    document.getElementById("edit-ticket-btn").style.display = "";
  }

  // Unlocks a loaded/saved ticket for editing - re-enables every header
  // field, brings back Save Ticket, and re-renders the passenger table so
  // rows show Edit/Del again instead of View-only. Save Ticket then hits
  // tickets/<id>/update/ instead of tickets/create/ since editId is set.
  document.getElementById("edit-ticket-btn").addEventListener("click", () => {
    viewMode = false;
    // Cancellation only unlocks the SAME fields that were editable at
    // creation time (Invoice Date/Type, User Name, Payment Mode/Gateway
    // Ref, Cancellation Reference/Ref Date, plus Base Fare/Discount/
    // Commission/Markup/Service Fee on each line via openFareModal's own
    // cancellationMode lock list, unaffected by viewMode here) - NOT a
    // blanket enable like Booking/Reschedule (Customer, the original
    // ticket link, etc. must stay frozen either way).
    if (cancellationMode) {
      document.querySelectorAll(".dom-form-grid input, .dom-form-grid select").forEach((el) => {
        if (CX_EDITABLE_HEADER_FIELD_IDS.has(el.id)) el.disabled = false;
      });
      document.querySelector("#invoice_date .dg-native").disabled = false;
      document.querySelector("#booking_ref_date .dg-native").disabled = false;
    } else {
      document.querySelectorAll(".dom-form-grid input, .dom-form-grid select").forEach((el) => (el.disabled = false));
      document.getElementById("booking_mode").disabled = true; // stays frozen at Manual regardless of mode
      // Booking Status stays frozen at its own mode's fixed value even once
      // unlocked for editing - Confirmed for a plain Booking ticket,
      // Re-Scheduled for a saved Reschedule (same as when it was first
      // created - see enterSavedRescheduleMode/enterRescheduleMode).
      document.getElementById("booking_status").disabled = true;
    }
    updateGatewayRefField(); // re-applies its own read-only/editable rule, not just "everything enabled"
    document.getElementById("submit-btn").style.display = cancellationMode ? "none" : "";
    document.getElementById("cancellation-save-btn").style.display = cancellationMode ? "" : "none";
    document.getElementById("edit-ticket-btn").style.display = "none";
    document.getElementById("cancel-link").textContent = "Discard";
    // Discard from Edit mode must return to THIS ticket's own view state,
    // not wherever cancel-link's href was left pointing from enterViewMode
    // (document.referrer, or the "Back to Tickets" default) - re-loading
    // this same ?id=/?reschedule_saved_id=/?cancellation_saved_id= is what
    // actually discards the in-progress edits.
    document.getElementById("cancel-link").setAttribute("href",
      rescheduleMode ? `ticket-entry.html?reschedule_saved_id=${editingRescheduleId}`
      : cancellationMode ? `ticket-entry.html?cancellation_saved_id=${cxEditSavedCancellationId}`
      : `ticket-entry.html?id=${editId}`);
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
      // Reschedule saves land back on this same reschedule ticket in its
      // view state (Edit button again, not the blank New Ticket screen) -
      // unlike a normal ticket save, which still goes to a fresh blank
      // form. result.id is the RescheduleAirlineTicket's own id either way
      // (create or update).
      const redirectTo = rescheduleMode ? `ticket-entry.html?reschedule_saved_id=${result.id}` : "ticket-entry.html";
      window.VoyagerEntry.showToast(result.message || `${payload.lines.length} ticket(s) saved.`, redirectTo);
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
    active = await VoyagerShell.init({ activeKey: rescheduleActiveKey, onCompanyChange: (id, country) => { activeCompanyId = Number(id); activeCountry = country; applyFYDatePickerLimits(); VoyagerUtil.loadDecimalPlaces(activeCompanyId); populateRefs(activeCompanyId); } });
  } catch (err) {
    console.error("Shell init failed", err);
  }
  if (active) {
    activeCompanyId = Number(active.id); activeCountry = active.country;
    applyFYDatePickerLimits();
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
      // Same fix as the editId branch above - existingTickets doesn't
      // depend on populateRefs (or vice versa), so fetching it only AFTER
      // populateRefs finished was a 2nd full round trip tacked onto the
      // first for no reason. This is the path the Reschedule/Cancellation
      // MENU ITEM takes (blank shell, no editId) - real, user-visible lag
      // on every single click of those two menu entries.
      try {
        const [, res] = await Promise.all([
          populateRefs(activeCompanyId),
          fetch(`${API_BASE}/tickets/?company_id=${activeCompanyId}`),
        ]);
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
          const [res, parentRes] = await Promise.all([
            fetch(`${API_BASE}/tickets/${rescheduleTicketId}/?company_id=${activeCompanyId}`),
            // Chaining - also fetch the PREVIOUS reschedule this one was
            // found via, so "Parent PNR Details" reflects its data instead
            // of the several-steps-back original ticket's.
            parentRescheduleId
              ? fetch(`${API_BASE}/reschedule-tickets/${parentRescheduleId}/?company_id=${activeCompanyId}`)
              : Promise.resolve(null),
          ]);
          const ticket = await res.json();
          if (!res.ok) throw new Error(ticket.error || "Ticket not found.");
          let parentSource = null;
          if (parentRes) {
            const parentData = await parentRes.json();
            if (parentRes.ok) parentSource = parentData;
            // Tolerates a failed parent fetch (e.g. it was deleted between
            // the lookup and now) by just falling back to the plain
            // original-ticket Parent PNR Details instead of failing the
            // whole page load.
          }
          // Every passenger checked on the lookup screen - stashed there
          // (not the URL) as a JSON array of {line_id, reschedule_line_id}
          // since it can be more than one. Falls back to a single-entry
          // array built from the old singular URL params if that storage
          // is somehow missing (e.g. a stale bookmark), so a direct link
          // still works for the one-passenger case.
          let pickedLines = null;
          try {
            const raw = sessionStorage.getItem("reschedule_picked_lines");
            if (raw) pickedLines = JSON.parse(raw);
          } catch (_) { pickedLines = null; }
          sessionStorage.removeItem("reschedule_picked_lines");
          if (!Array.isArray(pickedLines) || !pickedLines.length) {
            pickedLines = [{
              line_id: Number(rescheduleLineId),
              reschedule_line_id: basedOnRescheduleLineId ? Number(basedOnRescheduleLineId) : null,
            }];
          }
          await enterRescheduleMode(ticket, pickedLines, parentSource);
        } catch (err) {
          voyagerAlert(err.message || "Could not load the original ticket for reschedule. Is the Django backend running?", { icon: "error" });
          renderPaxTable();
        }
      } else if (rescheduleNew) {
        enterBlankRescheduleShell();
      } else if (cancellationNew) {
        enterBlankCancellationShell();
      } else if (cancellationSavedId) {
        try {
          const res = await fetch(`${API_BASE}/cancellation-tickets/${cancellationSavedId}/?company_id=${activeCompanyId}`);
          const ct = await res.json();
          if (!res.ok) throw new Error(ct.error || "Saved cancellation not found.");
          enterSavedCancellationMode(ct);
        } catch (err) {
          voyagerAlert(err.message || "Could not load this saved cancellation. Is the Django backend running?", { icon: "error" });
          renderPaxTable();
        }
      } else {
        renderPaxTable();
      }
    }
    // Whatever branch above just ran (success or caught error), the real
    // data load this overlay was covering for is now finished.
    const loadingOverlay = document.getElementById("ticket-loading-overlay");
    if (loadingOverlay) loadingOverlay.style.display = "none";
  } else {
    const loadingOverlay = document.getElementById("ticket-loading-overlay");
    if (loadingOverlay) loadingOverlay.style.display = "none";
    voyagerAlert("Could not load the active company. Check your connection and reload the page.", { icon: "error" });
  }
})();