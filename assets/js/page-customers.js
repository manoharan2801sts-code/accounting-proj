(async function () {
  const { get } = window.VoyagerAPI;
  const { fmtMoney, currencyFor, titleCaseLabel } = window.VoyagerUtil;
  let dt;

  async function load(companyId, country) {
    const rows = await get(`/parties/customers?company_id=${companyId}`);
    const ccy = currencyFor(country);
    document.getElementById("row-count").textContent = `${rows.length} customers`;
    if (dt) dt.destroy();
    $("#data-table tbody").html(rows.map((c) => {
      const util = c.credit_limit > 0 ? Math.min(100, (c.outstanding / c.credit_limit) * 100) : 0;
      const tone = util > 90 ? "danger" : util > 60 ? "warning" : "success";
      return `<tr class="drillable" data-name="${c.name}" title="Click to view this customer's transactions">
        <td>${c.code}</td><td style="font-weight:600;">${c.name}</td><td><span class="pill pill-neutral">${titleCaseLabel(c.customer_type)}</span></td>
        <td class="tabular-nums">${c.credit_limit ? fmtMoney(c.credit_limit, ccy) : "—"}</td>
        <td>${c.credit_days} days</td>
        <td class="tabular-nums" style="font-weight:700;">${fmtMoney(c.outstanding, ccy)}</td>
        <td>${c.credit_limit ? `<span class="pill pill-${tone}">${util.toFixed(0)}%</span>` : "—"}</td>
      </tr>`;
    }).join(""));
    dt = $("#data-table").DataTable({ pageLength: 10, order: [[5, "desc"]], language: { info: "Showing <b>_START_</b> to <b>_END_</b> of <b>_TOTAL_</b> entries", infoEmpty: "No entries to show", infoFiltered: "(filtered from <b>_MAX_</b> total entries)", search: "", searchPlaceholder: "Search…", paginate: { first: "«", previous: "‹", next: "›", last: "»" } } });
    $("#data-table tbody").off("click", "tr").on("click", "tr", function () {
      VoyagerDrilldown.byCustomer($(this).data("name"), companyId, ccy);
    });
  }

  const active = await VoyagerShell.init({ activeKey: "customers", onCompanyChange: load });
  if (active) load(active.id, active.country);
})();
