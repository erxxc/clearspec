"""PromptVersion loads versioned prompt artifacts with a provenance hash."""

from __future__ import annotations

import pytest

from semianalyst.extract import PromptVersion


def test_prompt_version_loads():
    pv = PromptVersion.load("extract_foundry_v1")
    assert pv.name == "extract_foundry_v1"
    assert "quote_span" in pv.text  # the grounding instruction is the prompt's core
    assert len(pv.sha256) == 64 and all(c in "0123456789abcdef" for c in pv.sha256)


def test_advisory_prompt_version_loads():
    pv = PromptVersion.load("extract_advisory_v1")
    assert pv.name == "extract_advisory_v1"
    assert "quote_span" in pv.text
    assert "GROUND EVERYTHING" in pv.text
    assert "source_record_kind" in pv.text
    assert "missing_range" in pv.text
    assert len(pv.sha256) == 64 and all(c in "0123456789abcdef" for c in pv.sha256)


def test_missing_prompt_raises():
    with pytest.raises(FileNotFoundError):
        PromptVersion.load("does_not_exist_v9")


def test_list_available_includes_v1():
    available = PromptVersion.list_available()
    assert "extract_foundry_v1" in available
    assert "extract_advisory_v1" in available
