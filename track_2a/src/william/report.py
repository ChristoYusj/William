"""PDF report: one section per link (summary + extracted structure + provenance)."""
from __future__ import annotations

import json

from fpdf import FPDF

from .shared import vocab

STATUS_MARK = {"extracted": "", "normalised": " [n]", "inferred": " [inferred]", "metadata": " [meta]"}


def _t(s) -> str:
    """Core PDF fonts are Latin-1: keep accents, replace the rest."""
    s = "" if s is None else str(s)
    s = (s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
         .replace("„", '"').replace("–", "-").replace("—", "-").replace("…", "...")
         .replace("­", ""))
    return s.encode("latin-1", "replace").decode("latin-1")


def _v(field) -> str:
    if not field:
        return "-"
    val = field.get("value")
    page = f" (p.{field['page']})" if field.get("page") else ""
    return f"{val}{STATUS_MARK.get(field.get('status'), '')}{page}"


class Report(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(120)
        self.cell(0, 6, _t("William - OpenParlData affair extraction (opd-affair/0.1) - Apertus"), align="R")
        self.ln(8)
        self.set_text_color(0)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(120)
        self.cell(0, 6, f"{self.page_no()}", align="C")

    def heading(self, text, size=13):
        self.set_font("Helvetica", "B", size)
        self.multi_cell(0, 6, _t(text), new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def para(self, text, size=9.5, style=""):
        self.set_font("Helvetica", style, size)
        self.multi_cell(0, 4.8, _t(text), new_x="LMARGIN", new_y="NEXT")

    def kv(self, k, v):
        self.set_font("Helvetica", "B", 9)
        self.cell(38, 5, _t(k))
        self.set_font("Helvetica", "", 9)
        self.multi_cell(0, 5, _t(v), new_x="LMARGIN", new_y="NEXT")


def build(items: list[dict], *, include_json: bool = True) -> bytes:
    """items: [{"url", "record"?, "summary"?, "error"?}]"""
    pdf = Report(format="A4")
    pdf.set_auto_page_break(True, 15)
    pdf.set_margins(15, 12, 15)
    pdf.add_page()
    pdf.heading("Parliamentary affairs - summary report", 16)
    pdf.para(f"{len(items)} link(s). Values marked [inferred] were not found verbatim in the source; "
          "[n] = normalised from a verified quote (date, vocabulary); [meta] = from OpenParlData metadata. "
          "Values whose quote could not be found in the document were removed.", 8.5, "I")
    pdf.ln(3)
    types = vocab()["affair_types"]
    for n, it in enumerate(items, 1):
        if n > 1:
            pdf.add_page()
        pdf.heading(f"{n}. {it.get('url')}", 10)
        if it.get("error"):
            pdf.para(f"Error: {it['error']}", 9.5, "B")
            continue
        rec = it.get("record") or {}
        a = rec.get("affair") or {}
        b = rec.get("body") or {}
        title = (a.get("title") or {}).get("value") or "(no verified title)"
        pdf.heading(title, 12)
        s = it.get("summary") or {}
        if s.get("summary"):
            pdf.para(s["summary"])
            for kp in s.get("key_points") or []:
                pdf.para(f"  - {kp}", 9)
            pdf.ln(2)
        tr = s.get("translation") or {}
        if tr.get("error"):
            pdf.para(f"Translation into {str(tr.get('language', '')).upper()} failed: {tr['error']}", 8.5, "I")
            pdf.ln(2)
        elif tr.get("summary") and not tr.get("note"):
            pdf.heading(f"Summary - {str(tr.get('source_language') or '?').upper()} > "
                        f"{str(tr.get('language')).upper()} translation (Apertus)", 10)
            pdf.para(tr["summary"])
            for kp in tr.get("key_points") or []:
                pdf.para(f"  - {kp}", 9)
            pdf.ln(2)
        t = a.get("type")
        tlabel = types.get(t["value"], {}).get("label", {}).get("en") if t else None
        pdf.kv("Level", _v(b.get("level")))
        pdf.kv("Parliament", _v(b.get("parliament")) + (f"  body_key={b.get('body_key')}" if b.get("body_key") else ""))
        pdf.kv("Number", _v(a.get("affair_number")))
        pdf.kv("Type", f"{tlabel or '-'}" + (f"  (OPD type id {t.get('opd_type_harmonized_id')})" if t else "") +
               (f"  original: {_v(a.get('type_original'))}" if a.get("type_original") else ""))
        pdf.kv("Submitted", _v(a.get("submission_date")))
        pdf.kv("Addressed to", _v(a.get("addressed_to")))
        pdf.kv("State", _v(a.get("state")))
        for ac in a.get("actors") or []:
            pdf.kv("Actor", f"{_v(ac.get('name'))} - {(ac.get('role') or {}).get('value', '?')}"
                   f"{' - ' + str((ac.get('party_or_group') or {}).get('value')) if ac.get('party_or_group') else ''}")
        for r in a.get("requests") or []:
            pdf.kv("Request", _v(r))
        for q in a.get("questions") or []:
            pdf.kv(f"Question {(q.get('number') or {}).get('value', '')}", _v(q.get("question")))
            if q.get("answer"):
                pdf.kv("  Answer", _v(q.get("answer")))
        for d in a.get("decisions") or []:
            pdf.kv("Decision", f"{_v(d.get('outcome'))} {_v(d.get('date'))} {_v(d.get('body'))}")
        for r in a.get("related_affairs") or []:
            pdf.kv("Related", f"{_v(r.get('reference'))} ({(r.get('relation') or {}).get('value', '?')})")
        if s.get("topics"):
            pdf.ln(1)
            pdf.heading("In the news", 10)
            for tp in s["topics"]:
                for art in (tp.get("articles") or [])[:2]:
                    pdf.set_font("Helvetica", "U", 8.5)
                    pdf.set_text_color(20, 70, 160)
                    pdf.multi_cell(0, 4.5, _t(f"[{tp['phrase']}] {art['title']} - {art.get('source', '')}"),
                                   link=art.get("url") or "", new_x="LMARGIN", new_y="NEXT")
                    pdf.set_text_color(0)
        q = rec.get("quality") or {}
        pdf.ln(1)
        pdf.para(f"Quality: verified share {q.get('verified_share')}, counts {q.get('value_counts')}", 8.5, "I")
        for fl in q.get("flags") or []:
            pdf.para(f"! {fl}", 8.5, "I")
        if include_json and rec:
            pdf.ln(2)
            pdf.heading("JSON (opd-affair/0.1)", 9)
            rec = {**rec, "extractor": {k: v for k, v in rec.get("extractor", {}).items() if k != "raw_model_output"}}
            slim = json.dumps(rec, ensure_ascii=False, indent=1)
            pdf.set_font("Courier", "", 6.5)
            pdf.multi_cell(0, 3, _t(slim), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
