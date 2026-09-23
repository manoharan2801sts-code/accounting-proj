(async function () {
  const { get } = window.VoyagerAPI;
  const { fmtMoney, fmtDate, statusPill, currencyFor } = window.VoyagerUtil;
  const { zoomInUrl } = window.VoyagerEntry;
  let dt;

  async function load(companyId, country) {
    const rows = await get(`/travel/visa?company_id=${companyId}`);
    const ccy = currencyFor(country);
    document.getElementById("row-count").textContent = `${rows.length} applications`;
    if (dt) dt.destroy();
    $("#data-table tbody").html(rows.map((v) => `
      <tr class="drillable" data-id="${v.id}" title="Click to view / correct this application">
        <td>${v.applicant_name}</td><td>${v.customer_name}</td><td>${v.destination_country}</td><td>${v.visa_type}</td>
        <td>${fmtDate(v.application_date)}</td>
        <td class="tabular-nums">${fmtMoney(v.supplier_fee, ccy)}</td>
        <td class="tabular-nums">${fmtMoney(v.customer_fee, ccy)}</td>
        <td class="tabular-nums" style="font-weight:700; color:var(--color-success);">${fmtMoney(v.service_charge, ccy)}</td>
        <td>${statusPill(v.status)}</td>
      </tr>`).join(""));
    dt = $("#data-table").DataTable({ pageLength: 10, order: [[4, "desc"]], language: { info: "Showing <b>_START_</b> to <b>_END_</b> of <b>_TOTAL_</b> entries", infoEmpty: "No entries to show", infoFiltered: "(filtered from <b>_MAX_</b> total entries)", search: "", searchPlaceholder: "Search…", paginate: { first: "«", previous: "‹", next: "›", last: "»" } } });
    $("#data-table tbody").off("click", "tr").on("click", "tr", function () {
      window.VoyagerShell.navigateTo(zoomInUrl("visa-entry.html", $(this).data("id"), "visa.html"));
    });
  }

  const active = await VoyagerShell.init({ activeKey: "visa", onCompanyChange: load });
  if (active) load(active.id, active.country);
})();
