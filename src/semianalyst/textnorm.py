"""Shared text-normalization primitives for attacker-influenceable strings.

`fold` is THE case/whitespace folding used wherever two surface forms are asked
"are you the same value?" — validate's entity dedup key, reconcile's identity
compare and alias-collision sets, analyze's group key and H1 publisher floor.
One implementation, because three drifting copies shipped three different
answers (`.lower()` / bare `.casefold()` / collapse+strip+casefold) and the
weakest one decided refusal behavior (2026-08-18 precommit gate, schema-purist
risk + devils-advocate §4d).

`CTRL_CLASS` is the shared C0/DEL character CLASS only — deliberately NOT a
shared function: the model layer REJECTS control bytes (pydantic `_NO_CTRL`
pattern → fail-soft item drop), while store/pipeline SCRUB-and-continue on
values that must degrade gracefully (conflict reprs, error strings). Sharing a
function would invite collapsing reject into scrub — a security regression
wearing a cleanup's clothes (devils-advocate §4b). `cli._ansi_safe` stays a
separate display-edge concern by design (CLAUDE.md: a web UI would HTML-escape
instead).

Unicode confusables/homoglyph folding (Latin/Cyrillic/Greek lookalikes defeat
fold-based comparison in G3/H1/J simultaneously) is DEFERRED with a named
trigger — see CLAUDE.md.
"""

from __future__ import annotations

import re

CTRL_CLASS = r"[\x00-\x1f\x7f]"

_WS = re.compile(r"\s+")


def fold(s: str) -> str:
    """Whitespace-collapse + strip + casefold: a casing/spacing variant is one
    value. Comparison keys only — never mutates stored data."""
    return _WS.sub(" ", s).strip().casefold()
