"""Extractor interface — raw document -> canonical schema records.

STUB (this phase): no LLM logic. When implemented, an Extractor takes raw bytes
plus the PromptVersion and returns entities + claims conforming to store.models,
enforcing the schema's normalization rules at extraction time:
  - normalize units (bandwidth->GB/s, power->W, density->MTr/mm², die->mm²),
  - keep relative claims as ratio + baseline ref; never store computed absolutes,
  - auto-tag completeness=marketing_only for sparsity+competitor claims unless the
    competitor number is also sparse,
  - resolve entity aliases BEFORE emitting claims (one entity per real thing).

The LLM call itself is provider-specific and out of scope this phase. When it is
written it should go through the official Anthropic SDK (the model name lives in
config), with the API key read from the environment — never committed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..store import models
from .prompts import PromptVersion


@dataclass(frozen=True)
class ExtractionResult:
    """What an Extractor returns for one raw document."""

    entities: list[models.Entity]
    claims: list[models.Claim]


class Extractor(Protocol):
    def extract(
        self,
        raw: bytes,
        document: models.Document,
        prompt: PromptVersion,
    ) -> ExtractionResult:
        ...


class NotImplementedExtractor(Extractor):
    """Placeholder used until the real LLM-backed extractor lands."""

    def extract(
        self,
        raw: bytes,
        document: models.Document,
        prompt: PromptVersion,
    ) -> ExtractionResult:
        raise NotImplementedError(
            "Extraction is not implemented yet (structure-only phase). "
            "The golden-fixture harness in tests/ is built and xfails until this lands."
        )
