(async function () {
  const API_BASE = window.API_BASE || "/api";
  const { fillSelect, todayISO, showToast, getEditId, getReturnTo } = window.VoyagerEntry;
  let activeCompanyId, activeCountry, accounts = [], originalVoucherNo = null;
  let allAccountRows = []; // unfiltered /api/accounts/ rows (ledgers + groups) - used to check a line's ledger group
  let lineCount = 0;
  const editId = getEditId();
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
      const res = await fetch(`${API_BASE}/tickets/${id}/jv-preview/?company_id=${activeCompanyId}`);
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

    document.getElementById("branch").innerHTML = `<option>${jv.branch_name || "—"}</option>`;
    document.getElementById("voucher_type").innerHTML = `<option>${window.VoyagerUtil.titleCaseLabel(jv.voucher_type)}</option>`;
    document.getElementById("voucher_date").value = jv.voucher_date;
    document.getElementById("narration").value = jv.narration || "";

    document.getElementById("lines-body").innerHTML = jv.accounts.map((a) => `
      <tr>
        <td><input class="form-control-custom" value="${a.ledger_name || "—"}" disabled /></td>
        <td><input class="form-control-custom" type="number" value="${a.debit || ""}" disabled /></td>
        <td><input class="form-control-custom" type="number" value="${a.credit || ""}" disabled /></td>
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
    return `<option value="">Select account…</option>` + accounts.map((a) => `<option value="${a.name}">${a.code} — ${a.name}</option>`).join("");
  }

  function addLine(prefill) {
    lineCount += 1;
    const id = `line-${lineCount}`;
    const tr = document.createElement("tr");
    tr.id = id;
    tr.innerHTML = `
      <td><select class="form-control-custom line-account">${accountOptionsHtml()}</select></td>
      <td><input class="form-control-custom line-debit" type="number" min="0" step="0.01" value="${prefill && prefill.debit ? prefill.debit : ""}" /></td>
      <td><input class="form-control-custom line-credit" type="number" min="0" step="0.01" value="${prefill && prefill.credit ? prefill.credit : ""}" /></td>
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

  const ACCOUNTS_API = `${API_BASE}/accounts/`;
  async function populateRefs(companyId) {
    const ref = window.VoyagerMock.getReferenceData(companyId);
    fillSelect(document.getElementById("branch"), ref.branches, (b) => b.name, (b) => b.name);
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
    document.getElementById("page-title").textContent = `Edit Voucher — ${v.voucher_no}`;
    document.getElementById("save-btn").textContent = "Update Voucher";
    originalVoucherNo = v.voucher_no;
    document.getElementById("branch").value = v.branch_name;
    // v.voucher_type comes back Title Case ("Payment") from the backend;
    // the <select>'s own options are UPPER_SNAKE ("PAYMENT") - reverse
    // the same VOUCHER_TYPE_LABELS map the submit handler uses.
    const upperSnake = Object.keys(VOUCHER_TYPE_LABELS).find((k) => VOUCHER_TYPE_LABELS[k] === v.voucher_type);
    document.getElementById("voucher_type").value = upperSnake || v.voucher_type;
    document.getElementById("voucher_date").value = v.voucher_date;
    document.getElementById("narration").value = v.narration || "";
    document.getElementById("lines-body").innerHTML = "";
    lineCount = 0;
    v.lines.forEach((l) => addLine({ account: l.ledger_name, debit: l.debit, credit: l.credit }));
    recalcTotals();
  }

  if (!editId && !ticketId) document.getElementById("voucher_date").value = todayISO();
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
    })).filter((l) => l.account_name && (l.debit || l.credit));

    const type = document.getElementById("voucher_type").value;

    // Payment vouchers must settle out of an actual Cash-in-Hand or Bank
    // Accounts ledger - hard block, no override, unlike the Credit-side
    // warning below.
    if (type === "PAYMENT" && !lines.some((l) => isCashOrBankLedger(l.account_name))) {
      voyagerAlert("A Payment voucher must include at least one ledger under Cash-in-Hand or Bank Accounts.");
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
      resolvedLines.push({ ledger_id: ledger.id, debit: l.debit, credit: l.credit });
    }

    const payload = {
      company_id: activeCompanyId,
      branch_name: document.getElementById("branch").value,
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
      ? `${API_BASE}/vouchers/${editId}/update/`
      : `${API_BASE}/vouchers/create/`;
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

  const active = await VoyagerShell.init({
    activeKey: ticketId ? "tickets" : "vouchers",
    onCompanyChange: async (id, country) => { activeCompanyId = Number(id); activeCountry = country; await populateRefs(activeCompanyId); },
  });
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
          const res = await fetch(`${API_BASE}/vouchers/${editId}/?company_id=${activeCompanyId}`);
          const v = await res.json();
          if (!res.ok) throw new Error(v.error || "Could not load this voucher.");
          prefill(v);
        } catch (err) {
          voyagerAlert(err.message || "Could not load this voucher. Is the Django backend running?");
        }
      } else {
        addLine(); addLine();
        recalcTotals();
      }
    }
  }
})();