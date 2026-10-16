"""Pydantic models for an opd-affair/0.1 record (validation + JSON Schema export)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from .shared import SCHEMA_VERSION

Status = Literal["extracted", "normalised", "inferred", "metadata"]


class Field_(BaseModel):
    """A value with provenance. page/quote/char_* point into the source page text."""
    model_config = ConfigDict(extra="allow")
    value: object
    status: Status
    page: Optional[int] = None
    quote: Optional[str] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    source: Optional[str] = None


F = Optional[Field_]


class Actor(BaseModel):
    name: Field_
    role: F = None
    kind: F = None
    party_or_group: F = None


class Question(BaseModel):
    number: F = None
    question: Field_
    answer: F = None


class HistoryEvent(BaseModel):
    date: F = None
    state: F = None
    description: F = None


class Decision(BaseModel):
    date: F = None
    body: F = None
    outcome: Field_
    votes_yes: F = None
    votes_no: F = None
    votes_abstain: F = None


class Related(BaseModel):
    reference: Field_
    relation: F = None


class Affair(BaseModel):
    affair_number: F = None
    title: F = None
    type: F = None
    type_original: F = None
    submission_date: F = None
    actors: list[Actor] = []
    addressed_to: F = None
    requests: list[Field_] = []
    questions: list[Question] = []
    procedural_history: list[HistoryEvent] = []
    state: F = None
    decisions: list[Decision] = []
    related_affairs: list[Related] = []
    keywords: list[str] = []


class Body(BaseModel):
    level: F = None
    body_key: Optional[str] = None
    parliament: F = None
    opd_body_type: Optional[Literal["country", "canton", "municipality"]] = None


class Source(BaseModel):
    url: str
    sha256: str
    content_type: str
    pages: int
    opd_doc_id: Optional[int] = None
    opd_affair_id: Optional[int] = None
    retrieved_at: str


class Quality(BaseModel):
    value_counts: dict[str, int]
    verified_share: float
    rejected_values: list[dict]
    flags: list[str]
    needs_review: bool


class Record(BaseModel):
    schema_version: Literal["opd-affair/0.1"] = SCHEMA_VERSION
    source: Source
    language: Optional[str] = None
    body: Body
    affair: Affair
    quality: Quality
    extractor: dict


def json_schema() -> dict:
    s = Record.model_json_schema()
    s["$id"] = "https://github.com/ChristoYusj/william/schema/opd-affair-0.1.json"
    s["title"] = "OpenParlData affair record (opd-affair/0.1)"
    return s


def validate(record: dict) -> Record:
    return Record.model_validate(record)
