"""Minimal OpenAI-compatible client for Apertus (CSCS endpoint by default).

Judges' convention: LLM_NAME / LLM_BASE_URL / LLM_API_KEY environment variables.
"""
from __future__ import annotations

import json
import os
import re
import time

import httpx

DEFAULT_BASE_URL = "https://api.inference.cscs.ch/v1"
DEFAULT_MODEL = "swiss-ai/Apertus-v1.5-70B"


class LLMError(RuntimeError):
    pass


def config() -> dict:
    return {
        "base_url": os.environ.get("LLM_BASE_URL") or DEFAULT_BASE_URL,
        "model": os.environ.get("LLM_NAME") or DEFAULT_MODEL,
        "api_key": os.environ.get("LLM_API_KEY") or "",
    }


def chat(system: str, user: str, *, max_tokens: int = 3000, temperature: float = 0.0,
         model: str | None = None, retries: int = 2) -> tuple[str, dict]:
    cfg = config()
    if not cfg["api_key"]:
        raise LLMError("LLM_API_KEY is not set")
    body = {
        "model": model or cfg["model"],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    last = None
    for attempt in range(retries + 1):
        try:
            r = httpx.post(
                cfg["base_url"].rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {cfg['api_key']}"},
                json=body, timeout=240,
            )
            if r.status_code >= 500 or r.status_code == 429:
                raise LLMError(f"HTTP {r.status_code}: {r.text[:200]}")
            if r.status_code >= 400:
                raise LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
            data = r.json()
            return data["choices"][0]["message"]["content"] or "", data.get("usage") or {}
        except (httpx.HTTPError, LLMError) as e:
            last = e
            if isinstance(e, LLMError) and "HTTP 4" in str(e) and "429" not in str(e):
                raise
            time.sleep(2 * (attempt + 1))
    raise LLMError(str(last))


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json(text: str) -> dict:
    """Parse the first JSON object in a model reply (tolerates code fences / chatter)."""
    t = _FENCE.sub("", text.strip())
    start = t.find("{")
    if start < 0:
        raise LLMError("no JSON object in model output")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(t)):
        c = t[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(t[start:i + 1])
    raise LLMError("unterminated JSON object in model output")


def chat_json(system: str, user: str, *, max_tokens: int, retry_suffix: str, model: str | None = None) -> tuple[dict, dict]:
    """One retry with a stricter instruction when the model's JSON is invalid or cut off."""
    text, usage = chat(system, user, max_tokens=max_tokens, model=model)
    try:
        return parse_json(text), usage
    except (LLMError, json.JSONDecodeError):
        text, usage = chat(system, user + retry_suffix, max_tokens=max_tokens, model=model)
        return parse_json(text), {**usage, "retried": True}
