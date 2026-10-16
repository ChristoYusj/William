// Tiny dependency-free PDF writer: A4 pages, Helvetica / Helvetica-Bold / Courier (WinAnsi),
// word wrapping, clickable links. Enough for William's batch report; keeps the extension self-contained.

const WIN = { "€": 0x80, "‚": 0x82, "„": 0x84, "…": 0x85, "‘": 0x91, "’": 0x92, "“": 0x93, "”": 0x94, "•": 0x95,
  "–": 0x96, "—": 0x97, "œ": 0x9c, "Œ": 0x8c, "Š": 0x8a, "š": 0x9a, "Ž": 0x8e, "ž": 0x9e, "Ÿ": 0x9f };
const W = 595.28, H = 841.89, M = 48;

function hex(str) {
  let h = "";
  for (const ch of str.normalize("NFC")) {
    const cp = ch.codePointAt(0);
    let b = WIN[ch] ?? (cp < 256 && !(cp >= 0x80 && cp < 0xa0) ? cp : 0x3f);
    if (b < 32) b = 32;
    h += b.toString(16).padStart(2, "0");
  }
  return "<" + h + ">";
}

export class MiniPdf {
  constructor() { this.pages = []; this.newPage(); }
  newPage() { this.cur = { ops: [], links: [] }; this.pages.push(this.cur); this.y = H - M; }
  ensure(h) { if (this.y - h < M) this.newPage(); }
  gap(h = 6) { this.y -= h; }
  // width estimate: Helvetica ~0.5em average, bold ~0.55em, Courier 0.6em
  wrap(text, size, font) {
    const k = font === "F3" ? 0.6 : font === "F2" ? 0.56 : 0.51;
    const max = Math.max(10, Math.floor((W - 2 * M) / (size * k)));
    const lines = [];
    for (const para of String(text ?? "").split("\n")) {
      let line = "";
      for (const word of para.split(/(\s+)/)) {
        if ((line + word).length > max) {
          if (line.trim()) lines.push(line.trimEnd());
          line = word.trimStart();
          while (line.length > max) { lines.push(line.slice(0, max)); line = line.slice(max); }
        } else line += word;
      }
      lines.push(line.trimEnd());
    }
    return lines;
  }
  text(text, { size = 10, bold = false, mono = false, color = [0, 0, 0], link = null, lead = 1.35 } = {}) {
    const font = mono ? "F3" : bold ? "F2" : "F1";
    for (const line of this.wrap(text, size, font)) {
      this.ensure(size * lead);
      this.y -= size * lead;
      this.cur.ops.push(`${color.map((c) => (c / 255).toFixed(3)).join(" ")} rg BT /${font} ${size} Tf ${M} ${this.y.toFixed(2)} Td ${hex(line)} Tj ET`);
      if (link) this.cur.links.push([M, this.y - 2, W - M, this.y + size, link]);
    }
  }
  rule() { this.ensure(8); this.y -= 6; this.cur.ops.push(`0.85 0.85 0.85 RG 0.5 w ${M} ${this.y} m ${W - M} ${this.y} l S`); this.y -= 4; }

  build() {
    const objs = [];
    const add = (s) => { objs.push(s); return objs.length; };
    const fonts = ["Helvetica", "Helvetica-Bold", "Courier"].map((f) =>
      add(`<< /Type /Font /Subtype /Type1 /BaseFont /${f} /Encoding /WinAnsiEncoding >>`));
    const pagesId = objs.length + 1;
    objs.push(null); // placeholder for /Pages
    const kids = [];
    for (const p of this.pages) {
      const stream = p.ops.join("\n");
      const cId = add(`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`);
      const annots = p.links.map(([x1, y1, x2, y2, url]) => add(
        `<< /Type /Annot /Subtype /Link /Rect [${x1} ${y1.toFixed(2)} ${x2} ${y2.toFixed(2)}] /Border [0 0 0] /A << /S /URI /URI ${hex(url)} >> >>`));
      kids.push(add(`<< /Type /Page /Parent ${pagesId} 0 R /MediaBox [0 0 ${W} ${H}] /Contents ${cId} 0 R ` +
        `/Resources << /Font << /F1 ${fonts[0]} 0 R /F2 ${fonts[1]} 0 R /F3 ${fonts[2]} 0 R >> >>` +
        (annots.length ? ` /Annots [${annots.map((a) => a + " 0 R").join(" ")}]` : "") + " >>"));
    }
    objs[pagesId - 1] = `<< /Type /Pages /Kids [${kids.map((k) => k + " 0 R").join(" ")}] /Count ${kids.length} >>`;
    const catalog = add(`<< /Type /Catalog /Pages ${pagesId} 0 R >>`);
    let out = "%PDF-1.4\n";
    const offs = [];
    objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
    const xref = out.length;
    out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map((o) => String(o).padStart(10, "0") + " 00000 n \n").join("");
    out += `trailer\n<< /Size ${objs.length + 1} /Root ${catalog} 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
    return new Blob([out], { type: "application/pdf" }); // all bytes are ASCII (text is hex-encoded)
  }
}
