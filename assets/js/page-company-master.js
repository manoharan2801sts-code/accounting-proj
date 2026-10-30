(async function () {
  const COMPANY_MASTER_API = "/api/company-master/";
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

  // ============================================================
  // Bank Details - stored in hidden inputs inside the form grid (so Edit/
  // Save/dirty-tracking treat them like any other field); the field itself
  // is a button that opens the popup to view (read-only) or edit them.
  // ============================================================
  const BANK_FIELDS = ["bank_account_holder", "bank_account_no", "bank_ifsc", "bank_swift", "bank_name", "bank_branch"];
  const bankHiddenId = (f) => `cm-${f.replace(/_/g, "-")}`;
  const bankPopupId = (f) => `bk-${f.replace(/_/g, "-")}`;
  function updateBankSummary() {
    const v = (f) => document.getElementById(bankHiddenId(f)).value.trim();
    const text = [v("bank_name"), v("bank_account_no") && `A/c ${v("bank_account_no")}`, v("bank_ifsc")].filter(Boolean).join(" - ");
    document.getElementById("cm-bank-summary").textContent = text || "Add bank details...";
    document.getElementById("cm-bank-btn").classList.toggle("is-empty", !text);
  }
  function openBankPopup() {
    const readOnly = document.getElementById("cm-edit-btn").style.display !== "none";
    BANK_FIELDS.forEach((f) => {
      const el = document.getElementById(bankPopupId(f));
      el.value = document.getElementById(bankHiddenId(f)).value;
      el.disabled = readOnly;
    });
    document.getElementById("bank-ok-btn").style.display = readOnly ? "none" : "";
    document.getElementById("bank-modal").classList.add("open");
  }
  document.getElementById("cm-bank-btn").addEventListener("click", openBankPopup);
  document.querySelectorAll("[data-bank-close]").forEach((b) => b.addEventListener("click", () => document.getElementById("bank-modal").classList.remove("open")));
  document.getElementById("bank-ok-btn").addEventListener("click", () => {
    BANK_FIELDS.forEach((f) => {
      let v = document.getElementById(bankPopupId(f)).value.trim();
      if (f === "bank_ifsc" || f === "bank_swift") v = v.toUpperCase();
      document.getElementById(bankHiddenId(f)).value = v;
    });
    updateBankSummary();
    document.getElementById("bank-modal").classList.remove("open");
    document.getElementById(bankHiddenId(BANK_FIELDS[0])).dispatchEvent(new Event("input", { bubbles: true }));
  });
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
  // India's financial year is fixed at 1-April by statute; every other
  // country here has no single fixed convention, so the user is asked
  // explicitly (askFyConvention below) rather than always silently
  // defaulting to the plain calendar year - some overseas branches still
  // want to align with an Apr-Mar parent/group reporting calendar.
  // Defaults to this FY/year if today's already past its start,
  // otherwise last one (same "current FY" convention ticket-entry.html's
  // own date pickers use). Still just a starting value, not locked -
  // editable like everything else once Edit is on.
  function fyStartISO(convention) {
    const today = new Date();
    if (convention !== "apr-mar") return `${today.getFullYear()}-01-01`;
    const fyYear = today.getMonth() >= 3 ? today.getFullYear() : today.getFullYear() - 1;
    return `${fyYear}-04-01`;
  }
  // fyConvention ("jan-dec"/"apr-mar") is only passed explicitly when the
  // user just picked one via askFyConvention() - otherwise defaults to
  // the one fixed convention for the country (India always Apr-Mar,
  // everything else Jan-Dec) same as before this popup existed.
  function applyCountryCurrencyDefaults(fyConvention) {
    const country = document.getElementById("cm-country").value;
    const d = COUNTRY_CURRENCY_DEFAULTS[country];
    if (!d) return;
    document.getElementById("cm-currency-symbol").value = d.symbol;
    document.getElementById("cm-currency-name").value = d.name;
    const fyStart = fyStartISO(fyConvention || (country === "India" ? "apr-mar" : "jan-dec"));
    document.getElementById("cm-fy-from").value = fyStart;
    document.getElementById("cm-books-from").value = fyStart;
  }

  // Small choice popup (built the same way shell.js's own voyagerConfirm
  // builds its modal, just with two meaningfully-labelled primary
  // buttons instead of Cancel/Delete, since this isn't a yes/no
  // question) - asked once, right when the user picks a non-India
  // Country, so the Monthly Ledger/Ledger Book reports built on
  // financial_year_from reflect whichever convention this company
  // actually follows instead of a silent guess.
  let fyConventionModalEl = null;
  function ensureFyConventionModal() {
    if (fyConventionModalEl) return fyConventionModalEl;
    const modal = document.createElement("div");
    modal.className = "dom-modal-backdrop";
    modal.id = "cm-fy-convention-modal";
    modal.innerHTML = `
      <div class="dom-modal-window" style="max-width:440px;">
        <div class="dom-modal-titlebar">
          <div>Select Financial Year</div>
        </div>
        <div class="voyager-alert-actions" style="flex-direction:column; padding:20px 18px;">
          <button type="button" class="dom-nav-btn btn-primary" id="cm-fy-jan-dec" style="width:100%; padding:14px; font-size:1rem;">January to December</button>
          <button type="button" class="dom-nav-btn btn-primary" id="cm-fy-apr-mar" style="width:100%; padding:14px; font-size:1rem;">April to March</button>
          <button type="button" class="dom-nav-btn" id="cm-fy-back" style="width:100%; padding:8px;">Back (Esc)</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    fyConventionModalEl = modal;
    return modal;
  }
  // Resolves to "jan-dec" / "apr-mar", or null on Back / Esc.
  function askFyConvention() {
    const modal = ensureFyConventionModal();
    modal.classList.add("open");
    return new Promise((resolve) => {
      const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); settle(null); } };
      const settle = (choice) => { modal.classList.remove("open"); document.removeEventListener("keydown", onKey, true); resolve(choice); };
      modal.querySelector("#cm-fy-jan-dec").onclick = () => settle("jan-dec");
      modal.querySelector("#cm-fy-apr-mar").onclick = () => settle("apr-mar");
      modal.querySelector("#cm-fy-back").onclick = () => settle(null);
      document.addEventListener("keydown", onKey, true);
      setTimeout(() => modal.querySelector("#cm-fy-jan-dec").focus(), 0);
    });
  }
  // Country before the current pick - Back / Esc on the Financial Year popup
  // puts it back, with nothing else changed.
  const countrySel = document.getElementById("cm-country");
  let prevCountry = countrySel.value;
  ["focus", "mousedown"].forEach((ev) => countrySel.addEventListener(ev, () => { prevCountry = countrySel.value; }));
  countrySel.addEventListener("change", async () => {
    const country = countrySel.value;
    if (country !== "India") {
      const choice = await askFyConvention();
      if (!choice) { countrySel.value = prevCountry; countrySel.focus(); return; }
      applyCountryCurrencyDefaults(choice);
    } else {
      applyCountryCurrencyDefaults();
    }
    prevCountry = country;
  });

  function clearForm() {
    ["cm-company-name", "cm-mailing-name", "cm-address", "cm-state", "cm-pincode", "cm-telephone",
      "cm-mobile", "cm-email", "cm-fy-from", "cm-books-from", "cm-pan", "cm-cin", "cm-tan", "cm-hsn-sac",
      "cm-currency-symbol", "cm-currency-name", "cm-decimal-places", "cm-terms",
      ...BANK_FIELDS.map(bankHiddenId)]
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
    updateBankSummary();
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
    // Logo / Seal arrive separately (loadCompanyImages) - only set here when
    // this response actually carries them.
    if ("logo_base64" in c && c.logo_base64 !== null) setLogo(c.logo_base64);
    if ("seal_base64" in c && c.seal_base64 !== null) setSeal(c.seal_base64);
    document.getElementById("cm-terms").value = c.terms_conditions || "";
    BANK_FIELDS.forEach((f) => { document.getElementById(bankHiddenId(f)).value = c[f] || ""; });
    updateBankSummary();
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
      reader.onload = async () => { onLoaded(await shrinkImage(reader.result)); refreshSaveEnabled(); };
      reader.readAsDataURL(file);
    });
  }
  // Scales an uploaded image down to at most 600px on its longest side (PNG,
  // so a transparent seal stays transparent). The logo/seal print far smaller
  // than that, and a huge base64 image slows every screen that loads it.
  function shrinkImage(dataUrl) {
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        const scale = Math.min(1, 600 / Math.max(img.width, img.height));
        if (scale === 1 && dataUrl.length < 400000) { resolve(dataUrl); return; }
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
        const out = canvas.toDataURL("image/png");
        resolve(out.length < dataUrl.length ? out : dataUrl);
      };
      img.onerror = () => resolve(dataUrl);
      img.src = dataUrl;
    });
  }
  wireUpload("cm-logo-file", setLogo);
  wireUpload("cm-seal-file", setSeal);

  // Loads (or blanks the form for) whichever CompanyMaster row matches
  // the active company - not a list of every company in the system.
  // The form fills from the light call (no images, ~0.1 s); the Logo / Seal
  // (can be MBs of base64) load right after in the background. Save waits
  // for them (imagesReady) so it never stores an empty logo / seal.
  let imagesReady = Promise.resolve();
  function loadCompanyImages() {
    imagesReady = (async () => {
      try {
        const res = await fetch(`${COMPANY_MASTER_API}?id=${activeCompanyId}&images=all`);
        if (!res.ok) return;
        const c = await res.json();
        // Not over a logo / seal just uploaded while this was loading.
        if (!logoBase64) setLogo(c.logo_base64 || null);
        if (!sealBase64) setSeal(c.seal_base64 || null);
      } catch (err) {
        console.error("Could not load the Company Master logo / seal", err);
      }
    })();
    return imagesReady;
  }
  async function loadActiveCompany() {
    if (!activeCompanyId) return;
    try {
      const res = await fetch(`${COMPANY_MASTER_API}?id=${activeCompanyId}`);
      if (res.ok) {
        fillForm(await res.json());
        setViewMode(true); // real saved data - open read-only
        loadCompanyImages();
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
    // Logo / Seal still loading in the background - wait, or they'd be saved empty.
    await imagesReady;

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
      terms_conditions: document.getElementById("cm-terms").value.trim(),
      ...Object.fromEntries(BANK_FIELDS.map((f) => [f, document.getElementById(bankHiddenId(f)).value.trim()])),
      id: activeCompanyId,
    };

    try {
      const res = await fetch(`${COMPANY_MASTER_API}save/`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error((data && data.error) || `Save failed: ${res.status}`);
      await voyagerAlert("Company details saved.", { icon: "success" });
      // Full reload, not just fillForm()/setViewMode() - the topnav's
      // company/flag switcher and Financial Year label are built once by
      // shell.js and persist across SPA navigations (navigateTo() only
      // swaps .app-main), so a Country change made here (which can flip
      // the flag shown and the Apr-Mar/Jan-Dec FY convention everywhere)
      // would otherwise sit stale until some unrelated full page load
      // happened to refresh it.
      window.location.reload();
      return;
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
  // ============================================================
  // Choose Invoice Template - each layout in assets/js/invoice-templates.js
  // shown as a live preview of this company's own details (name, address,
  // GST, logo, seal) with sample figures. Preview opens it full size,
  // Download prints it (Save as PDF), Select saves it as the layout every
  // Tax Invoice / Credit Note of this company prints in.
  // ============================================================
  let tplCompany = null;
  const tplEl = (id) => document.getElementById(id);
  const tplHtml = (key) => window.VoyagerInvoice.render(key, window.VoyagerInvoice.sampleData(tplCompany));
  const tplName = (key) => (window.VoyagerInvoice.TEMPLATES.find((t) => t.key === key) || {}).name || key;
  let tplPreviewKey = null;

  function renderTemplateCards() {
    const current = (tplCompany && tplCompany.invoice_template) || "classic";
    tplEl("tpl-grid").innerHTML = window.VoyagerInvoice.TEMPLATES.map((t) => `
      <div class="tpl-card ${t.key === current ? "selected" : ""}">
        <div class="tpl-thumb" data-preview="${t.key}" title="Preview"><iframe data-tpl="${t.key}" tabindex="-1"></iframe></div>
        <div class="tpl-info">
          <div class="tpl-name">${t.name}${t.key === current ? '<span class="tpl-badge">Selected</span>' : ""}</div>
          <div class="tpl-desc">${t.description}</div>
        </div>
        <div class="tpl-actions">
          <button type="button" class="cmx-btn" data-preview="${t.key}">Preview</button>
          <button type="button" class="cmx-btn" data-download="${t.key}">Download</button>
          <button type="button" class="cmx-btn cmx-primary" data-select="${t.key}" ${t.key === current ? "disabled" : ""}>${t.key === current ? "Selected" : "Select"}</button>
        </div>
      </div>`).join("");
    tplEl("tpl-grid").querySelectorAll("iframe[data-tpl]").forEach((f) => { f.srcdoc = tplHtml(f.dataset.tpl); });
  }

  async function openTemplateChooser() {
    try {
      const res = await fetch(`${COMPANY_MASTER_API}?id=${activeCompanyId}&images=all`);
      tplCompany = res.ok ? await res.json() : null;
    } catch (_) { tplCompany = null; }
    if (!tplCompany) {
      voyagerAlert("Save the Company Master details first - the templates preview this company's own details.");
      return;
    }
    renderTemplateCards();
    tplEl("tpl-modal").classList.add("open");
  }
  function openTemplatePreview(key) {
    tplPreviewKey = key;
    tplEl("tpl-preview-title").textContent = `Preview - ${tplName(key)}`;
    tplEl("tpl-preview-frame").srcdoc = tplHtml(key);
    const current = (tplCompany && tplCompany.invoice_template) || "classic";
    tplEl("tpl-preview-select").disabled = key === current;
    tplEl("tpl-preview-select").textContent = key === current ? "Selected" : "Select";
    tplEl("tpl-preview-modal").classList.add("open");
  }
  async function selectTemplate(key) {
    try {
      const res = await fetch(`${COMPANY_MASTER_API}invoice-template/`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: activeCompanyId, invoice_template: key }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || "Could not save the invoice template.");
      tplCompany.invoice_template = key;
      renderTemplateCards();
      tplEl("tpl-preview-modal").classList.remove("open");
      voyagerAlert(`"${tplName(key)}" is now the invoice template for every print.`, { icon: "success" });
    } catch (err) {
      voyagerAlert(err.message, { icon: "error" });
    }
  }
  const downloadTemplate = (key) => window.VoyagerInvoice.print(tplHtml(key), `${tplName(key)} - Sample`);

  tplEl("cm-template-btn").addEventListener("click", openTemplateChooser);
  tplEl("tpl-grid").addEventListener("click", (e) => {
    const t = e.target.closest("[data-preview],[data-download],[data-select]");
    if (!t) return;
    if (t.dataset.preview) openTemplatePreview(t.dataset.preview);
    else if (t.dataset.download) downloadTemplate(t.dataset.download);
    else if (t.dataset.select) selectTemplate(t.dataset.select);
  });
  tplEl("tpl-preview-download").addEventListener("click", () => downloadTemplate(tplPreviewKey));
  tplEl("tpl-preview-select").addEventListener("click", () => selectTemplate(tplPreviewKey));
  document.querySelectorAll("[data-tpl-close]").forEach((b) => b.addEventListener("click", () => tplEl(b.dataset.tplClose).classList.remove("open")));

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
