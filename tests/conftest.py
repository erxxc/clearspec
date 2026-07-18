"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from semianalyst.config import Config, ModelConfig, PathsConfig, RateLimits

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def fixture_cases() -> list[Path]:
    """Every golden-fixture directory that has an expected.json."""
    if not FIXTURES_DIR.exists():
        return []
    return sorted(
        p for p in FIXTURES_DIR.iterdir()
        if p.is_dir() and (p / "expected.json").exists()
    )


@pytest.fixture
def tmp_config(tmp_path: Path) -> Config:
    """A Config with all paths anchored inside a temp dir — never touches real data/."""
    return Config(
        model=ModelConfig(name="test-model", prompt_version="extract_foundry_v1"),
        paths=PathsConfig(
            data_dir=tmp_path,
            raw_dir=tmp_path / "raw",
            db_path=tmp_path / "semianalyst.db",
        ),
        rate_limits=RateLimits(),
        sources=(),
    )
