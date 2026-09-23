(function () {
  const { Store, get } = window.VoyagerAPI;

  // No login backend is wired up yet — VoyagerShell.init() (called below)
  // assigns every first-time visitor a real session token, so there is
  // nothing to gate here.
  const user = Store.getUser();
  const currency = (companyCountry) => (companyCountry === "AE" ? "AED" : "INR");

  function fmtMoney(value, ccy) {
    const abs = Math.abs(value);
    let display;
    if (abs >= 10000000 && ccy === "INR") display = (value / 10000000).toFixed(2) + " Cr";
    else if (abs >= 100000 && ccy === "INR") display = (value / 100000).toFixed(2) + " L";
    else if (abs >= 1000000) display = (value / 1000000).toFixed(2) + "M";
    else if (abs >= 1000) display = (value / 1000).toFixed(1) + "K";
    else display = value.toFixed(0);
    return `${ccy} ${display}`;
  }

  function initials(name) {
    return name.split(" ").filter(Boolean).slice(0, 2).map((p) => p[0]).join("").toUpperCase();
  }

  // --- Top nav: greeting ---
  if (user) {
    const hour = new Date().getHours();
    const greetWord = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
    document.getElementById("greeting").textContent = `${greetWord}, ${user.full_name.split(" ")[0]}`;
  }

  // --- Company selector + dashboard load ---
  let trendChartInstance, mixChartInstance;


  function heroCard(label, value, ccy, iconSvg) {
    return `
      <div class="boarding-pass">
        <div class="bp-main">
          <div class="bp-label">${iconSvg} ${label}</div>
          <div class="bp-value">${fmtMoney(value, ccy)}</div>
          <div class="bp-delta up">Live from posted transactions</div>
        </div>
        <div class="bp-stub">VOYAGER</div>
      </div>`;
  }

  const { ICONS } = window.VoyagerHardcode;
  function svgIcon(pathKey) {
    return `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="${ICONS[pathKey]}"/></svg>`;
  }

  function getPath(obj, path) {
    return path.split(".").reduce((o, k) => (o ? o[k] : undefined), obj);
  }

  function metricTile(label, value, ccy, ledgerName) {
    const cls = ledgerName ? "drillable" : "";
    const attr = ledgerName ? `data-ledger="${ledgerName}" title="Click to view the vouchers behind this figure"` : "";
    return `<div class="metric-tile ${cls}" ${attr}><div class="m-label">${label}</div><div class="m-value">${fmtMoney(value, ccy)}</div></div>`;
  }

  function wireDrillableTiles(containerId, companyId, ccy) {
    document.querySelectorAll(`#${containerId} .drillable`).forEach((el) => {
      el.addEventListener("click", () => VoyagerDrilldown.byLedger(el.dataset.ledger, companyId, ccy));
    });
  }

  async function loadDashboard(companyId, country) {
    document.getElementById("scope-label").textContent = "Loading dashboard for the selected entity…";
    const data = await get(`/dashboard?company_id=${companyId}`);
    const ccy = currency(country);
    document.getElementById("scope-label").textContent =
      `Real-time CFO dashboard — ${country === "AE" ? "UAE entity, AED" : "India entity, INR"}`;

    // Hero row — config comes from window.VoyagerHardcode.DASHBOARD_HERO_CARDS
    document.getElementById("hero-row").innerHTML = window.VoyagerHardcode.DASHBOARD_HERO_CARDS
      .map((c) => heroCard(c.label, getPath(data, c.dataPath), ccy, svgIcon(c.iconKey)))
      .join("");

    // Revenue grid — config comes from window.VoyagerHardcode.DASHBOARD_REVENUE_TILES
    document.getElementById("revenue-grid").innerHTML = window.VoyagerHardcode.DASHBOARD_REVENUE_TILES
      .map((t) => metricTile(t.label, getPath(data, t.dataPath), ccy, t.ledger))
      .join("");
    wireDrillableTiles("revenue-grid", companyId, ccy);

    // Finance grid — config comes from window.VoyagerHardcode.DASHBOARD_FINANCE_TILES,
    // plus BSP/Supplier liability which stay inline (used again in the compliance
    // grid logic just below and not worth a second layer of indirection).
    document.getElementById("finance-grid").innerHTML =
      window.VoyagerHardcode.DASHBOARD_FINANCE_TILES.map((t) => metricTile(t.label, getPath(data, t.dataPath), ccy, t.ledger)).join("") +
      metricTile("BSP Liability", data.finance.bsp_liability, ccy, "BSP Payable") +
      metricTile("Supplier Liability", data.finance.supplier_liability, ccy, "Trade Payable - Suppliers");
    wireDrillableTiles("finance-grid", companyId, ccy);

    // Compliance grid — show the relevant tax type for the entity's country
    const complianceHtml =
      country === "AE"
        ? metricTile("VAT Payable", data.compliance.vat_payable, ccy, "VAT Payable")
        : metricTile("GST Payable", data.compliance.gst_payable, ccy, "GST Payable") +
          metricTile("TDS Payable", data.compliance.tds_payable, ccy, "TDS Payable");
    document.getElementById("compliance-grid").innerHTML = complianceHtml;
    wireDrillableTiles("compliance-grid", companyId, ccy);

    // Trend chart
    const trendCtx = document.getElementById("trendChart").getContext("2d");
    if (trendChartInstance) trendChartInstance.destroy();
    trendChartInstance = new Chart(trendCtx, {
      type: "line",
      data: {
        labels: data.monthly_revenue_trend.map((p) => p.label),
        datasets: [
          {
            label: "Revenue",
            data: data.monthly_revenue_trend.map((p) => p.value),
            borderColor: "#3B6DB5",
            backgroundColor: "rgba(37,99,235,0.10)",
            tension: 0.35,
            fill: true,
            pointRadius: 3,
          },
          {
            label: "Profit",
            data: data.profitability_trend.map((p) => p.value),
            borderColor: "#17324D",
            backgroundColor: "rgba(23,50,77,0.08)",
            tension: 0.35,
            fill: true,
            pointRadius: 3,
          },
        ],
      },
      options: {
        responsive: true,
        plugins: { legend: { position: "bottom", labels: { usePointStyle: true } } },
        scales: { y: { ticks: { callback: (v) => fmtMoney(v, ccy) } } },
      },
    });

    // Product mix chart
    const mixCtx = document.getElementById("mixChart").getContext("2d");
    if (mixChartInstance) mixChartInstance.destroy();
    mixChartInstance = new Chart(mixCtx, {
      type: "doughnut",
      data: {
        labels: data.product_mix.map((p) => p.product),
        datasets: [
          {
            data: data.product_mix.map((p) => p.value),
            backgroundColor: ["#3B6DB5", "#17324D", "#6E9AD9", "#94A3B8"],
            borderWidth: 0,
          },
        ],
      },
      options: { plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8 } } }, cutout: "62%" },
    });

    // Branch performance table
    document.getElementById("branch-table-body").innerHTML = data.branch_performance
      .map((b) => {
        const margin = b.sales > 0 ? ((b.profit / b.sales) * 100).toFixed(1) : "0.0";
        return `<tr class="drillable" data-branch="${b.branch_name}" title="Click to view this branch's vouchers">
          <td style="font-weight:600;">${b.branch_name}</td>
          <td class="tabular-nums">${fmtMoney(b.sales, ccy)}</td>
          <td class="tabular-nums">${fmtMoney(b.profit, ccy)}</td>
          <td><span class="pill pill-success">${margin}%</span></td>
        </tr>`;
      })
      .join("");
    document.querySelectorAll("#branch-table-body tr.drillable").forEach((tr) => {
      tr.addEventListener("click", () => VoyagerDrilldown.byBranch(tr.dataset.branch, companyId, ccy));
    });
  }

  (async function init() {
    try {
      const active = await VoyagerShell.init({ activeKey: "dashboard", onCompanyChange: loadDashboard });
      if (active) await loadDashboard(active.id, active.country);
    } catch (err) {
      console.error(err);
      document.getElementById("scope-label").textContent = "Could not load dashboard: " + err.message;
    }
  })();
})();
