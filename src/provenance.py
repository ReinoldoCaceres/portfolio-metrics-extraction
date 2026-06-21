"""
Lightweight provenance verification.

The LLM is also the thing that could hallucinate, so we don't take its word that a
source_quote is real: we deterministically check the quote actually appears on the
cited page, and that the value's digits appear inside the quote. This is a Ctrl-F,
not a second model call: a string match is ground truth and can't itself hallucinate.

It is intentionally a soft flag (not fail-closed): pdfplumber whitespace/wrapping can
make a literal quote drift slightly, so we record a status per value rather than drop
data. The strict, fail-closed version is named in the README as a next step.
"""
from __future__ import annotations

import re


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _digits(s: str) -> str:
    return re.sub(r"[^\d]", "", s)


def verify(source_quote: str, page: int, pages: list[str], value_raw: str) -> str:
    """Return one of: verified | quote_not_found | value_not_in_quote | page_out_of_range."""
    if page < 1 or page > len(pages):
        return "page_out_of_range"
    page_text = _norm(pages[page - 1])
    q = _norm(source_quote)
    if q and q in page_text:
        # the core digits of the value should appear inside the quote
        vd = _digits(value_raw)
        if vd and vd not in _digits(source_quote):
            return "value_not_in_quote"
        return "verified"
    return "quote_not_found"
