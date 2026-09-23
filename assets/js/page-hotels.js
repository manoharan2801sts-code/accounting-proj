(async function () {
  const { get } = window.VoyagerAPI;
  const { fmtMoney, fmtDate, statusPill, currencyFor } = window.VoyagerUtil;
  const { zoomInUrl } = window.VoyagerEntry;
  let dt;

  async function load(companyId, country) {
    const rows = await get(`/travel/hotels?company_id=${companyId}`);
    const ccy = currencyFor(country);
    document.getElementById("row-count").textContent = `${rows.length} bookings`;
    if (dt) dt.destroy();
    $("#data-table tbody").html(rows.map((h) => {
      const profit = h.customer_billing - h.supplier_cost;
      return `<tr class="drillable" data-id="${h.id}" title="Click to view / correct this booking">
        <td>${h.hotel_name}</td><td>${h.guest_name}</td><td>${h.customer_name}</td><td>${h.supplier_name}</td>
        <td>${fmtDate(h.check_in)}</td><td>${h.nights}</td>
        <td class="tabular-nums">${fmtMoney(h.supplier_cost, ccy)}</td>
        <td class="tabular-nums">${fmtMoney(h.customer_billing, ccy)}</td>
        <td class="tabular-nums" style="font-weight:700; color:var(--color-success);">${fmtMoney(profit, ccy)}</td>
        <td>${statusPill(h.status)}</td>
      </tr>`;
    }).join(""));
    dt = $("#data-table").DataTable({ pageLength: 10, order: [[4, "desc"]], language: { info: "Showing <b>_START_</b> to <b>_END_</b> of <b>_TOTAL_</b> entries", infoEmpty: "No entries to show", infoFiltered: "(filtered from <b>_MAX_</b> total entries)", search: "", searchPlaceholder: "Search…", paginate: { first: "«", previous: "‹", next: "›", last: "»" } } });
    $("#data-table tbody").off("click", "tr").on("click", "tr", function () {
      window.VoyagerShell.navigateTo(zoomInUrl("hotel-entry.html", $(this).data("id"), "hotels.html"));
    });
  }

  const active = await VoyagerShell.init({ activeKey: "hotels", onCompanyChange: load });
  if (active) load(active.id, active.country);
})();
