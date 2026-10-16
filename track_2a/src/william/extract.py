"""Document -> opd-affair/0.1 record, with provenance on every value."""
from __future__ import annotations

import datetime as dt
import re

from . import llm
from .docs import Document
from .shared import SCHEMA_VERSION, prompts, vocab
from .verify import PageIndex, date_supported, norm_only

VOCAB_FIELDS = {
    "level": lambda: list(vocab()["levels"]),
    "affair_type": lambda: list(vocab()["affair_types"]),
    "role": lambda: list(vocab()["actor_roles"]),
    "kind": lambda: vocab()["actor_kinds"],
    "state": lambda: list(vocab()["procedural_states"]),
    "outcome": lambda: list(vocab()["decision_outcomes"]),
    "relation": lambda: vocab()["relation_types"],
}
DATE_FIELDS = {"submission_date", "date"}
INT_FIELDS = {"votes_yes", "votes_no", "votes_abstain"}
# free-text fields whose value must itself appear in the document
VERBATIM_FIELDS = {"name", "affair_number", "parliament", "party_or_group", "reference", "number", "body", "addressed_to"}


def lookup_type_term(original: str) -> str | None:
    """Map a verified original type word ('Kleine Anfrage', 'Interrogazione') to an affair_type."""
    terms = {k: v for k, v in vocab()["type_terms"].items() if not k.startswith("_")}
    o = " ".join(norm_only(original).split())
    if o in terms:
        return terms[o]
    best = max((t for t in terms if o.startswith(t + " ")), key=len, default=None)
    return terms[best] if best else None


def build_text(pages: list[str], max_chars: int) -> tuple[str, bool]:
    parts, total, truncated = [], 0, False
    for i, p in enumerate(pages, 1):
        block = f"=== PAGE {i} ===\n{p.strip()}\n"
        if total + len(block) > max_chars:
            room = max_chars - total
            if room > 500:
                parts.append(block[:room])
            truncated = True
            break
        parts.append(block)
        total += len(block)
    return "".join(parts), truncated


def render_prompt(text: str) -> tuple[str, str]:
    p = prompts()["extract"]
    v = vocab()
    user = p["user_template"]
    repl = {
        "{affair_types}": ", ".join(v["affair_types"]),
        "{actor_roles}": ", ".join(v["actor_roles"]),
        "{actor_kinds}": ", ".join(v["actor_kinds"]),
        "{procedural_states}": ", ".join(v["procedural_states"]),
        "{decision_outcomes}": ", ".join(v["decision_outcomes"]),
        "{relation_types}": ", ".join(v["relation_types"]),
        "{text}": text,
    }
    for k, val in repl.items():
        user = user.replace(k, val)
    return p["system"], user


class Checker:
    def __init__(self, index: PageIndex):
        self.index = index
        self.stats = {"extracted": 0, "normalised": 0, "inferred": 0, "rejected": 0, "metadata": 0}
        self.rejected: list[dict] = []

    def field(self, raw, name: str, path: str):
        """Verify one model field {"v","p","q"} -> provenance-annotated field or None."""
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raw = {"v": raw, "p": None, "q": None}
        value = raw.get("v")
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        quote = raw.get("q") or ""
        page = raw.get("p")
        try:
            page = int(page) if page is not None else None
        except (TypeError, ValueError):
            page = None
        hit = self.index.find(quote, page) if quote else None
        if hit is None:
            # no verifiable quote: the value itself may still be on a page
            if isinstance(value, str) and name not in VOCAB_FIELDS and name not in DATE_FIELDS and len(value) >= 4:
                hit = self.index.find(value, page)
                if hit:
                    quote = self.index.pages[hit[0] - 1][hit[1]:hit[2]]
        if hit is None and name in VOCAB_FIELDS:
            # a classification (role, kind, state...) is a judgement, not a copied fact:
            # keep it if it is a legal vocabulary term, but mark it as inferred
            v = str(value).strip().lower().replace(" ", "_")
            if v in VOCAB_FIELDS[name]():
                self.stats["inferred"] += 1
                return {"value": v, "status": "inferred", "page": None, "quote": None,
                        "char_start": None, "char_end": None}
        if hit is None:
            self.stats["rejected"] += 1
            self.rejected.append({"path": path, "value": value, "page": page, "quote": quote})
            return None
        pg, start, end = hit
        quote_text = self.index.pages[pg - 1][start:end]
        status = "extracted"

        if name in VOCAB_FIELDS:
            allowed = VOCAB_FIELDS[name]()
            v = str(value).strip().lower().replace(" ", "_")
            if v not in allowed:
                self.stats["rejected"] += 1
                self.rejected.append({"path": path, "value": value, "reason": "not in vocabulary"})
                return None
            value, status = v, "normalised"
        elif name in DATE_FIELDS:
            if not date_supported(str(value), quote_text):
                self.stats["rejected"] += 1
                self.rejected.append({"path": path, "value": value, "quote": quote_text, "reason": "date not supported by quote"})
                return None
            status = "normalised"
        elif name in INT_FIELDS:
            try:
                value = int(str(value).replace("'", "").strip())
            except ValueError:
                self.stats["rejected"] += 1
                return None
            if str(value) not in re.findall(r"\d+", quote_text):
                self.stats["rejected"] += 1
                self.rejected.append({"path": path, "value": value, "reason": "number not in quote"})
                return None
        elif isinstance(value, str):
            nv = norm_only(value)
            if nv not in norm_only(quote_text) and not self.index.contains(value):
                # paraphrase (e.g. a shortened request): keep, but say it is not verbatim
                status = "inferred" if name in VERBATIM_FIELDS else "normalised"
        self.stats[status] += 1
        return {"value": value, "status": status, "page": pg, "quote": quote_text,
                "char_start": start, "char_end": end}


def _list(x):
    return x if isinstance(x, list) else []


def extract(doc: Document, *, model: str | None = None) -> dict:
    cfg = prompts()
    text, truncated = build_text(doc.pages, cfg["max_doc_chars"])
    system, user = render_prompt(text)
    raw, usage = llm.chat_json(system, user, max_tokens=6000, retry_suffix=cfg["json_retry_suffix"], model=model)
    rec = assemble(doc, raw, usage=usage, truncated=truncated, model=model)
    rec["extractor"]["raw_model_output"] = raw   # kept so verification can be re-run offline
    return rec


def assemble(doc: Document, raw: dict, *, usage: dict | None = None, truncated: bool = False,
             model: str | None = None) -> dict:
    idx = PageIndex(doc.pages)
    ck = Checker(idx)
    f = ck.field

    actors = []
    for i, a in enumerate(_list(raw.get("actors"))):
        if not isinstance(a, dict):
            continue
        name = f(a.get("name"), "name", f"actors[{i}].name")
        if not name:
            continue
        actors.append({"name": name, "role": f(a.get("role"), "role", f"actors[{i}].role"),
                       "kind": f(a.get("kind"), "kind", f"actors[{i}].kind"),
                       "party_or_group": f(a.get("party_or_group"), "party_or_group", f"actors[{i}].party_or_group")})
    questions = []
    for i, q in enumerate(_list(raw.get("questions"))):
        if not isinstance(q, dict):
            continue
        qq = f(q.get("question"), "question", f"questions[{i}].question")
        if not qq:
            continue
        questions.append({"number": f(q.get("number"), "number", f"questions[{i}].number"), "question": qq,
                          "answer": f(q.get("answer"), "answer", f"questions[{i}].answer")})
    history = []
    for i, h in enumerate(_list(raw.get("procedural_history"))):
        if not isinstance(h, dict):
            continue
        e = {"date": f(h.get("date"), "date", f"procedural_history[{i}].date"),
             "state": f(h.get("state"), "state", f"procedural_history[{i}].state"),
             "description": f(h.get("description"), "description", f"procedural_history[{i}].description")}
        if e["date"] or e["description"]:
            history.append(e)
    decisions = []
    for i, d in enumerate(_list(raw.get("decisions"))):
        if not isinstance(d, dict):
            continue
        e = {k: f(d.get(k), k, f"decisions[{i}].{k}") for k in
             ("date", "body", "outcome", "votes_yes", "votes_no", "votes_abstain")}
        if e["outcome"]:
            decisions.append(e)
    related = []
    for i, r in enumerate(_list(raw.get("related_affairs"))):
        if not isinstance(r, dict):
            continue
        ref = f(r.get("reference"), "reference", f"related_affairs[{i}].reference")
        if ref:
            related.append({"reference": ref, "relation": f(r.get("relation"), "relation", f"related_affairs[{i}].relation")})
    requests = [x for x in (f(r, "request", f"requests[{i}]") for i, r in enumerate(_list(raw.get("requests")))) if x]

    affair_type = f(raw.get("affair_type"), "affair_type", "affair_type")
    type_original = f(raw.get("affair_type_original"), "affair_type_original", "affair_type_original")
    type_flags = []
    mapped = lookup_type_term(type_original["value"]) if type_original else None
    if mapped:
        # the parliament's own word for the instrument beats the model's guess
        # (e.g. Ticino "interrogazione" is a written question, not an interpellation)
        if affair_type and affair_type["value"] != mapped:
            type_flags.append(f"model type '{affair_type['value']}' replaced by '{mapped}' from the original term "
                              f"'{type_original['value']}'")
        elif not affair_type:
            ck.stats["normalised"] += 1
        affair_type = {k: type_original[k] for k in ("page", "quote", "char_start", "char_end")}
        affair_type.update(value=mapped, status="normalised", source="type_terms lookup on type_original")
    if affair_type:
        meta = vocab()["affair_types"][affair_type["value"]]
        affair_type["opd_type_harmonized_id"] = meta["opd_type_harmonized_id"]
        affair_type["wikidata"] = meta["wikidata"]
    state = f(raw.get("state"), "state", "state")
    if state:
        state["opd_state_name_harmonized_id"] = vocab()["procedural_states"][state["value"]]["opd_state_name_harmonized_id"]

    # level: metadata beats the model; model must still prove it with a quote
    hints = doc.hints
    level = None
    if hints.get("level"):
        level = {"value": hints["level"], "status": "metadata",
                 "source": "OpenParlData body_key" if "level_from_domain" not in hints else "URL domain"}
        ck.stats["metadata"] += 1
    else:
        level = f(raw.get("level"), "level", "level")
        if level is None and raw.get("level"):
            lv = raw["level"].get("v") if isinstance(raw["level"], dict) else raw["level"]
            if lv in vocab()["levels"]:
                level = {"value": lv, "status": "inferred", "source": "model, no verifiable quote"}
                ck.stats["inferred"] += 1

    flags = list(doc.flags) + type_flags
    if truncated:
        flags.append(f"document longer than {prompts()['max_doc_chars']} characters - only the beginning was read")
    if hints.get("opd_type_harmonized_id") and affair_type and \
            hints["opd_type_harmonized_id"] != affair_type.get("opd_type_harmonized_id"):
        flags.append(f"affair_type '{affair_type['value']}' disagrees with OpenParlData type_harmonized_id "
                     f"{hints['opd_type_harmonized_id']}")
    if ck.stats["rejected"]:
        flags.append(f"{ck.stats['rejected']} model value(s) rejected: quote not found in the document")
    if not affair_type:
        flags.append("affair type could not be verified")

    affair = {
        "affair_number": f(raw.get("affair_number"), "affair_number", "affair_number"),
        "title": f(raw.get("title"), "title", "title"),
        "type": affair_type,
        "type_original": type_original,
        "submission_date": f(raw.get("submission_date"), "submission_date", "submission_date"),
        "actors": actors,
        "addressed_to": f(raw.get("addressed_to"), "addressed_to", "addressed_to"),
        "requests": requests,
        "questions": questions,
        "procedural_history": history,
        "state": state,
        "decisions": decisions,
        "related_affairs": related,
        "keywords": [k for k in _list(raw.get("keywords")) if isinstance(k, str)][:8],
    }
    if hints.get("affair_number") and not affair["affair_number"]:
        affair["affair_number"] = {"value": hints["affair_number"], "status": "metadata", "source": "OpenParlData"}

    body_key = hints.get("body_key")
    body = {
        "level": level,
        "body_key": body_key,
        "parliament": f(raw.get("parliament"), "parliament", "parliament"),
        "opd_body_type": vocab()["levels"][level["value"]]["opd_body_type"] if level else None,
    }
    lang = hints.get("language") or (raw.get("language") if isinstance(raw.get("language"), str) else None)
    total = sum(ck.stats[k] for k in ("extracted", "normalised", "inferred", "metadata"))
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "url": doc.url, "sha256": doc.sha256, "content_type": doc.content_type,
            "pages": len(doc.pages), "opd_doc_id": hints.get("opd_doc_id"),
            "opd_affair_id": hints.get("opd_affair_id"),
            "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        },
        "language": lang,
        "body": body,
        "affair": affair,
        "quality": {
            "value_counts": ck.stats,
            "verified_share": round((ck.stats["extracted"] + ck.stats["normalised"] + ck.stats["metadata"]) /
                                    max(1, total + ck.stats["rejected"]), 3),
            "rejected_values": ck.rejected,
            "flags": flags,
            "needs_review": bool(flags) or ck.stats["inferred"] > 0,
        },
        "extractor": {
            "model": model or llm.config()["model"], "prompt_version": prompts()["prompt_version"],
            "usage": usage or {},
        },
    }


