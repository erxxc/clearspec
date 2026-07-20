"""extract — raw document -> grounded canonical records via a versioned prompt.

The model output is a PROPOSAL; extract/validate.py enforces grounding and the
schema's integrity rules before it becomes an ExtractionResult.
"""

from .base import (
    AnthropicExtractor,
    AnthropicModelClient,
    ModelClient,
    ReplayModelClient,
)
from .prompts import PromptVersion
from .validate import (
    ExtractionError,
    ExtractionResult,
    Rejection,
    build_result,
    validate_proposal,
)

__all__ = [
    "AnthropicExtractor",
    "AnthropicModelClient",
    "ModelClient",
    "ReplayModelClient",
    "PromptVersion",
    "ExtractionError",
    "ExtractionResult",
    "Rejection",
    "build_result",
    "validate_proposal",
]
