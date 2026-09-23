(async function () {
  const { get } = window.VoyagerAPI;
  const { fmtMoney, fmtDate, statusPill, currencyFor } = window.VoyagerUtil;
  const { zoomInUrl } = window.VoyagerEntry;
  let dt;

  async function load(companyId, country) {
    const rows = await get(`/travel/tours?company_id=${companyId}`);
    const ccy = currencyFor(country);
    document.getElementById("row-count").textContent = `${rows.length} packages`;
    if (dt) dt.destroy();
    $("#data-table tbody").html(rows.map((t) => {
      const margin = t.total_revenue - t.total_cost;
      return `<tr class="drillable" data-id="${t.id}" title="Click to view / correct this package">
        <td style="font-weight:600;">${t.package_name}</td><td>${t.customer_name}</td>
        <td><span class="pill pill-neutral">${t.package_type}</span></td><td>${t.pax_count}</td>
        <td>${fmtDate(t.start_date)}</td><td>${fmtDate(t.end_date)}</td>
        <td class="tabular-nums">${fmtMoney(t.total_cost, ccy)}</td>
        <td class="tabular-nums">${fmtMoney(t.total_revenue, ccy)}</td>
        <td class="tabular-nums" style="font-weight:700; color:var(--color-success);">${fmtMoney(margin, ccy)}</td>
        <td>${statusPill(t.status)}</td>
      </tr>`;
    }).join(""));
    dt = $("#data-table").DataTable({ pageLength: 10, order: [[4, "desc"]], language: { info: "Showing <b>_START_</b> to <b>_END_</b> of <b>_TOTAL_</b> entries", infoEmpty: "No entries to show", infoFiltered: "(filtered from <b>_MAX_</b> total entries)", search: "", searchPlaceholder: "Search…", paginate: { first: "«", previous: "‹", next: "›", last: "»" } } });
    $("#data-table tbody").off("click", "tr").on("click", "tr", function () {
      window.VoyagerShell.navigateTo(zoomInUrl("tour-entry.html", $(this).data("id"), "tours.html"));
    });
  }

  const active = await VoyagerShell.init({ activeKey: "tours", onCompanyChange: load });
  if (active) load(active.id, active.country);
})();
