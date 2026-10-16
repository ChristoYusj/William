"""Fetch a link (PDF, HTML page, or OpenParlData API/file link) and return page texts.

Supported links:
  * any direct PDF link (born-digital; scanned PDFs are flagged, not OCR'd)
  * any HTML page (one "page")
  * https://api.openparldata.ch/v1/docs/{id}      -> the document's PDF + body metadata
  * https://api.openparldata.ch/v1/affairs/{id}   -> the affair's first PDF doc + metadata
  * https://files.openparldata.ch/doc/{BODY}/{hash}
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
from pypdf import PdfReader

UA = {"User-Agent": "William/0.1 (Hack Apertus OpenParlData; +https://hackapertus.ch)"}
OPD_API = "https://api.openparldata.ch/v1"

CANTONS = {"AG", "AI", "AR", "BE", "BL", "BS", "FR", "GE", "GL", "GR", "JU", "LU", "NE", "NW",
           "OW", "SG", "SH", "SO", "SZ", "TG", "TI", "UR", "VD", "VS", "ZG", "ZH"}
# Domains that identify a parliament level without asking the model.
FEDERAL_DOMAINS = ("parlament.ch", "admin.ch", "fedlex.")


@dataclass
class Document:
    url: str
    pages: list[str]
    sha256: str
    content_type: str
    hints: dict = field(default_factory=dict)   # metadata we know without the model
    flags: list[str] = field(default_factory=list)


def level_from_body_key(body_key: str | None) -> str | None:
    if not body_key:
        return None
    if body_key == "CHE":
        return "federal"
    if body_key in CANTONS:
        return "cantonal"
    if body_key.isdigit():
        return "communal"
    return None   # e.g. LIE (Liechtenstein) is outside the Swiss three-level model


def level_from_domain(url: str) -> tuple[str | None, str | None]:
    host = urlparse(url).hostname or ""
    if any(d in host for d in FEDERAL_DOMAINS):
        return "federal", "CHE"
    m = re.match(r"^(?:.*\.)?([a-z]{2})\.ch$", host)
    if m and m.group(1).upper() in CANTONS:
        return "cantonal", m.group(1).upper()
    m = re.search(r"\b(?:gr|grandconseil|grossrat|kantonsrat|landrat)\.([a-z]{2})\.ch$", host)
    if m and m.group(1).upper() in CANTONS:
        return "cantonal", m.group(1).upper()
    return None, None


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "nav", "header", "footer", "svg"}

    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "tr", "section"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    text = "".join(p.out)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def pdf_pages(data: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(data))
    return [(pg.extract_text() or "") for pg in reader.pages]


def _get(url: str, attempts: int = 3) -> httpx.Response:
    for i in range(attempts):
        try:
            r = httpx.get(url, headers=UA, timeout=60, follow_redirects=True)
            r.raise_for_status()
            return r
        except (httpx.TimeoutException, httpx.TransportError):
            if i == attempts - 1:
                raise
    raise RuntimeError("unreachable")


def _opd_json(url: str) -> dict:
    return _get(url).json()


def fetch(url: str) -> Document:
    url = url.strip()
    hints: dict = {}
    flags: list[str] = []
    host = urlparse(url).hostname or ""

    if host == "api.openparldata.ch":
        m = re.search(r"/v1/(docs|affairs)/(\d+)", url)
        if not m:
            raise ValueError("unsupported OpenParlData API link (use /v1/docs/{id} or /v1/affairs/{id})")
        kind, oid = m.groups()
        if kind == "affairs":
            aff = _opd_json(f"{OPD_API}/affairs/{oid}")
            hints.update(opd_affair_id=int(oid), body_key=aff.get("body_key"),
                         opd_type_harmonized_id=aff.get("type_harmonized_id"),
                         affair_number=aff.get("number"))
            docs = _opd_json(f"{OPD_API}/affairs/{oid}/docs").get("data", [])
            pdfs = [d for d in docs if (d.get("format") or "").endswith("pdf")]
            if not pdfs:
                raise ValueError(f"OpenParlData affair {oid} has no PDF document")
            doc = pdfs[0]
            if len(pdfs) > 1:
                flags.append(f"affair has {len(pdfs)} PDFs; only the first was processed")
        else:
            doc = _opd_json(f"{OPD_API}/docs/{oid}")
            if "data" in doc and isinstance(doc["data"], dict):
                doc = doc["data"]
        hints.setdefault("body_key", doc.get("body_key"))
        hints["opd_doc_id"] = doc.get("id")
        if doc.get("affair_id") and "opd_affair_id" not in hints:
            hints["opd_affair_id"] = doc["affair_id"]
            try:  # OPD's own labels, used as a cross-check (not copied into the record)
                aff = _opd_json(f"{OPD_API}/affairs/{doc['affair_id']}")
                aff = aff.get("data", aff) if isinstance(aff.get("data"), dict) else aff
                hints.update(opd_type_harmonized_id=aff.get("type_harmonized_id"),
                             opd_affair_number=aff.get("number"))
            except Exception:
                pass
        if doc.get("language"):
            hints["language"] = doc["language"]
        url = doc.get("url_oparl") or doc.get("url")
    elif host == "files.openparldata.ch":
        m = re.search(r"/doc/([A-Za-z0-9]+)/", url)
        if m:
            hints["body_key"] = m.group(1)

    r = _get(url)
    data = r.content
    ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
    if data[:5] == b"%PDF-" or ctype == "application/pdf":
        pages = pdf_pages(data)
        ctype = "application/pdf"
        chars = sum(len(p.strip()) for p in pages)
        if pages and chars / len(pages) < 80:
            flags.append("little or no text layer (scanned PDF?) - OCR needed, extraction unreliable")
    else:
        pages = [html_to_text(r.text)]
        if hints.get("opd_doc_id") or url.lower().endswith(".pdf"):
            flags.append("source is listed as a PDF but the file is not a PDF (e.g. a Fedlex JavaScript wall) - "
                         "nothing reliable to extract")
        ctype = ctype or "text/html"

    if "body_key" not in hints or not hints.get("body_key"):
        lvl, key = level_from_domain(str(r.url))
        if lvl:
            hints["level_from_domain"] = lvl
            hints["body_key"] = key
    if hints.get("body_key"):
        lvl = level_from_body_key(hints["body_key"])
        if lvl:
            hints["level"] = lvl
    return Document(url=str(r.url), pages=pages, sha256=hashlib.sha256(data).hexdigest(),
                    content_type=ctype, hints=hints, flags=flags)


def from_text(text: str, url: str = "text://selection") -> Document:
    return Document(url=url, pages=[text], sha256=hashlib.sha256(text.encode()).hexdigest(),
                    content_type="text/plain")
