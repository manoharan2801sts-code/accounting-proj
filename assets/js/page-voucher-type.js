(function () {
  // Session-only form - there is no backend VoucherType table
  // (Voucher.VOUCHER_TYPE_CHOICES stays the fixed accounting types the
  // rest of the app actually uses). Nothing is saved to the server.

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
    return el && el.checked ? "yes" : "no";
  }
  function setToggleValue(id, value) {
    const el = document.getElementById(id);
    if (el) el.checked = value === "yes";
    updateToggleText(id);
  }

  TOGGLE_IDS.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", () => updateToggleText(id));
  });

  // Additional Numbering Details popup - opens automatically when that
  // toggle is switched on, per spec. UI-only, nothing persisted.
  const addlNumberingModal = document.getElementById("addl-numbering-modal");
  function closeAddlNumberingModal() { addlNumberingModal.classList.remove("open"); }
  document.getElementById("vt-addl-numbering").addEventListener("change", (e) => {
    if (e.target.checked) addlNumberingModal.classList.add("open");
  });
  document.getElementById("addl-numbering-close-x-btn").addEventListener("click", closeAddlNumberingModal);
  document.getElementById("addl-numbering-cancel-btn").addEventListener("click", closeAddlNumberingModal);
  document.getElementById("addl-numbering-save-btn").addEventListener("click", closeAddlNumberingModal);

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
    setToggleValue("vt-active", "yes");
    setToggleValue("vt-addl-numbering", "no");
    setToggleValue("vt-effective-dates", "no");
    setToggleValue("vt-zero-value", "no");
    setToggleValue("vt-narration", "yes");
    setToggleValue("vt-narration-ledger", "no");
    document.getElementById("an-width").value = "";
    document.getElementById("an-prefill-zero").checked = false;
    document.getElementById("an-prefill-zero-text").textContent = "No";
    document.getElementById("an-applicable-from").value = "";
    document.getElementById("an-starting-number").value = "";
    document.getElementById("an-period").value = "None";
    document.getElementById("an-prefix").value = "";
    document.getElementById("an-suffix").value = "";
    setHint("");
    document.getElementById("vt-name").focus();
  }

  document.getElementById("vt-new-btn").addEventListener("click", clearForm);

  document.getElementById("vt-save-btn").addEventListener("click", () => {
    const nameInput = document.getElementById("vt-name");
    const name = nameInput.value.trim();

    // Voucher Name - mandatory.
    if (!name) {
      setHint("Voucher Name is required.");
      nameInput.focus();
      return;
    }
    setHint(`"${name}" saved for this session.`, true);
  });

  // Not gated on DOMContentLoaded - this page's <script> can be injected
  // by the app's SPA navigation (shell.js's navigateTo) into a document
  // that already finished loading, so DOMContentLoaded never fires again
  // and this would silently never run except on a hard refresh.
  (async function () {
    await window.VoyagerShell.init({ activeKey: "voucher-type" });
  })();
})();
