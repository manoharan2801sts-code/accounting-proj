(async function () {
  // SSR Updation. New finds the live passenger (Booking, or its latest
  // Reschedule - same lookup the Cancellation screen uses), the Passenger +
  // Sector picker adds one SSR line per pick, and Save SSR stores it through
  // /api/ssr-tickets/ (dbo.sp_SSRTicket) and posts its own ALS-n JV. GST % and
  // the JV ledgers come from Ledger Mapping (SSR Markup / SSR Service Fee and
  // the Supplier SSR Markup / Supplier SSR Service Fee fields).
  const API = "/api/";
  const n = (v) => Number(String(v || "").replace(/,/g, "")) || 0;
  // Money amounts follow Company Master's "No. of Decimals" (same as the
  // ticket screen's fmtN) - f2 for display, fmtN for amount input boxes.
  // Percentages (GST %) stay at 2 decimals.
  const dp = () => VoyagerUtil.getDecimalPlaces();
  const f2 = (v) => n(v).toLocaleString("en-IN", { minimumFractionDigits: dp(), maximumFractionDigits: dp() });
  const fmtN = (v) => n(v).toFixed(dp());
  const pct = (v) => n(v).toFixed(2);
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const savedId = new URLSearchParams(window.location.search).get("ssr_saved_id");
  let lines = [];
  let editing = null;
  let activeCompanyId = null;
  let voucherTypes = [];
  let viewMode = false;
  let savedVoucherNo = "";   // the saved SSR's posted J.V number (ALS-n)
  // The picked ticket: original Booking id, the Reschedule its live data
  // came from (if any) and its customer - what Save sends.
  let source = null;

  // Dates first - the calendar built during shell init shows whatever
  // value the input already has.
  const today = new Date().toISOString().slice(0, 10);
  $("invoice_date").value = today;
  $("ssr_ref_date").value = today;
  const setDate = (id, iso) => { $(id).value = iso || ""; $(id).dispatchEvent(new Event("change")); };

  const active = await VoyagerShell.init({ activeKey: "trans-airline-ssr" });
  activeCompanyId = Number(active && active.id) || 1;
  await VoyagerUtil.loadDecimalPlaces(activeCompanyId);
  $("ssr-user-name-options").innerHTML = window.VoyagerHardcode.dropdownValues("userNames").map((v) => `<option value="${esc(v)}">`).join("");

  // ---------- Ledger Mapping: GST % + which fields have a ledger ----------
  const FIELD = {
    markup: "SSR Markup A/c", service_fee: "SSR Service Fee A/c",
    supp_markup: "Supplier SSR Markup A/c", supp_service_fee: "Supplier SSR Service Fee A/c",
  };
  let mapped = new Set();
  let gstPct = {};
  // Ledger Mapping in force on the SSR's Invoice Date (effective dates) -
  // reloaded when the date changes, same as the server's JV / totals.
  async function loadMapping() {
    const asOf = $("invoice_date").value;
    try {
      const res = await fetch(`${API}master-mapping/?company_id=${activeCompanyId}&product_type=Airline` + (asOf ? `&as_of=${asOf}` : ""));
      const next = new Set(), pct = {};
      (res.ok ? await res.json() : []).forEach((r) => { next.add(r.field_name); pct[r.field_name] = Number(r.ledger_gst_percentage) || 0; });
      mapped = next; gstPct = pct;
    } catch (_) { mapped = new Set(); gstPct = {}; }
  }
  await loadMapping();
  $("invoice_date").addEventListener("change", async () => { await loadMapping(); render(); });
  const custGstPct = () => gstPct[FIELD.service_fee] || 0;
  const suppGstPct = () => gstPct[FIELD.supp_service_fee] || 0;

  // ---------- Payment Mode -> Gateway Ref (same as the Booking screen) ----------
  // Gateway Ref lists PG Master's active gateways and is only enabled (and
  // only saved) when Payment Mode is Payment Gateway.
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
  // Invoice Type = Voucher Type master entries under General only (same as
  // Booking / Reschedule) - Journal / Payment / Receipt ... types belong to
  // the Voucher screen, Credit Note types to Cancellation.
  $("invoice_type").innerHTML = `<option value="">Select...</option>` +
    voucherTypes.filter((v) => v.is_active && v.voucher_category === "Airline")
      .map((v) => `<option value="${esc(v.name)}">${esc(v.name)}</option>`).join("");
  // A saved SSR's own type stays visible even if it's not in that list.
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

  // ---------- SSR lines grid + summary ----------
  // Total (what the customer pays) = SSR charges + Customer SSR Markup +
  // Customer SSR Service Fee + its GST + Supplier SSR Markup + Supplier SSR
  // Service Fee + its GST - same convention as a Booking's Total.
  // Purchase (what the supplier is owed) = SSR charges + Supplier SSR
  // Markup + Supplier SSR Service Fee + its GST.
  // Earnings = Sales - Purchase. Same formula as views._ssr_line_amounts.
  function lineTotals(l) {
    const ssr = n(l.seat) + n(l.meal) + n(l.baggage) + n(l.other_ssr);
    const gst = n(l.service_fee) * custGstPct() / 100;
    const suppGst = n(l.supp_service_fee) * suppGstPct() / 100;
    const purchase = ssr + n(l.supp_markup) + n(l.supp_service_fee) + suppGst;
    return {
      ssr, gst, suppGst, purchase,
      total: purchase + n(l.markup) + n(l.service_fee) + gst,
    };
  }
  function ssrSummary(l) {
    return Object.entries(l.ssr_items || {}).filter(([, v]) => v).map(([k, v]) => `${k}: ${v}`).join(", ");
  }

  // Grid Markup / Service Fee / GST columns = customer + supplier SSR
  // figures (the customer is billed both - see lineTotals).
  function render() {
    $("ssr-lines").innerHTML = lines.length
      ? lines.map((l, i) => {
          const t = lineTotals(l);
          return `<tr class="pax-row ssr-row" data-idx="${i}" title="Double-click to ${viewMode ? "view" : "edit"}">
            <td style="text-align:center;">${i + 1}</td><td>${esc(l.ticket_no) || "-"}</td><td>${esc(l.pax_name) || "-"}</td>
            <td>${esc(l.sector) || "-"}</td><td>${esc(ssrSummary(l)) || "-"}</td>
            <td class="num">${f2(l.seat)}</td><td class="num">${f2(l.meal)}</td><td class="num">${f2(l.baggage)}</td><td class="num">${f2(l.other_ssr)}</td>
            <td class="num">${f2(n(l.markup) + n(l.supp_markup))}</td><td class="num">${f2(n(l.service_fee) + n(l.supp_service_fee))}</td>
            <td class="num">${f2(t.gst + t.suppGst)}</td>
            <td class="num" style="font-weight:700;">${f2(t.total)}</td>
          </tr>`;
        }).join("")
      : `<tr class="pax-row pax-add-row"><td colspan="13" style="text-align:center; padding:14px; font-size:11.5px;">No SSR added yet. Click <strong style="color:#3B6DB5;">New</strong> to pick the ticket, passenger and sector, then double-click a row to enter its SSR.</td></tr>`;

    const sum = (fn) => lines.reduce((s, l) => s + fn(l), 0);
    const ssr = sum((l) => lineTotals(l).ssr);
    const pc = { markup: sum((l) => n(l.supp_markup)), sfee: sum((l) => n(l.supp_service_fee)), gst: sum((l) => lineTotals(l).suppGst) };
    // Sales Cost's Markup / Service Fee / GST fold in the supplier side too
    // (the customer is billed both), same as the ticket screen's summary.
    const sc = {
      markup: sum((l) => n(l.markup)) + pc.markup, sfee: sum((l) => n(l.service_fee)) + pc.sfee,
      gst: sum((l) => lineTotals(l).gst) + pc.gst,
    };
    const salesTotal = ssr + sc.markup + sc.sfee + sc.gst, purchaseTotal = ssr + pc.markup + pc.sfee + pc.gst;
    $("pc-ssr").textContent = f2(ssr); $("pc-markup").textContent = f2(pc.markup); $("pc-sfee").textContent = f2(pc.sfee);
    $("pc-gst").textContent = f2(pc.gst); $("pc-total").textContent = f2(purchaseTotal);
    $("sc-ssr").textContent = f2(ssr); $("sc-markup").textContent = f2(sc.markup); $("sc-sfee").textContent = f2(sc.sfee);
    $("sc-gst").textContent = f2(sc.gst); $("sc-total").textContent = f2(salesTotal);
    // Earnings = Customer Markup + Addl Markup + SSR Markup + Customer Service
    // Fee + Addl Service Fee + SSR Service Fee + Supplier Commission -
    // Customer Discount. An SSR line carries just the customer SSR Markup and
    // SSR Service Fee (no addl fields, commission or discount - those are 0).
    $("earnings_total").textContent = f2(sum((l) => n(l.markup)) + sum((l) => n(l.service_fee)));
  }

  const open = (id) => $(id).classList.add("open");
  const close = (id) => $(id).classList.remove("open");
  document.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => close(b.dataset.close)));
  document.querySelectorAll(".dom-date-type-btn").forEach((btn) => btn.addEventListener("click", () => {
    const group = btn.closest(".dom-date-type-toggle");
    group.querySelectorAll(".dom-date-type-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    group.dataset.value = btn.dataset.value;
  }));

  // ---------- SSR fare breakup popup (double-click a row) ----------
  // Line-level amount fields - each is the SUM of the popup grid's rows, so
  // the J.V, reports and prints keep reading the same columns.
  const EDIT_FIELDS = ["seat", "meal", "baggage", "other_ssr", "markup", "service_fee", "supp_markup", "supp_service_fee"];
  const INFO_FIELDS = { airline_category: "m-airline-category", ticket_no: "m-ticket-no", pax_name: "m-pax-name",
    pax_type: "m-pax-type", sector: "m-sector", office_id: "m-office-id", supplier: "m-supplier" };
  // FOP and Card Number are editable, same as the Reschedule screen: Cash,
  // plus Own Card / Client Card only when FOP Master has an ACTIVE card of
  // that type; Card Number lists that type's active cards (none for Cash).
  let fopChoices = ["Cash"];
  let activeCards = [];
  (async () => {
    try {
      const res = await fetch(`${API}fop-master/?company_id=${activeCompanyId}`);
      activeCards = (res.ok ? await res.json() : []).filter((c) => c.is_active);
      const activeTypes = new Set(activeCards.map((c) => c.card_type));
      fopChoices = ["Cash", ...window.VoyagerHardcode.dropdownValues("fopOptions").filter((o) => o !== "Cash" && activeTypes.has(o))];
    } catch (err) {
      console.error("Could not load FOP Master cards", err);
    }
  })();
  const options = (list) => list.map((o) => `<option value="${esc(o)}">${esc(o)}</option>`).join("");
  function fillFop(current) {
    // A saved line keeps showing its own FOP / card even if it is no longer active.
    const choices = current && !fopChoices.includes(current) ? [...fopChoices, current] : fopChoices;
    $("m-fop").innerHTML = options(choices);
    $("m-fop").value = current && choices.includes(current) ? current : "Cash";
  }
  function fillCardNumber(current) {
    const fop = $("m-fop").value;
    const sel = $("m-card-number");
    if (fop === "Cash") {
      sel.innerHTML = "";
      sel.disabled = true;
      return;
    }
    const cards = activeCards.filter((c) => c.card_type === fop).map((c) => c.card_number);
    const choices = current && !cards.includes(current) ? [...cards, current] : cards;
    sel.innerHTML = `<option value="">Select...</option>` + options(choices);
    sel.value = current && choices.includes(current) ? current : "";
    sel.disabled = viewMode;
  }
  $("m-fop").addEventListener("change", () => fillCardNumber(""));
  const SSR_TYPES = window.VoyagerHardcode.dropdownValues("ssrTypes");
  // SSR type -> the line's amount column it adds into.
  const TYPE_AMOUNT_FIELD = { Baggage: "baggage", Meal: "meal", Seat: "seat", "Other SSR": "other_ssr" };
  // Per-row charge boxes, in grid order (supplier side first, as the header).
  const ROW_CHARGES = ["amount", "supp_markup", "supp_service_fee", "markup", "service_fee"];
  const amtBox = (t, k) => `<input class="dom-input dom-amount m-ssr-amt" type="text" inputmode="decimal" data-type="${esc(t)}" data-k="${k}" value="0.00" />`;
  // One row per SSR type: Type | EMD | Details | Amt | Supplier SSR Markup /
  // SSR Service Fee / GST Amt | Customer SSR Markup / SSR Service Fee / GST Amt.
  $("m-ssr-rows").innerHTML = SSR_TYPES.map((t, i) => `<tr data-type="${esc(t)}">
      <td class="m-ssr-type">${esc(t)}</td>
      <td><input class="dom-input m-ssr-tkt" data-type="${esc(t)}" id="m-ssr-tkt-${i}" maxlength="30" placeholder="EMD ticket number" /></td>
      <td><input class="dom-input m-ssr-item" data-type="${esc(t)}" id="m-ssr-item-${i}" maxlength="60" placeholder="Code / item" /></td>
      <td>${amtBox(t, "amount")}</td>
      <td class="m-ssr-grp-start">${amtBox(t, "supp_markup")}</td><td>${amtBox(t, "supp_service_fee")}</td><td class="m-ssr-ro m-supp-gst">0.00</td>
      <td class="m-ssr-grp-start">${amtBox(t, "markup")}</td><td>${amtBox(t, "service_fee")}</td><td class="m-ssr-ro m-cust-gst">0.00</td>
    </tr>`).join("");
  const rowOf = (t) => Array.from(document.querySelectorAll("#m-ssr-rows tr")).find((tr) => tr.dataset.type === t);
  const box = (t, k) => rowOf(t).querySelector(`.m-ssr-amt[data-k="${k}"]`);
  function readModal() {
    const l = { ssr_items: {}, ssr_ticket_numbers: {}, ssr_charges: {} };
    EDIT_FIELDS.forEach((k) => { l[k] = 0; });
    SSR_TYPES.forEach((t) => {
      const c = {};
      ROW_CHARGES.forEach((k) => { c[k] = n(box(t, k).value); });
      if (ROW_CHARGES.some((k) => c[k])) l.ssr_charges[t] = c;
      const amountField = TYPE_AMOUNT_FIELD[t] || "other_ssr";
      l[amountField] += c.amount;
      ["markup", "service_fee", "supp_markup", "supp_service_fee"].forEach((k) => { l[k] += c[k]; });
    });
    document.querySelectorAll(".m-ssr-item").forEach((el) => { if (el.value.trim()) l.ssr_items[el.dataset.type] = el.value.trim(); });
    document.querySelectorAll(".m-ssr-tkt").forEach((el) => { if (el.value.trim()) l.ssr_ticket_numbers[el.dataset.type] = el.value.trim(); });
    return l;
  }
  function recalcModal() {
    const l = readModal();
    const t = lineTotals(l);
    SSR_TYPES.forEach((ty) => {
      const tr = rowOf(ty);
      tr.querySelector(".m-supp-gst").textContent = f2(n(box(ty, "supp_service_fee").value) * suppGstPct() / 100);
      tr.querySelector(".m-cust-gst").textContent = f2(n(box(ty, "service_fee").value) * custGstPct() / 100);
    });
    $("m-supp-head").title = `GST Amt = SSR Service Fee x ${pct(suppGstPct())}% (GST % of "${FIELD.supp_service_fee}" in Ledger Mapping)`;
    $("m-cust-head").title = `GST Amt = SSR Service Fee x ${pct(custGstPct())}% (GST % of "${FIELD.service_fee}" in Ledger Mapping)`;
    $("m-ssr-total").textContent = f2(t.ssr);
    $("m-supp-markup-total").textContent = f2(l.supp_markup); $("m-supp-sfee-total").textContent = f2(l.supp_service_fee);
    $("m-supp-gst-amt").textContent = f2(t.suppGst);
    $("m-markup-total").textContent = f2(l.markup); $("m-sfee-total").textContent = f2(l.service_fee);
    $("m-gst-amt").textContent = f2(t.gst);
    $("m-total").textContent = f2(t.total);
  }
  // (Leaving a box formats it to the company's decimals - shared, util.js.)
  // Same rule as the Booking screen: a markup / service fee can't hold an
  // amount until its ledger is set in Ledger Mapping. Every SSR type's markup
  // / service fee posts to the same single mapped ledger.
  const guardWarned = new Set();
  document.querySelectorAll(".m-ssr-amt").forEach((el) => el.addEventListener("input", (e) => {
    const k = el.dataset.k;
    if (FIELD[k] && !mapped.has(FIELD[k]) && n(e.target.value) !== 0) {
      e.target.value = fmtN(0);
      if (!guardWarned.has(k)) { guardWarned.add(k); voyagerAlert(`Required Ledger account is not mapped ("${FIELD[k]}" in Ledger Mapping).`); }
    }
    recalcModal();
  }));

  // Per-type charges of a line. Lines saved before the grid have no
  // ssr_charges: each type gets its own amount column, and the line's markup
  // / service fees sit on its first entered type.
  function chargesOf(l) {
    if (l.ssr_charges && Object.keys(l.ssr_charges).length) return l.ssr_charges;
    const out = {};
    SSR_TYPES.forEach((t) => { out[t] = { amount: n(l[TYPE_AMOUNT_FIELD[t] || "other_ssr"]) }; });
    const first = SSR_TYPES.find((t) => (l.ssr_items || {})[t] || out[t].amount) || SSR_TYPES[0];
    if (first) ["markup", "service_fee", "supp_markup", "supp_service_fee"].forEach((k) => { out[first][k] = n(l[k]); });
    return out;
  }

  function openLine(idx) {
    editing = idx;
    const l = lines[idx];
    Object.entries(INFO_FIELDS).forEach(([k, id]) => { $(id).textContent = l[k] || "—"; });
    // No auto-fill from another passenger (unlike the ticket screen): SSR
    // fares and details differ per passenger, so each line is typed by hand.
    const charges = chargesOf(l);
    SSR_TYPES.forEach((t) => ROW_CHARGES.forEach((k) => { box(t, k).value = fmtN((charges[t] || {})[k] || 0); }));
    document.querySelectorAll(".m-ssr-item").forEach((el) => { el.value = (l.ssr_items || {})[el.dataset.type] || ""; });
    document.querySelectorAll(".m-ssr-tkt").forEach((el) => { el.value = (l.ssr_ticket_numbers || {})[el.dataset.type] || ""; });
    document.querySelectorAll("#ssr-modal input").forEach((el) => { el.disabled = viewMode; });
    fillFop(l.fop);
    $("m-fop").disabled = viewMode;
    fillCardNumber(l.card_number);
    $("m-save-btn").style.display = viewMode ? "none" : "";
    $("m-remove-btn").style.display = viewMode ? "none" : "";
    $("ssr-modal-title").textContent = `SSR #${idx + 1} - ${l.pax_name || ""} (${l.sector || ""})`;
    recalcModal();
    open("ssr-modal");
  }
  $("m-save-btn").addEventListener("click", () => {
    const l = readModal();
    if (!Object.keys(l.ssr_items).length) { voyagerAlert("Enter at least one SSR detail (Baggage, Meal, Seat...)."); return; }
    // A type with an EMD number or any amount must say what the SSR is.
    const noDetail = SSR_TYPES.find((t) => !l.ssr_items[t] && (l.ssr_ticket_numbers[t] || l.ssr_charges[t]));
    if (noDetail) { voyagerAlert(`Enter the SSR Details for ${noDetail}.`); rowOf(noDetail).querySelector(".m-ssr-item").focus(); return; }
    const fop = $("m-fop").value;
    const cardNumber = fop === "Cash" ? "" : $("m-card-number").value;
    if (fop !== "Cash" && !cardNumber) { voyagerAlert(`Select the Card Number for FOP ${fop}.`, { focusEl: $("m-card-number") }); return; }
    lines[editing] = { ...lines[editing], ...l, fop, card_number: cardNumber };
    close("ssr-modal"); render();
  });
  $("m-remove-btn").addEventListener("click", async () => {
    const ok = await voyagerConfirm("Remove this SSR line?", { title: "Remove SSR", confirmLabel: "Remove", icon: "warning" });
    if (!ok) return;
    lines.splice(editing, 1);
    close("ssr-modal"); render();
  });
  $("ssr-lines").addEventListener("dblclick", (e) => {
    const row = e.target.closest(".ssr-row");
    if (row) openLine(Number(row.dataset.idx));
  });

  // ---------- Shared filter reading (New + Find use the same filter set) ----------
  const FILTER_IDS = ["invoice", "spnr", "airline-pnr", "gds-pnr", "ticket-no", "customer", "airline-code", "date-from", "date-to"];
  function readFilters(px) {
    const v = (id) => $(`${px}-${id}`).value.trim().toLowerCase();
    return {
      invoice: v("invoice"), spnr: v("spnr"), airlinePnr: v("airline-pnr"), gdsPnr: v("gds-pnr"), ticketNo: v("ticket-no"),
      customer: v("customer"), airlineCode: v("airline-code"), dateType: $(`${px}-date-type`).dataset.value,
      dateFrom: $(`${px}-date-from`).value, dateTo: $(`${px}-date-to`).value,
    };
  }
  const anyFilter = (f) => f.invoice || f.spnr || f.airlinePnr || f.gdsPnr || f.ticketNo || f.customer || f.airlineCode || f.dateFrom || f.dateTo;
  const toISO = (d) => {
    const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(String(d || "").trim());
    return m ? `${m[3]}-${m[2]}-${m[1]}` : String(d || "").slice(0, 10);
  };
  function matches(r, f) {
    const has = (val, q) => !q || String(val || "").toLowerCase().includes(q);
    let dateOk = true;
    if (f.dateFrom || f.dateTo) {
      const raw = r[f.dateType] || "";
      const list = f.dateType === "travel_date" ? raw.split(",").map((d) => toISO(d)).filter(Boolean) : (raw ? [toISO(raw)] : []);
      dateOk = list.some((iso) => (!f.dateFrom || iso >= f.dateFrom) && (!f.dateTo || iso <= f.dateTo));
    }
    return has(r.invoice_number, f.invoice) && has(r.booking_reference, f.spnr) && has(r.airline_pnr, f.airlinePnr) &&
      has(r.gds_pnr, f.gdsPnr) && has(r.ticket_no, f.ticketNo) && has(r.customer_name, f.customer) &&
      has(r.airline_code, f.airlineCode) && dateOk;
  }
  ["nl", "fd"].forEach((px) => FILTER_IDS.forEach((id) => $(`${px}-${id}`).addEventListener("keydown", (e) => {
    if (e.key === "Enter") (px === "nl" ? runNewSearch : runFind)();
  })));

  // ---------- New: live Booking / Reschedule lookup ----------
  let lookupPassengers = [];
  let lookupData = null;
  function openNewLookup() {
    if (savedId) { window.VoyagerShell.navigateTo("trans-airline-ssr.html"); return; }
    FILTER_IDS.forEach((id) => { $(`nl-${id}`).value = ""; });
    $("nl-results-wrap").style.display = "none";
    $("nl-results-body").innerHTML = "";
    open("ssr-lookup-modal");
  }
  $("ssr-new-btn").addEventListener("click", openNewLookup);
  $("nl-proceed-btn").addEventListener("click", () => runNewSearch());

  async function runNewSearch() {
    const f = readFilters("nl");
    if (!anyFilter(f)) { voyagerAlert("Enter at least one filter before searching."); return; }
    // Original tickets AND saved reschedules - a rescheduled passenger's
    // live data (new PNR / ticket no) lives on the reschedule.
    let rows = [];
    try {
      const [tRes, rRes] = await Promise.all([
        fetch(`${API}tickets/?company_id=${activeCompanyId}`),
        fetch(`${API}reschedule-tickets/list/?company_id=${activeCompanyId}`),
      ]);
      rows = [...(tRes.ok ? await tRes.json() : []), ...(rRes.ok ? await rRes.json() : [])];
    } catch (_) { rows = []; }
    const byTicket = new Map();
    rows.filter((r) => matches(r, f)).forEach((r) => {
      const key = r.reschedule_ticket_id ? `r${r.reschedule_ticket_id}` : `t${r.ticket_id}`;
      const ex = byTicket.get(key);
      if (!ex) byTicket.set(key, { row: r, paxCount: 1 }); else ex.paxCount += 1;
    });
    const found = Array.from(byTicket.values());
    if (!found.length) { voyagerAlert("No matching ticket found."); return; }
    const ticketNoOnly = !!f.ticketNo && !f.invoice && !f.spnr && !f.airlinePnr && !f.gdsPnr && !f.customer && !f.airlineCode && !f.dateFrom && !f.dateTo;
    const pick = (row) => lookupTicket({
      sPnr: ticketNoOnly ? "" : (row.booking_reference || ""), ticketNo: ticketNoOnly ? (row.ticket_no || "") : "", ticketNoOnly,
    });
    if (found.length === 1) { pick(found[0].row); return; }
    $("nl-results-body").innerHTML = found.map(({ row, paxCount }, i) => `
      <tr class="ssr-result-row" data-idx="${i}">
        <td style="padding:5px 8px;">${esc(row.invoice_number) || "-"}</td><td style="padding:5px 8px;">${esc(row.booking_reference) || "-"}</td>
        <td style="padding:5px 8px;">${esc(row.airline_pnr) || "-"}</td><td style="padding:5px 8px;">${esc(row.customer_name) || "-"}</td>
        <td style="padding:5px 8px;">${esc(row.airline_name || row.airline_code) || "-"}</td><td style="padding:5px 8px;">${paxCount}</td>
      </tr>`).join("");
    $("nl-results-body").querySelectorAll(".ssr-result-row").forEach((tr) => tr.addEventListener("click", () => pick(found[Number(tr.dataset.idx)].row)));
    $("nl-results-wrap").style.display = "";
  }

  async function lookupTicket({ sPnr, ticketNo, ticketNoOnly }) {
    try {
      const params = new URLSearchParams({ company_id: activeCompanyId, s_pnr: sPnr, airline_pnr: "", ticket_no: ticketNo });
      const res = await fetch(`${API}tickets/lookup-for-cancellation/?${params}`);
      const data = await res.json();
      if (!res.ok) throw new Error((data.error || "Ticket not found.").replace("left to cancel", "available for SSR"));
      lookupData = data;
      lookupPassengers = (ticketNoOnly && data.matched_line_id)
        ? (data.passengers || []).filter((p) => p.line_id === data.matched_line_id)
        : (data.passengers || []);
      renderPicker();
      close("ssr-lookup-modal");
      // One passenger with one sector - nothing to choose (renderPicker has
      // already ticked both), so add the SSR line straight away.
      if (document.querySelectorAll(".sp-pax").length === 1 && document.querySelectorAll(".sp-sector").length === 1) {
        $("sp-add-btn").click();
        return;
      }
      open("ssr-pax-modal");
    } catch (err) {
      voyagerAlert(err.message || "Could not search for this ticket. Is the Django backend running?", { icon: "error" });
    }
  }

  // ---------- Passenger + Sector picker ----------
  let pickerSectors = [];
  function renderPicker() {
    $("sp-pax-tbody").innerHTML = lookupPassengers.length
      ? lookupPassengers.map((p, i) => `<tr><td><input type="checkbox" class="sp-pax" data-idx="${i}" /></td>
          <td>${esc(p.pax_type) || "-"}</td><td>${esc(p.passenger_name) || "-"}</td><td>${esc(p.ticket_no) || "-"}</td></tr>`).join("")
      : `<tr><td colspan="4" style="text-align:center; padding:1rem; color:#64748B;">No passengers on this ticket.</td></tr>`;
    const seen = new Set();
    pickerSectors = [];
    lookupPassengers.forEach((p) => (p.sectors || []).forEach((s) => {
      const key = `${s.sector}|${s.flight_no}|${s.travel_class}|${s.travel_date}`;
      if (!seen.has(key)) { seen.add(key); pickerSectors.push(s); }
    }));
    $("sp-sector-tbody").innerHTML = pickerSectors.length
      ? pickerSectors.map((s, i) => `<tr><td><input type="checkbox" class="sp-sector" data-idx="${i}" /></td>
          <td>${esc(s.sector) || "-"}</td><td>${esc(s.flight_no) || "-"}</td><td>${esc(s.travel_class) || "-"}</td><td>${esc(s.travel_date) || "-"}</td></tr>`).join("")
      : `<tr><td colspan="5" style="text-align:center; padding:1rem; color:#64748B;">No sectors on this ticket.</td></tr>`;
    // Only one passenger / one sector - nothing to choose, tick it.
    if (lookupPassengers.length === 1) document.querySelector(".sp-pax").checked = true;
    if (pickerSectors.length === 1) document.querySelector(".sp-sector").checked = true;
    $("sp-pax-all").checked = false; $("sp-sector-all").checked = false;
    updatePickerState();
  }
  function updatePickerState() {
    const paxBoxes = document.querySelectorAll(".sp-pax"), secBoxes = document.querySelectorAll(".sp-sector");
    const anyPax = Array.from(paxBoxes).some((c) => c.checked), anySec = Array.from(secBoxes).some((c) => c.checked);
    $("sp-pax-all").checked = paxBoxes.length > 0 && Array.from(paxBoxes).every((c) => c.checked);
    $("sp-sector-all").checked = secBoxes.length > 0 && Array.from(secBoxes).every((c) => c.checked);
    $("sp-add-btn").disabled = !(anyPax && anySec);
  }
  $("ssr-pax-modal").addEventListener("change", (e) => {
    if (e.target.id === "sp-pax-all") document.querySelectorAll(".sp-pax").forEach((c) => { c.checked = e.target.checked; });
    if (e.target.id === "sp-sector-all") document.querySelectorAll(".sp-sector").forEach((c) => { c.checked = e.target.checked; });
    updatePickerState();
  });

  $("sp-add-btn").addEventListener("click", async () => {
    const pax = Array.from(document.querySelectorAll(".sp-pax:checked")).map((c) => lookupPassengers[Number(c.dataset.idx)]);
    const secs = Array.from(document.querySelectorAll(".sp-sector:checked")).map((c) => pickerSectors[Number(c.dataset.idx)]);
    const rid = lookupData.source_reschedule_ticket_id;
    let t;
    try {
      const url = rid ? `${API}reschedule-tickets/${rid}/?company_id=${activeCompanyId}` : `${API}tickets/${lookupData.ticket_id}/?company_id=${activeCompanyId}`;
      const res = await fetch(url);
      t = await res.json();
      if (!res.ok) throw new Error(t.error || "Ticket not found.");
    } catch (err) {
      voyagerAlert(err.message || "Could not load this ticket.", { icon: "error" });
      return;
    }
    source = { ticketId: lookupData.ticket_id, rescheduleId: rid || null, customer: t.customer_name || "" };
    // Invoice Type follows the picked Booking / Reschedule's own type, and
    // its change handler fills Invoice Number with that type's last number + 1.
    // SSR Reference is the picked ticket's own Booking Reference (not
    // editable - the field stays disabled).
    $("ssr_reference").value = t.booking_reference || "";
    const typeSel = $("invoice_type");
    if (t.invoice_type && Array.from(typeSel.options).some((o) => o.value === t.invoice_type)) {
      typeSel.value = t.invoice_type;
      typeSel.dispatchEvent(new Event("change"));
    }
    await fillHeaderInfo({
      original_invoice: t.invoice_number, customer_name: t.customer_name, travel_type: t.travel_type,
      airline_pnr: t.airline_pnr, gds_pnr: t.gds_pnr, currency: t.currency, roe: t.roe,
    });
    // One SSR line per picked passenger x picked sector the passenger flies.
    // A rescheduled passenger's line_id is its reschedule line; the booking
    // line it traces back to is that line's original_ticket_line_id.
    lines = [];
    pax.forEach((p) => {
      const tl = (t.lines || []).find((l) => l.id === p.line_id) || {};
      const flies = new Set((p.sectors || []).map((s) => s.sector));
      secs.filter((s) => flies.has(s.sector)).forEach((s) => lines.push({
        original_ticket_line_id: rid ? tl.original_ticket_line_id : p.line_id, reschedule_line_id: rid ? p.line_id : null,
        ticket_no: p.ticket_no, pax_name: p.passenger_name, pax_type: p.pax_type || tl.pax_type || "",
        sector: s.sector, airline_category: tl.airline_category || "", office_id: tl.office_id || "",
        // FOP starts as Cash (not the ticket's own) - changed in the SSR popup when the SSR is paid by card.
        supplier: tl.supplier_name || t.supplier_name || "", fop: "Cash", card_number: "",
        ssr_items: {}, ssr_ticket_numbers: {}, ssr_charges: {}, seat: 0, meal: 0, baggage: 0, other_ssr: 0, markup: 0, service_fee: 0, supp_markup: 0, supp_service_fee: 0,
      }));
    });
    close("ssr-pax-modal");
    render();
    if (lines.length === 1) openLine(0);
  });

  async function fillHeaderInfo(h) {
    $("original_invoice").textContent = h.original_invoice || "—";
    $("customer").textContent = h.customer_name || "—";
    $("travel_type").textContent = h.travel_type || "—";
    $("airline_pnr").textContent = h.airline_pnr || "—";
    $("gds_pnr").textContent = h.gds_pnr || "—";
    $("currency").textContent = h.currency || "INR";
    $("roe").textContent = Number(h.roe || 1).toFixed(4);
    try {
      const res = await fetch(`${API}customers/?company_id=${activeCompanyId}`);
      const c = (res.ok ? await res.json() : []).find((x) => x.name === h.customer_name);
      $("customer_agent_id").textContent = (c && c.agent_id) || "—";
      $("customer_address").textContent = (c && c.address) || "—";
      $("customer_gst").textContent = (c && c.gst_no) || "—";
    } catch (_) { /* customer extras are display-only */ }
  }

  // ---------- Save / payload ----------
  // SSR Reference is never editable (always disabled in the HTML), and
  // Gateway Ref follows Payment Mode (see syncGatewayRef) - neither is here.
  const EDITABLE_HEADER_IDS = ["invoice_number", "invoice_date", "invoice_type", "user_name", "ssr_ref_date", "payment_mode"];
  function buildPayload() {
    return {
      company_id: activeCompanyId,
      original_ticket_id: source && source.ticketId, source_reschedule_ticket_id: source && source.rescheduleId,
      parent_pnr: source && source.parentPnr,   // direct SSR (Auto Push, no booking here) only
      customer_name: source && source.customer,
      invoice_number: $("invoice_number").value.trim(), invoice_date: $("invoice_date").value,
      invoice_type: $("invoice_type").value, user_name: $("user_name").value.trim(),
      ssr_reference: $("ssr_reference").value.trim(), ssr_ref_date: $("ssr_ref_date").value,
      payment_mode: $("payment_mode").value, payment_gateway_ref: $("payment_gateway_ref").value,
      travel_type: $("travel_type").textContent.replace("—", ""),
      airline_pnr: $("airline_pnr").textContent.replace("—", ""), gds_pnr: $("gds_pnr").textContent.replace("—", ""),
      currency: $("currency").textContent, roe: $("roe").textContent,
      lines: lines.map((l) => ({
        original_ticket_line_id: l.original_ticket_line_id, reschedule_line_id: l.reschedule_line_id,
        ticket_no: l.ticket_no, passenger_name: l.pax_name, pax_type: l.pax_type, airline_category: l.airline_category,
        sector: l.sector, office_id: l.office_id, supplier_name: l.supplier, fop: l.fop, card_number: l.card_number || "", ssr_items: l.ssr_items || {},
        ssr_ticket_numbers: l.ssr_ticket_numbers || {}, ssr_charges: l.ssr_charges || {},
        seat: n(l.seat), meal: n(l.meal), baggage: n(l.baggage), other_ssr: n(l.other_ssr),
        markup: n(l.markup), service_fee: n(l.service_fee), supp_markup: n(l.supp_markup), supp_service_fee: n(l.supp_service_fee),
      })),
    };
  }
  $("ssr-save-btn").addEventListener("click", async () => {
    if (!source) { voyagerAlert("Click New and pick the ticket, passenger and sector first."); return; }
    if (!lines.length) { voyagerAlert("Add at least one SSR line."); return; }
    const missing = [["invoice_type", "Invoice Type"], ["invoice_number", "Invoice Number"], ["invoice_date", "Invoice Date"], ["ssr_reference", "SSR Reference"]]
      .filter(([id]) => !$(id).value.trim()).map(([, label]) => label);
    if (missing.length) { voyagerAlert(`${missing.join(", ")} ${missing.length === 1 ? "is" : "are"} required.`); return; }
    const empty = lines.findIndex((l) => !ssrSummary(l));
    if (empty !== -1) { voyagerAlert(`SSR line ${empty + 1} (${lines[empty].pax_name}) has no SSR detail - double-click it to enter one.`); return; }
    try {
      const url = savedId ? `${API}ssr-tickets/${savedId}/update/` : `${API}ssr-tickets/create/`;
      const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(buildPayload()) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not save this SSR Updation.");
      await voyagerAlert(data.message || "SSR Updation saved.", { icon: "success" });
      window.VoyagerShell.navigateTo(`trans-airline-ssr.html?ssr_saved_id=${data.id}`);
    } catch (err) {
      voyagerAlert(err.message || "Could not save. Is the Django backend running?", { icon: "error" });
    }
  });

  // ---------- Saved SSR: view, Edit, Discard ----------
  function setViewMode(on) {
    viewMode = on;
    EDITABLE_HEADER_IDS.forEach((id) => { $(id).disabled = on; });
    syncGatewayRef();
    $("ssr-save-btn").style.display = on ? "none" : "";
    $("ssr-edit-btn").style.display = on && savedId ? "" : "none";
    $("ssr-print-btn").style.display = on && savedId ? "" : "none";
    // Opened from a report row (Day Book / Ledger) -> Back returns there,
    // same as the ticket screen's own Back link.
    const fromReport = [["report-day-book.html", "Day Book"], ["report-ledger-book.html", "Ledger"], ["customers.html", "Receivables"], ["suppliers.html", "Payables"], ["report-dsr-airline-booking.html", "Returns"], ["report-dsr.html", "DSR"]]
      .find(([page]) => document.referrer.includes(page));
    $("ssr-discard-btn").textContent = on ? `<- Back to ${fromReport ? fromReport[1] : "SSR"}` : "Discard";
    $("ssr-discard-btn").setAttribute("href", on
      ? (fromReport ? document.referrer : "trans-airline-ssr.html")
      : (savedId ? `trans-airline-ssr.html?ssr_saved_id=${savedId}` : "trans-airline-ssr.html"));
    render();
  }
  $("ssr-edit-btn").addEventListener("click", () => setViewMode(false));
  $("ssr-discard-btn").addEventListener("click", (e) => {
    e.preventDefault(); e.stopPropagation();
    const href = e.currentTarget.getAttribute("href");
    if (viewMode) { window.VoyagerShell.navigateTo(href); return; }
    voyagerConfirm("Discard this SSR Updation and any unsaved changes?", { title: "Confirm Discard", confirmLabel: "Discard", icon: "warning" })
      .then((ok) => { if (ok) window.VoyagerShell.navigateTo(href); });
  });

  async function loadSaved(id) {
    try {
      const res = await fetch(`${API}ssr-tickets/${id}/?company_id=${activeCompanyId}`);
      const d = await res.json();
      if (!res.ok) throw new Error(d.error || "SSR Updation not found.");
      $("page-title").textContent = `View SSR Updation - ${d.invoice_number}`;
      savedVoucherNo = d.voucher_no || "";
      setInvoiceType(d.invoice_type || "");
      $("invoice_number").value = d.invoice_number || "";
      setDate("invoice_date", d.invoice_date);
      $("user_name").value = d.user_name || "";
      $("ssr_reference").value = d.ssr_reference || "";
      setDate("ssr_ref_date", d.ssr_ref_date);
      $("payment_mode").value = d.payment_mode || "";
      $("payment_gateway_ref").value = d.payment_gateway_ref || "";
      source = { ticketId: d.original_ticket_id, rescheduleId: d.source_reschedule_ticket_id, customer: d.customer_name,
                 parentPnr: d.parent_pnr || null };
      await fillHeaderInfo({
        // A direct SSR (Auto Push) has no booking here - show the Parent PNR it came with.
        original_invoice: d.source_reschedule_invoice_number || d.original_invoice_number
          || (d.parent_pnr ? `Direct - Parent PNR ${d.parent_pnr}` : ""), customer_name: d.customer_name,
        travel_type: d.travel_type, airline_pnr: d.airline_pnr, gds_pnr: d.gds_pnr, currency: d.currency, roe: d.roe,
      });
      lines = (d.lines || []).map((l) => {
        // "Extra Baggage" was renamed "Baggage" - older saved lines still
        // carry the old key, so show it in the Baggage box.
        const items = { ...(l.ssr_items || {}) };
        if (items["Extra Baggage"] && !items.Baggage) items.Baggage = items["Extra Baggage"];
        delete items["Extra Baggage"];
        return { ...l, ssr_items: items, pax_name: l.passenger_name, supplier: l.supplier_name };
      });
      setViewMode(true);
    } catch (err) {
      voyagerAlert(err.message || "Could not load this SSR Updation.", { icon: "error" });
    }
  }

  // ---------- Find: saved SSR Updations ----------
  $("ssr-find-btn").addEventListener("click", () => open("ssr-find-modal"));
  $("fd-clear-btn").addEventListener("click", () => {
    FILTER_IDS.forEach((id) => { $(`fd-${id}`).value = ""; });
    $("fd-results-body").innerHTML = `<tr><td colspan="7" style="text-align:center; padding:14px; color:#64748B;">Enter filters and click Search.</td></tr>`;
  });
  $("fd-search-btn").addEventListener("click", () => runFind());
  async function runFind() {
    const f = readFilters("fd");
    const body = $("fd-results-body");
    body.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:14px; color:#64748B;">Searching...</td></tr>`;
    let rows = [];
    try {
      const res = await fetch(`${API}ssr-tickets/list/?company_id=${activeCompanyId}`);
      rows = res.ok ? await res.json() : [];
    } catch (_) { rows = []; }
    // "Booking Date" here = the SSR's own Invoice Date (no travel dates on an SSR line).
    const found = rows.map((r) => ({ ...r, issue_date: r.invoice_date, travel_date: r.invoice_date })).filter((r) => matches(r, f));
    body.innerHTML = found.length
      ? found.map((r) => `<tr class="ssr-result-row" data-id="${r.ssr_ticket_id}">
          <td style="padding:5px 8px;">${esc(r.invoice_number)}</td><td style="padding:5px 8px;">${esc(r.booking_reference) || "-"}</td>
          <td style="padding:5px 8px;">${esc(r.airline_pnr) || "-"}</td><td style="padding:5px 8px;">${esc(r.ticket_no) || "-"}</td>
          <td style="padding:5px 8px;">${esc(r.passenger_name) || "-"}</td><td class="ssr-cut" style="padding:5px 8px;" title="${esc(r.ssr_details)}">${esc(r.ssr_details) || "-"}</td>
          <td style="padding:5px 8px; text-align:right;">${f2(r.total_billed)}</td></tr>`).join("")
      : `<tr><td colspan="7" style="text-align:center; padding:14px; color:#64748B;">No saved SSR Updation found.</td></tr>`;
    body.querySelectorAll(".ssr-result-row").forEach((tr) => tr.addEventListener("click", () => {
      close("ssr-find-modal");
      window.VoyagerShell.navigateTo(`trans-airline-ssr.html?ssr_saved_id=${tr.dataset.id}`);
    }));
  }

  // ---------- J.V ----------
  // Same layout as the Booking / Reschedule J.V: Journal Voucher, plus FOP
  // Payment (FOP not Cash) and PG Receipts (Payment Gateway) tabs - shown
  // only when they have rows. The server builds all three (_ssr_jv_payload).
  const jvRows = (rows) => rows.map((a, i) => `<tr><td style="text-align:center;">${i + 1}</td><td>${esc(a.ledger_name || "-")}</td>
      <td class="num">${a.debit ? f2(a.debit) : ""}</td><td class="num">${a.credit ? f2(a.credit) : ""}</td></tr>`).join("");
  function switchJvTab(name) {
    document.querySelectorAll("#ssr-jv-tabs .dom-tab").forEach((t) => t.classList.toggle("active", t.dataset.jvTab === name));
    ["voucher", "fop", "pg"].forEach((k) => { $(`ssr-jv-panel-${k}`).style.display = k === name ? "" : "none"; });
  }
  $("ssr-jv-tabs").addEventListener("click", (e) => {
    const tab = e.target.closest(".dom-tab");
    if (tab && tab.style.display !== "none") switchJvTab(tab.dataset.jvTab);
  });
  function renderJv(d) {
    const accounts = (d.accounts || []).filter((a) => a.debit || a.credit);
    $("ssr-jv-title").textContent = savedId ? `Journal Voucher - ${$("invoice_number").value}` : "Journal Voucher (preview)";
    $("ssr-jv-vno").textContent = $("invoice_number").value.trim() || savedVoucherNo || "Preview";   // the Invoice Number, not ALS-n
    $("ssr-jv-date").textContent = d.voucher_date ? d.voucher_date.split("-").reverse().join("/") : "-";
    $("ssr-jv-currency").textContent = d.currency || $("currency").textContent || "INR";
    document.querySelectorAll(".ssr-jv-cur").forEach((el) => { el.textContent = $("ssr-jv-currency").textContent; });
    $("ssr-jv-body").innerHTML = jvRows(accounts);
    $("ssr-jv-total-debit").textContent = f2(d.total_debit);
    $("ssr-jv-total-credit").textContent = f2(d.total_credit);
    $("ssr-jv-narration").textContent = d.narration || "-";
    [["fop", d.fop], ["pg", d.pg]].forEach(([k, tab]) => {
      const rows = (tab && tab.accounts) || [];
      $(`ssr-jv-tab-btn-${k}`).style.display = rows.length ? "" : "none";
      $(`ssr-jv-${k}-body`).innerHTML = jvRows(rows);
      $(`ssr-jv-${k}-total-debit`).textContent = f2(tab ? tab.total_debit : 0);
      $(`ssr-jv-${k}-total-credit`).textContent = f2(tab ? tab.total_credit : 0);
    });
    switchJvTab("voucher");
    const balanced = Math.abs(n(d.total_debit) - n(d.total_credit)) < 0.01;
    $("ssr-jv-verify").innerHTML = !balanced
      ? `<span style="color:#DC2626;">X Unbalanced - Debit ${f2(d.total_debit)} != Credit ${f2(d.total_credit)}</span>`
      : !savedId ? `<span style="color:#D97706;">Computed - not yet posted (live preview)</span>`
      : !viewMode ? `<span style="color:#D97706;">Balanced - live preview of your unsaved changes (Posted ${esc(savedVoucherNo || "-")} updates on Save)</span>`
      : `<span style="color:#16A34A;">&#10003; Double-Entry Verification: Balanced (Posted ${esc(savedVoucherNo || "-")})</span>`;
  }
  $("ssr-jv-btn").addEventListener("click", async () => {
    if (!source || !lines.length) { voyagerAlert("Pick the ticket with New and add the SSR first - the J.V is built from it."); return; }
    if (lines.some((l) => !ssrSummary(l))) { voyagerAlert("Enter the SSR detail on every line first (double-click a row)."); return; }
    try {
      const res = await fetch(`${API}ssr-tickets/jv-preview-draft/`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(buildPayload()) });
      const d = await res.json();
      if (!res.ok) throw new Error(d.error || "Could not build the J.V.");
      renderJv(d);
      open("ssr-jv-modal");
    } catch (err) {
      voyagerAlert(err.message || "Could not build the J.V. Is the Django backend running?", { icon: "error" });
    }
  });

  // ---------- Print (saved SSR only) - Company Master's chosen invoice template ----------
  // Tax Invoice (classic) table - the SAME columns as the Booking print (Basic
  // Fare / Other Taxes / SSR / Service Fee / IGST / CGST / SGST / Amount), with
  // the same rules: SSR has no Basic Fare, Other Taxes = customer + supplier SSR
  // Markup (Booking puts its markups there too), Service Fee = customer +
  // supplier SSR Service Fee, GST = customer + supplier GST.
  const SSR_COLUMNS = window.VoyagerInvoice.TICKET_COLUMNS.map((col) => ({
    ...col, key: { other: "fullMarkup", serviceFee: "fullServiceFee", igst: "fullIgst", cgst: "fullCgst", sgst: "fullSgst" }[col.key] || col.key,
  }));
  function buildInvoiceData(co, cust) {
    const custState = (cust.state_name || "").trim();
    const companyState = (co.state || "").trim();
    const intraState = !!custState && !!companyState && custState.toLowerCase() === companyState.toLowerCase();
    const ccy = ($("currency").textContent || "INR").trim();
    const rows = lines.map((l, i) => {
      const t = lineTotals(l);
      const gst = Math.round(t.gst * 100) / 100;
      const cgst = intraState ? Math.round((gst / 2) * 100) / 100 : 0;
      const sgst = intraState ? Math.round((gst - cgst) * 100) / 100 : 0;
      return {
        no: i + 1, serType: "Airline", pax: l.pax_name, basic: 0, sector: l.sector, details: ssrSummary(l), ssr: t.ssr, markup: n(l.markup),
        serviceFee: n(l.service_fee), igst: intraState ? 0 : gst, cgst, sgst, gst, amount: t.total,
        // Payment Invoice's passenger / fare tables
        paxType: (l.pax_type || "").toUpperCase(), productType: "SSR", gdsPnr: $("gds_pnr").textContent.replace("—", ""),
        airline: "", ticketNo: l.ticket_no || "", cls: "", flight: ssrSummary(l), travelDate: "",
        fare: 0, tax: 0, discount: 0,
        // Template 3 (Performa) passenger table: SSR split.
        yq: 0, baggage: n(l.baggage), seat: n(l.seat), meal: n(l.meal), otherSsr: n(l.other_ssr),
        // Tax Invoice (classic) columns + GST summary, same rule as the Booking /
        // Reschedule print: customer + supplier SSR Markup, customer + supplier
        // SSR Service Fee, customer GST + supplier GST (split IGST or CGST / SGST).
        fullMarkup: n(l.markup) + n(l.supp_markup),
        fullServiceFee: n(l.service_fee) + n(l.supp_service_fee),
        // Template 2 (Payment Invoice): Markup = 0 - the customer + supplier SSR
        // Markup print inside Tax instead (like the Booking print), Service Fee
        // = customer + supplier SSR Service Fee.
        t2Markup: 0,
        t2Tax: n(l.markup) + n(l.supp_markup),
        t2ServiceFee: n(l.service_fee) + n(l.supp_service_fee),
        ...(() => {
          const g = gst + Math.round(t.suppGst * 100) / 100;
          const c = intraState ? Math.round((g / 2) * 100) / 100 : 0;
          return { fullIgst: intraState ? 0 : g, fullCgst: c, fullSgst: intraState ? Math.round((g - c) * 100) / 100 : 0 };
        })(),
      };
    });
    const sum = (k) => rows.reduce((s, r) => s + r[k], 0);
    const grandTotal = sum("amount"), taxable = sum("fullServiceFee");
    const igst = sum("fullIgst"), cgst = sum("fullCgst"), sgst = sum("fullSgst"), totalTax = igst + cgst + sgst;
    return {
      docTitle: "TAX INVOICE", docTitleCase: "Tax Invoice",
      // The document's own Invoice Type (Voucher Type name) - Template 3's heading.
      invoiceType: $("invoice_type").value.trim(),
      company: {
        name: co.company_name, address: co.address, state: co.state, pincode: co.pincode, gst_no: co.gst_no,
        pan_number: co.pan_number, cin_number: co.cin_number, email: co.email, phone: co.mobile || co.telephone || "",
        hsn: co.hsn_sac || "998551", logo: co.logo_base64 || "", seal: co.seal_base64 || "",
        terms: co.terms_conditions || "", bank: window.VoyagerInvoice.bankLine(co),
      },
      invoiceNoLabel: "Invoice No", invoiceNo: $("invoice_number").value,
      invoiceDateLabel: "Invoice Date", invoiceDate: ($("invoice_date").value || "").split("-").reverse().join("/"),
      refLabel: "SSR Reference", refValue: $("ssr_reference").value, airlinePnr: $("airline_pnr").textContent.replace("—", ""),
      customer: { name: cust.name || $("customer").textContent, code: cust.code || "", address: cust.address || "", state: custState, gst_no: cust.gst_no || "", pan: "" },
      placeOfSupply: custState,
      infoRows: [["Original Invoice", $("original_invoice").textContent], ["Airline PNR", $("airline_pnr").textContent],
        ["Sector", [...new Set(lines.map((l) => l.sector).filter(Boolean))].join(", ")]],
      columns: SSR_COLUMNS, lines: rows, grandTotal, taxable, gstRate: custGstPct(), intraState,
      igst, cgst, sgst, totalTax, tds: 0, currency: ccy,
      amountWords: window.VoyagerInvoice.amountInWords(grandTotal, ccy), taxWords: window.VoyagerInvoice.amountInWords(totalTax, ccy),
    };
  }

  $("ssr-print-btn").addEventListener("click", async () => {
    if (!savedId || !lines.length) return;
    let co = {}, cust = {};
    try {
      const [coRes, custRes] = await Promise.all([
        fetch(`${API}company-master/?id=${activeCompanyId}&images=all`),
        fetch(`${API}customers/?company_id=${activeCompanyId}`),
      ]);
      co = coRes.ok ? await coRes.json() : {};
      cust = (custRes.ok ? await custRes.json() : []).find((c) => c.name === (source && source.customer)) || {};
    } catch (_) { /* print with whatever loaded */ }
    window.VoyagerInvoice.print(window.VoyagerInvoice.render(co.invoice_template, buildInvoiceData(co, cust)), $("invoice_number").value);
  });

  render();
  if (savedId) await loadSaved(savedId);
})();
