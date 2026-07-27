# pragmatist-shipper — WS-1 "extract wiring" precommit review

**Verdict: APPROVE**

The DoD is fully met, the diff is mostly disciplined about scope, and nothing I
found rises to a blocker — this is shippable as-is. Two findings are simplify-if-
you're-in-there nits, not conditions.

---

## Finding 1 — `_ansi_safe`'s three regexes are two regexes too many

`cli.py` lines 41-50:

```python
_ANSI_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_ANSI_CSI = re.compile(r"\x1b[@-_][0-?]*[ -/]*[@-~]")
_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f]")

def _ansi_safe(text: str) -> str:
    text = _ANSI_OSC.sub("", text)
    text = _ANSI_CSI.sub("", text)
    return _CTRL.sub("", text)
```

`_CTRL` matches every byte in `\x00-\x1f` and `\x7f-\x9f` — which already includes
`ESC` (`\x1b`) and `BEL` (`\x07`), the two bytes that make any ANSI/OSC/CSI
sequence *live*. Run `_CTRL.sub("", text)` alone on the hostile fixture in the
test and you get `"N2[31mHACK[0m]0;pwned speed"` — no `ESC`, no `BEL`, nothing a
terminal will interpret as an escape. The stated goal in the docstring
("Neutralize terminal escape sequences") is fully satisfied by the one-line
catch-all. `_ANSI_OSC` and `_ANSI_CSI` add two compiled patterns and a
three-sentence comment explaining CSI-vs-OSC-vs-residual-control-byte ordering,
and the only thing they buy over the one-liner is stripping the now-inert
*printable* remnants (`[31m`, `0;pwned`) for cosmetic cleanliness.

The tell: `test_report_display_is_ansi_sanitized` asserts `"[31m" not in safe`
and `"0;pwned" not in safe` — that's a test written to match the implementation
that's there, not a requirement derived from a threat model (the security
property is "no ESC survives," full stop). Delete `_ANSI_OSC`/`_ANSI_CSI`,
collapse `_ansi_safe` to `return _CTRL.sub("", text)`, loosen those two
assertions to permit inert bracket-text, and the golden harness, `db init`, and
every other test in the new file still pass.

Not blocking — it works, it's inert, and three regexes in a CLI module isn't a
real cost. But it's the textbook shape of unneeded generality: solving a problem
("make hostile control sequences render as harmless") with three mechanisms when
one already fully solves it.

## Finding 2 — the sidecar's atomic tmp-write is store_raw's pattern, copy-pasted without fitting the new case

`ingest/base.py` `write_sidecar`:

```python
tmp = dest.with_suffix(".meta.partial")
tmp.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
tmp.replace(dest)
```

This mirrors `store_raw`'s crash-safety dance for writing potentially-large,
network-fetched blobs. A provenance sidecar here is a ~200-byte JSON file
written by an operator's local CLI invocation — the risk profile that justified
`store_raw`'s atomicity (a large write truncated mid-stream, silently mistaken
for complete because the content-addressed path already exists) doesn't
transfer. Nothing in the DoD, the golden harness, or the new E2E test exercises
a crash-mid-sidecar-write scenario, and even if one hit, `read_raw_docs` would
just throw a loud `JSONDecodeError` on the corrupt file next run — not silently
launder bad data. A plain `dest.write_text(...)` passes every test in this diff.

Corroborating evidence this was mechanically copied rather than deliberately
re-derived for the new shape: `dest` here is `<sha256>.meta.json`, and
`dest.with_suffix(".meta.partial")` replaces only the *last* suffix, producing
`<sha256>.meta.meta.partial` — not `<sha256>.meta.partial` as the naming
clearly intends. Harmless (the rename target is still correct), but it's a
sign the pattern was reused, not re-checked.

Not blocking — it's four lines, it doesn't hurt, and consistency with
`store_raw`'s style has some value. But it's engineering for a durability
problem operator-scale usage doesn't have.

## 1 risk others will miss

The CLI docstring carves out exactly one exception to "zero business logic":
terminal output encoding. That's a clean, narrow, well-reasoned exception as
written. But finding 1 shows the exception is already elastic in practice — the
"one thing" grew from "strip control bytes" to three regexes with a paragraph
justifying their ordering, in the same PR that introduced it. Nobody scoped
`_ansi_safe` down to what the property actually requires before shipping it.
Security-minded reviewers will wave this through because it's *more* defense,
not less — a pragmatist angle is the only one that will notice that the "thin
CLI, one narrow exception" boundary has no test or convention stopping it from
accreting further "just to be safe" logic the next time someone touches
`report()`. Worth a one-line convention (e.g. "sanitizers here must be minimal
— justify every additional pattern against the property it changes") before a
fourth regex shows up uncontested.
