"""Shared test fixtures + the --run-live gate for the ENFORCE anchor."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from semianalyst.config import Config, ModelConfig, PathsConfig, RateLimits

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def pytest_addoption(parser):
    parser.addoption(
        "--run-live", action="store_true", default=False,
        help="Run @live tests against the real Anthropic model (needs ANTHROPIC_API_KEY).",
    )
    parser.addoption(
        "--record", action="store_true", default=False,
        help="With --run-live, (re)record the llm_response.json replay artifacts.",
    )


def pytest_collection_modifyitems(config, items):
    """Skip @live tests unless --run-live AND ANTHROPIC_API_KEY are both present.
    This is the ENFORCE contract: `uv run pytest --run-live` (with a key) is the
    real gate; a plain `uv run pytest` never silently claims live coverage."""
    run_live = config.getoption("--run-live") and os.environ.get("ANTHROPIC_API_KEY")
    skip_live = pytest.mark.skip(reason=(
        "live test: pass --run-live and set ANTHROPIC_API_KEY"
        if not config.getoption("--run-live")
        else "live test: ANTHROPIC_API_KEY is not set"
    ))
    for item in items:
        if not run_live and "live" in item.keywords:
            item.add_marker(skip_live)


def pytest_sessionfinish(session, exitstatus):
    """CI (GitHub Actions sets CI=true) must not go green on skipped tests.

    Offline goldens skip locally when a recording is missing; that skip is a
    failure for CI readiness. Live tests are deselected with `-m "not live"`,
    so they are not skips. Local runs without CI=true are unchanged.
    """
    if os.environ.get("CI") != "true":
        return
    if exitstatus not in (0, pytest.ExitCode.OK):
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    skipped = [] if reporter is None else reporter.stats.get("skipped", [])
    if skipped:
        if reporter is not None:
            reporter.write_line("")
            reporter.write_sep(
                "=",
                "CI forbids skipped tests (missing recordings are a failure)",
                red=True,
            )
            for rep in skipped:
                reporter.write_line(str(getattr(rep, "longrepr", rep.nodeid)))
        session.exitstatus = int(pytest.ExitCode.TESTS_FAILED)


@pytest.fixture
def record(request) -> bool:
    return request.config.getoption("--record")


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
