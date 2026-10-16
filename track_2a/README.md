<p align="center"><img src="src/extension/icons/logo.png" alt="William logo" width="140"></p>

# William — Swiss parliamentary affairs → one common structure (Apertus)

**Track 2A · OpenParlData challenge** — extracting parliamentary affairs (federal, cantonal, communal)
from PDFs into one common, provenance-carrying JSON structure with Apertus.

### Why "William"?

William is named after **William Tell**, the legendary hero of Swiss freedom. Part of that freedom is the **freedom of
information**, and that is William's goal: a parliamentary document should be understandable by any citizen, not only
by the people who wrote it. So William does more than turn the document into a schema. It also **links each
parliamentary affair to Swiss news articles about it**, which report on it and explain it: the motion, the question,
the vote or the decision, and what the press made of it. The reader gets the official text, a summary in its own
language, the structured record and the public debate around it, side by side.

William comes in three parts. All three share the same prompts, vocabularies and verifier, which live in one place:
[`src/extension/shared/`](src/extension/shared).

| Part | What it does |
|---|---|
| **Firefox extension** ([`src/extension`](src/extension)) | Opens parliamentary PDFs in its own viewer. Summarises the **document or the selected text in the document's language** (DE/FR/IT/RM). Highlights the political topics in the summary; each highlight links to **Swiss news articles** on the subject (Google News, CH edition). Extracts the affair into the common JSON with page-level evidence. Context menu: summarise any selection or page on any website. |
| **Batch page** (inside the extension, `batch/batch.html`) | Paste many links (PDFs, HTML pages, `api.openparldata.ch/v1/affairs/ID`, `/v1/docs/ID`, `files.openparldata.ch/doc/…`). For each link it produces a summary plus one `opd-affair/0.1` record. Download everything as **JSON** or as a **PDF report**, generated in the browser. |
| **HTTP API + web page** ([`src/william`](src/william)) | The same pipeline without a browser: web page at `/`, `POST /v1/extract`, `POST /v1/report` (PDF), `POST /v1/report/items`, `POST /v1/summarize`, `POST /v1/translate` (summary → DE/FR/IT/RM/EN with Apertus; also `translate_to` on extract/summarize), `GET /v1/schema`, `GET /v1/vocab`, `POST /v1/validate`; plus a CLI. |

## Run it (judges)

```bash
export LLM_API_KEY=...                                  # CSCS / Apertus key
export LLM_BASE_URL=https://api.inference.cscs.ch/v1    # default
export LLM_NAME=swiss-ai/Apertus-v1.5-70B               # default
make run          # API on http://localhost:8000  (web form at /, Swagger at /docs)
make test         # offline tests (verifier, schema, re-verification of stored Apertus outputs)
make eval         # evaluation table from the stored run (no API calls)
make sample       # live: re-extract the sample documents with Apertus
make validate     # validate the sample records (schema, provenance, vocabulary; no API calls)
```

Extension end-to-end test (headless Firefox + Selenium, live Apertus; last run 19/19, see `eval/e2e/`):

```bash
pip install selenium==4.35.0 && LLM_API_KEY=... python tests/e2e_firefox.py
```

API example:

```bash
curl -s localhost:8000/v1/extract -H 'content-type: application/json' \
  -d '{"urls":["https://api.openparldata.ch/v1/docs/928926"],"summary":true}'
curl -s localhost:8000/v1/report -H 'content-type: application/json' \
  -d '{"urls":["https://api.openparldata.ch/v1/docs/928926","https://api.openparldata.ch/v1/docs/448120"]}' -o report.pdf
```

## Apertus prompts

All prompts are in one file, [`src/extension/shared/prompts.json`](src/extension/shared/prompts.json)
(`william-prompts/0.2`), read by both the extension and the API. A readable copy is in
[`docs/prompts.md`](docs/prompts.md) (`python -m william prompts -o docs/prompts.md`).

| Prompt | Used for |
|---|---|
| `extract` | One `{v, p, q}` (value, page, verbatim quote) per field of `opd-affair/0.1`; the controlled vocabularies are filled in from [`vocab.json`](src/extension/shared/vocab.json) |
| `summarize` | Summary and key points in the document's language, plus 2–5 political topics with a news query each |
| `translate` | Optional translation of the summary (DE / FR / IT / RM / EN) |
| `json_retry_suffix` | One stricter retry when the model's JSON is invalid or cut off |

All calls run at temperature 0 with `swiss-ai/Apertus-v1.5-70B` (8B selectable); no other model is used.

## Validator

Two layers. The **verifier** ([`src/william/verify.py`](src/william/verify.py),
[`src/extension/shared/core.js`](src/extension/shared/core.js)) runs during extraction: a value whose quote is not on
its page is removed. The **validator** ([`src/william/validate.py`](src/william/validate.py)) checks any finished
record, including ones produced elsewhere:

1. **schema:** the record matches [`docs/opd-affair-0.1.schema.json`](docs/opd-affair-0.1.schema.json) (`GET /v1/schema`);
2. **provenance:** every `extracted` / `normalised` value has a page and a quote, the page exists, the char span is sane;
3. **vocabulary:** type, level, role, kind, state, outcome and relation are controlled terms; dates are `YYYY-MM-DD`;
   vote counts are integers;
4. **`--source`** (network): the document is fetched again and every quote must still be on its page; a changed
   document (sha256) is a warning.

```bash
python -m william validate data/sample/records/*.json            # exit code 1 on any error
python -m william validate --source data/sample/records/communal-it-928926.json
curl -s localhost:8000/v1/validate -H 'content-type: application/json' -d @data/sample/records/cantonal-it-109935.json
```

```
ok   data/sample/records/communal-it-928926.json | https://files.openparldata.ch/doc/5192/592b1e53… | 0 error(s), 0 warning(s)
FAIL edited.json | https://files.openparldata.ch/doc/5192/592b1e53… | 2 error(s), 0 warning(s)
     error   affair.title: quote not found in the source document
     error   affair.type: 'motion_x' is not a controlled affair_types term
```

`python -m william.evaluate reverify|stats|crosscheck` re-checks the stored raw model outputs offline.

## Samples

* **Breadth run:** 32 more documents from 15 more parliaments in [`data/sample/urls_breadth.txt`](data/sample/urls_breadth.txt),
  with results in [`eval/breadth_70b.json`](eval/breadth_70b.json) (29/32 extracted; table in the technical report §5g).
* **Human check** (blind, 50 values): open [`eval/human_check/human_check.html`](eval/human_check/human_check.html),
  mark each value, download the JSON, then `python eval/human_check/score.py human_check_*.json`.
* **Standards crosswalk** (OpenParlData API, Akoma Ntoso, Popolo, W3C Web Annotation): [`docs/schema.md`](docs/schema.md).

14 OpenParlData documents, federal / cantonal / communal × DE / FR / IT, all 14 processed. Inputs:
[`data/sample/urls.txt`](data/sample/urls.txt). One validated record per document is in
[`data/sample/records/`](data/sample/records); the full batch (records + raw Apertus output) is
[`eval/sample_70b_reverified.json`](eval/sample_70b_reverified.json). Evaluation tables: [`technical_report.md`](technical_report.md) §5.

| Level | Lang | Parliament | Record | Type | Number | Title (verified) | Verified share |
|---|---|---|---|---|---|---|---|
| federal | de | CHE | [federal-de-316738](data/sample/records/federal-de-316738.json) | motion | 23.4448 | Kurzbericht des SEM … im Zusammenhang mit Motion 23.4448 Chiesa «Schutz der Landesgrenzen» | 0.68 |
| federal | de | CHE | [federal-de-316740](data/sample/records/federal-de-316740.json) | consultation | 22.423 | Für eine unabhängige Presse sind die Beträge zur indirekten Förderung anzupassen | 0.75 |
| federal | fr | CHE | [federal-fr-38803](data/sample/records/federal-fr-38803.json) | report | 15.075 | Constitutionnalité de la version du projet de loi du Conseil des Etats … publicité et marketing | 0.46 |
| federal | it | CHE | [federal-it-485241](data/sample/records/federal-it-485241.json) | – | – | – (OPD stores a Fedlex "enable JavaScript" page, not the PDF: flagged) | 0.50 |
| cantonal | de | ZH | [cantonal-de-901098](data/sample/records/cantonal-de-901098.json) | election | 31/2026 | Wahl Mitglied Obergericht (100%) für den Rest der Amtsdauer 2025-2031 | 0.80 |
| cantonal | fr | GE | [cantonal-fr-448120](data/sample/records/cantonal-fr-448120.json) | resolution | R 687 | Proposition de résolution … soustraire les jeunes adultes de la compensation des risques LAMal | 0.56 |
| cantonal | fr | GE | [cantonal-fr-444907](data/sample/records/cantonal-fr-444907.json) | parliamentary_initiative | PL 9957 | Projet de loi modifiant la loi sur les cimetières (K 1 65) | 0.47 |
| cantonal | it | TI | [cantonal-it-109935](data/sample/records/cantonal-it-109935.json) | interpellation | 126.19 | Interpellazione sul seguito della mozione "Non danneggiamo il clima con i soldi pubblici" … | 0.68 |
| communal | de | Bern (351) | [communal-de-894215](data/sample/records/communal-de-894215.json) | motion | 2026.PRD.0014 | Riedbachstrasse 8, 9, 10 und 12 (Zentrum Bethlehem): Überbauungsordnung … | 0.38 |
| communal | de | Zürich (261) | [communal-de-929515](data/sample/records/communal-de-929515.json) | approval_decision (inferred) | 2026/167 | – (committee motion on the Zähringer- und Häringstrasse road project) | 0.20 |
| communal | fr | Lausanne (5586) | [communal-fr-650091](data/sample/records/communal-fr-650091.json) | interpellation | – | – (text layer without spaces) | 0.24 |
| communal | fr | Lausanne (5586) | [communal-fr-555996](data/sample/records/communal-fr-555996.json) | postulate | – | Un rabais sur les abonnements Mobilis TL pour les bénéficiaires de l'assurance invalidité | 0.61 |
| communal | it | Lugano (5192) | [communal-it-928925](data/sample/records/communal-it-928925.json) | interpellation | – | Legge sulle Commesse Pubbliche, ce la facciamo …? | 0.63 |
| communal | it | Lugano (5192) | [communal-it-928926](data/sample/records/communal-it-928926.json) | question | 1654 | Legge sulle Commesse Pubbliche, ce la facciamo...? | 0.68 |

**Extension end-to-end run** (headless Firefox, 19/19): screenshots and results in [`eval/e2e/`](eval/e2e). In that
run, the Lugano question 1654 above was linked to the Swiss article *“A Lugano ci sono volute 75 ore per rispondere a
un'interrogazione”*, which is about that same question.

Excerpt of a real record: a Lugano reply to a written question (communal, Italian). Ticino's *interrogazione* is
mapped to `question` by the type lookup, even though Apertus first said *interpellation*:

```json
{
 "schema_version": "opd-affair/0.1",
 "source": {
  "url": "https://files.openparldata.ch/doc/5192/592b1e53ea42d39cd74b6…",
  "pages": 3,
  "opd_doc_id": 928926
 },
 "language": "it",
 "body": {
  "level": {
   "value": "communal",
   "status": "metadata",
   "source": "OpenParlData body_key"
  },
  "body_key": "5192"
 },
 "affair": {
  "affair_number": {
   "value": "1654",
   "status": "extracted",
   "page": 1,
   "quote": "Interrogazione no. 1654"
  },
  "title": {
   "value": "Legge sulle Commesse Pubbliche, ce la facciamo...?",
   "status": "extracted",
   "page": 1,
   "quote": "Legge sulle Commesse Pubbliche, ce la facciamo"
  },
  "type": {
   "value": "question",
   "status": "normalised",
   "page": 1,
   "quote": "Interrogazione",
   "opd_type_harmonized_id": 12
  },
  "type_original": {
   "value": "interrogazione",
   "status": "extracted",
   "page": 1,
   "quote": "Interrogazione"
  },
  "actors": [
   {
    "name": {
     "value": "Demis Fumasoli",
     "status": "extracted",
     "page": 1,
     "quote": "Onorevole Signor\nDemis Fumasoli"
    },
    "role": {
     "value": "submitter",
     "status": "normalised",
     "page": 1,
     "quote": "presentata unitamente ad un altro cofirmatario"
    }
   },
   {
    "name": {
     "value": "Municipio di Lugano",
     "status": "inferred",
     "page": 1,
     "quote": "il Municipio"
    },
    "role": {
     "value": "respondent",
     "status": "normalised",
     "page": 1,
     "quote": "il Municipio"
    }
   }
  ],
  "questions": [
   {
    "question": {
     "value": "Nel corso del 2025 sono stati deliberati appalti a incarico diretto a ditte che erano già state segnalate da suissetec Ticino e Moesano come non in regola o non idonee?",
     "status": "extracted",
     "page": 2,
     "quote": "Nel corso del 2025 sono stati deliberati appalti a incarico diretto a ditte che erano già\nstate segnalate da suissetec Ticino e Moesano come non in regola o non idonee"
    }
   }
  ],
  "…": "…"
 },
 "quality": {
  "value_counts": {
   "extracted": 15,
   "normalised": 11,
   "inferred": 5,
   "rejected": 8,
   "metadata": 1
  },
  "verified_share": 0.675,
  "flags": [
   "model type 'interpellation' replaced by 'question' from the original term 'interrogazione'",
   "8 model value(s) rejected: quote not found in the document"
  ]
 }
}
```

## Install the Firefox extension

1. Firefox → `about:debugging#/runtime/this-firefox` → **Load Temporary Add-on…** → pick `src/extension/manifest.json`
   (or `make extension` to get a zip).
2. Click the William icon → **Settings** → paste your Apertus key. The key stays in the browser's extension storage and
   is sent only to the endpoint you configure.
3. Open any parliamentary PDF. William opens it in its own viewer. You can also right-click selected text on a page →
   *William: summarise selection*. Open the batch page from the toolbar popup.

## What makes the output trustworthy

Every value carries `{value, status, page, quote, char_start, char_end}`:

* The model must quote the text that supports every value. William searches for that quote in the page text
  (ignoring case, punctuation, hyphenation, quote styles, and missing spaces in broken PDF text layers) and stores
  the exact character span. **If the quote is not found, the value is removed** and logged in `quality.rejected_values`.
* `status` tells you where a value comes from:
  * `extracted`: copied from the text.
  * `normalised`: a date or vocabulary term derived from a verified quote.
  * `metadata`: taken from OpenParlData.
  * `inferred`: a judgement with no supporting quote, shown as needing review.
* Dates are kept only if day, month and year all appear in the quote. Vote counts are kept only if the number appears
  in the quote.
* The parliament's own word for the instrument ("Kleine Anfrage", "interrogazione", "question écrite") is mapped to
  the common type by a fixed lookup table, which overrides the model. This fixed the Italian "interrogazione → interpellation" error.

See [`docs/schema.md`](docs/schema.md), [`technical_report.md`](technical_report.md),
and the JSON Schema [`docs/opd-affair-0.1.schema.json`](docs/opd-affair-0.1.schema.json).

Requirements: Docker; an OpenAI-compatible Apertus endpoint (`LLM_*` env vars); no GPU and no model weights.
Firefox ≥ 115 for the extension.

## Licence

Code: Apache-2.0 (repository `LICENSE`). Report and docs: CC-BY-4.0. Data we produced (`data/`, `eval/`, `tests/fixtures/`): CDLA-Permissive-2.0. pdf.js (Apache-2.0) is included in `src/extension/lib/`.
