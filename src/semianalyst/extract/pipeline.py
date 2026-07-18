"""Extract orchestration — the library entry point behind `semianalyst extract`.

Stubbed this phase: raises NotImplementedError. When implemented it will read raw
docs from the store's ingested set, run the configured Extractor + PromptVersion,
and persist the resulting entities/claims through store.db.
"""

from __future__ import annotations

from ..config import Config, load_config


def run_extract(config: Config | None = None) -> None:
    config = config or load_config()  # noqa: F841 — validates config loads even in the stub
    raise NotImplementedError(
        "Extraction is not implemented yet (structure-only phase). "
        "The golden-fixture harness in tests/ is built and xfails until this lands."
    )
