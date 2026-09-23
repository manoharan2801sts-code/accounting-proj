(async function () {
  const { fillSelect, todayISO, saveRecord, getEditId, getReturnTo } = window.VoyagerEntry;
  let activeCompanyId;
  const editId = getEditId();
  const returnTo = getReturnTo("insurance.html");
  document.getElementById("cancel-link").href = returnTo;

  function populateRefs(companyId) {
    const ref = window.VoyagerMock.getReferenceData(companyId);
    fillSelect(document.getElementById("branch"), ref.branches, (b) => b.name, (b) => b.name);
    fillSelect(document.getElementById("customer"), ref.customers, (c) => c.name, (c) => `${c.name} (${c.code})`);
    fillSelect(document.getElementById("supplier"), ref.suppliers, (s) => s.name, (s) => `${s.name} (${window.VoyagerUtil.titleCaseLabel(s.supplier_type)})`);
  }

  function prefill(p) {
    document.getElementById("page-title").textContent = `Edit Insurance Policy — ${p.policy_no}`;
    document.getElementById("submit-btn").textContent = "Update Policy";
    document.getElementById("branch").value = p.branch_name;
    document.getElementById("customer").value = p.customer_name;
    document.getElementById("supplier").value = p.supplier_name;
    document.getElementById("policy_no").value = p.policy_no;
    document.getElementById("insured_name").value = p.insured_name;
    document.getElementById("status").value = p.status;
    document.getElementById("policy_start").value = p.policy_start;
    document.getElementById("policy_end").value = p.policy_end;
    document.getElementById("premium_cost").value = p.premium_cost;
    document.getElementById("premium_billed").value = p.premium_billed;
  }

  if (!editId) {
    document.getElementById("policy_start").value = todayISO();
    const end = new Date(); end.setDate(end.getDate() + 365);
    document.getElementById("policy_end").value = end.toISOString().slice(0, 10);
    document.getElementById("policy_no").value = `POL-${Date.now().toString().slice(-8)}`;
  }

  document.getElementById("insurance-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      branch_name: document.getElementById("branch").value,
      customer_name: document.getElementById("customer").value,
      supplier_name: document.getElementById("supplier").value,
      policy_no: document.getElementById("policy_no").value,
      insured_name: document.getElementById("insured_name").value,
      policy_start: document.getElementById("policy_start").value,
      policy_end: document.getElementById("policy_end").value,
      premium_cost: parseFloat(document.getElementById("premium_cost").value) || 0,
      premium_billed: parseFloat(document.getElementById("premium_billed").value) || 0,
      status: document.getElementById("status").value,
    };
    await saveRecord({
      mockAdd: window.VoyagerMock.addInsurance, mockUpdate: window.VoyagerMock.updateInsurance,
      apiPath: "/travel/insurance", companyId: activeCompanyId, editId,
      payload, successMessage: editId ? "Insurance policy updated." : "Insurance policy saved.", redirectTo: returnTo,
    });
  });

  const active = await VoyagerShell.init({
    activeKey: "insurance",
    onCompanyChange: (id) => { activeCompanyId = Number(id); populateRefs(activeCompanyId); },
  });
  if (active) {
    activeCompanyId = Number(active.id);
    populateRefs(activeCompanyId);
    if (editId) {
      const p = await window.VoyagerAPI.get(`/travel/insurance/${editId}`);
      prefill(p);
    }
  }
})();
