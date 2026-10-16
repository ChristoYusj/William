// Parity test: the extension's JS verifier/assembler must give the same record as the Python one
// on the same page texts and the same stored Apertus outputs.   node tests/parity.mjs
import { readFileSync } from "node:fs";
import { assemble } from "../src/extension/shared/core.js";

const root = new URL("../", import.meta.url);
const vocab = JSON.parse(readFileSync(new URL("src/extension/shared/vocab.json", root), "utf8"));
const prompts = JSON.parse(readFileSync(new URL("src/extension/shared/prompts.json", root), "utf8"));
const fixtures = JSON.parse(readFileSync(new URL("tests/fixtures/sample_v02.json", root), "utf8"));

const strip = (o) => JSON.parse(JSON.stringify(o, (k, v) => (["retrieved_at", "source"].includes(k) ? undefined : v)));
let fail = 0;
for (const fx of fixtures) {
  const js = strip(assemble(fx.doc, fx.raw, { vocab, prompts, model: "x" }));
  const py = strip(fx.expected);
  for (const key of ["language", "body", "affair"]) {
    const a = JSON.stringify(js[key]), b = JSON.stringify(py[key]);
    if (a !== b) {
      fail++;
      console.log(`DIFF ${fx.url} ${key}\n  js: ${a.slice(0, 400)}\n  py: ${b.slice(0, 400)}`);
    }
  }
  if (JSON.stringify(js.quality.value_counts) !== JSON.stringify(py.quality.value_counts)) {
    fail++;
    console.log(`DIFF ${fx.url} value_counts js=${JSON.stringify(js.quality.value_counts)} py=${JSON.stringify(py.quality.value_counts)}`);
  }
}
console.log(`${fixtures.length} documents, ${fail} differences`);
process.exit(fail ? 1 : 0);
