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
        <td><input class="form-control-custom" value="${a.ledger_name || "—"}" disabled /></td>
        <td><input class="form-control-custom" type="text" value="${a.debit ? Number(a.debit).toFixed(2) : ""}" disabled /></td>
        <td><input class="form-control-custom" type="text" value="${a.credit ? Number(a.credit).toFixed(2) : ""}" disabled /></td>
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
      <td><select class="form-control-custom line-account">${accountOptionsHtml()}</select><div class="line-bills"></div></td>
      <td><input class="form-control-custom line-debit dom-amount" type="text" inputmode="decimal" value="${prefill && prefill.debit ? Number(prefill.debit).toFixed(2) : ""}" /></td>
      <td><input class="form-control-custom line-credit dom-amount" type="text" inputmode="decimal" value="${prefill && prefill.credit ? Number(prefill.credit).toFixed(2) : ""}" /></td>
      <td><button type="button" class="btn-outline-brand remove-line" style="padding:0.4rem 0.7rem; font-size:0.78rem;">✕</button></td>`;
    document.getElementById("lines-body").appendChild(tr);
    const debitInput = tr.querySelector(".line-debit");
    const creditInput = tr.querySelector(".line-credit");
    // A single line is either a Debit or a Credit, never both - typing
    // into one clears whatever's in the other.
    debitInput.addEventListener("input", () => {
      if (debitInput.value && parseFloat(debitInput.value) > 0) creditInput.value = "";
      recalcTotals();
    });
    creditInput.addEventListener("input", () => {
      if (creditInput.value && parseFloat(creditInput.value) > 0) debitInput.value = "";
      recalcTotals();
    });
    tr.querySelector(".remove-line").addEventListener("click", () => { tr.remove(); recalcTotals(); });
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
    tr.querySelector(".line-account").addEventListener("change", () => maybeAllocate(tr));
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
      const t = document.getElementById("voucher_type").value;
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

  function recalcTotals() {
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
  async function populateRefs(companyId) {
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
    document.querySelectorAll(".line-account").forEach((sel) => {
      const current = sel.value;
      sel.innerHTML = accountOptionsHtml();
      if (current) sel.value = current;
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
    document.getElementById("voucher_type").value = upperSnake || v.voucher_type;
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
  async function showNextVoucherNo() {
    if (editId || ticketId || !activeCompanyId) return;
    const type = VOUCHER_TYPE_LABELS[document.getElementById("voucher_type").value] || "Journal";
    try {
      const res = await fetch(`http://localhost:8000/api/vouchers/next-number/?company_id=${activeCompanyId}&voucher_type=${encodeURIComponent(type)}`);
      const data = await res.json();
      document.getElementById("voucher_no").value = res.ok ? numberOnly(data.next_number) : "";
    } catch (_) { document.getElementById("voucher_no").value = ""; }
  }
  document.getElementById("voucher_type").addEventListener("change", showNextVoucherNo);
  document.getElementById("add-line-btn").addEventListener("click", () => addLine());

  // Backend Voucher.VOUCHER_TYPE_CHOICES are Title Case ("Journal", "Debit
  // Note", ...); the <select> uses UPPER_SNAKE values, so translate before
  // sending.
  const VOUCHER_TYPE_LABELS = {
    JOURNAL: "Journal", CONTRA: "Contra", PAYMENT: "Payment",
    RECEIPT: "Receipt", DEBIT_NOTE: "Debit Note", CREDIT_NOTE: "Credit Note",
  };

  document.getElementById("voucher-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const lines = Array.from(document.querySelectorAll("#lines-body tr")).map((tr) => ({
      account_name: tr.querySelector(".line-account").value,
      debit: parseFloat(tr.querySelector(".line-debit").value) || 0,
      credit: parseFloat(tr.querySelector(".line-credit").value) || 0,
      bill_allocations: billAllocationsFor(tr),
    })).filter((l) => l.account_name && (l.debit || l.credit));

    const type = document.getElementById("voucher_type").value;

    // Payment vouchers must settle out of an actual Cash-in-Hand or Bank
    // Accounts ledger - hard block, no override, unlike the Credit-side
    // warning below.
    if (type === "PAYMENT" && !lines.some((l) => isCashOrBankLedger(l.account_name))) {
      voyagerAlert("A Payment voucher must include at least one ledger under Cash-in-Hand or Bank Accounts.");
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