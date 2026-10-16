"""William HTTP API — the same pipeline as the extension's batch page, without a browser.

POST /v1/extract   {"urls": [...], "summary": true, "translate_to": "en"} -> JSON records (opd-affair/0.1)
POST /v1/report    {"urls": [...]}                       -> application/pdf
POST /v1/report/items {"items": [...]}                   -> application/pdf from /v1/extract items (no model calls)
POST /v1/summarize {"text": "...", "news": true}         -> summary + news-linked topics
POST /v1/translate {"summary": "...", "target": "rm"}    -> summary translated by Apertus (de, fr, it, rm, en)

translate_to (extract, report, summarize): Apertus also translates the summary and key points into
that language; the original stays in "summary", the translation is added as "summary.translation".
GET  /v1/schema                                          -> JSON Schema of a record
GET  /v1/vocab                                           -> controlled vocabularies
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from . import docs, llm, report, webext
from .extract import extract
from .schema import json_schema
from .shared import SCHEMA_VERSION, vocab
from .summarize import summarize, summarize_pages, translate, translate_languages

app = FastAPI(title="William — OpenParlData affair extractor (Apertus)", version="0.1.0")
app.include_router(webext.router)  # the extension's batch page + PDF viewer as web pages (/ext, /viewer)
# No CORS: the API has no auth and spends the operator's Apertus credits, so browsers on other sites must not call it.

MAX_URLS = 20
WEB_DIR = Path(__file__).resolve().parent / "web"

Lang = Literal["de", "fr", "it", "rm", "en"]
TRANSLATE_DOC = "Also translate the summary with Apertus into this language (implies summary=true)."


class ExtractRequest(BaseModel):
    urls: list[str] = Field(..., min_length=1, max_length=MAX_URLS)
    summary: bool = True
    news: bool = True
    translate_to: Lang | None = Field(None, description=TRANSLATE_DOC)
    model: str | None = None


class ItemsRequest(BaseModel):
    items: list[dict] = Field(..., min_length=1, max_length=MAX_URLS)


class SummarizeRequest(BaseModel):
    text: str = Field(..., min_length=20)
    news: bool = True
    translate_to: Lang | None = Field(None, description=TRANSLATE_DOC)
    model: str | None = None


class TranslateRequest(BaseModel):
    summary: str = Field(..., min_length=1)
    key_points: list[str] = []
    target: Lang
    source: str | None = Field(None, description="ISO 639-1 code of the summary's language, if known")
    model: str | None = None


def process(url: str, *, summary: bool, news: bool, model: str | None, translate_to: str | None = None) -> dict:
    try:
        d = docs.fetch(url)
        rec = extract(d, model=model)
        out = {"url": url, "record": rec}
        if summary or translate_to:
            out["summary"] = summarize_pages(d.pages, with_news=news, model=model, translate_to=translate_to)
        return out
    except Exception as e:  # one bad link must not sink the batch
        return {"url": url, "error": f"{type(e).__name__}: {e}"}


def run_batch(req: ExtractRequest) -> list[dict]:
    with ThreadPoolExecutor(max_workers=4) as ex:
        return list(ex.map(lambda u: process(u, summary=req.summary, news=req.news, model=req.model,
                                             translate_to=req.translate_to), req.urls))


@app.get("/health")
def health():
    cfg = llm.config()
    return {"ok": True, "schema_version": SCHEMA_VERSION, "model": cfg["model"],
            "base_url": cfg["base_url"], "api_key_set": bool(cfg["api_key"])}


@app.get("/v1/schema")
def schema():
    return json_schema()


@app.get("/v1/vocab")
def get_vocab():
    return vocab()


@app.post("/v1/validate")
def post_validate(body: Any = Body(...), source: bool = False):
    """Validate opd-affair/0.1 records (one, a list, or a William batch). ?source=true re-checks quotes on the source."""
    from .validate import check, check_source, records_in
    recs = records_in(body)
    if not 1 <= len(recs) <= MAX_URLS:
        raise HTTPException(400, f"send 1 to {MAX_URLS} records")
    results = []
    for rec in recs:
        issues = check_source(rec) if source else check(rec)
        results.append({"url": (rec.get("source") or {}).get("url") if isinstance(rec.get("source"), dict) else None,
                        "valid": not any(i["level"] == "error" for i in issues), "issues": issues})
    return {"schema_version": SCHEMA_VERSION, "valid": all(r["valid"] for r in results), "results": results}


@app.post("/v1/extract")
def post_extract(req: ExtractRequest):
    items = run_batch(req)
    return {"schema_version": SCHEMA_VERSION, "items": items}


@app.post("/v1/report")
def post_report(req: ExtractRequest):
    items = run_batch(req)
    return Response(report.build(items), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="william-report.pdf"'})


@app.post("/v1/report/items")
def post_report_items(req: ItemsRequest):
    """PDF from items the web page already got from /v1/extract, so Apertus isn't called twice."""
    return Response(report.build(req.items), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="william-report.pdf"'})


@app.post("/v1/summarize")
def post_summarize(req: SummarizeRequest):
    try:
        return summarize(req.text, with_news=req.news, model=req.model, translate_to=req.translate_to)
    except llm.LLMError as e:
        raise HTTPException(502, str(e))


@app.post("/v1/translate")
def post_translate(req: TranslateRequest):
    try:
        return translate(req.summary, req.key_points, req.target, source=req.source or "", model=req.model)
    except llm.LLMError as e:
        raise HTTPException(502, str(e))


@app.get("/v1/languages")
def get_languages():
    """Target languages for translate_to / /v1/translate."""
    return translate_languages()


@app.get("/", response_class=HTMLResponse)
def index():
    return (WEB_DIR / "index.html").read_text(encoding="utf-8")
