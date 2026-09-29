(async function () {
  const API_BASE = window.API_BASE || "/api";
  let activeCompanyId;
  let allMappings = []; // local cache of the last GET for the selected Product
  const ledgerCache = {}; // group_name -> [{id,name}, ...]

  const PRODUCT_TYPES = ["Airline", "Hotel", "Bus", "Visa", "Insurance", "Rail"];

  // A "section" is a rendering concept, not always a 1:1 match with the 5
  // real Masters categories saved on the backend (masters_category) -
  // "consolidator-earnings" below saves as "Earnings From Customer" too,
  // it's just shown as its own sub-heading + table body at the bottom of
  // the Customer tab (after Discount A/c) instead of being folded into
  // the same block as Markup A/c etc.
  const SECTION_DEFS = {
    "earnings-from-customer": {
      category: "Earnings From Customer",
      fields: [
        { field: "Markup A/c", group: "Incomes" },
        { field: "Addl Markup A/c", group: "Incomes" },
        { field: "SSR Markup A/c", group: "Incomes" },
        { field: "Service Fee A/c", group: "Incomes" },
        { field: "Addl Service Fee A/c", group: "Incomes" },
        { field: "SSR Service Fee A/c", group: "Incomes" },
      ],
    },
    "earnings-from-supplier": {
      category: "Earnings From Supplier",
      fields: [
        { field: "Commission A/c", group: "Incomes" },
      ],
    },
    "expenditure-to-customer": {
      category: "Expenditure To Customer",
      fields: [
        { field: "Discount A/c", group: "Expenses" },
      ],
    },
    // Separate income ledgers for the JV's supplier-fed Markup/Service Fee
    // Credit lines (see jv_hardcode.py) - previously those reused the same
    // "Markup A/c" etc. ledger as the customer-side lines; these let that
    // be a distinct Consolidator-specific ledger instead.
    "consolidator-earnings": {
      category: "Earnings From Customer",
      heading: "Consolidator Earnings",
      fields: [
        { field: "Consolidator Markup A/c", group: "Incomes" },
        { field: "Consolidator Addl Markup A/c", group: "Incomes" },
        { field: "Consolidator Service Fee A/c", group: "Incomes" },
        { field: "Consolidator Addl Service Fee A/c", group: "Incomes" },
      ],
    },
    "expenditure-to-supplier": {
      category: "Expenditure To Supplier",
      fields: [
        { field: "Supplier Markup A/c", group: "Expenses" },
        { field: "Supplier Addl Markup A/c", group: "Expenses" },
        { field: "Supplier Service Fee A/c", group: "Expenses" },
        { field: "Supplier Addl Service Fee A/c", group: "Expenses" },
      ],
    },
    "gst-and-tds": {
      category: "GST and TDS",
      fields: [
        { field: "Output IGST A/c", group: "Duties and Taxes" },
        { field: "Output CGST A/c", group: "Duties and Taxes" },
        { field: "Output SGST A/c", group: "Duties and Taxes" },
        { field: "Discount TDS A/c", group: "Duties and Taxes" },
        { field: "Commission TDS A/c", group: "Duties and Taxes" },
        { field: "Input IGST A/c", group: "Duties and Taxes" },
        { field: "Input CGST A/c", group: "Duties and Taxes" },
        { field: "Input SGST A/c", group: "Duties and Taxes" },
      ],
    },
  };

  // The 5 real Masters categories are grouped into just 3 tabs for
  // display: Customer, Supplier, GST and TDS. Order here is display
  // order - "consolidator-earnings" is listed last so it renders below
  // Discount A/c even though it shares a real masters_category with the
  // "earnings-from-customer" section above it.
  const TAB_GROUPS = [
    { key: "customer", label: "Customer", sections: ["earnings-from-customer", "expenditure-to-customer", "consolidator-earnings"] },
    { key: "supplier", label: "Supplier", sections: ["expenditure-to-supplier", "earnings-from-supplier"] },
    { key: "gst-and-tds", label: "GST and TDS", sections: ["gst-and-tds"] },
  ];

  function fillPlain(el, values, placeholder) {
    el.innerHTML = (placeholder ? `<option value="">${placeholder}</option>` : "") +
      values.map((v) => `<option value="${v}">${v}</option>`).join("");
  }
  const productSel = document.getElementById("mm-product");
  const categoriesWrap = document.getElementById("mm-categories-wrap");
  const tabsField = document.getElementById("mm-tabs-field");
  const tabsSlot = document.getElementById("mm-tabs-slot");
  const productBadge = document.getElementById("mm-product-badge");
  const productBadgeName = document.getElementById("mm-product-badge-name");
  fillPlain(productSel, PRODUCT_TYPES, "Select...");

  const LEDGERS_BY_GROUP_API = `${API_BASE}/ledgers-by-group/`;
  async function ledgersForGroup(groupName) {
    if (ledgerCache[groupName]) return ledgerCache[groupName];
    try {
      const res = await fetch(`${LEDGERS_BY_GROUP_API}?company_id=${activeCompanyId}&group_name=${encodeURIComponent(groupName)}`);
      ledgerCache[groupName] = res.ok ? await res.json() : [];
    } catch (err) {
      console.error(`Could not load ledgers for group "${groupName}"`, err);
      ledgerCache[groupName] = [];
    }
    return ledgerCache[groupName];
  }

  function existingMapping(productType, fieldName) {
    return allMappings.find((m) => m.product_type === productType && m.field_name === fieldName);
  }

  const CHECK_ICON = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>`;
  const DOT_ICON = `<svg class="mm-field-dot" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="9"/></svg>`;

  // Categories are shown as 3 tabs (Customer / Supplier / GST and TDS) -
  // right next to the Product dropdown - with one panel visible at a time
  // below. Each tab panel can hold more than one real Masters category
  // (e.g. the Customer tab holds both "Earnings From Customer" and
  // "Expenditure To Customer"), each still its own heading + table so the
  // underlying masters_category saved to the backend is unaffected.
  function buildCategorySections() {
    tabsField.style.display = "";
    tabsSlot.innerHTML = `<div class="mm-tabs">${TAB_GROUPS.map((tab, i) => `
      <button type="button" class="mm-tab-btn ${i === 0 ? "active" : ""}" data-tab="${tab.key}">${tab.label}</button>
    `).join("")}</div>`;

    // No per-category heading above the table - the active tab button
    // itself already says which category this is, a repeated heading was
    // redundant. Sections folded into one tab (e.g. the Customer tab
    // holds "earnings-from-customer", "expenditure-to-customer" and
    // "consolidator-earnings") still share one <table>/<thead>, just a
    // separate <tbody> each - a section with its own "heading" also gets
    // a small sub-heading row in its own <tbody> right before it.
    categoriesWrap.innerHTML = TAB_GROUPS.map((tab, i) => {
      return `
      <div class="mm-tab-panel ${i === 0 ? "active" : ""}" data-tab-panel="${tab.key}">
        <div class="mm-table-card">
          <table class="mm-table">
            <thead><tr>
              <th>Field Name</th><th>Ledger Name (Master)</th><th>Effective From Date</th><th>Action</th>
            </tr></thead>
            ${tab.sections.map((sectionKey) => {
              const def = SECTION_DEFS[sectionKey];
              const heading = def.heading
                ? `<tbody><tr class="mm-subhead-row"><td colspan="4">${def.heading}</td></tr></tbody>` : "";
              return `${heading}<tbody id="mm-fields-tbody-${sectionKey}"></tbody>`;
            }).join("")}
          </table>
        </div>
      </div>
    `;
    }).join("");

    tabsSlot.querySelectorAll(".mm-tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.dataset.tab;
        tabsSlot.querySelectorAll(".mm-tab-btn").forEach((b) => b.classList.toggle("active", b === btn));
        categoriesWrap.querySelectorAll(".mm-tab-panel").forEach((p) => p.classList.toggle("active", p.dataset.tabPanel === tab));
      });
    });
  }

  async function renderCategoryRows(sectionKey) {
    const product = productSel.value;
    const tbody = document.getElementById(`mm-fields-tbody-${sectionKey}`);
    tbody.innerHTML = "";
    if (!product) return;

    const section = SECTION_DEFS[sectionKey];
    for (const def of section.fields) {
      const ledgers = await ledgersForGroup(def.group);
      const existing = existingMapping(product, def.field);
      const locked = !!existing;
      const row = document.createElement("tr");
      row.className = "mm-field-row" + (locked ? " mm-locked" : "");
      row.dataset.category = section.category; // real masters_category, sent to the backend
      row.dataset.sectionKey = sectionKey; // which tbody this row lives in, for re-rendering after save/delete
      row.dataset.field = def.field;
      row.dataset.group = def.group;
      if (existing) row.dataset.mappingId = existing.id;
      row.innerHTML = `
        <td>
          <div class="mm-field-name">${DOT_ICON}${def.field}</div>
        </td>
        <td>
          <select class="form-control-custom mm-ledger-select" style="border-radius:0;" ${locked ? "disabled" : ""}>
            <option value="">- Select Ledger from Master -</option>
            ${ledgers.map((l) => `<option value="${l.id}" ${existing && existing.ledger_id === l.id ? "selected" : ""}>${l.name}</option>`).join("")}
          </select>
        </td>
        <td>
          <input type="date" class="form-control-custom mm-effective-from" style="border-radius:0;" value="${existing ? existing.effective_from : ""}" ${locked ? "disabled" : ""} />
        </td>
        <td>
          <div class="dom-action-btn-group">
            ${locked
              ? `<button type="button" class="dom-action-btn btn-edit mm-row-edit-btn" title="Edit">Edit</button>
                 <button type="button" class="dom-action-btn btn-delete mm-row-del-btn" title="Delete">Del</button>`
              : `<button type="button" class="dom-action-btn btn-edit mm-row-save-btn" title="Save">${CHECK_ICON}</button>`}
          </div>
        </td>
      `;
      tbody.appendChild(row);
    }
  }

  async function renderAllCategories() {
    for (const sectionKey of Object.keys(SECTION_DEFS)) {
      await renderCategoryRows(sectionKey);
    }
  }

  productSel.addEventListener("change", async () => {
    const has = !!productSel.value;
    categoriesWrap.style.display = has ? "" : "none";
    productBadge.style.display = has ? "inline-flex" : "none";
    if (!has) { categoriesWrap.innerHTML = ""; tabsSlot.innerHTML = ""; tabsField.style.display = "none"; return; }
    productBadgeName.textContent = productSel.value;
    buildCategorySections();
    await loadMappings();
    await renderAllCategories();
  });

  async function saveRow(row) {
    const product = productSel.value;
    const ledgerId = row.querySelector(".mm-ledger-select").value;
    const effectiveFrom = row.querySelector(".mm-effective-from").value;
    if (!ledgerId || !effectiveFrom) {
      voyagerAlert("Pick a Ledger and an Effective From date before saving this field.");
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/master-mapping/save/`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company_id: activeCompanyId, product_type: product, masters_category: row.dataset.category,
          rows: [{ field_name: row.dataset.field, ledger_id: Number(ledgerId), effective_from: effectiveFrom }],
        }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error((data && data.error) || `Save failed: ${res.status}`);
    } catch (err) {
      console.error("Could not save Master Mapping", err);
      voyagerAlert(err.message || "Could not save. Is the Django backend running?", { icon: "error" });
      return;
    }
    await loadMappings();
    await renderCategoryRows(row.dataset.sectionKey);
  }

  categoriesWrap.addEventListener("click", async (e) => {
    const row = e.target.closest(".mm-field-row");
    if (!row) return;

    if (e.target.closest(".mm-row-save-btn")) {
      await saveRow(row);
      return;
    }
    if (e.target.closest(".mm-row-edit-btn")) {
      row.classList.remove("mm-locked");
      row.querySelector(".mm-ledger-select").disabled = false;
      row.querySelector(".mm-effective-from").disabled = false;
      row.querySelector(".dom-action-btn-group").innerHTML =
        `<button type="button" class="dom-action-btn btn-edit mm-row-save-btn" title="Save">${CHECK_ICON}</button>`;
      return;
    }
    if (e.target.closest(".mm-row-del-btn")) {
      const id = row.dataset.mappingId;
      if (id) {
        try {
          await fetch(`${API_BASE}/master-mapping/${id}/delete/?company_id=${activeCompanyId}`, { method: "DELETE" });
        } catch (err) {
          console.error("Could not delete Master Mapping row", err);
        }
      }
      await loadMappings();
      await renderCategoryRows(row.dataset.sectionKey);
      return;
    }
  });

  // ============================================================
  // Local cache of every saved mapping for the selected Product - used to
  // pre-fill/lock the field rows above; there's no separate list view, the
  // field rows ARE the record.
  // ============================================================
  async function loadMappings() {
    if (!activeCompanyId || !productSel.value) return;
    try {
      const res = await fetch(`${API_BASE}/master-mapping/?company_id=${activeCompanyId}&product_type=${encodeURIComponent(productSel.value)}`);
      if (!res.ok) throw new Error(`Master Mapping API returned ${res.status}`);
      allMappings = await res.json();
    } catch (err) {
      console.error("Could not load Master Mapping - is the Django backend running?", err);
      allMappings = [];
    }
  }

  let active = null;
  try {
    active = await VoyagerShell.init({
      activeKey: "master-mapping",
      onCompanyChange: (id) => { activeCompanyId = Number(id); },
    });
  } catch (err) {
    console.error("Shell init failed", err);
  }
  if (active) {
    activeCompanyId = Number(active.id);
  } else {
    voyagerAlert("Could not load the active company. Check your connection and reload the page.", { icon: "error" });
  }
})();
