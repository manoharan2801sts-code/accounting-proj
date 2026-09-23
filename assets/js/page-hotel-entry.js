(async function () {
  const { fillSelect, todayISO, saveRecord, getEditId, getReturnTo } = window.VoyagerEntry;
  let activeCompanyId, activeCountry;
  const editId = getEditId();
  const returnTo = getReturnTo("hotels.html");
  document.getElementById("cancel-link").href = returnTo;

  function recalc() {
    const cost = parseFloat(document.getElementById("supplier_cost").value) || 0;
    const billing = parseFloat(document.getElementById("customer_billing").value) || 0;
    const ccy = activeCountry === "AE" ? "AED" : "INR";
    document.getElementById("profit").textContent = `${ccy} ${(billing - cost).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function nights() {
    const ci = new Date(document.getElementById("check_in").value);
    const co = new Date(document.getElementById("check_out").value);
    const diff = Math.round((co - ci) / (1000 * 60 * 60 * 24));
    return diff > 0 ? diff : 1;
  }

  function populateRefs(companyId) {
    const ref = window.VoyagerMock.getReferenceData(companyId);
    fillSelect(document.getElementById("branch"), ref.branches, (b) => b.name, (b) => b.name);
    fillSelect(document.getElementById("customer"), ref.customers, (c) => c.name, (c) => `${c.name} (${c.code})`);
    fillSelect(document.getElementById("supplier"), ref.suppliers, (s) => s.name, (s) => `${s.name} (${window.VoyagerUtil.titleCaseLabel(s.supplier_type)})`);
    fillSelect(document.getElementById("hotel_name"), ref.hotels, (h) => h, (h) => h);
  }

  function prefill(h) {
    document.getElementById("page-title").textContent = `Edit Hotel Booking — ${h.guest_name}`;
    document.getElementById("submit-btn").textContent = "Update Booking";
    document.getElementById("branch").value = h.branch_name;
    document.getElementById("customer").value = h.customer_name;
    document.getElementById("supplier").value = h.supplier_name;
    document.getElementById("hotel_name").value = h.hotel_name;
    document.getElementById("guest_name").value = h.guest_name;
    document.getElementById("status").value = h.status;
    document.getElementById("check_in").value = h.check_in;
    document.getElementById("check_out").value = h.check_out;
    document.getElementById("rooms").value = h.rooms;
    document.getElementById("supplier_cost").value = h.supplier_cost;
    document.getElementById("customer_billing").value = h.customer_billing;
    recalc();
  }

  if (!editId) {
    const today = todayISO();
    document.getElementById("check_in").value = today;
    const co = new Date(); co.setDate(co.getDate() + 3);
    document.getElementById("check_out").value = co.toISOString().slice(0, 10);
  }
  document.querySelectorAll(".calc").forEach((el) => el.addEventListener("input", recalc));

  document.getElementById("hotel-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const supplier_cost = parseFloat(document.getElementById("supplier_cost").value) || 0;
    const customer_billing = parseFloat(document.getElementById("customer_billing").value) || 0;
    const payload = {
      branch_name: document.getElementById("branch").value,
      customer_name: document.getElementById("customer").value,
      supplier_name: document.getElementById("supplier").value,
      hotel_name: document.getElementById("hotel_name").value,
      guest_name: document.getElementById("guest_name").value,
      check_in: document.getElementById("check_in").value,
      check_out: document.getElementById("check_out").value,
      nights: nights(),
      rooms: parseInt(document.getElementById("rooms").value) || 1,
      supplier_cost, customer_billing, status: document.getElementById("status").value,
    };
    await saveRecord({
      mockAdd: window.VoyagerMock.addHotel, mockUpdate: window.VoyagerMock.updateHotel,
      apiPath: "/travel/hotels", companyId: activeCompanyId, editId,
      payload, successMessage: editId ? "Hotel booking updated." : "Hotel booking saved — GL entry posted.", redirectTo: returnTo,
    });
  });

  const active = await VoyagerShell.init({
    activeKey: "hotels",
    onCompanyChange: (id, country) => { activeCompanyId = Number(id); activeCountry = country; populateRefs(activeCompanyId); },
  });
  if (active) {
    activeCompanyId = Number(active.id); activeCountry = active.country;
    populateRefs(activeCompanyId);
    if (editId) {
      const h = await window.VoyagerAPI.get(`/travel/hotels/${editId}`);
      prefill(h);
    } else {
      recalc();
    }
  }
})();
