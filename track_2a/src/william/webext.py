"""The Firefox extension's batch page and PDF viewer as plain web pages, served by the API.

GET  /ext/{path}          the extension's files; HTML pages get web/ext-shim.js injected, which supplies
                          the browser.* APIs the pages use and routes their cross-origin fetches here
GET  /viewer?file=URL     opens a PDF (or an OpenParlData /v1/docs|affairs link) in the viewer; no file -> a form
GET  /web/fetch?url=URL   fetch proxy for documents, OpenParlData and Google News (same SSRF guard and size cap
                          as /v1/extract), because a web page can't read other origins the way the extension can
POST /web/llm             Apertus proxy: the server's LLM_* key and model are used, the browser never sees the key
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from . import docs, llm
from .shared import SHARED_DIR

router = APIRouter()

EXT_DIR = SHARED_DIR.parent.resolve()
SHIM = Path(__file__).resolve().parent / "web" / "ext-shim.js"
# only the pages that work without the extension runtime (no popup, background page or content script)
EXT_DIRS = ("batch", "viewer", "shared", "lib", "icons")
MIME = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png"}
MAX_TOKENS = 8000


@router.get("/ext/{path:path}", include_in_schema=False)
def ext_file(path: str):
    f = (EXT_DIR / path).resolve()
    if not f.is_relative_to(EXT_DIR) or not f.is_file() or path.split("/")[0] not in EXT_DIRS:
        raise HTTPException(404)
    if f.suffix == ".html":
        page = f.read_text(encoding="utf-8")
        # a classic script runs before the pages' module scripts, so browser.* exists when they import engine.js
        page = page.replace("</head>", '<script src="/web/ext-shim.js"></script>\n</head>', 1)
        return HTMLResponse(page)
    return Response(f.read_bytes(), media_type=MIME.get(f.suffix, "application/octet-stream"))


@router.get("/web/ext-shim.js", include_in_schema=False)
def ext_shim():
    return Response(SHIM.read_bytes(), media_type=MIME[".js"])


@router.get("/web/fetch", include_in_schema=False)
def web_fetch(url: str):
    try:
        r = docs._get(url)
    except httpx.HTTPStatusError as e:
        return Response(e.response.text[:2000], status_code=e.response.status_code, media_type="text/plain")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except httpx.HTTPError as e:
        raise HTTPException(502, f"{type(e).__name__}: {e}")
    return Response(r.content, media_type=r.headers.get("content-type", "application/octet-stream"),
                    headers={"X-Final-URL": str(r.url)})


@router.post("/web/llm", include_in_schema=False)
async def web_llm(request: Request):
    # The key is the operator's: only same-origin JSON requests (a cross-site form can't send JSON, and
    # without CORS a cross-site fetch is refused at preflight; the Origin check closes the rest).
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "JSON only")
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "cross-origin request refused")
    cfg = llm.config()
    if not cfg["api_key"]:
        raise HTTPException(503, "LLM_API_KEY is not set on the server")
    body = await request.json()
    payload = {"model": cfg["model"], "messages": body.get("messages") or [],
               "temperature": body.get("temperature", 0),
               "max_tokens": min(int(body.get("max_tokens") or 3000), MAX_TOKENS)}
    async with httpx.AsyncClient(timeout=240) as c:
        r = await c.post(cfg["base_url"].rstrip("/") + "/chat/completions", json=payload,
                         headers={"Authorization": f"Bearer {cfg['api_key']}"})
    return Response(r.content, status_code=r.status_code, media_type="application/json")


def _resolve_opd(url: str) -> str:
    """api.openparldata.ch/v1/docs|affairs/ID -> the document's file URL (the viewer needs the PDF itself)."""
    m = re.search(r"api\.openparldata\.ch/v1/(docs|affairs)/(\d+)", url)
    if not m:
        return url
    kind, oid = m.groups()
    if kind == "affairs":
        pdfs = [d for d in docs._opd_json(f"{docs.OPD_API}/affairs/{oid}/docs").get("data", [])
                if (d.get("format") or "").endswith("pdf")]
        if not pdfs:
            raise ValueError(f"OpenParlData affair {oid} has no PDF document")
        d = pdfs[0]
    else:
        d = docs._opd_json(f"{docs.OPD_API}/docs/{oid}")
        if isinstance(d.get("data"), dict):
            d = d["data"]
    return d.get("url_oparl") or d.get("url") or url


@router.get("/viewer", include_in_schema=False)
def viewer(file: str = ""):
    err = ""
    if file.strip():
        try:
            return RedirectResponse("/ext/viewer/viewer.html?file=" + quote(_resolve_opd(file.strip()), safe=""))
        except (ValueError, httpx.HTTPError) as e:
            err = f'<p class="err">{html.escape(str(e))}</p>'
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>William viewer</title>
<link rel="stylesheet" href="/ext/shared/ui.css">
<style>main{{max-width:720px;margin:0 auto;padding:24px 16px}}form{{display:flex;gap:8px;flex-wrap:wrap}}
input{{flex:1;min-width:240px;font:inherit;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg)}}</style>
</head><body><header class="bar"><a class="brand" href="/" style="text-decoration:none">William</a>
<span class="muted">PDF viewer</span><span class="grow"></span><a class="btn ghost" href="/ext/batch/batch.html">Batch page</a></header>
<main><p class="muted small">Open a parliamentary PDF to read it, summarise it or a selection, and extract the affair with page-level evidence.
A direct PDF link, <code>files.openparldata.ch/doc/…</code>, or <code>api.openparldata.ch/v1/docs/ID</code> / <code>/v1/affairs/ID</code>.</p>
<form method="get" action="/viewer"><input name="file" value="{html.escape(file)}" placeholder="https://api.openparldata.ch/v1/docs/928926" required autofocus>
<button class="btn primary">Open</button></form>{err}</main></body></html>""")
