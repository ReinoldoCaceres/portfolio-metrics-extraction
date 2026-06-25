# Written note — approach, assumptions, next steps

*Short version; the [README](README.md) is the full write-up with run instructions and data model.*

## How I approached it
The sample set includes the artifact this tool would replace — the portfolio team's hand-built Q2 snapshot. It covers only 4 of 9 companies, puts one company's ARR in a footnote, omits another's headcount, and states it is "not independently verified." Because portfolio numbers get acted on, I scoped this as reconciliation with provenance rather than plain extraction: a wrong comparable is more costly than a missing one, so the design prioritizes catching wrong values over filling every cell.

The split: the LLM maps each company's own label to a canonical metric and quotes its source; deterministic code parses the number, verifies the quote is really on the page, and reconciles across documents. The model handles meaning; code handles everything checkable.

## What I built and why
- **Pipeline:** `pdfplumber` text → one structured-output LLM call per document (strict JSON schema, cached) → deterministic normalize (parse "$8.4M" → 8.4) + provenance check → a long tidy metrics table (`metrics_long.csv`) → a Q2 review pivot (`metrics_pivot_q2_2025.csv`) and a reconciliation report.
- **17 metrics across 3 business-model cohorts** (SaaS / lender / payments). Metrics are compared only within a cohort, because "Recognized Revenue" means subscription, interest income, and take-rate revenue across the three. A deterministic guard drops a metric mapped onto the wrong model.
- **Cross-document reconciliation:** cross-check the extracted numbers against the manual snapshot — this recovered the TalentVault headcount the snapshot dropped; auto-detect restatements from a document's own footnotes — it flagged PeopleFlow's Q1 revenue restatement (4.7M → 4.6M) with the footnote as evidence; and resolve a company rebrand. Cross-document facts use a machine-proposes / human-ratifies split in a small, visible `reconciliation.yaml`.
- **Verification:** every value is checked against its source page, and a hand-keyed ground-truth harness scores accuracy and names any miss. On this corpus: 49/49 on the hand-keyed cells, and 144/146 values provenance-verified (the 2 are flagged, not dropped). A committed cache makes the run reproducible offline with no API key (~23 gpt-4o-mini calls, a few cents, linear per document).

## Key assumptions
- A shared label can mean different metrics, so companies are tagged with a business-model cohort and compared only within it.
- Revenue is the total recognized line, not a component; TPV is not revenue.
- Currency is kept native; no FX conversion — no rate is disclosed in the corpus, so converting would introduce an unsourced number. Currency is flagged instead.
- Net burn is put on a common monthly basis (one company reports quarterly) so a comparison isn't ~3x off.
- All figures are unaudited management estimates (the documents say so) — a review-ready artifact, not an authoritative one.
- The snapshot is treated as a cross-check oracle, not another input document.
- Provenance is a soft substring flag (records a status; doesn't drop data) — deliberately, for a PoC.

## Potential next steps
- **Rules-first / LLM-fallback:** parse the clean two-column tables deterministically and route only prose/footnote/ambiguous cases to the model — lower cost, no model involvement on the easy ~80%.
- **Strict, fail-closed provenance** (token/column-aware) so a side-by-side column can't pass the wrong value.
- **Auto-propose entity aliases** (rebrands) from the text, the way restatements already are.
- **Productionize into the data stack:** land the long table as a dbt source, model the pivot/marts downstream, attach provenance + grain-uniqueness as dbt tests, orchestrate per-document extraction, and use the stored `text_hash` to skip unchanged documents.
- **Robustness for real packages:** OCR for scanned PDFs, layout-aware table extraction, FX with a sourced rate, and a review surface for low-confidence cells.
