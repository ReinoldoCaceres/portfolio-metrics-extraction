"""
Portfolio Metrics Extraction - crawl-phase PoC.

Usage:
  python run.py              # default: replay from committed cache/ (no API key, deterministic)
  python run.py --extract    # re-run live LLM extraction and refresh the cache (needs OPENAI_API_KEY)
  python run.py --data data --out outputs

Pipeline:
  PDFs -> [LLM extract per doc | cached] -> normalize + provenance-check -> reconcile
       -> long CSV + Q2-2025 cohort pivot + reconciliation report + accuracy
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

# currency symbols (£, €) render as mojibake on a default Windows console; force UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src import reconcile, table, evaluate
from src.llm_extract import extract_all
from src.pdf_text import list_pdfs

ROOT = Path(__file__).resolve().parent

# The Portfolio Snapshot is the portfolio team's hand-built artifact (the thing we automate);
# it is used as a cross-check oracle via reconciliation.yaml, not extracted as a source.
SNAPSHOT_MARKER = "Portfolio_Snapshot"


def main() -> None:
    ap = argparse.ArgumentParser(description="Portfolio metrics extraction PoC")
    ap.add_argument("--extract", action="store_true",
                    help="run live LLM extraction (needs OPENAI_API_KEY); default replays cache")
    ap.add_argument("--data", default=str(ROOT / "data"), help="folder of PDF reports")
    ap.add_argument("--out", default=str(ROOT / "outputs"), help="output folder for CSVs/report")
    args = ap.parse_args()

    pdfs = [p for p in list_pdfs(args.data) if SNAPSHOT_MARKER not in p.name]
    if not pdfs:
        raise SystemExit(f"error: no PDF reports found in '{args.data}'. Point --data at the folder of PDFs.")
    mode = "LIVE EXTRACTION" if args.extract else "REPLAY FROM CACHE"
    print(f"\n=== Portfolio Metrics Extraction ({mode}) ===")
    print(f"Processing {len(pdfs)} company reports (snapshot excluded -> used as cross-check oracle)\n")

    try:
        records = extract_all(pdfs, force=args.extract)
    except RuntimeError as e:
        raise SystemExit(f"error: {e}")
    recon = reconcile.load()
    rows = table.build_long_rows(records, recon)

    # data-quality: the grain (company_key, period, canonical_metric) should be unique.
    for key, ct in Counter((r["company_key"], r["period"], r["canonical_metric"]) for r in rows).items():
        if ct > 1:
            print(f"  [DUP] {ct} rows share grain {key} (last write wins)")

    pivot = table.build_pivot(rows, recon)
    table.save_outputs(rows, pivot, args.out)

    # ---- console: the review pivot ----
    print("\n--- Q2 2025 portfolio cross-section (grouped by business model) ---\n")
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(pivot.to_string())
    print("\n" + _legend(pivot) + "\n")

    # ---- reconciliation report ----
    xc = reconcile.cross_check(rows, recon)
    restate = reconcile.restatement_conflicts(recon)
    proposed = reconcile.propose_restatements(records)      # machine proposes...
    confirmed = reconcile.confirmed_restatement_keys(recon)  # ...human has ratified
    _write_recon_report(xc, restate, proposed, confirmed, Path(args.out))
    print("--- reconciliation cross-check vs the manual snapshot ---")
    for r in xc:
        print(f"  [{r['status']:<20}] {r['company_key']}/{r['metric']}: "
              f"snapshot={r['snapshot_value']} pipeline={r['pipeline_value']}")
    # auto-detected from each document's own footnotes/commentary (machine proposes)
    for p in proposed:
        tag = ("ratified in yaml"
               if (p["company_key"], p["metric"], p["period"]) in confirmed else "NEW - needs review")
        print(f"  [restatement PROPOSED ] {p['company_key']}/{p['metric']} {p['period']}: "
              f"{p['from_value']} -> {p['to_value']}  (auto-detected p{p['page']}; {tag})")
    # the human-ratified tier from reconciliation.yaml
    for r in restate:
        vals = " vs ".join(f"{v['value_raw']} ({v['as_reported_in']})" for v in r["values"])
        print(f"  [restatement RATIFIED ] {r['company_key']}/{r['metric']} {r['period']}: {vals}")

    # ---- provenance summary ----
    verified = sum(1 for r in rows if r["provenance"] == "verified")
    checkable = sum(1 for r in rows if r["provenance"] != "derived")
    print(f"\nprovenance: {verified}/{checkable} extracted values verified against source page text")
    for r in rows:
        if r["provenance"] not in ("verified", "derived"):
            print(f"  unverified  {r['company_key']}/{r['canonical_metric']} [{r['provenance']}]: "
                  f"\"{r['source_quote'][:60]}\"")

    # ---- accuracy ----
    acc = evaluate.evaluate(rows)
    print(f"\naccuracy vs hand-keyed ground truth: {acc['correct']}/{acc['total']} = {acc['accuracy']}%")
    for m in acc["misses"]:
        print(f"  MISS  {m['company_key']}/{m['metric']}: expected {m['expected']}, got {m['got']}  {m['note']}")

    print(f"\noutputs written to {args.out}/ : metrics_long.csv, metrics_pivot_q2_2025.csv, reconciliation_report.md\n")


def _legend(pivot: pd.DataFrame) -> str:
    """Show only the cell markers that actually appear in this cross-section."""
    text = " ".join(str(v) for v in pivot.values.flatten())
    parts = []
    for marker, meaning in [("~", "prose"), ("(ftn)", "footnote"), ("*restated", "conflict"),
                            ("--", "not disclosed"), ("n/a", "not applicable")]:
        if marker in text:
            parts.append(f"'{marker}' {meaning}")
    return "legend: " + "  ".join(parts)


def _write_recon_report(xc, restate, proposed, confirmed, outdir: Path) -> None:
    outdir.mkdir(exist_ok=True)
    lines = ["# Reconciliation report\n",
             "## Cross-check vs the manual Q2 2025 snapshot\n",
             "| company | metric | snapshot | pipeline | status | note |",
             "|---|---|---|---|---|---|"]
    for r in xc:
        lines.append(f"| {r['company_key']} | {r['metric']} | {r['snapshot_value']} | "
                     f"{r['pipeline_value']} | {r['status']} | {r['note']} |")
    lines.append("\n## Restatements auto-proposed from document text (machine-detected)\n")
    lines.append("_The pipeline scans each document's own footnotes/commentary for "
                 "restatement language and proposes the conflict with verbatim evidence; "
                 "a human ratifies it below._\n")
    if not proposed:
        lines.append("_none detected_")
    for p in proposed:
        tag = ("ratified in reconciliation.yaml"
               if (p["company_key"], p["metric"], p["period"]) in confirmed else "NEW - needs human review")
        lines.append(f"- **{p['company_key']} / {p['metric']} {p['period']}**: "
                     f"{p['from_value']} → {p['to_value']} _({tag})_<br>"
                     f"evidence (p{p['page']}, {p['source_doc']}): \"{p['evidence_quote']}\"")
    lines.append("\n## Restatements ratified in reconciliation.yaml (human-approved tier)\n")
    for r in restate:
        vals = "<br>".join(f"{v['value_raw']} - {v['as_reported_in']}" for v in r["values"])
        lines.append(f"- **{r['company_key']} / {r['metric']} {r['period']}**: {vals}<br>{r['note']}")
    (outdir / "reconciliation_report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
