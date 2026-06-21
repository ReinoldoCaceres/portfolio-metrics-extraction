"""
Accuracy against a small hand-keyed ground truth (~50 cells covering all 9 Q2 2025
companies, core + key cohort metrics). A real, checkable number with the misses named
beats an LLM-reported confidence score: it measures the outcome, not the model's vibe.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_GT_PATH = Path(__file__).resolve().parent.parent / "ground_truth.csv"


def _close(expected: float, got: float | None) -> bool:
    if got is None:
        return False
    return abs(got - expected) <= 0.05 + 0.01 * abs(expected)


def evaluate(rows: list[dict]) -> dict:
    gt = pd.read_csv(_GT_PATH)
    idx = {(r["company_key"], r["canonical_metric"], r["period"]): r for r in rows}
    total = len(gt)
    correct, misses = 0, []
    for _, g in gt.iterrows():
        key = (g["company_key"], g["metric"], g["period"])
        row = idx.get(key)
        got = row["value"] if row else None
        if _close(float(g["expected_value"]), got):
            correct += 1
        else:
            misses.append({
                "company_key": g["company_key"], "metric": g["metric"],
                "expected": f"{g['expected_value']} {g['expected_unit']}",
                "got": (f"{got} {row['unit']}" if row else "NOT FOUND"),
                "note": g.get("note", ""),
            })
    return {
        "total": total,
        "correct": correct,
        "accuracy": round(100.0 * correct / total, 1) if total else 0.0,
        "misses": misses,
    }
