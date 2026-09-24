(async function () {
  const API_BASE = window.API_BASE || "/api";
  const COMPANY_MASTER_API = `${API_BASE}/company-master/`;
  let activeCompanyId = null;
  // This page always edits ONE row - whichever CompanyMaster row's id
  // matches the active company from the top-nav switcher (creating it on
  // first Save if it doesn't exist yet). CompanyMaster.id IS the same
  // company_id every other table in the app scopes its data by, so this
  // is never null/auto-assigned the way editId briefly used to be.

  // ============================================================
  // State dropdown - loaded from assets/data/india-states.xml
  // ============================================================
  async function loadStates() {
    const stateSel = document.getElementById("cm-state");
    try {
      const res = await fetch("assets/data/india-states.xml");
      const xmlText = await res.text();
      const xml = new DOMParser().parseFromString(xmlText, "application/xml");
      const states = Array.from(xml.getElementsByTagName("State")).map((el) => el.getAttribute("name"));
      stateSel.innerHTML = `<option value="">Select...</option>` +
        states.map((name) => `<option value="${name}">${name}</option>`).join("");
    } catch (err) {
      console.error("Could not load assets/data/india-states.xml", err);
    }
  }
  // ============================================================
  // Numeric-only fields (Pincode, Telephone, Mobile) - strip anything
  // that isn't a digit as the user types.
  // ============================================================
  ["cm-pincode", "cm-telephone", "cm-mobile"].forEach((id) => {
    document.getElementById(id).addEventListener("input", (e) => {
      const cleaned = e.target.value.replace(/[^0-9]/g, "");
      if (cleaned !== e.target.value) e.target.value = cleaned;
    });
  });

  // ============================================================
  // Field validation
  // ============================================================
  function setHint(id, msg, ok) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = msg || "";
    el.className = "cmx-field-hint" + (msg && ok ? " ok" : "");
  }

  function validatePincode() {
    const val = document.getElementById("cm-pincode").value.trim();
    if (!val) { setHint("cm-pincode-hint", "", true); return true; }
    const ok = /^[0-9]{6}$/.test(val);
    setHint("cm-pincode-hint", ok ? "" : "Pincode must be 6 digits.", ok);
    return ok;
  }
  document.getElementById("cm-pincode").addEventListener("blur", validatePincode);

  function validateMobile() {
    const val = document.getElementById("cm-mobile").value.trim();
    if (!val) { setHint("cm-mobile-hint", "", true); return true; }
    const ok = /^[0-9]{10}$/.test(val);
    setHint("cm-mobile-hint", ok ? "" : "Mobile No. must be 10 digits.", ok);
    return ok;
  }
  document.getElementById("cm-mobile").addEventListener("blur", validateMobile);

  const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  function validateEmail() {
    const val = document.getElementById("cm-email").value.trim();
    if (!val) { setHint("cm-email-hint", "", true); return true; }
    const ok = EMAIL_REGEX.test(val);
    setHint("cm-email-hint", ok ? "" : "Enter a valid email address.", ok);
    return ok;
  }
  document.getElementById("cm-email").addEventListener("blur", validateEmail);

  // Same GSTIN format used across the app (see page-ledger-entry.js).
  const GSTIN_REGEX = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;
  function validateGstNo() {
    const gstType = document.getElementById("cm-gst-reg-type").value;
    const val = document.getElementById("cm-gst-no").value.trim().toUpperCase();
    if (gstType === "Unregistered") {
      if (!val) { setHint("cm-gst-no-hint", "", true); return true; }
      const ok = GSTIN_REGEX.test(val);
      setHint("cm-gst-no-hint", ok ? "" : "Not a valid GST number format.", ok);
      return ok;
    }
    if (!val) { setHint("cm-gst-no-hint", "GST No. is required unless GST Reg Type is Unregistered.", false); return false; }
    const ok = GSTIN_REGEX.test(val);
    setHint("cm-gst-no-hint", ok ? "" : "Not a valid GST number format (e.g. 33AAAAA0000A1Z5).", ok);
    return ok;
  }
  document.getElementById("cm-gst-no").addEventListener("blur", validateGstNo);
  document.getElementById("cm-gst-reg-type").addEventListener("change", validateGstNo);

  // ============================================================
  // Form <-> record
  // ============================================================
  function set(id, value) { document.getElementById(id).value = value || ""; }

  function clearForm() {
    ["cm-company-name", "cm-mailing-name", "cm-address", "cm-state", "cm-pincode", "cm-telephone",
      "cm-mobile", "cm-email", "cm-fy-from", "cm-books-from", "cm-cin", "cm-tan", "cm-hsn-sac", "cm-description"]
      .forEach((id) => { document.getElementById(id).value = ""; });
    document.getElementById("cm-gst-reg-type").value = "Regular";
    ["cm-pincode-hint", "cm-mobile-hint", "cm-email-hint", "cm-gst-no-hint"].forEach((id) => setHint(id, "", true));
    document.getElementById("cm-company-name").focus();
  }

  function fillForm(c) {
    set("cm-company-name", c.company_name);
    set("cm-mailing-name", c.mailing_name);
    document.getElementById("cm-address").value = c.address || "";
    set("cm-state", c.state);
    set("cm-pincode", c.pincode);
    set("cm-telephone", c.telephone);
    set("cm-mobile", c.mobile);
    set("cm-email", c.email);
    set("cm-fy-from", c.financial_year_from);
    set("cm-books-from", c.books_beginning_from);
    set("cm-gst-reg-type", c.gst_reg_type || "Regular");
    set("cm-gst-no", c.gst_no);
    set("cm-cin", c.cin_number);
    set("cm-tan", c.tan_number);
    set("cm-hsn-sac", c.hsn_sac);
    document.getElementById("cm-description").value = c.description || "";
  }

  // Loads (or blanks the form for) whichever CompanyMaster row matches
  // the active company - not a list of every company in the system.
  async function loadActiveCompany() {
    if (!activeCompanyId) return;
    try {
      const res = await fetch(`${COMPANY_MASTER_API}?id=${activeCompanyId}`);
      if (res.ok) {
        fillForm(await res.json());
        return;
      }
    } catch (err) {
      console.error("Could not load Company Master - is the Django backend running?", err);
    }
    // No row saved yet for this company (a fresh 404, or a network miss) -
    // start blank, ready for the first Save to create it.
    clearForm();
  }

  // ============================================================
  // Save / New
  // ============================================================
  document.getElementById("cm-new-btn").addEventListener("click", clearForm);

  document.getElementById("cm-save-btn").addEventListener("click", async () => {
    if (!activeCompanyId) {
      voyagerAlert("No active company selected.");
      return;
    }
    if (!document.getElementById("cm-company-name").value.trim()) {
      voyagerAlert("Company Name is required.");
      return;
    }
    const pincodeOk = validatePincode();
    const mobileOk = validateMobile();
    const emailOk = validateEmail();
    const gstOk = validateGstNo();
    if (!pincodeOk || !mobileOk || !emailOk || !gstOk) {
      voyagerAlert("Fix the highlighted field(s) before saving.");
      return;
    }

    const payload = {
      company_name: document.getElementById("cm-company-name").value.trim(),
      mailing_name: document.getElementById("cm-mailing-name").value.trim(),
      address: document.getElementById("cm-address").value.trim(),
      country: document.getElementById("cm-country").value,
      state: document.getElementById("cm-state").value,
      pincode: document.getElementById("cm-pincode").value.trim(),
      telephone: document.getElementById("cm-telephone").value.trim(),
      mobile: document.getElementById("cm-mobile").value.trim(),
      email: document.getElementById("cm-email").value.trim(),
      financial_year_from: document.getElementById("cm-fy-from").value || null,
      books_beginning_from: document.getElementById("cm-books-from").value || null,
      gst_reg_type: document.getElementById("cm-gst-reg-type").value,
      gst_no: document.getElementById("cm-gst-no").value.trim().toUpperCase(),
      cin_number: document.getElementById("cm-cin").value.trim().toUpperCase(),
      tan_number: document.getElementById("cm-tan").value.trim().toUpperCase(),
      hsn_sac: document.getElementById("cm-hsn-sac").value.trim(),
      description: document.getElementById("cm-description").value.trim(),
      id: activeCompanyId,
    };

    try {
      const res = await fetch(`${COMPANY_MASTER_API}save/`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error((data && data.error) || `Save failed: ${res.status}`);
      await voyagerAlert("Company details saved.", { icon: "success" });
      fillForm(data);
    } catch (err) {
      voyagerAlert(err.message || "Could not save. Is the Django backend running?", { icon: "error" });
    }
  });

  await loadStates();

  const active = await VoyagerShell.init({
    activeKey: "company-master",
    onCompanyChange: async (id) => {
      activeCompanyId = Number(id);
      await loadActiveCompany();
    },
  });
  if (active) {
    activeCompanyId = Number(active.id);
    await loadActiveCompany();
  }
})();
