// William engine — the same pipeline as src/william (Python), for the Firefox extension.
// Prompts and vocabularies come from shared/prompts.json and shared/vocab.json (single source).
import * as pdfjsLib from "../lib/pdf.min.mjs";
import { parseJson, buildText, assemble, SCHEMA_VERSION, locatePhrase, highlightSegments, normLang, rankNews } from "./core.js";
export { parseJson, buildText, assemble, SCHEMA_VERSION };
export { PageIndex, normalise, dateSupported } from "./core.js";

pdfjsLib.GlobalWorkerOptions.workerSrc = browser.runtime.getURL("lib/pdf.worker.min.mjs");
export { pdfjsLib };

const DEFAULTS = {
  baseUrl: "https://api.inference.cscs.ch/v1",
  model: "swiss-ai/Apertus-v1.5-70B",
  apiKey: "",
  autoOpenPdf: true,
  summaryLang: "doc", // "doc" = language of the document
};
const OPD_API = "https://api.openparldata.ch/v1";
const CANTONS = new Set("AG AI AR BE BL BS FR GE GL GR JU LU NE NW OW SG SH SO SZ TG TI UR VD VS ZG ZH".split(" "));

let _shared;
export async function shared() {
  if (!_shared) {
    const [vocab, prompts] = await Promise.all(
      ["shared/vocab.json", "shared/prompts.json"].map((p) => fetch(browser.runtime.getURL(p)).then((r) => r.json())),
    );
    _shared = { vocab, prompts };
  }
  return _shared;
}

export async function settings() {
  const s = await browser.storage.local.get(Object.keys(DEFAULTS));
  return { ...DEFAULTS, ...s };
}

// ---------------------------------------------------------------- LLM
export async function chat(system, user, { maxTokens = 3000 } = {}) {
  const s = await settings();
  if (!s.apiKey) throw new Error("No Apertus API key — open William settings and paste your key.");
  let last;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const r = await fetch(s.baseUrl.replace(/\/$/, "") + "/chat/completions", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + s.apiKey },
        body: JSON.stringify({
          model: s.model, temperature: 0, max_tokens: maxTokens,
          messages: [{ role: "system", content: system }, { role: "user", content: user }],
        }),
      });
      if (r.status === 429 || r.status >= 500) throw new Error("HTTP " + r.status);
      if (!r.ok) {
        const e = new Error("Apertus HTTP " + r.status + ": " + (await r.text()).slice(0, 200));
        e.fatal = true;
        throw e;
      }
      const j = await r.json();
      return { text: j.choices[0].message.content || "", usage: j.usage || {} };
    } catch (e) {
      last = e;
      if (e.fatal) throw e;
      await new Promise((res) => setTimeout(res, 2000 * (attempt + 1)));
    }
  }
  throw last;
}

// One retry with a stricter instruction when the model's JSON is invalid or cut off.
async function chatJson(system, user, maxTokens, prompts) {
  const first = await chat(system, user, { maxTokens });
  try {
    return { raw: parseJson(first.text), usage: first.usage };
  } catch {
    const second = await chat(system, user + prompts.json_retry_suffix, { maxTokens });
    return { raw: parseJson(second.text), usage: { ...second.usage, retried: true } };
  }
}

// ---------------------------------------------------------------- documents
export async function pdfPagesFromData(data) {
  const doc = await pdfjsLib.getDocument({ data }).promise;
  const pages = [];
  for (let i = 1; i <= doc.numPages; i++) {
    const tc = await (await doc.getPage(i)).getTextContent();
    let s = "";
    for (const it of tc.items) s += it.str + (it.hasEOL ? "\n" : "");
    pages.push(s);
  }
  return pages;
}

function htmlToText(html) {
  const d = new DOMParser().parseFromString(html, "text/html");
  d.querySelectorAll("script,style,noscript,nav,header,footer,svg").forEach((n) => n.remove());
  const main = d.querySelector("main, article, #content, .content") || d.body;
  return (main?.innerText || main?.textContent || "").replace(/[ \t]+/g, " ").replace(/\n\s*\n+/g, "\n\n").trim();
}

async function sha256(buf) {
  const h = await crypto.subtle.digest("SHA-256", buf);
  return [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function levelFromBodyKey(k) {
  if (!k) return null;
  if (k === "CHE") return "federal";
  if (CANTONS.has(k)) return "cantonal";
  if (/^\d+$/.test(k)) return "communal";
  return null;
}

function levelFromDomain(url) {
  const host = new URL(url).hostname;
  if (/parlament\.ch$|admin\.ch$|fedlex\./.test(host)) return ["federal", "CHE"];
  const m = host.match(/^(?:.*\.)?([a-z]{2})\.ch$/);
  if (m && CANTONS.has(m[1].toUpperCase())) return ["cantonal", m[1].toUpperCase()];
  return [null, null];
}

export async function fetchDoc(url) {
  url = url.trim();
  const hints = {}, flags = [];
  const u = new URL(url);
  if (u.hostname === "api.openparldata.ch") {
    const m = url.match(/\/v1\/(docs|affairs)\/(\d+)/);
    if (!m) throw new Error("unsupported OpenParlData API link (use /v1/docs/ID or /v1/affairs/ID)");
    let doc;
    if (m[1] === "affairs") {
      const aff = await (await fetch(`${OPD_API}/affairs/${m[2]}`)).json();
      Object.assign(hints, { opd_affair_id: +m[2], body_key: aff.body_key,
        opd_type_harmonized_id: aff.type_harmonized_id, affair_number: aff.number });
      const docs = ((await (await fetch(`${OPD_API}/affairs/${m[2]}/docs`)).json()).data || [])
        .filter((d) => (d.format || "").endsWith("pdf"));
      if (!docs.length) throw new Error(`OpenParlData affair ${m[2]} has no PDF document`);
      if (docs.length > 1) flags.push(`affair has ${docs.length} PDFs; only the first was processed`);
      doc = docs[0];
    } else {
      doc = await (await fetch(`${OPD_API}/docs/${m[2]}`)).json();
      if (doc.data && !Array.isArray(doc.data)) doc = doc.data;
    }
    hints.body_key ??= doc.body_key;
    hints.opd_doc_id = doc.id;
    if (doc.affair_id && hints.opd_affair_id == null) {
      hints.opd_affair_id = doc.affair_id;
      try { // OPD's own labels, used as a cross-check (not copied into the record)
        let aff = await (await fetch(`${OPD_API}/affairs/${doc.affair_id}`)).json();
        if (aff.data && !Array.isArray(aff.data)) aff = aff.data;
        Object.assign(hints, { opd_type_harmonized_id: aff.type_harmonized_id, opd_affair_number: aff.number });
      } catch {}
    }
    if (doc.language) hints.language = doc.language;
    url = doc.url_oparl || doc.url;
  } else if (u.hostname === "files.openparldata.ch") {
    const m = url.match(/\/doc\/([A-Za-z0-9]+)\//);
    if (m) hints.body_key = m[1];
  }
  const r = await fetch(url, { credentials: "omit", redirect: "follow" });
  if (!r.ok) throw new Error(`HTTP ${r.status} for ${url}`);
  const buf = await r.arrayBuffer();
  const head = new TextDecoder().decode(buf.slice(0, 5));
  const ctype = (r.headers.get("content-type") || "").split(";")[0].trim().toLowerCase();
  let pages, contentType;
  if (head === "%PDF-" || ctype === "application/pdf") {
    pages = await pdfPagesFromData(new Uint8Array(buf.slice(0)));
    contentType = "application/pdf";
    const chars = pages.reduce((a, p) => a + p.trim().length, 0);
    if (pages.length && chars / pages.length < 80) flags.push("little or no text layer (scanned PDF?) - OCR needed, extraction unreliable");
  } else {
    pages = [htmlToText(new TextDecoder().decode(buf))];
    if (hints.opd_doc_id || /\.pdf($|\?)/i.test(url))
      flags.push("source is listed as a PDF but the file is not a PDF (e.g. a Fedlex JavaScript wall) - nothing reliable to extract");
    contentType = ctype || "text/html";
  }
  if (!hints.body_key) {
    const [lvl, key] = levelFromDomain(r.url || url);
    if (lvl) Object.assign(hints, { level_from_domain: lvl, body_key: key });
  }
  const lvl = levelFromBodyKey(hints.body_key);
  if (lvl) hints.level = lvl;
  return { url: r.url || url, pages, sha256: await sha256(buf), contentType, hints, flags };
}

export async function extract(doc) {
  const { vocab, prompts } = await shared();
  const [text, truncated] = buildText(doc.pages, prompts.max_doc_chars);
  let user = prompts.extract.user_template;
  const rep = { "{affair_types}": Object.keys(vocab.affair_types), "{actor_roles}": Object.keys(vocab.actor_roles),
    "{actor_kinds}": vocab.actor_kinds, "{procedural_states}": Object.keys(vocab.procedural_states),
    "{decision_outcomes}": Object.keys(vocab.decision_outcomes), "{relation_types}": vocab.relation_types };
  for (const [k, v] of Object.entries(rep)) user = user.replaceAll(k, v.join(", "));
  user = user.replace("{text}", () => text);
  const s = await settings();
  const { raw, usage } = await chatJson(prompts.extract.system, user, 6000, prompts);
  const rec = assemble(doc, raw, { usage, truncated, model: s.model, vocab, prompts });
  rec.extractor.raw_model_output = raw; // kept so verification can be re-run offline
  return rec;
}

// ---------------------------------------------------------------- summary + news
export async function summarize(text, { withNews = true } = {}) {
  const { prompts } = await shared();
  const s = await settings();
  const max = prompts.max_doc_chars;
  let user = prompts.summarize.user_template.replace("{text}", () => text.slice(0, max));
  if (s.summaryLang && s.summaryLang !== "doc") user += `\nWrite the summary and key points in this language instead: ${s.summaryLang}.`;
  const { raw: d, usage } = await chatJson(prompts.summarize.system, user, 1500, prompts);
  const summary = String(d.summary || "");
  const lang = normLang(d.language, summary);
  const topics = [];
  for (const t of d.topics || []) {
    if (!t || !t.phrase) continue;
    const topic = { phrase: String(t.phrase), query: String(t.query || t.phrase) };
    topic.span = locatePhrase(summary, topic.phrase);
    topic.in_summary = !!topic.span;
    if (withNews) topic.articles = await news(topic.query, lang);
    topics.push(topic);
  }
  return { language: lang, summary, key_points: d.key_points || [], topics, truncated: text.length > max, usage };
}

export async function news(query, lang = "de", limit = 5) {
  const { prompts } = await shared();
  const cfg = prompts.news;
  if (!cfg.supported_lang.includes(lang)) lang = cfg.fallback_lang;
  const sites = cfg.swiss_sites?.[lang];
  const words = (query.match(/[\p{L}\p{N}]+/gu) || []).filter((w) => w.length >= 4);
  // progressively shorter queries: the model's query is sometimes too specific to match anything
  const queries = [...new Set([query, words.slice(0, 3).join(" "), words.slice(0, 2).join(" ")].filter((q) => q.trim()))];
  for (const q of queries) {
    const full = sites ? `${q} (${sites.map((x) => "site:" + x).join(" OR ")})` : q;
    const url = cfg.google_news_rss.replace("{query}", encodeURIComponent(full)).replaceAll("{lang}", lang);
    try {
      const r = await fetch(url, { credentials: "omit" });
      const x = new DOMParser().parseFromString(await r.text(), "text/xml");
      const all = [...x.querySelectorAll("item")].slice(0, 20).map((it) => {
        const source = it.querySelector("source")?.textContent?.trim() || "";
        let title = it.querySelector("title")?.textContent?.trim() || "";
        if (source && title.endsWith(" - " + source)) title = title.slice(0, -(source.length + 3));
        return { title, url: it.querySelector("link")?.textContent?.trim() || "", source,
          published: it.querySelector("pubDate")?.textContent?.trim() || "", query: q };
      });
      const items = rankNews(all, query, limit);
      if (items.length) return items;
    } catch {}
  }
  return [];
}

// ---------------------------------------------------------------- UI helpers
export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Summary HTML with topic phrases turned into news links (phrases not found verbatim become chips).
export function summaryHtml(res) {
  const html = highlightSegments(res.summary, res.topics).map((sg) => sg.topic == null ? esc(sg.text)
    : `<a class="w-topic" data-topic="${sg.topic}" href="#" title="Swiss news: ${esc(res.topics[sg.topic].query)}">${esc(sg.text)}</a>`).join("");
  const chips = res.topics.map((t, i) => (t.span ? "" : `<a class="w-topic" data-topic="${i}" href="#" title="Swiss news: ${esc(t.query)}">${esc(t.phrase)}</a>`)).filter(Boolean);
  const kp = (res.key_points || []).map((p) => `<li>${esc(p)}</li>`).join("");
  return `<p class="w-summary">${html}</p>${kp ? `<ul class="w-kp">${kp}</ul>` : ""}` +
    (chips.length ? `<div class="w-chips">${chips.join(" ")}</div>` : "");
}

export function newsHtml(topic) {
  if (!topic.articles?.length) return `<div class="w-news-empty">No Swiss news found for “${esc(topic.query)}”.</div>`;
  return `<div class="w-news-h">Swiss news · ${esc(topic.query)}</div><ul class="w-news">` + topic.articles.map((a) =>
    `<li><a href="${/^https?:\/\//.test(a.url) ? esc(a.url) : "#"}" target="_blank" rel="noopener noreferrer">${esc(a.title)}</a><span>${esc(a.source)}${a.published ? " · " + esc(a.published.slice(5, 16)) : ""}</span></li>`,
  ).join("") + "</ul>";
}

export function bindTopics(root, res) {
  root.querySelectorAll(".w-topic").forEach((a) => {
    a.addEventListener("click", (ev) => {
      ev.preventDefault();
      const box = root.querySelector(".w-newsbox") || root.appendChild(Object.assign(document.createElement("div"), { className: "w-newsbox" }));
      box.innerHTML = newsHtml(res.topics[+a.dataset.topic]);
      root.querySelectorAll(".w-topic.on").forEach((x) => x.classList.remove("on"));
      a.classList.add("on");
    });
  });
}

export function downloadBlob(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
}
