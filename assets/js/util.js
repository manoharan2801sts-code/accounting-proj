(function (window) {
  // Company Master's "No. of Decimals" - how many decimal places every
  // money amount displays with project-wide (some currencies price in
  // 3 decimals, not just 2). Starts at the old hardcoded default so
  // anything that renders before loadDecimalPlaces() resolves still
  // looks right; percentages/ROE/quantities are NOT affected by this -
  // only real currency amounts (Basic Fare, Taxes, Total, Debit, Credit,
  // Balance, GST Amount, etc.).
  let decimalPlaces = 2;
  async function loadDecimalPlaces(companyId) {
    if (!companyId) return decimalPlaces;
    try {
      const res = await fetch(`http://localhost:8000/api/company-master/?id=${companyId}`);
      if (res.ok) {
        const data = await res.json();
        if (data.decimal_places != null) decimalPlaces = Number(data.decimal_places);
      }
    } catch (_) {
      // Backend unreachable - keep whatever decimalPlaces already was
      // (the 2-decimal default, or a previously-loaded company's value).
    }
    return decimalPlaces;
  }
  function getDecimalPlaces() { return decimalPlaces; }
  // Shared amount formatter (no currency prefix, just the number) - every
  // report/ticket-entry fmtAmt()-style helper should delegate here instead
  // of hardcoding toFixed(2)/minimumFractionDigits:2, so they all move
  // together whenever loadDecimalPlaces() picks up a different value.
  function fmtAmt(value) {
    const n = Number(value) || 0;
    return n.toLocaleString("en-IN", { minimumFractionDigits: decimalPlaces, maximumFractionDigits: decimalPlaces });
  }
  function fmtMoney(value, ccy) {
    const n = Number(value) || 0;
    return `${ccy} ${n.toLocaleString(undefined, { minimumFractionDigits: decimalPlaces, maximumFractionDigits: decimalPlaces })}`;
  }
  // Every date shown in the app is dd/mm/yyyy. An ISO "yyyy-mm-dd..." string
  // is reformatted directly (no Date/timezone round-trip that could shift
  // the day); an already dd/mm/yyyy value passes through unchanged.
  function fmtDate(value) {
    if (!value) return "—";
    if (typeof value === "string") {
      const iso = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
      if (iso) return `${iso[3]}/${iso[2]}/${iso[1]}`;
      if (/^\d{2}\/\d{2}\/\d{4}$/.test(value)) return value;
    }
    const d = new Date(value);
    if (isNaN(d)) return String(value);
    return `${String(d.getDate()).padStart(2, "0")}/${String(d.getMonth() + 1).padStart(2, "0")}/${d.getFullYear()}`;
  }
  // Short-form abbreviations that must stay fully capitalized when a raw
  // backend code (e.g. "SALES_INVOICE", "ASSET") is formatted for display —
  // every other word gets Title Case (first letter capital, rest lowercase).
  const ABBR_WORDS = new Set([
    "GDS", "FOP", "TDS", "TCS", "PNR", "GST", "IGST", "CGST", "SGST", "HSN", "PAN",
    "IFSC", "SWIFT", "ROE", "JV", "ERP", "SSR", "K3", "YQ", "YR", "ID", "COA",
    "LCC", "FSC", "OSC", "TRN", "VAT", "INR", "AED", "USD", "PAX", "OK", "FY",
    "CSV", "PDF", "URL", "API", "SQL", "DB", "DMC", "BSP", "MIS", "OTP", "MFA", "IATA",
  ]);
  function titleCaseLabel(str) {
    return String(str || "")
      .split(/[_ ]+/)
      .map((w) => {
        if (!w) return w;
        const upper = w.toUpperCase();
        if (ABBR_WORDS.has(upper)) return upper;
        return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase();
      })
      .join(" ");
  }
  function statusPill(status) {
    const tone = window.VoyagerHardcode.STATUS_MAP[status] || "neutral";
    return `<span class="pill pill-${tone}">${titleCaseLabel(status)}</span>`;
  }
  function currencyFor(country) {
    return country === "AE" ? "AED" : "INR";
  }

  // Shared digit/decimal-point filter for any "amount" field project-wide
  // - type="text" inputmode="decimal" plus this class, instead of a
  // native type="number" input, which silently resets its value to ""
  // (read as 0 by anything consuming it) on an intermediate-invalid
  // value like "12." while the user is still typing the fraction - this
  // looked like the field randomly resetting to 0.00 (the bug originally
  // fixed in ticket-entry.html's Passenger Fare modal, now shared here so
  // every other page's amount fields get the same fix for free just by
  // using this class, no per-page filter to hand-write).
  // Delegated on `document` so it also covers rows built dynamically
  // after this script has already run (e.g. Supplier Master's Commission
  // Rules grid, Voucher Entry's line rows).
  document.addEventListener("input", (e) => {
    if (!e.target.matches || !e.target.matches(".dom-amount")) return;
    let v = e.target.value.replace(/[^0-9.]/g, "");
    const firstDot = v.indexOf(".");
    if (firstDot !== -1) v = v.slice(0, firstDot + 1) + v.slice(firstDot + 1).replace(/\./g, "");
    if (v !== e.target.value) e.target.value = v;
  });
  // Clicking/tabbing into an amount field selects its current text (e.g.
  // the default "0.00") so typing straight away overwrites it, instead of
  // the user having to manually delete the 0 first.
  document.addEventListener("focus", (e) => {
    if (e.target.matches && e.target.matches(".dom-amount")) e.target.select();
  }, true);

  window.VoyagerUtil = { fmtMoney, fmtAmt, fmtDate, statusPill, currencyFor, titleCaseLabel, loadDecimalPlaces, getDecimalPlaces };
})(window);
