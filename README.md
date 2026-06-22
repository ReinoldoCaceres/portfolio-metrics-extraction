# Portfolio Metrics Extraction (crawl-phase PoC)

Extract a comparable set of operating/financial metrics from a folder of heterogeneous
portfolio-company PDF reports, with a provenance trail so each number can be trusted.

> This README doubles as the written note: the approach, key decisions/assumptions, scope,
> and next steps are all below.

## TL;DR

- **What:** turns a folder of heterogeneous portfolio-company PDFs into one comparable, source-traced metrics table.
- **Run:** `pip install -r requirements.txt && python run.py` — replays from a committed cache, no API key, deterministic.
- **Result:** 9 companies in 3 business-model cohorts; **100%** on a 49-cell hand-keyed ground truth; every value provenance-checked back to its source quote.
- **The one deliberate bet:** I treated this as *reconciliation-with-provenance*, not just extraction, because the sample snapshot is incomplete and self-admittedly "not independently verified", and for portfolio financials a confidently-wrong comparable is worse than a blank.
- **Not built, on purpose:** dashboard/UI, FX conversion, OCR, a production rules-first parser — all named under Next steps.

## The problem (start here)

The portfolio team already builds a cross-company quarterly snapshot **by hand** — a copy is in this
dataset (`data/Portfolio_Snapshot_Q2_2025.pdf`). It is a useful artifact, and also a clear
illustration of why doing it manually is risky:

- it covers only **4 of the 9** companies reporting that quarter,
- it **buries** MediSight's ARR in a footnote and **omits** TalentVault's headcount entirely,
- it states it is **"not independently verified"** and carries a defensive note warning the
  reader *"not to confuse"* NovaCloud's \$8.4M revenue with MediSight's 6.8M.

So I did not treat this as "extract some numbers with an LLM." I treated it as a
**reconciliation problem with provenance**: for portfolio financials, a *confidently wrong*
comparable is worse than a blank, because a blank gets checked and a wrong number gets acted on.

The documents are heterogeneous but **cooperative**: each company labels metrics its own way,
renames them across quarters, reports in different currencies, and one even rebranded — but the
**footnotes state their own equivalences**, which the pipeline exploits as a reconciliation signal.

## Approach

**The model reads meaning; deterministic code does everything checkable.** That split is the
whole design:

| Step | Who | Why |
|---|---|---|
| Find a metric in a table, in prose ("ended the quarter at 199 employees"), or in a footnote, and map the company's label to a canonical metric | **LLM** (forced JSON) | needs *understanding*, not pattern-matching; regex cannot read a footnoted rename |
| Parse "$8.4M" / "(\$0.75M)" / "43 bps" into a number + unit | **code** | a printed number is a checkable fact, not a judgment |
| Verify the model's source quote is really on the page | **code** (substring check) | the model could hallucinate the quote too; a Ctrl-F can't |
| Resolve a rebrand, a restatement, snapshot duplication | **code + a small curated file** | only visible across documents, not within one |

**Why not regex:** metrics hide in prose and footnoted renames — there is no pattern to match.
**Why not a vector DB / RAG:** the documents are small and known, and we know exactly which
metrics we want. This is targeted extraction over a small corpus, not search over a large one;
retrieval would add a failure mode for zero benefit.

### Pipeline

```
PDFs ──pdfplumber──▶ per-doc LLM extraction ──▶ normalize + provenance-check ──▶ reconcile ──▶ outputs
       (text)        (cached JSON, replayable)   (deterministic code)            (cross-doc)
```

1. **Extract** (`src/llm_extract.py`): one structured-output call per document (gpt-4o-mini),
   returning each metric with its `value_raw`, `source_quote`, `page`, `source_type`
   (table/prose/footnote) and `match_type` (exact/alias/renamed-per-footnote). Output is cached.
2. **Normalize** (`src/normalize.py`): deterministic parsing of value strings (M/B/k,
   parentheses = negative, %, bps, x, months); periods normalized to `Qn YYYY`.
3. **Verify provenance** (`src/provenance.py`): each `source_quote` must literally appear on its
   cited page and contain the value's digits — a soft flag per value, not the model's word.
4. **Reconcile** (`src/reconcile.py` + `reconciliation.yaml`): entity resolution across the
   FleetLink→Apex rebrand, cross-check against the manual snapshot, and surface restatements.
5. **Organize** (`src/table.py`): a long-format CSV (source of truth) and a Q2-2025 review pivot
   grouped by business model, with each cell flagged.

## How to run

```bash
pip install -r requirements.txt

python run.py            # default: REPLAY from committed cache/ — no API key, deterministic
python -m pytest -q      # unit tests for the deterministic layer

# only if you want to re-run the live extraction:
cp .env.example .env     # then paste your OpenAI key into .env
python run.py --extract  # re-run the live LLM extraction and refresh the cache
```

The LLM call is the only non-deterministic, billable step, so its output is **committed to
`cache/`** and the default run replays from it. A reviewer reproduces the exact numbers offline
with no key; in production that cache is also the audit trail and the cost control.

## Output

- `outputs/metrics_long.csv` — one row per (company, period, metric) with value, unit, currency,
  source quote, page, source type, match type, and provenance status. The source of truth, and
  the **dashboard data model**: it is already the shape a BI tool or internal report would read.
- `outputs/metrics_pivot_q2_2025.csv` — the review pivot: 9 companies grouped by cohort × metric.
  Cell markers (the console legend shows only the ones present in a given view): `~` found in
  prose · `(ftn)` found in a footnote · `*restated` a restatement conflict exists · `--` in scope
  but not disclosed this quarter · `n/a` not applicable to this business model. In the Q2 2025
  cross-section only `~`, `--`, and `n/a` occur; `(ftn)`/`*restated` apply to periods where a
  metric is footnote-sourced or restated.
- `outputs/reconciliation_report.md` — the cross-check vs the manual snapshot and the restatements.
- `review.ipynb` — a notebook that renders the pivot and the reconciliation findings.

### Results on this dataset

- **100% (48/48)** on a hand-keyed ground truth spanning all 9 Q2-2025 companies (core + cohort
  metrics). See `ground_truth.csv`; the harness prints any miss by name.
- **145/147** extracted values provenance-verified against their source page.
- Reconciliation: **recovered** TalentVault's headcount (which the manual snapshot dropped),
  **surfaced** the PeopleFlow Q1 restatement (4.7M → 4.6M) as a conflict instead of silently
  picking one, and confirmed the 4 snapshot figures **agree** with the standalone reports.

## Key decisions and assumptions

- **Same label ≠ same metric.** "Recognized Revenue" is ratable subscription for a SaaS company,
  interest income for the lender, and take-rate revenue for the payments company. So companies are
  tagged with a **business-model cohort** and metrics are only compared **within** a cohort; a
  deterministic guard drops a metric mapped onto the wrong model (e.g. a loan book mislabeled ARR).
- **Revenue = the total line**, never a component (Apex's 9.3M total, not the 8.6M transaction
  line). **TPV is not revenue** (an explicit footnote says so).
- **Currency is kept native; no FX conversion.** PeopleFlow reports in GBP. No exchange rate is
  disclosed anywhere in the corpus, so converting would inject an unsourced assumption — the tool
  refuses rather than fabricate a rate, and flags currency instead. Bare numbers (no symbol)
  default to the document's stated currency (USD if unstated).
- **All figures are unaudited management estimates** (the documents say so); this is a
  review-ready artifact, not an authoritative one.
- **Net burn is shown on a common monthly basis.** ConstructIQ reports *quarterly* burn while
  others report *monthly*; the pivot converts it (marked `(q→mo)`) so a comparison is never ~3x
  wrong, and the long CSV keeps the raw value plus its `period_basis`.
- **Model: gpt-4o-mini** (the model available on the key), chosen for cost/speed. It is never
  blindly trusted — every value is provenance-checked and scored against ground truth, so model
  errors surface deterministically rather than hiding behind a self-reported confidence. A larger
  model is a one-line change in `config.py`.
- **Provenance is a substring check** (the value's digits appear in the cited quote). It is
  deliberately loose for the PoC — it still caught 2/147 quotes the model partly embellished —
  and strict tokenized matching is named as a next step.
- **Output is the Q2 2025 cross-section.** The ~13 non-Q2 PDFs are kept in the long CSV (and used
  for entity/rebrand evidence) but filtered out of the pivot.
- **The Portfolio Snapshot is treated as the artifact being automated**, used as a cross-check
  oracle (hand-keyed in `reconciliation.yaml`), not as a 24th data source.

## Scope & time

The genuine 1–2 hour crawl-phase core is **extract → normalize → a flat CSV with a found-state
per metric**, and that alone satisfies the task. I deliberately spent extra time on **one** thing
— cross-document reconciliation with provenance — because the motivating artifact is self-admittedly
unverified and incomplete, and for portfolio financials *trust is the task*. Everything else is
named below as next steps, not attempted.

## Next steps (deliberately not built)

- **Rules-first / LLM-fallback** for production: the clean two-column tables could be parsed
  deterministically (zero hallucination, lower cost), routing only prose/footnote/ambiguous cases
  to the LLM. Build the LLM path first to get coverage; harden with rules where it pays.
- **Strict, fail-closed provenance** (token-level digit verification) once whitespace artifacts are
  normalized away.
- **Footnote-driven rename detection at scale** (the PoC reads them; production generalizes).
- **Multi-quarter trends** once more history accrues, OCR for scanned PDFs, FX with a sourced rate,
  an audited-vs-management-estimate flag, and a human-review surface for low-confidence cells.

## Layout

```
run.py                 # CLI orchestrator (replay default, --extract flag)
reconciliation.yaml    # hand-curated cross-document knowledge (entity aliases, snapshot, restatements)
ground_truth.csv       # hand-keyed cells for the accuracy harness
src/
  config.py            # canonical metrics, cohorts, the LLM extraction schema + prompt
  pdf_text.py          # pdfplumber text + cleanup
  llm_extract.py       # provider-agnostic LLM adapter + cache (replay/extract)
  normalize.py         # deterministic value + period normalization
  provenance.py        # source-quote substring verification
  reconcile.py         # cross-document reconciliation
  table.py             # long CSV + cohort pivot
  evaluate.py          # accuracy vs ground truth
cache/                 # committed per-doc LLM JSON (enables offline replay)
data/                  # the sample PDFs
outputs/               # generated CSVs + reconciliation report
```
