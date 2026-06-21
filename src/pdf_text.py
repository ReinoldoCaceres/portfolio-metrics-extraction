"""
PDF -> clean per-page text, using pdfplumber.

Why pdfplumber text (not a layout/vision parser): these reports are born-digital,
two-column "Metric | Value" tables plus prose. The hard part here is SEMANTIC
(footnoted renames, prose-only metrics, a rebrand), not visual layout, so plain
text over the whole document is the right, lightweight tool. Scanned-PDF OCR and
layout-aware table parsing are noted as next steps, not needed for this corpus.
"""
from __future__ import annotations

import re
from pathlib import Path

import pdfplumber

# pdfplumber renders some glyphs as artifacts; clean the common ones so neither
# the LLM nor the provenance substring-check trips on them.
_ARTIFACTS = {
    "(cid:127)": "-",   # bullet
    "–": "-",       # en dash
    "—": "-",       # em dash
    "ﬁ": "fi",
    "ﬂ": "fl",
}


def clean(text: str) -> str:
    for bad, good in _ARTIFACTS.items():
        text = text.replace(bad, good)
    # collapse runs of spaces/tabs but keep newlines (line structure helps the LLM)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def read_pages(pdf_path: str | Path) -> list[str]:
    """Return cleaned text for each page (1-based index in the returned list order)."""
    pages: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            pages.append(clean(page.extract_text() or ""))
    return pages


def document_text(pages: list[str]) -> str:
    """Concatenate pages with explicit page markers so the model can cite a page."""
    return "\n\n".join(f"--- PAGE {i + 1} ---\n{p}" for i, p in enumerate(pages))


def list_pdfs(data_dir: str | Path) -> list[Path]:
    return sorted(Path(data_dir).glob("*.pdf"))
