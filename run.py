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

# The Portfolio Snapshot is Sagard's hand-built artifact (the thing we automate);
# it is used as a cross-check oracle via reconciliation.yaml, not extracted as a source.
SNAPSHOT_MARKER = "Portfolio_Snapshot"


def main() -> None:
    ap = argparse.ArgumentParser(description="Portfolio metrics extraction PoC")
    ap.add_argument("--extract", action="store_true",
                    help="run live LLM extraction (needs OPENAI_API_KEY); default replays cache")
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--out", default=str(ROOT / "outputs"))
    args = ap.parse_args()

    pdfs = [p for p in list_pdfs(args.data) if SNAPSHOT_MARKER not in p.name]
    mode = "LIVE EXTRACTION" if args.extract else "REPLAY FROM CACHE"
    print(f"\n=== Portfolio Metrics Extraction ({mode}) ===")
    print(f"Processing {len(pdfs)} company reports (snapshot excluded -> used as cross-check oracle)\n")

    records = extract_all(pdfs, force=args.extract)
    recon = reconcile.load()
    rows = table.build_long_rows(records, recon)
    pivot = table.build_pivot(rows, recon)
    table.save_outputs(rows, pivot, args.out)

    # ---- console: the review pivot ----
    print("\n--- Q2 2025 portfolio cross-section (grouped by business model) ---\n")
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(pivot.to_string())
    print("\nlegend: '~' prose  '(ftn)' footnote  '*restated' conflict  '--' not disclosed  'n/a' not applicable\n")

    # ---- reconciliation report ----
    xc = reconcile.cross_check(rows, recon)
    restate = reconcile.restatement_conflicts(recon)
    _write_recon_report(xc, restate, Path(args.out))
    print("--- reconciliation cross-check vs Sagard's manual snapshot ---")
    for r in xc:
        print(f"  [{r['status']:<20}] {r['company_key']}/{r['metric']}: "
              f"snapshot={r['snapshot_value']} pipeline={r['pipeline_value']}")
    for r in restate:
        vals = " vs ".join(f"{v['value_raw']} ({v['as_reported_in']})" for v in r["values"])
        print(f"  [restatement        ] {r['company_key']}/{r['metric']} {r['period']}: {vals}")

    # ---- provenance summary ----
    verified = sum(1 for r in rows if r["provenance"] == "verified")
    checkable = sum(1 for r in rows if r["provenance"] != "derived")
    print(f"\nprovenance: {verified}/{checkable} extracted values verified against source page text")

    # ---- accuracy ----
    acc = evaluate.evaluate(rows)
    print(f"\naccuracy vs hand-keyed ground truth: {acc['correct']}/{acc['total']} = {acc['accuracy']}%")
    for m in acc["misses"]:
        print(f"  MISS  {m['company_key']}/{m['metric']}: expected {m['expected']}, got {m['got']}  {m['note']}")

    print(f"\noutputs written to {args.out}/ : metrics_long.csv, metrics_pivot_q2_2025.csv, reconciliation_report.md\n")


def _write_recon_report(xc, restate, outdir: Path) -> None:
    outdir.mkdir(exist_ok=True)
    lines = ["# Reconciliation report\n",
             "## Cross-check vs Sagard's manual Q2 2025 snapshot\n",
             "| company | metric | snapshot | pipeline | status | note |",
             "|---|---|---|---|---|---|"]
    for r in xc:
        lines.append(f"| {r['company_key']} | {r['metric']} | {r['snapshot_value']} | "
                     f"{r['pipeline_value']} | {r['status']} | {r['note']} |")
    lines.append("\n## Restatements (same company/metric/period, two values)\n")
    for r in restate:
        vals = "<br>".join(f"{v['value_raw']} - {v['as_reported_in']}" for v in r["values"])
        lines.append(f"- **{r['company_key']} / {r['metric']} {r['period']}**: {vals}<br>{r['note']}")
    (outdir / "reconciliation_report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
