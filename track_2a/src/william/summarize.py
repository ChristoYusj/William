"""Summary in the document's language + topics linked to Swiss news."""
from __future__ import annotations

import re
import unicodedata
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import httpx

from . import llm
from .docs import UA
from .extract import build_text
from .shared import prompts


# The model sometimes answers "german" / "ge" instead of an ISO 639-1 code
LANG_ALIASES = {"ge": "de", "ger": "de", "deu": "de", "german": "de", "deutsch": "de",
                "fra": "fr", "fre": "fr", "french": "fr", "francais": "fr", "français": "fr",
                "ita": "it", "italian": "it", "italiano": "it",
                "roh": "rm", "romansh": "rm", "rumantsch": "rm", "eng": "en", "english": "en"}


def _lang(raw) -> str:
    raw = str(raw or "de").strip().lower()
    return LANG_ALIASES.get(raw, raw[:2])


def summarize(text: str, *, model: str | None = None, with_news: bool = True,
              translate_to: str | None = None) -> dict:
    p = prompts()["summarize"]
    body, truncated = (text[: prompts()["max_doc_chars"]], len(text) > prompts()["max_doc_chars"])
    out, usage = llm.chat(p["system"], p["user_template"].replace("{text}", body), max_tokens=1200, model=model)
    data = llm.parse_json(out)
    summary = str(data.get("summary") or "")
    lang = _lang(data.get("language"))
    topics = []
    for t in data.get("topics") or []:
        if not isinstance(t, dict) or not t.get("phrase"):
            continue
        phrase = str(t["phrase"])
        span = locate_phrase(summary, phrase)
        topic = {"phrase": phrase, "query": str(t.get("query") or phrase), "span": span, "in_summary": span is not None}
        if with_news:
            topic["articles"] = news(topic["query"], lang)
        topics.append(topic)
    key_points = data.get("key_points") or []
    out = {"language": lang, "summary": summary, "key_points": key_points,
           "topics": topics, "truncated": truncated, "usage": usage}
    if translate_to:
        try:
            out["translation"] = translate(summary, key_points, translate_to, source=lang, model=model)
        except (llm.LLMError, ValueError) as e:  # keep the original summary if the translation fails
            out["translation"] = {"language": translate_to, "error": f"{type(e).__name__}: {e}"}
    return out


def _stem(w: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", w) if not unicodedata.combining(c)).lower()[:5]


_WORD = re.compile(r"[^\W_]+")


def locate_phrase(summary: str, phrase: str) -> list[int] | None:
    """Same algorithm as core.js locatePhrase: exact match, else shortest window covering most content-word stems."""
    k = summary.lower().find(phrase.lower())
    if k >= 0 and phrase:
        return [k, k + len(phrase)]
    want = list(dict.fromkeys(_stem(w) for w in _WORD.findall(phrase) if len(w) >= 4))
    if not want:
        return None
    toks = [(m.start(), m.end(), _stem(m.group())) for m in _WORD.finditer(summary)]
    need = max(2, -(-len(want) // 2)) if len(want) >= 2 else 1
    best = None
    for i in range(len(toks)):
        if toks[i][2] not in want:
            continue
        seen = set()
        for j in range(i, min(len(toks), i + len(want) + 4)):
            if toks[j][2] in want:
                seen.add(toks[j][2])
                if len(seen) >= need:
                    cand = (len(seen), -(j - i), [toks[i][0], toks[j][1]])
                    if best is None or cand[:2] > best[:2]:
                        best = cand
    return best[2] if best else None


def translate_languages() -> dict:
    return prompts()["translate"]["languages"]


def translate(summary: str, key_points: list, target: str, *, source: str = "",
              model: str | None = None) -> dict:
    """Translate a summary and its key points with Apertus (target: de, fr, it, rm or en)."""
    names = translate_languages()
    if target not in names:
        raise ValueError(f"unsupported language {target!r}; use one of {', '.join(names)}")
    if target == source:
        return {"language": target, "source_language": source, "summary": summary,
                "key_points": list(key_points), "note": "already in the target language"}
    p = prompts()["translate"]
    vals = {"source": names.get(source, source or "the original language"), "target_name": names[target],
            "summary": summary, "key_points": json.dumps([str(k) for k in key_points], ensure_ascii=False)}
    user = re.sub(r"\{(source|target_name|summary|key_points)\}", lambda m: vals[m.group(1)], p["user_template"])
    out, usage = llm.chat(p["system"], user, max_tokens=1600, model=model)
    data = llm.parse_json(out)
    kp = data.get("key_points")
    return {"language": target, "source_language": source, "summary": str(data.get("summary") or ""),
            "key_points": [str(k) for k in kp] if isinstance(kp, list) else [], "usage": usage}


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


