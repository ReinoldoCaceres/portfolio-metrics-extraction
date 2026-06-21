"""
Accuracy against a small hand-keyed ground truth (~50 cells covering all 9 Q2 2025
companies, core + key cohort metrics). A real, checkable number with the misses named
beats an LLM-reported confidence score: it measures the outcome, not the model's vibe.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_GT_PATH = Path(__file__).resolve().parent.parent / "ground_truth.csv"


def _match(expected_val: float, expected_unit: str, row: dict | None) -> bool:
    """Correct requires BOTH the number AND the unit to match (43% != 43 bps)."""
    if row is None or row.get("value") is None:
        return False
    if str(row.get("unit")) != str(expected_unit):
        return False
    return abs(row["value"] - expected_val) <= 0.05 + 0.01 * abs(expected_val)


def evaluate(rows: list[dict]) -> dict:
    gt = pd.read_csv(_GT_PATH)
    idx = {(r["company_key"], r["canonical_metric"], r["period"]): r for r in rows}
    total = len(gt)
    correct, misses = 0, []
    for _, g in gt.iterrows():
        key = (g["company_key"], g["metric"], g["period"])
        row = idx.get(key)
        if _match(float(g["expected_value"]), g["expected_unit"], row):
            correct += 1
        else:
            misses.append({
                "company_key": g["company_key"], "metric": g["metric"],
                "expected": f"{g['expected_value']} {g['expected_unit']}",
                "got": (f"{row['value']} {row['unit']}" if row else "NOT FOUND"),
                "note": g.get("note", ""),
            })
    return {
        "total": total,
        "correct": correct,
        "accuracy": round(100.0 * correct / total, 1) if total else 0.0,
        "misses": misses,
    }
