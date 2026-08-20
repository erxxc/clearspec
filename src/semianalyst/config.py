"""Single configuration loader for semianalyst.

Every module reads configuration through `load_config()` — no module parses
config.toml on its own. Config is immutable once loaded.
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict

# Repo root = two parents up from this file (src/semianalyst/config.py -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.toml"


class ModelConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    prompt_version: str


class PathsConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    data_dir: Path
    raw_dir: Path
    db_path: Path

    def resolved(self, root: Path) -> "PathsConfig":
        """Return a copy with relative paths anchored to `root`."""

        def anchor(p: Path) -> Path:
            return p if p.is_absolute() else (root / p)

        return PathsConfig(
            data_dir=anchor(self.data_dir),
            raw_dir=anchor(self.raw_dir),
            db_path=anchor(self.db_path),
        )


class RateLimits(BaseModel):
    model_config = ConfigDict(frozen=True)
    requests_per_minute: int = 10
    max_concurrency: int = 2


class Source(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    url: str
    doc_type: str
    source_tier: int
    # Sidecar publisher; ingest falls back to `name` when omitted (WS-2b).
    publisher: str | None = None
    # Explicit document URLs to fetch — the WS-2b direct-URL scope. Discovering
    # documents from the index page at `url` is HTML-discovery work (WS-3).
    # Defaults keep parsing backward-compatible with pre-WS-2b config files.
    documents: tuple[str, ...] = ()


class Config(BaseModel):
    model_config = ConfigDict(frozen=True)
    model: ModelConfig
    paths: PathsConfig
    rate_limits: RateLimits
    sources: tuple[Source, ...]


def _load(path: Path) -> Config:
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    cfg = Config(
        model=ModelConfig(**raw["model"]),
        paths=PathsConfig(**raw["paths"]),
        rate_limits=RateLimits(**raw.get("rate_limits", {})),
        sources=tuple(Source(**s) for s in raw.get("sources", [])),
    )
    # Anchor relative paths to the config file's directory so the CLI works
    # regardless of the current working directory.
    return cfg.model_copy(update={"paths": cfg.paths.resolved(path.resolve().parent)})


@lru_cache(maxsize=1)
def load_config(path: Path | None = None) -> Config:
    """Load and cache the config. Pass an explicit path in tests."""
    return _load(path or DEFAULT_CONFIG_PATH)
