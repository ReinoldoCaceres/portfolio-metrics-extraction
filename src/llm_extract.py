"""
Per-document extraction via an LLM, with a committed cache for offline replay.

Two run modes:
  * replay (default): load the committed cache/*.json. No API key, no cost,
    fully deterministic, reproduces the exact numbers in the README.
  * extract (--extract): call the LLM live and refresh the cache.

The LLM is the only non-deterministic, billable step, so we persist its output
and rebuild everything downstream deterministically from the cache. In production
that same cache is the audit trail and the cost control.

The provider is behind a tiny interface (LLMClient). OpenAI today; swapping to
Azure/Bedrock/Anthropic is one class, not a rewrite.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from . import config
from .pdf_text import read_pages, document_text

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

CACHE_DIR = _ROOT / "cache"


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


class LLMClient:
    """Provider-agnostic structured-extraction interface."""

    def extract(self, system_prompt: str, doc_text: str) -> dict:
        raise NotImplementedError


class OpenAIClient(LLMClient):
    def __init__(self, model: str = config.MODEL):
        from openai import OpenAI

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY not set. Add it to .env to run --extract. "
                "(Default replay mode needs no key.)"
            )
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def extract(self, system_prompt: str, doc_text: str) -> dict:
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": doc_text},
            ],
            response_format={"type": "json_schema", "json_schema": config.EXTRACTION_SCHEMA},
        )
        return json.loads(resp.choices[0].message.content)


def _cache_path(pdf_path: Path) -> Path:
    return CACHE_DIR / f"{pdf_path.stem}.json"


def load_or_extract(pdf_path: Path, client: LLMClient | None, force: bool) -> dict:
    """
    Return a record: {pdf, model, text_hash, pages, extraction}.
    'pages' (cleaned page text) is cached too so the provenance check and the
    whole downstream run work offline without re-reading the PDF.
    """
    pages = read_pages(pdf_path)
    doc_text = document_text(pages)
    th = _text_hash(doc_text)
    cache_file = _cache_path(pdf_path)

    if not force and cache_file.exists():
        record = json.loads(cache_file.read_text(encoding="utf-8"))
        return record

    if client is None:
        raise RuntimeError(
            f"No cache for {pdf_path.name} and extraction is disabled. "
            f"Run with --extract to build the cache first."
        )

    extraction = client.extract(config.build_system_prompt(), doc_text)
    record = {
        "pdf": pdf_path.name,
        "model": getattr(client, "model", "unknown"),
        "text_hash": th,
        "pages": pages,
        "extraction": extraction,
    }
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return record


def extract_all(pdf_paths: list[Path], force: bool) -> list[dict]:
    client = OpenAIClient() if force else None
    records = []
    for p in pdf_paths:
        records.append(load_or_extract(p, client, force))
        print(f"  {'extracted' if force else 'cached  '}  {p.name}")
    return records
