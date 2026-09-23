(async function () {
  const { fillSelect, todayISO, saveRecord, getEditId, getReturnTo } = window.VoyagerEntry;
  let activeCompanyId, activeCountry;
  const editId = getEditId();
  const returnTo = getReturnTo("tours.html");
  document.getElementById("cancel-link").href = returnTo;

  function recalc() {
    const cost = parseFloat(document.getElementById("total_cost").value) || 0;
    const rev = parseFloat(document.getElementById("total_revenue").value) || 0;
    const ccy = activeCountry === "AE" ? "AED" : "INR";
    document.getElementById("margin").textContent = `${ccy} ${(rev - cost).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function populateRefs(companyId) {
    const ref = window.VoyagerMock.getReferenceData(companyId);
    fillSelect(document.getElementById("branch"), ref.branches, (b) => b.name, (b) => b.name);
    fillSelect(document.getElementById("customer"), ref.customers, (c) => c.name, (c) => `${c.name} (${c.code})`);
  }

  function prefill(t) {
    document.getElementById("page-title").textContent = `Edit Tour Package — ${t.package_name}`;
    document.getElementById("submit-btn").textContent = "Update Package";
    document.getElementById("branch").value = t.branch_name;
    document.getElementById("customer").value = t.customer_name;
    document.getElementById("package_name").value = t.package_name;
    document.getElementById("package_type").value = t.package_type;
    document.getElementById("pax_count").value = t.pax_count;
    document.getElementById("start_date").value = t.start_date;
    document.getElementById("end_date").value = t.end_date;
    document.getElementById("status").value = t.status;
    document.getElementById("total_cost").value = t.total_cost;
    document.getElementById("total_revenue").value = t.total_revenue;
    recalc();
  }

  if (!editId) {
    document.getElementById("start_date").value = todayISO();
    const end = new Date(); end.setDate(end.getDate() + 6);
    document.getElementById("end_date").value = end.toISOString().slice(0, 10);
  }
  document.querySelectorAll(".calc").forEach((el) => el.addEventListener("input", recalc));

  document.getElementById("tour-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      branch_name: document.getElementById("branch").value,
      customer_name: document.getElementById("customer").value,
      package_name: document.getElementById("package_name").value,
      package_type: document.getElementById("package_type").value,
      pax_count: parseInt(document.getElementById("pax_count").value) || 1,
      start_date: document.getElementById("start_date").value,
      end_date: document.getElementById("end_date").value,
      total_cost: parseFloat(document.getElementById("total_cost").value) || 0,
      total_revenue: parseFloat(document.getElementById("total_revenue").value) || 0,
      status: document.getElementById("status").value,
    };
    await saveRecord({
      mockAdd: window.VoyagerMock.addTour, mockUpdate: window.VoyagerMock.updateTour,
      apiPath: "/travel/tours", companyId: activeCompanyId, editId,
      payload, successMessage: editId ? "Tour package updated." : "Tour package saved.", redirectTo: returnTo,
    });
  });

  const active = await VoyagerShell.init({
    activeKey: "tours",
    onCompanyChange: (id, country) => { activeCompanyId = Number(id); activeCountry = country; populateRefs(activeCompanyId); },
  });
  if (active) {
    activeCompanyId = Number(active.id); activeCountry = active.country;
    populateRefs(activeCompanyId);
    if (editId) {
      const t = await window.VoyagerAPI.get(`/travel/tours/${editId}`);
      prefill(t);
    } else {
      recalc();
    }
  }
})();
