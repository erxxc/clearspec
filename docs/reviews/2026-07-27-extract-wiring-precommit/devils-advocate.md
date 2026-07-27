# devils-advocate — WS-1 extract-wiring precommit

**Role:** attack the agreement, name the sharpest conflict, surface the question
the group avoided. I do not cast a verdict; I make the human's adjudication
honest. Verdicts as returned: injection-attacker = CONDITIONAL, schema-purist =
BLOCK, pragmatist-shipper = APPROVE.

I verified every mechanical claim below against the code (`_ansi_safe` byte
behavior, `insert_document`'s plain INSERT, the `DOC_OPEN`/`DOC_CLOSE` model
call). I did not trust the reviewers on anything load-bearing.

---

## 1. The sharpest unresolved conflict: schema-purist BLOCK vs pragmatist APPROVE on the silent-revision skip

This is the real fault line, and it is a clean BLOCK-vs-APPROVE on **one** issue:
a sidecar whose `doc_id` is already in the store is bucketed `skipped` purely by
`doc_id`, **never** comparing `file_sha256` (`pipeline.py:60-63`). Schema-purist
calls this the most-severe defect and the basis for BLOCK. Pragmatist never
engages it and APPROVEs. That is not a difference of taste; it is the two of them
looking at the same three lines and one calling them a shipping blocker while the
other doesn't see them.

I confirmed the scenario is reachable and self-inflicting: re-ingesting a
*corrected* PDF under the same (stable, per-ROADMAP) `doc_id` writes a second blob
+ sidecar (new sha256), both survive on disk, and on the next `extract` the
revised doc is classified `skipped` — the CLI prints only `skipped: {len}`
(`cli.py:78`), so it is **byte-for-byte indistinguishable** from the honest
"already extracted, nothing to do." The revision is dropped with no signal. This
is not adversarial; it is the exact re-ingest workflow ROADMAP advertises
(`doc_id` is the stable handle).

**What each side actually costs — do not average these:**

- **Schema-purist's BLOCK costs**: you hold the slice to fix a defect that (a) is
  only reachable by a *benign operator re-ingest*, and (b) is recoverable by hand
  (drop the row, re-extract, or pick a new `doc_id`). If "BLOCK" hardens into "add
  sha256 comparison + re-extract logic now," you are pulling a chunk of
  revision-handling design into a slice whose entire selling point is *minimal,
  Class-A-free wiring*.
- **Pragmatist's APPROVE costs**: you ship a tool whose stated purpose is
  claim **integrity and provenance**, and the first time an operator loads a
  correction it **silently serves stale claims** while reporting success. For a
  provenance tool, silently returning superseded numbers after an explicit
  re-ingest is not a peripheral nit — it is a violation of the one property the
  product exists to guarantee. CLAUDE.md names sha256 as *"how silent revisions
  of the same URL are detected"*; this diff makes that guarantee **dead on
  arrival at the extract layer**, and does so untested (the E2E suite only
  exercises identical-bytes idempotency).

**The dishonest middle to refuse:** "note it in ROADMAP and ship." That averages
BLOCK and APPROVE into a TODO and pretends the guarantee still holds. The two
honest resolutions are (a) make the skip compare `file_sha256` and either
re-extract or **loudly refuse** the same-doc_id/new-bytes case, or (b) explicitly
state in CLAUDE.md/ROADMAP that same-`doc_id` revision is **unsupported in WS-1**
and `doc_id` must be unique-per-bytes — converting a silent skip into a stated
limitation. One of those, chosen by the human. Not a comment.

---

## 2. Attacking the shared agreement: is "no per-document fault isolation" a real defect, or are they wrong together?

Two reviewers independently flagged it, and the code confirms the mechanism: the
`for rd in pending` loop (`pipeline.py:74`) calls `_build_document` with bare
`meta["..."]` indexing and hard pydantic validation, no try/except, so one bad
sidecar raises `KeyError`/`ValidationError` and the exception propagates out of
`run_extract` — no `ExtractReport` returned, CLI gets a bare traceback.

Independent agreement is exactly what I am here to distrust. Here it is
**half a false positive**: the line item is real, but *both reviewers reached it
by a wrong road and both overstated its severity.*

**Wrong framing #1 (injection-attacker): "full-batch denial of service."** You
cannot DoS yourself. The same reviewer *concedes* the trust boundary is honest —
operator hand-types every sidecar, zero network, no adversary. Importing
"denial of service" into an adversary-free path is threat-model theater. The bad
sidecar is the operator's own typo, and the operator is standing at the terminal.

**Wrong framing #2 (schema-purist): "regression against validate.py's isolation
norm."** This is a category error. `validate.py` isolates **model-proposed**
items — one bad claim among many the LLM emitted, where partial garbage is
*expected and normal*. The sidecar is **operator-authored identity metadata**,
where a bad value means the operator's command was wrong. Different trust class;
the "drop the bad item, keep going" norm does not automatically transfer. In
fact, silently *continuing* past a malformed operator sidecar (the "isolation"
schema-purist implicitly wants) is arguably **worse**: the operator believes they
loaded 5 docs, got 4, and the skip is buried in a report they may not read. For
operator-authored identity metadata, fail-loud is a *defensible* choice, and it
matches this codebase's own established pattern — `insert_document` is a plain
`INSERT` that fails loud on a duplicate `doc_id` (verified, `db.py:100-105`).

**Both overstated it.** Docs committed before the crash *stay committed* (each is
its own `with conn:`), and the idempotent re-run *skips* them, so **nothing is
permanently lost** — after the operator fixes the bad sidecar, re-running
processes the rest. The batch is not destroyed; it is *paused at the first bad
doc.*

**The narrower TRUE residual neither reviewer named precisely:** the real cost is
(1) a **bare traceback instead of a partial `ExtractReport`** — the operator is
never told which docs already succeeded — and (2) **head-of-line blocking in
sha256 order**: because `pending` is processed in content-hash order (effectively
random), one bad sidecar blocks every *good* sidecar that happens to sort behind
it until it is fixed. That is an **operability nit**, fixable with a per-document
try/except that collects failures into `ExtractReport.errors` and keeps going —
which lands the severity far closer to pragmatist's silence than to
schema-purist's BLOCK. The convergence of two reviewers manufactured false
confidence in a severity **neither actually justified**: they agreed on the
*line*, by two broken arguments, at two wrong severities.

(Concrete unhandled path nobody traced to its crash: two **distinct** files
ingested under the **same** `doc_id` — both land in `pending` on the first run;
the second hits `insert_document`'s duplicate-`doc_id` INSERT and dies with an
uncaught `IntegrityError` *after* the first is committed. Same isolation gap,
triggered by two legitimately-ingested files, not a typo.)

---

## 3. `_ansi_safe`: which frame is right — and why the "conflict" is partly an illusion

Verified byte behavior. `_CTRL = [\x00-\x1f\x7f-\x9f]` alone turns the hostile
fixture into `N2[31mHACK[0m]0;pwned speed` — **no ESC, no BEL** — and strips every
sequence-introducer: `\x1b`, `\x07`, the 8-bit C1 CSI `0x9b`, the C1 OSC `0x9d`,
`0x7f`. So:

- **Pragmatist is mechanically correct**: the security property is "no live escape
  survives," and `_CTRL` alone fully satisfies it. `_ANSI_OSC`/`_ANSI_CSI` carry
  **zero security weight**; they only strip now-inert *printable* residue
  (`[31m`, `0;pwned`). The tell pragmatist names is real: the test asserts
  `"[31m" not in safe`, which is a test written to the implementation, not to a
  threat.
- **Injection-attacker is correct that the function is incomplete**: verified —
  RLO `U+202E`, PDI `U+2069`, ZWSP `U+200B`, BOM `U+FEFF` all survive `_ansi_safe`
  untouched (they sit above `\x9f`). Trojan-Source bidi/zero-width spoofing of a
  human reading `report` is un-addressed.

**But "both cannot be the right frame" is itself the trap.** They do not actually
contradict — they pull on **orthogonal axes** that merely *project* onto the same
three lines. Pragmatist optimizes the *covered* half (over-built for its
property → simplify down). Injection-attacker points at the *uncovered* half
(missing a same-class threat → incomplete). You could honestly apply **both**
(drop the cosmetic regexes **and** add Unicode handling) or **neither** (ship
as-is, defer both).

**What each gets wrong:**
- **Injection-attacker over-credits the regexes.** Calling `_ansi_safe`
  "security-load-bearing" without noticing that the *load* rests entirely on the
  one `_CTRL` line — and that the two ANSI regexes it implicitly defends are
  security-inert — is the same over-generality it criticizes elsewhere. Its
  "under-reaches" is true only for Unicode, *never* for ANSI (which `_CTRL`
  already fully covers).
- **Pragmatist under-sells the residue and never asks the right question.**
  Leaving `[31m` litter mid-metric is not *purely* cosmetic — it is low-grade
  display pollution injected by proposal content, aimed at the *same victim* the
  guard exists to protect (the human reading `report`). More importantly,
  pragmatist optimizes the *shape* of the covered half and **never asks whether
  the property is even the right property** — it never mentions Unicode at all.
  Deleting the cosmetic regexes makes the function simpler **and still
  incomplete**: optimizing the wrong axis.

**The one thing neither endorses is exactly what the diff does:** ship the
cosmetic half of a display-safety control and mark the *whole class* RESOLVED. See §4.

---

## 4. Scope-honesty: is "RESOLVED" honest, or premature?

It is **letter-honest and spirit-premature** — a silent scope-*widening* disguised
as a retirement.

The original Class A item was scoped, verbatim, to **"ANSI/OSC escape sequences."**
By the letter, `_ansi_safe` addresses exactly that, so striking *that sentence* is
defensible. The dishonesty is in the *width* of the strike: the line's **title** is
"**Report display safety**," and it is now marked "RESOLVED 2026-07-27." A future
session reads that as *terminal display safety is done* — when the honest claim is
*the ANSI/OSC/control-escape subset is done; Unicode bidi/zero-width spoofing of
the same sink, against the same human, is not.* The retirement doesn't just close
a gap; it **removes the only line that would have been the natural home for the
Unicode gap**, so the threat class falls off the tracked list entirely.

There is a sharper internal contradiction the group skirted. Under the
operator-fed boundary, **nothing hostile reaches `report` today** — so *neither*
ANSI *nor* Unicode is exploitable yet. That raises the question: if the threat is
speculative enough that Unicode can be omitted, why was ANSI sanitization pulled
forward **at all**? The pull-forward's own rationale is "defend the day live
extraction feeds proposal strings into `report`." That rationale demands Unicode
coverage *just as much* as ANSI. The diff treats the identical threat, on the
identical sink, against the identical victim, as **real enough to preempt (ANSI)
and not real enough to finish (Unicode) in the same commit.** That is not a
coherent scope; it is the half of the job that was easy to write a regex for.

Honest fix (cheap, and injection-attacker already sketched it): reword the note to
scope RESOLVED explicitly to *ANSI/OSC/control escape sequences*, and keep a live
Class A line for *Unicode bidi/zero-width display spoofing* so the retirement
doesn't quietly bury it.

---

## 5. The question the group avoided entirely: "operator-fed" is doing dishonest double-duty as "content-trusted"

All three split on verdict, but **all three accepted the manifest's framing**:
"operator-fed / curated-fixture, **zero Class A exposure**, no hostile document
reaches the store, hostile-input trust fully DEFERRED to WS-2." That shared
premise is the thing to attack.

**Pre-diff, `run_extract` was a stub (`NotImplementedError`) — the model was never
called on an ingested document.** This diff is what wires `semianalyst extract` to
call the **real** Anthropic model on an ingested PDF: `extractor.extract(rd.blob_
path.read_bytes(), ...)` → `pdf_to_text(raw)` → into the prompt between `DOC_OPEN`
/`DOC_CLOSE` (verified, `base.py:51,106`). So the PDF **body text** reaches the
live model *in production* for the first time **in this exact diff.**

Now examine what "operator-fed" actually buys. The operator hand-*feeds* the file;
the operator did **not author its bytes**. The documents this tool exists to
scrutinize are **foundry and vendor marketing PDFs** — third-party, self-serving,
by the product's own thesis semi-adversarial. "Curated fixture" silently conflates
*the operator chose this file* with *this file's content is benign*. For the
**numbers**, that conflation is harmless — `validate.py` grounds every claim to its
source span, so self-serving figures are captured *with their distortion visible*;
that is the tool working. But for **prompt-injection text embedded in the PDF
body**, "the operator picked it" is **no protection whatsoever** — the operator
picks precisely the semi-adversarial marketing PDFs the tool is *for*.

So the prompt-injection surface is **LIVE today, not deferred to WS-2.** WS-2 is
about *who fetches the bytes*; it says nothing about whether the bytes' content is
trusted. Whether `DOC_OPEN`/`DOC_CLOSE` actually holds against injection embedded
in a *real* vendor PDF is **not established by this diff** — and this diff adds no
test driving the new `ingest_file → run_extract → real model` path against a
crafted PDF (the `@live` injection test pre-exists and exercises the extractor
directly, not the new production wiring).

The damning part: **the reviewer who owns this angle cleared it on a
technicality.** injection-attacker's "ruled out" list states "No new
prompt-injection surface: sidecar fields never reach the model — only
`pdf_to_text(raw)` does, inside the existing delimiter." That answers *do the
sidecar fields inject?* (they don't) — a narrower question than the one that
matters: *does wiring the real model to operator-ingested, third-party-authored
PDF bodies make injection a newly production-reachable surface?* It does, in this
diff. "The delimiter pre-existed" is true at the code level and **wrong at the
production-reachability level** — the code that makes `extract` call the model on
ingested bytes is *this* workstream.

The honest statement the gate should force into CLAUDE.md/ROADMAP: *prompt-injection
via PDF body goes **live** in WS-1 (first real model call on ingested third-party
PDFs); it is defended by the pre-existing `DOC_OPEN`/`DOC_CLOSE` delimiter and the
`@live` injection anchor, and is **not** deferred to WS-2 — only the network fetch
of the bytes is.* The manifest's "zero Class A exposure" is true for persistence
and claim integrity, and **false for the injection surface**, which just became
reachable.

---

## Bottom line for the human (not a vote)

- **The verdict split is genuine and unaveragable.** BLOCK vs APPROVE turns on a
  single question: is contradicting a **named** CLAUDE.md guarantee (sha256 =
  revision signal) a shipping blocker when the contradiction is reachable only by
  a *benign operator re-ingest*? Pick (a) fix the skip, or (b) declare same-doc_id
  revision unsupported. Not a TODO.
- **The one thing two reviewers agreed on is the weakest finding**, not the
  strongest: real line item, two broken framings (DoS / isolation-regression),
  overstated severity (idempotent re-run self-heals). True residual = no partial
  report + sha256-order head-of-line blocking; an operability nit, not a BLOCK.
- **`_ansi_safe`: pragmatist is right on the mechanism, injection-attacker is right
  on the gap, and the "conflict" is an illusion** — they're orthogonal. The diff
  does the one move neither endorses: ships the cosmetic half and retires the
  whole class.
- **"RESOLVED" is letter-honest, spirit-premature** — a silent widening from
  "ANSI/OSC" to "display safety" that buries the Unicode gap.
- **The unchecked shared assumption behind all three verdicts:** operator-fed ≠
  content-trusted. Prompt-injection via PDF body is **live in this diff**, not
  deferred — and the angle's own reviewer waved it through on a narrower question.
