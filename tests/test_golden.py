"""Golden-fixture extraction harness — the QA backbone of the project.

Each fixture is tests/fixtures/<doc_id>/ with raw.pdf + expected.json. This test
runs the extractor over raw.pdf and diffs the result against expected.json.

Extraction is stubbed this phase, so every case xfails on NotImplementedError.
When the real extractor lands:
  1. point EXTRACTOR at it,
  2. delete the @pytest.mark.xfail marker.
The strict xfail means a passing case will FAIL until the marker is removed —
a forcing function so the harness can never silently rot into a no-op.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from semianalyst.extract import NotImplementedExtractor, PromptVersion
from semianalyst.store import models

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Swap for the real extractor when extraction lands.
EXTRACTOR = NotImplementedExtractor()


def _cases() -> list[Path]:
    if not FIXTURES_DIR.exists():
        return []
    return sorted(
        p for p in FIXTURES_DIR.iterdir()
        if p.is_dir() and (p / "raw.pdf").exists() and (p / "expected.json").exists()
    )


def _document_for(case_dir: Path, raw: bytes) -> models.Document:
    """A minimal Document derived from fixture metadata, as ingest would supply."""
    return models.Document(
        doc_id=case_dir.name,
        title=case_dir.name,
        publisher="TSMC",
        doc_type=models.DocType.foundry_announcement,
        source_tier=models.SourceTier.foundry,
        url=f"https://example.test/{case_dir.name}",
        file_sha256=hashlib.sha256(raw).hexdigest(),
        ingest_date=dt.date(2026, 1, 1),
    )


def _strip_meta(expected: dict) -> dict:
    """Drop documentation-only keys (prefixed with '_') from expected.json."""
    return {k: v for k, v in expected.items() if not k.startswith("_")}


@pytest.mark.xfail(
    raises=NotImplementedError,
    strict=True,
    reason="extract/ is a stub this phase; harness activates when extraction lands",
)
@pytest.mark.parametrize("case_dir", _cases(), ids=lambda p: p.name)
def test_golden_extraction(case_dir: Path):
    raw = (case_dir / "raw.pdf").read_bytes()
    expected = _strip_meta(json.loads((case_dir / "expected.json").read_text()))
    prompt = PromptVersion.load("extract_foundry_v1")

    result = EXTRACTOR.extract(raw, _document_for(case_dir, raw), prompt)

    assert result.model_dump(mode="json") == expected
