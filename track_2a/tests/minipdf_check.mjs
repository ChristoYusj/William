// Builds a report with the extension's MiniPdf from stored records; tests/test_minipdf.py parses it back.
import { readFileSync, writeFileSync } from "node:fs";
import { MiniPdf } from "../src/extension/shared/minipdf.js";
const fx = JSON.parse(readFileSync(new URL("fixtures/sample_v02.json", import.meta.url), "utf8"));
const pdf = new MiniPdf();
pdf.text("Parliamentary affairs — summary report", { size: 18, bold: true });
for (const f of fx) {
  pdf.newPage();
  pdf.text(f.url, { size: 8.5, color: [11, 87, 208], link: f.url });
  pdf.text(f.expected.affair.title?.value || "(no verified title)", { size: 14, bold: true });
  pdf.text("Zürich · Genève · città · « guillemets » · “quotes” – dash … €", { size: 10 });
  pdf.text(JSON.stringify(f.expected.affair, null, 1), { size: 6.5, mono: true, lead: 1.2 });
}
const buf = Buffer.from(await pdf.build().arrayBuffer());
writeFileSync(process.argv[2], buf);
console.log("bytes", buf.length);
