/**
 * Invoice print templates - one place that turns an invoice's data into the
 * printable HTML, shared by every print button (Booking / Reschedule /
 * Cancellation on ticket-entry.html, SSR Updation) and by Company Master's
 * "Choose Invoice Template" previews. Which template prints is chosen per
 * company (CompanyMaster.invoice_template).
 *
 *   "classic" - Tax Invoice (the project's original layout)
 *   "payment" - Payment Invoice (company / GST block, Trip ID, passenger
 *               table, fare table and a Total Due summary)
 *
 * Every template reads the same normalized data object - see sampleData()
 * for its full shape.
 */
(function (window) {
  const TEMPLATES = [
    { key: "classic", name: "Template 1", description: "The original layout - company header, Billed To, item table and HSN/SAC tax summary." },
    { key: "payment", name: "Template 2", description: "Proforma-style layout - company & GST block, Trip ID, passenger and fare tables, Total Due summary, HSN/SAC GST table." },
  ];

  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const n2 = (v) => (Number(v) || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const rate = (r) => `${Number((Number(r) || 0).toFixed(2))}%`;

  // Indian grouping: Crore, Lakh, Thousand, Hundred.
  function amountInWords(amount, currency) {
    const ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
      "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"];
    const tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"];
    const twoDigits = (x) => (x < 20 ? ones[x] : `${tens[Math.floor(x / 10)]}${x % 10 ? " " + ones[x % 10] : ""}`);
    const threeDigits = (x) => [Math.floor(x / 100) ? `${ones[Math.floor(x / 100)]} Hundred` : "", x % 100 ? twoDigits(x % 100) : ""].filter(Boolean).join(" ");
    const words = (x) => {
      if (x === 0) return "Zero";
      const parts = [];
      const crore = Math.floor(x / 10000000); x %= 10000000;
      const lakh = Math.floor(x / 100000); x %= 100000;
      const thousand = Math.floor(x / 1000); x %= 1000;
      if (crore) parts.push(`${words(crore)} Crore`);
      if (lakh) parts.push(`${twoDigits(lakh)} Lakh`);
      if (thousand) parts.push(`${twoDigits(thousand)} Thousand`);
      if (x) parts.push(threeDigits(x));
      return parts.join(" ");
    };
    const abs = Math.abs(Math.round((Number(amount) || 0) * 100));
    const rupees = Math.floor(abs / 100), paise = abs % 100;
    return `${(currency || "INR").trim()} ${words(rupees)}${paise ? ` and ${twoDigits(paise)} paise` : ""} Only.`;
  }

  // "BANK NAME , BRANCH , A/c Holder , CA-123456 , IFSC - ABCD0001 , SWIFT - ..." -
  // the Payment Invoice's Bank Info row (Company Master > Bank Details).
  function bankLine(co) {
    co = co || {};
    return [co.bank_name, co.bank_branch, co.bank_account_holder,
      co.bank_account_no && `A/c No. ${co.bank_account_no}`, co.bank_ifsc && `IFSC - ${co.bank_ifsc}`,
      co.bank_swift && `SWIFT - ${co.bank_swift}`].filter(Boolean).join(" , ");
  }
  const sealHtml = (d, cls) => (d.company.seal ? `<img class="${cls}" src="${d.company.seal}" alt="" />` : "");
  const logoSrc = (d) => d.company.logo || new URL("assets/img/travel-agency-logo.png", window.location.href).href;
  const companyLine = (c) => [esc(c.address || "").replace(/\n/g, "<br/>"), [c.state, c.pincode].filter(Boolean).map(esc).join(" - ")].filter(Boolean).join(", ");

  // ---------------------------------------------------------------- classic
  function classic(d) {
    const c = d.company;
    const cols = d.columns;
    const lineRows = d.lines.map((l) => `<tr>${cols.map((col) => {
      const v = l[col.key];
      const isNum = col.align === "r";
      return `<td${isNum ? ' class="r"' : (col.align === "c" ? ' style="text-align:center;"' : "")}>${isNum ? n2(v) : esc(v)}</td>`;
    }).join("")}</tr>`).join("");
    return `<!DOCTYPE html><html><head><meta charset="UTF-8"><title>${esc(d.invoiceNo || d.docTitle)}</title>
      <style>
        @page { size: A4; margin: 12mm; }
        * { box-sizing: border-box; }
        body { font-family: Arial, Helvetica, sans-serif; font-size: 11px; color: #000; margin: 0; }
        table, th, td { font-size: 11px; font-family: inherit; }
        .inv { border: 1px solid #000; }
        .sec { border-bottom: 1px solid #000; padding: 6px 8px; }
        .head { text-align: center; position: relative; min-height: 96px; }
        .head .logo { position: absolute; left: 8px; top: 24px; }
        .title { font-weight: bold; font-size: 13px; margin-bottom: 8px; }
        .cname { font-weight: bold; font-size: 17px; }
        .grid2 { display: flex; } .grid2 > div { flex: 1; }
        .kv td { padding: 2px 4px 6px 0; vertical-align: top; }
        table { border-collapse: collapse; width: 100%; }
        .items th, .items td { border-left: 1px solid #000; padding: 3px 5px; }
        .items th:first-child, .items td:first-child { border-left: none; }
        .items th { border-bottom: 1px solid #000; font-weight: normal; }
        .items td.r, .items th.r, .tax td.r { text-align: right; }
        .items tbody td { height: 16px; vertical-align: top; }
        .items tr.fill td { height: ${Math.max(140 - d.lines.length * 16, 30)}px; }
        .items tr.gt td { border-top: 1px solid #000; font-weight: bold; }
        .tax th, .tax td { border: 1px solid #000; padding: 2px 4px; }
        .words { padding: 4px 8px; border-bottom: 1px solid #000; }
        .foot { display: flex; min-height: 90px; }
        .foot .terms { flex: 1; padding: 6px 8px; border-right: 1px solid #000; font-weight: bold; }
        .foot .terms .terms-text { font-weight: normal; margin-top: 4px; line-height: 1.5; }
        .foot .sign { width: 230px; padding: 6px 8px; text-align: center; font-weight: bold; display: flex; flex-direction: column; justify-content: space-between; }
        .foot .sign span { font-weight: normal; }
        .foot .sign .seal { display: block; margin: 4px auto; max-height: 70px; max-width: 160px; object-fit: contain; }
      </style></head><body>
      <div class="inv">
        <div class="sec head">
          <div class="title">${esc(d.docTitle)}</div>
          <div class="logo"><img src="${logoSrc(d)}" alt="" style="max-height:52px; max-width:170px;" /></div>
          <div class="cname">${esc(c.name)}</div>
          <div>${companyLine(c)}</div>
          ${c.gst_no ? `<div style="font-weight:bold; margin-top:6px;">GSTIN : ${esc(c.gst_no)}</div>` : ""}
          <div style="font-weight:bold;">${c.phone ? `Tel : ${esc(c.phone)}` : ""}${c.phone && c.email ? "&nbsp; " : ""}${c.email ? `Email : ${esc(c.email)}` : ""}</div>
        </div>
        <div class="sec grid2">
          <div><table class="kv">
            <tr><td style="width:110px; white-space:nowrap;">${esc(d.invoiceNoLabel)}</td><td>: ${esc(d.invoiceNo)}</td></tr>
            <tr><td>${esc(d.invoiceDateLabel)}</td><td>: ${esc(d.invoiceDate)}</td></tr>
            <tr><td>${esc(d.refLabel)}</td><td>: ${esc(d.refValue)}</td></tr>
            <tr><td>Place of Supply</td><td>: ${esc(d.placeOfSupply)}</td></tr>
          </table></div>
          <div><b>Billed To :</b><br/>${esc(d.customer.name)}<br/>${(d.customer.address || "").split("\n").map(esc).join("<br/>")}<br/><br/>${esc(d.customer.state)}${d.customer.gst_no ? ` - ${esc(d.customer.gst_no)}` : ""}</div>
        </div>
        <div class="sec"><table class="kv" style="width:auto;">
          ${d.infoRows.map(([k, v]) => `<tr><td style="width:110px; white-space:nowrap; padding-bottom:0;">${esc(k)}</td><td style="padding-bottom:0;">: ${esc(v)}</td></tr>`).join("")}
        </table></div>
        <table class="items">
          <thead><tr>${cols.map((col) => `<th${col.align === "r" ? ' class="r"' : ""}${col.width ? ` style="width:${col.width};"` : ""}>${esc(col.label)}</th>`).join("")}</tr></thead>
          <tbody>
            ${lineRows}
            <tr class="fill">${"<td></td>".repeat(cols.length)}</tr>
            <tr class="gt"><td colspan="${cols.length - 1}" style="border-left:none;">&nbsp;&nbsp;&nbsp;Grand Total</td><td class="r">${n2(d.grandTotal)}</td></tr>
          </tbody>
        </table>
        <div class="words" style="border-top:1px solid #000;">Total Amount (In Words): ${esc(d.amountWords)}</div>
        <table class="tax">
          <thead>
            <tr><th rowspan="2">HSN/SAC</th><th>Taxable</th><th colspan="2">IGST</th><th colspan="2">CGST</th><th colspan="2">SGST/UTGST</th><th rowspan="2">Total<br/>Tax Amount</th></tr>
            <tr><th>Value</th><th>Rate</th><th>Amount</th><th>Rate</th><th>Amount</th><th>Rate</th><th>Amount</th></tr>
          </thead>
          <tbody>
            <tr><td>${esc(c.hsn)}</td><td class="r">${n2(d.taxable)}</td>
              <td class="r">${d.intraState ? "" : rate(d.gstRate)}</td><td class="r">${n2(d.igst)}</td>
              <td class="r">${d.intraState ? rate(d.gstRate / 2) : ""}</td><td class="r">${n2(d.cgst)}</td>
              <td class="r">${d.intraState ? rate(d.gstRate / 2) : ""}</td><td class="r">${n2(d.sgst)}</td><td class="r">${n2(d.totalTax)}</td></tr>
            <tr><td class="r"><b>Total</b></td><td class="r">${n2(d.taxable)}</td><td></td><td class="r">${n2(d.igst)}</td><td></td><td class="r">${n2(d.cgst)}</td><td></td><td class="r">${n2(d.sgst)}</td><td class="r">${n2(d.totalTax)}</td></tr>
          </tbody>
        </table>
        <div class="words">Tax Amount (In Words): ${esc(d.taxWords)}</div>
        <div class="foot">
          <div class="terms">Terms and Conditions:${c.terms ? `<div class="terms-text">${esc(c.terms).replace(/\n/g, "<br/>")}</div>` : ""}</div>
          <div class="sign">${esc(c.name)}${sealHtml(d, "seal")}<span>Authorised Signatory</span></div>
        </div>
      </div></body></html>`;
  }

  // ---------------------------------------------------------------- payment
  // Payment Invoice - laid out like the Riya "Proforma Invoice": centred logo,
  // company block with GST / PAN / User ID / CIN, customer block with Invoice
  // No / Date / Trip ID, passenger table (one line per sector), fare table
  // (Document Number / Fare / Tax / SSR / Discount / Surcharge / PG Charges /
  // Markup / Service Fee / Total), a (+) Total / GST / TDS / Total Due
  // summary, amount in words + tax breakup, HSN/SAC GST table, Terms and
  // Conditions box, seal and the "ORIGINAL FOR RECIPIENT" footer.
  function payment(d) {
    const c = d.company;
    const cu = d.customer;
    const num = (v) => Number(v) || 0;
    const kv = (rows) => rows.filter(([, v]) => v).map(([k, v]) => `<tr><td class="k">${esc(k)}</td><td class="v">${esc(v)}</td></tr>`).join("");
    const multi = (v) => String(v || "").split(",").map((x) => esc(x.trim())).filter(Boolean).join("<br/>");
    const paxRows = d.lines.map((l) => `<tr><td>${esc(l.pax)}</td><td class="c">${esc(l.paxType)}</td><td class="c">${esc(l.productType)}</td>
      <td class="c">${esc(l.gdsPnr)}</td><td class="c">${esc(l.airlineName || l.airline)}</td><td class="c">${esc(l.ticketNo)}</td>
      <td class="c">${multi(l.cls)}</td><td class="c">${multi(l.sector)}</td><td class="c">${multi(l.flight)}</td><td class="c">${multi(l.travelDate)}</td></tr>`).join("");

    // Fare table. Total (per line) = the billed amount before GST and TDS -
    // both are added back in the summary below, like the reference invoice.
    // GST here is customer GST + supplier GST (the same figure as the HSN/SAC
    // GST table), so the supplier GST sits in the GST breakup, not in Total.
    const lineGst = (l) => (l.bkCgst != null ? num(l.bkIgst) + num(l.bkCgst) + num(l.bkSgst)
      : l.fullCgst != null ? num(l.fullIgst) + num(l.fullCgst) + num(l.fullSgst)
      : num(l.fareGst ?? l.gst));
    const lineTds = (l) => num(l.custTds);
    // A line's own Template 2 figures (t2Tax / t2Markup / t2ServiceFee - set
    // for a Reschedule print) override the common ones.
    const tax = (l) => num(l.t2Tax ?? l.tax);
    const mgmt = (l) => num(l.t2Markup ?? l.markup);
    const svc = (l) => num(l.t2ServiceFee ?? l.fareServiceFee ?? l.serviceFee);
    // Credit Note: Total = Fare + Tax + SSR - Discount - Service Fee (the
    // cancellation screen's own columns), and the summary takes the GST OFF
    // (refunded with the service fee) and adds the TDS, which lands on the
    // credit note's real amount. Any other invoice: the billed amount before
    // GST and TDS, both added back in the summary.
    const cn = !!d.creditNote;
    const lineTotal = (l) => (cn ? num(l.fare) + tax(l) + num(l.ssr) - num(l.discount) - svc(l)
      : num(l.amount) - lineGst(l) - lineTds(l));
    const fareRows = d.lines.map((l) => `<tr><td class="c">${esc(l.ticketNo || l.pax)}</td><td class="r">${n2(l.fare)}</td><td class="r">${n2(tax(l))}</td>
      <td class="r">${n2(l.ssr)}</td><td class="r">${n2(l.discount)}</td><td class="r">${n2(0)}</td><td class="r">${n2(l.pgCharges)}</td>
      <td class="r">${n2(mgmt(l))}</td><td class="r">${n2(svc(l))}</td><td class="r">${n2(lineTotal(l))}</td></tr>`).join("");
    const sum = (f) => d.lines.reduce((s, l) => s + f(l), 0);
    const total = sum(lineTotal), gstAmt = sum(lineGst), tdsAmt = sum(lineTds);
    const half = Math.round((gstAmt / 2) * 100) / 100;
    const totalAmount = total + (cn ? -gstAmt : gstAmt) + tdsAmt;
    const gstSign = cn ? "(-)" : "(+)";
    const words = amountInWords(totalAmount, d.currency)
      .replace(/^(\S+) /, "$1 - ").replace(/ and (.+) paise Only\.$/, " Rupees $1 Paisa").replace(/ Only\.$/, " Rupees");

    // Tax breakup line - Tax:YQ:../YR:../K3:../OT:.. summed over the lines.
    const parts = {};
    d.lines.forEach((l) => Object.entries(l.taxParts || {}).forEach(([k, v]) => { parts[k] = (parts[k] || 0) + num(v); }));
    const taxLine = Object.entries(parts).filter(([, v]) => v).map(([k, v]) => `${k}:${Number(v.toFixed(2))}`).join("/");

    // Place of Supply with its GST state code, e.g. TAMIL NADU (33).
    const stateCode = /^\d{2}/.test(cu.gst_no || "") ? cu.gst_no.slice(0, 2) : (d.intraState && /^\d{2}/.test(c.gst_no || "") ? c.gst_no.slice(0, 2) : "");
    const pos = d.placeOfSupply ? `${String(d.placeOfSupply).toUpperCase()}${stateCode ? ` (${stateCode})` : ""}` : "-";
    const cg = d.intraState ? rate(d.gstRate / 2) : rate(0), ig = d.intraState ? rate(0) : rate(d.gstRate);
    const gstRow = (label, taxable, cgst, sgst, igst) => `<tr><td>${label}</td><td>${esc(c.hsn)}</td><td class="r">${n2(taxable)}</td><td class="r">${cg}</td><td class="r">${n2(cgst)}</td>
      <td class="r">${cg}</td><td class="r">${n2(sgst)}</td><td class="r">${ig}</td><td class="r">${n2(igst)}</td><td class="r">${n2(num(cgst) + num(sgst) + num(igst))}</td></tr>`;

    return `<!DOCTYPE html><html><head><meta charset="UTF-8"><title>${esc(d.invoiceNo || d.docTitle)}</title>
      <style>
        @page { size: A4; margin: 10mm; }
        * { box-sizing: border-box; }
        body { font-family: Verdana, Arial, Helvetica, sans-serif; font-size: 9px; color: #000; margin: 0; }
        table { border-collapse: collapse; width: 100%; }
        th, td { font-size: 9px; font-family: inherit; }
        .page { border: 1px solid #CCC; padding: 10px 12px 14px; }
        .logo { text-align: center; padding: 4px 0 8px; }
        .logo img { max-height: 60px; max-width: 230px; }
        .rule { border-top: 3px solid #000; margin: 0 0 10px; }
        .top { display: flex; justify-content: space-between; gap: 20px; }
        .co { font-weight: bold; line-height: 2; text-transform: uppercase; }
        .kv { width: auto; }
        .kv td { padding: 2px 0; vertical-align: top; font-weight: bold; line-height: 1.6; }
        .kv td.k { white-space: nowrap; padding-right: 30px; }
        .doc-title { text-align: center; font-weight: bold; font-size: 10px; margin: 14px 0 10px; }
        .cust { font-weight: bold; line-height: 1.7; }
        .meta { width: auto; margin-top: 12px; }
        .meta td { padding: 3px 0; font-weight: bold; line-height: 1.5; }
        .meta td.k { width: 210px; }
        .grid { margin-top: 14px; }
        .grid th { font-weight: bold; padding: 2px 4px; border: 1px solid #BBB; background: #FFF; }
        .grid td { padding: 1px 4px; vertical-align: top; }
        .grid.pax td { border-left: 1px solid #BBB; border-right: 1px solid #BBB; }
        .grid.pax tr:last-child td { border-bottom: 1px solid #BBB; }
        .grid.fare td { border: 1px solid #BBB; }
        .grid .c { text-align: center; } .grid .r { text-align: right; }
        .grid th.l { text-align: left; }
        .grid tr.tot td { font-weight: bold; }
        .sum-wrap { display: flex; justify-content: flex-end; margin-top: 12px; }
        .sum { width: 360px; }
        .sum td { padding: 5px 0; font-weight: bold; font-size: 9.5px; }
        .sum td.r { text-align: right; }
        .sum tr.gap td { padding-top: 22px; }
        .words { border: 1px solid #BBB; padding: 2px 4px; font-weight: bold; margin-top: 10px; line-height: 1.5; }
        .gst { margin-top: 12px; }
        .gst th { border: 1px solid #BBB; padding: 2px 4px; font-weight: bold; text-align: left; }
        .gst td { padding: 1px 4px; border-left: 1px solid #BBB; border-right: 1px solid #BBB; }
        .gst tr.tot td { font-weight: bold; border: 1px solid #BBB; }
        .gst .r { text-align: right; }
        .notes { border: 2px solid #000; margin-top: 14px; }
        .notes td { padding: 3px 6px; vertical-align: top; border-bottom: 1px solid #000; line-height: 1.6; }
        .notes td.k { font-weight: bold; width: 1%; white-space: nowrap; padding-right: 10px; }
        .seal { display: block; margin: 28px 0 8px 220px; max-height: 105px; max-width: 160px; object-fit: contain; }
        .orig { text-align: center; font-weight: bold; line-height: 1.6; margin-top: 10px; }
      </style></head><body>
      <div class="page">
        <div class="logo"><img src="${logoSrc(d)}" alt="" /></div>
        <div class="rule"></div>
        <div class="top">
          <div class="co">${esc(c.name)}<br/>${esc(c.address || "").replace(/\n/g, "<br/>")}${c.state ? `<br/>${esc(c.state)}${c.pincode ? ` - ${esc(c.pincode)}` : ""}` : ""}</div>
          <table class="kv">${kv([["GST Reg. No.", c.gst_no], ["PAN No.", c.pan_number], ["User ID", d.userName], ["CIN No.", c.cin_number]])}</table>
        </div>
        <div class="doc-title">${esc(d.docTitleCase)}</div>
        <div class="rule"></div>
        <div class="top">
          <div class="cust">${esc([cu.code, cu.name].filter(Boolean).join(" - "))}<br/>${(cu.address || "").split("\n").map(esc).join(" ")}</div>
          <table class="kv">${kv([[d.invoiceNoLabel, d.invoiceNo], [d.invoiceDateLabel, d.invoiceDate], [d.refLabel === "Booking ID" ? "Trip ID" : d.refLabel, d.refValue]])}</table>
        </div>
        <table class="meta">
          <tr><td class="k">PAN No :</td><td>${esc(cu.pan || "-")}</td></tr>
          <tr><td class="k">GST Reg. No :</td><td>${esc(cu.gst_no || "-")}</td></tr>
          <tr><td class="k">Place of Supply :</td><td>${esc(pos)}</td></tr>
          <tr><td class="k">HSN Code :</td><td>${esc(c.hsn)}</td></tr>
          <tr><td class="k">Tax Payable on Reverse Charge :</td><td>No</td></tr>
          <tr><td class="k">IRN No :</td><td>-</td></tr>
        </table>
        <table class="grid pax">
          <thead><tr><th class="l">Passenger Name</th><th>Passenger Type</th><th>Product Type</th><th>GDS PNR</th><th>Airline</th><th>Ticket No</th><th>Class</th><th>Sector</th><th>Travel Details</th><th>Travel Date</th></tr></thead>
          <tbody>${paxRows}</tbody>
        </table>
        <table class="grid fare">
          <thead><tr><th class="l">Ticket No</th><th>Fare</th><th>Tax</th><th>SSR</th><th>Discount</th><th>Surcharge</th><th>PG Charges</th><th>Markup</th><th>Service Fee</th><th>Total</th></tr></thead>
          <tbody>${fareRows}
            <tr class="tot"><td class="c">Total</td><td class="r">${n2(sum((l) => num(l.fare)))}</td><td class="r">${n2(sum(tax))}</td><td class="r">${n2(sum((l) => num(l.ssr)))}</td>
              <td class="r">${n2(sum((l) => num(l.discount)))}</td><td class="r">${n2(0)}</td><td class="r">${n2(sum((l) => num(l.pgCharges)))}</td>
              <td class="r">${n2(sum(mgmt))}</td><td class="r">${n2(sum(svc))}</td><td class="r">${n2(total)}</td></tr>
          </tbody>
        </table>
        <div class="sum-wrap"><table class="sum">
          <tr><td>(+) Total</td><td class="r">${n2(total)}</td></tr>
          ${d.intraState
            ? `<tr><td>${gstSign} CGST (${rate(d.gstRate / 2)})</td><td class="r">${n2(half)}</td></tr><tr><td>${gstSign} SGST (${rate(d.gstRate / 2)})</td><td class="r">${n2(gstAmt - half)}</td></tr>`
            : `<tr><td>${gstSign} IGST (${rate(d.gstRate)})</td><td class="r">${n2(gstAmt)}</td></tr>`}
          <tr><td>(+) TDS Amount</td><td class="r">${n2(tdsAmt)}</td></tr>
          <tr><td>Total Amount</td><td class="r">${n2(totalAmount)}</td></tr>
          <tr><td>(-) Payments</td><td class="r">0.00</td></tr>
          <tr class="gap"><td>Total Due (${esc(d.currency)})</td><td class="r">${n2(totalAmount)}</td></tr>
        </table></div>
        <div class="words">Amount (in Words) : ${esc(words)}${taxLine ? `<br/>Tax:${esc(taxLine)}` : ""}</div>
        <table class="gst">
          <thead><tr><th>Description</th><th>HSN /SAC</th><th>TaxableValue</th><th>CGST%</th><th>CGST Amt.</th><th>SGST/UGST %</th><th>SGST/UGST Amt.</th><th>IGST %</th><th>IGST Amt.</th><th>Total GST Amount</th></tr></thead>
          <tbody>
            ${gstRow("Service Fee", d.taxable, d.cgst, d.sgst, d.igst)}
            ${gstRow("Surcharge Amount", 0, 0, 0, 0)}
            <tr class="tot"><td colspan="2" class="r">Total</td><td class="r">${n2(d.taxable)}</td><td></td><td class="r">${n2(d.cgst)}</td><td></td><td class="r">${n2(d.sgst)}</td><td></td><td class="r">${n2(d.igst)}</td><td class="r">${n2(d.totalTax)}</td></tr>
          </tbody>
        </table>
        <table class="notes">
          <tr><td class="k">Terms and Conditions :</td><td style="height:48px;">${esc(c.terms || "").replace(/\n/g, "<br/>")}</td></tr>
        </table>
        ${sealHtml(d, "seal")}
      </div>
      <div class="orig">ORIGINAL FOR RECIPIENT<br/>This is computer generated invoice hence no signature required.</div>
      </body></html>`;
  }

  function render(key, d) {
    return (key === "payment" ? payment : classic)(d);
  }

  // Printed through a hidden iframe (no popup window to get blocked). The
  // PDF file name ("Save as PDF") follows the page title - pdfName.
  function print(html, pdfName) {
    let frame = document.getElementById("invoice-print-frame");
    if (frame) frame.remove();
    frame = document.createElement("iframe");
    frame.id = "invoice-print-frame";
    frame.style.cssText = "position:fixed; right:0; bottom:0; width:0; height:0; border:0; visibility:hidden;";
    document.body.appendChild(frame);
    const doc = frame.contentWindow.document;
    doc.open();
    doc.write(html);
    doc.close();
    const pageTitle = document.title;
    document.title = pdfName || pageTitle;
    const restoreTitle = () => { document.title = pageTitle; };
    frame.contentWindow.addEventListener("afterprint", restoreTitle);
    // Wait for the logo/seal to load, or they can print blank.
    const imgs = Array.from(doc.images);
    Promise.all(imgs.map((img) => (img.complete ? null : new Promise((res) => { img.onload = img.onerror = res; }))))
      .then(() => {
        frame.contentWindow.focus();
        frame.contentWindow.print();
        setTimeout(restoreTitle, 1000);
      });
  }

  // Example invoice for Company Master's template previews - the company's
  // own name/address/GST/logo/seal, sample booking figures.
  function sampleData(co) {
    co = co || {};
    const gstRate = 18, serviceFee = 300, gst = 54;
    const lines = [
      { no: 1, serType: "Airline", pax: "Mr. Arjun Kumar", paxType: "ADULT", productType: "AIR - INT", gdsPnr: "A9EFMQ", airline: "6E",
        ticketNo: "0652417529001", cls: "Y", sector: "MAA-DXB", flight: "6E 1453", travelDate: "15/11/2026",
        basic: 12915, other: 9631, ssr: 450, serviceFee, igst: 0, cgst: 27, sgst: 27, amount: 23350,
        fare: 12915, tax: 9631, discount: 0, markup: 0, gst, custTds: 0, pgCharges: 0, airlineName: "IndiGo",
        taxParts: { YQ: 5200, YR: 431, K3: 2400, OT: 1600 } },
    ];
    lines[0].amount = lines[0].fare + lines[0].tax + lines[0].ssr + serviceFee + gst;
    lines[0].other = lines[0].amount - lines[0].basic - lines[0].ssr - serviceFee - gst;
    const grandTotal = lines[0].amount;
    return {
      docTitle: "TAX INVOICE", docTitleCase: "Tax Invoice",
      company: {
        name: co.company_name || "Your Company", address: co.address || "", state: co.state || "", pincode: co.pincode || "",
        gst_no: co.gst_no || "", pan_number: co.pan_number || "", cin_number: co.cin_number || "", email: co.email || "",
        phone: co.mobile || co.telephone || "", hsn: co.hsn_sac || "998551", logo: co.logo_base64 || "", seal: co.seal_base64 || "",
        terms: co.terms_conditions || "", bank: bankLine(co),
      },
      invoiceNoLabel: "Invoice No", invoiceNo: "TA/TAX/00001/26-27", invoiceDateLabel: "Invoice Date", invoiceDate: "15/10/2026",
      refLabel: "Booking ID", refValue: "TT01HJ0001", userName: "ADMIN",
      customer: { name: "Sample Customer Pvt Ltd", code: "CUS-0001", address: "No. 1, Sample Street\nChennai", state: co.state || "Tamil Nadu", gst_no: "33AAAAA0000A1Z5", pan: "AAAAA0000A" },
      placeOfSupply: co.state || "Tamil Nadu",
      infoRows: [["Date of Travel", "15/11/2026"], ["Airline PNR", "A9EFMQ"], ["Sector", "MAA-DXB"]],
      columns: TICKET_COLUMNS, lines, grandTotal, taxable: serviceFee, gstRate, intraState: true,
      igst: 0, cgst: 27, sgst: 27, totalTax: gst, tds: 0, currency: "INR",
      amountWords: amountInWords(grandTotal, "INR"), taxWords: amountInWords(gst, "INR"),
    };
  }

  // Classic item-table columns for Booking / Reschedule / Cancellation.
  const TICKET_COLUMNS = [
    { label: "# No", key: "no", align: "c", width: "30px" }, { label: "Ser. Type", key: "serType", align: "c", width: "55px" },
    { label: "Pax Name", key: "pax" }, { label: "Basic Fare", key: "basic", align: "r" }, { label: "Other Taxes", key: "other", align: "r" },
    { label: "SSR", key: "ssr", align: "r" }, { label: "Service Fee", key: "serviceFee", align: "r" }, { label: "IGST", key: "igst", align: "r" },
    { label: "CGST", key: "cgst", align: "r" }, { label: "SGST", key: "sgst", align: "r" }, { label: "Amount", key: "amount", align: "r" },
  ];

  window.VoyagerInvoice = { TEMPLATES, TICKET_COLUMNS, render, print, amountInWords, sampleData, bankLine };
})(window);
