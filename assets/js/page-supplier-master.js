(async function () {
  const API_BASE = window.API_BASE || "/api";
  const OPT = window.VoyagerHardcode.TICKET_FORM_OPTIONS;
  let activeCompanyId, allSuppliers = [];

  // Office ID: loaded from Sundry Creditors (suppliers) for the active
  // company; picking/typing a matching Office ID auto-fills Supplier Name.
  const SUPPLIERS_API = `${API_BASE}/suppliers/`;
  async function populateSuppliers(companyId) {
    try {
      const res = await fetch(`${SUPPLIERS_API}?company_id=${companyId}`);
      if (!res.ok) throw new Error(`Suppliers API returned ${res.status}`);
      allSuppliers = await res.json();
    } catch (err) {
      console.error("Could not load suppliers (Sundry Creditors) from the Django API - is it running on localhost:8000?", err);
      allSuppliers = [];
    }
    document.getElementById("sm-office-id-options").innerHTML = allSuppliers
      .filter((s) => s.office_id)
      .map((s) => `<option value="${s.office_id}">`).join("");
  }

  // ============================================================
  // Commission Rules table - per-row Travel Type / Airline Category /
  // Cabin / Fare Type / Calculation Type criteria, each row an independent
  // commission rule. Client-side only for now (no backend table yet).
  // ============================================================
  const ruleTbody = document.getElementById("sm-rule-tbody");

  function ruleSelectHtml(cls, values, placeholder) {
    return `<select class="form-control-custom ${cls}">` +
      (placeholder ? `<option value="">${placeholder}</option>` : "") +
      values.map((v) => `<option value="${v}">${v}</option>`).join("") + "</select>";
  }

  const CHECK_ICON = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>`;

  // Always exactly one entry row - built once, reused (cleared/refilled)
  // rather than multiplying as rows get saved.
  const entryRow = document.createElement("tr");
  entryRow.innerHTML = `
    <td><input class="form-control-custom" value="Commission" readonly disabled /></td>
    <td><input class="form-control-custom sm-rule-office" list="sm-office-id-options" placeholder="Office ID" autocomplete="off" /></td>
    <td><input class="form-control-custom sm-rule-supplier" readonly placeholder="Auto" /></td>
    <td>${ruleSelectHtml("sm-rule-travel-type", OPT.travelTypes, "Select...")}</td>
    <td>${ruleSelectHtml("sm-rule-airline-cat", OPT.airlineCategories, "Select...")}</td>
    <td>${ruleSelectHtml("sm-rule-cabin", OPT.cabinOptions, "Select...")}</td>
    <td>${ruleSelectHtml("sm-rule-fare-type", OPT.fareTypeOptions, "Select...")}</td>
    <td>${ruleSelectHtml("sm-rule-comm-on", OPT.custDiscountOn, "Select...")}</td>
    <td>${ruleSelectHtml("sm-rule-calc-type", OPT.custDiscountTypes, "Select...")}</td>
    <td>
      <input class="form-control-custom sm-rule-calc-pct" type="number" min="0" max="100" step="0.01" value="0.00" style="display:none;" />
      <input class="form-control-custom sm-rule-flat-amt" type="number" min="0" step="0.01" value="0.00" style="display:none;" />
    </td>
    <td><input class="form-control-custom sm-rule-valid-upto" type="date" /></td>
    <td>
      <div class="dom-action-btn-group">
        <button type="button" class="dom-action-btn btn-edit sm-rule-save-btn" title="Save">${CHECK_ICON}</button>
      </div>
    </td>
  `;
  ruleTbody.appendChild(entryRow);

  function readEntryRow() {
    return {
      office_id: entryRow.querySelector(".sm-rule-office").value.trim(),
      supplier: entryRow.querySelector(".sm-rule-supplier").value,
      travel_type: entryRow.querySelector(".sm-rule-travel-type").value,
      airline_category: entryRow.querySelector(".sm-rule-airline-cat").value,
      cabin: entryRow.querySelector(".sm-rule-cabin").value,
      fare_type: entryRow.querySelector(".sm-rule-fare-type").value,
      comm_on: entryRow.querySelector(".sm-rule-comm-on").value,
      calc_type: entryRow.querySelector(".sm-rule-calc-type").value,
      calc_pct: entryRow.querySelector(".sm-rule-calc-pct").value,
      flat_amt: entryRow.querySelector(".sm-rule-flat-amt").value,
      valid_upto: entryRow.querySelector(".sm-rule-valid-upto").value,
    };
  }
  // The "Calculation Value" column header text tracks whichever type is
  // currently selected - "% of Calculation" for Percentage, "Flat Amount"
  // for Flat (defaults back to "% of Calculation" while nothing's picked).
  const calcValueHeader = document.getElementById("sm-rule-calc-value-header");
  function updateCalcValueHeader(calcType) {
    calcValueHeader.textContent = calcType === "Flat" ? "Flat Amount" : "% of Calculation";
  }
  function writeEntryRow(data) {
    entryRow.querySelector(".sm-rule-office").value = data.office_id;
    entryRow.querySelector(".sm-rule-supplier").value = data.supplier;
    entryRow.querySelector(".sm-rule-travel-type").value = data.travel_type;
    entryRow.querySelector(".sm-rule-airline-cat").value = data.airline_category;
    entryRow.querySelector(".sm-rule-cabin").value = data.cabin;
    entryRow.querySelector(".sm-rule-fare-type").value = data.fare_type;
    entryRow.querySelector(".sm-rule-comm-on").value = data.comm_on;
    entryRow.querySelector(".sm-rule-calc-type").value = data.calc_type;
    entryRow.querySelector(".sm-rule-calc-pct").value = data.calc_pct;
    entryRow.querySelector(".sm-rule-flat-amt").value = data.flat_amt;
    entryRow.querySelector(".sm-rule-valid-upto").value = data.valid_upto;
    const isPct = data.calc_type === "Percentage";
    entryRow.querySelector(".sm-rule-calc-pct").style.display = isPct ? "" : "none";
    entryRow.querySelector(".sm-rule-flat-amt").style.display = isPct ? "none" : "";
    updateCalcValueHeader(data.calc_type);
  }
  function clearEntryRow() {
    writeEntryRow({
      office_id: "", supplier: "", travel_type: "", airline_category: "", cabin: "", fare_type: "", comm_on: "",
      calc_type: "", calc_pct: "0.00", flat_amt: "0.00", valid_upto: "",
    });
  }

  // ============================================================
  // Supplier Commission List - saved rules persist to the real backend
  // (SupplierCommissionRule table) so the New Ticket modal can look them
  // up by Office ID. `savedRules` is a local cache of the last GET, kept
  // in sync after every create/delete.
  // ============================================================
  const RULES_API = `${API_BASE}/supplier-commission-rules/`;
  const listTbody = document.getElementById("sm-list-tbody");
  const emptyRow = document.getElementById("sm-list-empty-row");
  let savedRules = [];

  async function loadRules() {
    if (!activeCompanyId) return;
    try {
      const res = await fetch(`${RULES_API}?company_id=${activeCompanyId}`);
      if (!res.ok) throw new Error(`Supplier commission rules API returned ${res.status}`);
      savedRules = await res.json();
    } catch (err) {
      console.error("Could not load supplier commission rules - is the Django backend running?", err);
      savedRules = [];
    }
    renderList();
  }

  function renderList() {
    listTbody.querySelectorAll("tr:not(#sm-list-empty-row)").forEach((tr) => tr.remove());
    emptyRow.style.display = savedRules.length ? "none" : "";
    savedRules.forEach((r) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>Commission</td><td>${r.office_id}</td><td>${r.supplier_name || ""}</td>
        <td>${r.travel_type || ""}</td><td>${r.airline_category || ""}</td><td>${r.cabin || ""}</td><td>${r.fare_type || ""}</td>
        <td>${r.comm_on || ""}</td>
        <td>${r.calc_type || ""}</td>
        <td class="num">${r.calc_type === "Flat" ? r.flat_amt : r.calc_pct}${r.calc_type === "Percentage" ? "%" : ""}</td>
        <td>${r.valid_upto || ""}</td>
        <td>
          <div class="dom-action-btn-group">
            <button type="button" class="dom-action-btn btn-edit sm-list-edit-btn" data-id="${r.id}">Edit</button>
            <button type="button" class="dom-action-btn btn-delete sm-list-del-btn" data-id="${r.id}">Del</button>
          </div>
        </td>
      `;
      listTbody.appendChild(tr);
    });
  }
  listTbody.addEventListener("click", async (e) => {
    const id = Number(e.target.dataset.id);
    if (e.target.matches(".sm-list-edit-btn")) {
      const record = savedRules.find((r) => r.id === id);
      if (!record) return;
      writeEntryRow({
        office_id: record.office_id, supplier: record.supplier_name || "",
        travel_type: record.travel_type || "", airline_category: record.airline_category || "",
        cabin: record.cabin || "", fare_type: record.fare_type || "", comm_on: record.comm_on || "",
        calc_type: record.calc_type || "",
        calc_pct: record.calc_pct, flat_amt: record.flat_amt, valid_upto: record.valid_upto || "",
      });
      // Editing removes it from the saved list - the next Save re-creates it.
      try { await fetch(`${RULES_API}${id}/delete/?company_id=${activeCompanyId}`, { method: "DELETE" }); } catch (_) {}
      await loadRules();
    } else if (e.target.matches(".sm-list-del-btn")) {
      try {
        await fetch(`${RULES_API}${id}/delete/?company_id=${activeCompanyId}`, { method: "DELETE" });
      } catch (err) {
        console.error("Could not delete supplier commission rule", err);
      }
      await loadRules();
    }
  });

  // Event delegation on the single entry row.
  ruleTbody.addEventListener("input", (e) => {
    if (e.target.matches(".sm-rule-office")) {
      const s = allSuppliers.find((s) => s.office_id === e.target.value);
      entryRow.querySelector(".sm-rule-supplier").value = s ? s.name : "";
    }
    if (e.target.matches(".sm-rule-calc-pct") && parseFloat(e.target.value) > 100) {
      e.target.value = "100";
    }
  });
  ruleTbody.addEventListener("change", (e) => {
    if (e.target.matches(".sm-rule-calc-type")) {
      const isPct = e.target.value === "Percentage";
      entryRow.querySelector(".sm-rule-calc-pct").style.display = isPct ? "" : "none";
      entryRow.querySelector(".sm-rule-flat-amt").style.display = isPct ? "none" : "";
      updateCalcValueHeader(e.target.value);
    }
  });
  ruleTbody.addEventListener("click", async (e) => {
    if (e.target.closest(".sm-rule-save-btn")) {
      const data = readEntryRow();
      if (!data.office_id) {
        voyagerAlert("Enter an Office ID before saving this rule.");
        return;
      }
      try {
        const res = await fetch(`${RULES_API}create/`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            company_id: activeCompanyId, office_id: data.office_id, supplier_name: data.supplier,
            travel_type: data.travel_type, airline_category: data.airline_category,
            cabin: data.cabin, fare_type: data.fare_type, comm_on: data.comm_on, calc_type: data.calc_type,
            calc_pct: data.calc_pct, flat_amt: data.flat_amt, valid_upto: data.valid_upto,
          }),
        });
        if (!res.ok) throw new Error(`Create failed: ${res.status}`);
      } catch (err) {
        console.error("Could not save supplier commission rule - is the Django backend running?", err);
        voyagerAlert("Could not save this rule. Is the Django backend running?", { icon: "error" });
        return;
      }
      await loadRules();
      clearEntryRow();
    }
  });

  const active = await VoyagerShell.init({
    activeKey: "supplier-master",
    onCompanyChange: (id) => {
      activeCompanyId = Number(id);
      populateSuppliers(activeCompanyId);
      loadRules();
    },
  });
  if (active) {
    activeCompanyId = Number(active.id);
    await populateSuppliers(activeCompanyId);
    await loadRules();
  }
})();
