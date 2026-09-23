(async function () {
  const { fmtMoney, fmtDate, currencyFor, titleCaseLabel } = window.VoyagerUtil;
  const { zoomInUrl } = window.VoyagerEntry;

  function displayVoucherNo(v) {
    return v.voucher_no || `VCH-${v.id}`;
  }

  async function load(companyId, country) {
    let vouchers = [];
    const API_BASE = window.API_BASE || "/api";
    try {
      const res = await fetch(`${API_BASE}/vouchers/?company_id=${companyId}`);
      if (!res.ok) throw new Error(`Vouchers API returned ${res.status}`);
      vouchers = await res.json();
    } catch (err) {
      console.error("Could not load vouchers from the backend API", err);
      document.getElementById("voucher-list").innerHTML =
        `<p style="color:var(--color-danger); padding:16px;">Could not load vouchers from the database. Is the backend running?</p>`;
      return;
    }

    const ccy = currencyFor(country);
    if (vouchers.length === 0) {
      document.getElementById("voucher-list").innerHTML =
        `<p class="text-muted-custom" style="padding:16px;">No vouchers posted yet. Click "+ New Voucher" to create one.</p>`;
      return;
    }

    document.getElementById("voucher-list").innerHTML = vouchers.map((v, i) => `
      <div class="v-card">
        <div class="v-head" data-idx="${i}">
          <div class="v-no">${displayVoucherNo(v)}</div>
          <div class="v-type"><span class="pill pill-neutral">${titleCaseLabel(v.voucher_type)}</span></div>
          <div class="v-date">${fmtDate(v.voucher_date)}</div>
          <div class="v-narration">${v.narration || ""} <span class="text-muted-custom">— ${v.branch_name || "—"}</span></div>
          <div class="v-amount">${fmtMoney(v.total_debit, ccy)}</div>
          <a href="${zoomInUrl("voucher-entry.html", v.id, "vouchers.html")}" class="btn-outline-brand" style="padding:0.2rem 0.5rem; font-size:0.72rem; margin-left:0.5rem;" onclick="event.stopPropagation()">Edit</a>
        </div>
        <div class="v-lines" id="vl-${i}">
          <table>
            <thead><tr><th>Account</th><th>Debit</th><th>Credit</th></tr></thead>
            <tbody>
              ${v.lines.map((l) => `<tr><td>${l.ledger_name}</td><td>${l.debit ? fmtMoney(l.debit, ccy) : ""}</td><td>${l.credit ? fmtMoney(l.credit, ccy) : ""}</td></tr>`).join("")}
            </tbody>
          </table>
        </div>
      </div>`).join("");

    // Debit/Credit lines show fully expanded by default (no click needed
    // to see a voucher's data) - clicking the row still lets you collapse
    // one you're not interested in.
    document.querySelectorAll(".v-head").forEach((head) => {
      head.addEventListener("click", () => document.getElementById(`vl-${head.dataset.idx}`).classList.toggle("closed"));
    });
  }

  const active = await VoyagerShell.init({ activeKey: "vouchers", onCompanyChange: load });
  if (active) load(active.id, active.country);
})();