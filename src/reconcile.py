"""
Cross-document reconciliation: the second pass that sees all documents at once.

A per-document extraction is blind to the other 23 docs, so anything that requires
comparing documents (a rebrand, a restatement, the snapshot duplicating a standalone
report) has to live here. For a PoC this consumes a small hand-curated knowledge file
(reconciliation.yaml); the value of the pass is making the comparison trustworthy:
- canonicalize company identity across the FleetLink -> Apex rebrand,
- cross-check our automated numbers against Sagard's manual snapshot (agree / recovered
  by the pipeline / snapshot-only / mismatch),
- surface restatements as explicit conflicts instead of silently picking one value.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from . import config
from .normalize import normalize_value

_RECON_PATH = Path(__file__).resolve().parent.parent / "reconciliation.yaml"


def load() -> dict:
    return yaml.safe_load(_RECON_PATH.read_text(encoding="utf-8"))


def company_key(name: str) -> str:
    """Stable key from a company name: first alphabetic token, lowercased.
    'NovaCloud Analytics Inc.' -> 'novacloud'; 'FleetLink Logistics Network' -> 'fleetlink'."""
    tok = re.findall(r"[A-Za-z]+", name or "")
    return tok[0].lower() if tok else ""


def canonical_company(name: str, recon: dict) -> tuple[str, str]:
    """Return (canonical_name, canonical_key), applying the rebrand alias."""
    key = company_key(name)
    alias = recon.get("entity_aliases", {}).get(key)
    if alias:
        canon = alias["canonical_name"]
        return canon, company_key(canon)
    return name, key


def cross_check(rows: list[dict], recon: dict) -> list[dict]:
    """Compare our extracted standalone values against the manual snapshot baseline."""
    baseline = recon.get("manual_snapshot_baseline", {})
    period = baseline.get("period")
    # index our rows by (company_key, metric) for the snapshot period
    idx: dict[tuple[str, str], dict] = {}
    for r in rows:
        if r.get("period") == period:
            idx[(r["company_key"], r["canonical_metric"])] = r

    out = []
    for entry in baseline.get("values", []):
        ck, metric = entry["company_key"], entry["metric"]
        ours = idx.get((ck, metric))
        snap_raw = entry.get("snapshot_value_raw")
        rec = {
            "company_key": ck,
            "metric": metric,
            "period": period,
            "snapshot_value": snap_raw,
            "pipeline_value": ours["value_raw"] if ours else None,
            "note": entry.get("note", ""),
        }
        if snap_raw is None and ours is not None:
            rec["status"] = "recovered_by_pipeline"  # snapshot dropped it; we got it
        elif snap_raw is not None and ours is None:
            rec["status"] = "snapshot_only"
        elif snap_raw is not None and ours is not None:
            # compare normalized magnitudes using the metric's own unit type
            ut = config.CANONICAL_METRICS.get(metric, {}).get("unit_type", "currency")
            a = normalize_value(snap_raw, ut).value
            b = ours.get("value")
            rec["status"] = "agree" if (a is not None and b is not None and abs(a - b) < 0.05) else "mismatch"
        else:
            rec["status"] = "absent_both"
        out.append(rec)
    return out


def restatement_conflicts(recon: dict) -> list[dict]:
    out = []
    for r in recon.get("restatements", []):
        out.append({
            "company_key": r["company_key"],
            "metric": r["metric"],
            "period": r["period"],
            "values": r["values"],
            "note": r.get("note", ""),
        })
    return out
