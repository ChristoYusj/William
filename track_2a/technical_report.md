# Technical report — William

- **Track:** Track 2A — OpenParlData: Extracting Parliamentary Affairs from PDFs into One Common Structure
- **Event:** Online
- **Team:** RedPandas — Christopher Yazigi, Giovanni Yazbeck, Alfredo Pio Yazbeck
- **Demo:** Firefox extension in `src/extension`; API via `make run`

## 1. Summary

William converts parliamentary documents from federal, cantonal and communal parliaments into one common, versioned
structure (`opd-affair/0.1`) with Apertus 1.5 70B. Every value is tied to a page and a verbatim text span, and a value
whose evidence cannot be found is removed. The same pipeline runs in three forms:
* a **Firefox extension**: summarises a PDF or a selection in the document's language and links its topics to
  Swiss news;
* an in-extension **batch page**: many links → JSON + PDF report;
* an **HTTP API** for production use.

On a 14-document sample (3 levels × DE/FR/IT, all from OpenParlData):
* **147 values were verified against the source text**;
* **70 proposed values were rejected** (65 of them had no quote at all);
* **54 classifications are kept but marked `inferred`**.

**Headline insight:** a common schema works for *identity* fields: number, title, original type term, addressee,
authors (core-field coverage 0.78). It does **not** work, from the PDF alone, for *procedure*: state, decisions, history.
Only 2 of 13 procedural states were verifiable, and **0 decisions** were found in the documents.

## 2. Architecture

```
link ─► fetch (PDF via pypdf / pdf.js, HTML, OpenParlData API & file links)
     ─► OPD hints (body_key → level, OPD type & number of the parent affair, used as a cross-check)
     ─► Apertus 70B: JSON with {v, p, q} per field (prompt william-prompts/0.2)
     ─► verifier: quote search on the page (normalised; space-insensitive fallback) → char span
                  dates: day+month+year must be in the quote; numbers must be in the quote
                  vocab fields: legal term or removed; no quote → status "inferred"
                  type_original → fixed type lookup (DE/FR/IT) overrides the model
     ─► opd-affair/0.1 record + quality block (+ raw model output kept for offline re-verification)
     ─► summary (document language) + topics → Google News RSS (CH edition, document language)
```

* `src/extension/shared/{vocab,prompts}.json`: the single source of prompts and vocabularies, read by both the
  extension and the API.
* `src/extension/shared/core.js` and `src/william/{verify,extract}.py`: the verifier and record assembly, written
  twice. `tests/parity.mjs` checks that they produce **identical records** on all 13 stored documents (0 differences).
* `src/william/api.py`: FastAPI (`/v1/extract`, `/v1/report`, `/v1/summarize`, `/v1/schema`, `/v1/vocab`).
  `make run` starts it in Docker.
* The extension's PDF report is written by a 150-line dependency-free PDF writer (`shared/minipdf.js`). Its output was
  checked by parsing it back with pypdf in strict mode (27 pages, working links).

## 3. Use of Apertus

- **Model:** `swiss-ai/Apertus-v1.5-70B` (8B selectable). It is reached through the CSCS OpenAI-compatible endpoint;
  `LLM_NAME` / `LLM_BASE_URL` / `LLM_API_KEY` follow the judges' convention.
- **How it is used:** inference only (temperature 0). There are two prompts: structured extraction with quotes, and a
  summary with topics. No other LLM is used anywhere.
- **Cost:** the 14-document extraction run used 44.6k input and 12.8k output tokens.

## 4. Data

`data/sample/urls.txt` lists 14 OpenParlData documents: federal (CHE ×4), cantonal (GE ×2, TI, ZH) and communal
(Bern 351, Zürich 261, Lausanne 5586 ×2, Lugano 5192 ×2), in German, French and Italian. They are public parliamentary
documents fetched at run time. Page texts are stored in `tests/fixtures/` only for the offline tests. There is no
personal data beyond the names of elected officials as published by the parliaments.

## 5. Evaluation

**We have no manually checked gold set** (a single-day build). Instead we report three measurements that need no gold
labels:

**(a) Evidence verification** (`make eval`, verifier v2, prompt v0.2).

| level | docs | verified values | inferred | rejected | verified share | core-field coverage* |
|---|---|---|---|---|---|---|
| federal | 4 | 36 | 11 | 9 | 0.64 | 0.71 |
| cantonal | 4 | 37 | 16 | 7 | 0.62 | 0.88 |
| communal | 6 | 74 | 27 | 54 | 0.48 | 0.77 |
| **all** | 14 (1 failed) | **147** | 54 | 70 | 0.54 | 0.78 |

\* share of {number, title, type, submission date, addressee, state} that are present.

The same per-language breakdown is printed by `make eval`. The weakest cell is communal FR, with 36 rejections. It
comes from one Lausanne PDF whose text layer has **no space characters** ("RéponsedelaMunicipalité…").

**(b) Ablations.** "Verified" counts include OPD metadata values.

| run | verified | rejected |
|---|---|---|
| prompt v0.1 + verifier v1 (12 docs; 2 of them were the Fedlex-wall files below, swapped out afterwards) | 73 | 112 |
| prompt v0.2 ("q is REQUIRED…") + punctuation-insensitive matching + vocab-without-quote → `inferred` (14 docs) | 132 | 72 |
| + space-insensitive fallback for broken text layers (same model output, re-verified offline) | 147 | 70 |

The v0.1 and v0.2 rows differ in documents as well as in prompt, so they show the direction of the change, not a
controlled comparison. The last row is controlled: identical model output, verifier change only.

**(c) Agreement with OpenParlData's own harmonized type** (`python -m william.evaluate crosscheck`): **5/10** where both
exist. The disagreements are informative:
* **Italian vocabulary trap.** Ticino's *interrogazione* is a written question (OPD id 12). Apertus labelled it
  *interpellation*. A fixed term lookup on the verified original word now fixes this. That is +1, and the case is
  flagged in the record.
* **Document vs affair.** A consultation report inside a parliamentary initiative, a committee report inside a
  government affair, and a list of proposals in a Bern government affair are all correct *for the document* but not
  for the affair → schema proposal `document.type` (docs/schema.md §Known gaps).
* **Possible OPD labelling inconsistency.** A Ticino item numbered `I126.19` with the original term *Interpellazione*
  is harmonized by OPD as *question*.

**Data-quality findings in OpenParlData itself.**
* For at least two federal documents (e.g. doc 485241, "FF 2013 1073"), OPD's stored file and `text` are the Fedlex
  *"please enable JavaScript"* page, not the PDF. William detects this and flags *"source is listed as a PDF but the
  file is not a PDF"* instead of extracting from it.
* OPD's `state_name_harmonized_id` is filled for **278 of 326,334 affairs (0.09 %)**, measured via
  `/v1/affairs/group_by/states_harmonized` on 16 Oct 2026.

**Cross-parliamentary question: *can the procedural state of affairs be read from the documents?*** OPD cannot answer
this today (0.09 % coverage). Our answer is **mostly no**:
* William proposed a state for 13/13 documents, but only 2 had a verbatim basis; 11 are `inferred`;
* none of the 13 documents contained a parliamentary decision with an outcome.

State and outcome should come from structured event data (OPD `events`/`votings`), with documents used as evidence,
not as the source. This is a well-founded *partial negative* result for the common-schema question.

## 6. Limitations

* There is no human gold set, so precision of the *kept* values is not measured. Verification shows that a value
  appears in the document, not that it fills the right slot (e.g. a co-signatory recorded as the submitter).
* Only the first 28k characters are read; long documents are truncated and flagged. The Zürich 261 document failed in
  the v0.2 run because of a verifier bug (a character whose lowercase form is two characters). The bug is fixed and
  tested, but that document was not re-run, to save API cost. With v0.1 it returned no usable values.
* There is no OCR: scanned PDFs are flagged ("little or no text layer"), not processed.
* One PDF = one affair. Bundles of several affairs per PDF are not split.
* News links come from Google News search. They are related coverage, not verified to be about the same affair; in the
  live test some results were off-topic. Topic phrases are paraphrased by Apertus; a fuzzy locator places 4 of 6 inline
  (the rest are shown as clickable chips).
* The API has no authentication and spends the operator's Apertus credits. It refuses private/local addresses (SSRF
  guard), caps downloads at 25 MB and sends no CORS headers. Run it behind a gateway in production.
* Tested: live API end to end in Docker (`/v1/extract` with summary + news, `/v1/report` PDF, error handling for bad and
  local links), offline tests (`make test`, 8 tests), JS/Python parity (0 differences), Docker build, `web-ext lint`
  (0 errors), and in-browser PDF generation. Not tested: a full Apertus-backed run inside Firefox. The extension was
  loaded in Firefox, but no API key was entered in that profile.

## 7. Reproducibility

`make test` and `make eval` reproduce every number in §5 without an API key. They use the stored Apertus outputs in
`eval/sample_70b.json` and the page texts in `tests/fixtures/`. `make sample` re-runs the extraction live. Apertus at
temperature 0 is not perfectly deterministic, so expect small differences.

## 8. Next steps

* A 60–100-affair gold set (3 languages × 3 levels), checked by people, to measure slot precision and recall.
* Schema 0.2: `document.type`, `affairs[]` per document, and state/decisions taken from OPD events.
* Chunked reading for long documents; OCR for scanned PDFs (an open OCR model, on-prem).
* Run with the 8B model on-prem (~20 GB) and compare against 70B on the same verifier.
