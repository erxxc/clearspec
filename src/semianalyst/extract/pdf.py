"""PDF -> text, plus the whitespace-normalized grounding predicate.

`is_grounded` is the code-level hallucination control: a value survives only if
its cited quote appears in the extracted document text. Two deliberate choices,
recorded in the GATE-1 resolution:

  - **whitespace-normalized** on both sides — `pypdf` collapses/join line breaks
    and hyphenation unpredictably, so an exact match would over-reject genuinely
    grounded quotes. We normalize runs of whitespace to a single space.
  - **case-sensitive** — the model is instructed to quote verbatim; case-folding
    would let short coincidental tokens under-match.

Known residual (see resolution.md): `pypdf` extracts text regardless of
visibility, so "grounded" means "present in extracted text," NOT "visible to a
human." Hidden-layer text is a real exposure; revisit with a visibility-aware
parser. The injection fixture includes a hidden-text case to keep this visible.
"""

from __future__ import annotations

import io
import re

from pypdf import PdfReader

_WS = re.compile(r"\s+")


def pdf_to_text(raw: bytes) -> str:
    """Extract concatenated text from all pages of a PDF byte string."""
    reader = PdfReader(io.BytesIO(raw))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def normalize_ws(text: str) -> str:
    return _WS.sub(" ", text).strip()


def is_grounded(quote: str, source_text: str) -> bool:
    """True iff `quote` appears in `source_text` (whitespace-normalized, case-sensitive)."""
    return normalize_ws(quote) in normalize_ws(source_text)
