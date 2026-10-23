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
  // Unadjusted column (bill, each adjustment line and the Total): the plain
  // amount, never with a "-" sign in front.
  const neg = (v) => n2(Math.abs(Number(v) || 0));
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
    misc: (id) => `trans-misc.html?misc_saved_id=${id}`,
    voucher: (id) => `voucher-entry.html?id=${id}&returnTo=${encodeURIComponent(location.pathname.split("/").pop())}&view=1`,
  };
  const docAttr = (doc) => (doc && DOC_URL[doc.kind] ? ` data-url="${DOC_URL[doc.kind](doc.id)}"` : "");

  // Two views (tabs):
  //   Ledger Wise - one group per customer / supplier, its bills under it.
  //   Bill Wise   - every bill on its own row, by date then invoice number
  //                 (no party grouping), with the party in its own column.
  // Column headings: the bill amount, what's adjusted against it, and what
  // is still open. Receivables: Outstanding / Unadjusted / Net Outstanding.
  const BILLED_LABEL = RECEIVABLE ? "Outstanding" : "Payable";
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
    $("po-thead").innerHTML = `<tr>${v.head.map((h) => `<th>${h}</th>`).join("")}<th class="amt">${BILLED_LABEL}</th><th class="amt">Unadjusted</th><th class="amt">Net Outstanding</th></tr>`;
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
  // A bill's own Adjusted figure - left blank in Detailed View when its
  // adjustment lines are listed right under it (no repeated sub-total).
  const billAdjusted = (b, detailed) => (detailed && b.adjustments.length ? "" : neg(b.adjusted));
  const adjAmount = (a) => (RECEIVABLE ? a.credit - a.debit : a.debit - a.credit);
  const clickAttrs = (doc, cls) => `class="${cls}${doc ? " po-click" : ""}"${docAttr(doc)} title="${doc ? "Double-click to open" : ""}"`;

  // Which parties to show: the one picked in the Customer / Supplier box, or
  // everyone when "All Customers" / "All Suppliers" is ticked. null = none
  // picked yet (the report waits for a choice instead of loading everyone).
  function selectedParties() {
    if ($("po-all").checked) return data.parties;
    const name = $("po-party").value.trim().toLowerCase();
    if (!name) return null;
    return data.parties.filter((p) => p.name.toLowerCase() === name);
  }

  function render() {
    const tbody = $("po-tbody");
    if (!data) return;
    const view = currentView();
    applyViewLayout(view);
    const ncols = VIEWS[view].head.length + 3;
    const parties = selectedParties();
    if (!parties) {
      tbody.innerHTML = `<tr><td colspan="${ncols}" class="po-empty">Choose a ${PARTY_LABEL} (or tick All ${PARTY_LABEL}s) and click Apply.</td></tr>`;
      $("po-total-label").textContent = "Grand Total";
      ["po-total-billed", "po-total-adjusted"].forEach((id) => { $(id).textContent = n2(0); });
      $("po-total-outstanding").innerHTML = drcr(0);
      return;
    }
    // Show Only Settled Bills: ONLY bills fully settled (nothing left
    // outstanding) - no open bills and no On Account (Unadjusted) amounts;
    // the vouchers that settled them show under each bill only when Detailed
    // View is ticked, same as every other view. Otherwise as before: open
    // bills, plus settled ones when Show Settled Bills is ticked.
    const onlySettled = $("po-only-settled").checked;
    const detailed = $("po-detailed").checked;
    const showSettled = $("po-settled").checked;
    const keep = (b) => (onlySettled
      ? b.invoice_number !== ON_ACCOUNT && Math.abs(b.outstanding) < 0.005 && b.adjustments.length > 0
      : (showSettled || Math.abs(b.outstanding) >= 0.005));
    const q = $("po-search").value.trim().toLowerCase();
    const matches = (p, b) => !q || [p.name, b.invoice_number, billLabel(b), b.type, b.ref].some((x) => String(x || "").toLowerCase().includes(q));
    let rows = "", count = 0, tBilled = 0, tAdjusted = 0, tOutstanding = 0;

    if (view === "ledger") {
      parties.forEach((p) => {
        const shown = p.bills.filter((b) => keep(b) && matches(p, b));
        if (!shown.length) return;
        const sum = (k) => shown.reduce((s, b) => s + b[k], 0);
        const billed = sum("billed"), adjusted = sum("adjusted"), outstanding = sum("outstanding");
        tBilled += billed; tAdjusted += adjusted; tOutstanding += outstanding; count += 1;
        rows += `<tr class="po-party"><td>${esc(p.name)}</td><td></td><td></td><td></td>
          <td class="amt">${n2(billed)}</td><td class="amt">${neg(adjusted)}</td><td class="amt">${drcr(outstanding)}</td></tr>`;
        if (!detailed) return;
        shown.forEach((b) => {
          const onAccount = b.invoice_number === ON_ACCOUNT;
          rows += `<tr ${clickAttrs(b.doc, "po-bill")}>
            <td class="po-indent">${esc(billLabel(b))}</td><td>${ddmmyyyy(b.date)}</td><td>${esc(b.type)}</td><td>${esc(b.ref)}</td>
            <td class="amt">${n2(b.billed)}</td><td class="amt">${billAdjusted(b, detailed)}</td><td class="amt">${drcr(b.outstanding)}</td></tr>`;
          b.adjustments.forEach((a) => {
            rows += `<tr ${clickAttrs(a.doc, "po-adj")}>
              <td class="po-indent2">&#8627; ${onAccount ? "On Account" : "Adjusted"} - ${esc(a.type)}</td><td>${ddmmyyyy(a.date)}</td><td></td><td></td>
              <td></td><td class="amt">${neg(adjAmount(a))}</td><td></td></tr>`;
          });
        });
      });
    } else {
      // Bill Wise - flat list, oldest first; On Account (Unadjusted) rows last.
      const all = [];
      parties.forEach((p) => p.bills.forEach((b) => {
        if (keep(b) && matches(p, b)) all.push({ p, b });
      }));
      all.sort((x, y) => (x.b.invoice_number === ON_ACCOUNT) - (y.b.invoice_number === ON_ACCOUNT)
        || String(x.b.date || "").localeCompare(String(y.b.date || ""))
        || String(x.b.invoice_number || "").localeCompare(String(y.b.invoice_number || "")));
      all.forEach(({ p, b }) => {
        tBilled += b.billed; tAdjusted += b.adjusted; tOutstanding += b.outstanding; count += 1;
        const onAccount = b.invoice_number === ON_ACCOUNT;
        rows += `<tr ${clickAttrs(b.doc, "po-bill po-bill-flat")}>
          <td>${ddmmyyyy(b.date)}</td><td>${esc(billLabel(b))}</td><td>${esc(p.name)}</td><td>${esc(b.type)}</td><td>${esc(b.ref)}</td>
          <td class="amt">${n2(b.billed)}</td><td class="amt">${billAdjusted(b, detailed)}</td><td class="amt">${drcr(b.outstanding)}</td></tr>`;
        if (!detailed) return;
        b.adjustments.forEach((a) => {
          rows += `<tr ${clickAttrs(a.doc, "po-adj")}>
            <td>${ddmmyyyy(a.date)}</td><td class="po-indent" colspan="4">&#8627; ${onAccount ? "On Account" : "Adjusted"} - ${esc(a.type)}</td>
            <td></td><td class="amt">${neg(adjAmount(a))}</td><td></td></tr>`;
        });
      });
    }

    tbody.innerHTML = rows || `<tr><td colspan="${ncols}" class="po-empty">${q ? "No matching entries." : onlySettled ? "No fully settled bills as on this date." : "Nothing outstanding as on this date."}</td></tr>`;
    const word = view === "bill" ? "bill" : PARTY_LABEL.toLowerCase();
    $("po-total-label").textContent = `Grand Total${count ? ` (${count} ${word}${count === 1 ? "" : "s"})` : ""}`;
    $("po-total-billed").textContent = n2(tBilled);
    $("po-total-adjusted").textContent = neg(tAdjusted);
    $("po-total-outstanding").innerHTML = drcr(tOutstanding);
  }

  let loadSeq = 0; // only the latest load's result is used (loads can overlap)
  async function load() {
    const tbody = $("po-tbody");
    const seq = ++loadSeq;
    tbody.innerHTML = `<tr><td colspan="8" class="po-empty">Loading...</td></tr>`;
    try {
      const qs = new URLSearchParams({ company_id: activeCompanyId, as_of: $("po-as-of").value || "" });
      const res = await fetch(`http://127.0.0.1:8000/api/${SIDE}/?${qs}`);
      const result = await res.json();
      if (seq !== loadSeq) return; // a newer load (e.g. the filter's Show) took over
      data = result;
      if (!res.ok) throw new Error(data.error || `Server returned ${res.status}`);
      // Customer / Supplier box suggestions = every party in the report.
      $("po-party-list").innerHTML = data.parties.map((p) => `<option value="${esc(p.name)}">`).join("");
      render();
    } catch (err) {
      if (seq !== loadSeq) return;
      console.error(err);
      data = null;
      tbody.innerHTML = `<tr><td colspan="8" class="po-empty">Could not load data. Is the Django backend running on 127.0.0.1:8000?</td></tr>`;
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

  // ---------- Customer / Supplier filter ----------
  $("po-as-of").value = new Date().toISOString().slice(0, 10);
  document.querySelector(".po-party-label").textContent = PARTY_LABEL;
  $("po-all-label").textContent = `All ${PARTY_LABEL}s`;
  $("po-party").placeholder = `Type ${PARTY_LABEL.toLowerCase()} name...`;
  const syncPartyBox = () => { $("po-party").disabled = $("po-all").checked; };
  $("po-all").addEventListener("change", () => { syncPartyBox(); render(); });
  $("po-party").addEventListener("keydown", (e) => { if (e.key === "Enter") load(); });

  // Opening the report fresh asks for the Customer / Supplier and As On date
  // first (instead of loading everyone). "All Customers" there loads all.
  function openFilterPopup() {
    let modal = $("po-filter-modal");
    // Lives on <body>, so it outlasts an in-app move between Receivables
    // and Payables - rebuild it when it was made for the other side.
    if (modal && modal.dataset.side !== SIDE) { modal.remove(); modal = null; }
    if (!modal) {
      modal = document.createElement("div");
      modal.className = "dom-modal-backdrop";
      modal.id = "po-filter-modal";
      modal.dataset.side = SIDE;
      modal.innerHTML = `
        <div class="dom-modal-window">
          <div class="dom-modal-titlebar"><div>${RECEIVABLE ? "Receivables" : "Payables"} - Filter</div>
            <button type="button" class="dom-titlebar-btn btn-close" data-pf="close">&times;</button></div>
          <div class="po-filter-body">
            <label class="po-fl" for="pf-party">${PARTY_LABEL}</label>
            <input type="text" class="form-control-custom" id="pf-party" list="po-party-list" autocomplete="off" placeholder="Type ${PARTY_LABEL.toLowerCase()} name..." />
            <label class="po-fl" for="pf-as-of">As On</label>
            <input type="date" class="form-control-custom" id="pf-as-of" />
            <label class="po-filter-all"><input type="checkbox" id="pf-all" /> All ${PARTY_LABEL}s</label>
            <div class="po-filter-hint" id="pf-hint"></div>
          </div>
          <div class="voyager-alert-actions">
            <button type="button" class="dom-nav-btn" data-pf="close">Cancel</button>
            <button type="button" class="dom-nav-btn btn-primary" data-pf="show">Show</button>
          </div>
        </div>`;
      document.body.appendChild(modal);
      const close = () => modal.classList.remove("open");
      const show = () => {
        const all = $("pf-all").checked;
        const name = $("pf-party").value.trim();
        if (!all && !name) { $("pf-hint").textContent = `Choose a ${PARTY_LABEL.toLowerCase()}, or tick All ${PARTY_LABEL}s.`; return; }
        $("po-party").value = all ? "" : name;
        $("po-all").checked = all;
        $("po-as-of").value = $("pf-as-of").value || $("po-as-of").value;
        $("po-as-of").dispatchEvent(new Event("change"));
        syncPartyBox();
        close();
        load();
      };
      modal.querySelectorAll('[data-pf="close"]').forEach((b) => b.addEventListener("click", close));
      modal.querySelector('[data-pf="show"]').addEventListener("click", show);
      $("pf-all").addEventListener("change", () => { $("pf-party").disabled = $("pf-all").checked; $("pf-hint").textContent = ""; });
      $("pf-party").addEventListener("input", () => { $("pf-hint").textContent = ""; });
      modal.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); show(); }
        if (e.key === "Escape") close();
      });
    }
    $("pf-party").value = $("po-party").value;
    $("pf-all").checked = $("po-all").checked;
    $("pf-party").disabled = $("pf-all").checked;
    $("pf-as-of").value = $("po-as-of").value;
    $("pf-hint").textContent = "";
    modal.classList.add("open");
    setTimeout(() => $("pf-party").focus(), 0);
  }

  $("po-apply").addEventListener("click", load);
  $("po-detailed").addEventListener("change", render);
  $("po-view-ledger").addEventListener("change", render);
  $("po-view-bill").addEventListener("change", render);
  $("po-settled").addEventListener("change", render);
  $("po-only-settled").addEventListener("change", render);
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
    if (rs) {
      // Back to this report -> same filter / options as it was left.
      VoyagerShell.reportState.applyInputs(rs);
      syncPartyBox();
      await load();
      VoyagerShell.reportState.restoreAfterLoad(rs);
      return;
    }
    // Fresh open: Detailed View off, Show Settled Bills off, nothing loaded
    // until a Customer / Supplier (or All) is chosen in the filter popup.
    $("po-detailed").checked = false;
    $("po-settled").checked = false;
    $("po-only-settled").checked = false;
    $("po-all").checked = false;
    $("po-party").value = "";
    syncPartyBox();
    load(); // in the background - fills the popup's name suggestions
    openFilterPopup();
  })();
})();
