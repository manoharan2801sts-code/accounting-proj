(async function () {
  const { fillSelect, todayISO, saveRecord, getEditId, getReturnTo } = window.VoyagerEntry;
  let activeCompanyId, activeCountry;
  const editId = getEditId();
  const returnTo = getReturnTo("visa.html");
  document.getElementById("cancel-link").href = returnTo;

  function recalc() {
    const sf = parseFloat(document.getElementById("supplier_fee").value) || 0;
    const cf = parseFloat(document.getElementById("customer_fee").value) || 0;
    const ccy = activeCountry === "AE" ? "AED" : "INR";
    document.getElementById("service_charge").textContent = `${ccy} ${(cf - sf).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function populateRefs(companyId) {
    const ref = window.VoyagerMock.getReferenceData(companyId);
    fillSelect(document.getElementById("branch"), ref.branches, (b) => b.name, (b) => b.name);
    fillSelect(document.getElementById("customer"), ref.customers, (c) => c.name, (c) => `${c.name} (${c.code})`);
  }

  function prefill(v) {
    document.getElementById("page-title").textContent = `Edit Visa Application — ${v.applicant_name}`;
    document.getElementById("submit-btn").textContent = "Update Application";
    document.getElementById("branch").value = v.branch_name;
    document.getElementById("customer").value = v.customer_name;
    document.getElementById("applicant_name").value = v.applicant_name;
    document.getElementById("destination_country").value = v.destination_country;
    document.getElementById("visa_type").value = v.visa_type;
    document.getElementById("application_date").value = v.application_date;
    document.getElementById("status").value = v.status;
    document.getElementById("supplier_fee").value = v.supplier_fee;
    document.getElementById("customer_fee").value = v.customer_fee;
    recalc();
  }

  if (!editId) document.getElementById("application_date").value = todayISO();
  document.querySelectorAll(".calc").forEach((el) => el.addEventListener("input", recalc));

  document.getElementById("visa-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const supplier_fee = parseFloat(document.getElementById("supplier_fee").value) || 0;
    const customer_fee = parseFloat(document.getElementById("customer_fee").value) || 0;
    const payload = {
      branch_name: document.getElementById("branch").value,
      customer_name: document.getElementById("customer").value,
      applicant_name: document.getElementById("applicant_name").value,
      destination_country: document.getElementById("destination_country").value,
      visa_type: document.getElementById("visa_type").value,
      application_date: document.getElementById("application_date").value,
      supplier_fee, customer_fee, service_charge: customer_fee - supplier_fee,
      status: document.getElementById("status").value,
    };
    await saveRecord({
      mockAdd: window.VoyagerMock.addVisa, mockUpdate: window.VoyagerMock.updateVisa,
      apiPath: "/travel/visa", companyId: activeCompanyId, editId,
      payload, successMessage: editId ? "Visa application updated." : "Visa application saved.", redirectTo: returnTo,
    });
  });

  const active = await VoyagerShell.init({
    activeKey: "visa",
    onCompanyChange: (id, country) => { activeCompanyId = Number(id); activeCountry = country; populateRefs(activeCompanyId); },
  });
  if (active) {
    activeCompanyId = Number(active.id); activeCountry = active.country;
    populateRefs(activeCompanyId);
    if (editId) {
      const v = await window.VoyagerAPI.get(`/travel/visa/${editId}`);
      prefill(v);
    } else {
      recalc();
    }
  }
})();
