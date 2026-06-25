# Written note — approach, assumptions, next steps

*The short version. The [README](README.md) is the full write-up (run instructions, data model, decisions); this is the one-page note the brief asks for.*

## How I approached it
The sample set includes the artifact this tool would replace — the portfolio team's hand-built Q2 snapshot — and it makes the case for the project: it covers only **4 of 9** companies, buries one company's ARR in a footnote, omits another's headcount, and says outright it is *"not independently verified."* So I did not treat this as "extract some numbers with an LLM." For portfolio financials a **confidently-wrong comparable is worse than a blank** — a blank gets checked, a wrong number gets acted on — so I built it as **reconciliation with provenance**.

One decision drives the whole design: **the LLM reads *meaning*; deterministic code does everything *checkable*.** The model maps each company's own label to a canonical metric and quotes its source; code parses the number, verifies the quote is really on the page, and reconciles across documents.

## What I built and why
- **Pipeline:** `pdfplumber` text → one structured-output LLM call per document (strict JSON schema, cached) → deterministic **normalize** (parse "$8.4M" → 8.4) + **provenance** check (the quoted value is really on the cited page) → a long tidy metrics table → a Q2 review pivot.
- **17 metrics across 3 business-model cohorts** (SaaS / lender / payments). Metrics are only compared *within* a cohort, because "Recognized Revenue" means subscription, interest income, and take-rate revenue in the three cases. A deterministic guard drops a metric mapped onto the wrong model.
- **Cross-document reconciliation:** cross-check the extracted numbers against the manual snapshot (and **recover** what it dropped, e.g. a headcount); **auto-detect restatements** from a document's own footnotes (with verbatim evidence + page); resolve a company rebrand. High-stakes cross-document facts follow a **machine-proposes / human-ratifies** split in a small visible `reconciliation.yaml`.
- **Trustworthiness, not just output:** every value is provenance-checked, and a hand-keyed ground-truth harness scores accuracy and prints any miss by name. A committed cache makes the whole run reproducible offline with no API key.

## Key assumptions
- **Same label ≠ same metric** — so companies are tagged with a business-model cohort and compared only within it.
- **Revenue = the total recognized line**, never a component; **TPV is not revenue**.
- **Currency is kept native; no FX conversion** — no rate is disclosed in the corpus, so converting would invent an unsourced number. Currency is flagged instead.
- **Net burn is normalized to a monthly basis** (one company reports quarterly) so a comparison isn't ~3x off.
- All figures are **unaudited management estimates** (the documents say so) — this is a review-ready artifact, not an authoritative one.
- The snapshot is treated as a **cross-check oracle**, not a 24th data source.
- Provenance is a **soft substring flag** (records a status; doesn't drop data) — deliberately, for a PoC.

## Potential next steps
- **Rules-first / LLM-fallback:** parse the clean two-column tables deterministically; route only prose/footnote/ambiguous cases to the model (lower cost, zero hallucination on the easy 80%).
- **Strict, fail-closed provenance** (token/column-aware) so a side-by-side column can't pass the wrong value.
- **Auto-propose entity aliases** (rebrands) from the text, the same way restatements already are — machine proposes, human ratifies.
- **Productionize into the data stack:** land the long table as a dbt *source*, model the pivot/marts downstream, attach provenance + grain-uniqueness as dbt *tests*, orchestrate per-doc extraction with bounded concurrency, use the stored `text_hash` to skip unchanged docs.
- **Robustness for real packages:** OCR for scanned PDFs, layout-aware table extraction, FX with a sourced rate, and a review surface for low-confidence cells.
