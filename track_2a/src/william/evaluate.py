"""Evaluation helpers.

  python -m william.evaluate reverify eval/sample_70b.json eval/sample_70b_reverified.json
      re-run provenance verification on the stored raw model output (no LLM calls)
  python -m william.evaluate stats eval/sample_70b.json [data/sample/urls.txt]
      per-level / per-language coverage and verification table (markdown)
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from . import docs
from .extract import assemble

CORE = ["affair_number", "title", "type", "submission_date", "addressed_to", "state"]


def reverify(src: str, dst: str, fixtures: str | None = None) -> None:
    data = json.loads(Path(src).read_text(encoding="utf-8"))
    out, fx = [], []
    for it in data["items"]:
        raw = (it.get("record") or {}).get("extractor", {}).get("raw_model_output")
        if raw is None:
            out.append(it)
            continue
        try:
            d = docs.fetch(it["url"])
        except Exception as e:  # source temporarily unreachable: keep the stored record
            print("skip", it["url"], type(e).__name__, file=sys.stderr)
            out.append(it)
            continue
        old = it["record"]
        rec = assemble(d, raw, usage=old["extractor"].get("usage"), model=old["extractor"].get("model"))
        rec["extractor"]["raw_model_output"] = raw
        out.append({**it, "record": rec, "opd_hints": {k: d.hints.get(k) for k in
                    ("opd_type_harmonized_id", "opd_affair_number", "opd_affair_id", "body_key")}})
        fx.append({"url": it["url"], "raw": raw,
                   "doc": {"url": d.url, "pages": d.pages, "sha256": d.sha256, "contentType": d.content_type,
                           "hints": d.hints, "flags": d.flags},
                   "expected": {k: rec[k] for k in ("language", "body", "affair", "quality")}})
    Path(dst).write_text(json.dumps({"items": out}, ensure_ascii=False, indent=2), encoding="utf-8")
    if fixtures:
        Path(fixtures).write_text(json.dumps(fx, ensure_ascii=False), encoding="utf-8")


def stats(src: str, labels: str | None = None) -> str:
    items = json.loads(Path(src).read_text(encoding="utf-8"))["items"]
    lab = {}
    if labels:
        for line in Path(labels).read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                lvl, lang, url = line.split("\t")[:3]
                lab[url.strip()] = (lvl, lang)
    groups = defaultdict(list)
    for it in items:
        lvl, lang = lab.get(it["url"], ("?", "?"))
        groups[(lvl, lang)].append(it)
        groups[(lvl, "all")].append(it)
        groups[("all", "all")].append(it)
    rows = ["| level | lang | docs | errors | verified values | inferred | rejected | verified share | core-field coverage |",
            "|---|---|---|---|---|---|---|---|---|"]
    for (lvl, lang) in sorted(groups, key=lambda k: (k[0] == "all", k[0], k[1] == "all", k[1])):
        g = groups[(lvl, lang)]
        ok = [x for x in g if "record" in x]
        c = defaultdict(int)
        cov = 0
        for x in ok:
            for k, v in x["record"]["quality"]["value_counts"].items():
                c[k] += v
            a = x["record"]["affair"]
            cov += sum(1 for k in CORE if a.get(k))
        ver = c["extracted"] + c["normalised"] + c["metadata"]
        total = ver + c["inferred"] + c["rejected"]
        rows.append(f"| {lvl} | {lang} | {len(g)} | {len(g) - len(ok)} | {ver} | {c['inferred']} | {c['rejected']} | "
                    f"{ver / max(1, total):.2f} | {cov / max(1, len(ok) * len(CORE)):.2f} |")
    return "\n".join(rows)


def crosscheck(src: str) -> str:
    """Agreement with OpenParlData's own labels (needs the OPD hints, i.e. a fresh `reverify`)."""
    from .shared import vocab
    by_id = {v["opd_type_harmonized_id"]: k for k, v in vocab()["affair_types"].items()}
    rows = ["| doc | OPD type | William type (status) | OPD number | William number |", "|---|---|---|---|---|"]
    agree = n = 0
    for it in json.loads(Path(src).read_text(encoding="utf-8"))["items"]:
        if "record" not in it:
            continue
        h = it.get("opd_hints") or {}
        a = it["record"]["affair"]
        opd_t = by_id.get(h.get("opd_type_harmonized_id"), "—") if h.get("opd_type_harmonized_id") else "—"
        w_t = f"{a['type']['value']} ({a['type']['status']})" if a.get("type") else "—"
        if opd_t != "—" and a.get("type"):
            n += 1
            agree += opd_t == a["type"]["value"]
        w_n = (a.get("affair_number") or {}).get("value", "—")
        rows.append(f"| {it['url'].rsplit('/', 1)[-1]} | {opd_t} | {w_t} | {h.get('opd_affair_number') or '—'} | {w_n} |")
    rows.append(f"\nType agreement where both exist: {agree}/{n}")
    return "\n".join(rows)


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    if cmd == "reverify":
        reverify(*args)
    elif cmd == "stats":
        print(stats(*args))
    elif cmd == "crosscheck":
        print(crosscheck(*args))
