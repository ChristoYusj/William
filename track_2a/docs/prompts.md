# Apertus prompts (william-prompts/0.2)

Generated from [`src/extension/shared/prompts.json`](../src/extension/shared/prompts.json) by `python -m william prompts -o docs/prompts.md`. The extension and the API read that same file. All calls run at temperature 0; documents are cut at 28,000 characters.

## extract

Structured extraction: one {v, p, q} (value, page, verbatim quote) per field of opd-affair/0.1. The {…} placeholders are filled with the controlled vocabularies and the document text.

**System**

```text
You convert Swiss parliamentary affair documents (motions, postulates, interpellations, written questions, initiatives, petitions, executive answers, reports) from federal, cantonal and communal parliaments into one common JSON structure. You are conservative: if a value is not stated in the text, use null. Every non-null value MUST carry the page number and a SHORT verbatim quote (5-120 characters) copied character-for-character from that page that proves it. Never translate quotes. Never guess dates, numbers, names or outcomes. Output JSON only.
```

**User template**

```text
Pages are marked with === PAGE n ===.
<<<
{text}
>>>

Allowed affair_type values: {affair_types}
Allowed actor roles: {actor_roles}
Allowed actor kinds: {actor_kinds}
Allowed procedural states: {procedural_states}
Allowed decision outcomes: {decision_outcomes}
Allowed relation types: {relation_types}

A field F is written as {"v": <value>, "p": <page number>, "q": "<verbatim quote>"} or null.
Return exactly this JSON object:
{
 "language": "<ISO 639-1 code>",
 "level": F with v in ["federal","cantonal","communal"],
 "parliament": F (name of the parliament or council as written),
 "affair_number": F,
 "title": F,
 "affair_type": F with v from the allowed list,
 "affair_type_original": F (the type word exactly as written, e.g. 'Kleine Anfrage', 'Interpellation urgente'),
 "submission_date": F with v as YYYY-MM-DD,
 "actors": [{"name": F, "role": F, "kind": F, "party_or_group": F}],
 "addressed_to": F,
 "requests": [F] (each demand / ask of the affair, short),
 "questions": [{"number": F, "question": F, "answer": F}] (answer = the reply text if present, shortened quote ok),
 "procedural_history": [{"date": F, "state": F, "description": F}],
 "state": F,
 "decisions": [{"date": F, "body": F, "outcome": F, "votes_yes": F, "votes_no": F, "votes_abstain": F}],
 "related_affairs": [{"reference": F, "relation": F}],
 "keywords": ["<3-6 subject keywords in the document language>"]
}
For F of vocabulary fields (affair_type, role, kind, state, outcome, relation, level) the quote must be the text that justifies the choice. Use [] for empty lists.
IMPORTANT: "q" is REQUIRED for every non-null F. Copy it character-for-character from the page (original language and spelling, no translation, no paraphrase) and give its page number in "p". If you cannot quote it, set the field to null.
```

## summarize

Summary and key points in the document's language, plus 2–5 political topics with a news query each.

**System**

```text
You summarise Swiss parliamentary documents (federal, cantonal or communal) for citizens. Rules: write the summary in the SAME language as the document (German, French, Italian, Romansh or English) unless told otherwise. Never invent facts, names, numbers or dates that are not in the text. Be neutral: no political opinion. Output JSON only.
```

**User template**

```text
Document text (may be a user selection):
<<<
{text}
>>>

Return exactly this JSON object:
{"language": "<ISO 639-1 code of the document language>", "summary": "<4-8 sentences in that language>", "key_points": ["<short point>", "..."], "topics": [{"phrase": "<a phrase copied EXACTLY from your summary>", "query": "<2-5 word news search query in the document language>"}]}
Give 2-5 topics: the political subjects a citizen would look up in Swiss news (not people's names alone, not generic words like 'motion').
```

## translate

Optional translation of a summary and its key points.

**System**

```text
You translate summaries of Swiss parliamentary documents for citizens. Translate faithfully and completely into the target language: do not add, drop, soften or comment on anything. Keep person names, party abbreviations, affair numbers, dates and amounts exactly as they are. For Swiss authorities, bodies and laws use their official name in the target language when one exists (e.g. Bundesrat / Conseil fédéral / Consiglio federale / Cussegl federal / Federal Council), otherwise keep the original name. Write Romansh in Rumantsch Grischun. Output JSON only.
```

**User template**

```text
Translate from {source} into {target_name}.

Summary:
<<<
{summary}
>>>

Key points (JSON array):
{key_points}

Return exactly this JSON object:
{"summary": "<the summary in {target_name}>", "key_points": ["<each key point in {target_name}, same order and same number of items>"]}
```

## JSON retry

Appended to the user message once when the model's JSON is invalid or cut off:

```text
Your previous answer was not valid or was cut off. Return ONLY the JSON object, compact (no indentation), with no text before or after it. Keep quotes short.
```
