(async function () {
  const { showToast } = window.VoyagerEntry;
  let activeCompanyId, activeCountry, groupsFlat = [];
  const editId = new URLSearchParams(window.location.search).get("id");
  const returnTo = new URLSearchParams(window.location.search).get("returnTo") || "accounts.html";

  // States now load from a real XML file at runtime instead of a
  // hardcoded JS array - assets/data/india-states.xml. Feeds both the
  // Debtor's State Name dropdown and the Creditor's Place of Supply dropdown.
  async function loadStatesFromXml() {
    const selects = [
      document.getElementById("in_state_name"),
      document.getElementById("in_place_of_supply"),
      document.getElementById("cr_place_of_supply"),
    ];
    try {
      const res = await fetch("assets/data/india-states.xml");
      if (!res.ok) throw new Error(`Could not fetch india-states.xml (${res.status})`);
      const xmlText = await res.text();
      const xml = new DOMParser().parseFromString(xmlText, "application/xml");
      if (xml.querySelector("parsererror")) throw new Error("india-states.xml is not valid XML");
      const names = Array.from(xml.querySelectorAll("State")).map((el) => el.getAttribute("name"));
      const optionsHtml = '<option value="">Select...</option>' + names.map((s) => `<option value="${s}">${s}</option>`).join("");
      selects.forEach((sel) => { sel.innerHTML = optionsHtml; });
    } catch (err) {
      console.error("Could not load states from XML:", err);
      selects.forEach((sel) => { sel.innerHTML = '<option value="">Could not load states</option>'; });
    }
  }
  await loadStatesFromXml();
  document.getElementById("cancel-link").href = returnTo;

  const API = `${window.API_BASE || '/api'}`;

  const SECTIONS = ["section-bank", "section-debtor-in", "section-debtor-ae", "section-creditor", "section-taxledger", "section-duties-taxes"];
  function hideAllSections() { SECTIONS.forEach((id) => (document.getElementById(id).style.display = "none")); }

  function currentGroupBehavior() {
    const sel = document.getElementById("parent_id");
    const groupName = sel.selectedOptions[0] ? sel.selectedOptions[0].dataset.name : "";
    return window.VoyagerMock.GROUP_BEHAVIOR[groupName] || "OTHER";
  }
  function currentGroupAccountType() {
    const sel = document.getElementById("parent_id");
    return sel.selectedOptions[0] ? sel.selectedOptions[0].dataset.accountType : "";
  }

  function updateVisibility() {
    hideAllSections();
    const cat = currentGroupBehavior();
    if (cat === "BANK") document.getElementById("section-bank").style.display = "block";
    else if (cat === "DEBTOR") document.getElementById(activeCountry === "AE" ? "section-debtor-ae" : "section-debtor-in").style.display = "block";
    else if (cat === "CREDITOR") document.getElementById("section-creditor").style.display = "block";
    else if (cat === "INCOME" || cat === "EXPENSE") document.getElementById("section-taxledger").style.display = "block";
    else if (cat === "DUTIES_TAXES") document.getElementById("section-duties-taxes").style.display = "block";
    document.getElementById("agent-id-wrap").style.display = cat === "DEBTOR" ? "block" : "none";
    // New ledger only - auto-default Opening Balance Type from the group's
    // real accounting nature: Asset/Expense are Debit-natured, Liability/
    // Income/Equity are Credit-natured. This applies to EVERY group, not
    // just Debtor/Creditor specifically.
    if (!editId) {
      const accountType = currentGroupAccountType();
      const debitNature = accountType === "ASSET" || accountType === "EXPENSE";
      const creditNature = accountType === "LIABILITY" || accountType === "INCOME" || accountType === "EQUITY";
      if (debitNature) document.getElementById("opening_balance_type").value = "Debit";
      else if (creditNature) document.getElementById("opening_balance_type").value = "Credit";
    }
    updateGstRequiredMarker();
  }

  document.getElementById("parent_id").addEventListener("change", updateVisibility);
  document.getElementById("tax_category").addEventListener("change", (e) => {
    document.getElementById("tax-type-wrap").style.display = e.target.value === "GST" ? "block" : "none";
  });

  // ============================================================
  // PAN / GST format validation + conditional-mandatory GST No
  // ============================================================
  const PAN_REGEX = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
  const GSTIN_REGEX = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

  function setHint(id, msg, ok) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = msg || "";
    el.className = "field-hint" + (msg ? (ok ? " ok" : " error") : "");
  }

  function updateGstRequiredMarker() {
    const marker = document.getElementById("gst-required-marker");
    if (!marker) return;
    const unregistered = document.getElementById("in_gst_type").value === "Unregistered";
    marker.style.display = unregistered ? "none" : "inline";
  }
  document.getElementById("in_gst_type").addEventListener("change", () => { updateGstRequiredMarker(); validateGstNo(); });

  function validateGstNo() {
    const gstType = document.getElementById("in_gst_type").value;
    const val = document.getElementById("in_gst_no").value.trim().toUpperCase();
    if (gstType === "Unregistered") {
      // Optional when Unregistered - but if they typed one anyway, still check format.
      if (!val) { setHint("in_gst_no_hint", "", true); return true; }
      const ok = GSTIN_REGEX.test(val);
      setHint("in_gst_no_hint", ok ? "" : "Not a valid GST number format.", ok);
      return ok;
    }
    if (!val) { setHint("in_gst_no_hint", "GST No. is required unless GST Type is Unregistered.", false); return false; }
    const ok = GSTIN_REGEX.test(val);
    setHint("in_gst_no_hint", ok ? "" : "Not a valid GST number format (e.g. 33AAAAA0000A1Z5).", ok);
    return ok;
  }
  function validatePanNo() {
    const val = document.getElementById("in_pan_no").value.trim().toUpperCase();
    if (!val) { setHint("in_pan_no_hint", "", true); return true; } // PAN stays optional
    const ok = PAN_REGEX.test(val);
    setHint("in_pan_no_hint", ok ? "" : "Not a valid PAN format (e.g. AAAAA0000A).", ok);
    return ok;
  }
  document.getElementById("in_gst_no").addEventListener("blur", validateGstNo);
  document.getElementById("in_pan_no").addEventListener("blur", validatePanNo);

  function validateCrGstNo() {
    const val = document.getElementById("cr_gst_no").value.trim().toUpperCase();
    if (!val) { setHint("cr_gst_no_hint", "", true); return true; }
    const ok = GSTIN_REGEX.test(val);
    setHint("cr_gst_no_hint", ok ? "" : "Not a valid GST number format (e.g. 33AAAAA0000A1Z5).", ok);
    return ok;
  }
  function validateCrPanNo() {
    const val = document.getElementById("cr_pan_no").value.trim().toUpperCase();
    if (!val) { setHint("cr_pan_no_hint", "", true); return true; }
    const ok = PAN_REGEX.test(val);
    setHint("cr_pan_no_hint", ok ? "" : "Not a valid PAN format (e.g. AAAAA0000A).", ok);
    return ok;
  }
  document.getElementById("cr_gst_no").addEventListener("blur", validateCrGstNo);
  document.getElementById("cr_pan_no").addEventListener("blur", validateCrPanNo);

  // ============================================================
  // Live Agent ID uniqueness check (global - across every ledger/company)
  // ============================================================
  let agentIdCheckTimer;
  document.getElementById("agent_id").addEventListener("blur", () => {
    const agentId = document.getElementById("agent_id").value.trim();
    if (!agentId) { setHint("agent_id_hint", "", true); return; }
    clearTimeout(agentIdCheckTimer);
    agentIdCheckTimer = setTimeout(async () => {
      try {
        const params = new URLSearchParams({ agent_id: agentId });
        if (editId) params.set("exclude_id", editId);
        const res = await fetch(`${API}/ledgers/agent-id-available/?${params}`);
        const result = await res.json();
        setHint("agent_id_hint", result.available ? "" : "This Agent ID is already used by another ledger.", result.available);
      } catch (_) { /* silent - backend down shouldn't block typing */ }
    }, 200);
  });

  // ============================================================
  // Live ledger-name uniqueness check
  // ============================================================
  let nameCheckTimer;
  document.getElementById("name").addEventListener("blur", () => {
    const name = document.getElementById("name").value.trim();
    if (!name || !activeCompanyId) { setHint("name_hint", "", true); return; }
    clearTimeout(nameCheckTimer);
    nameCheckTimer = setTimeout(async () => {
      try {
        const params = new URLSearchParams({ company_id: activeCompanyId, name });
        if (editId) params.set("exclude_id", editId);
        const res = await fetch(`${API}/ledgers/name-available/?${params}`);
        const result = await res.json();
        setHint("name_hint", result.available ? "" : "A ledger with this name already exists.", result.available);
      } catch (_) { /* silent - backend down shouldn't block typing */ }
    }, 200);
  });

  function renderGroupOptions(groups) {
    const byParent = {};
    groups.forEach((g) => { (byParent[g.parent_id || "root"] = byParent[g.parent_id || "root"] || []).push(g); });
    const out = [];
    function walk(parentKey, depth) {
      (byParent[parentKey] || []).forEach((g) => {
        out.push(`<option value="${g.id}" data-name="${g.name}" data-account-type="${g.account_type}">${"- ".repeat(depth)}${g.name}</option>`);
        walk(g.id, depth + 1);
      });
    }
    walk("root", 0);
    return out.join("");
  }

  function prefillForm(ledger) {
    document.getElementById("page-title").textContent = `Edit Ledger - ${ledger.name}`;
    document.getElementById("submit-btn").textContent = "Update Ledger";
    document.getElementById("name").value = ledger.name;
    document.getElementById("parent_id").value = ledger.parent_id;
    document.getElementById("opening_balance").value = ledger.opening_balance || 0;
    document.getElementById("opening_balance_type").value = ledger.opening_balance_type
      || ((ledger.balance ?? ledger.opening_balance ?? 0) >= 0 ? "Debit" : "Credit");
    updateVisibility();

    const set = (id, val) => { const el = document.getElementById(id); if (el && val !== undefined && val !== null) el.value = val; };
    set("bank_account_no", ledger.bank_account_no); set("bank_branch", ledger.bank_branch);
    set("ifsc_code", ledger.ifsc_code); set("swift_code", ledger.swift_code);
    set("in_alias_name", ledger.alias_name); set("in_address_line1", ledger.address_line1); set("in_address_line2", ledger.address_line2);
    set("in_city", ledger.city); set("in_pincode", ledger.pincode); set("in_state_name", ledger.state_name);
    set("in_gst_no", ledger.gst_no); set("in_gst_type", ledger.gst_registration_type); set("in_pan_no", ledger.pan_no);
    set("in_bill_wise", ledger.maintain_balance_bill_wise); set("in_place_of_supply", ledger.place_of_supply);
    set("ae_alias_name", ledger.alias_name); set("ae_address_line1", ledger.address_line1); set("ae_address_line2", ledger.address_line2);
    set("ae_emirate", ledger.emirate); set("ae_po_box_no", ledger.po_box_no); set("ae_vat_trn_no", ledger.vat_trn_no);
    set("ae_trade_license_no", ledger.trade_license_no); set("ae_trade_license_expiry", ledger.trade_license_expiry);
    set("creditor_type", ledger.creditor_type);
    set("supplier_code", ledger.supplier_code); set("creditor_office_id", ledger.office_id);
    set("cr_alias_name", ledger.alias_name); set("cr_address_line1", ledger.address_line1); set("cr_address_line2", ledger.address_line2);
    set("cr_city", ledger.city); set("cr_pincode", ledger.pincode); set("cr_state_name", ledger.state_name);
    set("cr_gst_no", ledger.gst_no); set("cr_gst_type", ledger.gst_registration_type); set("cr_pan_no", ledger.pan_no);
    set("cr_place_of_supply", ledger.place_of_supply);
    set("agent_id", ledger.agent_id);
    set("tax_category", ledger.tax_category); set("tax_type", ledger.tax_type);
    if (ledger.tax_category === "GST") document.getElementById("tax-type-wrap").style.display = "block";
    set("gst_applicable", String(!!ledger.gst_applicable)); set("gst_tax_type", ledger.gst_tax_type);
    set("gst_percentage", ledger.gst_percentage); set("tds_applicable", String(!!ledger.tds_applicable));
    set("tds_percentage", ledger.tds_percentage); set("hsn_code", ledger.hsn_code);
    set("tcs_applicable", String(!!ledger.tcs_applicable)); set("tcs_percentage", ledger.tcs_percentage);
    updateGstRequiredMarker();
  }

  async function populateRefs(companyId) {
    try {
      const res = await fetch(`${API}/ledger-groups/?company_id=${companyId}`);
      if (!res.ok) throw new Error(`Ledger groups API returned ${res.status}`);
      groupsFlat = await res.json();
    } catch (err) {
      console.error("Could not load ledger groups from the Django API - is it running on localhost:8000?", err);
      voyagerAlert("Could not load account groups from the database. Is the Django backend running?", { icon: "error" });
      groupsFlat = [];
    }
    document.getElementById("parent_id").innerHTML = renderGroupOptions(groupsFlat);
    updateVisibility();

    if (editId) {
      try {
        const res = await fetch(`${API}/ledgers/${editId}/?company_id=${companyId}`);
        if (!res.ok) throw new Error("Ledger not found");
        const ledger = await res.json();
        prefillForm(ledger);
      } catch (err) {
        voyagerAlert("Could not load this ledger for editing. Is the Django backend running?", { icon: "error" });
      }
    }
  }

  document.getElementById("ledger-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const cat = currentGroupBehavior();
    const val = (id) => document.getElementById(id)?.value;
    const bool = (id) => document.getElementById(id)?.value === "true";

    // Ledger-name uniqueness (final check right before save, on top of the live blur check)
    const name = document.getElementById("name").value.trim();
    const params = new URLSearchParams({ company_id: activeCompanyId, name });
    if (editId) params.set("exclude_id", editId);
    try {
      const res = await fetch(`${API}/ledgers/name-available/?${params}`);
      const result = await res.json();
      if (!result.available) { setHint("name_hint", "A ledger with this name already exists.", false); voyagerAlert("This ledger name already exists - please use a different name."); return; }
    } catch (_) { /* if the check itself fails, let the create/update call surface the error instead */ }

    // PAN/GST format + conditional-mandatory, only when the Debtor (India) section is showing
    if (cat === "DEBTOR" && activeCountry !== "AE") {
      const gstOk = validateGstNo();
      const panOk = validatePanNo();
      if (!gstOk || !panOk) { voyagerAlert("Fix the GST No. / PAN No. format before saving."); return; }
    }
    if (cat === "CREDITOR") {
      const gstOk = validateCrGstNo();
      const panOk = validateCrPanNo();
      if (!gstOk || !panOk) { voyagerAlert("Fix the GST No. / PAN No. format before saving."); return; }
    }

    // Agent ID uniqueness (final check, Debtor only - it's the only category that shows this field)
    if (cat === "DEBTOR") {
      const agentId = document.getElementById("agent_id").value.trim();
      if (agentId) {
        const agentParams = new URLSearchParams({ agent_id: agentId });
        if (editId) agentParams.set("exclude_id", editId);
        try {
          const res = await fetch(`${API}/ledgers/agent-id-available/?${agentParams}`);
          const result = await res.json();
          if (!result.available) { setHint("agent_id_hint", "This Agent ID is already used by another ledger.", false); voyagerAlert("This Agent ID is already used by another ledger - please use a different one."); return; }
        } catch (_) { /* if the check fails, let the create/update call surface the error instead */ }
      }
    }

    const payload = {
      name,
      parent_id: parseInt(document.getElementById("parent_id").value),
      opening_balance: parseFloat(document.getElementById("opening_balance").value) || 0,
      opening_balance_type: document.getElementById("opening_balance_type").value,
      ledger_category: cat,
    };

    if (cat === "BANK") {
      Object.assign(payload, {
        bank_account_no: val("bank_account_no"), bank_branch: val("bank_branch"),
        ifsc_code: val("ifsc_code"), swift_code: val("swift_code"),
      });
    } else if (cat === "DEBTOR" && activeCountry !== "AE") {
      Object.assign(payload, {
        alias_name: val("in_alias_name"), address_line1: val("in_address_line1"), address_line2: val("in_address_line2"),
        city: val("in_city"), pincode: val("in_pincode"), state_name: val("in_state_name"),
        gst_no: val("in_gst_no") ? val("in_gst_no").toUpperCase() : null,
        gst_registration_type: val("in_gst_type"),
        pan_no: val("in_pan_no") ? val("in_pan_no").toUpperCase() : null,
        agent_id: val("agent_id"),
        maintain_balance_bill_wise: val("in_bill_wise"), place_of_supply: val("in_place_of_supply"),
      });
    } else if (cat === "DEBTOR" && activeCountry === "AE") {
      Object.assign(payload, {
        alias_name: val("ae_alias_name"), address_line1: val("ae_address_line1"), address_line2: val("ae_address_line2"),
        emirate: val("ae_emirate"), po_box_no: val("ae_po_box_no"), vat_trn_no: val("ae_vat_trn_no"),
        trade_license_no: val("ae_trade_license_no"), trade_license_expiry: val("ae_trade_license_expiry") || null,
        agent_id: val("agent_id"),
        maintain_balance_bill_wise: val("in_bill_wise"), place_of_supply: val("in_place_of_supply"),
      });
    } else if (cat === "CREDITOR") {
      Object.assign(payload, {
        creditor_type: val("creditor_type"),
        supplier_code: val("supplier_code"), office_id: val("creditor_office_id"),
        alias_name: val("cr_alias_name"), address_line1: val("cr_address_line1"), address_line2: val("cr_address_line2"),
        city: val("cr_city"), pincode: val("cr_pincode"), state_name: val("cr_state_name"),
        gst_no: val("cr_gst_no") ? val("cr_gst_no").toUpperCase() : null,
        gst_registration_type: val("cr_gst_type"),
        pan_no: val("cr_pan_no") ? val("cr_pan_no").toUpperCase() : null,
        place_of_supply: val("cr_place_of_supply"),
      });
    } else if (cat === "INCOME" || cat === "EXPENSE") {
      Object.assign(payload, {
        gst_applicable: bool("gst_applicable"), gst_tax_type: val("gst_tax_type") || null,
        gst_percentage: parseFloat(val("gst_percentage")) || 0,
        tds_applicable: bool("tds_applicable"), tds_percentage: parseFloat(val("tds_percentage")) || 0,
        hsn_code: val("hsn_code"),
        tcs_applicable: bool("tcs_applicable"), tcs_percentage: parseFloat(val("tcs_percentage")) || 0,
      });
    } else if (cat === "DUTIES_TAXES") {
      Object.assign(payload, {
        tax_category: val("tax_category"),
        tax_type: val("tax_category") === "GST" ? val("tax_type") : null,
      });
    }

    try {
      if (editId) {
        const res = await fetch(`${API}/ledgers/${editId}/update/?company_id=${activeCompanyId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const result = await res.json();
        if (!res.ok) throw new Error(result.error || "Could not update this ledger.");
        showToast("Ledger updated.", returnTo);
      } else {
        const res = await fetch(`${API}/ledgers/create/`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ company_id: activeCompanyId, ...payload }),
        });
        const result = await res.json();
        if (!res.ok) throw new Error(result.error || "Could not save this ledger.");
        showToast("Ledger created and saved to the database.", returnTo);
      }
    } catch (err) {
      voyagerAlert(err.message || "Could not save this ledger. Is the Django backend running on localhost:8000?", { icon: "error" });
    }
  });

  const active = await VoyagerShell.init({
    activeKey: "accounts",
    onCompanyChange: (id, country) => { activeCompanyId = Number(id); activeCountry = country; populateRefs(activeCompanyId); },
  });
  if (active) { activeCompanyId = Number(active.id); activeCountry = active.country; await populateRefs(activeCompanyId); }
})();