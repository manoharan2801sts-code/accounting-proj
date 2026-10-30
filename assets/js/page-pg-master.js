(async function () {
  let activeCompanyId;
  let allGateways = []; // local cache of gateways for active company
  let ledgers = []; // "Current Liabilities" ledgers, loaded once per company
  let chargesLedgers = []; // "Expenses" ledgers, loaded once per company
  let editingGatewayId = null; // null = creating new, number = editing

  const LEDGER_GROUP = "Current Liabilities";
  const CHARGES_LEDGER_GROUP = "Expenses";
  const PG_MASTER_API = "/api/pg-master/";
  const LEDGERS_BY_GROUP_API = "/api/ledgers-by-group/";

  // DOM Elements - Left Form
  const formName = document.getElementById("pg-form-name");
  const formMaster = document.getElementById("pg-form-master");
  const formChargesMaster = document.getElementById("pg-form-charges-master");
  const formChargesPercentage = document.getElementById("pg-form-charges-percentage");
  const formChargesEffectiveFrom = document.getElementById("pg-form-charges-effective-from");
  const formStatus = document.getElementById("pg-form-status");
  const formStatusLabel = document.getElementById("pg-form-status-label");
  const btnSave = document.getElementById("pg-btn-save");
  const btnSaveText = document.getElementById("pg-btn-save-text");
  const btnCancel = document.getElementById("pg-btn-cancel");
  const formTitle = document.getElementById("pg-form-title");
  const modeBadge = document.getElementById("pg-mode-badge");

  // DOM Elements - Right Grid
  const gatewaysCount = document.getElementById("pg-gateways-count");
  const tbody = document.getElementById("pg-tbody");

  // Effective From may be any date. Before today, saved documents can be
  // affected - the server asks first (chooseBackdateMode), same as Ledger Mapping.
  const fmtISO = (iso) => (iso ? iso.split("-").reverse().join("/") : "");
  const escHtml = (v) => String(v == null ? "" : v).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const pgSettingsText = (s) => s
    ? `${escHtml(s.payment_master_ledger_name || "-")} / ${escHtml(s.pg_charges_master_ledger_name || "-")} / ${s.pg_charges_percentage != null ? Number(s.pg_charges_percentage).toFixed(2) + "%" : "-"}`
    : "-";

  // Back-dated PG Master change (409 needs_backdate_choice) - Replace All /
  // Retain Old Ledgers / Cancel. Resolves "replace", "retain" or null.
  function chooseBackdateMode(data) {
    const d = fmtISO(data.effective_from);
    const docs = data.documents === 1 ? "1 saved document" : `${data.documents} saved documents`;
    const replaced = (data.replaced_rows || []).map((r) => `${pgSettingsText(r)} from ${fmtISO(r.effective_from)}`).join("<br>");
    const modal = document.createElement("div");
    modal.className = "dom-modal-backdrop open";
    modal.innerHTML = `
      <div class="dom-modal-window" style="max-width:560px;">
        <div class="dom-modal-titlebar">
          <div>Back-dated PG Master</div>
          <button type="button" class="dom-titlebar-btn btn-close" data-choice="">&times;</button>
        </div>
        <div style="padding:14px 18px; font-size:13px; line-height:1.5; color:#0F172A;">
          <p style="margin:0 0 8px;"><b>${escHtml(data.gateway_name)}</b> - new settings from <b>${d}</b> (before today).
            There ${data.documents === 1 ? "is" : "are"} <b>${docs}</b> paid through it dated ${d} or later.</p>
          <p style="margin:0 0 8px; color:#475569;">In force on ${d} now (Payment Master / PG Charges Master / PG Charges %):
            ${pgSettingsText(data.current)}</p>
          ${replaced ? `<p style="margin:0 0 10px; color:#475569;">Replaced from ${d}:<br>${replaced}</p>` : ""}
          <div style="border:1px solid #D8E1EC; border-radius:6px; padding:8px 10px; margin-bottom:8px;">
            <b>1. Replace all previous data also</b><br>
            <span style="color:#475569;">Every document dated ${d} or later - saved ones too - posts with the new settings.</span>
          </div>
          <div style="border:1px solid #D8E1EC; border-radius:6px; padding:8px 10px;">
            <b>2. Retain old ledgers</b><br>
            <span style="color:#475569;">The ${docs} keep the settings they post with now. Only documents saved
              (or edited) from now on, dated ${d} or later, take the new settings.</span>
          </div>
        </div>
        <div class="voyager-alert-actions">
          <button type="button" class="dom-nav-btn" data-choice="">Cancel</button>
          <button type="button" class="dom-nav-btn btn-primary" data-choice="retain">Retain Old Ledgers</button>
          <button type="button" class="dom-nav-btn btn-danger" data-choice="replace">Replace All</button>
        </div>
      </div>`;
    document.body.appendChild(modal);
    return new Promise((resolve) => {
      const done = (choice) => {
        document.removeEventListener("keydown", onKey);
        modal.remove();
        resolve(choice || null);
      };
      const onKey = (e) => { if (e.key === "Escape") done(null); };
      document.addEventListener("keydown", onKey);
      modal.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-choice]");
        if (btn) done(btn.dataset.choice);
        else if (e.target === modal) done(null);
      });
      modal.querySelector('[data-choice="retain"]').focus({ preventScroll: true });
    });
  }

  function populateLedgerOptions(selectedId) {
    formMaster.innerHTML = `<option value="">- Select Ledger from Master -</option>` +
      ledgers.map((l) => `<option value="${l.id}" ${Number(selectedId) === l.id ? "selected" : ""}>${l.name}</option>`).join("");
  }

  function populateChargesLedgerOptions(selectedId) {
    formChargesMaster.innerHTML = `<option value="">- Select Ledger from Master -</option>` +
      chargesLedgers.map((l) => `<option value="${l.id}" ${Number(selectedId) === l.id ? "selected" : ""}>${l.name}</option>`).join("");
  }

  async function loadLedgers() {
    try {
      const res = await fetch(`${LEDGERS_BY_GROUP_API}?company_id=${activeCompanyId}&group_name=${encodeURIComponent(LEDGER_GROUP)}`);
      ledgers = res.ok ? await res.json() : [];
    } catch (err) {
      console.error(`Could not load ledgers for group "${LEDGER_GROUP}"`, err);
      ledgers = [];
    }
    populateLedgerOptions(editingGatewayId ? formMaster.value : null);
  }

  async function loadChargesLedgers() {
    try {
      const res = await fetch(`${LEDGERS_BY_GROUP_API}?company_id=${activeCompanyId}&group_name=${encodeURIComponent(CHARGES_LEDGER_GROUP)}`);
      chargesLedgers = res.ok ? await res.json() : [];
    } catch (err) {
      console.error(`Could not load ledgers for group "${CHARGES_LEDGER_GROUP}"`, err);
      chargesLedgers = [];
    }
    populateChargesLedgerOptions(editingGatewayId ? formChargesMaster.value : null);
  }

  async function loadGateways() {
    try {
      const res = await fetch(`${PG_MASTER_API}?company_id=${activeCompanyId}`);
      allGateways = res.ok ? await res.json() : [];
    } catch (err) {
      console.error("Could not load PG Master gateways - is the Django backend running?", err);
      allGateways = [];
    }
  }

  function renderGrid() {
    gatewaysCount.textContent = `${allGateways.length} Gateway${allGateways.length === 1 ? "" : "s"}`;
    tbody.innerHTML = "";

    if (allGateways.length === 0) {
      tbody.innerHTML = `<tr>
        <td colspan="8" style="text-align:center; padding:2.5rem 1rem; color:var(--color-text-muted);">
          <div style="font-size:13px; font-weight:600; margin-bottom:4px;">No Payment Gateways found</div>
          <div style="font-size:12px; color:var(--color-text-faint);">Use the form on the left to add a new gateway.</div>
        </td>
      </tr>`;
      return;
    }

    allGateways.forEach((gw, idx) => {
      const tr = document.createElement("tr");
      tr.className = "pg-grid-row" + (editingGatewayId === gw.id ? " is-selected" : "");
      tr.dataset.id = gw.id;
      tr.title = "Double-click to edit this payment gateway";

      const statusHtml = `<span class="pg-badge-status ${gw.is_active ? "active" : "inactive"}">${gw.is_active ? "Active" : "Inactive"}</span>`;
      const minusBtnHtml = `<button type="button" class="pg-btn-minus" data-id="${gw.id}" title="Delete Gateway">&minus;</button>`;

      tr.innerHTML = `
        <td style="text-align:center; color:var(--color-text-muted); font-size:11.5px; font-weight:600;">${idx + 1}</td>
        <td><strong style="color:var(--color-text-dark);">${gw.gateway_name}</strong></td>
        <td style="color:var(--color-text-dark); font-weight:500;">${gw.payment_master_ledger_name || "-"}</td>
        <td style="color:var(--color-text-dark); font-weight:500;">${gw.pg_charges_master_ledger_name || "-"}</td>
        <td style="text-align:center; color:var(--color-text-dark); font-weight:500;">${gw.pg_charges_percentage != null ? `${Number(gw.pg_charges_percentage).toFixed(2)}%` : "-"}</td>
        <td style="text-align:center; color:var(--color-text-dark); font-weight:500;">${gw.pg_charges_percentage_effective_from ? window.VoyagerUtil.fmtDate(gw.pg_charges_percentage_effective_from) : "-"}</td>
        <td style="text-align:center;">${statusHtml}</td>
        <td style="text-align:center;">${minusBtnHtml}</td>
      `;

      tbody.appendChild(tr);
    });
  }

  function populateForm(gw) {
    editingGatewayId = gw.id;

    formName.value = gw.gateway_name || "";
    populateLedgerOptions(gw.payment_master_ledger_id);
    populateChargesLedgerOptions(gw.pg_charges_master_ledger_id);
    formChargesPercentage.value = gw.pg_charges_percentage != null ? gw.pg_charges_percentage : "";
    formChargesEffectiveFrom.value = gw.pg_charges_percentage_effective_from || "";
    formStatus.checked = !!gw.is_active;
    formStatusLabel.textContent = gw.is_active ? "Active" : "Inactive";

    // Mode UI indicator
    formTitle.textContent = "Edit Payment Gateway";
    modeBadge.textContent = "Modify";
    modeBadge.className = "pg-mode-badge edit";
    btnSaveText.textContent = "Update";

    // Highlight row in grid
    document.querySelectorAll(".pg-grid-row").forEach((r) => {
      if (Number(r.dataset.id) === gw.id) {
        r.classList.add("is-selected");
        r.scrollIntoView({ behavior: "smooth", block: "nearest" });
      } else {
        r.classList.remove("is-selected");
      }
    });
  }

  function resetForm() {
    editingGatewayId = null;

    formName.value = "";
    formMaster.value = "";
    formChargesMaster.value = "";
    formChargesPercentage.value = "";
    formChargesEffectiveFrom.value = "";
    formStatus.checked = true;
    formStatusLabel.textContent = "Active";

    formTitle.textContent = "Add Payment Gateway";
    modeBadge.textContent = "New";
    modeBadge.className = "pg-mode-badge new";
    btnSaveText.textContent = "Save";

    document.querySelectorAll(".pg-grid-row").forEach((r) => r.classList.remove("is-selected"));
  }

  async function saveGateway(confirmReplace = false, backdateMode = null) {
    const gatewayName = formName.value.trim();
    if (!gatewayName) {
      voyagerAlert("Enter a Payment Gateway Name.");
      formName.focus();
      return;
    }

    const ledgerId = formMaster.value;
    if (!ledgerId) {
      voyagerAlert("Pick a Payment Master ledger from the list.");
      formMaster.focus();
      return;
    }

    const isActive = formStatus.checked;
    const chargesLedgerId = formChargesMaster.value;

    const chargesPercentageRaw = formChargesPercentage.value.trim();
    if (chargesPercentageRaw && (isNaN(Number(chargesPercentageRaw)) || Number(chargesPercentageRaw) < 0 || Number(chargesPercentageRaw) > 100)) {
      voyagerAlert("PG Charges Percentage must be a number between 0 and 100.");
      formChargesPercentage.focus();
      return;
    }

    const payload = {
      company_id: activeCompanyId,
      gateway_name: gatewayName,
      payment_master_ledger_id: Number(ledgerId),
      pg_charges_master_ledger_id: chargesLedgerId ? Number(chargesLedgerId) : null,
      pg_charges_percentage: chargesPercentageRaw ? Number(chargesPercentageRaw) : null,
      pg_charges_percentage_effective_from: formChargesEffectiveFrom.value || null,
      is_active: isActive,
      confirm_replace: confirmReplace,
      backdate_mode: backdateMode || undefined,
    };

    if (editingGatewayId) {
      payload.id = editingGatewayId;
    }

    try {
      const res = await fetch(`${PG_MASTER_API}save/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (res.status === 409 && data.needs_backdate_choice) {
        const choice = await chooseBackdateMode(data);
        if (choice) await saveGateway(confirmReplace, choice);
        return;
      }
      // Same Effective From date, different settings: every document dated
      // from that day would move to them - ask first.
      if (res.status === 409 && data.needs_confirm) {
        const d = fmtISO(data.effective_from);
        const ok = await voyagerConfirm(
          `"${data.gateway_name}" already has settings from ${d}:
${pgSettingsText(data.old).replace(/&amp;/g, "&")}

` +
          `Saving with the same date REPLACES them - every document dated ${d} or later ` +
          `(already saved ones too) will post with the new settings.

` +
          `To keep older documents on the old settings, press Cancel and change Effective From ` +
          `to the date the new settings should start.`,
          { title: "Replace PG Master settings?", confirmLabel: "Replace", icon: "warning" });
        if (ok) await saveGateway(true, backdateMode);
        return;
      }
      if (!res.ok) {
        throw new Error(data.error || `Save failed (${res.status})`);
      }
      if (backdateMode === "retain" && data.documents_retained) {
        voyagerAlert(`Saved. ${data.documents_retained} saved document(s) keep their old PG settings.`, { icon: "success" });
      }

      await loadGateways();
      resetForm();
      renderGrid();
    } catch (err) {
      console.error("Could not save PG Master gateway", err);
      voyagerAlert(err.message || "Could not save this gateway. Is the Django backend running?", { icon: "error" });
    }
  }

  async function deleteGateway(gwId) {
    const id = Number(gwId);
    const gw = allGateways.find((g) => g.id === id);
    const label = gw ? `gateway "${gw.gateway_name}"` : "this gateway";
    const confirmed = await voyagerConfirm(`Are you sure you want to delete ${label}? This cannot be undone.`, { icon: "delete" });
    if (!confirmed) return;

    try {
      const res = await fetch(`${PG_MASTER_API}${id}/delete/?company_id=${activeCompanyId}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || `Delete failed (${res.status})`);
      }
      if (editingGatewayId === id) {
        resetForm();
      }
      await loadGateways();
      renderGrid();
    } catch (err) {
      console.error("Could not delete PG Master gateway", err);
      voyagerAlert(err.message || "Could not delete this gateway.", { icon: "error" });
    }
  }

  // Double-click row handler to populate left fields for editing
  tbody.addEventListener("dblclick", (e) => {
    const row = e.target.closest(".pg-grid-row");
    if (!row || !row.dataset.id) return;
    const gwId = Number(row.dataset.id);
    const gw = allGateways.find((g) => g.id === gwId);
    if (gw) {
      populateForm(gw);
    }
  });

  // Click on minus button in grid
  tbody.addEventListener("click", (e) => {
    const minusBtn = e.target.closest(".pg-btn-minus");
    if (minusBtn) {
      e.stopPropagation();
      deleteGateway(minusBtn.dataset.id);
    }
  });

  // Numbers-only filter (digits + a single decimal point) for the
  // PG Charges Percentage field - it's type="text" (not type="number")
  // because native number inputs silently reset to "" on an intermediate-
  // invalid value like "2." while typing.
  formChargesPercentage.addEventListener("input", (e) => {
    let v = e.target.value.replace(/[^0-9.]/g, "");
    const firstDot = v.indexOf(".");
    if (firstDot !== -1) v = v.slice(0, firstDot + 1) + v.slice(firstDot + 1).replace(/\./g, "");
    e.target.value = v;
  });

  // Status toggle label
  formStatus.addEventListener("change", () => {
    formStatusLabel.textContent = formStatus.checked ? "Active" : "Inactive";
  });

  // Action buttons
  btnSave.addEventListener("click", () => saveGateway());
  btnCancel.addEventListener("click", resetForm);

  // Initialize Shell & Data
  let active = null;
  try {
    active = await VoyagerShell.init({
      activeKey: "pg-master",
      onCompanyChange: async (id) => {
        activeCompanyId = Number(id);
        await loadLedgers();
        await loadChargesLedgers();
        await loadGateways();
        resetForm();
        renderGrid();
      },
    });
  } catch (err) {
    console.error("Shell init failed", err);
  }

  if (active) {
    activeCompanyId = Number(active.id);
    await loadLedgers();
    await loadChargesLedgers();
    await loadGateways();
    renderGrid();
  } else {
    voyagerAlert("Could not load the active company. Check your connection and reload the page.", { icon: "error" });
  }
})();
