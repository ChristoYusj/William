"""CLI: python -m william {serve|extract|report|schema|validate|prompts} ..."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main(argv=None):
    ap = argparse.ArgumentParser(prog="william")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    s.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    for name in ("extract", "report"):
        p = sub.add_parser(name)
        p.add_argument("urls", nargs="+")
        p.add_argument("-o", "--out")
        p.add_argument("--no-summary", action="store_true")
        p.add_argument("--no-news", action="store_true")
        p.add_argument("--translate", choices=["de", "fr", "it", "rm", "en"],
                       help="also translate the summary with Apertus into this language")
    sc = sub.add_parser("schema")
    sc.add_argument("-o", "--out")
    v = sub.add_parser("validate", help="check opd-affair/0.1 records (schema, provenance, vocabulary)")
    v.add_argument("files", nargs="+", help="a record, a list of records, or a William batch JSON")
    v.add_argument("--source", action="store_true", help="fetch each source again and check every quote on its page")
    pr = sub.add_parser("prompts", help="the Apertus prompts as Markdown")
    pr.add_argument("-o", "--out")
    a = ap.parse_args(argv)

    if a.cmd == "validate":
        from .validate import main as validate_main
        sys.exit(validate_main(a.files, source=a.source))
    if a.cmd == "prompts":
        from .shared import prompts_markdown
        txt = prompts_markdown()
        Path(a.out).write_text(txt, encoding="utf-8") if a.out else sys.stdout.write(txt)
        return

    if a.cmd == "serve":
        import uvicorn
        uvicorn.run("william.api:app", host=a.host, port=a.port)
        return
    if a.cmd == "schema":
        from .schema import json_schema
        txt = json.dumps(json_schema(), indent=2, ensure_ascii=False)
        Path(a.out).write_text(txt, encoding="utf-8") if a.out else print(txt)
        return

    from .api import ExtractRequest, run_batch
    items = run_batch(ExtractRequest(urls=a.urls, summary=not a.no_summary, news=not a.no_news,
                                      translate_to=a.translate))
    if a.cmd == "extract":
        txt = json.dumps({"items": items}, indent=2, ensure_ascii=False)
        Path(a.out).write_text(txt, encoding="utf-8") if a.out else sys.stdout.write(txt + "\n")
    else:
        from .report import build
        Path(a.out or "william-report.pdf").write_bytes(build(items))
        print(a.out or "william-report.pdf")


if __name__ == "__main__":
    main()
