// Pure William logic (no browser APIs): provenance verification, assembly, JSON parsing.
// Shared by the extension (engine.js) and the Node parity test (tests/parity.mjs).
export const SCHEMA_VERSION = "opd-affair/0.1";

export function parseJson(text) {
  const t = text.replace(/^```(?:json)?\s*|\s*```$/gm, "").trim();
  const start = t.indexOf("{");
  if (start < 0) throw new Error("no JSON object in model output");
  let depth = 0, inStr = false, esc = false;
  for (let i = start; i < t.length; i++) {
    const c = t[i];
    if (inStr) {
      if (esc) esc = false;
      else if (c === "\\") esc = true;
      else if (c === '"') inStr = false;
    } else if (c === '"') inStr = true;
    else if (c === "{") depth++;
    else if (c === "}" && --depth === 0) {
      const chunk = t.slice(start, i + 1);
      try { return JSON.parse(chunk); }
      // repair lone backslashes the model sometimes emits (e.g. "x\_y")
      catch { return JSON.parse(chunk.replace(/\\(?!["\\/bfnrtu])/g, "\\\\")); }
    }
  }
  throw new Error("unterminated JSON object in model output");
}

// ---------------------------------------------------------------- provenance verification (port of verify.py)
const TRANS = { "’": "'", "‘": "'", "‛": "'", "´": "'", "`": "'", "“": '"', "”": '"',
  "„": '"', "–": "-", "—": "-", "‑": "-", " ": " ", " ": " " };

export function normalise(text) {
  const out = [], idx = [];
  let prevSpace = true;
  for (let i = 0; i < text.length; i++) {
    let c = text[i];
    if (c === "­") continue;
    if (c === "-" && text[i + 1] === "\n" && out.length && /\p{L}/u.test(out[out.length - 1])) {
      let j = i + 1;
      while (j < text.length && /\s/.test(text[j])) j++;
      if (j < text.length && /\p{Ll}/u.test(text[j])) { i = j - 1; continue; }
    }
    c = (TRANS[c] || c).normalize("NFC").toLowerCase()[0]; // "İ".toLowerCase() is 2 chars
    if (/[\p{P}\p{S}]/u.test(c)) c = " "; // punctuation/symbols compare as spaces
    if (/\s/.test(c)) {
      if (prevSpace) continue;
      c = " "; prevSpace = true;
    } else prevSpace = false;
    out.push(c); idx.push(i);
  }
  return [out.join(""), idx];
}
const normOnly = (t) => normalise(t || "")[0].trim();

export class PageIndex {
  constructor(pages) {
    this.pages = pages;
    this.norm = pages.map(normalise);
    // space-free view: some PDFs have no space glyphs ("RéponsedelaMunicipalité")
    this.tight = this.norm.map(([t, m]) => {
      const keep = [...t].map((c, i) => (c === " " ? -1 : i)).filter((i) => i >= 0);
      return [keep.map((i) => t[i]).join(""), keep.map((i) => m[i])];
    });
  }
  find(quote, page) {
    const q = normOnly(quote);
    if (q.length < 3) return null;
    const order = [...this.pages.keys()];
    if (Number.isInteger(page) && page >= 1 && page <= this.pages.length) {
      order.splice(page - 1, 1); order.unshift(page - 1);
    }
    for (const pi of order) {
      const [nt, map] = this.norm[pi];
      const k = nt.indexOf(q);
      if (k >= 0) return [pi + 1, map[k], map[k + q.length - 1] + 1];
      if (q.length > 40) {
        const head = q.slice(0, 25), tail = q.slice(-25);
        const h = nt.indexOf(head);
        if (h >= 0) {
          const t = nt.indexOf(tail, h);
          if (t >= 0 && t - h < q.length * 2) return [pi + 1, map[h], map[t + tail.length - 1] + 1];
        }
      }
    }
    const qt = q.replace(/ /g, "");
    if (qt.length >= 8) {
      for (const pi of order) {
        const [tt, tm] = this.tight[pi];
        const k = tt.indexOf(qt);
        if (k >= 0) return [pi + 1, tm[k], tm[k + qt.length - 1] + 1];
      }
    }
    return null;
  }
  contains(v) {
    const n = normOnly(v);
    if (!n) return false;
    const nt = n.replace(/ /g, "");
    return this.norm.some(([t]) => t.includes(n)) || (nt.length >= 8 && this.tight.some(([t]) => t.includes(nt)));
  }
}

const MONTHS = { 1: ["jan", "janv", "genn", "jän"], 2: ["feb", "févr", "fevr", "febbr"], 3: ["mär", "märz", "mars", "marz", "marzo"],
  4: ["apr", "avr"], 5: ["mai", "mag"], 6: ["jun", "juin", "giu"], 7: ["jul", "juil", "lug"], 8: ["aug", "août", "aout", "ago"],
  9: ["sep", "sept", "set"], 10: ["okt", "oct", "ott"], 11: ["nov"], 12: ["dez", "déc", "dec", "dic"] };

export function dateSupported(value, quote) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value || "");
  if (!m) return false;
  const [y, mo, d] = [+m[1], +m[2], +m[3]];
  const q = normOnly(quote);
  const nums = (q.match(/\d+/g) || []);
  if (!q.includes(String(y)) && !nums.includes(String(y % 100).padStart(2, "0"))) return false;
  const ints = nums.map(Number);
  if (!ints.includes(d)) return false;
  return ints.includes(mo) || MONTHS[mo].some((n) => q.includes(n));
}

// ---------------------------------------------------------------- extraction (port of extract.py)
const VERBATIM = new Set(["name", "affair_number", "parliament", "party_or_group", "reference", "number", "body", "addressed_to"]);
const DATES = new Set(["submission_date", "date"]);
const INTS = new Set(["votes_yes", "votes_no", "votes_abstain"]);

export function lookupTypeTerm(original, vocab) {
  const terms = Object.fromEntries(Object.entries(vocab.type_terms || {}).filter(([k]) => !k.startsWith("_")));
  const o = normOnly(original).split(" ").filter(Boolean).join(" ");
  if (o in terms) return terms[o];
  const best = Object.keys(terms).filter((t) => o.startsWith(t + " ")).sort((a, b) => b.length - a.length)[0];
  return best ? terms[best] : null;
}

export function buildText(pages, maxChars) {
  let out = "", truncated = false;
  for (let i = 0; i < pages.length; i++) {
    const block = `=== PAGE ${i + 1} ===\n${pages[i].trim()}\n`;
    if (out.length + block.length > maxChars) {
      const room = maxChars - out.length;
      if (room > 500) out += block.slice(0, room);
      truncated = true;
      break;
    }
    out += block;
  }
  return [out, truncated];
}

function vocabLists(v) {
  return { level: Object.keys(v.levels), affair_type: Object.keys(v.affair_types), role: Object.keys(v.actor_roles),
    kind: v.actor_kinds, state: Object.keys(v.procedural_states), outcome: Object.keys(v.decision_outcomes),
    relation: v.relation_types };
}

export function assemble(doc, raw, { usage = {}, truncated = false, model, vocab, prompts }) {
  const idx = new PageIndex(doc.pages);
  const VL = vocabLists(vocab);
  const stats = { extracted: 0, normalised: 0, inferred: 0, rejected: 0, metadata: 0 };
  const rejected = [];
  const reject = (o) => { stats.rejected++; rejected.push(o); return null; };
  const L = (x) => (Array.isArray(x) ? x : []);

  function f(rawF, name, path) {
    if (rawF == null) return null;
    if (typeof rawF !== "object") rawF = { v: rawF };
    let value = rawF.v;
    if (value == null || (typeof value === "string" && !value.trim())) return null;
    let quote = rawF.q || "";
    let page = Number.parseInt(rawF.p, 10);
    if (Number.isNaN(page)) page = null;
    let hit = quote ? idx.find(quote, page) : null;
    if (!hit && typeof value === "string" && !(name in VL) && !DATES.has(name) && value.length >= 4) hit = idx.find(value, page);
    if (!hit && name in VL) {
      // a classification is a judgement, not a copied fact: keep legal terms, marked inferred
      const v = String(value).trim().toLowerCase().replace(/ /g, "_");
      if (VL[name].includes(v)) { stats.inferred++; return { value: v, status: "inferred", page: null, quote: null, char_start: null, char_end: null }; }
    }
    if (!hit) return reject({ path, value, page, quote });
    const [pg, start, end] = hit;
    const qt = doc.pages[pg - 1].slice(start, end);
    let status = "extracted";
    if (name in VL) {
      const v = String(value).trim().toLowerCase().replace(/ /g, "_");
      if (!VL[name].includes(v)) return reject({ path, value, reason: "not in vocabulary" });
      value = v; status = "normalised";
    } else if (DATES.has(name)) {
      if (!dateSupported(String(value), qt)) return reject({ path, value, quote: qt, reason: "date not supported by quote" });
      status = "normalised";
    } else if (INTS.has(name)) {
      value = Number.parseInt(String(value).replace(/'/g, ""), 10);
      if (Number.isNaN(value) || !(qt.match(/\d+/g) || []).includes(String(value))) return reject({ path, value, reason: "number not in quote" });
    } else if (typeof value === "string") {
      if (!normOnly(qt).includes(normOnly(value)) && !idx.contains(value)) status = VERBATIM.has(name) ? "inferred" : "normalised";
    }
    stats[status]++;
    return { value, status, page: pg, quote: qt, char_start: start, char_end: end };
  }

  // same evaluation order as extract.py: a rejected key field skips the rest of the item
  const actors = [];
  L(raw.actors).forEach((a, i) => {
    if (!a || typeof a !== "object") return;
    const name = f(a.name, "name", `actors[${i}].name`);
    if (!name) return;
    actors.push({ name, role: f(a.role, "role", `actors[${i}].role`), kind: f(a.kind, "kind", `actors[${i}].kind`),
      party_or_group: f(a.party_or_group, "party_or_group", `actors[${i}].party_or_group`) });
  });
  const questions = [];
  L(raw.questions).forEach((q, i) => {
    if (!q || typeof q !== "object") return;
    const question = f(q.question, "question", `questions[${i}].question`);
    if (!question) return;
    questions.push({ number: f(q.number, "number", `questions[${i}].number`), question,
      answer: f(q.answer, "answer", `questions[${i}].answer`) });
  });
  const history = L(raw.procedural_history).filter((h) => h && typeof h === "object").map((h, i) => ({
    date: f(h.date, "date", `procedural_history[${i}].date`), state: f(h.state, "state", `procedural_history[${i}].state`),
    description: f(h.description, "description", `procedural_history[${i}].description`),
  })).filter((h) => h.date || h.description);
  const decisions = L(raw.decisions).filter((d) => d && typeof d === "object").map((d, i) => Object.fromEntries(
    ["date", "body", "outcome", "votes_yes", "votes_no", "votes_abstain"].map((k) => [k, f(d[k], k, `decisions[${i}].${k}`)]),
  )).filter((d) => d.outcome);
  const related = [];
  L(raw.related_affairs).forEach((r, i) => {
    if (!r || typeof r !== "object") return;
    const reference = f(r.reference, "reference", `related_affairs[${i}].reference`);
    if (reference) related.push({ reference, relation: f(r.relation, "relation", `related_affairs[${i}].relation`) });
  });
  const requests = L(raw.requests).map((r, i) => f(r, "request", `requests[${i}]`)).filter(Boolean);

  let type = f(raw.affair_type, "affair_type", "affair_type");
  const typeOriginal = f(raw.affair_type_original, "affair_type_original", "affair_type_original");
  const typeFlags = [];
  const mapped = typeOriginal ? lookupTypeTerm(typeOriginal.value, vocab) : null;
  if (mapped) {
    // the parliament's own word for the instrument beats the model's guess
    // (e.g. Ticino "interrogazione" is a written question, not an interpellation)
    if (type && type.value !== mapped)
      typeFlags.push(`model type '${type.value}' replaced by '${mapped}' from the original term '${typeOriginal.value}'`);
    else if (!type) stats.normalised++;
    type = { page: typeOriginal.page, quote: typeOriginal.quote, char_start: typeOriginal.char_start, char_end: typeOriginal.char_end,
      value: mapped, status: "normalised", source: "type_terms lookup on type_original" };
  }
  if (type) Object.assign(type, { opd_type_harmonized_id: vocab.affair_types[type.value].opd_type_harmonized_id,
    wikidata: vocab.affair_types[type.value].wikidata });
  const state = f(raw.state, "state", "state");
  if (state) state.opd_state_name_harmonized_id = vocab.procedural_states[state.value].opd_state_name_harmonized_id;

  const h = doc.hints || {};
  let level;
  if (h.level) {
    level = { value: h.level, status: "metadata", source: h.level_from_domain ? "URL domain" : "OpenParlData body_key" };
    stats.metadata++;
  } else {
    level = f(raw.level, "level", "level");
    const lv = raw.level && typeof raw.level === "object" ? raw.level.v : raw.level;
    if (!level && VL.level.includes(lv)) { level = { value: lv, status: "inferred", source: "model, no verifiable quote" }; stats.inferred++; }
  }
  const flags = [...(doc.flags || []), ...typeFlags];
  if (truncated) flags.push(`document longer than ${prompts.max_doc_chars} characters - only the beginning was read`);
  if (h.opd_type_harmonized_id && type && h.opd_type_harmonized_id !== type.opd_type_harmonized_id)
    flags.push(`affair_type '${type.value}' disagrees with OpenParlData type_harmonized_id ${h.opd_type_harmonized_id}`);
  if (stats.rejected) flags.push(`${stats.rejected} model value(s) rejected: quote not found in the document`);
  if (!type) flags.push("affair type could not be verified");

  const affair = {
    affair_number: f(raw.affair_number, "affair_number", "affair_number"), title: f(raw.title, "title", "title"),
    type, type_original: typeOriginal,
    submission_date: f(raw.submission_date, "submission_date", "submission_date"), actors,
    addressed_to: f(raw.addressed_to, "addressed_to", "addressed_to"), requests, questions,
    procedural_history: history, state, decisions, related_affairs: related,
    keywords: L(raw.keywords).filter((k) => typeof k === "string").slice(0, 8),
  };
  if (h.affair_number && !affair.affair_number) affair.affair_number = { value: h.affair_number, status: "metadata", source: "OpenParlData" };
  const total = stats.extracted + stats.normalised + stats.inferred + stats.metadata;
  return {
    schema_version: SCHEMA_VERSION,
    source: { url: doc.url, sha256: doc.sha256, content_type: doc.contentType, pages: doc.pages.length,
      opd_doc_id: h.opd_doc_id ?? null, opd_affair_id: h.opd_affair_id ?? null, retrieved_at: new Date().toISOString() },
    language: h.language || (typeof raw.language === "string" ? raw.language : null),
    body: { level, body_key: h.body_key || null, parliament: f(raw.parliament, "parliament", "parliament"),
      opd_body_type: level ? vocab.levels[level.value].opd_body_type : null },
    affair,
    quality: {
      value_counts: stats,
      verified_share: Math.round(((stats.extracted + stats.normalised + stats.metadata) / Math.max(1, total + stats.rejected)) * 1000) / 1000,
      rejected_values: rejected, flags, needs_review: flags.length > 0 || stats.inferred > 0,
    },
    extractor: { model, prompt_version: prompts.prompt_version, usage, runtime: "firefox-extension" },
  };
}


// Where in the summary does a topic phrase sit? Apertus often paraphrases the phrase, so after an exact match
// we look for the shortest run of summary words that covers most of the phrase's content words (5-letter stems).
const stem = (w) => w.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().slice(0, 5);
export function locatePhrase(summary, phrase) {
  const k = summary.toLowerCase().indexOf(String(phrase).toLowerCase());
  if (k >= 0 && phrase) return [k, k + phrase.length];
  // phrase copied from a space-less PDF text layer ("rabaissurlesabonnements"): compare without spaces
  if (/[\p{L}]{20,}/u.test(String(phrase))) {
    const keep = [...summary].map((c, i) => (/[\p{L}\p{N}]/u.test(c) ? i : -1)).filter((i) => i >= 0);
    const flat = keep.map((i) => summary[i]).join("").toLowerCase();
    const q = (String(phrase).match(/[\p{L}\p{N}]+/gu) || []).join("").toLowerCase();
    for (let n = q.length; n >= 12; n -= 4) {
      const k2 = flat.indexOf(q.slice(0, n));
      if (k2 >= 0) return [keep[k2], keep[k2 + n - 1] + 1];
    }
  }
  const want = [...new Set((String(phrase).match(/[\p{L}\p{N}]+/gu) || []).filter((w) => w.length >= 4).map(stem))];
  if (!want.length) return null;
  const toks = [...summary.matchAll(/[\p{L}\p{N}]+/gu)].map((m) => ({ s: m.index, e: m.index + m[0].length, st: stem(m[0]) }));
  const need = want.length >= 2 ? Math.max(2, Math.ceil(want.length / 2)) : 1;
  let best = null;
  for (let i = 0; i < toks.length; i++) {
    if (!want.includes(toks[i].st)) continue;
    const seen = new Set();
    for (let j = i; j < Math.min(toks.length, i + want.length + 4); j++) {
      if (want.includes(toks[j].st)) seen.add(toks[j].st);
      if (seen.size >= need && want.includes(toks[j].st)) {
        const cand = { n: seen.size, len: j - i, span: [toks[i].s, toks[j].e] };
        if (!best || cand.n > best.n || (cand.n === best.n && cand.len < best.len)) best = cand;
      }
    }
  }
  return best ? best.span : null;
}

// Summary text split into plain / highlighted segments (non-overlapping, in order).
export function highlightSegments(summary, topics) {
  const spans = topics.map((t, i) => (t.span ? { s: t.span[0], e: t.span[1], i } : null)).filter(Boolean).sort((a, b) => a.s - b.s);
  const segs = [];
  let pos = 0;
  for (const sp of spans) {
    if (sp.s < pos) continue; // overlapping: keep the first
    if (sp.s > pos) segs.push({ text: summary.slice(pos, sp.s) });
    segs.push({ text: summary.slice(sp.s, sp.e), topic: sp.i });
    pos = sp.e;
  }
  segs.push({ text: summary.slice(pos) });
  return segs;
}

// Apertus sometimes returns a wrong language code (e.g. "ge" for German). Map aliases; else guess from stopwords.
const LANG_ALIAS = { ge: "de", ger: "de", deu: "de", fre: "fr", fra: "fr", ita: "it", roh: "rm", rom: "rm", rum: "rm", eng: "en" };
const STOP = { de: ["der", "die", "und", "das", "nicht", "mit", "für", "ist"], fr: ["le", "la", "les", "des", "et", "est", "pour", "une"],
  it: ["il", "che", "della", "per", "non", "una", "sono", "del"], en: ["the", "and", "of", "to", "is", "for", "that", "with"],
  rm: ["da", "la", "il", "e", "per", "cun", "ina", "ils"] };
export function normLang(code, text) {
  const c = String(code || "").trim().toLowerCase().slice(0, 3);
  if (["de", "fr", "it", "rm", "en"].includes(c.slice(0, 2)) && !LANG_ALIAS[c]) return c.slice(0, 2);
  if (LANG_ALIAS[c]) return LANG_ALIAS[c];
  const words = String(text || "").toLowerCase().match(/\p{L}+/gu) || [];
  let best = "de", n = -1;
  for (const [l, sw] of Object.entries(STOP)) {
    const k = words.filter((w) => sw.includes(w)).length;
    if (k > n) { n = k; best = l; }
  }
  return best;
}

// Rank news items by how many of the query's content words (5-letter stems) their title shares; drop unrelated
// items when at least two related ones exist. Google's search is broad; this keeps the list on-topic.
export function rankNews(items, query, limit = 5) {
  const want = new Set((String(query).match(/[\p{L}\p{N}]+/gu) || []).filter((w) => w.length >= 4).map(stem));
  const scored = items.map((it, i) => ({ it, i, n: new Set((it.title.match(/[\p{L}\p{N}]+/gu) || []).map(stem).filter((t) => want.has(t))).size }));
  scored.sort((a, b) => b.n - a.n || a.i - b.i);
  const related = scored.filter((x) => x.n > 0);
  return (related.length >= 2 ? related : scored).slice(0, limit).map((x) => x.it);
}
