(async function () {
  const { get } = window.VoyagerAPI;
  const { fmtMoney, currencyFor, titleCaseLabel } = window.VoyagerUtil;
  let dt;

  async function load(companyId, country) {
    const rows = await get(`/parties/suppliers/?company_id=${companyId}`);
    const ccy = currencyFor(country);
    document.getElementById("row-count").textContent = `${rows.length} suppliers`;
    if (dt) dt.destroy();
    $("#data-table tbody").html(rows.map((s) => `
      <tr class="drillable" data-name="${s.name}" title="Click to view this supplier's transactions">
        <td>${s.code}</td><td style="font-weight:600;">${s.name}</td><td><span class="pill pill-neutral">${titleCaseLabel(s.supplier_type)}</span></td>
        <td>${s.credit_days} days</td>
        <td class="tabular-nums" style="font-weight:700;">${fmtMoney(s.outstanding, ccy)}</td>
      </tr>`).join(""));
    dt = $("#data-table").DataTable({ pageLength: 10, order: [[4, "desc"]], language: { info: "Showing <b>_START_</b> to <b>_END_</b> of <b>_TOTAL_</b> entries", infoEmpty: "No entries to show", infoFiltered: "(filtered from <b>_MAX_</b> total entries)", search: "", searchPlaceholder: "Search…", paginate: { first: "«", previous: "‹", next: "›", last: "»" } } });
    $("#data-table tbody").off("click", "tr").on("click", "tr", function () {
      VoyagerDrilldown.bySupplier($(this).data("name"), companyId, ccy);
    });
  }

  const active = await VoyagerShell.init({ activeKey: "suppliers", onCompanyChange: load });
  if (active) load(active.id, active.country);
})();
