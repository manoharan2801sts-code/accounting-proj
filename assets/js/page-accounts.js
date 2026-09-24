(async function () {
  const API_BASE = window.API_BASE || "/api";
  const { get } = window.VoyagerAPI;
  const { fmtMoney, currencyFor } = window.VoyagerUtil;
  let allAccounts = [], byParent = {}, byId = {}, currentCcy = "INR", currentCompanyId, currentCountryCode;

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function highlight(text, term) {
    if (!term) return escapeHtml(text);
    const idx = text.toLowerCase().indexOf(term.toLowerCase());
    if (idx === -1) return escapeHtml(text);
    return escapeHtml(text.slice(0, idx)) +
      `<mark style="background:#FFE9A8; color:inherit; border-radius:3px; padding:0 2px;">${escapeHtml(text.slice(idx, idx + term.length))}</mark>` +
      escapeHtml(text.slice(idx + term.length));
  }

  function collectAncestors(id, set) {
    let node = byId[id];
    while (node && node.parent_id) {
      set.add(node.parent_id);
      node = byId[node.parent_id];
    }
  }
  function collectDescendants(id, set) {
    (byParent[id] || []).forEach((child) => {
      set.add(child.id);
      collectDescendants(child.id, set);
    });
  }

  function render(term) {
    const trimmed = (term || "").trim();
    let visibleIds = null; // null = show everything

    if (trimmed) {
      const matches = allAccounts.filter(
        (a) => a.name.toLowerCase().includes(trimmed.toLowerCase()) || a.code.toLowerCase().includes(trimmed.toLowerCase())
      );
      if (matches.length === 0) {
        document.getElementById("coa-body").innerHTML = "";
        document.getElementById("coa-empty").style.display = "block";
        return;
      }
      const visible = new Set();
      matches.forEach((a) => {
        visible.add(a.id);
        collectAncestors(a.id, visible);
        if (a.is_group) collectDescendants(a.id, visible);
      });
      visibleIds = visible;
    }
    document.getElementById("coa-empty").style.display = "none";

    function renderLevel(parentKey, depth) {
      return (byParent[parentKey] || [])
        .filter((a) => !visibleIds || visibleIds.has(a.id))
        .map((a) => {
          const indent = 16 + depth * 20;
          const nameHtml = a.is_group
            ? highlight(a.name, trimmed)
            : `<a href="${window.VoyagerEntry.zoomInUrl("ledger-entry.html", a.id, "accounts.html")}" title="Click to edit this ledger">${highlight(a.name, trimmed)}</a>`;
          const balDisplay = a.is_group ? "" : `<span class="drillable" data-ledger="${escapeHtml(a.name)}" title="Click to view the vouchers behind this balance">${fmtMoney(a.balance, currentCcy)}</span>`;
          const actions = a.is_group
            ? ""
            : a.is_in_use
              ? `<div class="coa-actions">
                   <button type="button" class="delete-ledger-btn" disabled title="This ledger is used by one or more tickets and can't be deleted.">Delete</button>
                 </div>`
              : `<div class="coa-actions">
                   <button type="button" class="delete-ledger-btn" data-id="${a.id}" data-name="${escapeHtml(a.name)}" title="Click to delete this ledger.">Delete</button>
                 </div>`;
          return `
            <div class="coa-row ${a.is_group ? "group" : ""}">
              <div class="coa-code">${highlight(a.code, trimmed)}</div>
              <div class="coa-name" style="padding-left:${indent}px;">${nameHtml}</div>
              <div class="coa-type"><span class="pill pill-neutral">${a.account_type}</span></div>
              <div class="coa-balance">${balDisplay}</div>
              ${a.is_group ? '<div style="width:110px;"></div>' : actions}
            </div>
            ${renderLevel(a.id, depth + 1)}`;
        }).join("");
    }
    document.getElementById("coa-body").innerHTML = renderLevel("root", 0);

    document.querySelectorAll(".coa-balance .drillable").forEach((el) => {
      el.addEventListener("click", () => VoyagerDrilldown.byLedger(el.dataset.ledger, currentCompanyId, currentCcy));
    });

    document.querySelectorAll(".delete-ledger-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const ok = await voyagerConfirm(
          `Delete ledger "${btn.dataset.name}"? This only works if no transactions exist for it.`,
          { title: "Delete Ledger", confirmLabel: "Delete", icon: "delete" }
        );
        if (!ok) return;
        try {
          const res = await fetch(`${API_BASE}/ledgers/${btn.dataset.id}/delete/?company_id=${currentCompanyId}`, {
            method: "DELETE",
          });
          const result = await res.json();
          if (!res.ok) throw new Error(result.error || "Could not delete this ledger.");
          load(currentCompanyId, currentCountryCode);
        } catch (err) {
          voyagerAlert(err.message || "Could not delete this ledger. Is the Django backend running?", { icon: "error" });
        }
      });
    });
  }

  const ACCOUNTS_API = `${API_BASE}/accounts/`;

  async function load(companyId, country) {
    currentCompanyId = companyId; currentCountryCode = country;
    try {
      const res = await fetch(`${ACCOUNTS_API}?company_id=${companyId}`);
      if (!res.ok) throw new Error(`Accounts API returned ${res.status}`);
      allAccounts = await res.json();
    } catch (err) {
      console.error("Could not load accounts from the Django API - is it running on localhost:8000?", err);
      allAccounts = [];
    }
    currentCcy = currencyFor(country);
    byParent = {}; byId = {};
    allAccounts.forEach((a) => {
      byId[a.id] = a;
      const key = a.parent_id || "root";
      (byParent[key] = byParent[key] || []).push(a);
    });
    render(document.getElementById("coa-search").value);
  }

  document.getElementById("coa-search").addEventListener("input", (e) => render(e.target.value));

  const active = await VoyagerShell.init({ activeKey: "accounts", onCompanyChange: load });
  if (active) load(active.id, active.country);
})();