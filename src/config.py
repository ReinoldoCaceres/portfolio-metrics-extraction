"""
Canonical metric definitions, cohort structure, and the LLM extraction schema.

Design note
-----------
The LLM does ONE job: read meaning out of messy text (map a company's own label
to a canonical metric, find the value even when it lives in prose or a footnote,
and quote its source). It does NOT parse numbers. Number/unit normalization is
deterministic code (see normalize.py), because "what is 8.4M as a float" is a
checkable fact, not a judgment call. LLM for meaning, code for the checkable.
"""

# Model with strict JSON-schema structured outputs. Swap here to change provider/model.
# gpt-4o-mini chosen deliberately: cheap + fast, and provenance verification plus the
# ground-truth accuracy harness mean we never blindly trust it. A larger model is a
# one-line change here.
MODEL = "gpt-4o-mini-2024-07-18"

# Business-model cohorts. We only compare metrics WITHIN a cohort (a lender's
# "revenue" is interest income; a SaaS company's is subscription; a payments
# company's is bps on volume). Same label != same metric across cohorts.
COHORTS = ["saas", "lender", "payments_marketplace"]

# Canonical metric registry.
#   unit_type drives deterministic normalization (normalize.py).
#   cohort = "core" means it is comparable across every company.
CANONICAL_METRICS = {
    # ---- Universal core (meaningful for every company) ----
    "recognized_revenue": {
        "display": "Recognized Revenue",
        "cohort": "core",
        "unit_type": "currency",
        "definition": "Total revenue recognized in the quarter. Use the TOTAL line "
                      "(e.g. 'Total Recognized Revenue' 9.3M), never a single component "
                      "(e.g. transaction-only 8.6M). For a lender this is interest+fee income; "
                      "for payments it is net/take-rate revenue, NOT total payment volume (TPV).",
    },
    "gross_margin": {
        "display": "Gross Margin",
        "cohort": "core",
        "unit_type": "percent",
        "definition": "Gross margin %. Definition differs by business model (lender = net "
                      "interest over cost of funds); carry the raw label so the difference is visible.",
    },
    "headcount": {
        "display": "Headcount",
        "cohort": "core",
        "unit_type": "count",
        "definition": "Total full-time employees / FTE at period end. Often only stated in prose "
                      "(e.g. 'ended the quarter at 199 employees').",
    },
    # ---- SaaS cohort ----
    "arr": {
        "display": "ARR",
        "cohort": "saas",
        "unit_type": "currency",
        "definition": "Annual Recurring Revenue, for SUBSCRIPTION SaaS only. Flavors: 'ARR', "
                      "'End-of-Period ARR', 'Contracted ARR', 'Annual Recurring Revenue', "
                      "'Subscription ARR'. NEVER map a lender's 'Total Loan Book', a balance-sheet "
                      "stock, or any non-recurring-revenue figure to ARR.",
    },
    "nrr": {
        "display": "Net Revenue Retention",
        "cohort": "saas",
        "unit_type": "percent",
        "definition": "Net Revenue Retention (LTM). Same metric as 'Net Dollar Retention', 'NRR', "
                      "and 'Net Pound Retention (NPR)' when the document's own footnote equates them.",
    },
    "gross_revenue_retention": {
        "display": "Gross Revenue Retention",
        "cohort": "saas",
        "unit_type": "percent",
        "definition": "Gross Revenue Retention (LTM), excludes expansion. Distinct from NRR; do NOT "
                      "fold into NRR.",
    },
    "logo_churn": {
        "display": "Logo Churn",
        "cohort": "saas",
        "unit_type": "percent",
        "definition": "Logo / customer churn rate (LTM or annualized).",
    },
    "cash": {
        "display": "Cash",
        "cohort": "core",
        "unit_type": "currency",
        "definition": "Cash (and equivalents) at period end. If a doc separates restricted vs "
                      "available, prefer the headline cash balance and note any caveat.",
    },
    "net_burn": {
        "display": "Net Burn (mo)",
        "cohort": "core",
        "unit_type": "currency",
        "definition": "Net cash burn. CRITICAL: capture period_basis. Most report MONTHLY net burn; "
                      "ConstructIQ reports QUARTERLY net burn. The basis must be preserved or a "
                      "comparison is ~3x wrong.",
    },
    "cash_runway_months": {
        "display": "Cash Runway (months)",
        "cohort": "saas",
        "unit_type": "months",
        "definition": "Cash runway in months, where stated (e.g. '~30 months').",
    },
    # ---- Lender cohort ----
    "net_interest_margin": {
        "display": "Net Interest Margin",
        "cohort": "lender",
        "unit_type": "percent",
        "definition": "Net interest margin (lender).",
    },
    "total_loan_book": {
        "display": "Total Loan Book (gross)",
        "cohort": "lender",
        "unit_type": "currency",
        "definition": "Gross loan book outstanding (lender).",
    },
    "charge_off_rate": {
        "display": "Net Charge-off / Credit Loss Rate",
        "cohort": "lender",
        "unit_type": "percent",
        "definition": "Net charge-off rate (LTM). The same metric is labeled 'Credit Loss Rate' in "
                      "some quarters; the document footnotes state the equivalence.",
    },
    "provision_coverage_ratio": {
        "display": "Provision Coverage Ratio",
        "cohort": "lender",
        "unit_type": "ratio_x",
        "definition": "Loan loss reserves as a multiple of LTM net charge-offs (e.g. 2.4x).",
    },
    # ---- Payments / Marketplace cohort ----
    "tpv": {
        "display": "Total Payment Volume (TPV)",
        "cohort": "payments_marketplace",
        "unit_type": "currency",
        "definition": "Gross payment/transaction volume processed. NOT revenue (an explicit footnote "
                      "says so). Do not map TPV to recognized_revenue.",
    },
    "take_rate": {
        "display": "Take Rate",
        "cohort": "payments_marketplace",
        "unit_type": "percent",
        "definition": "Effective take rate. May be a percent (11.2%) or basis points (43 bps); "
                      "preserve the unit.",
    },
}

# Which canonical metrics belong to each cohort's display block (in order).
CORE_METRICS = [k for k, v in CANONICAL_METRICS.items() if v["cohort"] == "core"]
COHORT_METRICS = {
    c: [k for k, v in CANONICAL_METRICS.items() if v["cohort"] == c] for c in COHORTS
}

_METRIC_KEYS = list(CANONICAL_METRICS.keys())

# ---------------------------------------------------------------------------
# OpenAI strict structured-output schema for ONE document's extraction.
# Every property is required and additionalProperties is false (strict mode).
# ---------------------------------------------------------------------------
EXTRACTION_SCHEMA = {
    "name": "portfolio_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["company_name", "business_model", "reporting_period",
                     "reporting_currency", "metrics"],
        "properties": {
            "company_name": {"type": "string", "description": "Company name as printed."},
            "business_model": {
                "type": "string",
                "enum": COHORTS + ["other"],
                "description": "saas = subscription software; lender = specialty finance/credit; "
                               "payments_marketplace = payment processing or transaction marketplace.",
            },
            "reporting_period": {"type": "string", "description": "Normalized period, e.g. 'Q2 2025'."},
            "reporting_currency": {
                "type": "string",
                "enum": ["USD", "GBP", "EUR", "other"],
                "description": "Document reporting currency. Bare numbers (no symbol) default to the "
                               "document's stated currency; USD if unstated.",
            },
            "metrics": {
                "type": "array",
                "description": "One entry per canonical metric found in THIS document for its "
                               "reporting period. Omit metrics not present (do not invent).",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["canonical_metric", "raw_label", "value_raw", "period",
                                 "period_basis", "source_quote", "page", "source_type",
                                 "match_type", "note"],
                    "properties": {
                        "canonical_metric": {"type": "string", "enum": _METRIC_KEYS},
                        "raw_label": {"type": "string", "description": "Label exactly as printed."},
                        "value_raw": {"type": "string",
                                      "description": "Value EXACTLY as printed: keep $/%, M/k/B, "
                                                     "parentheses for negatives, bps, x. Do not convert."},
                        "period": {"type": "string",
                                   "description": "Which period this value is for. On side-by-side "
                                                  "columns (e.g. 'Metric Q2 2025 Q1 2025') pick the "
                                                  "CURRENT reporting period's value."},
                        "period_basis": {"type": "string",
                                         "enum": ["monthly", "quarterly", "ltm", "annual",
                                                  "point_in_time", "unknown"]},
                        "source_quote": {"type": "string",
                                         "description": "Verbatim line or sentence from the document "
                                                        "containing this value. Must be copied exactly."},
                        "page": {"type": "integer", "description": "1-based page number."},
                        "source_type": {"type": "string",
                                        "enum": ["table", "prose", "footnote", "derived"]},
                        "match_type": {"type": "string",
                                       "enum": ["exact", "alias", "renamed_per_footnote", "inferred"],
                                       "description": "exact = label matches canonical; alias = synonym; "
                                                      "renamed_per_footnote = equated via a footnote; "
                                                      "inferred = read from prose."},
                        "note": {"type": "string",
                                 "description": "Optional caveat (e.g. 'transaction component only'); "
                                                "empty string if none."},
                    },
                },
            },
        },
    },
}

SYSTEM_PROMPT = """You extract a fixed set of canonical financial/operating metrics from a single \
portfolio-company quarterly report.

Rules:
- Only extract the canonical metrics defined below; map the company's own label to the right one.
- A metric may appear in a table, in prose ("ended the quarter at 199 employees" = headcount), or in a \
footnote. Extract from wherever it is, and set source_type accordingly.
- The SAME metric is often relabeled across companies or quarters; documents usually footnote the \
equivalence (e.g. "Net Charge-off Rate ... equivalent to Credit Loss Rate"). When a footnote equates \
labels, map to the canonical metric and set match_type="renamed_per_footnote".
- For revenue, always prefer the TOTAL recognized line over a single component. Never map Total Payment \
Volume (TPV) to revenue.
- On side-by-side period columns, take the CURRENT reporting period's value.
- Copy value_raw EXACTLY as printed (keep $, %, M/k/B, parentheses for negatives, bps, x). Do NOT do math.
- source_quote MUST be copied verbatim from the document and MUST contain the value. If you cannot find a \
real quote, do not emit the metric.
- Do not invent or estimate values. If a metric is absent, omit it.
- Extract EVERY canonical metric that is present, including business-model-specific ones \
(Total Payment Volume / TPV and Take Rate for payments companies; Total Loan Book, Net Interest \
Margin, Charge-off Rate, Provision Coverage for lenders). Do not stop at the common SaaS metrics.
- Map each label to the SINGLE best canonical metric and never place a metric on the wrong business \
model (e.g. a lender has Loan Book and NIM, NOT ARR or NRR).

Canonical metrics:
"""


def build_system_prompt() -> str:
    lines = [SYSTEM_PROMPT]
    for key, meta in CANONICAL_METRICS.items():
        lines.append(f"- {key} ({meta['display']}): {meta['definition']}")
    return "\n".join(lines)
