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
    { key: "proforma", name: "Template 3", description: "Performa layout - From / To blocks, flight details, passenger fare table (YQ / taxes / SSR split), Gross to Net Amount summary." },
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
    // Tax table: a tax's Rate / Amount pair is shown only when it has an
    // amount (intra-state -> CGST + SGST, inter-state -> IGST).
    const taxCols = [
      { label: "IGST", rate: d.intraState ? "" : rate(d.gstRate), amount: d.igst },
      { label: "CGST", rate: d.intraState ? rate(d.gstRate / 2) : "", amount: d.cgst },
      { label: "SGST/UTGST", rate: d.intraState ? rate(d.gstRate / 2) : "", amount: d.sgst },
    ].filter((t) => (Number(t.amount) || 0) !== 0);
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
            <tr><th rowspan="2">HSN/SAC</th><th>Taxable</th>${taxCols.map((t) => `<th colspan="2">${t.label}</th>`).join("")}<th rowspan="2">Total<br/>Tax Amount</th></tr>
            <tr><th>Value</th>${taxCols.map(() => "<th>Rate</th><th>Amount</th>").join("")}</tr>
          </thead>
          <tbody>
            <tr><td>${esc(c.hsn)}</td><td class="r">${n2(d.taxable)}</td>
              ${taxCols.map((t) => `<td class="r">${t.rate}</td><td class="r">${n2(t.amount)}</td>`).join("")}<td class="r">${n2(d.totalTax)}</td></tr>
            <tr><td class="r"><b>Total</b></td><td class="r">${n2(d.taxable)}</td>${taxCols.map((t) => `<td></td><td class="r">${n2(t.amount)}</td>`).join("")}<td class="r">${n2(d.totalTax)}</td></tr>
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
    // Trip table - one row for the whole invoice: each column lists its
    // distinct values across the passengers (passenger names / types / ticket
    // numbers sit in the fare table below).
    const uniq = (f) => multi([...new Set(d.lines.flatMap((l) => String(f(l) || "").split(",")).map((x) => x.trim()).filter(Boolean))].join(","));
    const airlinePnr = d.airlinePnr || ((d.infoRows || []).find(([k]) => /airline pnr/i.test(k)) || [])[1] || "";
    const tripRow = `<tr><td class="c">${uniq((l) => l.productType)}</td><td class="c">${uniq((l) => l.gdsPnr)}</td><td class="c">${multi(airlinePnr)}</td>
      <td class="c nw">${uniq((l) => l.airlineName || l.airline)}</td><td class="c">${uniq((l) => l.cls)}</td><td class="c nw">${uniq((l) => l.sector)}</td>
      <td class="c">${uniq((l) => l.flight)}</td><td class="c">${uniq((l) => l.travelDate)}</td></tr>`;

    // Fare table. Total (per line) = the billed amount before GST and TDS -
    // both are added back in the summary below, like the reference invoice.
    // GST here is customer GST + supplier GST (the same figure as the HSN/SAC
    // GST table), so the supplier GST sits in the GST breakup, not in Total.
    const lineGst = (l) => (l.bkCgst != null ? num(l.bkIgst) + num(l.bkCgst) + num(l.bkSgst)
      : l.fullCgst != null ? num(l.fullIgst) + num(l.fullCgst) + num(l.fullSgst)
      : num(l.fareGst ?? l.gst));
    const lineTds = (l) => num(l.custTds);
    // A line's own Template 2 figures (t2Tax / t2ServiceFee - set for a
    // Reschedule print) override the common ones. (No Markup column.)
    const tax = (l) => num(l.t2Tax ?? l.tax);
    const svc = (l) => num(l.t2ServiceFee ?? l.fareServiceFee ?? l.serviceFee);
    // Credit Note: Total = Fare + Tax + SSR - Discount - Service Fee (the
    // cancellation screen's own columns), and the summary takes the GST OFF
    // (refunded with the service fee) and adds the TDS, which lands on the
    // credit note's real amount. Any other invoice: the billed amount before
    // GST and TDS, both added back in the summary.
    const cn = !!d.creditNote;
    const lineTotal = (l) => (cn ? num(l.fare) + tax(l) + num(l.ssr) - num(l.discount) - svc(l)
      : num(l.amount) - lineGst(l) - lineTds(l));
    const fareRows = d.lines.map((l) => `<tr><td>${esc(l.pax)}</td><td class="c">${esc(l.paxType)}</td><td class="c nw">${esc(l.ticketNo)}</td>
      <td class="r">${n2(l.fare)}</td><td class="r">${n2(tax(l))}</td>
      <td class="r">${n2(l.ssr)}</td><td class="r">${n2(l.discount)}</td><td class="r">${n2(l.pgCharges)}</td>
      <td class="r">${n2(svc(l))}</td><td class="r">${n2(lineTotal(l))}</td></tr>`).join("");
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
    // GST table: a tax's % / Amt. column pair is shown only when that tax has
    // an amount on this invoice - e.g. an intra-state bill shows CGST + SGST
    // and drops the all-zero IGST pair (inter-state: the reverse).
    const showCgst = num(d.cgst) !== 0, showSgst = num(d.sgst) !== 0, showIgst = num(d.igst) !== 0;
    const gstPair = (show, pct, amt) => (show ? `<td class="r">${pct}</td><td class="r">${n2(amt)}</td>` : "");
    const gstRow = (label, taxable, cgst, sgst, igst) => `<tr><td>${label}</td><td>${esc(c.hsn)}</td><td class="r">${n2(taxable)}</td>
      ${gstPair(showCgst, cg, cgst)}${gstPair(showSgst, cg, sgst)}${gstPair(showIgst, ig, igst)}<td class="r">${n2(num(cgst) + num(sgst) + num(igst))}</td></tr>`;
    const gstHead = `<th>Description</th><th>HSN /SAC</th><th>TaxableValue</th>`
      + (showCgst ? `<th>CGST%</th><th>CGST Amt.</th>` : "")
      + (showSgst ? `<th>SGST/UGST %</th><th>SGST/UGST Amt.</th>` : "")
      + (showIgst ? `<th>IGST %</th><th>IGST Amt.</th>` : "")
      + `<th>Total GST Amount</th>`;
    const gstTotalPair = (show, amt) => (show ? `<td></td><td class="r">${n2(amt)}</td>` : "");

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
        .grid .nw { white-space: nowrap; }
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
          <table class="kv">${kv([["GST Reg. No.", c.gst_no], ["PAN No.", c.pan_number], ["User Name", d.userName], ["CIN No.", c.cin_number]])}</table>
        </div>
        <div class="doc-title">${esc(d.docTitleCase)}</div>
        <div class="rule"></div>
        <div class="top">
          <div class="cust">${esc([cu.code, cu.name].filter(Boolean).join(" - "))}<br/>${(cu.address || "").split("\n").map(esc).join(" ")}</div>
          <table class="kv">${kv([[d.invoiceNoLabel, d.invoiceNo], [d.invoiceDateLabel, d.invoiceDate], [d.refLabel === "Booking ID" ? "SPNR" : d.refLabel, d.refValue]])}</table>
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
          <thead><tr><th>Product</th><th>GDS PNR</th><th>Airline PNR</th><th>Airline</th><th>Class</th><th>Sector</th><th>Flight No</th><th>Travel Date</th></tr></thead>
          <tbody>${tripRow}</tbody>
        </table>
        <table class="grid fare">
          <thead><tr><th class="l">Pax Name</th><th>Pax Type</th><th>Ticket No</th><th>Basic Fare</th><th>Other Taxes</th><th>SSR</th><th>Discount</th><th>PG Charges</th><th>Service Fee</th><th>Total</th></tr></thead>
          <tbody>${fareRows}
            <tr class="tot"><td class="c" colspan="3">Total</td><td class="r">${n2(sum((l) => num(l.fare)))}</td><td class="r">${n2(sum(tax))}</td><td class="r">${n2(sum((l) => num(l.ssr)))}</td>
              <td class="r">${n2(sum((l) => num(l.discount)))}</td><td class="r">${n2(sum((l) => num(l.pgCharges)))}</td>
              <td class="r">${n2(sum(svc))}</td><td class="r">${n2(total)}</td></tr>
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
          <thead><tr>${gstHead}</tr></thead>
          <tbody>
            ${gstRow("Service Fee", d.taxable, d.cgst, d.sgst, d.igst)}
            ${gstRow("Surcharge Amount", 0, 0, 0, 0)}
            <tr class="tot"><td colspan="2" class="r">Total</td><td class="r">${n2(d.taxable)}</td>${gstTotalPair(showCgst, d.cgst)}${gstTotalPair(showSgst, d.sgst)}${gstTotalPair(showIgst, d.igst)}<td class="r">${n2(d.totalTax)}</td></tr>
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

  // --------------------------------------------------------------- proforma
  // Template 3 - laid out like the "Performa Invoice" reference: Invoice Date
  // / Invoice No bar, From (company) / To (customer) blocks, a flight table
  // (Airlines / S PNR / Airlines PNR / GDS PNR / Flight Details / Sector /
  // Travel Date), a passenger table (Base Fare / YQ Tax / Other Taxes /
  // Baggage / Seat / Meal / Other SSR / Total) and a Gross -> Net Amount
  // summary with the amount in words, seal and bulleted Terms & Conditions.
  // Net Amount is always the invoice's real billed total (sum of each line's
  // amount); the summary rows are built to add up to it.
  function proforma(d) {
    const c = d.company;
    const cu = d.customer;
    const num = (v) => Number(v) || 0;
    const na = (v) => esc(v && String(v).trim() ? v : "N/A");
    const uniq = (vals) => [...new Set(vals.flatMap((v) => String(v || "").split(",")).map((v) => v.trim()).filter(Boolean))];
    const PAX = { ADULT: "ADT", CHILD: "CHD", INFANT: "INF" };
    const yq = (l) => num(l.yq ?? (l.taxParts || {}).YQ);
    const sum = (f) => d.lines.reduce((s, l) => s + f(l), 0);
    const r2 = (v) => Math.round(v * 100) / 100;

    // Summary - Gross = the passenger table's Total; GST = customer + supplier
    // GST (same figure every template prints); Service Fee = customer +
    // supplier Service Fee / Addl / SSR Service Fee.
    const lineGst = (l) => (l.bkCgst != null ? num(l.bkIgst) + num(l.bkCgst) + num(l.bkSgst)
      : l.fullCgst != null ? num(l.fullIgst) + num(l.fullCgst) + num(l.fullSgst)
      : num(l.fareGst ?? l.gst));
    const svc = (l) => num(l.t2ServiceFee ?? l.fareServiceFee ?? l.serviceFee);
    // Markup & other charges (markups, penalties; on a Credit Note the
    // markups / penalties kept back, net of any markup reversal) have no
    // summary row - they sit inside each passenger's Other Taxes, so the
    // passenger Total and Gross carry them. Worked out per passenger as
    // what's left of its amount once fare, Discount, Service Fee, GST and
    // TDS are accounted for, so the summary always adds up to Net Amount.
    // Same for Booking, Reschedule, Cancellation and SSR Updation.
    const baseTotal = (l) => num(l.fare) + num(l.tax) + num(l.baggage) + num(l.seat) + num(l.meal) + num(l.otherSsr);
    const otherCharges = (l) => r2(d.creditNote
      ? num(l.amount) - (baseTotal(l) - num(l.discount) - svc(l) - lineGst(l) + num(l.custTds))
      : num(l.amount) - (baseTotal(l) - num(l.discount) + svc(l) + lineGst(l) + num(l.custTds)));
    const otherTax = (l) => num(l.tax) - yq(l) + otherCharges(l);
    const rowTotal = (l) => num(l.fare) + yq(l) + otherTax(l) + num(l.baggage) + num(l.seat) + num(l.meal) + num(l.otherSsr);
    const gross = r2(sum(rowTotal));
    const commission = r2(sum((l) => num(l.discount)));
    const serviceFee = r2(sum(svc));
    const gstAmt = r2(sum(lineGst));
    const tdsAmt = r2(sum((l) => num(l.custTds)));
    const net = r2(sum((l) => num(l.amount)));
    const cgst = d.intraState ? r2(gstAmt / 2) : 0;
    const sgst = d.intraState ? r2(gstAmt - cgst) : 0;
    const igst = d.intraState ? 0 : gstAmt;
    const half = (Number(d.gstRate) || 0) / 2;
    const summary = [["", "Gross:", gross, true]];
    if (d.creditNote) {
      // Credit Note - the same rows as a Booking / Reschedule (one template
      // for Booking, Reschedule, Cancellation and SSR Updation): Service Fee
      // and its CGST / SGST / IGST each on their own row, kept back from the
      // refund (Less). Markups / penalties are inside Other Taxes (above).
      summary.push(["Less", "Discount", commission],
        ["Less", "Service Fee", serviceFee],
        ["Less", `CGST @${half.toFixed(2)}%`, cgst], ["Less", `SGST @${half.toFixed(2)}%`, sgst],
        ["Less", `IGST @${(d.intraState ? 0 : Number(d.gstRate) || 0).toFixed(2)}%`, igst],
        ["Add", "TDS Deducted", tdsAmt]);
    } else {
      // Markups / penalties are inside Other Taxes (above) - no row of their own.
      summary.push(["Less", "Discount", commission],
        ["Add", "Service Fee", serviceFee],
        ["Add", `CGST @${half.toFixed(2)}%`, cgst], ["Add", `SGST @${half.toFixed(2)}%`, sgst],
        ["Add", `IGST @${(d.intraState ? 0 : Number(d.gstRate) || 0).toFixed(2)}%`, igst],
        ["Add", "TDS Deducted", tdsAmt]);
    }
    const words = amountInWords(Math.abs(net), d.currency).replace(/^[A-Z]{3} /, "").replace(/ and (.+) paise Only\.$/, " Rupees and $1 Paise only.").replace(/ Only\.$/, " Rupees only.");

    const airlinePnr = d.airlinePnr || ((d.infoRows || []).find(([k]) => /airline pnr/i.test(k)) || [])[1] || "";
    const flightRow = [uniq(d.lines.map((l) => l.airlineName || l.airline)).join(", "), d.refValue, airlinePnr,
      uniq(d.lines.map((l) => l.gdsPnr)).join(", "), uniq(d.lines.map((l) => l.flight)).join(", "),
      uniq(d.lines.map((l) => l.sector)).join(", "), uniq(d.lines.map((l) => l.travelDate)).join(", ")];
    const paxRows = d.lines.map((l, i) => `<tr><td>${i + 1}</td><td>${esc(l.ticketNo)}</td><td>${esc(l.pax)}</td>
      <td>${esc(PAX[String(l.paxType || "").toUpperCase()] || l.paxType || "")}</td><td>${n2(l.fare)}</td><td>${n2(yq(l))}</td><td>${n2(otherTax(l))}</td>
      <td>${n2(l.baggage)}</td><td>${n2(l.seat)}</td><td>${n2(l.meal)}</td><td>${n2(l.otherSsr)}</td><td>${n2(rowTotal(l))}</td></tr>`).join("");
    const party = (title, p) => `
      <td class="party">
        <div class="ph">${title},</div><div class="pn">${esc(p.name)}</div>
        <table class="pk">
          <tr><td class="k">Regd Office:</td><td>${p.address}</td></tr>
          <tr><td class="k">Email:</td><td>${na(p.email)}</td></tr>
          <tr><td class="k">Phone:</td><td>${na(p.phone)}</td></tr>
          <tr><td class="k">PAN:</td><td>${na(p.pan)}</td></tr>
          <tr><td class="k">GST State:</td><td>${na(p.state)}</td></tr>
          <tr><td class="k">GSTIN:</td><td>${na(p.gst_no)}</td></tr>
        </table>
      </td>`;
    const terms = String(c.terms || "").split("\n").map((t) => t.trim()).filter(Boolean);

    return `<!DOCTYPE html><html><head><meta charset="UTF-8"><title>${esc(d.invoiceNo || d.docTitle)}</title>
      <style>
        @page { size: A4; margin: 10mm; }
        * { box-sizing: border-box; }
        body { font-family: Roboto, Arial, Helvetica, sans-serif; font-size: 10px; color: #111; margin: 0; }
        table { border-collapse: collapse; width: 100%; }
        .page { border: 1px solid #D5D5D5; padding: 18px 16px 22px; }
        h1 { text-align: center; font-size: 17px; font-weight: 700; text-decoration: underline; margin: 4px 0 18px; letter-spacing: 0.02em; }
        .bar td { background: #F2F2F2; font-weight: 700; font-size: 11px; padding: 6px 8px; border: 1px solid #D5D5D5; }
        .bar td.r { text-align: right; }
        .parties { border: 1px solid #D5D5D5; border-top: none; }
        .party { width: 50%; vertical-align: top; padding: 0; }
        .party + .party { border-left: 1px solid #D5D5D5; }
        .ph { padding: 6px 8px 2px; font-weight: 700; }
        .pn { padding: 2px 8px 6px; font-weight: 700; font-size: 10.5px; }
        .pk td { padding: 3px 8px; border-top: 1px dashed #D5D5D5; vertical-align: top; line-height: 1.4; }
        .pk td.k { width: 80px; font-weight: 700; white-space: nowrap; border-right: 1px dashed #D5D5D5; }
        .grid { margin-top: 16px; }
        .grid th { background: #F2F2F2; font-weight: 700; padding: 6px 4px; border: 1px solid #D5D5D5; text-align: center; }
        .grid td { padding: 5px 4px; border: 1px solid #D5D5D5; text-align: center; }
        .bottom { display: flex; gap: 20px; margin-top: 18px; align-items: flex-start; }
        .sum { width: 50%; margin-left: auto; }
        .sum td { border: 1px solid #D5D5D5; padding: 5px 8px; }
        .sum td.lbl { width: 22%; }
        /* Value column = the passenger table's Total column (same width,
           same alignment) so the amounts line up in one straight column. */
        .sum td.v, .grid th.tot { width: 90px; }
        .sum td.v { text-align: center; }
        .sum tr.b td { font-weight: 700; }
        .side { flex: 1; text-align: center; padding-top: 30px; }
        .bottom > .side { order: -1; }
        .seal { max-height: 95px; max-width: 150px; object-fit: contain; display: block; margin: 0 auto 10px; }
        .terms h3 { font-size: 11px; text-decoration: underline; margin: 16px 0 6px; }
        .terms ul { margin: 0; padding-left: 18px; line-height: 1.7; }
      </style></head><body>
      <div class="page">
        <h1>${esc(String(d.invoiceType || (d.creditNote ? "Credit Note" : "Performa Invoice")).toUpperCase())}</h1>
        <table class="bar"><tr><td>${esc(d.invoiceDateLabel)}: ${esc(d.invoiceDate)}</td><td class="r">${esc(d.invoiceNoLabel)}: ${esc(d.invoiceNo)}</td></tr></table>
        <table class="parties"><tr>
          ${party("From", { name: c.name, address: companyLine(c) || "N/A", email: c.email, phone: c.phone, pan: c.pan_number, state: c.state, gst_no: c.gst_no })}
          ${party("To", { name: cu.name, address: esc(cu.address || "").replace(/\n/g, "<br/>") || "N/A", email: cu.email, phone: cu.phone, pan: cu.pan, state: cu.state, gst_no: cu.gst_no })}
        </tr></table>
        <table class="grid">
          <thead><tr><th>Airlines</th><th>S PNR</th><th>Airlines PNR</th><th>GDS PNR</th><th>Flight Details</th><th>Sector</th><th>Travel Date</th></tr></thead>
          <tbody><tr>${flightRow.map((v) => `<td>${na(v)}</td>`).join("")}</tr></tbody>
        </table>
        <table class="grid">
          <thead><tr><th>Sr.No</th><th>Ticket No.</th><th>Pax Name</th><th>Pax Type</th><th>Base Fare</th><th>YQ Tax</th><th>Other Taxes</th><th>Baggage Charges</th><th>Seat Charges</th><th>Meal Charges</th><th>Other SSR</th><th class="tot">Total</th></tr></thead>
          <tbody>${paxRows}</tbody>
        </table>
        <div class="bottom">
          <table class="sum">
            ${summary.map(([a, b, v, bold]) => `<tr${bold ? ' class="b"' : ""}><td class="lbl">${a}</td><td>${esc(b)}</td><td class="v">${n2(v)}</td></tr>`).join("")}
            <tr class="b"><td class="lbl"></td><td>Net Amount (${esc(d.currency)})</td><td class="v">${n2(net)}</td></tr>
            <tr><td class="lbl">Amount (in Words)</td><td colspan="2" class="b" style="font-weight:700;">${esc(words)}</td></tr>
          </table>
          <div class="side">${sealHtml(d, "seal")}This is Computer Generated Invoice, No Signature Required</div>
        </div>
        ${terms.length ? `<div class="terms"><h3>Terms &amp; Conditions:</h3><ul>${terms.map((t) => `<li>${esc(t)}</li>`).join("")}</ul></div>` : ""}
      </div>
      </body></html>`;
  }

  function render(key, d) {
    return (key === "payment" ? payment : key === "proforma" ? proforma : classic)(d);
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
        taxParts: { YQ: 5200, YR: 431, K3: 2400, OT: 1600 }, yq: 5200, baggage: 0, seat: 450, meal: 0, otherSsr: 0 },
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
