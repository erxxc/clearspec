"""PromptVersion — prompts are versioned artifacts, loaded from prompts/.

Prompts are never edited in place: a change means a new file (extract_foundry_v2.md),
so every extraction run can be tied to the exact prompt bytes that produced it.
`PromptVersion.sha256` is that provenance handle — record it (alongside the model
name) in Document.extraction_model when a run happens, so re-runs are reproducible.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from ..config import REPO_ROOT

PROMPTS_DIR = REPO_ROOT / "prompts"


@dataclass(frozen=True)
class PromptVersion:
    name: str          # e.g. "extract_foundry_v1"
    text: str
    sha256: str        # hash of the prompt bytes — provenance for re-runs

    @classmethod
    def load(cls, name: str, prompts_dir: Path | None = None) -> "PromptVersion":
        directory = prompts_dir or PROMPTS_DIR
        path = directory / f"{name}.md"
        if not path.exists():
            available = ", ".join(sorted(p.stem for p in directory.glob("*.md"))) or "(none)"
            raise FileNotFoundError(
                f"Prompt '{name}' not found in {directory}. Available: {available}"
            )
        content = path.read_bytes()
        return cls(
            name=name,
            text=content.decode("utf-8"),
            sha256=hashlib.sha256(content).hexdigest(),
        )

    @staticmethod
    def list_available(prompts_dir: Path | None = None) -> list[str]:
        directory = prompts_dir or PROMPTS_DIR
        return sorted(p.stem for p in directory.glob("*.md"))
