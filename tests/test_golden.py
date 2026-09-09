"""Golden extraction harness.

Under the ENFORCE posture the REAL model is the anchor:
  - `test_golden_live` (@live) runs the actual Anthropic extractor against raw.pdf
    and asserts the grounded result equals expected.json. `--record` also writes
    the raw proposal to llm_response.json (stamped with prompt sha256 + model).
  - `test_golden_offline_replay` replays that recorded proposal through the real
    validation pipeline offline. It SKIPS until a recording exists — a plain
    `uv run pytest` never fabricates model output or claims live coverage.

The validation pipeline itself is covered deterministically and offline by
tests/test_validate.py (including the full golden proposal -> expected.json path).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path

import pytest

from semianalyst.config import load_config
from semianalyst.extract import (
    AnthropicExtractor,
    AnthropicModelClient,
    PromptVersion,
    ReplayModelClient,
    build_result,
)
from semianalyst.extract.pdf import pdf_to_text
from semianalyst.store import models

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GOLDEN_DIRS = [FIXTURES_DIR / "tsmc_n2_2025"]
PROMPT_NAME = "extract_foundry_v1"


def _document_for(case_dir: Path, raw: bytes) -> models.Document:
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


def _expected(case_dir: Path) -> dict:
    data = json.loads((case_dir / "expected.json").read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


@pytest.mark.parametrize("case_dir", GOLDEN_DIRS, ids=lambda p: p.name)
def test_golden_offline_replay(case_dir: Path):
    recording = case_dir / "llm_response.json"
    if not recording.exists():
        reason = (
            f"no recorded llm_response.json for {case_dir.name} — "
            "run `uv run pytest --run-live --record` with ANTHROPIC_API_KEY"
        )
        # Local: skip (never fabricate). CI: fail — a missing recording is not green.
        if os.environ.get("CI"):
            pytest.fail(reason)
        pytest.skip(reason)
    prompt = PromptVersion.load(PROMPT_NAME)
    cfg = load_config()
    recorded = json.loads(recording.read_text())
    stamp = recorded.get("_recorded_against", {})
    # Provenance tripwire: a recording made against a different prompt or model is stale.
    assert stamp.get("prompt_sha256") == prompt.sha256, "replay recorded against a different prompt"
    assert stamp.get("model") == cfg.model.name, "replay recorded against a different model"

    raw = (case_dir / "raw.pdf").read_bytes()
    extractor = AnthropicExtractor(ReplayModelClient(json.dumps(recorded)))
    result = extractor.extract(raw, _document_for(case_dir, raw), prompt)
    assert result.model_dump(mode="json") == _expected(case_dir)


@pytest.mark.live
@pytest.mark.parametrize("case_dir", GOLDEN_DIRS, ids=lambda p: p.name)
def test_golden_live(case_dir: Path, record: bool):
    prompt = PromptVersion.load(PROMPT_NAME)
    cfg = load_config()
    raw = (case_dir / "raw.pdf").read_bytes()
    document = _document_for(case_dir, raw)
    source = pdf_to_text(raw)

    client = AnthropicModelClient(cfg.model.name)
    proposal = json.loads(client.complete(prompt.text, source))
    for claim in proposal.get("claims", []):
        claim["doc_id"] = document.doc_id

    if record:
        recorded = dict(proposal)
        recorded["_recorded_against"] = {"prompt_sha256": prompt.sha256, "model": cfg.model.name}
        (case_dir / "llm_response.json").write_text(json.dumps(recorded, indent=2) + "\n")

    result = build_result(proposal, source)
    assert result.model_dump(mode="json") == _expected(case_dir)
