"""Offline tests (no network, no LLM): verifier, schema, and re-assembly of stored Apertus outputs."""
import json
from pathlib import Path

from william.docs import Document, level_from_body_key
from william.extract import assemble
from william.schema import validate
from william.verify import PageIndex, date_supported

FIX = Path(__file__).parent / "fixtures" / "sample_v02.json"


def test_quote_found_despite_typography_and_hyphenation():
    idx = PageIndex(["Die Motion «Schutz der Verkehrs-\nwege» wurde am 3. März 2025 eingereicht."])
    assert idx.find('Schutz der Verkehrswege', 1)
    assert idx.find('"Schutz der Verkehrswege"', None)
    assert idx.find("am 3. März 2025", 1)
    assert idx.find("am 4. März 2025", 1) is None


def test_space_free_pdf_text():
    idx = PageIndex(["RéponsedelaMunicipalitéàl’interpellationdeMmePaulineBlanc"])
    hit = idx.find("Réponse de la Municipalité à l'interpellation", 1)
    assert hit and hit[0] == 1


def test_dates_need_day_month_year_in_quote():
    assert date_supported("2025-03-03", "am 3. März 2025")
    assert date_supported("2019-07-23", "Bellinzona, 23 luglio 2019")
    assert date_supported("2025-11-18", "déposée le 18.11.2025")
    assert not date_supported("2025-11-19", "déposée le 18 novembre 2025")
    assert not date_supported("2024-11-18", "déposée le 18 novembre 2025")


def test_levels_from_opd_body_key():
    assert level_from_body_key("CHE") == "federal"
    assert level_from_body_key("GE") == "cantonal"
    assert level_from_body_key("5192") == "communal"
    assert level_from_body_key("LIE") is None


def test_invented_quote_is_rejected_and_vocab_inferred():
    doc = Document(url="x", pages=["Interpellanza presentata da Demis Fumasoli al Municipio di Lugano"],
                   sha256="0", content_type="text/plain", hints={"body_key": "5192", "level": "communal"})
    raw = {
        "state": {"v": "submitted", "p": 1, "q": "Interpellanza presentata e in attesa di risposta"},  # invented quote
        "addressed_to": {"v": "Municipio di Lugano", "p": 1, "q": "al Municipio di Lugano"},
        "submission_date": {"v": "2026-10-05", "p": 1, "q": "Interpellanza presentata"},  # no date in quote
        "actors": [{"name": {"v": "Demis Fumasoli", "p": 1, "q": "Demis Fumasoli"}, "role": {"v": "submitter"}}],
        "title": {"v": "Una mozione inventata", "p": 1, "q": "Una mozione inventata"},
    }
    rec = assemble(doc, raw)
    a = rec["affair"]
    assert a["state"]["status"] == "inferred" and a["state"]["quote"] is None   # judgement kept, flagged
    assert a["addressed_to"]["status"] == "extracted"
    assert a["submission_date"] is None                                       # unsupported date removed
    assert a["title"] is None                                                 # invented title removed
    assert a["actors"][0]["role"]["status"] == "inferred"
    assert rec["body"]["level"]["status"] == "metadata"
    assert rec["quality"]["value_counts"]["rejected"] == 2
    validate(rec)


def test_stored_apertus_outputs_reassemble_identically():
    fixtures = json.loads(FIX.read_text(encoding="utf-8"))
    assert len(fixtures) >= 10
    for fx in fixtures:
        d = fx["doc"]
        doc = Document(url=d["url"], pages=d["pages"], sha256=d["sha256"], content_type=d["contentType"],
                       hints=d["hints"], flags=d["flags"])
        rec = assemble(doc, fx["raw"])
        validate(rec)
        for key in ("language", "body", "affair"):
            assert rec[key] == fx["expected"][key], (fx["url"], key)
        # every kept value with a page must point at its quote in the page text
        for f in _fields(rec["affair"]):
            if f.get("page") and f.get("char_start") is not None:
                assert d["pages"][f["page"] - 1][f["char_start"]:f["char_end"]] == f["quote"]


def _fields(o):
    if isinstance(o, dict):
        if "status" in o and "value" in o:
            yield o
        for v in o.values():
            yield from _fields(v)
    elif isinstance(o, list):
        for v in o:
            yield from _fields(v)
