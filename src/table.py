"""
Turn cached extractions into (1) a long-format CSV that is the source of truth and
(2) a cohort-grouped Q2 2025 review pivot. The pivot is DERIVED from the long rows,
not a parallel build.

Cell semantics in the pivot:
  value           -> extracted and provenance-verified
  value ~         -> found in prose
  value (ftn)     -> found in a footnote
  value *restated -> a restatement conflict exists (see conflicts output)
  --              -> in scope for this company but NOT disclosed this quarter
  n/a             -> not applicable to this business model (e.g. ARR for a lender)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import config
from .normalize import normalize_value, normalize_period, monthly_from_basis
from .provenance import verify
from .reconcile import canonical_company, company_key

CROSS_SECTION_PERIOD = "Q2 2025"

# Column order for the review pivot.
PIVOT_COLUMNS = (
    config.CORE_METRICS
    + ["revenue_per_headcount"]
    + config.COHORT_METRICS["saas"]
    + config.COHORT_METRICS["lender"]
    + config.COHORT_METRICS["payments_marketplace"]
)
DISPLAY = {k: v["display"] for k, v in config.CANONICAL_METRICS.items()}
DISPLAY["revenue_per_headcount"] = "Rev/Head ($K, qtr)"


def build_long_rows(records: list[dict], recon: dict) -> list[dict]:
    rows: list[dict] = []
    for rec in records:
        ext = rec["extraction"]
        pages = rec["pages"]
        canon_name, ckey = canonical_company(ext["company_name"], recon)
        cohort = ext.get("business_model", "other")
        currency = ext.get("reporting_currency", "USD")
        for m in ext.get("metrics", []):
            mk = m["canonical_metric"]
            if mk not in config.CANONICAL_METRICS:
                continue
            # Deterministic guard: a metric must belong to 'core' or to THIS company's
            # business model. A SaaS metric on a lender (e.g. loan book mis-mapped to ARR)
            # is almost certainly a model error, drop it rather than show a confident-wrong cell.
            mcohort = config.CANONICAL_METRICS[mk]["cohort"]
            if mcohort != "core" and mcohort != cohort:
                print(f"  [guard] dropped {mk} from {canon_name} ({cohort}): "
                      f"metric belongs to '{mcohort}' (raw label: {m['raw_label']!r})")
                continue
            unit_type = config.CANONICAL_METRICS[mk]["unit_type"]
            norm = normalize_value(m["value_raw"], unit_type)
            prov = verify(m["source_quote"], m.get("page", 1), pages, m["value_raw"])
            rows.append({
                "company": canon_name,
                "company_key": ckey,
                "cohort": cohort,
                "currency": currency,
                "canonical_metric": mk,
                "metric_display": DISPLAY.get(mk, mk),
                "raw_label": m["raw_label"],
                "value_raw": m["value_raw"],
                "value": norm.value,
                "unit": norm.unit,
                "period": normalize_period(m.get("period", ext.get("reporting_period", ""))),
                "period_basis": m.get("period_basis", "unknown"),
                "source_type": m.get("source_type", "table"),
                "match_type": m.get("match_type", "exact"),
                "provenance": prov,
                "source_quote": m["source_quote"],
                "page": m.get("page", 1),
                "source_doc": rec["pdf"],
                "note": m.get("note", ""),
            })
    rows += _derived_rev_per_head(rows)
    return rows


def _derived_rev_per_head(rows: list[dict]) -> list[dict]:
    """Revenue-per-Headcount ($K, quarterly) = recognized_revenue(M)*1000 / headcount."""
    idx: dict[tuple, dict] = {}
    for r in rows:
        idx[(r["company_key"], r["period"], r["canonical_metric"])] = r
    seen, out = set(), []
    for (ck, period, mk), r in list(idx.items()):
        if (ck, period) in seen:
            continue
        rev = idx.get((ck, period, "recognized_revenue"))
        hc = idx.get((ck, period, "headcount"))
        if rev and hc and rev["value"] and hc["value"]:
            seen.add((ck, period))
            out.append({
                "company": rev["company"], "company_key": ck, "cohort": rev["cohort"],
                "currency": rev["currency"], "canonical_metric": "revenue_per_headcount",
                "metric_display": DISPLAY["revenue_per_headcount"], "raw_label": "(derived)",
                "value_raw": "", "value": round(rev["value"] * 1000.0 / hc["value"], 1),
                "unit": "k", "period": period, "period_basis": "quarterly",
                "source_type": "derived", "match_type": "inferred", "provenance": "derived",
                "source_quote": f"{rev['value_raw']} / {hc['value_raw']} employees",
                "page": 0, "source_doc": rev["source_doc"], "note": "derived = revenue/headcount",
            })
    return out


def _sym(currency: str) -> str:
    return {"USD": "$", "GBP": "£", "EUR": "€"}.get(currency, "")


def format_value(value, unit, currency) -> str:
    if value is None:
        return "?"
    neg = value < 0
    v = abs(value)
    if unit == "M":
        s = _sym(currency)
        body = f"{s}{v/1000:.2f}B" if v >= 1000 else (f"{s}{v:.1f}M" if v >= 1 else f"{s}{v*1000:.0f}k")
        return f"({body})" if neg else body
    if unit == "%":
        return f"{value:.1f}%".replace(".0%", "%")
    if unit == "bps":
        return f"{value:.0f}bps"
    if unit == "count":
        return f"{int(value):,}"
    if unit == "x":
        return f"{value:.1f}x"
    if unit == "months":
        return f"{value:.0f}mo"
    if unit == "k":
        return f"{_sym(currency)}{value:.0f}k"
    return str(value)


def _cell(row: dict | None, company_cohort: str, metric: str, restated_keys: set) -> str:
    if row is not None:
        # Net burn is shown on a common MONTHLY basis so a quarterly reporter (ConstructIQ)
        # is not compared ~3x wrong against monthly peers; mark converted cells.
        if metric == "net_burn" and row["period_basis"] == "quarterly":
            mv = monthly_from_basis(row["value"], row["unit"], "quarterly")
            return format_value(mv, row["unit"], row["currency"]) + " (q->mo)"
        txt = format_value(row["value"], row["unit"], row["currency"])
        st = row["source_type"]
        if st == "prose":
            txt += " ~"
        elif st == "footnote":
            txt += " (ftn)"
        if (row["company_key"], metric, row["period"]) in restated_keys:
            txt += " *restated"
        return txt
    mcohort = config.CANONICAL_METRICS.get(metric, {}).get("cohort", "core")
    if metric == "revenue_per_headcount" or mcohort == "core" or mcohort == company_cohort:
        return "--"            # in scope but not disclosed
    return "n/a"               # not applicable to this business model


def build_pivot(rows: list[dict], recon: dict, period: str = CROSS_SECTION_PERIOD) -> pd.DataFrame:
    restated_keys = {
        (r["company_key"], r["metric"], r["period"]) for r in recon.get("restatements", [])
    }
    # index Q2 rows by (company_key, metric)
    idx = {(r["company_key"], r["canonical_metric"]): r for r in rows if r["period"] == period}
    companies = {}
    for r in rows:
        if r["period"] == period:
            companies.setdefault(r["company_key"], {"name": r["company"], "cohort": r["cohort"]})
    cohort_rank = {"saas": 0, "lender": 1, "payments_marketplace": 2, "other": 3}
    ordered = sorted(companies.items(), key=lambda kv: (cohort_rank.get(kv[1]["cohort"], 9), kv[1]["name"]))

    data, index = [], []
    for ck, meta in ordered:
        index.append(f"{meta['name']}  [{meta['cohort']}]")
        data.append({
            DISPLAY.get(mk, mk): _cell(idx.get((ck, mk)), meta["cohort"], mk, restated_keys)
            for mk in PIVOT_COLUMNS
        })
    return pd.DataFrame(data, index=index)


def save_outputs(rows: list[dict], pivot: pd.DataFrame, outdir: str | Path) -> None:
    outdir = Path(outdir)
    outdir.mkdir(exist_ok=True)
    cols = ["company", "company_key", "cohort", "currency", "canonical_metric", "metric_display",
            "raw_label", "value_raw", "value", "unit", "period", "period_basis",
            "source_type", "match_type", "provenance", "page", "source_doc",
            "source_quote", "note"]
    df = pd.DataFrame(rows)[cols].sort_values(["cohort", "company", "period", "canonical_metric"])
    df.to_csv(outdir / "metrics_long.csv", index=False)
    pivot.to_csv(outdir / "metrics_pivot_q2_2025.csv")
