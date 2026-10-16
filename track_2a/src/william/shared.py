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
