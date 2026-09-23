/**
 * Voyager ERP - Drill-down modal
 * Every report screen can call VoyagerDrilldown.byLedger(...) / .byBranch(...)
 * to zoom from a summary line down to the actual vouchers behind it, then
 * expand any voucher to see its full debit/credit detail - Tally-style zoom.
 */
(function (window) {
  function ensureModal() {
    let modal = document.getElementById("drilldown-modal");
    if (modal) return modal;

    modal = document.createElement("div");
    modal.id = "drilldown-modal";
    modal.className = "dd-overlay";
    modal.innerHTML = `
      <div class="dd-panel">
        <div class="dd-header">
          <div>
            <div class="dd-title" id="dd-title"></div>
            <div class="dd-subtitle" id="dd-subtitle"></div>
          </div>
          <button type="button" class="dd-close" id="dd-close" aria-label="Close">&times;</button>
        </div>
        <div class="dd-body" id="dd-body"></div>
      </div>`;
    document.body.appendChild(modal);

    modal.addEventListener("click", (e) => { if (e.target === modal) close(); });
    document.getElementById("dd-close").addEventListener("click", close);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
    return modal;
  }

  function close() {
    const modal = document.getElementById("drilldown-modal");
    if (modal) modal.classList.remove("open");
  }

  function render(title, subtitle, vouchers, ccy) {
    const modal = ensureModal();
    const { fmtMoney, fmtDate, titleCaseLabel } = window.VoyagerUtil;
    const returnTo = window.location.pathname.split("/").pop() + window.location.search;

    document.getElementById("dd-title").textContent = title;
    document.getElementById("dd-subtitle").textContent = subtitle;
    document.getElementById("dd-body").innerHTML = vouchers.length
      ? vouchers.map((v, i) => `
        <div class="dd-voucher">
          <div class="dd-voucher-head" data-idx="${i}">
            <span class="dd-vno">${v.voucher_no}</span>
            <span class="pill pill-neutral">${titleCaseLabel(v.voucher_type)}</span>
            <span class="dd-date">${fmtDate(v.voucher_date)}</span>
            <span class="dd-narr">${v.narration || ""} <span class="text-muted-custom">- ${v.branch_name || ""}</span></span>
            <span class="dd-amt">${fmtMoney(v.total_debit, ccy)}</span>
            <a href="${window.VoyagerEntry.zoomInUrl("voucher-entry.html", v.id, returnTo)}" class="btn-outline-brand" style="padding:0.18rem 0.45rem; font-size:0.7rem; margin-left:0.5rem; flex-shrink:0;" onclick="event.stopPropagation()">Edit</a>
          </div>
          <div class="dd-lines" id="dd-lines-${i}">
            <table>
              <thead><tr><th>Account</th><th>Debit</th><th>Credit</th></tr></thead>
              <tbody>
                ${v.lines.map((l) => `<tr><td>${l.account_name}</td><td>${l.debit ? fmtMoney(l.debit, ccy) : ""}</td><td>${l.credit ? fmtMoney(l.credit, ccy) : ""}</td></tr>`).join("")}
              </tbody>
            </table>
          </div>
        </div>`).join("")
      : `<div class="dd-empty">No vouchers found for this line.</div>`;

    document.querySelectorAll(".dd-voucher-head").forEach((head) => {
      head.addEventListener("click", () => {
        document.getElementById(`dd-lines-${head.dataset.idx}`).classList.toggle("open");
      });
    });

    modal.classList.add("open");
  }

  function byLedger(accountName, companyId, ccy) {
    if (!window.VoyagerAPI.Store.isMockMode()) {
      voyagerAlert("Drill-down works in Demo Mode (sample data). Connected to a real backend, this would call a filtered vouchers API - not built in this preview.", { icon: "info" });
      return;
    }
    const vouchers = window.VoyagerMock.getVouchersForAccount(companyId, accountName);
    render(accountName, `${vouchers.length} voucher(s) posted to this ledger - click a row to view its debit/credit lines`, vouchers, ccy);
  }

  function byBranch(branchName, companyId, ccy) {
    if (!window.VoyagerAPI.Store.isMockMode()) {
      voyagerAlert("Drill-down works in Demo Mode (sample data). Connected to a real backend, this would call a filtered vouchers API - not built in this preview.", { icon: "info" });
      return;
    }
    const vouchers = window.VoyagerMock.getVouchersForBranch(companyId, branchName);
    render(branchName, `${vouchers.length} voucher(s) posted for this branch`, vouchers, ccy);
  }

  function renderTransactions(title, subtitle, items, ccy) {
    const modal = ensureModal();
    const { fmtMoney, fmtDate } = window.VoyagerUtil;
    document.getElementById("dd-title").textContent = title;
    document.getElementById("dd-subtitle").textContent = subtitle;
    document.getElementById("dd-body").innerHTML = items.length
      ? items.map((it) => `
        <div class="dd-voucher">
          <div class="dd-voucher-head" style="cursor:default;">
            <span class="pill pill-neutral" style="width:70px; text-align:center;">${it.kind}</span>
            <span class="dd-date">${fmtDate(it.date)}</span>
            <span class="dd-narr">${it.label}</span>
            <span class="dd-amt">${fmtMoney(it.amount, ccy)}</span>
            <a href="${it.editUrl}" class="btn-outline-brand" style="padding:0.18rem 0.45rem; font-size:0.7rem; margin-left:0.5rem; flex-shrink:0;">View / Edit</a>
          </div>
        </div>`).join("")
      : `<div class="dd-empty">No transactions found.</div>`;
    modal.classList.add("open");
  }

  function byCustomer(customerName, companyId, ccy) {
    if (!window.VoyagerAPI.Store.isMockMode()) {
      voyagerAlert("Drill-down works in Demo Mode (sample data).", { icon: "info" });
      return;
    }
    const returnTo = window.location.pathname.split("/").pop() + window.location.search;
    const tickets = window.VoyagerMock.getTicketsForCustomer(companyId, customerName)
      .map((t) => ({ kind: "Ticket", date: t.issue_date, label: `${t.pnr} - ${t.passenger_name} (${t.sector})`, amount: t.total_billed, editUrl: window.VoyagerEntry.zoomInUrl("ticket-entry.html", t.id, returnTo) }));
    const hotels = window.VoyagerMock.getHotelsForCustomer(companyId, customerName)
      .map((h) => ({ kind: "Hotel", date: h.check_in, label: `${h.hotel_name} - ${h.guest_name}`, amount: h.customer_billing, editUrl: window.VoyagerEntry.zoomInUrl("hotel-entry.html", h.id, returnTo) }));
    const items = tickets.concat(hotels).sort((a, b) => (a.date < b.date ? 1 : -1));
    renderTransactions(customerName, `${items.length} transaction(s) for this customer`, items, ccy);
  }

  function bySupplier(supplierName, companyId, ccy) {
    if (!window.VoyagerAPI.Store.isMockMode()) {
      voyagerAlert("Drill-down works in Demo Mode (sample data).", { icon: "info" });
      return;
    }
    const returnTo = window.location.pathname.split("/").pop() + window.location.search;
    const items = window.VoyagerMock.getHotelsForSupplier(companyId, supplierName)
      .map((h) => ({ kind: "Hotel", date: h.check_in, label: `${h.hotel_name} - ${h.guest_name}`, amount: h.supplier_cost, editUrl: window.VoyagerEntry.zoomInUrl("hotel-entry.html", h.id, returnTo) }))
      .sort((a, b) => (a.date < b.date ? 1 : -1));
    renderTransactions(supplierName, `${items.length} transaction(s) for this supplier`, items, ccy);
  }

  window.VoyagerDrilldown = { byLedger, byBranch, byCustomer, bySupplier, close };
})(window);
