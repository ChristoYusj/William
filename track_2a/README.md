# William — Swiss parliamentary affairs → one common structure (Apertus)

**Track 2A · OpenParlData challenge** — extracting parliamentary affairs (federal, cantonal, communal)
from PDFs into one common, provenance-carrying JSON structure with Apertus.

William comes in three parts. All three share the same prompts, vocabularies and verifier, which live in one place:
[`src/extension/shared/`](src/extension/shared).

| Part | What it does |
|---|---|
| **Firefox extension** ([`src/extension`](src/extension)) | Opens parliamentary PDFs in its own viewer. Summarises the **document or the selected text in the document's language** (DE/FR/IT/RM). Highlights the political topics in the summary; each highlight links to **Swiss news articles** on the subject (Google News, CH edition). Extracts the affair into the common JSON with page-level evidence. Context menu: summarise any selection or page on any website. |
| **Batch page** (inside the extension, `batch/batch.html`) | Paste many links (PDFs, HTML pages, `api.openparldata.ch/v1/affairs/ID`, `/v1/docs/ID`, `files.openparldata.ch/doc/…`). For each link it produces a summary plus one `opd-affair/0.1` record. Download everything as **JSON** or as a **PDF report**, generated in the browser. |
| **HTTP API + web page** ([`src/william`](src/william)) | The same pipeline without a browser: web page at `/`, `POST /v1/extract`, `POST /v1/report` (PDF), `POST /v1/report/items`, `POST /v1/summarize`, `POST /v1/translate` (summary → DE/FR/IT/RM/EN with Apertus; also `translate_to` on extract/summarize), `GET /v1/schema`, `GET /v1/vocab`; plus a CLI. |

## Run it (judges)

```bash
export LLM_API_KEY=...                                  # CSCS / Apertus key
export LLM_BASE_URL=https://api.inference.cscs.ch/v1    # default
export LLM_NAME=swiss-ai/Apertus-v1.5-70B               # default
make run          # API on http://localhost:8000  (web form at /, Swagger at /docs)
make test         # offline tests (verifier, schema, re-verification of stored Apertus outputs)
make eval         # evaluation table from the stored run (no API calls)
make sample       # live: re-extract the 14-document sample with Apertus
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

## Samples

* **14-document sample** (federal / cantonal / communal × DE / FR / IT): inputs in
  [`data/sample/urls.txt`](data/sample/urls.txt). Full Apertus outputs and the verified records are in
  [`eval/sample_70b_reverified.json`](eval/sample_70b_reverified.json); the evaluation tables are in
  [`technical_report.md`](technical_report.md) §5.
* **Validator:** the provenance verifier ([`src/william/verify.py`](src/william/verify.py),
  [`src/extension/shared/core.js`](src/extension/shared/core.js)) plus the JSON Schema
  [`docs/opd-affair-0.1.schema.json`](docs/opd-affair-0.1.schema.json) (`GET /v1/schema`).
  `python -m william.evaluate reverify|stats|crosscheck` re-checks stored outputs offline.
* **Apertus prompts:** [`src/extension/shared/prompts.json`](src/extension/shared/prompts.json).
* **Extension end-to-end run** (headless Firefox, 19/19): screenshots and results in [`eval/e2e/`](eval/e2e).

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
