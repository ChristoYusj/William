"""Single source of truth for vocabularies and prompts.

The JSON files live in the extension (src/extension/shared/) so the Firefox
extension and the Python API use exactly the same prompts and vocabularies.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

SHARED_DIR = Path(os.environ.get(
    "WILLIAM_SHARED_DIR",
    Path(__file__).resolve().parent.parent / "extension" / "shared",
))


@lru_cache(maxsize=None)
def vocab() -> dict:
    return json.loads((SHARED_DIR / "vocab.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def prompts() -> dict:
    return json.loads((SHARED_DIR / "prompts.json").read_text(encoding="utf-8"))


SCHEMA_VERSION = "opd-affair/0.1"

_PROMPT_USES = {
    "extract": "Structured extraction: one {v, p, q} (value, page, verbatim quote) per field of opd-affair/0.1. "
               "The {…} placeholders are filled with the controlled vocabularies and the document text.",
    "summarize": "Summary and key points in the document's language, plus 2–5 political topics with a news query each.",
    "translate": "Optional translation of a summary and its key points.",
}


def prompts_markdown() -> str:
    """docs/prompts.md: the Apertus prompts from shared/prompts.json, readable (python -m william prompts)."""
    p = prompts()
    out = [f"# Apertus prompts ({p['prompt_version']})", "",
           "Generated from [`src/extension/shared/prompts.json`](../src/extension/shared/prompts.json) by "
           "`python -m william prompts -o docs/prompts.md`. The extension and the API read that same file. "
           f"All calls run at temperature 0; documents are cut at {p['max_doc_chars']:,} characters.", ""]
    for name, use in _PROMPT_USES.items():
        out += [f"## {name}", "", use, "", "**System**", "", "```text", p[name]["system"].strip(), "```", "",
                "**User template**", "", "```text", p[name]["user_template"].strip(), "```", ""]
    out += ["## JSON retry", "", "Appended to the user message once when the model's JSON is invalid or cut off:", "",
            "```text", p["json_retry_suffix"].strip(), "```", ""]
    return "\n".join(out)
