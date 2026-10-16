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


def test_pdf_report_builds_offline():
    from io import BytesIO

    from pypdf import PdfReader

    from william.report import build
    fixtures = json.loads(FIX.read_text(encoding="utf-8"))[:3]
    items = [{"url": fx["url"], "record": {**fx["expected"], "extractor": {"raw_model_output": {}}},
              "summary": {"summary": "Résumé – «test» “quotes” …", "key_points": ["ä ö ü"],
                          "topics": [{"phrase": "x", "articles": [{"title": "t", "source": "s", "url": "https://x.ch"}]}]}}
             for fx in fixtures] + [{"url": "https://bad", "error": "ConnectError"}]
    pdf = build(items)
    assert pdf[:5] == b"%PDF-"
    assert len(PdfReader(BytesIO(pdf)).pages) >= 4


def test_ssrf_guard_blocks_local_and_non_http():
    import pytest

    from william.docs import _check_host
    for bad in ("http://127.0.0.1:8000/health", "http://localhost/x.pdf", "http://169.254.169.254/latest",
                "http://10.0.0.5/a.pdf", "file:///etc/passwd", "ftp://example.org/a.pdf"):
        with pytest.raises(ValueError):
            _check_host(bad)


def test_language_codes_are_normalised():
    from william.summarize import norm_lang
    assert norm_lang("ge", "Der Gemeinderat hat die Motion abgelehnt") == "de"
    assert norm_lang("FR", "") == "fr"
    assert norm_lang("xx", "Il Municipio di Lugano ha risposto che non è possibile per il momento") == "it"
    assert norm_lang(None, "Le Conseil d'Etat est invité à présenter une étude pour les familles") == "fr"


def test_bad_json_is_retried_once(monkeypatch):
    from william import llm
    calls = []

    def fake_chat(system, user, **kw):
        calls.append(user)
        return ('{"a": 1' if len(calls) == 1 else '{"a": 1}'), {"prompt_tokens": 1}
    monkeypatch.setattr(llm, "chat", fake_chat)
    raw, usage = llm.chat_json("s", "u", max_tokens=10, retry_suffix=" RETRY")
    assert raw == {"a": 1} and usage["retried"] and calls[1].endswith(" RETRY")


def test_extension_pages_are_served_with_the_shim(monkeypatch):
    from fastapi.testclient import TestClient
    from william.api import app
    c = TestClient(app)
    for page in ("/ext/batch/batch.html", "/ext/viewer/viewer.html"):
        r = c.get(page)
        assert r.status_code == 200 and '<script src="/web/ext-shim.js"></script>' in r.text
    assert c.get("/ext/lib/pdf.worker.min.mjs").headers["content-type"].startswith("text/javascript")
    # only the ported pages: no background/popup, no way out of the extension folder
    for bad in ("/ext/background.js", "/ext/popup/popup.html", "/ext/../william/llm.py", "/ext/..%2F..%2Fwilliam%2Fllm.py"):
        assert c.get(bad).status_code == 404, bad
    assert c.get("/viewer").status_code == 200


def test_llm_proxy_refuses_non_json_and_cross_origin(monkeypatch):
    from fastapi.testclient import TestClient
    from william.api import app
    monkeypatch.setenv("LLM_API_KEY", "test")
    c = TestClient(app)
    assert c.post("/web/llm", content="{}", headers={"content-type": "text/plain"}).status_code == 415
    assert c.post("/web/llm", json={}, headers={"origin": "https://evil.example"}).status_code == 403



def _fixture_record(i=0):
    fx = json.loads(FIX.read_text(encoding="utf-8"))[i]
    d = fx["doc"]
    doc = Document(url=d["url"], pages=d["pages"], sha256=d["sha256"], content_type=d["contentType"],
                   hints=d["hints"], flags=d["flags"])
    return assemble(doc, fx["raw"]), d["pages"]


def test_validator_accepts_william_records_and_their_quotes():
    from william.validate import check
    fixtures = json.loads(FIX.read_text(encoding="utf-8"))
    for i in range(len(fixtures)):
        rec, pages = _fixture_record(i)
        assert [x for x in check(rec, pages) if x["level"] == "error"] == [], fixtures[i]["url"]


def test_validator_catches_bad_vocabulary_provenance_and_quotes():
    import copy

    from william.validate import check
    rec, pages = _fixture_record()
    bad = copy.deepcopy(rec)
    field = next(f for f in ("title", "affair_number", "addressed_to") if (bad["affair"].get(f) or {}).get("quote"))
    bad["affair"][field]["quote"] = "Ein Zitat, das in diesem Dokument nicht vorkommt"
    bad["affair"][field]["char_start"] = bad["affair"][field]["char_end"] = None
    bad["affair"]["type"] = {"value": "motion_x", "status": "inferred"}
    bad["affair"]["submission_date"] = {"value": "3.3.2025", "status": "extracted", "page": None, "quote": None}
    msgs = {x["path"]: x["message"] for x in check(bad, pages) if x["level"] == "error"}
    assert "not found" in msgs[f"affair.{field}"]
    assert "controlled" in msgs["affair.type"]
    assert "without page and quote" in msgs["affair.submission_date"]
    assert check({"schema_version": "opd-affair/0.1"})[0]["message"].startswith("schema:")


def test_validator_reads_batches_and_skips_failed_items():
    from william.validate import records_in
    rec, _ = _fixture_record()
    assert len(records_in({"items": [{"url": "a", "record": rec}, {"url": "b", "error": "HTTP 404"}]})) == 1
    assert len(records_in(rec)) == 1 and len(records_in([rec, rec])) == 2


def test_prompts_markdown_lists_every_prompt():
    from william.shared import prompts_markdown
    md = prompts_markdown()
    assert all(f"## {k}" in md for k in ("extract", "summarize", "translate", "JSON retry"))
