# `opd-affair/0.1` — a common structure for Swiss parliamentary affairs

Machine-readable sources:
* JSON Schema: [`opd-affair-0.1.schema.json`](opd-affair-0.1.schema.json)
* controlled vocabularies: [`../src/extension/shared/vocab.json`](../src/extension/shared/vocab.json)

Both the extension and the API read these same files.

## Design

The challenge asks for a middle layer, similar in spirit to JATS: richer than Docling's generic layout, lighter than
Akoma Ntoso. `opd-affair` describes **one affair as it is visible in one document**. Each value is a *field with provenance*:

```json
{"value": "question", "status": "normalised", "page": 1,
 "quote": "Interrogazione", "char_start": 36, "char_end": 50,
 "source": "type_terms lookup on type_original"}
```

| status | meaning | trust |
|---|---|---|
| `extracted` | copied from the text; quote found verbatim (after normalisation) on `page` | high |
| `normalised` | derived from a verified quote by a fixed rule: an ISO date, or a vocabulary term | high |
| `metadata` | taken from OpenParlData metadata (`body_key` → level) or the URL domain | high |
| `inferred` | a judgement with no supporting quote (classifications only) | **review** |
| *(removed)* | the model proposed a value but its quote is not in the document → listed in `quality.rejected_values` | – |

## Record

| path | type | notes / mapping |
|---|---|---|
| `schema_version` | `"opd-affair/0.1"` | |
| `source.url`, `sha256`, `pages`, `content_type`, `retrieved_at` | | provenance of the file actually read |
| `source.opd_doc_id`, `source.opd_affair_id` | int | OpenParlData `docs.id`, `affairs.id` |
| `language` | ISO 639-1 | OPD `docs.language`, else model |
| `body.level` | `federal` \| `cantonal` \| `communal` | from OPD `body_key` (`CHE` / canton code / BFS number) → `metadata` |
| `body.body_key` | string | OPD `body_key` |
| `body.opd_body_type` | `country`/`canton`/`municipality` | OPD `bodies.type` |
| `body.parliament` | field | name as written (Grand Conseil, Gemeinderat, Consiglio comunale…) |
| `affair.affair_number` | field | OPD `affairs.number` |
| `affair.title` | field | OPD `affairs.title` |
| `affair.type` | field + `opd_type_harmonized_id`, `wikidata` | OPD `type_harmonized_id`; Wikidata where OPD has one |
| `affair.type_original` | field | OPD `type_name`, the parliament's own term |
| `affair.submission_date` | field (ISO date) | OPD `begin_date` |
| `affair.actors[]` | `{name, role, kind, party_or_group}` | OPD `contributors`; roles ≈ Popolo `Membership.role` |
| `affair.addressed_to` | field | the executive or body asked to act / answer |
| `affair.requests[]` | field | each demand of a motion/postulate/initiative |
| `affair.questions[]` | `{number, question, answer}` | question/answer pairs (interpellations, written questions) |
| `affair.procedural_history[]` | `{date, state, description}` | OPD `events` |
| `affair.state` | field + `opd_state_name_harmonized_id` | OPD `state_name_harmonized_id` (1 submitted, 2 scheduled, 3 closed) |
| `affair.decisions[]` | `{date, body, outcome, votes_yes/no/abstain}` | OPD `votings` |
| `affair.related_affairs[]` | `{reference, relation}` | |
| `affair.keywords[]` | strings | not verified (search aid only) |
| `quality` | `value_counts`, `verified_share`, `rejected_values`, `flags`, `needs_review` | |
| `extractor` | model, prompt version, token usage, raw model output | lets verification be re-run without an LLM |

## Controlled vocabularies

* **affair_types** (18): the 17 OpenParlData harmonized types, with their ids and Wikidata QIDs where they exist, plus
  `resolution`. Resolutions are common in cantonal and communal parliaments but have no OPD harmonized type.
* **type_terms** (60): maps the original term, in DE/FR/IT, to `affair_type`. It is applied to the *verified*
  `type_original` and overrides the model.
* **actor_roles**: `submitter, co_signatory, addressee, respondent, committee, rapporteur, other`.
* **actor_kinds**: `person, parliamentary_group, party, committee, executive, parliament, administration, other`.
* **procedural_states** (10): OPD's three harmonized states (submitted / scheduled / closed) are extended with
  `answered, in_committee, referred, decided, withdrawn, written_off, unknown`.
* **decision_outcomes** (9): includes the executive's *recommendation* (`recommended_accept/reject`) as distinct from a
  parliament's *decision*. Swiss documents often contain only the former.
* **relation_types**: `replies_to, follow_up_of, same_subject, joint_treatment, replaced_by, cited`.

## Known gaps → proposals for 0.2

1. **Document type ≠ affair type.** A consultation report attached to a parliamentary initiative, or an answer
   attached to an interpellation, is classified as the document, not as the affair. 0.2 should add
   `document.type` (initial text / executive answer / report / committee proposal / minutes) next to `affair.type`.
2. **Procedural state is mostly not in the PDF.** The state belongs to the affair's history, not to one document.
   Only 2 of 13 states were verifiable. It should come from OPD events, with the document confirming it.
3. **One PDF can hold several affairs** (agenda bundles, "Anträge und Synopse"). 0.2 needs `affairs[]` per document.
