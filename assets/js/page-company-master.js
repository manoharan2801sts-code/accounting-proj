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
  // View/Edit mode - opens read-only showing whatever's already saved;
  // "Edit" in the titlebar unlocks every field, "Save" (in the actions
  // row) both persists it AND drops back into read-only afterward.
  // ============================================================
  // Save stays disabled until something in the form actually differs
  // from the snapshot taken the moment Edit was clicked - opening Edit
  // and clicking Save without changing anything shouldn't be allowed to
  // fire a save (and re-persist identical data) at all.
  let editSnapshot = null;
  function formFieldsList() {
    return Array.from(document.querySelectorAll(".cmx-grid input, .cmx-grid select, .cmx-grid textarea"));
  }
  function snapshotForm() {
    const snap = {};
    formFieldsList().forEach((el) => { snap[el.id] = el.value; });
    return snap;
  }
  function formIsDirty() {
    if (!editSnapshot) return false;
    return formFieldsList().some((el) => editSnapshot[el.id] !== el.value);
  }
  function refreshSaveEnabled() {
    document.getElementById("cm-save-btn").disabled = !formIsDirty();
  }

  function setViewMode(readOnly) {
    formFieldsList().forEach((el) => { el.disabled = readOnly; });
    document.getElementById("cm-edit-btn").style.display = readOnly ? "" : "none";
    document.getElementById("cm-save-btn").style.display = readOnly ? "none" : "";
    if (!readOnly) {
      editSnapshot = snapshotForm();
      refreshSaveEnabled(); // starts disabled - nothing's changed yet
    } else {
      editSnapshot = null;
    }
  }
  document.getElementById("cm-edit-btn").addEventListener("click", () => setViewMode(false));
  document.querySelector(".cmx-grid").addEventListener("input", refreshSaveEnabled);
  document.querySelector(".cmx-grid").addEventListener("change", refreshSaveEnabled);

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
  // No. of Decimals - a single digit only, no decimal point or anything
  // else (maxlength=1 alone doesn't stop a paste from slipping in extra
  // non-digit characters, so this strips+truncates on every input too).
  document.getElementById("cm-decimal-places").addEventListener("input", (e) => {
    const cleaned = e.target.value.replace(/[^0-9]/g, "").slice(0, 1);
    if (cleaned !== e.target.value) e.target.value = cleaned;
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

  // Country -> default Currency Symbol/Name, applied on the Country
  // dropdown's own onchange - just fills the two fields in, doesn't lock
  // them, so a real value can still be typed over it by hand afterward.
  const COUNTRY_CURRENCY_DEFAULTS = {
    India: { symbol: "₹", name: "Indian Rupee" },
    UAE: { symbol: "د.إ", name: "UAE Dirham" },
  };
  // India's financial year starts 1-April - defaults Financial Year From/
  // Books Beginning From to that (this FY if today's on/after 1-Apr,
  // otherwise last FY, same "current FY" convention ticket-entry.html's
  // own date pickers use). Still just a starting value, not locked -
  // editable like everything else once Edit is on.
  function currentFyStartISO() {
    const today = new Date();
    const fyYear = today.getMonth() >= 3 ? today.getFullYear() : today.getFullYear() - 1;
    return `${fyYear}-04-01`;
  }
  function applyCountryCurrencyDefaults() {
    const country = document.getElementById("cm-country").value;
    const d = COUNTRY_CURRENCY_DEFAULTS[country];
    if (!d) return;
    document.getElementById("cm-currency-symbol").value = d.symbol;
    document.getElementById("cm-currency-name").value = d.name;
    if (country === "India") {
      const fyStart = currentFyStartISO();
      document.getElementById("cm-fy-from").value = fyStart;
      document.getElementById("cm-books-from").value = fyStart;
    }
  }
  document.getElementById("cm-country").addEventListener("change", applyCountryCurrencyDefaults);

  function clearForm() {
    ["cm-company-name", "cm-mailing-name", "cm-address", "cm-state", "cm-pincode", "cm-telephone",
      "cm-mobile", "cm-email", "cm-fy-from", "cm-books-from", "cm-pan", "cm-cin", "cm-tan", "cm-hsn-sac",
      "cm-currency-symbol", "cm-currency-name", "cm-decimal-places"]
      .forEach((id) => { document.getElementById(id).value = ""; });
    document.getElementById("cm-gst-reg-type").value = "Regular";
    document.getElementById("cm-decimal-places").value = "2";
    document.getElementById("cm-country").value = "India";
    applyCountryCurrencyDefaults();
    ["cm-pincode-hint", "cm-mobile-hint", "cm-email-hint", "cm-gst-no-hint"].forEach((id) => setHint(id, "", true));
    document.getElementById("cm-logo-file").value = "";
    document.getElementById("cm-seal-file").value = "";
    setLogo(null);
    setSeal(null);
    document.getElementById("cm-company-name").focus();
  }

  function fillForm(c) {
    set("cm-company-name", c.company_name);
    set("cm-mailing-name", c.mailing_name);
    document.getElementById("cm-country").value = c.country || "India";
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
    set("cm-pan", c.pan_number);
    set("cm-cin", c.cin_number);
    set("cm-tan", c.tan_number);
    set("cm-hsn-sac", c.hsn_sac);
    set("cm-currency-symbol", c.currency_symbol);
    set("cm-currency-name", c.currency_name);
    set("cm-decimal-places", c.decimal_places != null ? c.decimal_places : 2);
    setLogo(c.logo_base64 || null);
    setSeal(c.seal_base64 || null);
  }

  // ============================================================
  // Upload Logo / Upload Seal - each image lives as a base64 data URL
  // right in the same JSON save payload as every other field (no
  // MEDIA_ROOT/file-upload infra exists in this project), capped at 2MB
  // client-side before it's ever read into memory.
  // ============================================================
  const MAX_UPLOAD_BYTES = 2 * 1024 * 1024;
  let logoBase64 = null;
  let sealBase64 = null;
  function setLogo(dataUrl) {
    logoBase64 = dataUrl || null;
    const img = document.getElementById("cm-logo-preview");
    img.src = logoBase64 || "";
    img.style.display = logoBase64 ? "" : "none";
  }
  function setSeal(dataUrl) {
    sealBase64 = dataUrl || null;
    const img = document.getElementById("cm-seal-preview");
    img.src = sealBase64 || "";
    img.style.display = sealBase64 ? "" : "none";
  }
  function wireUpload(inputId, onLoaded) {
    document.getElementById(inputId).addEventListener("change", (e) => {
      const file = e.target.files[0];
      if (!file) return;
      if (file.size > MAX_UPLOAD_BYTES) {
        voyagerAlert("Image must be under 2 MB.", { icon: "error" });
        e.target.value = "";
        return;
      }
      const reader = new FileReader();
      reader.onload = () => { onLoaded(reader.result); refreshSaveEnabled(); };
      reader.readAsDataURL(file);
    });
  }
  wireUpload("cm-logo-file", setLogo);
  wireUpload("cm-seal-file", setSeal);

  // Loads (or blanks the form for) whichever CompanyMaster row matches
  // the active company - not a list of every company in the system.
  async function loadActiveCompany() {
    if (!activeCompanyId) return;
    try {
      const res = await fetch(`${COMPANY_MASTER_API}?id=${activeCompanyId}`);
      if (res.ok) {
        fillForm(await res.json());
        setViewMode(true); // real saved data - open read-only
        return;
      }
    } catch (err) {
      console.error("Could not load Company Master - is the Django backend running?", err);
    }
    // No row saved yet for this company (a fresh 404, or a network miss) -
    // start blank and already editable, ready for the first Save to
    // create it (nothing to "view" yet, so skip the Edit-button step).
    clearForm();
    setViewMode(false);
  }

  // ============================================================
  // Save
  // ============================================================
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
      pan_number: document.getElementById("cm-pan").value.trim().toUpperCase(),
      cin_number: document.getElementById("cm-cin").value.trim().toUpperCase(),
      tan_number: document.getElementById("cm-tan").value.trim().toUpperCase(),
      hsn_sac: document.getElementById("cm-hsn-sac").value.trim(),
      currency_symbol: document.getElementById("cm-currency-symbol").value.trim(),
      currency_name: document.getElementById("cm-currency-name").value.trim(),
      decimal_places: document.getElementById("cm-decimal-places").value || null,
      logo_base64: logoBase64,
      seal_base64: sealBase64,
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
      setViewMode(true);
    } catch (err) {
      voyagerAlert(err.message || "Could not save. Is the Django backend running?", { icon: "error" });
    }
  });

  await loadStates();

  // VoyagerShell.init() itself has no try/catch around its own
  // /companies fetch - a network hiccup there rejects this call, which
  // (unguarded) used to throw all the way out of this page's top-level
  // IIFE and silently abort everything after it. That left the page
  // stuck showing its raw static markup - India/Regular selected by
  // their own default <option>, every other field blank/placeholder -
  // permanently, since loadActiveCompany() (and so fillForm() with the
  // real saved data) never even got called.
  let active = null;
  try {
    active = await VoyagerShell.init({
      activeKey: "company-master",
      onCompanyChange: async (id) => {
        activeCompanyId = Number(id);
        await loadActiveCompany();
      },
    });
  } catch (err) {
    console.error("Shell init failed", err);
  }
  if (!active) {
    // VoyagerShell.init() itself already fell back to demo/mock mode on
    // first-ever load (see its own Store.setToken("demo-token") call), so
    // the active company id is really just whatever's in localStorage
    // (or "1", the first demo company, if nothing's been picked yet) -
    // read that straight from VoyagerAPI.Store instead of giving up, so
    // a failed /companies fetch doesn't stop the real saved data (which
    // has nothing to do with that call) from loading.
    const fallbackId = (window.VoyagerAPI && window.VoyagerAPI.Store.getCompanyId()) || "1";
    active = { id: fallbackId };
  }
  activeCompanyId = Number(active.id);
  await loadActiveCompany();
})();
