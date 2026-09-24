(async function () {
  const API_BASE = window.API_BASE || "/api";
  let activeCompanyId;
  let allMappings = []; // local cache of the last GET for the selected Product
  const ledgerCache = {}; // group_name -> [{id,name}, ...]

  const PRODUCT_TYPES = ["Airline", "Hotel", "Bus", "Visa", "Insurance", "Rail"];
  const MASTERS_CATEGORIES = [
    "Earnings From Customer", "Earnings From Supplier", "Expenditure To Customer",
    "Expenditure To Supplier", "GST and TDS",
  ];
  // Masters category -> its fields, each loaded from a specific Ledger Group.
  const FIELD_DEFS = {
    "Earnings From Customer": [
      { field: "Markup A/c", group: "Incomes" },
      { field: "Addl Markup A/c", group: "Incomes" },
      { field: "SSR Markup A/c", group: "Incomes" },
      { field: "Service Fee A/c", group: "Incomes" },
      { field: "Addl Service Fee A/c", group: "Incomes" },
      { field: "SSR Service Fee A/c", group: "Incomes" },
    ],
    "Earnings From Supplier": [
      { field: "Commission A/c", group: "Incomes" },
    ],
    "Expenditure To Customer": [
      { field: "Discount A/c", group: "Expenses" },
    ],
    "Expenditure To Supplier": [
      { field: "Supplier Markup A/c", group: "Expenses" },
      { field: "Supplier Addl Markup A/c", group: "Expenses" },
      { field: "Supplier Service Fee A/c", group: "Expenses" },
      { field: "Supplier Addl Service Fee A/c", group: "Expenses" },
    ],
    "GST and TDS": [
      { field: "Output IGST A/c", group: "Duties and Taxes" },
      { field: "Output CGST A/c", group: "Duties and Taxes" },
      { field: "Output SGST A/c", group: "Duties and Taxes" },
      { field: "Discount TDS A/c", group: "Duties and Taxes" },
      { field: "Commission TDS A/c", group: "Duties and Taxes" },
      { field: "Input IGST A/c", group: "Duties and Taxes" },
      { field: "Input CGST A/c", group: "Duties and Taxes" },
      { field: "Input SGST A/c", group: "Duties and Taxes" },
    ],
  };
  const categorySlug = (category) => category.toLowerCase().replace(/[^a-z]+/g, "-");

  // The 5 real Masters categories (unchanged - still what gets saved as
  // masters_category on the backend) are grouped into just 3 tabs for
  // display: Customer, Supplier, GST and TDS.
  const TAB_GROUPS = [
    { key: "customer", label: "Customer", categories: ["Earnings From Customer", "Expenditure To Customer"] },
    { key: "supplier", label: "Supplier", categories: ["Expenditure To Supplier", "Earnings From Supplier"] },
    { key: "gst-and-tds", label: "GST and TDS", categories: ["GST and TDS"] },
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
    // redundant. Categories folded into one tab (e.g. the Customer tab
    // holds both "Earnings From Customer" and "Expenditure To Customer")
    // still share one <table>/<thead>, just a separate <tbody> each.
    categoriesWrap.innerHTML = TAB_GROUPS.map((tab, i) => {
      return `
      <div class="mm-tab-panel ${i === 0 ? "active" : ""}" data-tab-panel="${tab.key}">
        <div class="mm-table-card">
          <table class="mm-table">
            <thead><tr>
              <th>Field Name</th><th>Ledger Name (Master)</th><th>Effective From Date</th><th>Action</th>
            </tr></thead>
            ${tab.categories.map((category) => `<tbody id="mm-fields-tbody-${categorySlug(category)}"></tbody>`).join("")}
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

  async function renderCategoryRows(category) {
    const product = productSel.value;
    const tbody = document.getElementById(`mm-fields-tbody-${categorySlug(category)}`);
    tbody.innerHTML = "";
    if (!product) return;

    const defs = FIELD_DEFS[category] || [];
    for (const def of defs) {
      const ledgers = await ledgersForGroup(def.group);
      const existing = existingMapping(product, def.field);
      const locked = !!existing;
      const row = document.createElement("tr");
      row.className = "mm-field-row" + (locked ? " mm-locked" : "");
      row.dataset.category = category;
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
    for (const category of MASTERS_CATEGORIES) {
      await renderCategoryRows(category);
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
    await renderCategoryRows(row.dataset.category);
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
      await renderCategoryRows(row.dataset.category);
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

  const active = await VoyagerShell.init({
    activeKey: "master-mapping",
    onCompanyChange: (id) => { activeCompanyId = Number(id); },
  });
  if (active) {
    activeCompanyId = Number(active.id);
  }
})();
