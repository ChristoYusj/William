"""Validator for opd-affair/0.1 records.

  python -m william validate RECORD.json [...] [--source]

A file can hold one record, a list of records, or a William batch ({"items": [{"record": …}, …]}).
Checks, in order:
  1. schema:      the record matches the JSON Schema (docs/opd-affair-0.1.schema.json, via Pydantic);
  2. provenance:  an "extracted" or "normalised" value carries a page and a quote; the page exists; the char span is sane;
  3. vocabulary:  type, level, role, kind, state, outcome and relation use the controlled terms (shared/vocab.json);
                  dates are ISO (YYYY-MM-DD) and vote counts are integers;
  4. with --source (network): the document is fetched again and every quote must still be on its page
                  (and at its char span); a changed document (sha256) is reported as a warning.
Exit code 1 if any record has an error.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from pydantic import ValidationError

from .schema import validate as schema_validate
from .shared import vocab
from .verify import PageIndex, norm_only

VOCAB = {
    "type": "affair_types", "level": "levels", "role": "actor_roles", "kind": "actor_kinds",
    "state": "procedural_states", "outcome": "decision_outcomes", "relation": "relation_types",
}
DATE_FIELDS = {"submission_date", "date"}
INT_FIELDS = {"votes_yes", "votes_no", "votes_abstain"}
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _fields(node, path):
    """Yield (path, field_name, field) for every provenance field {value, status, …} below node."""
    if isinstance(node, dict):
        if "value" in node and "status" in node:
            yield path, re.sub(r"\[\d+\]$", "", path.rsplit(".", 1)[-1]), node
            return
        for k, v in node.items():
            yield from _fields(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _fields(v, f"{path}[{i}]")


def check(record: dict, pages: list[str] | None = None) -> list[dict]:
    """Issues [{level: error|warning, path, message}]; pages = the source document's page texts (for quote checks)."""
    issues = []

    def add(level, path, msg):
        issues.append({"level": level, "path": path, "message": msg})

    try:
        schema_validate(record)
    except ValidationError as e:
        for err in e.errors():
            add("error", ".".join(str(x) for x in err["loc"]), f"schema: {err['msg']}")
        return issues  # the other checks assume the schema's shape

    n_pages = record["source"]["pages"]
    terms = {name: set(vocab()[key]) for name, key in VOCAB.items()}
    index = PageIndex(pages) if pages is not None else None
    for path, name, f in _fields({"body": record["body"], "affair": record["affair"]}, ""):
        value, status, page, quote = f["value"], f["status"], f.get("page"), f.get("quote")
        if status in ("extracted", "normalised"):
            if not quote or page is None:
                add("error", path, f"{status} value without page and quote")
                continue
        if page is not None and not 1 <= page <= n_pages:
            add("error", path, f"page {page} outside the document (1–{n_pages})")
            continue
        cs, ce = f.get("char_start"), f.get("char_end")
        if (cs is None) != (ce is None) or (cs is not None and not 0 <= cs < ce):
            add("error", path, f"bad char span {cs}–{ce}")
        if name in terms and value not in terms[name]:
            add("error", path, f"'{value}' is not a controlled {VOCAB[name]} term")
        if name in DATE_FIELDS and not (isinstance(value, str) and ISO_DATE.match(value)):
            add("error", path, f"date '{value}' is not YYYY-MM-DD")
        if name in INT_FIELDS and not isinstance(value, int):
            add("error", path, f"vote count '{value}' is not an integer")
        if index is not None and quote and page is not None and page <= len(pages):
            if cs is not None and norm_only(pages[page - 1][cs:ce]) == norm_only(quote):
                continue
            hit = index.find(quote, page)
            if hit is None:
                add("error", path, "quote not found in the source document")
            elif hit[0] != page:
                add("error", path, f"quote is on page {hit[0]}, not on page {page}")
            else:
                add("warning", path, "quote found on its page, but not at the recorded char span")
    q = record["quality"]
    if not 0 <= q["verified_share"] <= 1:
        add("error", "quality.verified_share", "verified_share outside 0–1")
    return issues


def check_source(record: dict) -> list[dict]:
    """Fetch the record's source document again and check every quote against it."""
    from . import docs
    try:
        doc = docs.fetch(record["source"]["url"])
    except Exception as e:
        return check(record) + [{"level": "warning", "path": "source.url",
                                 "message": f"source not re-checked: {type(e).__name__}: {e}"}]
    issues = check(record, doc.pages)
    if doc.sha256 != record["source"].get("sha256"):
        issues.append({"level": "warning", "path": "source.sha256", "message": "the document changed since extraction"})
    return issues


def records_in(data) -> list[dict]:
    """Records in a file's JSON: one record, a list of records, or a William batch {"items": […]}."""
    if isinstance(data, dict) and "items" in data:
        data = data["items"]
    if isinstance(data, dict):
        data = [data]
    out = []
    for it in data:
        if isinstance(it, dict) and "schema_version" not in it and ("record" in it or "error" in it):
            it = it.get("record")  # batch item {url, record, summary}; an item that failed has no record
        if isinstance(it, dict):
            out.append(it)
    return out


def main(paths: list[str], source: bool = False) -> int:
    bad = 0
    for p in paths:
        for i, rec in enumerate(records_in(json.loads(Path(p).read_text(encoding="utf-8")))):
            issues = check_source(rec) if source else check(rec)
            errors = sum(x["level"] == "error" for x in issues)
            bad += errors > 0
            label = rec.get("source", {}).get("url", f"record {i}") if isinstance(rec.get("source"), dict) else f"record {i}"
            print(f"{'FAIL' if errors else 'ok  '} {p} | {label} | {errors} error(s), {len(issues) - errors} warning(s)")
            for x in issues:
                print(f"     {x['level']:7} {x['path']}: {x['message']}")
    return 1 if bad else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    sys.exit(main([a for a in args if a != "--source"], source="--source" in args))
