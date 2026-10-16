(async function () {
  const { fillSelect, todayISO, showToast, getEditId, getReturnTo } = window.VoyagerEntry;
  let activeCompanyId, activeCountry, accounts = [], originalVoucherNo = null;
  let allAccountRows = []; // unfiltered /api/accounts/ rows (ledgers + groups) - used to check a line's ledger group
  let lineCount = 0;
  const editId = getEditId();
  // ?view=1 (double-click on the Vouchers list) opens the voucher read-only
  // first; its Edit button unlocks it.
  let viewMode = !!editId && new URLSearchParams(window.location.search).get("view") === "1";
  const numberOnly = (no) => String(no || "").split("-").pop();
  // Opened from a report row (Day Book / Ledger / Receivables / Payables) ->
  // the Back button names that report.
  function backLabel() {
    const rt = new URLSearchParams(window.location.search).get("returnTo") || "";
    return [["report-day-book", "Day Book"], ["report-ledger-book", "Ledger"], ["customers", "Receivables"], ["suppliers", "Payables"]]
      .reduce((found, [page, label]) => found || (rt.startsWith(page) ? label : ""), "") || "Vouchers";
  }
  function applyViewMode() {
    document.querySelectorAll("#voucher-form input, #voucher-form select").forEach((el) => {
      if (el.id !== "voucher_no") el.disabled = viewMode;
    });
    document.querySelectorAll(".remove-line").forEach((b) => { b.style.display = viewMode ? "none" : ""; });
    document.getElementById("add-line-btn").style.display = viewMode ? "none" : "";
    document.getElementById("save-btn").style.display = viewMode ? "none" : "";
    document.getElementById("edit-btn").style.display = viewMode ? "" : "none";
    document.getElementById("cancel-link").textContent = viewMode ? `<- Back to ${backLabel()}` : "Cancel";
    applyNumberMethod();
    // Re-lock each line's other column (By = Debit only, To = Credit only).
    document.querySelectorAll("#lines-body tr").forEach((tr) => { if (tr.querySelector("select.line-account")) updateLineMeta(tr); });
  }
  document.getElementById("edit-btn").addEventListener("click", () => {
    viewMode = false;
    document.getElementById("page-title").textContent = document.getElementById("page-title").textContent.replace("View Voucher", "Edit Voucher");
    applyViewMode();
  });
  const ticketId = new URLSearchParams(window.location.search).get("ticket_id");
  const returnTo = getReturnTo("vouchers.html");
  document.getElementById("cancel-link").href = returnTo;

  // ============================================================
  // View mode — ?ticket_id=X shows the REAL posted voucher for that
  // ticket (read-only), using this same form's layout instead of a
  // separate details page.
  // ============================================================
  async function enterTicketVoucherViewMode(id) {
    let jv;
    try {
      const res = await fetch(`http://localhost:8000/api/tickets/${id}/jv-preview/?company_id=${activeCompanyId}`);
      jv = await res.json();
      if (!res.ok) throw new Error(jv.error || "Could not compute this ticket's JV.");
    } catch (err) {
      document.querySelector("main").innerHTML = `<p style="color:var(--color-danger); padding:20px;">${err.message || "Could not load this voucher. Is the Django backend running?"}</p>
        <a href="ticket-entry.html?id=${id}" class="btn-outline-brand">← Back to Ticket</a>`;
      return;
    }

    document.getElementById("page-title").textContent = jv.posted ? `Voucher ${jv.voucher_no} — from Ticket` : "JV Preview — from Ticket";
    document.querySelector("main p.text-muted-custom").textContent =
      "Computed live from this ticket's fare lines (Python logic, not a stored snapshot). Read-only.";

    document.getElementById("voucher_no").value = jv.voucher_no || "";  // ticket JV - shown as posted
    document.getElementById("voucher_type").innerHTML = `<option>${window.VoyagerUtil.titleCaseLabel(jv.voucher_type)}</option>`;
    document.getElementById("voucher_date").value = jv.voucher_date;
    document.getElementById("narration").value = jv.narration || "";

    document.getElementById("lines-body").innerHTML = jv.accounts.map((a) => `
      <tr>
        <td class="vx-dc">${a.debit ? "By" : "To"}</td>
        <td><input class="form-control-custom line-account" value="${a.ledger_name || "—"}" disabled /></td>
        <td class="vx-amt"><input class="form-control-custom" type="text" value="${a.debit ? Number(a.debit).toFixed(2) : ""}" disabled /></td>
        <td class="vx-amt"><input class="form-control-custom" type="text" value="${a.credit ? Number(a.credit).toFixed(2) : ""}" disabled /></td>
        <td></td>
      </tr>`).join("");

    document.getElementById("total-debit").textContent = jv.total_debit.toFixed(2);
    document.getElementById("total-credit").textContent = jv.total_credit.toFixed(2);
    const indicator = document.getElementById("balance-indicator");
    if (jv.posted) {
      indicator.textContent = `Posted ${jv.voucher_no} ✓`;
      indicator.style.background = "var(--color-success-bg)"; indicator.style.color = "var(--color-success)";
    } else {
      indicator.textContent = jv.total_debit === jv.total_credit ? "Not yet posted" : "Unbalanced";
      indicator.style.background = "var(--color-warning-bg, #FEF3C7)"; indicator.style.color = "var(--color-warning, #92400E)";
    }

    document.querySelectorAll("#voucher-form input, #voucher-form select").forEach((el) => (el.disabled = true));
    document.getElementById("add-line-btn").style.display = "none";
    document.getElementById("save-btn").style.display = "none";
    document.getElementById("cancel-link").textContent = "← Back to Ticket";
    document.getElementById("cancel-link").href = `ticket-entry.html?id=${id}`;
  }

  // Case/punctuation-insensitive group-name match, same idea as the
  // backend's _normalize_group_name() (Cash-in-Hand / Cash-in-hand /
  // Cash in Hand all match).
  const CASH_BANK_GROUP_NAMES = ["cashinhand", "bankaccounts"];
  function normalizeGroupName(name) {
    return (name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  }
  function isCashOrBankLedger(accountName) {
    const ledger = allAccountRows.find((r) => !r.is_group && r.name === accountName);
    if (!ledger) return false;
    const group = allAccountRows.find((r) => r.is_group && r.id === ledger.parent_id);
    return !!group && CASH_BANK_GROUP_NAMES.includes(normalizeGroupName(group.name));
  }

  function accountOptionsHtml() {
    return `<option value="">Select account…</option>` + accounts.map((a) => `<option value="${a.name}">${a.name}</option>`).join("");
  }

  function addLine(prefill) {
    lineCount += 1;
    const id = `line-${lineCount}`;
    const tr = document.createElement("tr");
    tr.id = id;
    tr.innerHTML = `
      <td class="vx-dc" tabindex="0"></td>
      <td><select class="form-control-custom line-account">${accountOptionsHtml()}</select><div class="vx-curbal"></div><div class="line-bills"></div></td>
      <td class="vx-amt"><input class="form-control-custom line-debit dom-amount" type="text" inputmode="decimal" value="${prefill && prefill.debit ? Number(prefill.debit).toFixed(2) : ""}" /></td>
      <td class="vx-amt"><input class="form-control-custom line-credit dom-amount" type="text" inputmode="decimal" value="${prefill && prefill.credit ? Number(prefill.credit).toFixed(2) : ""}" /></td>
      <td><button type="button" class="remove-line vx-btn-remove" title="Remove line">&times;</button></td>`;
    document.getElementById("lines-body").appendChild(tr);
    const debitInput = tr.querySelector(".line-debit");
    const creditInput = tr.querySelector(".line-credit");
    // A single line is either a Debit or a Credit, never both - typing
    // into one clears whatever's in the other.
    debitInput.addEventListener("input", () => {
      tr._autoBalance = false; // typed by hand - never auto-adjusted again
      if (debitInput.value && parseFloat(debitInput.value) > 0) creditInput.value = "";
      recalcTotals();
    });
    creditInput.addEventListener("input", () => {
      tr._autoBalance = false;
      if (creditInput.value && parseFloat(creditInput.value) > 0) debitInput.value = "";
      recalcTotals();
    });
    // Leaving an amount box balances the voucher automatically (see autoBalance).
    [debitInput, creditInput].forEach((inp) => inp.addEventListener("change", autoBalance));
    tr.querySelector(".remove-line").addEventListener("click", () => { tr.remove(); recalcTotals(); autoBalance(); });
    if (prefill && prefill.account) tr.querySelector(".line-account").value = prefill.account;

    // Bill-by-Bill: a Sundry Debtor / Creditor ledger with Maintain Balance
    // Bill-by-Bill = Yes asks Against Invoice / On Account / New Invoice once
    // the line has an amount (Enter, or leaving the box).
    if (prefill && prefill.bill_allocations && prefill.bill_allocations.length) {
      tr._alloc = prefill.bill_allocations;
      tr._allocSig = lineSignature(tr);
      tr._allocKey = tr._allocSig.split("|").slice(0, 2).join("|");
    }
    renderLineBills(tr);
    [debitInput, creditInput].forEach((inp) => {
      inp.addEventListener("keydown", (e) => {
        if (e.key !== "Enter") return;
        e.preventDefault();
        maybeAllocate(tr);
      });
      inp.addEventListener("change", () => maybeAllocate(tr));
    });
    tr.querySelector(".line-account").addEventListener("change", () => { updateLineMeta(tr); fillDefaultBank(); maybeAllocate(tr); });
    // Switching a line's side - click By / To, or press B (By) / T (To) like
    // Tally while on the By/To label or in the Debit / Credit box. An amount
    // already entered moves across to the other column with it.
    function setSide(next) {
      if (viewMode || lineSide(tr) === next) {
        if (!viewMode) (next === "By" ? debitInput : creditInput).focus();
        return;
      }
      const amount = debitInput.value || creditInput.value;
      tr._sideManual = next;
      tr._autoBalance = false;
      debitInput.value = next === "By" ? amount : "";
      creditInput.value = next === "To" ? amount : "";
      recalcTotals();
      if (amount) autoBalance();
      (next === "By" ? debitInput : creditInput).focus();
    }
    tr.querySelector(".vx-dc").addEventListener("click", () => setSide(lineSide(tr) === "By" ? "To" : "By"));
    tr.addEventListener("keydown", (e) => {
      if (e.ctrlKey || e.altKey || e.metaKey) return;
      const key = e.key.toLowerCase();
      if (key !== "b" && key !== "t") return;
      // Not inside the account dropdown - letters there search ledger names.
      if (!e.target.matches(".vx-dc, .line-debit, .line-credit")) return;
      e.preventDefault();
      setSide(key === "b" ? "By" : "To");
    });
    updateLineMeta(tr);
    tr.querySelector(".line-bills").addEventListener("click", () => { if (!viewMode) maybeAllocate(tr, true); });
  }

  // ============================================================
  // Bill-wise allocation (Sundry Debtors / Sundry Creditors with Maintain
  // Balance Bill-by-Bill = Yes) - manual vouchers only; ticket JVs never ask.
  //   Against Invoice -> pick from the party's un-adjusted invoices
  //   On Account      -> no invoice; shows as Unadjusted Credits / Debits
  //   New Invoice     -> a new bill reference of its own
  // Stored on the line as bill_allocations [{type, ref, amount}]; any amount
  // not allocated to an invoice counts as On Account.
  // ============================================================
  const VOUCHER_PREFIX = { JOURNAL: "JV", PAYMENT: "PV", RECEIPT: "RV", CONTRA: "CV", DEBIT_NOTE: "DN", CREDIT_NOTE: "CN" };
  const partyBillsCache = {};
  const money = (v) => (Number(v) || 0).toFixed(2);
  const escHtml = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

  function lineState(tr) {
    const ledger = accounts.find((a) => a.name === tr.querySelector(".line-account").value);
    const debit = parseFloat(tr.querySelector(".line-debit").value) || 0;
    const credit = parseFloat(tr.querySelector(".line-credit").value) || 0;
    return { ledger, isDebit: debit > 0, amount: Math.round((debit || credit) * 100) / 100 };
  }
  function lineSignature(tr) {
    const s = lineState(tr);
    return s.ledger && s.amount > 0 ? `${s.ledger.id}|${s.isDebit ? "Dr" : "Cr"}|${s.amount}` : "";
  }

  function renderLineBills(tr) {
    const el = tr.querySelector(".line-bills");
    const allocs = tr._alloc || [];
    if (!allocs.length) { el.innerHTML = ""; el.style.display = "none"; return; }
    const { amount, isDebit } = lineState(tr);
    const allocated = allocs.reduce((s, a) => s + (a.type === "On Account" ? 0 : a.amount), 0);
    const parts = allocs.filter((a) => a.type !== "On Account").map((a) =>
      `${a.type === "New Invoice" ? "New Ref" : "Agst Ref"} ${escHtml(a.ref)}: ${money(a.amount)}`);
    const onAccount = Math.round((amount - allocated) * 100) / 100;
    if (onAccount > 0.005) parts.push(`On Account: ${money(onAccount)} (Unadjusted ${isDebit ? "Debit" : "Credit"})`);
    el.innerHTML = parts.join(" &nbsp;|&nbsp; ");
    el.title = viewMode ? "" : "Click to change the bill allocation";
    el.style.display = "";
    el.style.cursor = viewMode ? "default" : "pointer";
  }

  async function fetchPartyBills(ledgerId) {
    if (partyBillsCache[ledgerId]) return partyBillsCache[ledgerId];
    const qs = new URLSearchParams({ company_id: activeCompanyId, ledger_id: ledgerId });
    if (editId) qs.set("exclude_voucher_id", editId);
    const res = await fetch(`http://localhost:8000/api/party-bills/?${qs}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Could not load this party's invoices.");
    partyBillsCache[ledgerId] = data;
    return data;
  }

  async function maybeAllocate(tr, force) {
    if (viewMode || ticketId || tr._allocBusy) return;
    const sig = lineSignature(tr);
    if (!sig) { if (tr._alloc) { tr._alloc = null; renderLineBills(tr); } tr._allocSig = ""; return; }
    if (!force && sig === tr._allocSig) return;
    const { ledger, amount, isDebit } = lineState(tr);
    tr._allocBusy = true;
    try {
      let data;
      try { data = await fetchPartyBills(ledger.id); } catch (err) {
        voyagerAlert(err.message || "Could not load this party's invoices.", { icon: "error" });
        return;
      }
      tr._allocSig = sig;
      if (!data.bill_wise) { tr._alloc = null; renderLineBills(tr); return; }
      // Bill-wise details are asked only on the settling side, any voucher type:
      //   Sundry Debtors   (receivables) - only when the line is a CREDIT
      //   Sundry Creditors (payables)    - only when the line is a DEBIT
      // The other side (e.g. debiting a debtor) posts with no bill popup.
      const asksBills = data.side === "payables" ? isDebit : !isDebit;
      if (!asksBills) { tr._alloc = null; renderLineBills(tr); return; }
      // Invoices on the other side of this line: a Credit settles Debit bills
      // (customer receipts), a Debit settles Credit bills (supplier payments).
      // Less whatever the voucher's other lines already allocated to them.
      const usedElsewhere = {};
      document.querySelectorAll("#lines-body tr").forEach((other) => {
        if (other === tr || !other._alloc) return;
        const o = lineState(other);
        if (!o.ledger || o.ledger.id !== ledger.id) return;
        other._alloc.filter((a) => a.type === "Against Invoice").forEach((a) => { usedElsewhere[a.ref] = (usedElsewhere[a.ref] || 0) + a.amount; });
      });
      const bills = data.bills
        .filter((b) => (isDebit ? b.balance < 0 : b.balance > 0))
        .map((b) => ({ ...b, pending: Math.round((Math.abs(b.balance) - (usedElsewhere[b.invoice_number] || 0)) * 100) / 100 }))
        .filter((b) => b.pending > 0.005);
      const key = `${ledger.id}|${isDebit ? "Dr" : "Cr"}`;
      // An allocation made for another ledger / side doesn't carry over.
      const current = tr._allocKey === key ? tr._alloc || [] : [];
      const result = await openBillAllocation({ ledgerName: ledger.name, amount, isDebit, bills, current, report: data.side === "payables" ? "Payables" : "Receivables" });
      if (result) {
        tr._alloc = result.length ? result : null;
      } else {
        // Cancelled: keep the earlier allocation only if it still fits this line.
        const against = current.reduce((s, a) => s + (a.type === "On Account" ? 0 : a.amount), 0);
        tr._alloc = current.length && against <= amount + 0.005 ? current : null;
      }
      tr._allocKey = key;
      renderLineBills(tr);
    } finally {
      tr._allocBusy = false;
    }
  }

  // What a line saves: its invoice allocations, plus the rest as On Account
  // (recomputed from the current amount, so an edited amount never leaves a
  // stale On Account figure). Only for the ledger / side it was made for.
  function billAllocationsFor(tr) {
    if (!tr._alloc || !tr._alloc.length) return null;
    const sig = lineSignature(tr);
    if (!sig || sig.split("|").slice(0, 2).join("|") !== tr._allocKey) return null;
    const { amount } = lineState(tr);
    const out = tr._alloc.filter((a) => a.type !== "On Account").map((a) => ({ type: a.type, ref: a.ref, amount: a.amount }));
    const rest = Math.round((amount - out.reduce((s, a) => s + a.amount, 0)) * 100) / 100;
    if (rest > 0.005) out.push({ type: "On Account", ref: "", amount: rest });
    return out;
  }

  function ensureBillAllocModal() {
    let modal = document.getElementById("bill-alloc-modal");
    if (modal) return modal;
    if (!document.getElementById("bill-alloc-style")) {
      const st = document.createElement("style");
      st.id = "bill-alloc-style";
      st.textContent = `
        #lines-body td { vertical-align: top; }
        .line-bills { font-size: 11.5px; color: var(--color-primary, #3B6DB5); margin-top: 3px; font-weight: 600; }
        #bill-alloc-modal { z-index: 1500; }
        #bill-alloc-modal .dom-modal-window { width: 760px; background: #FFFFFF; }
        .ba-body { padding: 12px 14px; font-size: 12.5px; color: #1E293B; }
        .ba-head { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 10px; font-size: 12.5px; }
        .ba-types { display: flex; gap: 8px; margin-bottom: 12px; }
        .ba-type { flex: 1; padding: 8px 10px; border: 1px solid #CBD5E1; border-radius: 4px; background: #F8FAFC; cursor: pointer;
          font-size: 12.5px; font-weight: 600; color: #334155; text-align: center; }
        .ba-type.active { background: #3B6DB5; border-color: #3B6DB5; color: #FFFFFF; }
        .ba-panel { min-height: 120px; }
        .ba-table-wrap { max-height: 260px; overflow-y: auto; border: 1px solid #E2E8F0; border-radius: 4px; }
        .ba-table { width: 100%; border-collapse: collapse; }
        .ba-table th { position: sticky; top: 0; background: #F1F5F9; font-size: 11px; font-weight: 700; color: #64748B; text-align: left; padding: 6px 8px; border-bottom: 1px solid #E2E8F0; }
        .ba-table td { padding: 5px 8px; border-bottom: 1px solid #F1F5F9; font-size: 12px; white-space: nowrap; }
        .ba-table .amt { text-align: right; font-variant-numeric: tabular-nums; }
        .ba-table tr.ba-row { cursor: pointer; }
        .ba-table tr.ba-row:hover td { background: #EFF6FF; }
        #bill-alloc-modal .ba-table input[type=checkbox] { width: 14px !important; height: 14px !important; padding: 0 !important; margin: 0; cursor: pointer; }
        #bill-alloc-modal .ba-table input.ba-amt { width: 110px; text-align: right; }
        .ba-note { padding: 18px 6px; color: #475569; line-height: 1.6; }
        .ba-sum { display: flex; justify-content: flex-end; gap: 18px; margin-top: 10px; font-size: 12.5px; }
        .ba-sum strong { font-variant-numeric: tabular-nums; }
        .ba-field { display: flex; align-items: center; gap: 10px; padding: 14px 6px; }
        .ba-field label { width: 120px; font-weight: 600; color: #475569; }
        #bill-alloc-modal .ba-field input { height: 28px !important; font-size: 12.5px !important; width: 240px; }
      `;
      document.head.appendChild(st);
    }
    modal = document.createElement("div");
    modal.className = "dom-modal-backdrop";
    modal.id = "bill-alloc-modal";
    modal.innerHTML = `
      <div class="dom-modal-window">
        <div class="dom-modal-titlebar"><div>Bill-wise Details</div><button type="button" class="dom-titlebar-btn btn-close" data-ba="cancel">&times;</button></div>
        <div class="ba-body">
          <div class="ba-head"><div>Ledger: <strong id="ba-ledger"></strong></div><div>Amount: <strong id="ba-amount"></strong></div></div>
          <div class="ba-types">
            <button type="button" class="ba-type" data-type="Against Invoice">Against Invoice</button>
            <button type="button" class="ba-type" data-type="On Account">On Account</button>
            <button type="button" class="ba-type" data-type="New Invoice">New Invoice</button>
          </div>
          <div class="ba-panel" id="ba-panel"></div>
        </div>
        <div class="voyager-alert-actions">
          <button type="button" class="dom-nav-btn" data-ba="cancel">Cancel</button>
          <button type="button" class="dom-nav-btn btn-primary" data-ba="ok">OK</button>
        </div>
      </div>`;
    document.body.appendChild(modal);
    return modal;
  }

  // Resolves to the new allocation list, or null when cancelled.
  function openBillAllocation({ ledgerName, amount, isDebit, bills, current, report }) {
    const modal = ensureBillAllocModal();
    const side = isDebit ? "Debit" : "Credit";
    modal.querySelector("#ba-ledger").textContent = ledgerName;
    modal.querySelector("#ba-amount").textContent = `${money(amount)} ${isDebit ? "Dr" : "Cr"}`;
    const panel = modal.querySelector("#ba-panel");
    const currentAgainst = {};
    current.filter((a) => a.type === "Against Invoice").forEach((a) => { currentAgainst[a.ref] = a.amount; });
    const currentNew = current.find((a) => a.type === "New Invoice");
    let type = currentNew ? "New Invoice" : Object.keys(currentAgainst).length ? "Against Invoice" : current.length ? "On Account" : "Against Invoice";
    const defaultNewRef = () => {
      const t = voucherBaseType();
      return `${VOUCHER_PREFIX[t] || "JV"}-${document.getElementById("voucher_no").value || ""}`;
    };
    // A bill this line already allocated to stays listed, even if it's now
    // fully settled by it.
    const list = bills.map((b) => ({ ...b, pending: Math.round((b.pending + 0) * 100) / 100 }));
    Object.keys(currentAgainst).forEach((ref) => {
      if (!list.some((b) => b.invoice_number === ref)) list.push({ invoice_number: ref, date: null, type: "", pending: currentAgainst[ref] });
    });

    function updateSum() {
      if (type !== "Against Invoice") return;
      let allocated = 0;
      panel.querySelectorAll("tr.ba-row").forEach((r) => { if (r.querySelector("input[type=checkbox]").checked) allocated += parseFloat(r.querySelector(".ba-amt").value) || 0; });
      allocated = Math.round(allocated * 100) / 100;
      panel.querySelector("#ba-allocated").textContent = money(allocated);
      const rest = Math.round((amount - allocated) * 100) / 100;
      panel.querySelector("#ba-rest").textContent = money(Math.max(rest, 0));
      panel.querySelector("#ba-rest").style.color = rest < -0.005 ? "#DC2626" : "";
    }

    function renderPanel() {
      modal.querySelectorAll(".ba-type").forEach((b) => b.classList.toggle("active", b.dataset.type === type));
      if (type === "On Account") {
        panel.innerHTML = `<div class="ba-note">No invoice is adjusted. The full amount <strong>${money(amount)}</strong> is kept On Account
          and shows in the ${report} report as <strong>Unadjusted ${side}s</strong> for this party,
          until it's adjusted against an invoice later.</div>`;
        return;
      }
      if (type === "New Invoice") {
        panel.innerHTML = `
          <div class="ba-field"><label>New Reference</label><input class="form-control-custom" id="ba-new-ref" maxlength="60" value="${escHtml(currentNew ? currentNew.ref : defaultNewRef())}" /></div>
          <div class="ba-field"><label>Amount</label><input class="form-control-custom" value="${money(amount)} ${isDebit ? "Dr" : "Cr"}" disabled /></div>
          <div class="ba-note" style="padding-top:0;">The full amount becomes a new bill under this reference - later vouchers can be adjusted against it.</div>`;
        setTimeout(() => panel.querySelector("#ba-new-ref").focus(), 0);
        return;
      }
      if (!list.length) {
        panel.innerHTML = `<div class="ba-note">This party has no un-adjusted ${isDebit ? "Credit" : "Debit"} invoices to adjust this ${side} against.
          Choose <strong>On Account</strong> or <strong>New Invoice</strong>.</div>`;
        return;
      }
      panel.innerHTML = `
        <div class="ba-table-wrap"><table class="ba-table">
          <thead><tr><th style="width:28px;"></th><th>Invoice No.</th><th>Date</th><th>Type</th><th class="amt">Pending</th><th class="amt">Adjust Amount</th></tr></thead>
          <tbody>${list.map((b, i) => {
            const amt = currentAgainst[b.invoice_number];
            return `<tr class="ba-row" data-i="${i}">
              <td><input type="checkbox" ${amt ? "checked" : ""} /></td>
              <td>${escHtml(b.invoice_number)}</td><td>${b.date ? b.date.split("-").reverse().join("/") : ""}</td><td>${escHtml(b.type)}</td>
              <td class="amt">${money(b.pending)}</td>
              <td class="amt"><input class="form-control-custom ba-amt" inputmode="decimal" value="${amt ? money(amt) : ""}" ${amt ? "" : "disabled"} /></td></tr>`;
          }).join("")}</tbody>
        </table></div>
        <div class="ba-sum"><span>Allocated: <strong id="ba-allocated">0.00</strong></span><span>On Account (Unadjusted ${side}): <strong id="ba-rest">0.00</strong></span></div>`;
      panel.querySelectorAll("tr.ba-row").forEach((r) => {
        const cb = r.querySelector("input[type=checkbox]");
        const amtInput = r.querySelector(".ba-amt");
        const b = list[Number(r.dataset.i)];
        const toggle = (checked) => {
          cb.checked = checked;
          amtInput.disabled = !checked;
          if (checked) {
            // Fill with what's left of the line amount, up to the bill's pending.
            let others = 0;
            panel.querySelectorAll("tr.ba-row").forEach((o) => { if (o !== r && o.querySelector("input[type=checkbox]").checked) others += parseFloat(o.querySelector(".ba-amt").value) || 0; });
            amtInput.value = money(Math.max(0, Math.min(b.pending, amount - others)));
            amtInput.focus(); amtInput.select();
          } else {
            amtInput.value = "";
          }
          updateSum();
        };
        cb.addEventListener("click", (e) => { e.stopPropagation(); toggle(cb.checked); });
        r.addEventListener("click", (e) => { if (e.target === amtInput) return; toggle(!cb.checked); });
        amtInput.addEventListener("input", updateSum);
        amtInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); modal.querySelector('[data-ba="ok"]').click(); } });
      });
      updateSum();
    }

    function collect() {
      if (type === "On Account") return [{ type: "On Account", ref: "", amount }];
      if (type === "New Invoice") {
        const ref = panel.querySelector("#ba-new-ref").value.trim();
        if (!ref) { voyagerAlert("Enter the New Reference for this invoice."); return undefined; }
        if (bills.some((b) => b.invoice_number.toLowerCase() === ref.toLowerCase())) {
          voyagerAlert(`"${ref}" is already an invoice of this party - choose Against Invoice to adjust it, or use another reference.`);
          return undefined;
        }
        return [{ type: "New Invoice", ref, amount }];
      }
      const out = [];
      for (const r of panel.querySelectorAll("tr.ba-row")) {
        if (!r.querySelector("input[type=checkbox]").checked) continue;
        const b = list[Number(r.dataset.i)];
        const amt = Math.round((parseFloat(r.querySelector(".ba-amt").value) || 0) * 100) / 100;
        if (amt <= 0) continue;
        if (amt > b.pending + 0.005) { voyagerAlert(`${b.invoice_number}: the adjust amount ${money(amt)} is more than its pending ${money(b.pending)}.`); return undefined; }
        out.push({ type: "Against Invoice", ref: b.invoice_number, amount: amt });
      }
      const total = out.reduce((s, a) => s + a.amount, 0);
      if (total > amount + 0.005) { voyagerAlert(`The adjusted total ${money(total)} is more than the line amount ${money(amount)}.`); return undefined; }
      if (!out.length) { voyagerAlert("Tick at least one invoice to adjust, or choose On Account."); return undefined; }
      return out;
    }

    renderPanel();
    modal.classList.add("open");
    return new Promise((resolve) => {
      const typeBtns = modal.querySelectorAll(".ba-type");
      const onType = (e) => { type = e.currentTarget.dataset.type; renderPanel(); };
      const finish = (val) => {
        modal.classList.remove("open");
        typeBtns.forEach((b) => b.removeEventListener("click", onType));
        modal.querySelectorAll("[data-ba]").forEach((b) => b.removeEventListener("click", onAction));
        document.removeEventListener("keydown", onKey, true);
        resolve(val);
      };
      const onAction = (e) => {
        if (e.currentTarget.dataset.ba === "cancel") return finish(null);
        const val = collect();
        if (val !== undefined) finish(val);
      };
      const onKey = (e) => {
        if (e.key === "Escape" && modal.classList.contains("open") && !document.querySelector("#voyager-alert-modal.open")) { e.stopPropagation(); finish(null); }
      };
      typeBtns.forEach((b) => b.addEventListener("click", onType));
      modal.querySelectorAll("[data-ba]").forEach((b) => b.addEventListener("click", onAction));
      document.addEventListener("keydown", onKey, true);
      setTimeout(() => (modal.querySelector(".ba-type.active") || typeBtns[0]).focus(), 0);
    });
  }

  // Tally-style auto balance: when the hand-entered Debit and Credit totals
  // differ, the difference goes into the OPPOSITE column of one line - an
  // empty line (the next one), or a new line when none is empty. That line
  // keeps following the difference as other amounts change, until its own
  // amount is typed by hand (then it's left alone). Balanced -> it clears.
  function autoBalance() {
    if (viewMode) return;
    const rows = Array.from(document.querySelectorAll("#lines-body tr"));
    const amt = (tr, cls) => parseFloat(tr.querySelector(cls).value) || 0;
    let debit = 0, credit = 0;
    rows.filter((tr) => !tr._autoBalance).forEach((tr) => { debit += amt(tr, ".line-debit"); credit += amt(tr, ".line-credit"); });
    const diff = Math.round((debit - credit) * 100) / 100;
    let target = rows.find((tr) => tr._autoBalance);
    if (!diff) {
      if (target) { target.querySelector(".line-debit").value = ""; target.querySelector(".line-credit").value = ""; }
      recalcTotals();
      return;
    }
    if (!target) {
      target = rows.find((tr) => !amt(tr, ".line-debit") && !amt(tr, ".line-credit"));
      if (!target) {
        addLine();
        target = document.getElementById("lines-body").lastElementChild;
      }
      target._autoBalance = true;
    }
    const dp = window.VoyagerUtil ? VoyagerUtil.getDecimalPlaces() : 2;
    // More Debit entered -> the balancing line is a Credit, and vice versa.
    target.querySelector(".line-credit").value = diff > 0 ? diff.toFixed(dp) : "";
    target.querySelector(".line-debit").value = diff < 0 ? (-diff).toFixed(dp) : "";
    recalcTotals();
    fillDefaultBank(); // Payment: the balancing "To" line is the Default Bank
  }

  // Tally-style line labels: "By" = a Debit line, "To" = a Credit line. A line
  // with no amount yet shows what it will most likely be - "To" when the
  // voucher is short on Credit, otherwise "By". Under the ledger: its current
  // balance (Chart of Accounts balance, Debit + / Credit -), e.g. "345.46 Dr".
  // Each line has a side, like Tally: "By" = Debit only (Credit box locked),
  // "To" = Credit only (Debit box locked). Side = the column holding the
  // amount; a blank line uses the side picked by clicking its By/To label,
  // else follows the balance ("To" when the voucher is short on Credit).
  function lineSide(tr) {
    if (parseFloat(tr.querySelector(".line-debit").value) || 0) return "By";
    if (parseFloat(tr.querySelector(".line-credit").value) || 0) return "To";
    if (tr._sideManual) return tr._sideManual;
    let d = 0, c = 0;
    const rows = Array.from(document.querySelectorAll("#lines-body tr")).filter((o) => o.querySelector(".line-debit"));
    rows.forEach((o) => {
      if (o === tr) return;
      d += parseFloat(o.querySelector(".line-debit").value) || 0;
      c += parseFloat(o.querySelector(".line-credit").value) || 0;
    });
    if (d > c) return "To";
    if (c > d) return "By";
    // Nothing to balance yet: line 1 starts on the voucher type's usual side
    // (Receipt -> To, the party paying in; everything else -> By), and every
    // later line starts on the opposite side of line 1.
    const firstSide = voucherBaseType() === "RECEIPT" ? "To" : "By";
    if (tr === rows[0]) return firstSide;
    const first = rows[0];
    const lead = first && (first._sideManual
      || ((parseFloat(first.querySelector(".line-debit").value) || 0) ? "By" : null)
      || ((parseFloat(first.querySelector(".line-credit").value) || 0) ? "To" : null)
      || firstSide);
    return lead === "To" ? "By" : "To";
  }
  function updateLineMeta(tr) {
    const tag = lineSide(tr);
    const dc = tr.querySelector(".vx-dc");
    dc.textContent = tag;
    dc.title = viewMode ? "" : "B = By (Debit), T = To (Credit) - or click to switch";
    dc.tabIndex = viewMode ? -1 : 0;
    dc.classList.toggle("vx-dc-click", !viewMode);
    if (!viewMode) {
      tr.querySelector(".line-debit").disabled = tag !== "By";
      tr.querySelector(".line-credit").disabled = tag !== "To";
    }
    const name = tr.querySelector(".line-account").value;
    const ledger = name && accounts.find((a) => a.name === name);
    const curBal = tr.querySelector(".vx-curbal");
    if (!ledger) { curBal.innerHTML = ""; return; }
    const bal = Number(ledger.balance) || 0;
    const dp = window.VoyagerUtil ? VoyagerUtil.getDecimalPlaces() : 2;
    curBal.innerHTML = `Cur Bal: <strong>${Math.abs(bal).toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp })} ${bal < 0 ? "Cr" : "Dr"}</strong>`;
  }

  function recalcTotals() {
    document.querySelectorAll("#lines-body tr").forEach((tr) => { if (tr.querySelector("select.line-account")) updateLineMeta(tr); });
    let debit = 0, credit = 0;
    document.querySelectorAll("#lines-body tr").forEach((tr) => {
      debit += parseFloat(tr.querySelector(".line-debit").value) || 0;
      credit += parseFloat(tr.querySelector(".line-credit").value) || 0;
    });
    document.getElementById("total-debit").textContent = debit.toFixed(2);
    document.getElementById("total-credit").textContent = credit.toFixed(2);
    const balanced = debit > 0 && Math.abs(debit - credit) < 0.005;
    const indicator = document.getElementById("balance-indicator");
    const saveBtn = document.getElementById("save-btn");
    if (balanced) {
      indicator.textContent = "Balanced ✓";
      indicator.style.background = "var(--color-success-bg)"; indicator.style.color = "var(--color-success)";
      saveBtn.disabled = false;
    } else {
      indicator.textContent = "Unbalanced";
      indicator.style.background = "var(--color-danger-bg)"; indicator.style.color = "var(--color-danger)";
      saveBtn.disabled = true;
    }
  }

  const ACCOUNTS_API = "http://localhost:8000/api/accounts/";
  // Payment / Receipt: once line 1 (the party) has its ledger, the next empty
  // line becomes the Default Bank automatically (Ledger Master's Default
  // Bank) - "To <bank>" on a Payment (money goes out of the bank), "By
  // <bank>" on a Receipt (money comes into the bank). Only fills a line with
  // no ledger yet - never replaces a ledger already picked - and does nothing
  // when no Default Bank is set or it's already on the voucher.
  let defaultBankName = null;
  const BANK_SIDE = { PAYMENT: "To", RECEIPT: "By" };
  function fillDefaultBank() {
    const bankSide = BANK_SIDE[voucherBaseType()];
    if (viewMode || !defaultBankName || !bankSide) return;
    const rows = Array.from(document.querySelectorAll("#lines-body tr")).filter((tr) => tr.querySelector("select.line-account"));
    if (!rows.length || !rows[0].querySelector(".line-account").value) return;
    if (rows.some((tr) => tr.querySelector(".line-account").value === defaultBankName)) return;
    const target = rows.slice(1).find((tr) => !tr.querySelector(".line-account").value);
    if (!target) return;
    const sel = target.querySelector(".line-account");
    if (!Array.from(sel.options).some((o) => o.value === defaultBankName)) return;
    sel.value = defaultBankName;
    target._sideManual = bankSide;
    recalcTotals();
  }

  // ---------- Voucher Type master -> this screen's Voucher Type list ----------
  // The 6 standard types (Journal, Contra, Payment, Receipt, Debit Note,
  // Credit Note) are always listed; every ACTIVE type created in Voucher Type
  // master whose "Type of Voucher" is one of those 6 is listed after them
  // (e.g. "Petty Cash Payment" under Payment). Master types under General
  // (Tax Invoice, Sales Air ...) are ticket invoice types - never listed.
  // A master type behaves exactly like its category (numbering, By/To,
  // Cash/Bank rules, Default Bank ...) - see voucherBaseType.
  const CATEGORY_VALUE = { "Journal": "JOURNAL", "Contra": "CONTRA", "Payment": "PAYMENT", "Receipt": "RECEIPT", "Debit Note": "DEBIT_NOTE", "Credit Note": "CREDIT_NOTE" };
  // The selected type's category value (JOURNAL / PAYMENT / ...) - for a
  // master type this is its "Type of Voucher", never the master entry itself.
  function voucherBaseType() {
    const sel = document.getElementById("voucher_type");
    const opt = sel.selectedOptions[0];
    return (opt && opt.dataset.base) || sel.value;
  }
  // The master entry's own name when one is selected, else null.
  function voucherTypeName() {
    const opt = document.getElementById("voucher_type").selectedOptions[0];
    return opt && opt.dataset.base ? opt.textContent : null;
  }
  async function loadVoucherTypeOptions(companyId) {
    const sel = document.getElementById("voucher_type");
    if (ticketId) return; // a ticket's own JV - its type is fixed
    let types = [];
    try {
      const res = await fetch(`http://localhost:8000/api/voucher-type/?company_id=${companyId}`);
      types = res.ok ? await res.json() : [];
    } catch (_) { types = []; }
    const standard = new Set(Object.keys(CATEGORY_VALUE).map((k) => k.toLowerCase()));
    const current = sel.value;
    sel.querySelectorAll("option[data-base]").forEach((o) => o.remove());
    types
      .filter((t) => t.is_active && CATEGORY_VALUE[t.voucher_category] && !standard.has(String(t.name).trim().toLowerCase()))
      .sort((a, b) => a.name.localeCompare(b.name))
      .forEach((t) => {
        const o = document.createElement("option");
        o.value = `VT:${t.id}`;
        o.dataset.base = CATEGORY_VALUE[t.voucher_category];
        o.dataset.method = t.number_method || "Automatic"; // drives the No. box (applyNumberMethod)
        o.textContent = t.name;
        o.title = `${t.name} (${t.voucher_category})`;
        sel.appendChild(o);
      });
    if (Array.from(sel.options).some((o) => o.value === current)) sel.value = current;
  }

  async function populateRefs(companyId) {
    await loadVoucherTypeOptions(companyId);
    try {
      const res = await fetch(`http://localhost:8000/api/ledgers/default-bank/?company_id=${companyId}`);
      defaultBankName = res.ok ? (await res.json()).name || null : null;
    } catch (_) { defaultBankName = null; }
    // Account dropdown = real Chart of Accounts leaf Ledgers (no groups),
    // not the old mock account list.
    try {
      const res = await fetch(`${ACCOUNTS_API}?company_id=${companyId}`);
      const rows = res.ok ? await res.json() : [];
      allAccountRows = rows;
      accounts = rows.filter((r) => !r.is_group).sort((a, b) => a.name.localeCompare(b.name));
    } catch (err) {
      console.error("Could not load ledgers - is the Django backend running?", err);
      allAccountRows = [];
      accounts = [];
    }
    document.querySelectorAll("select.line-account").forEach((sel) => {
      const current = sel.value;
      sel.innerHTML = accountOptionsHtml();
      if (current) sel.value = current;
      updateLineMeta(sel.closest("tr")); // Cur Bal needs the ledger list just loaded
    });
  }

  function prefill(v) {
    document.getElementById("page-title").textContent = `${viewMode ? "View" : "Edit"} Voucher — ${numberOnly(v.voucher_no)}`;
    document.getElementById("save-btn").textContent = "Update Voucher";
    originalVoucherNo = v.voucher_no;
    document.getElementById("voucher_no").value = numberOnly(v.voucher_no);
    // v.voucher_type comes back Title Case ("Payment") from the backend;
    // the <select>'s own options are UPPER_SNAKE ("PAYMENT") - reverse
    // the same VOUCHER_TYPE_LABELS map the submit handler uses.
    const upperSnake = Object.keys(VOUCHER_TYPE_LABELS).find((k) => VOUCHER_TYPE_LABELS[k] === v.voucher_type);
    const typeSel = document.getElementById("voucher_type");
    // Saved against a Voucher Type master entry -> select that entry (same
    // name + category); otherwise the standard type.
    const masterOpt = v.voucher_type_name && Array.from(typeSel.options).find((o) =>
      o.dataset.base && o.textContent === v.voucher_type_name && o.dataset.base === upperSnake);
    if (masterOpt) typeSel.value = masterOpt.value;
    else typeSel.value = upperSnake || v.voucher_type;
    lastVoucherType = voucherBaseType(); // a saved voucher's own type
    applyNumberMethod();
    renderShortcutBar();
    document.getElementById("voucher_date").value = v.voucher_date;
    document.getElementById("narration").value = v.narration || "";
    document.getElementById("lines-body").innerHTML = "";
    lineCount = 0;
    v.lines.forEach((l) => addLine({ account: l.ledger_name, debit: l.debit, credit: l.credit, bill_allocations: l.bill_allocations }));
    recalcTotals();
  }

  if (!editId && !ticketId) document.getElementById("voucher_date").value = todayISO();

  // Voucher No. - automatic, one series per voucher type (JV / PV / RV / CV /
  // DN / CN). A new voucher shows the number it will get; the server assigns
  // it for real on save. An existing voucher keeps its own number.
  // Voucher No. follows the selected master type's Voucher Number Method,
  // same as the ticket screens: Automatic = next number, locked; Automatic &
  // Manual Override = next number, editable; Manual = empty, must be typed.
  // Standard types (no master entry) are Automatic.
  function numberMethod() {
    const opt = document.getElementById("voucher_type").selectedOptions[0];
    return (opt && opt.dataset.method) || "Automatic";
  }
  function applyNumberMethod() {
    const inp = document.getElementById("voucher_no");
    const m = numberMethod();
    const editable = !viewMode && !ticketId && m !== "Automatic";
    inp.readOnly = !editable;
    inp.tabIndex = editable ? 0 : -1;
    inp.classList.toggle("vx-no-edit", editable);
    inp.placeholder = editable && m === "Manual" ? "Enter No." : "";
    inp.title = m === "Manual" ? "Manual - type the voucher number"
      : m === "Automatic & Manual Override" ? "Automatic - you can change it" : "Automatic - numbered per voucher type";
  }
  // No "-" in a typed number (it separates the series prefix from the number).
  document.getElementById("voucher_no").addEventListener("input", (e) => {
    if (e.target.value.includes("-")) e.target.value = e.target.value.replace(/-/g, "");
  });

  async function showNextVoucherNo() {
    applyNumberMethod();
    if (editId || ticketId || !activeCompanyId) return;
    if (numberMethod() === "Manual") { document.getElementById("voucher_no").value = ""; return; }
    const type = VOUCHER_TYPE_LABELS[voucherBaseType()] || "Journal";
    try {
      const name = voucherTypeName(); // a master entry has its own series (starts at 1)
      const res = await fetch(`http://localhost:8000/api/vouchers/next-number/?company_id=${activeCompanyId}&voucher_type=${encodeURIComponent(type)}`
        + (name ? `&voucher_type_name=${encodeURIComponent(name)}` : ""));
      const data = await res.json();
      document.getElementById("voucher_no").value = res.ok ? numberOnly(data.next_number) : "";
    } catch (_) { document.getElementById("voucher_no").value = ""; }
  }
  document.getElementById("voucher_type").addEventListener("change", showNextVoucherNo);
  // Type changed -> blank lines take the new type's usual sides (Receipt's
  // line 1 = To), then the Default Bank line is filled for Payment / Receipt.
  // Receipt <-> Payment are mirror images (Receipt: By Bank / To Party,
  // Payment: By Party / To Bank), so switching between the two flips every
  // entered line to the other side - the lines stay a valid voucher of the
  // new type instead of e.g. a "Payment" with the bank still on the Debit.
  // A flipped line's bill allocation no longer applies (it was for the
  // other side), so it's cleared and asked again when relevant.
  let lastVoucherType = voucherBaseType();
  const hasAmount = (tr) => (parseFloat(tr.querySelector(".line-debit").value) || 0) || (parseFloat(tr.querySelector(".line-credit").value) || 0);
  // Lines with no amount yet take the NEW type's natural sides (Receipt:
  // To, By ... / everything else: By, To ...) - forget any side they had
  // picked up under the old type.
  function resetBlankLineSides() {
    document.querySelectorAll("#lines-body tr").forEach((tr) => {
      if (tr.querySelector(".line-debit") && !hasAmount(tr)) tr._sideManual = null;
    });
  }
  function flipAllLineSides() {
    document.querySelectorAll("#lines-body tr").forEach((tr) => {
      const dr = tr.querySelector(".line-debit"), cr = tr.querySelector(".line-credit");
      if (!dr || !cr || !hasAmount(tr)) return; // blank lines: see resetBlankLineSides
      const debit = dr.value, credit = cr.value;
      const side = lineSide(tr);
      dr.value = credit;
      cr.value = debit;
      tr._sideManual = side === "By" ? "To" : "By";
      if (tr._alloc) { tr._alloc = null; tr._allocSig = ""; renderLineBills(tr); }
      maybeAllocate(tr);
    });
  }
  document.getElementById("voucher_type").addEventListener("change", () => {
    const now = voucherBaseType();
    const mirror = (a, b) => (a === "RECEIPT" && b === "PAYMENT") || (a === "PAYMENT" && b === "RECEIPT");
    if (!viewMode && mirror(lastVoucherType, now)) flipAllLineSides();
    if (!viewMode) resetBlankLineSides();
    lastVoucherType = now;
    recalcTotals();
    fillDefaultBank();
  });
  document.getElementById("add-line-btn").addEventListener("click", () => addLine());

  // Backend Voucher.VOUCHER_TYPE_CHOICES are Title Case ("Journal", "Debit
  // Note", ...); the <select> uses UPPER_SNAKE values, so translate before
  // sending.
  const VOUCHER_TYPE_LABELS = {
    JOURNAL: "Journal", CONTRA: "Contra", PAYMENT: "Payment",
    RECEIPT: "Receipt", DEBIT_NOTE: "Debit Note", CREDIT_NOTE: "Credit Note",
  };

  // ---------- Voucher Type shortcut keys ----------
  // F1 Journal, F2 Contra, F3 Payment, F4 Receipt, F5 Debit Note, F6 Credit
  // Note - same order as the Voucher Type list. Listed as a plain legend at
  // the bottom of the page (keyboard only, no buttons). Only while the type can
  // actually be changed (a new voucher, or an existing one in Edit) - the
  // browser's own F-key action (help, find, refresh ...) is blocked here.
  const SHORTCUT_TYPES = Object.keys(VOUCHER_TYPE_LABELS).map((value, i) => ({ key: `F${i + 1}`, value, label: VOUCHER_TYPE_LABELS[value] }));
  function setVoucherTypeOption(optValue) {
    const sel = document.getElementById("voucher_type");
    if (sel.value === optValue) return;
    sel.value = optValue;
    sel.dispatchEvent(new Event("change"));
  }
  // F-key: the standard type directly - unless Voucher Type master entries
  // exist under it (e.g. "Test Journal" under Journal), then a small popup
  // lists the standard type + those entries to pick from (click, or Up /
  // Down + Enter; Esc closes without changing anything).
  function pickVoucherType(value) {
    const sel = document.getElementById("voucher_type");
    if (!sel || sel.disabled || ticketId) return;
    const standard = Array.from(sel.options).find((o) => o.value === value && !o.dataset.base);
    if (!standard) return;
    const masters = Array.from(sel.options).filter((o) => o.dataset.base === value);
    if (!masters.length) { setVoucherTypeOption(value); return; }
    openVoucherTypePicker(VOUCHER_TYPE_LABELS[value] || standard.textContent, [standard, ...masters]);
  }
  function openVoucherTypePicker(title, options) {
    let modal = document.getElementById("vx-type-picker");
    if (!modal) {
      modal = document.createElement("div");
      modal.className = "dom-modal-backdrop";
      modal.id = "vx-type-picker";
      modal.innerHTML = `
        <div class="dom-modal-window" style="width:340px; max-width:92vw; background:#FFFFFF;">
          <div class="dom-modal-titlebar"><div id="vx-tp-title"></div>
            <button type="button" class="dom-titlebar-btn btn-close" data-tp="close">&times;</button></div>
          <div id="vx-tp-list" role="listbox" style="padding:6px 0; max-height:300px; overflow-y:auto;"></div>
        </div>`;
      document.body.appendChild(modal);
      const st = document.createElement("style");
      st.textContent = `
        #vx-tp-list .vx-tp-item { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:7px 14px;
          font-size:12.5px; font-weight:600; color:var(--color-text-dark); cursor:pointer; }
        #vx-tp-list .vx-tp-item small { font-weight:500; color:var(--color-text-muted); font-size:11px; }
        #vx-tp-list .vx-tp-item.active { background:var(--color-primary); color:#FFFFFF; }
        #vx-tp-list .vx-tp-item.active small { color:#FFFFFF; }`;
      modal.appendChild(st);
      const close = () => modal.classList.remove("open");
      modal.querySelector('[data-tp="close"]').addEventListener("click", close);
      modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
      modal.addEventListener("keydown", (e) => {
        const items = Array.from(modal.querySelectorAll(".vx-tp-item"));
        let i = items.findIndex((x) => x.classList.contains("active"));
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          i = e.key === "ArrowDown" ? (i + 1) % items.length : (i - 1 + items.length) % items.length;
          items.forEach((x, k) => x.classList.toggle("active", k === i));
          items[i].scrollIntoView({ block: "nearest" });
        } else if (e.key === "Enter") {
          e.preventDefault();
          if (items[i]) items[i].click();
        } else if (e.key === "Escape") {
          e.preventDefault();
          close();
        }
      });
      modal._close = close;
    }
    modal.querySelector("#vx-tp-title").textContent = `Choose ${title} Voucher Type`;
    const current = document.getElementById("voucher_type").value;
    const list = modal.querySelector("#vx-tp-list");
    list.innerHTML = options.map((o, k) => `
      <div class="vx-tp-item" role="option" tabindex="-1" data-value="${o.value}">
        <span>${o.textContent}</span><small>${k === 0 ? "Standard" : title}</small>
      </div>`).join("");
    const items = Array.from(list.querySelectorAll(".vx-tp-item"));
    const start = Math.max(0, items.findIndex((x) => x.dataset.value === current));
    items.forEach((x, k) => {
      x.classList.toggle("active", k === start);
      x.addEventListener("mouseenter", () => items.forEach((y) => y.classList.toggle("active", y === x)));
      x.addEventListener("click", () => { modal._close(); setVoucherTypeOption(x.dataset.value); });
    });
    modal.classList.add("open");
    modal.tabIndex = -1;
    setTimeout(() => modal.focus(), 0);
  }
  function renderShortcutBar() {
    const bar = document.getElementById("vx-shortcuts");
    const sel = document.getElementById("voucher_type");
    if (!bar || !sel) return;
    if (ticketId) { bar.innerHTML = ""; return; } // a ticket's own JV - type is fixed
    // Dimmed while the type can't be changed (a saved voucher before Edit).
    bar.classList.toggle("is-off", sel.disabled);
    bar.innerHTML = `<span class="vx-sc-label">Shortcut Keys:</span>` + SHORTCUT_TYPES.map((s) =>
      `<span class="vx-sc"><kbd>${s.key}</kbd>${s.label}</span>`).join("") +
      // Line side keys (on the By/To label or in a Debit / Credit box).
      `<span class="vx-sc"><kbd>B</kbd>By (Debit)</span><span class="vx-sc"><kbd>T</kbd>To (Credit)</span>`;
  }
  // Bound once per document - this page's script re-runs on every SPA visit,
  // so the key handler calls the LATEST visit's picker (it reads this
  // visit's own ticketId and looks the live elements up by id).
  window.__pickVoucherType = pickVoucherType;
  if (!window.__voucherTypeShortcutsBound) {
    window.__voucherTypeShortcutsBound = true;
    document.addEventListener("keydown", (e) => {
      const m = /^F([1-9])$/.exec(e.key);
      if (!m || e.ctrlKey || e.altKey || e.metaKey || !document.getElementById("vx-shortcuts")) return;
      const s = SHORTCUT_TYPES[Number(m[1]) - 1];
      if (!s) return;
      e.preventDefault();
      if (document.querySelector(".dom-modal-backdrop.open, #voyager-alert-modal.open")) return; // a popup is open
      window.__pickVoucherType(s.value);
    });
  }
  // Re-drawn whenever view/edit mode flips (disabled state) too.
  new MutationObserver(renderShortcutBar).observe(document.getElementById("voucher_type"), { attributes: true, attributeFilter: ["disabled"] });
  renderShortcutBar();

  document.getElementById("voucher-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const lines = Array.from(document.querySelectorAll("#lines-body tr")).map((tr) => ({
      account_name: tr.querySelector(".line-account").value,
      debit: parseFloat(tr.querySelector(".line-debit").value) || 0,
      credit: parseFloat(tr.querySelector(".line-credit").value) || 0,
      bill_allocations: billAllocationsFor(tr),
    })).filter((l) => l.account_name && (l.debit || l.credit));

    const type = voucherBaseType();
    const typedNo = document.getElementById("voucher_no").value.trim();
    if (numberMethod() === "Manual" && !typedNo) {
      voyagerAlert("Voucher No. is required - this voucher type is numbered manually.");
      return;
    }

    // Payment vouchers must pay OUT of Cash / Bank - at least one CREDIT
    // ("To") line on a Cash-in-Hand or Bank Accounts ledger. Hard block, no
    // override (checked on the server too). The side matters: a bank only on
    // the Debit side - e.g. lines kept from a Receipt after switching the
    // type to Payment - is not a payment out of the bank.
    if (type === "PAYMENT" && !lines.some((l) => l.credit > 0 && isCashOrBankLedger(l.account_name))) {
      voyagerAlert("A Payment voucher must have at least one Credit line on a ledger under Bank Accounts or Cash-in-Hand.");
      return;
    }

    // Receipt vouchers: any number of lines, but the money must be received
    // into Cash / Bank - at least one DEBIT line on a Cash-in-Hand or Bank
    // Accounts ledger, or the voucher can't be saved (checked on the server too).
    if (type === "RECEIPT" && !lines.some((l) => l.debit > 0 && isCashOrBankLedger(l.account_name))) {
      voyagerAlert("A Receipt voucher must have at least one Debit line on a ledger under Bank Accounts or Cash-in-Hand.");
      return;
    }

    // Payment vouchers should always have at least one Credit-side line
    // (the account being paid FROM) - warn, but let the user proceed
    // anyway if they click OK.
    if (type === "PAYMENT" && !lines.some((l) => l.credit > 0)) {
      const proceed = await voyagerConfirm(
        "This Payment voucher has no value on the Credit side. Save anyway?",
        { title: "Confirm Save", confirmLabel: "OK", icon: "warning" }
      );
      if (!proceed) return;
    }

    // The backend identifies each line's ledger by id, not by name.
    const resolvedLines = [];
    for (const l of lines) {
      const ledger = accounts.find((a) => a.name === l.account_name);
      if (!ledger) {
        voyagerAlert(`Could not resolve ledger "${l.account_name}" - please reselect it.`);
        return;
      }
      const line = { ledger_id: ledger.id, debit: l.debit, credit: l.credit };
      if (l.bill_allocations) line.bill_allocations = l.bill_allocations;
      resolvedLines.push(line);
    }

    const payload = {
      company_id: activeCompanyId,
      voucher_type: VOUCHER_TYPE_LABELS[type] || type,
      voucher_type_name: voucherTypeName(),
      // Manual / Override types: the number typed (Automatic ignores it).
      voucher_no_manual: numberMethod() !== "Automatic" ? typedNo : null,
      voucher_date: document.getElementById("voucher_date").value,
      narration: document.getElementById("narration").value,
      lines: resolvedLines,
    };

    // Always posts to the real Django backend - never through the
    // mock/demo-mode store - since a voucher is a real ledger posting,
    // same as how the grid (page-vouchers.js) always reads the real
    // /api/vouchers/ endpoint regardless of Demo Mode. Editing an
    // existing voucher must PUT it through the update endpoint, not
    // create/ again - that would just post a second, duplicate voucher.
    const saveBtn = document.getElementById("save-btn");
    saveBtn.disabled = true;
    const url = editId
      ? `http://localhost:8000/api/vouchers/${editId}/update/`
      : "http://localhost:8000/api/vouchers/create/";
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not post this voucher.");
      showToast(editId ? "Voucher updated." : "Voucher posted.", returnTo);
    } catch (err) {
      voyagerAlert(err.message || "Could not post this voucher. Is the Django backend running?", { icon: "error" });
      saveBtn.disabled = false;
    }
  });

  let active = null;
  try {
    active = await VoyagerShell.init({
      activeKey: ticketId ? "tickets" : "vouchers",
      onCompanyChange: async (id, country) => { activeCompanyId = Number(id); activeCountry = country; await populateRefs(activeCompanyId); await showNextVoucherNo(); },
    });
  } catch (err) {
    console.error("Shell init failed", err);
  }
  if (active) {
    activeCompanyId = Number(active.id); activeCountry = active.country;
    if (ticketId) {
      await enterTicketVoucherViewMode(ticketId);
    } else {
      await populateRefs(activeCompanyId);
      if (editId) {
        // Real backend fetch - never mock-routed, since this is a real
        // ledger posting that only exists in the Voucher table.
        try {
          const res = await fetch(`http://localhost:8000/api/vouchers/${editId}/?company_id=${activeCompanyId}`);
          const v = await res.json();
          if (!res.ok) throw new Error(v.error || "Could not load this voucher.");
          prefill(v);
          applyViewMode();
        } catch (err) {
          voyagerAlert(err.message || "Could not load this voucher. Is the Django backend running?");
        }
      } else {
        addLine(); addLine();
        recalcTotals();
        await showNextVoucherNo();
      }
    }
  } else {
    voyagerAlert("Could not load the active company. Check your connection and reload the page.", { icon: "error" });
  }
})();