// Report Export - writes a real Excel (.xlsx) file from the report's table rows.
//   * no "₹" symbol: amounts are stored as numbers (#,##0.00), so Excel can total them
//   * colspan cells are expanded, so a Total row's amounts sit under the same
//     columns as the amounts above (a separate total <table> lines up too)
//   * header row: bold on blue; Total row (tfoot / "Total :" / *total* class): bold + coloured
// Usage: VoyagerExport.excel("Day Book", rows)  -> "Day Book - 01-10-2026 - 28-10-2026.xlsx"
//   rows - <tr> elements, or a plain string for a bold title line (e.g. "Liabilities").
(function (window) {
  const RUPEE = /[₹]/g;
  const AMOUNT = /^-?(\d{1,3}(,\d{2,3})*|\d+)\.\d+$|^-?\d{1,3}(,\d{2,3})+$/;
  const TOTAL_TEXT = /^((grand |current |sub ?|net )?total|closing balance)\b/i;

  // style ids - must match cellXfs in STYLES below
  const S = { text: 0, head: 1, title: 2, num: { 0: 5, 2: 3, 3: 4 }, totText: 6, totNum: { 0: 9, 2: 7, 3: 8 } };

  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;")
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g, "");

  function colName(i) {
    let s = "";
    for (i += 1; i > 0; i = Math.floor((i - 1) / 26)) s = String.fromCharCode(65 + ((i - 1) % 26)) + s;
    return s;
  }

  function cellValue(text) {
    const t = text.replace(RUPEE, "").replace(/\s+/g, " ").trim();
    if (AMOUNT.test(t)) {
      const dec = (t.split(".")[1] || "").length;
      return { num: Number(t.replace(/,/g, "")), dec: dec in S.num ? dec : 2, text: t };
    }
    return { text: t };
  }

  function isTotalRow(tr, texts) {
    if (tr.closest("tfoot")) return true;
    if (/total/i.test(tr.className || "") || /total/i.test(tr.id || "")) return true;
    return texts.some((t) => TOTAL_TEXT.test(t));
  }

  // rows -> [{kind, cells:[{text,num,dec}]}] with colspans expanded
  function readRows(rows) {
    const out = [];
    Array.from(rows).forEach((tr) => {
      if (typeof tr === "string") { out.push({ kind: "title", cells: [{ text: tr }] }); return; }
      const tds = Array.from(tr.querySelectorAll("th, td"));
      if (!tds.length || tr.style.display === "none") return;
      const cells = [];
      tds.forEach((td) => {
        const c = cellValue(td.innerText || "");
        const span = Number(td.colSpan) || 1;
        if (span > 1) c.span = span;
        if (td.style.textAlign === "right" || td.style.textAlign === "center") c.align = td.style.textAlign;
        cells.push(c);
        for (let k = 1; k < (Number(td.colSpan) || 1); k++) cells.push({ text: "" });
      });
      const head = tr.closest("thead") || tds.every((td) => td.tagName === "TH");
      const kind = head ? "head" : isTotalRow(tr, cells.map((c) => c.text)) ? "total" : "body";
      out.push({ kind, cells });
    });
    return out;
  }

  function sheetXml(rows) {
    const widths = [];
    const body = rows.map((r, ri) => {
      const cells = r.cells.map((c, ci) => {
        widths[ci] = Math.max(widths[ci] || 8, Math.min(50, (c.text || "").length + 2));
        const ref = colName(ci) + (ri + 1);
        const total = r.kind === "total";
        if (c.num != null && r.kind !== "head") {
          return `<c r="${ref}" s="${(total ? S.totNum : S.num)[c.dec]}"><v>${c.num}</v></c>`;
        }
        const s = r.kind === "head" ? S.head : r.kind === "title" ? S.title : total ? S.totText : S.text;
        if (!c.text) return s ? `<c r="${ref}" s="${s}"/>` : "";
        return `<c r="${ref}" s="${s}" t="inlineStr"><is><t xml:space="preserve">${esc(c.text)}</t></is></c>`;
      }).join("");
      return `<row r="${ri + 1}">${cells}</row>`;
    }).join("");
    const cols = widths.length
      ? `<cols>${widths.map((w, i) => `<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"/>`).join("")}</cols>` : "";
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">${cols}<sheetData>${body}</sheetData></worksheet>`;
  }

  const STYLES = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="3"><numFmt numFmtId="164" formatCode="#,##0.00"/><numFmt numFmtId="165" formatCode="#,##0.000"/><numFmt numFmtId="166" formatCode="#,##0"/></numFmts>
<fonts count="3"><font><sz val="10"/><name val="Arial"/></font><font><b/><sz val="10"/><name val="Arial"/></font><font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Arial"/></font></fonts>
<fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF3B6DB5"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>
<border><left/><right/><top style="thin"><color rgb="FF3B6DB5"/></top><bottom style="double"><color rgb="FF3B6DB5"/></bottom><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="10">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="2" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="0" fontId="1" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>
<xf numFmtId="164" fontId="1" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1"/>
<xf numFmtId="165" fontId="1" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1"/>
<xf numFmtId="166" fontId="1" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>`;

  const STATIC = {
    "[Content_Types].xml": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>`,
    "_rels/.rels": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>`,
    "xl/_rels/workbook.xml.rels": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>`,
    "xl/styles.xml": STYLES,
  };

  // --- minimal ZIP writer (stored, no compression) ---
  const CRC = (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
    return t;
  })();
  function crc32(bytes) {
    let c = 0xFFFFFFFF;
    for (let i = 0; i < bytes.length; i++) c = CRC[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }
  function zip(files) {
    const enc = new TextEncoder();
    const parts = [], central = [];
    let offset = 0;
    Object.entries(files).forEach(([name, text]) => {
      const nameB = enc.encode(name), data = enc.encode(text), crc = crc32(data);
      const local = new DataView(new ArrayBuffer(30));
      local.setUint32(0, 0x04034b50, true); local.setUint16(4, 20, true); local.setUint16(6, 0x0800, true);
      local.setUint32(14, crc, true); local.setUint32(18, data.length, true); local.setUint32(22, data.length, true);
      local.setUint16(26, nameB.length, true);
      const cen = new DataView(new ArrayBuffer(46));
      cen.setUint32(0, 0x02014b50, true); cen.setUint16(4, 20, true); cen.setUint16(6, 20, true); cen.setUint16(8, 0x0800, true);
      cen.setUint32(16, crc, true); cen.setUint32(20, data.length, true); cen.setUint32(24, data.length, true);
      cen.setUint16(28, nameB.length, true); cen.setUint32(42, offset, true);
      parts.push(local, nameB, data);
      central.push(cen, nameB);
      offset += 30 + nameB.length + data.length;
    });
    const size = central.reduce((n, p) => n + p.byteLength, 0);
    const end = new DataView(new ArrayBuffer(22));
    const count = Object.keys(files).length;
    end.setUint32(0, 0x06054b50, true); end.setUint16(8, count, true); end.setUint16(10, count, true);
    end.setUint32(12, size, true); end.setUint32(16, offset, true);
    return new Blob([...parts, ...central, end], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
  }

  // "2026-10-12" -> "12-10-2026" (a file name cannot hold "/")
  const dmy = (v) => (v || "").split("-").reverse().join("-");

  // File name = report name + the filter's date range, e.g. "DSR - 12-10-2026 - 28-10-2026"
  // (a report with only an "as on" / "to" date gets that one date).
  function fileNameFor(title) {
    const val = (id) => (document.getElementById(id) || {}).value || "";
    const from = val("filter-from"), to = val("filter-to") || val("po-as-of");
    return [title, from && dmy(from), to && dmy(to)].filter(Boolean).join(" - ").replace(/[\\/:*?"<>|]/g, "-");
  }

  function excel(title, rows) {
    if (window.VoyagerShell && !window.VoyagerShell.can("export")) return;   // no Export Excel access on this menu
    const fileName = fileNameFor(title);
    const name = esc(title.replace(/[\\/?*[\]:]/g, " ").slice(0, 31) || "Report");
    const files = Object.assign({}, STATIC, {
      "xl/workbook.xml": `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="${name}" sheetId="1" r:id="rId1"/></sheets></workbook>`,
      "xl/worksheets/sheet1.xml": sheetXml(readRows(rows)),
    });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(zip(files));
    link.download = fileName + ".xlsx";
    // Not added to the page: shell.js's SPA click handler would grab an <a> in the
    // document and the download would lose its name (saved as a random id).
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 60000);
  }

  // ------------------------------------------------------------------ print
  // A clean print of the report, not a screenshot of the page: company name /
  // address / pin code / mobile centred on top, then the report name, ledger
  // and period, then EVERY row of the table (no scroll bar, header repeated
  // on each page, Total rows bold). Same rows as the Excel export.
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  // "2026-10-01" -> "1-Oct-26"
  const shortDate = (v) => {
    const [y, m, d] = (v || "").split("-");
    return y && m && d ? `${Number(d)}-${MONTHS[Number(m) - 1]}-${y.slice(2)}` : "";
  };

  let companyCache = null;
  async function company() {
    const id = window.VoyagerAPI && window.VoyagerAPI.Store.getCompanyId();
    if (!id) return {};
    if (companyCache && String(companyCache.id) === String(id)) return companyCache;
    try {
      const res = await fetch(`http://127.0.0.1:8000/api/company-master/?id=${id}`);
      if (res.ok) companyCache = await res.json();
    } catch (_) { /* backend unreachable - print without the address */ }
    return companyCache || {};
  }

  function companyHtml(c) {
    const lines = [];
    String(c.address || "").split(/\r?\n/).map((s) => s.trim()).filter(Boolean).forEach((s) => lines.push(esc(s)));
    const place = [c.state, c.pincode].filter(Boolean).join(" - ");
    if (place) lines.push(esc(place + (c.country && !/india/i.test(c.country) ? `, ${c.country}` : "")));
    const phones = [c.mobile && `Mobile: ${c.mobile}`, c.telephone && `Phone: ${c.telephone}`, c.email && `Email: ${c.email}`].filter(Boolean);
    return `<div class="co-name">${esc(c.mailing_name || c.company_name || "")}</div>` +
      lines.map((l) => `<div class="co-line">${l}</div>`).join("") +
      (phones.length ? `<div class="co-contact">${esc(phones.join("   |   "))}</div>` : "");
  }

  function tableHtml(rows) {
    const width = rows.reduce((n, r) => Math.max(n, r.cells.length), 0);
    // Columns empty on every row (action icons, checkboxes) are left out.
    const keep = [];
    for (let i = 0; i < width; i++) if (rows.some((r) => r.kind !== "title" && r.cells[i] && r.cells[i].text)) keep.push(i);
    const amountCol = new Map(keep.map((i) => [i, rows.some((r) => r.kind === "body" && r.cells[i] && r.cells[i].num != null)]));
    // One row -> cells over the kept columns; a colspan cell (e.g. "Current Total :" over 8
    // columns) stays one cell over the kept columns it covers, so its label is never lost.
    function rowCells(tag, r) {
      const out = [];
      for (let i = 0; i < width; i++) {
        const c = r.cells[i] || { text: "" };
        const span = c.span || 1;
        const n = keep.filter((k) => k >= i && k < i + span).length;
        if (n) {
          const right = c.align === "right" || c.num != null || (span === 1 && amountCol.get(i));
          const cls = right ? "num" : c.align === "center" ? "mid" : "";
          out.push(`<${tag}${n > 1 ? ` colspan="${n}"` : ""}${cls ? ` class="${cls}"` : ""}>${esc(c.text || "")}</${tag}>`);
        }
        i += span - 1;
      }
      return out.join("");
    }
    const head = [], body = [];
    rows.forEach((r) => {
      if (r.kind === "title") { body.push(`<tr class="sec"><td colspan="${keep.length}">${esc(r.cells[0].text)}</td></tr>`); return; }
      const tag = r.kind === "head" ? "th" : "td";
      const html = `<tr${r.kind === "total" ? ' class="tot"' : ""}>${rowCells(tag, r)}</tr>`;
      // Only the first header row block repeats on each page; later header rows (a second table) stay in the body.
      (r.kind === "head" && !body.length ? head : body).push(html);
    });
    return { cols: keep.length, html: `<table><thead>${head.join("")}</thead><tbody>${body.join("")}</tbody></table>` };
  }

  async function print(title, rows, opts) {
    opts = opts || {};
    const c = await company();
    const val = (id) => (document.getElementById(id) || {}).value || "";
    const from = val("filter-from"), to = val("filter-to") || val("po-as-of");
    const period = from && to ? `${shortDate(from)} To ${shortDate(to)}` : to ? `As on ${shortDate(to)}` : "";
    const ledgerEl = document.querySelector("#lb-ledger-name-2, #ms-ledger-name");
    const ledger = opts.subtitle || (ledgerEl && ledgerEl.textContent.trim()) || "";
    const table = tableHtml(readRows(rows));
    const size = table.cols > 10 ? 8 : table.cols > 7 ? 9.5 : 11;
    const doc = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${esc(fileNameFor(title))}</title><style>
      @page { size: A4 ${table.cols > 7 ? "landscape" : "portrait"}; margin: 12mm 10mm; }
      * { box-sizing: border-box; }
      body { font-family: "Segoe UI", Arial, sans-serif; color: #111; margin: 0; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
      .hdr { text-align: center; margin-bottom: 10px; }
      .co-name { font-size: 20px; font-weight: 700; letter-spacing: .2px; }
      .co-line { font-size: 12.5px; text-transform: uppercase; line-height: 1.45; }
      .co-contact { font-size: 12px; line-height: 1.45; margin-top: 1px; }
      .rule { width: 60%; margin: 6px auto 8px; border: 0; border-top: 1.5px solid #333; }
      .rpt-ledger { font-size: 17px; font-weight: 700; text-transform: uppercase; }
      .rpt-title { font-size: 14.5px; font-weight: 700; margin-top: 2px; }
      .rpt-period { font-size: 12.5px; font-weight: 600; margin-top: 6px; }
      table { width: 100%; border-collapse: collapse; font-size: ${size}px; }
      thead { display: table-header-group; }
      tr { page-break-inside: avoid; }
      th { background: #2F5994; color: #fff; font-weight: 700; text-align: left; padding: 5px 6px; border: 1px solid #2F5994; }
      td { padding: 4px 6px; border-bottom: 1px solid #ddd; vertical-align: top; }
      .num { text-align: right; white-space: nowrap; }
      .mid { text-align: center; }
      tr.tot td { font-weight: 700; background: #DCE6F2; border-top: 1.5px solid #2F5994; border-bottom: 1.5px solid #2F5994; }
      tr.sec td { font-weight: 700; background: #F2F2F2; padding-top: 6px; }
      .foot { margin-top: 10px; font-size: 10px; color: #666; text-align: right; }
    </style></head><body>
      <div class="hdr">
        ${companyHtml(c)}
        <hr class="rule">
        ${ledger ? `<div class="rpt-ledger">${esc(ledger)}</div>` : ""}
        <div class="rpt-title">${esc(ledger && title === "Ledger" ? "Ledger Account" : title)}</div>
        ${period ? `<div class="rpt-period">${esc(period)}</div>` : ""}
      </div>
      ${table.html}
      <div class="foot">Printed on ${esc(new Date().toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }))}</div>
    </body></html>`;

    const frame = document.createElement("iframe");
    frame.style.cssText = "position:fixed; right:0; bottom:0; width:0; height:0; border:0;";
    document.body.appendChild(frame);
    frame.contentDocument.open();
    frame.contentDocument.write(doc);
    frame.contentDocument.close();
    setTimeout(() => {
      frame.contentWindow.focus();
      frame.contentWindow.print();
      setTimeout(() => frame.remove(), 1000);
    }, 100);
  }

  // Print button: runs the page's own exportCSV() but catches the rows it
  // would export and prints them instead - so print and Excel always match.
  function printReport(exportFn, opts) {
    if (window.VoyagerShell && !window.VoyagerShell.can("print")) return;   // no Print access on this menu
    const api = window.VoyagerExport;
    const realExcel = api.excel;
    let captured = null;
    api.excel = (title, rows) => { captured = [title, rows]; };
    try { (exportFn || window.exportCSV)(); } finally { api.excel = realExcel; }
    if (captured) print(captured[0], captured[1], opts);
  }

  window.VoyagerExport = { excel, print, printReport, _readRows: readRows, _cellValue: cellValue };
})(window);
