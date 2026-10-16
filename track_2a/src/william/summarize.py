"""Summary in the document's language + topics linked to Swiss news."""
from __future__ import annotations

import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import httpx

from . import llm
from .docs import UA
from .extract import build_text
from .shared import prompts


def summarize(text: str, *, model: str | None = None, with_news: bool = True,
              translate_to: str | None = None) -> dict:
    p = prompts()["summarize"]
    body, truncated = (text[: prompts()["max_doc_chars"]], len(text) > prompts()["max_doc_chars"])
    data, usage = llm.chat_json(p["system"], p["user_template"].replace("{text}", body), max_tokens=1500,
                                retry_suffix=prompts()["json_retry_suffix"], model=model)
    summary = str(data.get("summary") or "")
    lang = norm_lang(data.get("language"), summary)
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
    if re.search(r"[^\W\d_]{20,}", phrase):  # copied from a space-less PDF text layer
        keep = [i for i, c in enumerate(summary) if c.isalnum()]
        flat = "".join(summary[i] for i in keep).lower()
        q = "".join(_WORD.findall(phrase)).lower()
        for n in range(len(q), 11, -4):
            k2 = flat.find(q[:n])
            if k2 >= 0:
                return [keep[k2], keep[k2 + n - 1] + 1]
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
    data, usage = llm.chat_json(p["system"], user, max_tokens=1600,
                                retry_suffix=prompts()["json_retry_suffix"], model=model)
    kp = data.get("key_points")
    return {"language": target, "source_language": source, "summary": str(data.get("summary") or ""),
            "key_points": [str(k) for k in kp] if isinstance(kp, list) else [], "usage": usage}


def summarize_pages(pages: list[str], **kw) -> dict:
    text, _ = build_text(pages, prompts()["max_doc_chars"])
    return summarize(text, **kw)


LANG_ALIAS = {"ge": "de", "ger": "de", "deu": "de", "fre": "fr", "fra": "fr", "ita": "it", "roh": "rm", "rom": "rm", "rum": "rm", "eng": "en"}
STOP = {"de": ["der", "die", "und", "das", "nicht", "mit", "für", "ist"], "fr": ["le", "la", "les", "des", "et", "est", "pour", "une"],
        "it": ["il", "che", "della", "per", "non", "una", "sono", "del"], "en": ["the", "and", "of", "to", "is", "for", "that", "with"],
        "rm": ["da", "la", "il", "e", "per", "cun", "ina", "ils"]}


def norm_lang(code, text: str) -> str:
    """Same as core.js normLang: fix aliases like 'ge'; else guess from stopwords."""
    c = str(code or "").strip().lower()[:3]
    if c[:2] in ("de", "fr", "it", "rm", "en") and c not in LANG_ALIAS:
        return c[:2]
    if c in LANG_ALIAS:
        return LANG_ALIAS[c]
    words = re.findall(r"[^\W\d_]+", (text or "").lower())
    return max(STOP, key=lambda lang: sum(w in STOP[lang] for w in words))


def rank_news(items: list[dict], query: str, limit: int = 5) -> list[dict]:
    """Same as core.js rankNews: order by shared content-word stems with the query; drop unrelated ones
    when at least two related items exist."""
    want = {_stem(w) for w in _WORD.findall(query) if len(w) >= 4}
    scored = [(len({_stem(t) for t in _WORD.findall(it["title"])} & want), i, it) for i, it in enumerate(items)]
    scored.sort(key=lambda x: (-x[0], x[1]))
    related = [x for x in scored if x[0] > 0]
    return [x[2] for x in (related if len(related) >= 2 else scored)[:limit]]


def news(query: str, lang: str = "de", limit: int = 5) -> list[dict]:
    """Swiss news for a query (Google News RSS, CH edition; Italian restricted to Swiss outlets).
    Falls back to shorter queries when the model's query is too specific."""
    cfg = prompts()["news"]
    if lang not in cfg["supported_lang"]:
        lang = cfg["fallback_lang"]
    sites = (cfg.get("swiss_sites") or {}).get(lang)
    words = [w for w in _WORD.findall(query) if len(w) >= 4]
    queries = list(dict.fromkeys(q for q in (query, " ".join(words[:3]), " ".join(words[:2])) if q.strip()))
    for q in queries:
        full = f"{q} ({' OR '.join('site:' + x for x in sites)})" if sites else q
        url = cfg["google_news_rss"].replace("{query}", quote_plus(full)).replace("{lang}", lang)
        try:
            r = httpx.get(url, headers=UA, timeout=20, follow_redirects=True)
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except Exception:
            continue
        items = []
        for it in list(root.iter("item"))[:20]:
            title = (it.findtext("title") or "").strip()
            source = (it.findtext("source") or "").strip()
            if source and title.endswith(" - " + source):
                title = title[: -len(source) - 3]
            items.append({"title": title, "url": (it.findtext("link") or "").strip(), "source": source,
                          "published": (it.findtext("pubDate") or "").strip(), "query": q})
        items = rank_news(items, query, limit)
        if items:
            return items
    return []
