"""
Cross-document reconciliation: the second pass that sees all documents at once.

A per-document extraction is blind to the other 23 docs, so anything that requires
comparing documents (a rebrand, a restatement, the snapshot duplicating a standalone
report) has to live here. The pass follows a machine-proposes / human-ratifies split:
- cross-check our automated numbers against the manual snapshot (agree / recovered
  by the pipeline / snapshot-only / mismatch),
- AUTO-PROPOSE restatements from each document's own footnotes, with verbatim evidence
  (propose_restatements) -- the machine detects the conflict from the text,
- apply human-ratified cross-document facts from a small, visible knowledge file
  (reconciliation.yaml): the FleetLink -> Apex rebrand alias and confirmed restatements.
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
    """The CONFIRMED tier: restatements a human has ratified into reconciliation.yaml."""
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


# --- Auto-proposed restatements -------------------------------------------------
# A restatement (a prior-period figure changed after the fact) is a cross-document
# fact, but unlike a rebrand it is usually stated IN a document's own footnote
# ("Q1 2025 Revenue has been restated from 4.7M to 4.6M"). So the pipeline can
# PROPOSE it directly from the extracted page text, with the verbatim quote + page
# as evidence. A human still ratifies it into reconciliation.yaml (the confirmed
# tier above) -- this is the "machine proposes, human approves" boundary in miniature.

_VALUE = r"[£$€]?\d[\d,]*(?:\.\d+)?\s*[MBKmbk]?"
_RESTATE_RE = re.compile(rf"restated\s+from\s+({_VALUE})\s+to\s+({_VALUE})", re.I)
_PERIOD_RE = re.compile(r"Q[1-4]\s*20\d{2}", re.I)

# Fallback metric keywords, only used if no already-extracted raw_label matches the
# restatement sentence. Order matters: check 'recurring'/'arr' before 'revenue'.
_RESTATE_KEYWORDS = [
    ("recurring", "arr"), ("arr", "arr"),
    ("headcount", "headcount"), ("employees", "headcount"),
    ("gross margin", "gross_margin"), ("loan book", "total_loan_book"),
    ("revenue", "recognized_revenue"),
]


def _sentence_around(text: str, idx: int) -> str:
    """The sentence containing position idx, as clean verbatim evidence. Start at the
    line/sentence boundary; end at the next sentence stop (a soft line-wrap inside the
    sentence is collapsed, not treated as the end)."""
    start = max(text.rfind(". ", 0, idx) + 2, text.rfind("\n", 0, idx) + 1, 0)
    end = text.find(". ", idx)
    if end == -1:
        end = text.find("\n", idx)
    if end == -1:
        end = len(text)
    return " ".join(text[start:end].split())


def _map_restate_metric(sentence: str, ext: dict) -> str | None:
    """Map a restatement sentence to a canonical metric, preferring the LLM's own
    extracted raw labels for this document, then a small keyword fallback."""
    low = sentence.lower()
    for m in ext.get("metrics", []):
        rl = (m.get("raw_label") or "").lower()
        if rl and rl in low:
            return m["canonical_metric"]
    for kw, canon in _RESTATE_KEYWORDS:
        if kw in low:
            return canon
    return None


def propose_restatements(records: list[dict]) -> list[dict]:
    """Auto-detect restatements from each document's own text (footnote/commentary),
    with verbatim evidence + page. Proposals; a human ratifies them in the YAML."""
    out, seen = [], set()
    for rec in records:
        ext = rec.get("extraction", {})
        ckey = company_key(ext.get("company_name", ""))
        for pi, page in enumerate(rec.get("pages", []), start=1):
            for mt in _RESTATE_RE.finditer(page):
                from_v, to_v = mt.group(1).strip(), mt.group(2).strip()
                sentence = _sentence_around(page, mt.start())
                pm = (_PERIOD_RE.search(sentence)
                      or _PERIOD_RE.search(page[max(0, mt.start() - 120):mt.start()]))
                period = re.sub(r"Q([1-4])\s*", r"Q\1 ", pm.group(0).upper()).strip() if pm else ""
                metric = _map_restate_metric(sentence, ext)
                key = (ckey, metric, period, from_v, to_v)
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "company_key": ckey,
                    "metric": metric or "(unmapped)",
                    "period": period or "(unknown)",
                    "from_value": from_v,
                    "to_value": to_v,
                    "evidence_quote": sentence,
                    "page": pi,
                    "source_doc": rec.get("pdf", ""),
                })
    return out


def confirmed_restatement_keys(recon: dict) -> set:
    """(company_key, metric, period) tuples a human has ratified in the YAML."""
    return {(r["company_key"], r["metric"], r["period"]) for r in recon.get("restatements", [])}
