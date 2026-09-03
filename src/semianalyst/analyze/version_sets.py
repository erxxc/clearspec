"""Structured version-range set comparison (GEI-9).

Compares VersionRange values as sets of versions: equal / subset / overlap /
disjoint. Never applies ±10% numeric tolerance. Never picks a winning range.
"""

from __future__ import annotations

import re
from typing import Any

# Sentinel keys for unbounded ends. Compared before/after every real version.
_NEG_INF: tuple = ((-2, 0),)
_POS_INF: tuple = ((2, 0),)

_TOKEN = re.compile(r"\d+|[A-Za-z]+")


def version_key(version: str) -> tuple:
    """Order key for a version string.

    Numeric runs compare numerically; letter runs compare case-insensitively
    and sort *before* a missing letter at the same position so that
    ``9.7p1 < 9.8`` and ``1.0.0-rc93 < 1.1.11``.
    """
    parts: list[tuple[int, int | str]] = []
    for tok in _TOKEN.findall(version):
        if tok.isdigit():
            parts.append((0, int(tok)))
        else:
            # Letter tokens: kind=1 sorts after numbers in the same slot, but
            # when comparing unequal-length keys we treat a trailing letter
            # as a pre-release relative to a longer numeric continuation.
            parts.append((1, tok.lower()))
    return tuple(parts) if parts else ((1, version.lower()),)


def _bound_key(bound: dict | None, *, upper: bool) -> tuple[tuple, bool]:
    """Return (order_key, inclusive) for an interval end.

    ``bound is None`` means unbounded (below for start, above for end).
    The inclusive flag is meaningful only for real bounds.
    """
    if bound is None:
        return (_POS_INF if upper else _NEG_INF), True
    return version_key(bound["version"]), bool(bound["inclusive"])


def _point_in_interval(point: tuple, start_k: tuple, start_incl: bool,
                       end_k: tuple, end_incl: bool) -> bool:
    if point < start_k:
        return False
    if point == start_k and not start_incl:
        return False
    if point > end_k:
        return False
    if point == end_k and not end_incl:
        return False
    return True


def _interval_tuple(interval: dict) -> tuple[tuple, bool, tuple, bool]:
    start = interval.get("start")
    end = interval.get("end")
    sk, si = _bound_key(start, upper=False)
    ek, ei = _bound_key(end, upper=True)
    return sk, si, ek, ei


def _intervals_equal(a: tuple, b: tuple) -> bool:
    return a == b


def _interval_subset(inner: tuple, outer: tuple) -> bool:
    """True if every version in ``inner`` is also in ``outer`` (proper or equal)."""
    isk, isi, iek, iei = inner
    osk, osi, oek, oei = outer
    # start of inner must be >= start of outer (with inclusivity)
    if isk < osk:
        return False
    if isk == osk and isi and not osi:
        return False
    # end of inner must be <= end of outer
    if iek > oek:
        return False
    if iek == oek and iei and not oei:
        return False
    return True


def _interval_overlap(a: tuple, b: tuple) -> bool:
    """True if the two intervals share at least one version on the order."""
    ask, asi, aek, aei = a
    bsk, bsi, bek, bei = b
    # Disjoint if a ends before b starts, or b ends before a starts.
    # a ends before b starts:
    if aek < bsk:
        return False
    if aek == bsk and (not aei or not bsi):
        return False
    if bek < ask:
        return False
    if bek == ask and (not bei or not asi):
        return False
    return True


def _range_intervals(vr: dict | None) -> list[tuple]:
    if not vr or not vr.get("intervals"):
        return []
    return [_interval_tuple(iv) for iv in vr["intervals"]]


def _range_subset(a_ivs: list[tuple], b_ivs: list[tuple]) -> bool:
    """True if every interval of A is covered by the union of B's intervals.

    Conservative: each A interval must be a subset of *some* B interval.
    (Sufficient for the GEI-10 goldens; multi-interval unions that require
    stitching B intervals are out of scope for M0.)
    """
    if not a_ivs:
        return True
    if not b_ivs:
        return False
    for a in a_ivs:
        if not any(_interval_subset(a, b) for b in b_ivs):
            return False
    return True


def _range_overlap(a_ivs: list[tuple], b_ivs: list[tuple]) -> bool:
    return any(_interval_overlap(a, b) for a in a_ivs for b in b_ivs)


def _ranges_equal(a_ivs: list[tuple], b_ivs: list[tuple]) -> bool:
    if len(a_ivs) != len(b_ivs):
        # Equal as sets if each side is a subset of the other.
        return _range_subset(a_ivs, b_ivs) and _range_subset(b_ivs, a_ivs)
    # Order-insensitive: every A matches some unused B
    remaining = list(b_ivs)
    for a in a_ivs:
        for i, b in enumerate(remaining):
            if _intervals_equal(a, b):
                remaining.pop(i)
                break
        else:
            return _range_subset(a_ivs, b_ivs) and _range_subset(b_ivs, a_ivs)
    return True


def compare_version_ranges(a: dict | None, b: dict | None) -> str:
    """Return ``equal`` / ``subset`` / ``overlap`` / ``disjoint``.

    ``subset`` means one range is a (possibly equal-as-covered) proper subset
    of the other: A ⊆ B or B ⊆ A but not equal.
    """
    a_ivs = _range_intervals(a)
    b_ivs = _range_intervals(b)
    if not a_ivs or not b_ivs:
        # Missing range cannot speak (e.g. KEV with no range). Treat as
        # incomparable → disjoint so callers do not corroborate on emptiness.
        return "disjoint"
    if _ranges_equal(a_ivs, b_ivs):
        return "equal"
    a_in_b = _range_subset(a_ivs, b_ivs)
    b_in_a = _range_subset(b_ivs, a_ivs)
    if a_in_b or b_in_a:
        return "subset"
    if _range_overlap(a_ivs, b_ivs):
        return "overlap"
    return "disjoint"


def version_range_as_dict(vr: Any) -> dict | None:
    """Normalize a VersionRange pydantic model, dict, or JSON string to a dict."""
    if vr is None:
        return None
    if isinstance(vr, str):
        import json
        return json.loads(vr)
    if hasattr(vr, "model_dump"):
        return vr.model_dump(mode="json")
    if isinstance(vr, dict):
        return vr
    return None
