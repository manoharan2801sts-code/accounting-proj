(function (window) {
  function fmtMoney(value, ccy) {
    const n = Number(value) || 0;
    return `${ccy} ${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  function fmtDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
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
  window.VoyagerUtil = { fmtMoney, fmtDate, statusPill, currencyFor, titleCaseLabel };
})(window);
