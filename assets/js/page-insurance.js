(async function () {
  const { get } = window.VoyagerAPI;
  const { fmtMoney, fmtDate, statusPill, currencyFor } = window.VoyagerUtil;
  const { zoomInUrl } = window.VoyagerEntry;
  let dt;

  async function load(companyId, country) {
    const rows = await get(`/travel/insurance?company_id=${companyId}`);
    const ccy = currencyFor(country);
    document.getElementById("row-count").textContent = `${rows.length} policies`;
    if (dt) dt.destroy();
    $("#data-table tbody").html(rows.map((p) => `
      <tr class="drillable" data-id="${p.id}" title="Click to view / correct this policy">
        <td style="font-family:var(--font-mono);">${p.policy_no}</td><td>${p.insured_name}</td><td>${p.customer_name}</td><td>${p.supplier_name}</td>
        <td>${fmtDate(p.policy_start)}</td><td>${fmtDate(p.policy_end)}</td>
        <td class="tabular-nums">${fmtMoney(p.premium_cost, ccy)}</td>
        <td class="tabular-nums">${fmtMoney(p.premium_billed, ccy)}</td>
        <td>${statusPill(p.status)}</td>
      </tr>`).join(""));
    dt = $("#data-table").DataTable({ pageLength: 10, order: [[4, "desc"]], language: { info: "Showing <b>_START_</b> to <b>_END_</b> of <b>_TOTAL_</b> entries", infoEmpty: "No entries to show", infoFiltered: "(filtered from <b>_MAX_</b> total entries)", search: "", searchPlaceholder: "Search…", paginate: { first: "«", previous: "‹", next: "›", last: "»" } } });
    $("#data-table tbody").off("click", "tr").on("click", "tr", function () {
      window.VoyagerShell.navigateTo(zoomInUrl("insurance-entry.html", $(this).data("id"), "insurance.html"));
    });
  }

  const active = await VoyagerShell.init({ activeKey: "insurance", onCompanyChange: load });
  if (active) load(active.id, active.country);
})();
