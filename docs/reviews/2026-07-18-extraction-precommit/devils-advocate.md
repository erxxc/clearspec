# devils-advocate — GATE 2 (pre-commit / diff) — attack on the consensus

**Role:** I don't review the diff. I review the *agreement* about the diff. I read
`injection-attacker.md`, `schema-purist.md`, `pragmatist-shipper.md`, the
`workstream.diff`, `CLAUDE.md`, and the GATE-1 `resolution.md`, then checked the
one file all three declined to open: `src/semianalyst/store/db.py`.

**Verdict:** The consensus reaches the right disposition (BLOCK) for reasons that,
followed literally, will not fix the thing they are afraid of — and will manufacture
the *feeling* of a fix, which is the exact anti-pattern GATE-1 congratulated itself
for rejecting. I am not blocking on a new bug. I am blocking on **where the group
agreed the fixes go.**

---

## The shared frame nobody checked: "the trust boundary is `validate.py`"

Read the three "what would move this to APPROVE" lists. Every proposed fix — all of
them, across all three reviewers — is an edit to `extract/validate.py`, its tests, or
the prompt. injection-attacker says it outright: *"Both are fixable with small,
bounded additions to `validate.py` (no redesign)."* schema-purist's remedy list is
five `validate.py`/fixture edits. pragmatist's is dead-branch trims and a prompt
tweak. The whole gate has silently agreed on one proposition:

> `validate.py` is the trust boundary; if `validate.py` rejects/nulls/flags the bad
> thing, the corruption is contained.

That proposition is false, and it is false in a way that makes the group's headline
finding (entity poisoning) unfixable at the location they all chose.

`validate.py::validate_proposal` is a **pure function over one document's proposal.**
It has no connection, no cursor, no knowledge that any other document ever existed.
The place where a proposal stops being a proposal and becomes durable, corruptible
state is `store/db.py::insert_entity` / `insert_claim` — and both are
`INSERT OR REPLACE` (db.py:121, db.py:145) under `PRAGMA foreign_keys = ON`
(db.py:30). That module was declared **out of scope** by the GATE-1 resolution
("scope discipline: `store/` untouched") except for the authorized v2 schema bump.

So the trust boundary is architecturally split: the *check* is a per-document pure
function in scope; the *corruption primitive* is a blind upsert in a module out of
scope. No reviewer named that split. All three reasoned as if closing the check
closes the vector. It does not.

---

## The sharpest conflict about WHERE a fix belongs — and it's a self-contradiction, not a standoff

The three don't argue loudly about location; they *concur by omission*, which is
worse, because it buries the real conflict. Here it is, named plainly:

**injection-attacker's F2 locates the mechanism in `store/` but prescribes the fix in
`validate.py`, and the two do not connect.** The finding's own scenario is: a hostile
PDF name-drops "NVIDIA H200"; the model resolves it to `nvidia_h200` (the prompt hands
attackers the deterministic id convention, prompt.md:106); the attacker's PDF grounds
a fabricated claim about it; `INSERT OR REPLACE` writes it under the real competitor's
row. The prescribed fix: *"reject any claim whose `entity_id` is not present in
`kept_entities` for that same proposal."*

Trace it. In the poisoning scenario the attacker's PDF **mentions** NVIDIA H200, so
the model **emits an entity** for it, so `nvidia_h200` **is** in `kept_entities`. The
same-proposal existence check passes. **The proposed `validate.py` fix does not block
the attack the finding is built around.** It blocks a strictly weaker, benign bug (a
claim referencing an entity the model forgot to emit). The actual attack — capturing a
*pre-existing, cross-document* entity id — is, by construction, invisible to any
single-proposal function, because "pre-existing" and "cross-document" are exactly the
facts a pure per-proposal function cannot see.

That is the sharpest WHERE conflict, and it forces a choice the group avoided:

- **Either** the poisoning finding is real → then it cannot be fixed within the
  gate's declared scope, and BLOCK means *reopen `store/` and the schema*, not "add a
  line to `validate.py`";
- **Or** scope holds (`store/` stays closed) → then F2 is not a `validate.py`-fixable
  defect, the proposed check is theater, and shipping it lets everyone mark F2
  "handled" while the vector stays open.

There is no third option, and the same-proposal check is the false middle between
them. GATE-1 rejected the coarse-substring check in precisely these words: it
*"manufactures the feeling of enforcement while providing none, and worse, lets
everyone mark C 'handled.'"* One gate later, the same-proposal entity check is the
same move against a different finding, and no reviewer noticed, because they share the
frame that trust boundaries live in `validate.py`.

schema-purist's F2 (dedup merges citations but loses node/chip *values*) is the same
question refracted through the one module that reviewer was allowed to look at: it,
too, only *matters* because the merged entity is then `INSERT OR REPLACE`'d into
store. Both F2s are shadows of one unasked question — **who owns an entity row, and
what does a collision mean** — split across whichever module each persona had
permission to open.

---

## The scenario where all three are wrong at once: the benign case is worse than the attack

Every reviewer framed the entity/id problem adversarially (hostile PDF). Strip the
attacker and the *same* mechanism breaks the product's reason to exist.

`entity` PK is `entity_id`; `claim` PK is `claim_id = "<entity_id>_<metric slug>"`
(prompt.md). Both insert paths are `INSERT OR REPLACE`. Now run the mundane happy
path the whole system is built for — **cross-source corroboration** (`analyze/`, "one
entity per real thing," `corroboration.related_claim_ids`):

- Document A (a conference paper, tier 1) creates `tsmc_n2` with rich, grounded
  node attributes and a `tsmc_n2_logic_speed` claim.
- Document B (a foundry brief, tier 2) legitimately mentions TSMC N2 and makes its
  own logic-speed claim. The model mints the *same* `tsmc_n2` entity and the *same*
  `tsmc_n2_logic_speed` claim_id.
- `insert_entity(B)` **REPLACES** A's entire entity row — A's grounded
  `attribute_citations`, A's node values, gone. `insert_claim(B)` **REPLACES** A's
  claim outright.

The store cannot hold two documents' claims about the same metric on the same entity
*at all*. The corroboration layer — the entire thesis — is designed to compare claims
from multiple sources about one entity, and the storage layer silently destroys the
second-arriving-minus-one every time. `related_claim_ids` will point at rows that were
overwritten. This is not adversarial; it is the first thing that happens the moment a
second real document about the same chip is ingested, which is the *point* of the
corpus. All three reviewers argued about the exotic case and missed that the identical
mechanism is fatal on the ordinary one.

The unexamined assumption underneath: `entity_id`/`claim_id` are being used as
**content-identity keys** (safe to upsert = re-ingest), but they are actually
**document-independent semantic keys** (a collision means "two sources agree," which
must *accumulate*, never overwrite). `INSERT OR REPLACE` conflates "same document
re-run" (should upsert — CLAUDE.md's idempotency rule) with "different document, same
real-world thing" (must corroborate). Nobody at either gate asked whether these are
safe primary keys.

---

## Why this can't be patched anywhere in *this* diff: entities have no provenance

Suppose the group takes the honest branch and moves the guard to `store/`. Write the
rule: "reject/flag an `INSERT OR REPLACE` that would overwrite an entity created by a
different document." You cannot. **The `entity` table has no `doc_id` column** — check
the schema (`schema/extraction_schema_v2.yaml`, `entity:` block) and the model
(`Entity` in models.py): claims carry `doc_id`, entities carry none. Entity identity
is *global and unprovenanced*. There is no column that records "`nvidia_h200` came
from document A," so there is nothing to compare against at insert time. The poisoning
check is un-hostable not just in `validate.py` but *anywhere in the current schema.*

And note the bitter irony of timing: the v2 bump is the one change that **did** open
`store/` this gate — the diff edits `insert_entity` itself to add the
`attribute_citations` column. The reviewer's hand was literally inside the function
that carries `INSERT OR REPLACE`; the corruption primitive sat one line above the
edit, in the same hunk, and went unremarked because "store is out of scope." The exact
moment the schema was already being versioned and migrated was the moment to add
entity provenance — and it passed unused.

---

## The honest severity of F2 (which cuts against the group in both directions)

Devil's due to the diff: the poisoning vector is **not reachable today.**
`run_extract` is stubbed (resolution.md); nothing calls `insert_entity`/`insert_claim`
from the extract path. `AnthropicExtractor.extract` returns an `ExtractionResult` and
stops. So injection-attacker's "gets written under a real competitor's entity row"
overstates what this diff can do — there is no writer. That cuts two ways, and both
cut against the consensus:

1. It undercuts F2 as a *pre-commit blocker on this diff* — there is no live
   corruption path to block.
2. It confirms the fix does not belong in `validate.py` *now*: the real defense is a
   design constraint on the store/ingest wiring **that does not yet exist**, plus
   entity provenance in the schema. The correct GATE-2 action is not "add a check to a
   pure function" — it is "write the actual rule into the store handoff contract
   before `run_extract` is wired," which GATE-1 deferred to a contract nobody has
   drafted.

The resolution "handed off an alias-resolution contract to the store workstream" as a
one-line open item. That handoff *is* the fix location for F2, it is empty, and no
GATE-2 reviewer looked at whether it says anything. It says nothing.

---

## Second front: the ENFORCE anchor is non-deterministic, so "green" is CURATE in disguise

pragmatist caught that `AnthropicModelClient.complete` sends no `temperature` (API
default 1) while `test_golden_live` asserts exact `model_dump == expected.json` on
free-running output — and filed it as a *shipping-cost* nit (CI flake $). Connect it
to Q0 and it stops being a nit. The human's headline decision was **Q0 = ENFORCE:**
"green in CI means the model was actually exercised." But an exact-match assertion
against temperature-1 output passes *by luck*; the first flake gets "fixed" by
re-recording `expected.json`/`llm_response.json` to whatever the model said that day —
at which point the golden's "grounded-ness" is just the model's last utterance, and
ENFORCE has silently decayed into CURATE: the precise posture the human explicitly
rejected, re-entering through a sampling-parameter backdoor. The GATE-1 devils-advocate
warned "green DoD has zero real-model coverage"; nobody at GATE-2 noticed that the
`--run-live` anchor meant to answer that warning is itself non-reproducible. All three
GATE-2 reviewers *trust the "23 passed --run-live" claim* (pragmatist even writes
"claimed at 23 passed") without anyone confirming it reproduces. It is one green roll
of a die reported as a passing gate.

**The scenario where all three are wrong at once:** the live anchor never runs
deterministically (so ENFORCE is nominal), the store writer that would make F2 real
does not exist yet (so the poisoning BLOCK is unactionable this diff), and the
`validate.py` edits they are debating rearrange the boundary that isn't where the
water is coming in. Correct call, wrong wall.

---

## The one question the group avoided

Not "can an attacker poison an entity." The question upstream of that, which all four
personas (the three reviewers *and* the resolution) walked around:

> **When a second document names an entity or metric the first document already
> created, what happens to the first document's data — and where is that decided?**

Today's answer, provable from the code: *it is silently destroyed by
`INSERT OR REPLACE`, and the decision is made nowhere* — not in `validate.py` (blind
to other documents), not in the schema (entities have no provenance), not in the store
handoff contract (empty). The adversarial phrasing everyone argued about is a special
case of this. The benign phrasing is the common case and it breaks the product thesis.
Until this question has an owner and an answer, hardening `validate.py` is polishing a
boundary that the real corruption flows straight past.

---

## Recommendation (as a challenge, not a merge)

BLOCK stands — but redirect it. Do **not** accept a same-proposal `entity_id` check in
`validate.py` as closing F2; it is the false middle and will mark an open vector
"handled." Instead, before commit, force three things the gate structurally avoided:

1. **Answer the ownership question in writing:** decide whether `entity_id`/`claim_id`
   are content-identity keys or semantic keys, and therefore whether store must
   *accumulate* (append + corroborate) rather than `INSERT OR REPLACE` on
   cross-document collision. This is a store/schema decision, not a `validate.py` one.
2. **Add entity provenance** (a `doc_id`/source set on `entity`) *in this v2 bump*,
   while `store/` and the migration are already open — otherwise the guard in (1) has
   no column to stand on and the next schema version pays the migration cost again.
3. **Pin `temperature=0` on the live client** and treat the golden as tolerance-based,
   or admit in `CLAUDE.md` that the anchor is CURATE — do not let an exact-match,
   temperature-1 test masquerade as the ENFORCE gate the human chose.

The `validate.py` bugs the three found are real (the `%`/yield over-rejection is a
genuine data-destroyer, the merge-loses-values is a genuine orphan). Fix them. But
they are the visible edge of a trust model that put the security boundary in a pure
function and the corruption primitive in an out-of-scope upsert, and then reviewed
only the function. The agreement to fix everything in `validate.py` is the defect.
