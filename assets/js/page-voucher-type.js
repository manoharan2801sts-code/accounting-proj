(function () {
  const API_BASE = window.API_BASE || "/api";
  const VOUCHER_TYPE_API = `${API_BASE}/voucher-type/`;
  let activeCompanyId;
  let editingId = null; // null = creating new, number = editing that Voucher Type's id

  function setHint(msg, ok) {
    const el = document.getElementById("vt-name-hint");
    el.textContent = msg || "";
    el.style.color = ok ? "#1B8A5A" : "#D64545";
  }

  const TOGGLE_IDS = [
    "vt-active", "vt-addl-numbering", "vt-effective-dates",
    "vt-zero-value", "vt-narration", "vt-narration-ledger",
  ];

  function updateToggleText(id) {
    const el = document.getElementById(id);
    const text = document.getElementById(`${id}-text`);
    if (el && text) text.textContent = el.checked ? "Yes" : "No";
  }
  function getToggleValue(id) {
    const el = document.getElementById(id);
    return !!(el && el.checked);
  }
  function setToggleValue(id, value) {
    const el = document.getElementById(id);
    if (el) el.checked = !!value;
    updateToggleText(id);
  }

  TOGGLE_IDS.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", () => updateToggleText(id));
  });

  // Additional Numbering Details popup - opens automatically when that
  // toggle is switched on. Its fields are part of the same Save payload.
  // Closing without clicking the popup's own Save (Cancel or the x) means
  // the details were never confirmed, so the toggle reverts to No - it
  // only stays Yes (and the eye icon to reopen/review appears) once the
  // popup itself has been saved at least once.
  const addlNumberingModal = document.getElementById("addl-numbering-modal");
  const addlNumberingToggle = document.getElementById("vt-addl-numbering");
  const anViewBtn = document.getElementById("an-view-btn");
  let anDetailsSaved = false;

  function openAddlNumberingModal() { addlNumberingModal.classList.add("open"); }
  function closeAddlNumberingModal() { addlNumberingModal.classList.remove("open"); }

  addlNumberingToggle.addEventListener("change", (e) => {
    if (e.target.checked) {
      openAddlNumberingModal();
    } else {
      anDetailsSaved = false;
      anViewBtn.style.display = "none";
    }
  });
  anViewBtn.addEventListener("click", openAddlNumberingModal);

  document.getElementById("addl-numbering-close-x-btn").addEventListener("click", () => {
    if (!anDetailsSaved) setToggleValue("vt-addl-numbering", false);
    closeAddlNumberingModal();
  });
  document.getElementById("addl-numbering-cancel-btn").addEventListener("click", () => {
    if (!anDetailsSaved) setToggleValue("vt-addl-numbering", false);
    closeAddlNumberingModal();
  });
  document.getElementById("addl-numbering-save-btn").addEventListener("click", () => {
    anDetailsSaved = true;
    anViewBtn.style.display = "inline-flex";
    closeAddlNumberingModal();
  });

  const anPrefillZero = document.getElementById("an-prefill-zero");
  anPrefillZero.addEventListener("change", () => {
    document.getElementById("an-prefill-zero-text").textContent = anPrefillZero.checked ? "Yes" : "No";
  });

  // Numbers-only filter for the width / starting-number inputs.
  ["an-width", "an-starting-number"].forEach((id) => {
    document.getElementById(id).addEventListener("input", (e) => {
      e.target.value = e.target.value.replace(/[^0-9]/g, "");
    });
  });

  function clearForm() {
    document.getElementById("vt-name").value = "";
    document.getElementById("vt-alias").value = "";
    document.getElementById("vt-type").value = "General";
    document.getElementById("vt-number-method").value = "Automatic";
    setToggleValue("vt-active", true);
    setToggleValue("vt-addl-numbering", false);
    setToggleValue("vt-effective-dates", false);
    setToggleValue("vt-zero-value", false);
    setToggleValue("vt-narration", true);
    setToggleValue("vt-narration-ledger", false);
    anDetailsSaved = false;
    anViewBtn.style.display = "none";
    document.getElementById("an-width").value = "";
    document.getElementById("an-prefill-zero").checked = false;
    document.getElementById("an-prefill-zero-text").textContent = "No";
    document.getElementById("an-applicable-from").value = "";
    document.getElementById("an-starting-number").value = "";
    document.getElementById("an-period").value = "None";
    document.getElementById("an-prefix").value = "";
    document.getElementById("an-suffix").value = "";
    editingId = null;
    setHint("");
    document.getElementById("vt-name").focus();
  }

  function fillForm(vt) {
    document.getElementById("vt-name").value = vt.name || "";
    document.getElementById("vt-alias").value = vt.alias_name || "";
    document.getElementById("vt-type").value = vt.voucher_category || "General";
    document.getElementById("vt-number-method").value = vt.number_method || "Automatic";
    setToggleValue("vt-active", vt.is_active);
    setToggleValue("vt-addl-numbering", vt.allow_additional_numbering);
    setToggleValue("vt-effective-dates", vt.allow_effective_dates);
    setToggleValue("vt-zero-value", vt.allow_zero_value_transaction);
    setToggleValue("vt-narration", vt.allow_narration);
    setToggleValue("vt-narration-ledger", vt.allow_narration_in_each_ledger);

    // setToggleValue() above never dispatches "change" (only a real click
    // does), so it won't auto-open the Additional Numbering Details popup -
    // just reflect its already-saved state via the eye icon.
    anDetailsSaved = !!vt.allow_additional_numbering;
    anViewBtn.style.display = anDetailsSaved ? "inline-flex" : "none";
    document.getElementById("an-width").value = vt.an_width_of_invoice_number != null ? vt.an_width_of_invoice_number : "";
    document.getElementById("an-prefill-zero").checked = !!vt.an_prefill_with_zero;
    document.getElementById("an-prefill-zero-text").textContent = vt.an_prefill_with_zero ? "Yes" : "No";
    document.getElementById("an-applicable-from").value = vt.an_restart_applicable_from || "";
    document.getElementById("an-starting-number").value = vt.an_restart_starting_number != null ? vt.an_restart_starting_number : "";
    document.getElementById("an-period").value = vt.an_restart_period || "None";
    document.getElementById("an-prefix").value = vt.an_prefix_details || "";
    document.getElementById("an-suffix").value = vt.an_suffix_details || "";

    editingId = vt.id;
    setHint("");
    document.getElementById("vt-name").focus();
  }

  document.getElementById("vt-new-btn").addEventListener("click", clearForm);

  // Select Voucher Type popup - lists every saved type by name only; picking
  // one loads its full record into the form above for editing.
  const vtListModal = document.getElementById("vt-list-modal");
  const vtListModalBody = document.getElementById("vt-list-modal-body");
  function closeVtListModal() { vtListModal.classList.remove("open"); }

  document.getElementById("vt-list-btn").addEventListener("click", async () => {
    if (!activeCompanyId) {
      setHint("No active company selected.");
      return;
    }
    vtListModalBody.innerHTML = `<div class="vt-list-empty">Loading...</div>`;
    vtListModal.classList.add("open");
    try {
      const res = await fetch(`${VOUCHER_TYPE_API}?company_id=${activeCompanyId}`);
      const rows = res.ok ? await res.json() : [];
      if (!rows.length) {
        vtListModalBody.innerHTML = `<div class="vt-list-empty">No voucher types saved yet.</div>`;
        return;
      }
      vtListModalBody.innerHTML = rows
        .map((vt) => `<button type="button" class="vt-list-item" data-id="${vt.id}">${vt.name}</button>`)
        .join("");
      vtListModalBody.querySelectorAll(".vt-list-item").forEach((btn) => {
        btn.addEventListener("click", () => {
          const vt = rows.find((r) => r.id === Number(btn.dataset.id));
          if (vt) fillForm(vt);
          closeVtListModal();
        });
      });
    } catch (err) {
      console.error("Could not load Voucher Types", err);
      vtListModalBody.innerHTML = `<div class="vt-list-empty">Could not reach the server.</div>`;
    }
  });
  document.getElementById("vt-list-close-x-btn").addEventListener("click", closeVtListModal);
  document.getElementById("vt-list-cancel-btn").addEventListener("click", closeVtListModal);

  document.getElementById("vt-save-btn").addEventListener("click", async () => {
    const nameInput = document.getElementById("vt-name");
    const name = nameInput.value.trim();

    if (!name) {
      setHint("Voucher Name is required.");
      nameInput.focus();
      return;
    }
    if (!activeCompanyId) {
      setHint("No active company selected.");
      return;
    }

    const body = {
      company_id: activeCompanyId,
      name,
      id: editingId || undefined,
      alias_name: document.getElementById("vt-alias").value.trim(),
      voucher_category: document.getElementById("vt-type").value,
      is_active: getToggleValue("vt-active"),
      number_method: document.getElementById("vt-number-method").value,
      allow_additional_numbering: getToggleValue("vt-addl-numbering"),
      allow_effective_dates: getToggleValue("vt-effective-dates"),
      allow_zero_value_transaction: getToggleValue("vt-zero-value"),
      allow_narration: getToggleValue("vt-narration"),
      allow_narration_in_each_ledger: getToggleValue("vt-narration-ledger"),
      an_width_of_invoice_number: document.getElementById("an-width").value || null,
      an_prefill_with_zero: document.getElementById("an-prefill-zero").checked,
      an_restart_applicable_from: document.getElementById("an-applicable-from").value || null,
      an_restart_starting_number: document.getElementById("an-starting-number").value || null,
      an_restart_period: document.getElementById("an-period").value,
      an_prefix_details: document.getElementById("an-prefix").value.trim(),
      an_suffix_details: document.getElementById("an-suffix").value.trim(),
    };

    const saveBtn = document.getElementById("vt-save-btn");
    saveBtn.disabled = true;
    try {
      const res = await fetch(`${VOUCHER_TYPE_API}save/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        setHint(data.error || "Could not save Voucher Type.");
        nameInput.focus();
        return;
      }
      const verb = editingId ? "updated" : "saved";
      await window.voyagerAlert(`Voucher Type "${data.name}" ${verb} successfully.`, { icon: "success" });
      clearForm();
    } catch (err) {
      console.error("Voucher Type save failed", err);
      setHint("Could not reach the server. Please try again.");
    } finally {
      saveBtn.disabled = false;
    }
  });

  // Not gated on DOMContentLoaded - this page's <script> can be injected
  // by the app's SPA navigation (shell.js's navigateTo) into a document
  // that already finished loading, so DOMContentLoaded never fires again
  // and this would silently never run except on a hard refresh.
  (async function () {
    const active = await window.VoyagerShell.init({
      activeKey: "voucher-type",
      onCompanyChange: (id) => { activeCompanyId = Number(id); },
    });
    if (active) activeCompanyId = Number(active.id);
  })();
})();
