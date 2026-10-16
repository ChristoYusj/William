"""William HTTP API — the same pipeline as the extension's batch page, without a browser.

POST /v1/extract   {"urls": [...], "summary": true}      -> JSON records (opd-affair/0.1)
POST /v1/report    {"urls": [...]}                       -> application/pdf
POST /v1/summarize {"text": "...", "news": true}         -> summary + news-linked topics
GET  /v1/schema                                          -> JSON Schema of a record
GET  /v1/vocab                                           -> controlled vocabularies
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from . import docs, llm, report
from .extract import extract
from .schema import json_schema
from .shared import SCHEMA_VERSION, vocab
from .summarize import summarize, summarize_pages

app = FastAPI(title="William — OpenParlData affair extractor (Apertus)", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

MAX_URLS = 20


class ExtractRequest(BaseModel):
    urls: list[str] = Field(..., min_length=1, max_length=MAX_URLS)
    summary: bool = True
    news: bool = True
    model: str | None = None


class SummarizeRequest(BaseModel):
    text: str = Field(..., min_length=20)
    news: bool = True
    model: str | None = None


def process(url: str, *, summary: bool, news: bool, model: str | None) -> dict:
    try:
        d = docs.fetch(url)
        rec = extract(d, model=model)
        out = {"url": url, "record": rec}
        if summary:
            out["summary"] = summarize_pages(d.pages, with_news=news, model=model)
        return out
    except Exception as e:  # one bad link must not sink the batch
        return {"url": url, "error": f"{type(e).__name__}: {e}"}


def run_batch(req: ExtractRequest) -> list[dict]:
    with ThreadPoolExecutor(max_workers=4) as ex:
        return list(ex.map(lambda u: process(u, summary=req.summary, news=req.news, model=req.model), req.urls))


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


@app.post("/v1/extract")
def post_extract(req: ExtractRequest):
    items = run_batch(req)
    return {"schema_version": SCHEMA_VERSION, "items": items}


@app.post("/v1/report")
def post_report(req: ExtractRequest):
    items = run_batch(req)
    return Response(report.build(items), media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="william-report.pdf"'})


@app.post("/v1/summarize")
def post_summarize(req: SummarizeRequest):
    try:
        return summarize(req.text, with_news=req.news, model=req.model)
    except llm.LLMError as e:
        raise HTTPException(502, str(e))


@app.get("/", response_class=HTMLResponse)
def index():
    return """<!doctype html><meta charset=utf-8><title>William API</title>
<style>body{font:15px system-ui;max-width:760px;margin:40px auto;padding:0 16px}textarea{width:100%;height:140px}</style>
<h1>William API</h1><p>OpenParlData affair extraction with Apertus. Interactive docs: <a href=/docs>/docs</a>.</p>
<form id=f><textarea id=u placeholder="one link per line (PDF, HTML, api.openparldata.ch/v1/affairs/ID or /docs/ID)"></textarea>
<p><button name=a value=json>JSON</button> <button name=a value=pdf>PDF report</button></p></form><pre id=o></pre>
<script>f.onsubmit=async e=>{e.preventDefault();const urls=u.value.split(/\\s+/).filter(Boolean);
const pdf=e.submitter.value==='pdf';o.textContent='working...';
const r=await fetch(pdf?'/v1/report':'/v1/extract',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({urls})});
if(pdf){const b=await r.blob();const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='william-report.pdf';a.click();o.textContent='done';}
else o.textContent=JSON.stringify(await r.json(),null,1);}</script>"""
