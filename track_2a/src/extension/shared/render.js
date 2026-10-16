// Render an opd-affair/0.1 record as a readable table with provenance badges.
import { esc } from "./engine.js";

const fv = (f) => {
  if (!f) return '<span class="muted">—</span>';
  const pg = f.page ? `<a class="pg" data-page="${f.page}" title="${esc(f.quote || "")}">p.${f.page}</a>` : "";
  return `${esc(f.value)}<span class="st ${esc(f.status)}" title="${esc(f.status)}">${esc(f.status)}</span>${pg}`;
};

export function recordHtml(rec, vocab) {
  const a = rec.affair || {}, b = rec.body || {};
  const rows = [];
  const row = (k, v) => rows.push(`<tr><th>${esc(k)}</th><td>${v}</td></tr>`);
  row("Level", fv(b.level) + (b.body_key ? ` <span class="muted small">body_key ${esc(b.body_key)}</span>` : ""));
  row("Parliament", fv(b.parliament));
  row("Number", fv(a.affair_number));
  row("Title", fv(a.title));
  const t = a.type;
  row("Type", fv(t) + (t ? ` <span class="muted small">${esc(vocab?.affair_types?.[t.value]?.label?.en || "")} · OPD id ${esc(t.opd_type_harmonized_id ?? "–")}</span>` : ""));
  row("Type (original)", fv(a.type_original));
  row("Submitted", fv(a.submission_date));
  row("Addressed to", fv(a.addressed_to));
  row("State", fv(a.state));
  (a.actors || []).forEach((x) => row("Actor", `${fv(x.name)}<br><span class="small">${x.role ? "role " + fv(x.role) : ""} ${x.kind ? "· " + fv(x.kind) : ""} ${x.party_or_group ? "· " + fv(x.party_or_group) : ""}</span>`));
  (a.requests || []).forEach((x) => row("Request", fv(x)));
  (a.questions || []).forEach((q) => row(`Question ${q.number?.value ?? ""}`, fv(q.question) + (q.answer ? `<br><b class="small">Answer</b> ${fv(q.answer)}` : "")));
  (a.procedural_history || []).forEach((h) => row("History", `${fv(h.date)} ${fv(h.state)} ${fv(h.description)}`));
  (a.decisions || []).forEach((d) => row("Decision", `${fv(d.outcome)} ${fv(d.date)} ${fv(d.body)} ${d.votes_yes ? `yes ${fv(d.votes_yes)} no ${fv(d.votes_no)}` : ""}`));
  (a.related_affairs || []).forEach((r) => row("Related", `${fv(r.reference)} ${fv(r.relation)}`));
  if (a.keywords?.length) row("Keywords", esc(a.keywords.join(", ")));
  const q = rec.quality || {};
  const flags = (q.flags || []).map((f) => `<div class="flag">⚠ ${esc(f)}</div>`).join("");
  const counts = Object.entries(q.value_counts || {}).map(([k, v]) => `${k} ${v}`).join(" · ");
  return `<table class="fields">${rows.join("")}</table>
    <div class="small muted">Verified share ${esc(q.verified_share)} — ${esc(counts)}</div>${flags}`;
}
