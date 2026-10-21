(async function () {
  // Miscellaneous (trans-misc.html). One free-text service (Description)
  // billed to a Customer and bought from a Supplier: Base Amount plus the
  // supplier's and the customer's own Markup / Service Fee. Save stores it
  // through /api/misc/ (dbo.sp_MiscTransaction) and posts its own MSC-n JV -
  // none while Status is Cancelled. GST % and the JV ledgers come from Ledger
  // Mapping (Misc Markup / Misc Service Fee and the Supplier ones).
  const API = "http://localhost:8000/api/";
  const n = (v) => Number(String(v || "").replace(/,/g, "")) || 0;
  // Money follows Company Master's "No. of Decimals" (same as the ticket /
  // SSR screens) - f2 for display, fmtN for amount input boxes.
  const dp = () => VoyagerUtil.getDecimalPlaces();
  const f2 = (v) => n(v).toLocaleString("en-IN", { minimumFractionDigits: dp(), maximumFractionDigits: dp() });
  const fmtN = (v) => n(v).toFixed(dp());
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const savedId = new URLSearchParams(window.location.search).get("misc_saved_id");
  let activeCompanyId = null;
  let voucherTypes = [];
  let viewMode = false;
  let customers = [], suppliers = [];

  // Dates first - the calendar built during shell init shows whatever
  // value the input already has.
  const today = new Date().toISOString().slice(0, 10);
  $("invoice_date").value = today;
  $("ref_date").value = today;
  const setDate = (id, iso) => { $(id).value = iso || ""; $(id).dispatchEvent(new Event("change")); };

  const active = await VoyagerShell.init({ activeKey: "trans-misc" });
  activeCompanyId = Number(active && active.id) || 1;
  await VoyagerUtil.loadDecimalPlaces(activeCompanyId);
  $("misc-user-name-options").innerHTML = window.VoyagerHardcode.dropdownValues("userNames").map((v) => `<option value="${esc(v)}">`).join("");
  $("misc_status").value = "Confirmed";
  const ccy = (VoyagerUtil.currencyFor && VoyagerUtil.currencyFor(active && active.country)) || "INR";
  $("earnings-ccy").textContent = ccy;

  // ---------- Customer / Supplier lists ----------
  try {
    const [cRes, sRes] = await Promise.all([
      fetch(`${API}customers/?company_id=${activeCompanyId}`),
      fetch(`${API}suppliers/?company_id=${activeCompanyId}`),
    ]);
    customers = cRes.ok ? await cRes.json() : [];
    suppliers = sRes.ok ? await sRes.json() : [];
  } catch (_) { customers = []; suppliers = []; }
  $("misc-customer-options").innerHTML = customers.map((c) => `<option value="${esc(c.name)}">`).join("");
  // Agent ID / Address / GST-TRN - read-only, from the
  // Customer picked (same as the Booking screen).
  function fillCustomerInfo() {
    const c = customers.find((x) => x.name === $("customer").value.trim()) || {};
    $("customer_agent_id").textContent = c.agent_id || "—";
    $("customer_address").textContent = c.address || "—";
    $("customer_address").title = c.address || "Customer Address";
    $("customer_gst").textContent = c.gst_no || "—";
  }
  $("customer").addEventListener("input", fillCustomerInfo);
  // Supplier ID = the supplier ledger's Office ID (same as the Booking
  // screen). Supplier Name is read-only - always the picked ID's supplier
  // (cleared while the ID matches none).
  $("misc-supplier-id-options").innerHTML = suppliers.filter((s) => s.office_id)
    .map((s) => `<option value="${esc(s.office_id)}">${esc(s.name)}</option>`).join("");
  const supplierIdFor = (name) => ((suppliers.find((s) => s.name === name) || {}).office_id || "");
  $("supplier_id").addEventListener("input", (e) => {
    const id = e.target.value.trim().toUpperCase();
    const s = suppliers.find((x) => String(x.office_id || "").toUpperCase() === id);
    $("supplier").value = s ? s.name : "";
  });

  // ---------- Ledger Mapping: GST % + which fields have a ledger ----------
  const FIELD = {
    markup: "Misc Markup A/c", service_fee: "Misc Service Fee A/c",
    supp_markup: "Supplier Misc Markup A/c", supp_service_fee: "Supplier Misc Service Fee A/c",
  };
  let mapped = new Set();
  let gstPct = {};
  // Ledger Mapping in force on the Invoice Date (effective dates) - reloaded
  // when the date changes, same as the server's JV / totals.
  async function loadMapping() {
    const asOf = $("invoice_date").value;
    try {
      const res = await fetch(`${API}master-mapping/?company_id=${activeCompanyId}&product_type=Miscellaneous` + (asOf ? `&as_of=${asOf}` : ""));
      const next = new Set(), pct = {};
      (res.ok ? await res.json() : []).forEach((r) => { next.add(r.field_name); pct[r.field_name] = Number(r.ledger_gst_percentage) || 0; });
      mapped = next; gstPct = pct;
    } catch (_) { mapped = new Set(); gstPct = {}; }
  }
  await loadMapping();
  $("invoice_date").addEventListener("change", async () => { await loadMapping(); recalc(); });
  const custGstPct = () => gstPct[FIELD.service_fee] || 0;
  const suppGstPct = () => gstPct[FIELD.supp_service_fee] || 0;

  // ---------- Payment Mode -> Gateway Ref (same as the Booking screen) ----------
  try {
    const res = await fetch(`${API}pg-master/?company_id=${activeCompanyId}`);
    const gateways = (res.ok ? await res.json() : []).filter((g) => g.is_active).map((g) => g.gateway_name);
    $("payment_gateway_ref").innerHTML = `<option value="">Select...</option>` +
      gateways.map((g) => `<option value="${esc(g)}">${esc(g)}</option>`).join("");
  } catch (_) { /* leave just "Select..." */ }
  function syncGatewayRef() {
    const isGateway = $("payment_mode").value === "Payment Gateway";
    if (!isGateway) $("payment_gateway_ref").value = "";
    $("payment_gateway_ref").disabled = viewMode || !isGateway;
  }
  $("payment_mode").addEventListener("change", syncGatewayRef);

  // ---------- Invoice Type + numbering (same rules as the Booking screen) ----------
  try {
    const res = await fetch(`${API}voucher-type/?company_id=${activeCompanyId}`);
    voucherTypes = res.ok ? await res.json() : [];
  } catch (_) { voucherTypes = []; }
  // Invoice Type = Voucher Type master entries whose Type of Voucher is
  // Miscellaneous - they're listed only here (never on Booking / SSR or the
  // Voucher screen).
  $("invoice_type").innerHTML = `<option value="">Select...</option>` +
    voucherTypes.filter((v) => v.is_active && v.voucher_category === "Miscellaneous")
      .map((v) => `<option value="${esc(v.name)}">${esc(v.name)}</option>`).join("");
  const setInvoiceType = (name) => {
    if (name && !Array.from($("invoice_type").options).some((o) => o.value === name)) {
      $("invoice_type").insertAdjacentHTML("beforeend", `<option value="${esc(name)}">${esc(name)}</option>`);
    }
    $("invoice_type").value = name || "";
  };
  $("invoice_type").addEventListener("change", async () => {
    const vt = voucherTypes.find((v) => v.name === $("invoice_type").value);
    const input = $("invoice_number");
    if (!vt || vt.number_method === "Manual") { input.readOnly = false; return; }
    try {
      const qs = new URLSearchParams({ company_id: activeCompanyId, name: vt.name, voucher_date: $("invoice_date").value || "" });
      const res = await fetch(`${API}voucher-type/next-number/?${qs}`);
      const data = await res.json();
      if (res.ok && data.next_number) input.value = data.next_number;
    } catch (_) { /* leave whatever was typed */ }
    input.readOnly = vt.number_method === "Automatic";
  });
  // One Invoice Type only -> pick it straight away (fills the number too).
  if ($("invoice_type").options.length === 2 && !savedId) {
    $("invoice_type").selectedIndex = 1;
    $("invoice_type").dispatchEvent(new Event("change"));
  }

  // ---------- Amounts, cards and summary ----------
  // Same convention as SSR Updation / views._misc_amounts:
  //   Supplier Total = Supplier Markup + Service Fee + its GST
  //   Customer Total = Customer Markup + Service Fee + its GST
  //   Purchase Cost  = Base Amount + Other Taxes + Supplier Total (what the supplier is owed)
  //   Sales Cost     = Purchase Cost + Customer Total (what the customer pays)
  //   Earnings       = Customer Markup + Customer Service Fee
  const AMOUNT_IDS = ["base_amount", "other_taxes", "markup", "service_fee", "supp_markup", "supp_service_fee"];
  function readAmounts() {
    const a = {};
    AMOUNT_IDS.forEach((id) => { a[id] = n($(id).value); });
    a.gst = a.service_fee * custGstPct() / 100;
    a.supp_gst = a.supp_service_fee * suppGstPct() / 100;
    a.supp_total = a.supp_markup + a.supp_service_fee + a.supp_gst;
    a.cust_total = a.markup + a.service_fee + a.gst;
    a.purchase = a.base_amount + a.other_taxes + a.supp_total;
    a.sales = a.purchase + a.cust_total;
    return a;
  }
  function recalc() {
    const a = readAmounts();
    $("cust-gst-label").textContent = `GST Amount (${custGstPct().toFixed(2)}%)`;
    $("supp-gst-label").textContent = `GST Amount (${suppGstPct().toFixed(2)}%)`;
    $("cust_gst").textContent = f2(a.gst); $("cust_total").textContent = f2(a.cust_total);
    $("supp_gst").textContent = f2(a.supp_gst); $("supp_total").textContent = f2(a.supp_total);
    // Sales Cost's Markup / Service Fee / GST fold in the supplier side too
    // (the customer is billed both), same as the Booking / SSR summary.
    $("pc-base").textContent = f2(a.base_amount); $("pc-taxes").textContent = f2(a.other_taxes); $("pc-markup").textContent = f2(a.supp_markup);
    $("pc-sfee").textContent = f2(a.supp_service_fee); $("pc-gst").textContent = f2(a.supp_gst); $("pc-total").textContent = f2(a.purchase);
    $("sc-base").textContent = f2(a.base_amount); $("sc-taxes").textContent = f2(a.other_taxes); $("sc-markup").textContent = f2(a.markup + a.supp_markup);
    $("sc-sfee").textContent = f2(a.service_fee + a.supp_service_fee); $("sc-gst").textContent = f2(a.gst + a.supp_gst);
    $("sc-total").textContent = f2(a.sales);
    $("earnings_total").textContent = f2(a.markup + a.service_fee);
  }
  document.querySelectorAll(".misc-calc").forEach((el) => el.addEventListener("input", recalc));
  // Same rule as the Booking / SSR screens: a markup / service fee can't
  // hold an amount until its ledger is set in Ledger Mapping.
  const guardWarned = new Set();
  Object.keys(FIELD).forEach((id) => $(id).addEventListener("input", (e) => {
    if (mapped.has(FIELD[id]) || n(e.target.value) === 0) return;
    e.target.value = fmtN(0);
    if (!guardWarned.has(id)) { guardWarned.add(id); voyagerAlert(`Required Ledger account is not mapped ("${FIELD[id]}" in Ledger Mapping > Miscellaneous).`); }
    recalc();
  }));

  const open = (id) => $(id).classList.add("open");
  const close = (id) => $(id).classList.remove("open");
  document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => close(b.dataset.close)));

  // ---------- Save / payload ----------
  const EDITABLE_IDS = ["invoice_number", "invoice_date", "invoice_type", "misc_status", "user_name", "reference", "ref_date",
    "payment_mode", "customer", "supplier_id", "description", ...AMOUNT_IDS];
  function buildPayload() {
    const payload = {
      company_id: activeCompanyId,
      invoice_number: $("invoice_number").value.trim(), invoice_date: $("invoice_date").value,
      invoice_type: $("invoice_type").value, status: $("misc_status").value || "Confirmed",
      user_name: $("user_name").value.trim(), reference: $("reference").value.trim().toUpperCase(),
      ref_date: $("ref_date").value, payment_mode: $("payment_mode").value, payment_gateway_ref: $("payment_gateway_ref").value,
      currency: ccy, customer_name: $("customer").value.trim(), supplier_name: $("supplier").value.trim(),
      description: $("description").value.trim(),
    };
    AMOUNT_IDS.forEach((id) => { payload[id] = n($(id).value); });
    return payload;
  }
  function validate() {
    const missing = [["invoice_type", "Invoice Type"], ["invoice_number", "Invoice Number"], ["invoice_date", "Invoice Date"],
      ["reference", "Reference"], ["customer", "Customer Name"], ["supplier_id", "Supplier ID"], ["description", "Description"]]
      .filter(([id]) => !$(id).value.trim()).map(([, label]) => label);
    if (missing.length) { voyagerAlert(`${missing.join(", ")} ${missing.length === 1 ? "is" : "are"} required.`); return false; }
    if (!customers.some((c) => c.name === $("customer").value.trim())) { voyagerAlert("Choose the Customer Name from the list."); return false; }
    if (!suppliers.some((s) => s.name === $("supplier").value.trim())) { voyagerAlert("Choose a valid Supplier ID from the list."); return false; }
    if ($("misc_status").value !== "Cancelled" && readAmounts().sales <= 0) {
      voyagerAlert("Enter the Base Amount (and any Other Taxes / Markup / Service Fee).");
      return false;
    }
    return true;
  }
  $("misc-save-btn").addEventListener("click", async () => {
    if (!validate()) return;
    try {
      const url = savedId ? `${API}misc/${savedId}/update/` : `${API}misc/create/`;
      const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(buildPayload()) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not save this Miscellaneous transaction.");
      await voyagerAlert(data.message || "Miscellaneous transaction saved.", { icon: "success" });
      window.VoyagerShell.navigateTo(`trans-misc.html?misc_saved_id=${data.id}`);
    } catch (err) {
      voyagerAlert(err.message || "Could not save. Is the Django backend running?", { icon: "error" });
    }
  });

  // ---------- Saved transaction: view, Edit, Discard, New ----------
  function setViewMode(on) {
    viewMode = on;
    EDITABLE_IDS.forEach((id) => { $(id).disabled = on; });
    syncGatewayRef();
    $("misc-save-btn").style.display = on ? "none" : "";
    $("misc-edit-btn").style.display = on && savedId ? "" : "none";
    // Opened from a report row (Day Book / Ledger / Receivables / Payables)
    // -> Back returns there, same as the ticket screens.
    const fromReport = [["report-day-book.html", "Day Book"], ["report-ledger-book.html", "Ledger"], ["customers.html", "Receivables"], ["suppliers.html", "Payables"]]
      .find(([page]) => document.referrer.includes(page));
    $("misc-discard-btn").textContent = on ? `<- Back to ${fromReport ? fromReport[1] : "Miscellaneous"}` : "Discard";
    $("misc-discard-btn").setAttribute("href", on
      ? (fromReport ? document.referrer : "trans-misc.html")
      : (savedId ? `trans-misc.html?misc_saved_id=${savedId}` : "trans-misc.html"));
  }
  $("misc-edit-btn").addEventListener("click", () => setViewMode(false));
  $("misc-discard-btn").addEventListener("click", (e) => {
    e.preventDefault(); e.stopPropagation();
    const href = e.currentTarget.getAttribute("href");
    if (viewMode) { window.VoyagerShell.navigateTo(href); return; }
    voyagerConfirm("Discard this Miscellaneous transaction and any unsaved changes?", { title: "Confirm Discard", confirmLabel: "Discard", icon: "warning" })
      .then((ok) => { if (ok) window.VoyagerShell.navigateTo(href); });
  });
  $("misc-new-btn").addEventListener("click", () => {
    if (savedId || viewMode) { window.VoyagerShell.navigateTo("trans-misc.html"); return; }
    voyagerConfirm("Clear this screen and start a new Miscellaneous transaction?", { title: "New", confirmLabel: "New", icon: "warning" })
      .then((ok) => { if (ok) window.VoyagerShell.navigateTo("trans-misc.html"); });
  });

  async function loadSaved(id) {
    try {
      const res = await fetch(`${API}misc/${id}/?company_id=${activeCompanyId}`);
      const d = await res.json();
      if (!res.ok) throw new Error(d.error || "Miscellaneous transaction not found.");
      $("page-title").textContent = `View Miscellaneous - ${d.invoice_number}`;
      setInvoiceType(d.invoice_type || "");
      $("invoice_number").value = d.invoice_number || "";
      setDate("invoice_date", d.invoice_date);
      await loadMapping();
      $("misc_status").value = d.status || "Confirmed";
      $("user_name").value = d.user_name || "";
      $("reference").value = d.reference || "";
      setDate("ref_date", d.ref_date);
      $("payment_mode").value = d.payment_mode || "";
      $("payment_gateway_ref").value = d.payment_gateway_ref || "";
      $("customer").value = d.customer_name || "";
      fillCustomerInfo();
      $("supplier").value = d.supplier_name || "";
      $("supplier_id").value = supplierIdFor(d.supplier_name);
      $("description").value = d.description || "";
      AMOUNT_IDS.forEach((k) => { $(k).value = fmtN(d[k]); });
      recalc();
      setViewMode(true);
    } catch (err) {
      voyagerAlert(err.message || "Could not load this Miscellaneous transaction.", { icon: "error" });
    }
  }

  // ---------- Find ----------
  const FIND_IDS = ["invoice", "reference", "customer", "supplier", "date-from", "date-to"];
  const emptyFind = `<tr><td colspan="8" style="text-align:center; padding:14px; color:#64748B;">Enter filters and click Search.</td></tr>`;
  $("misc-find-btn").addEventListener("click", () => { open("misc-find-modal"); setTimeout(() => $("fd-invoice").focus(), 0); });
  $("fd-clear-btn").addEventListener("click", () => {
    FIND_IDS.forEach((id) => { $(`fd-${id}`).value = ""; });
    $("fd-results-body").innerHTML = emptyFind;
  });
  $("fd-search-btn").addEventListener("click", () => runFind());
  FIND_IDS.forEach((id) => $(`fd-${id}`).addEventListener("keydown", (e) => { if (e.key === "Enter") runFind(); }));
  async function runFind() {
    const v = (id) => $(`fd-${id}`).value.trim().toLowerCase();
    const f = { invoice: v("invoice"), reference: v("reference"), customer: v("customer"), supplier: v("supplier"),
      from: $("fd-date-from").value, to: $("fd-date-to").value };
    const body = $("fd-results-body");
    body.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:14px; color:#64748B;">Searching...</td></tr>`;
    let rows = [];
    try {
      const res = await fetch(`${API}misc/list/?company_id=${activeCompanyId}`);
      rows = res.ok ? await res.json() : [];
    } catch (_) { rows = []; }
    const has = (val, q) => !q || String(val || "").toLowerCase().includes(q);
    const found = rows.filter((r) => has(r.invoice_number, f.invoice) && has(r.reference, f.reference) &&
      has(r.customer_name, f.customer) && has(r.supplier_name, f.supplier) &&
      (!f.from || (r.invoice_date || "") >= f.from) && (!f.to || (r.invoice_date || "") <= f.to));
    const dmy = (iso) => (iso || "").split("-").reverse().join("/");
    body.innerHTML = found.length
      ? found.map((r) => `<tr class="misc-result-row" data-id="${r.id}">
          <td style="padding:5px 8px;">${esc(r.invoice_number)}</td><td style="padding:5px 8px;">${dmy(r.invoice_date)}</td>
          <td style="padding:5px 8px;">${esc(r.reference) || "-"}</td><td style="padding:5px 8px;">${esc(r.customer_name) || "-"}</td>
          <td style="padding:5px 8px;">${esc(r.supplier_name) || "-"}</td>
          <td style="padding:5px 8px; max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${esc(r.description)}">${esc(r.description) || "-"}</td>
          <td style="padding:5px 8px;">${esc(r.status)}</td><td style="padding:5px 8px; text-align:right;">${f2(r.total_billed)}</td></tr>`).join("")
      : `<tr><td colspan="8" style="text-align:center; padding:14px; color:#64748B;">No saved Miscellaneous transaction found.</td></tr>`;
    body.querySelectorAll(".misc-result-row").forEach((tr) => tr.addEventListener("click", () => {
      close("misc-find-modal");
      window.VoyagerShell.navigateTo(`trans-misc.html?misc_saved_id=${tr.dataset.id}`);
    }));
  }

  // ---------- J.V ----------
  $("misc-jv-btn").addEventListener("click", async () => {
    if (!$("customer").value.trim() || !$("supplier").value.trim()) { voyagerAlert("Choose the Customer and Supplier first - the J.V is built from them."); return; }
    try {
      const res = await fetch(`${API}misc/jv-preview-draft/`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(buildPayload()) });
      const d = await res.json();
      if (!res.ok) throw new Error(d.error || "Could not build the J.V.");
      $("misc-jv-title").textContent = savedId ? `Journal Voucher - ${$("invoice_number").value}` : "Journal Voucher (preview)";
      $("misc-jv-meta").textContent = d.cancelled
        ? "Status is Cancelled - this transaction posts no Journal Voucher. (Shown below as it would post when Confirmed.)"
        : `Date: ${d.voucher_date ? d.voucher_date.split("-").reverse().join("/") : "-"}   |   Narration: ${d.narration || "-"}`;
      $("misc-jv-body").innerHTML = d.accounts.map((a) => `<tr><td>${esc(a.ledger_name)}</td>
          <td style="text-align:right;">${a.debit ? f2(a.debit) : ""}</td><td style="text-align:right;">${a.credit ? f2(a.credit) : ""}</td></tr>`).join("")
        + `<tr style="font-weight:700;"><td>Total</td><td style="text-align:right;">${f2(d.total_debit)}</td><td style="text-align:right;">${f2(d.total_credit)}</td></tr>`;
      open("misc-jv-modal");
    } catch (err) {
      voyagerAlert(err.message || "Could not build the J.V. Is the Django backend running?", { icon: "error" });
    }
  });

  recalc();
  if (savedId) await loadSaved(savedId);
})();
