# William — Hack Apertus 2026 · Track 2A · OpenParlData

**Team RedPandas** — Christopher Yazigi, Giovanni Yazbeck, Alfredo Pio Yazbeck

Apertus-powered extraction of Swiss parliamentary affairs (federal, cantonal, communal; DE/FR/IT) from PDFs into one
common, provenance-carrying structure (`opd-affair/0.1`). It runs as a Firefox extension, a batch web page and an
HTTP API.

➡ **Project:** [`track_2a/`](track_2a) · [README](track_2a/README.md) · [technical report](track_2a/technical_report.md)
([PDF](track_2a/RedPandas_Report.pdf)) · [schema](track_2a/docs/schema.md)

```bash
cd track_2a && make run      # needs LLM_API_KEY (and optionally LLM_BASE_URL / LLM_NAME)
```

Licences: code Apache-2.0 ([LICENSE](LICENSE)); report/docs CC-BY-4.0; data CDLA-Permissive-2.0.
