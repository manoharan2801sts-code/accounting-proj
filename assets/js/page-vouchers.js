(async function () {
  const { fmtMoney, fmtDate, currencyFor, titleCaseLabel } = window.VoyagerUtil;
  const { zoomInUrl } = window.VoyagerEntry;
  let allVouchers = [];
  let ccy = "INR";

  // Number only - each voucher type has its own series (stored JV-1 / PV-1 /
  // RV-1 ...), the Voucher Type column already says which series it is.
  function displayVoucherNo(v) {
    return String(v.voucher_no || v.id).split("-").pop();
  }

  // Date filter - defaults to today, like every report screen.
  const today = new Date().toISOString().slice(0, 10);
  document.getElementById("vf-from").value = today;
  document.getElementById("vf-to").value = today;

  function render() {
    const from = document.getElementById("vf-from").value;
    const to = document.getElementById("vf-to").value;
    const list = allVouchers.filter((v) => (!from || v.voucher_date >= from) && (!to || v.voucher_date <= to));
    const el = document.getElementById("voucher-list");
    const detailed = document.getElementById("vf-detailed").checked;
    // Grand Total - every voucher in the date range (Debit = Credit on each).
    document.getElementById("v-total-amount").textContent = fmtMoney(list.reduce((s, v) => s + (Number(v.total_debit) || 0), 0), ccy);
    document.getElementById("v-total-count").textContent = list.length ? `${list.length} voucher${list.length === 1 ? "" : "s"}` : "";
    if (!list.length) {
      el.innerHTML = `<p class="text-muted-custom" style="padding:16px; text-align:center;">${allVouchers.length
        ? "No vouchers in this date range."
        : 'No vouchers posted yet. Click "+ New Voucher" to create one.'}</p>`;
      return;
    }
    selIdx = -1;
    el.innerHTML = list.map((v, i) => `
      <div class="v-card">
        <div class="v-head" data-idx="${i}" data-id="${v.id}" title="Double-click to open this voucher">
          <div class="v-no">${displayVoucherNo(v)}</div>
          <div class="v-type"><span class="pill pill-neutral" title="${titleCaseLabel(v.voucher_type)}">${v.voucher_type_name || titleCaseLabel(v.voucher_type)}</span></div>
          <div class="v-date">${fmtDate(v.voucher_date)}</div>
          <div class="v-narration">${v.narration || ""}</div>
          <div class="v-amount">${fmtMoney(v.total_debit, ccy)}</div>
        </div>
        <div class="v-lines${detailed ? "" : " closed"}" id="vl-${i}">
          <table>
            <thead><tr><th>Account</th><th>Debit</th><th>Credit</th></tr></thead>
            <tbody>
              ${v.lines.map((l) => `<tr><td>${l.ledger_name}</td><td>${l.debit ? fmtMoney(l.debit, ccy) : ""}</td><td>${l.credit ? fmtMoney(l.credit, ccy) : ""}</td></tr>`).join("")}
            </tbody>
          </table>
        </div>
      </div>`).join("");

    // Single click collapses / expands the lines; double-click opens the
    // voucher (read-only first, with an Edit button there).
    el.querySelectorAll(".v-head").forEach((head) => {
      head.addEventListener("click", () => document.getElementById(`vl-${head.dataset.idx}`).classList.toggle("closed"));
      head.addEventListener("dblclick", () => {
        window.VoyagerShell.navigateTo(`${zoomInUrl("voucher-entry.html", head.dataset.id, "vouchers.html")}&view=1`);
      });
    });
  }

  // Keyboard row navigation, like the report pages - Up / Down moves the
  // highlighted row (kept in step with the mouse), Enter opens it, same as a
  // double-click. Ignored while typing in a field.
  let selIdx = -1;
  const heads = () => Array.from(document.querySelectorAll("#voucher-list .v-head"));
  function selectRow(i) {
    const rows = heads();
    rows.forEach((r) => r.classList.remove("v-sel"));
    if (!rows.length) { selIdx = -1; return; }
    selIdx = Math.max(0, Math.min(i, rows.length - 1));
    rows[selIdx].classList.add("v-sel");
    rows[selIdx].scrollIntoView({ block: "nearest" });
  }
  document.getElementById("voucher-list").addEventListener("mouseover", (e) => {
    const row = e.target.closest(".v-head");
    if (row) { const i = heads().indexOf(row); if (i !== -1 && i !== selIdx) selectRow(i); }
  });
  document.addEventListener("keydown", (e) => {
    if (!["ArrowDown", "ArrowUp", "Enter"].includes(e.key)) return;
    const tag = document.activeElement && document.activeElement.tagName;
    if (["INPUT", "SELECT", "TEXTAREA"].includes(tag)) return;
    if (!heads().length) return;
    e.preventDefault();
    if (e.key === "ArrowDown") selectRow(selIdx + 1);
    else if (e.key === "ArrowUp") selectRow(selIdx < 0 ? 0 : selIdx - 1);
    else if (selIdx >= 0) heads()[selIdx].dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
  });

  async function load(companyId, country) {
    try {
      const res = await fetch(`http://localhost:8000/api/vouchers/?company_id=${companyId}`);
      if (!res.ok) throw new Error(`Vouchers API returned ${res.status}`);
      allVouchers = await res.json();
    } catch (err) {
      console.error("Could not load vouchers from the Django API — is it running on localhost:8000?", err);
      document.getElementById("voucher-list").innerHTML =
        `<p style="color:var(--color-danger); padding:16px;">Could not load vouchers from the database. Is the Django backend running on localhost:8000?</p>`;
      return;
    }
    ccy = currencyFor(country);
    render();
  }
  document.getElementById("vf-apply").addEventListener("click", render);
  // Detailed View: each voucher's Debit / Credit lines shown under it; off =
  // one summary row per voucher.
  document.getElementById("vf-detailed").addEventListener("change", render);

  let active = null;
  try {
    active = await VoyagerShell.init({ activeKey: "vouchers", onCompanyChange: load });
  } catch (err) {
    console.error("Shell init failed", err);
  }
  if (active) {
    load(active.id, active.country);
  } else {
    voyagerAlert("Could not load the active company. Check your connection and reload the page.", { icon: "error" });
  }
})();
