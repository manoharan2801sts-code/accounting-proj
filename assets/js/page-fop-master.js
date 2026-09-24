(async function () {
  const API_BASE = window.API_BASE || "/api";
  let activeCompanyId;
  let currentCards = []; // cards loaded for the currently selected Card Type
  let ledgers = []; // "Current Liabilities" ledgers, loaded once per company
  let editingCardId = null; // null = creating new card, number = editing card

  const CARD_MASK_PREFIX = "XXXXXXXXXXXX"; // 12 X's — same for Own Card and Client Card
  const LEDGER_GROUP = "Current Liabilities";
  const FOP_MASTER_API = `${API_BASE}/fop-master/`;
  const LEDGERS_BY_GROUP_API = `${API_BASE}/ledgers-by-group/`;

  // DOM Elements - Top Toolbar
  const cardTypeSelect = document.getElementById("fm-card-type-select");
  const typeBadgeName = document.getElementById("fm-type-badge-name");

  // DOM Elements - Left Form
  const cardLast4 = document.getElementById("fm-card-last4");
  const bankNameGroup = document.getElementById("fm-bank-name-group");
  const bankName = document.getElementById("fm-bank-name");
  const cardMasterGroup = document.getElementById("fm-card-master-group");
  const cardMaster = document.getElementById("fm-card-master");
  const statusToggle = document.getElementById("fm-status-toggle");
  const statusLabel = document.getElementById("fm-status-label");
  const btnSave = document.getElementById("fm-btn-save");
  const btnSaveText = document.getElementById("fm-btn-save-text");
  const btnCancel = document.getElementById("fm-btn-cancel");
  const formTitle = document.getElementById("fm-form-title");
  const modeBadge = document.getElementById("fm-mode-badge");

  // DOM Elements - Right Grid
  const gridTitle = document.getElementById("fm-grid-title");
  const cardsCount = document.getElementById("fm-cards-count");
  const thead = document.getElementById("fm-thead");
  const tbody = document.getElementById("fm-tbody");

  function getSelectedCardType() {
    return cardTypeSelect ? cardTypeSelect.value : "";
  }

  function updateCardTypeView() {
    const type = getSelectedCardType();
    const splitLayout = document.getElementById("fm-split-layout");
    const typeBadge = document.getElementById("fm-type-badge");

    if (!type) {
      if (splitLayout) splitLayout.style.display = "none";
      if (typeBadge) typeBadge.style.display = "none";
      return;
    }

    if (splitLayout) splitLayout.style.display = "grid";
    if (typeBadge) typeBadge.style.display = "inline-flex";
    if (typeBadgeName) typeBadgeName.textContent = type;

    const isClient = type === "Client Card";

    // Toggle Left Form fields - Card Number is the same masked format for
    // both card types now; Bank Name is shown for both; Card Master
    // (ledger) is Own Card only, hidden for Client Card.
    cardMasterGroup.style.display = isClient ? "none" : "block";
    bankNameGroup.style.display = "block";

    // Update Headings
    formTitle.textContent = editingCardId ? `Edit ${type}` : `Add ${type}`;
    gridTitle.textContent = `${type}s List`;

    // Render Grid Headers - Bank Name column shown for both card types;
    // Card Master column only for Own Card.
    thead.innerHTML = `<tr>
      <th style="width:38px; text-align:center;">#</th>
      <th style="width:190px;">Card Number</th>
      <th style="width:150px;">Bank Name</th>
      ${isClient ? "" : "<th>Card Master</th>"}
      <th style="width:90px; text-align:center;">Status</th>
      <th style="width:65px; text-align:center;">Action</th>
    </tr>`;
  }

  function populateLedgerOptions(selectedId) {
    cardMaster.innerHTML = `<option value="">- Select Ledger from Master -</option>` +
      ledgers.map((l) => `<option value="${l.id}" ${Number(selectedId) === l.id ? "selected" : ""}>${l.name}</option>`).join("");
  }

  async function loadLedgers() {
    try {
      const res = await fetch(`${LEDGERS_BY_GROUP_API}?company_id=${activeCompanyId}&group_name=${encodeURIComponent(LEDGER_GROUP)}`);
      ledgers = res.ok ? await res.json() : [];
    } catch (err) {
      console.error(`Could not load ledgers for group "${LEDGER_GROUP}"`, err);
      ledgers = [];
    }
    populateLedgerOptions(editingCardId ? cardMaster.value : null);
  }

  async function loadCardsForType() {
    const type = getSelectedCardType();
    try {
      const res = await fetch(`${FOP_MASTER_API}?company_id=${activeCompanyId}&card_type=${encodeURIComponent(type)}`);
      currentCards = res.ok ? await res.json() : [];
    } catch (err) {
      console.error("Could not load FOP Master cards - is the Django backend running?", err);
      currentCards = [];
    }
  }

  function renderGrid() {
    cardsCount.textContent = `${currentCards.length} Card${currentCards.length === 1 ? "" : "s"}`;
    tbody.innerHTML = "";

    if (currentCards.length === 0) {
      const colSpan = getSelectedCardType() === "Client Card" ? 5 : 6;
      tbody.innerHTML = `<tr>
        <td colspan="${colSpan}" style="text-align:center; padding:2.5rem 1rem; color:var(--color-text-muted);">
          <div style="font-size:13px; font-weight:600; margin-bottom:4px;">No ${getSelectedCardType()}s found</div>
          <div style="font-size:12px; color:var(--color-text-faint);">Use the form on the left to add a new card.</div>
        </td>
      </tr>`;
      return;
    }

    currentCards.forEach((card, idx) => {
      const tr = document.createElement("tr");
      tr.className = "fm-grid-row" + (editingCardId === card.id ? " is-selected" : "");
      tr.dataset.id = card.id;
      tr.title = "Double-click to edit this card";

      const isClient = getSelectedCardType() === "Client Card";
      const bankNameHtml = card.bank_name ? card.bank_name : `<span style="color:var(--color-text-faint);">-</span>`;
      const cardMasterHtml = isClient ? "" : `<td style="color:var(--color-text-dark); font-weight:500;">${card.card_master_ledger_name || "-"}</td>`;
      const statusHtml = `<span class="fm-badge-status ${card.is_active ? "active" : "inactive"}">${card.is_active ? "Active" : "Inactive"}</span>`;
      const minusBtnHtml = `<button type="button" class="fm-btn-minus" data-id="${card.id}" title="Delete Card">&minus;</button>`;

      tr.innerHTML = `
        <td style="text-align:center; color:var(--color-text-muted); font-size:11.5px; font-weight:600;">${idx + 1}</td>
        <td><span style="font-family:var(--font-mono); font-size:12.5px; font-weight:500;">${card.card_number}</span></td>
        <td>${bankNameHtml}</td>
        ${cardMasterHtml}
        <td style="text-align:center;">${statusHtml}</td>
        <td style="text-align:center;">${minusBtnHtml}</td>
      `;

      tbody.appendChild(tr);
    });
  }

  function populateForm(card) {
    editingCardId = card.id;
    const type = getSelectedCardType();

    cardLast4.value = (card.card_number || "").slice(-4);
    bankName.value = card.bank_name || "";

    if (type !== "Client Card") populateLedgerOptions(card.card_master_ledger_id);
    statusToggle.checked = !!card.is_active;
    statusLabel.textContent = card.is_active ? "Active" : "Inactive";

    // Mode UI indicator
    formTitle.textContent = `Edit ${type}`;
    modeBadge.textContent = "Modify";
    modeBadge.className = "fm-mode-badge edit";
    btnSaveText.textContent = "Update";

    // Highlight row in grid
    document.querySelectorAll(".fm-grid-row").forEach((r) => {
      if (Number(r.dataset.id) === card.id) {
        r.classList.add("is-selected");
        r.scrollIntoView({ behavior: "smooth", block: "nearest" });
      } else {
        r.classList.remove("is-selected");
      }
    });
  }

  function resetForm() {
    editingCardId = null;
    const type = getSelectedCardType();

    cardLast4.value = "";
    bankName.value = "";
    cardMaster.value = "";
    statusToggle.checked = true;
    statusLabel.textContent = "Active";

    formTitle.textContent = `Add ${type}`;
    modeBadge.textContent = "New";
    modeBadge.className = "fm-mode-badge new";
    btnSaveText.textContent = "Save";

    document.querySelectorAll(".fm-grid-row").forEach((r) => r.classList.remove("is-selected"));
  }

  async function saveCard() {
    const cardType = getSelectedCardType();
    const isClient = cardType === "Client Card";
    let bankNameVal = "";

    const last4 = cardLast4.value.trim();
    if (!/^\d{4}$/.test(last4)) {
      voyagerAlert("Enter the last 4 digits of the Card Number.");
      cardLast4.focus();
      return;
    }
    const cardNumberVal = CARD_MASK_PREFIX + last4;

    bankNameVal = bankName.value.trim();
    if (!bankNameVal) {
      voyagerAlert(`Enter the Bank Name for the ${cardType}.`);
      bankName.focus();
      return;
    }

    let ledgerId = null;
    if (!isClient) {
      ledgerId = cardMaster.value;
      if (!ledgerId) {
        voyagerAlert("Pick a Card Master ledger from the list.");
        cardMaster.focus();
        return;
      }
    }

    const isActive = statusToggle.checked;

    const payload = {
      company_id: activeCompanyId,
      card_type: cardType,
      card_number: cardNumberVal,
      bank_name: bankNameVal,
      card_master_ledger_id: ledgerId ? Number(ledgerId) : null,
      is_active: isActive,
    };

    if (editingCardId) {
      payload.id = editingCardId;
    }

    try {
      const res = await fetch(`${FOP_MASTER_API}save/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || `Save failed (${res.status})`);
      }

      await loadCardsForType();
      resetForm();
      renderGrid();
    } catch (err) {
      console.error("Could not save FOP Master card", err);
      voyagerAlert(err.message || "Could not save this card. Is the Django backend running?", { icon: "error" });
    }
  }

  async function deleteCard(cardId) {
    const id = Number(cardId);
    const card = currentCards.find((c) => c.id === id);
    const label = card ? `card "${card.card_number}"` : "this card";
    const confirmed = await voyagerConfirm(`Are you sure you want to delete ${label}? This cannot be undone.`, { icon: "delete" });
    if (!confirmed) return;

    try {
      const res = await fetch(`${FOP_MASTER_API}${id}/delete/?company_id=${activeCompanyId}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || `Delete failed (${res.status})`);
      }
      if (editingCardId === id) {
        resetForm();
      }
      await loadCardsForType();
      renderGrid();
    } catch (err) {
      console.error("Could not delete FOP Master card", err);
      voyagerAlert(err.message || "Could not delete this card.", { icon: "error" });
    }
  }

  // Top dropdown Card Type change
  cardTypeSelect.addEventListener("change", async () => {
    resetForm();
    updateCardTypeView();
    if (getSelectedCardType()) {
      await loadCardsForType();
      renderGrid();
    }
  });

  // Double-click row handler to populate left fields for editing
  tbody.addEventListener("dblclick", (e) => {
    const row = e.target.closest(".fm-grid-row");
    if (!row || !row.dataset.id) return;
    const cardId = Number(row.dataset.id);
    const card = currentCards.find((c) => c.id === cardId);
    if (card) {
      populateForm(card);
    }
  });

  // Click on minus button in grid
  tbody.addEventListener("click", (e) => {
    const minusBtn = e.target.closest(".fm-btn-minus");
    if (minusBtn) {
      e.stopPropagation();
      deleteCard(minusBtn.dataset.id);
    }
  });

  // Digits-only for Client Card last 4 box
  cardLast4.addEventListener("input", (e) => {
    e.target.value = e.target.value.replace(/\D/g, "").slice(0, 4);
  });

  // Status toggle label
  statusToggle.addEventListener("change", () => {
    statusLabel.textContent = statusToggle.checked ? "Active" : "Inactive";
  });

  // Action buttons
  btnSave.addEventListener("click", saveCard);
  btnCancel.addEventListener("click", resetForm);

  // Initialize Shell & Data
  const active = await VoyagerShell.init({
    activeKey: "fop-master",
    onCompanyChange: async (id) => {
      activeCompanyId = Number(id);
      await loadLedgers();
      if (getSelectedCardType()) {
        await loadCardsForType();
        resetForm();
        renderGrid();
      } else {
        resetForm();
        updateCardTypeView();
      }
    },
  });

  if (active) {
    activeCompanyId = Number(active.id);
    await loadLedgers();
    cardTypeSelect.value = "";
    updateCardTypeView();
  }
})();
