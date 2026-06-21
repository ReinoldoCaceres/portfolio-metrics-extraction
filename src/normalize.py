"""
Deterministic value normalization. The LLM hands us value_raw EXACTLY as printed
("$8.4M", "($0.75M)", "78%", "2.4x", "43 bps", "~30 months"); here we turn that
into a number + canonical unit with pure code. No model judgment: parsing a
printed number is a checkable fact.

Conventions:
  currency  -> value in MILLIONS of the document's native currency (so $241k = 0.241,
               $3.42B = 3420, ($0.75M) = -0.75). Currency itself is tracked separately.
  percent   -> the percent number (78% -> 78.0); 'bps' values flagged as unit 'bps'.
  count     -> integer.
  ratio_x   -> the multiple (2.4x -> 2.4).
  months    -> the number of months.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Norm:
    value: float | None
    unit: str
    ok: bool


_NUM = r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?"


def _strip_sign(s: str) -> tuple[str, bool]:
    s = s.strip()
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1].strip()
    if s.startswith("+"):
        s = s[1:].strip()
    elif s.startswith("-"):
        neg, s = True, s[1:].strip()
    return s, neg


def _first_number(s: str) -> float | None:
    m = re.search(_NUM, s.replace(",", ""))
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def normalize_value(value_raw: str, unit_type: str) -> Norm:
    s, neg = _strip_sign(value_raw)
    sign = -1 if neg else 1

    if unit_type == "currency":
        body = s.replace("$", "").replace("£", "").replace("€", "").replace(",", "").strip()
        mult = 1.0  # default: already in millions
        low = body.lower()
        if low.endswith("b"):
            mult, body = 1000.0, body[:-1]
        elif low.endswith("m"):
            mult, body = 1.0, body[:-1]
        elif low.endswith("k"):
            mult, body = 0.001, body[:-1]
        num = _first_number(body)
        if num is None:
            return Norm(None, "M", False)
        return Norm(round(sign * num * mult, 4), "M", True)

    if unit_type == "percent":
        if "bps" in s.lower():
            num = _first_number(s.lower().replace("bps", ""))
            return Norm(sign * num, "bps", True) if num is not None else Norm(None, "bps", False)
        num = _first_number(s.replace("%", ""))
        return Norm(sign * num, "%", True) if num is not None else Norm(None, "%", False)

    if unit_type == "count":
        num = _first_number(s)
        return Norm(int(round(sign * num)), "count", True) if num is not None else Norm(None, "count", False)

    if unit_type == "ratio_x":
        num = _first_number(s.lower().replace("x", ""))
        return Norm(sign * num, "x", True) if num is not None else Norm(None, "x", False)

    if unit_type == "months":
        num = _first_number(s.replace("~", "").lower().replace("months", "").replace("month", ""))
        return Norm(sign * num, "months", True) if num is not None else Norm(None, "months", False)

    return Norm(None, "?", False)


_MONTH_TO_Q = {
    "jan": 1, "feb": 1, "mar": 1, "march": 1,
    "apr": 2, "may": 2, "jun": 2, "june": 2,
    "jul": 3, "aug": 3, "sep": 3, "sept": 3,
    "oct": 4, "nov": 4, "dec": 4,
}


def normalize_period(s: str) -> str:
    """Normalize varied period labels to 'Qn YYYY'.
    'Q2 2025' | 'Quarter ended June 30, 2025' | '30 June 2025' -> 'Q2 2025'."""
    if not s:
        return s
    t = s.strip()
    m = re.search(r"Q([1-4])\s*[- ]?\s*(20\d{2})", t, re.I)
    if m:
        return f"Q{m.group(1)} {m.group(2)}"
    ym = re.search(r"([A-Za-z]{3,9})\.?\s+\d{0,2},?\s*(20\d{2})", t)
    if not ym:
        ym = re.search(r"(20\d{2}).*?([A-Za-z]{3,9})", t)
        if ym:
            year, mon = ym.group(1), ym.group(2)
            q = _MONTH_TO_Q.get(mon[:4].lower()) or _MONTH_TO_Q.get(mon[:3].lower())
            return f"Q{q} {year}" if q else t
    if ym:
        mon, year = ym.group(1), ym.group(2)
        q = _MONTH_TO_Q.get(mon[:4].lower()) or _MONTH_TO_Q.get(mon[:3].lower())
        return f"Q{q} {year}" if q else t
    return t


def monthly_from_basis(value: float | None, unit: str, period_basis: str) -> float | None:
    """Net burn comparability: express a quarterly figure on a monthly basis so a
    quarterly reporter (ConstructIQ) is never compared ~3x wrong against monthly ones."""
    if value is None or unit != "M":
        return value
    if period_basis == "quarterly":
        return round(value / 3.0, 4)
    return value
