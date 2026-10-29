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
  const TOTAL_TEXT = /^(grand |current |sub ?|net )?total\b/i;

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
        cells.push(cellValue(td.innerText || ""));
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

  window.VoyagerExport = { excel, _readRows: readRows, _cellValue: cellValue };
})(window);
