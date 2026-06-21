"""
Unit tests for the deterministic layer (the part the design claims is "checkable").
Run: python -m pytest -q   (or: python tests/test_pipeline.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.normalize import normalize_value, normalize_period, monthly_from_basis
from src import table, config


def test_currency_scales():
    assert normalize_value("$8.4M", "currency").value == 8.4
    assert normalize_value("$3.42B", "currency").value == 3420.0      # billions -> millions
    assert normalize_value("$241k", "currency").value == 0.241
    assert normalize_value("($0.75M)", "currency").value == -0.75     # parens = negative
    assert normalize_value("$(5M)", "currency").value == -5.0         # currency before paren


def test_no_thousands_truncation():
    # regression: values >= 1000 must not be truncated to their first 3 digits
    assert normalize_value("1000", "count").value == 1000
    assert normalize_value("1,420", "count").value == 1420
    assert normalize_value("12,500", "currency").value == 12500.0
    assert normalize_value("3420M", "currency").value == 3420.0


def test_units():
    assert normalize_value("78%", "percent").unit == "%"
    assert normalize_value("43 bps", "percent").unit == "bps"
    assert normalize_value("2.4x", "ratio_x").value == 2.4
    assert normalize_value("~30 months", "months").value == 30


def test_period_normalization():
    assert normalize_period("Q2 2025") == "Q2 2025"
    assert normalize_period("Quarter ended June 30, 2025") == "Q2 2025"
    assert normalize_period("Period Ended: Q1 2025") == "Q1 2025"


def test_quarterly_burn_to_monthly():
    assert monthly_from_basis(-0.91, "M", "quarterly") == round(-0.91 / 3, 4)
    assert monthly_from_basis(-0.75, "M", "monthly") == -0.75


def test_cohort_guard_drops_mismapped_metric():
    # a SaaS metric (arr) emitted for a lender must be dropped, not shown as a confident-wrong cell
    rec = {
        "pdf": "synthetic.pdf", "pages": ["Total Loan Book (gross) $316M"],
        "extraction": {
            "company_name": "Synthetic Lender Corp.", "business_model": "lender",
            "reporting_period": "Q2 2025", "reporting_currency": "USD",
            "metrics": [{
                "canonical_metric": "arr", "raw_label": "Total Loan Book (gross)",
                "value_raw": "$316M", "period": "Q2 2025", "period_basis": "point_in_time",
                "source_quote": "Total Loan Book (gross) $316M", "page": 1,
                "source_type": "table", "match_type": "inferred", "note": "",
            }],
        },
    }
    rows = table.build_long_rows([rec], {"entity_aliases": {}})
    assert not any(r["canonical_metric"] == "arr" for r in rows)


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
