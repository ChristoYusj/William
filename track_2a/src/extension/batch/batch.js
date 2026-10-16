import { fetchDoc, extract, summarize, summaryHtml, bindTopics, shared, buildText, downloadBlob, esc, SCHEMA_VERSION } from "../shared/engine.js";
import { recordHtml } from "../shared/render.js";
import { MiniPdf } from "../shared/minipdf.js";

const $ = (id) => document.getElementById(id);
let results = [];

try { $("urls").value = localStorage.getItem("william-urls") || ""; } catch {}

async function processOne(url, card, opts) {
  const { vocab, prompts } = await shared();
  const set = (html) => (card.querySelector(".body").innerHTML = html);
  try {
    set('<div class="spin"></div><div class="small muted">fetching…</div>');
    const doc = await fetchDoc(url);
    set('<div class="spin"></div><div class="small muted">Apertus is extracting…</div>');
    const record = await extract(doc);
    let summary = null;
    if (opts.summary) {
      set('<div class="spin"></div><div class="small muted">Apertus is summarising…</div>');
      const s = await summarize(buildText(doc.pages, prompts.max_doc_chars)[0], { withNews: opts.news });
      summary = s;
    }
    const a = record.affair, lvl = record.body.level?.value;
    card.querySelector("h3").innerHTML = (lvl ? `<span class="lvl">${esc(lvl)}${record.body.body_key ? " · " + esc(record.body.body_key) : ""}</span>` : "") +
      esc(a.title?.value || a.affair_number?.value || "(no verified title)");
    set((summary ? summaryHtml(summary) : "") +
      `<details open><summary>Structured record</summary>${recordHtml(record, vocab)}</details>` +
      `<details><summary>JSON</summary><pre class="json"></pre></details>`);
    card.querySelector("pre").textContent = JSON.stringify(record, null, 1);
    if (summary) bindTopics(card, summary);
    return { url, record, summary };
  } catch (e) {
    set(`<p class="err">${esc(e.message || e)}</p>`);
    return { url, error: String(e.message || e) };
  }
}

$("run").onclick = async () => {
  const urls = [...new Set($("urls").value.split(/\s+/).map((u) => u.trim()).filter((u) => /^https?:\/\//.test(u)))];
  if (!urls.length) { $("status").textContent = "Paste at least one http(s) link."; return; }
  try { localStorage.setItem("william-urls", $("urls").value); } catch {}
  const opts = { summary: $("optSum").checked, news: $("optNews").checked };
  $("run").disabled = $("dlJson").disabled = $("dlPdf").disabled = true;
  $("cards").innerHTML = "";
  const cards = urls.map((u) => {
    const c = document.createElement("div");
    c.className = "card";
    c.innerHTML = `<h3>…</h3><div class="u">${esc(u)}</div><div class="body"></div>`;
    $("cards").appendChild(c);
    return c;
  });
  results = new Array(urls.length);
  let done = 0;
  const queue = urls.map((u, i) => i);
  const worker = async () => {
    while (queue.length) {
      const i = queue.shift();
      results[i] = await processOne(urls[i], cards[i], opts);
      $("status").textContent = `${++done} / ${urls.length} done`;
    }
  };
  $("status").textContent = `0 / ${urls.length} done`;
  await Promise.all([worker(), worker(), worker()]);
  $("run").disabled = $("dlJson").disabled = $("dlPdf").disabled = false;
};

$("dlJson").onclick = () => downloadBlob(new Blob([JSON.stringify({ schema_version: SCHEMA_VERSION, generated_at: new Date().toISOString(), items: results }, null, 2)],
  { type: "application/json" }), "william-affairs.json");

const fv = (f) => (f ? `${f.value}${f.status === "inferred" ? " [inferred]" : f.status === "metadata" ? " [meta]" : ""}${f.page ? ` (p.${f.page})` : ""}` : "-");

$("dlPdf").onclick = async () => {
  const { vocab } = await shared();
  const pdf = new MiniPdf();
  pdf.text("Parliamentary affairs — summary report", { size: 18, bold: true });
  pdf.text(`William · Apertus · schema ${SCHEMA_VERSION} · ${new Date().toLocaleString()}`, { size: 9, color: [110, 110, 115] });
  pdf.text("Values marked [inferred] were not found verbatim in the source; values whose quote was not found were removed. (p.N) = page of the evidence.", { size: 8.5, color: [110, 110, 115] });
  results.forEach((r, n) => {
    if (n > 0) pdf.newPage(); else pdf.rule();
    pdf.text(`${n + 1}. ${r.url}`, { size: 8.5, color: [11, 87, 208], link: r.url });
    if (r.error) { pdf.text("Error: " + r.error, { bold: true, color: [176, 0, 32] }); return; }
    const a = r.record.affair, b = r.record.body;
    pdf.gap(4);
    pdf.text(a.title?.value || "(no verified title)", { size: 14, bold: true });
    if (r.summary) {
      pdf.gap(3);
      pdf.text(r.summary.summary, { size: 10.5 });
      for (const k of r.summary.key_points || []) pdf.text("• " + k, { size: 10 });
    }
    pdf.gap(6);
    const t = a.type;
    const kv = (k, v) => pdf.text(`${k}: ${v}`, { size: 9.5 });
    kv("Level", `${fv(b.level)}${b.body_key ? "  · body_key " + b.body_key : ""}`);
    kv("Parliament", fv(b.parliament));
    kv("Number", fv(a.affair_number));
    kv("Type", t ? `${vocab.affair_types[t.value]?.label?.en} (${t.value}, OPD type id ${t.opd_type_harmonized_id ?? "–"})  · original: ${fv(a.type_original)}` : "-");
    kv("Submitted", fv(a.submission_date));
    kv("Addressed to", fv(a.addressed_to));
    kv("State", fv(a.state));
    for (const x of a.actors) kv("Actor", `${fv(x.name)} — ${x.role?.value || "?"}${x.party_or_group ? " — " + x.party_or_group.value : ""}`);
    for (const x of a.requests) kv("Request", fv(x));
    for (const q of a.questions) { kv(`Question ${q.number?.value ?? ""}`, fv(q.question)); if (q.answer) kv("  Answer", fv(q.answer)); }
    for (const d of a.decisions) kv("Decision", `${fv(d.outcome)} ${fv(d.date)} ${fv(d.body)}`);
    for (const x of a.related_affairs) kv("Related", `${fv(x.reference)} (${x.relation?.value || "?"})`);
    if (r.summary?.topics?.length) {
      pdf.gap(6);
      pdf.text("In the Swiss news", { size: 11, bold: true });
      for (const tp of r.summary.topics) for (const art of (tp.articles || []).slice(0, 2))
        pdf.text(`[${tp.phrase}] ${art.title} — ${art.source}`, { size: 9, color: [11, 87, 208], link: art.url });
    }
    const q = r.record.quality;
    pdf.gap(6);
    pdf.text(`Quality: verified share ${q.verified_share} · ${Object.entries(q.value_counts).map(([k, v]) => k + " " + v).join(" · ")}`, { size: 8.5, color: [110, 110, 115] });
    for (const f of q.flags) pdf.text("! " + f, { size: 8.5, color: [161, 92, 0] });
    pdf.gap(6);
    pdf.text("JSON (opd-affair/0.1)", { size: 9, bold: true });
    const slim = { ...r.record, extractor: { ...r.record.extractor, raw_model_output: undefined } };
    pdf.text(JSON.stringify(slim, null, 1), { size: 6.5, mono: true, lead: 1.2 });
  });
  downloadBlob(pdf.build(), "william-report.pdf");
};
