"""Summary in the document's language + topics linked to Swiss news."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import httpx

from . import llm
from .docs import UA
from .extract import build_text
from .shared import prompts


def summarize(text: str, *, model: str | None = None, with_news: bool = True) -> dict:
    p = prompts()["summarize"]
    body, truncated = (text[: prompts()["max_doc_chars"]], len(text) > prompts()["max_doc_chars"])
    out, usage = llm.chat(p["system"], p["user_template"].replace("{text}", body), max_tokens=1200, model=model)
    data = llm.parse_json(out)
    summary = str(data.get("summary") or "")
    lang = str(data.get("language") or "de")[:2].lower()
    topics = []
    for t in data.get("topics") or []:
        if not isinstance(t, dict) or not t.get("phrase"):
            continue
        phrase = str(t["phrase"])
        topic = {"phrase": phrase, "query": str(t.get("query") or phrase),
                 "in_summary": phrase.lower() in summary.lower()}
        if with_news:
            topic["articles"] = news(topic["query"], lang)
        topics.append(topic)
    return {"language": lang, "summary": summary, "key_points": data.get("key_points") or [],
            "topics": topics, "truncated": truncated, "usage": usage}


def summarize_pages(pages: list[str], **kw) -> dict:
    text, _ = build_text(pages, prompts()["max_doc_chars"])
    return summarize(text, **kw)


def news(query: str, lang: str = "de", limit: int = 5) -> list[dict]:
    """Swiss news articles for a query (Google News RSS, region CH, document language)."""
    cfg = prompts()["news"]
    if lang not in cfg["supported_lang"]:
        lang = cfg["fallback_lang"]
    url = cfg["google_news_rss"].replace("{query}", quote_plus(query)).replace("{lang}", lang)
    try:
        r = httpx.get(url, headers=UA, timeout=20, follow_redirects=True)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception:
        return []
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        source = (it.findtext("source") or "").strip()
        if source and title.endswith(" - " + source):
            title = title[: -len(source) - 3]
        items.append({"title": title, "url": (it.findtext("link") or "").strip(), "source": source,
                      "published": (it.findtext("pubDate") or "").strip()})
        if len(items) >= limit:
            break
    return items


