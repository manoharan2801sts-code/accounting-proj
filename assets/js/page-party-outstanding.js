(function () {
  // Receivables (customers.html) / Payables (suppliers.html) - bill-wise
  // outstanding per Sundry Debtor / Sundry Creditor, invoice number as the
  // reference (cancellations adjusted against the booking they cancel).
  // The page says which side it is via its toolbar's data-side
  // ("receivables" | "payables") - inside .app-main, so it survives the
  // in-app page loader (which only copies .app-main's content).
  const SIDE = document.querySelector(".po-toolbar[data-side]").dataset.side;
  const RECEIVABLE = SIDE === "receivables";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const n2 = (v) => Math.abs(Number(v) || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  // Receivable balance is a Debit, payable a Credit; the other side means an
  // advance / excess (e.g. a cancellation refund bigger than the bill).
  const drcr = (v) => {
    if (!Number(v)) return "0.00";
    const normal = RECEIVABLE ? "Dr" : "Cr", other = RECEIVABLE ? "Cr" : "Dr";
    return `${n2(v)} <span class="po-tag">${v > 0 ? normal : other}</span>`;
  };
  const ddmmyyyy = (iso) => (iso ? iso.split("-").reverse().join("/") : "");
  let activeCompanyId = null;
  let data = null;
  const ON_ACCOUNT = "On Account"; // views.ON_ACCOUNT_KEY

  const DOC_URL = {
    ticket: (id) => `ticket-entry.html?id=${id}`,
    reschedule: (id) => `ticket-entry.html?reschedule_saved_id=${id}`,
    cancellation: (id) => `ticket-entry.html?cancellation_saved_id=${id}`,
    ssr: (id) => `trans-airline-ssr.html?ssr_saved_id=${id}`,
    voucher: (id) => `voucher-entry.html?id=${id}&returnTo=${encodeURIComponent(location.pathname.split("/").pop())}&view=1`,
  };
  const docAttr = (doc) => (doc && DOC_URL[doc.kind] ? ` data-url="${DOC_URL[doc.kind](doc.id)}"` : "");

  // Two views (tabs):
  //   Ledger Wise - one group per customer / supplier, its bills under it.
  //   Bill Wise   - every bill on its own row, by date then invoice number
  //                 (no party grouping), with the party in its own column.
  const BILLED_LABEL = RECEIVABLE ? "Billed" : "Payable";
  const PARTY_LABEL = RECEIVABLE ? "Customer" : "Supplier";
  const VIEWS = {
    ledger: {
      title: "ledger-wise outstanding",
      widths: [30, 10, 12, 12, 12, 12, 12],
      head: ["Particulars", "Date", "Type", "Reference"],
    },
    bill: {
      title: "bill-wise outstanding",
      widths: [9, 15, 22, 10, 10, 11, 11, 12],
      head: ["Date", "Invoice No", PARTY_LABEL, "Type", "Reference"],
    },
  };
  const currentView = () => ($("po-view-bill").checked ? "bill" : "ledger");

  function applyViewLayout(view) {
    const v = VIEWS[view];
    const cols = v.widths.map((w) => `<col style="width:${w}%">`).join("");
    $("po-cols").innerHTML = cols;
    $("po-total-cols").innerHTML = cols;
    $("po-thead").innerHTML = `<tr>${v.head.map((h) => `<th>${h}</th>`).join("")}<th class="amt">${BILLED_LABEL}</th><th class="amt">Adjusted</th><th class="amt">Outstanding</th></tr>`;
    // Grand Total row: label (2 columns wide in Bill Wise, where Date is
    // narrow) + one blank cell per remaining text column.
    const row = $("po-total-label").parentElement;
    row.querySelectorAll(".po-total-spacer").forEach((td) => td.remove());
    $("po-total-label").colSpan = view === "bill" ? 2 : 1;
    for (let i = $("po-total-label").colSpan; i < v.head.length; i += 1) {
      const td = document.createElement("td");
      td.className = "po-total-spacer";
      $("po-total-label").after(td);
    }
    $("po-title").textContent = `${$("po-title").dataset.base} (${v.title})`;
  }

  // Voucher amounts not adjusted against any invoice (On Account) -
  // Unadjusted Credits / Debits, by which side the balance is on.
  function billLabel(b) {
    if (b.invoice_number !== ON_ACCOUNT) return b.invoice_number;
    const isCredit = RECEIVABLE ? b.outstanding < 0 : b.outstanding > 0;
    return `Unadjusted ${isCredit ? "Credits" : "Debits"}`;
  }
  const adjAmount = (a) => (RECEIVABLE ? a.credit - a.debit : a.debit - a.credit);
  const clickAttrs = (doc, cls) => `class="${cls}${doc ? " po-click" : ""}"${docAttr(doc)} title="${doc ? "Double-click to open" : ""}"`;

  function render() {
    const tbody = $("po-tbody");
    if (!data) return;
    const view = currentView();
    applyViewLayout(view);
    const ncols = VIEWS[view].head.length + 3;
    const detailed = $("po-detailed").checked;
    const showSettled = $("po-settled").checked;
    const q = $("po-search").value.trim().toLowerCase();
    const matches = (p, b) => !q || [p.name, b.invoice_number, billLabel(b), b.type, b.ref].some((x) => String(x || "").toLowerCase().includes(q));
    let rows = "", count = 0, tBilled = 0, tAdjusted = 0, tOutstanding = 0;

    if (view === "ledger") {
      data.parties.forEach((p) => {
        const shown = p.bills.filter((b) => (showSettled || Math.abs(b.outstanding) >= 0.005) && matches(p, b));
        if (!shown.length) return;
        const sum = (k) => shown.reduce((s, b) => s + b[k], 0);
        const billed = sum("billed"), adjusted = sum("adjusted"), outstanding = sum("outstanding");
        tBilled += billed; tAdjusted += adjusted; tOutstanding += outstanding; count += 1;
        rows += `<tr class="po-party"><td>${esc(p.name)}</td><td></td><td></td><td></td>
          <td class="amt">${n2(billed)}</td><td class="amt">${n2(adjusted)}</td><td class="amt">${drcr(outstanding)}</td></tr>`;
        if (!detailed) return;
        shown.forEach((b) => {
          const onAccount = b.invoice_number === ON_ACCOUNT;
          rows += `<tr ${clickAttrs(b.doc, "po-bill")}>
            <td class="po-indent">${esc(billLabel(b))}</td><td>${ddmmyyyy(b.date)}</td><td>${esc(b.type)}</td><td>${esc(b.ref)}</td>
            <td class="amt">${n2(b.billed)}</td><td class="amt">${n2(b.adjusted)}</td><td class="amt">${drcr(b.outstanding)}</td></tr>`;
          b.adjustments.forEach((a) => {
            rows += `<tr ${clickAttrs(a.doc, "po-adj")}>
              <td class="po-indent2">&#8627; ${onAccount ? "On Account" : "Adjusted"} - ${esc(a.type)}</td><td>${ddmmyyyy(a.date)}</td><td></td><td></td>
              <td></td><td class="amt">${n2(adjAmount(a))}</td><td></td></tr>`;
          });
        });
      });
    } else {
      // Bill Wise - flat list, oldest first; On Account (Unadjusted) rows last.
      const all = [];
      data.parties.forEach((p) => p.bills.forEach((b) => {
        if ((showSettled || Math.abs(b.outstanding) >= 0.005) && matches(p, b)) all.push({ p, b });
      }));
      all.sort((x, y) => (x.b.invoice_number === ON_ACCOUNT) - (y.b.invoice_number === ON_ACCOUNT)
        || String(x.b.date || "").localeCompare(String(y.b.date || ""))
        || String(x.b.invoice_number || "").localeCompare(String(y.b.invoice_number || "")));
      all.forEach(({ p, b }) => {
        tBilled += b.billed; tAdjusted += b.adjusted; tOutstanding += b.outstanding; count += 1;
        const onAccount = b.invoice_number === ON_ACCOUNT;
        rows += `<tr ${clickAttrs(b.doc, "po-bill po-bill-flat")}>
          <td>${ddmmyyyy(b.date)}</td><td>${esc(billLabel(b))}</td><td>${esc(p.name)}</td><td>${esc(b.type)}</td><td>${esc(b.ref)}</td>
          <td class="amt">${n2(b.billed)}</td><td class="amt">${n2(b.adjusted)}</td><td class="amt">${drcr(b.outstanding)}</td></tr>`;
        if (!detailed) return;
        b.adjustments.forEach((a) => {
          rows += `<tr ${clickAttrs(a.doc, "po-adj")}>
            <td>${ddmmyyyy(a.date)}</td><td class="po-indent" colspan="4">&#8627; ${onAccount ? "On Account" : "Adjusted"} - ${esc(a.type)}</td>
            <td></td><td class="amt">${n2(adjAmount(a))}</td><td></td></tr>`;
        });
      });
    }

    tbody.innerHTML = rows || `<tr><td colspan="${ncols}" class="po-empty">${q ? "No matching entries." : "Nothing outstanding as on this date."}</td></tr>`;
    const word = view === "bill" ? "bill" : PARTY_LABEL.toLowerCase();
    $("po-total-label").textContent = `Grand Total${count ? ` (${count} ${word}${count === 1 ? "" : "s"})` : ""}`;
    $("po-total-billed").textContent = n2(tBilled);
    $("po-total-adjusted").textContent = n2(tAdjusted);
    $("po-total-outstanding").innerHTML = drcr(tOutstanding);
  }

  async function load() {
    const tbody = $("po-tbody");
    tbody.innerHTML = `<tr><td colspan="8" class="po-empty">Loading...</td></tr>`;
    try {
      const qs = new URLSearchParams({ company_id: activeCompanyId, as_of: $("po-as-of").value || "" });
      const res = await fetch(`http://localhost:8000/api/${SIDE}/?${qs}`);
      data = await res.json();
      if (!res.ok) throw new Error(data.error || `Server returned ${res.status}`);
      render();
    } catch (err) {
      console.error(err);
      data = null;
      tbody.innerHTML = `<tr><td colspan="8" class="po-empty">Could not load data. Is the Django backend running on localhost:8000?</td></tr>`;
    }
  }

  function exportCSV() {
    const csv = Array.from(document.querySelectorAll("#po-table tr")).map((tr) =>
      Array.from(tr.querySelectorAll("th, td")).map((td) => `"${td.innerText.replace(/"/g, '""')}"`).join(","));
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([csv.join("\n")], { type: "text/csv;charset=utf-8;" }));
    link.download = `${SIDE}.csv`;
    link.click();
  }

  $("po-as-of").value = new Date().toISOString().slice(0, 10);
  $("po-apply").addEventListener("click", load);
  $("po-detailed").addEventListener("change", render);
  $("po-view-ledger").addEventListener("change", render);
  $("po-view-bill").addEventListener("change", render);
  $("po-settled").addEventListener("change", render);
  $("po-search").addEventListener("input", render);
  $("po-export").addEventListener("click", exportCSV);
  $("po-print").addEventListener("click", () => window.print());
  $("po-tbody").addEventListener("dblclick", (e) => {
    const row = e.target.closest("tr[data-url]");
    if (row) window.location.href = row.dataset.url;
  });

  (async function init() {
    const rs = VoyagerShell.reportState.consume();
    try {
      const active = await VoyagerShell.init({ activeKey: RECEIVABLE ? "customers" : "suppliers", onCompanyChange: (id) => { activeCompanyId = Number(id); load(); } });
      if (active) activeCompanyId = Number(active.id);
    } catch (err) {
      console.error("Shell init failed", err);
    }
    VoyagerShell.reportState.applyInputs(rs);
    await load();
    VoyagerShell.reportState.restoreAfterLoad(rs);
  })();
})();
