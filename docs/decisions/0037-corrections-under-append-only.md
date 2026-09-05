# ADR-0037 — Corrections under append-only

**Status:** Proposed

**Builds on:** ADR-0035 (append-only claims, content-hash identity, attestations),
ADR-0036 (serving surface, absence states, the coverage queue)

## Context

ADR-0035 made the claims store append-only and content-addressed, and ADR-0036 put a
serving surface in front of it. Both were designed as if transcription never errs. It
does: a transcriber (human or agent) will eventually file a value the document does not
state — a misread digit, a row slip in a merged-cell table, a unit transposed. The
FU-67TG near-miss during catalog ingestion (a merged-cell guess that would have recorded
R25 where the document prints R10) is the shape of the failure, caught that time only
because the rule was skip-and-name rather than guess.

Append-only makes the obvious fix illegal: the wrong record cannot be edited (a rewritten
record is a different claim, ADR-0035 D7) and cannot be removed (D3). But serving a value
the document does not state is the *confidently wrong* failure ADR-0036 D4 calls the
worst this system can produce — with full provenance attached, pointing at a page that
disproves it. The store needs a way to stop serving a record without touching it, a way
for the correct value to arrive, and a way for consumers to learn any of this happened.
It also needs an intake: the party most likely to notice a transcription error is a
consumer holding the document, and today they have no channel but a human conversation.

Two failure modes must not be conflated. A **transcription error** is ours: the document
is right and the record is wrong. A **document error** — a manufacturer misprint — is
theirs: the record faithfully transcribes a wrong statement. The second is not a
transcription failure and must not be treated as one; the transcription discipline
(ADR-0014, ADR-0035 D1) records what the document says, not what is true.

## Decision 1 — Only transcription errors retract; document errors are new documents

A retraction asserts exactly one thing: *this record does not faithfully transcribe its
cited source.* That is the only assertion the claims layer is competent to make — it can
be settled by anyone holding the document, by reading the cited page.

A manufacturer misprint therefore never retracts. The claim faithfully says what the
document says; retracting it would substitute our judgment of truth for the document's
statement, which is authorship, not transcription. When the manufacturer publishes an
erratum or a revised datasheet, that is a new document: it ingests under its own hash
with its own claims (ADR-0035 D5), and whether a manifest migrates to the newer
document's claims is the visible authorship decision D5 already assigns to the manifest
layer. Disagreement between a document and its erratum is served as disagreement — two
claims, two citations — exactly as two disagreeing restatements within one document are
both transcribed.

## Decision 2 — A retraction is an appended record; the correction is an ordinary claim

A claims file gains an optional `retractions:` array. Each entry names:

- `retracts` — the claim id being retracted, which must identify a claim in the same
  file (a retraction crossing document files would let one document's pass damage
  another's record),
- `reason` — free text stating what the record got wrong, precise enough that a reader
  with the document can verify the error,
- `date` — when the retraction was recorded,
- `superseded_by` — optional: the id of the claim that replaces the retracted one.

The retracted claim's bytes never change. Its id still verifies, its citation still
resolves, and the append-only property stays checkable in exactly ADR-0035 D7's sense:
the retraction is a *pure addition* that changes what the store serves, never what it
stored. An existing claims file now has exactly **three** legal mutations — appending a
later pass's claims, appending that pass's attestation (both ADR-0035 D7), and appending
a retraction. Nothing else; existing records are still never edited or removed.

The correction, when there is one, is not a special artifact: it is an **ordinary
claim**, appended through the same machinery as any other, carrying the same citation
(same document, page, locator — the correction re-reads the same statement), earning its
own content-hash id, and passing full validation. `superseded_by` points at it. A
retraction may also stand alone — the record was wrong and the document states nothing
in its place — in which case `superseded_by` is omitted and the absence answers
recompute as if the retracted claim never answered (Decision 5).

The rejected alternative was a `status:` field on the claim itself. That edits the
record, which changes its hash, which retargets every citation — the exact cascade
content addressing exists to prevent. A tombstone file per retraction was also
considered and rejected: it scatters one document's story across files, and ADR-0035 D7
already made the file the unit that accumulates a document's history.

## Decision 3 — Retractions are operator-authored; disputes arrive through a queue

**No tool ever writes a retraction.** A retraction is a judgment that our record
contradicts its source — checking that means reading the document, and the documents are
deliberately not in the repository (`claims/README.md`). The retraction record is
written by the operator, in a supervised session, after that reading. This is ADR-0036
D1's rationale extended to the one mutation that *reduces* what is served: a serving
path that could silence claims is a bigger prize for an attacker than one that could add
them.

What tools get is intake. `report_claim(claim_id, reason, expected_value?, note?)`
files a dispute on the coverage-queue repository as a GitHub issue labeled
`claim-report`, deduplicated on the claim id — repeat reports stack as comments, and the
stack is the operator's triage ranking, exactly the coverage queue's shape (ADR-0036 D1
as amended). `claim_id` is required and must exist in the serving index: served values
carry their ids, so a genuine dispute is precise by construction, and an unknown id is
politely refused rather than filed. Everything the coverage queue learned applies
unchanged — free text fenced and stripped in the public issue body, unavailability
answered politely without consuming the shared daily cap, and the tool not registered at
all when the queue credentials are unset. The agent may OFFER a report when the user
disputes a served value; it never files one without the user's explicit yes.

The issue template states Decision 1's line, because the reporter cannot be assumed to
know it: transcription errors are retracted and replaced; manufacturer misprints are
not retracted — the erratum ingests as a new document. Either way a valid report
resolves visibly, in the store's git history or the corpus's.

## Decision 4 — Retracted claims are excluded by default and retrievable with their story

`get_claims` omits retracted claims from `claims`. Serving a value known not to match
its source, even flagged, invites exactly the skim-read failure the flag is supposed to
prevent; the default consumer should be unable to quote a retracted value by accident.

The story is not hidden, it is relocated. When a query would have matched a retracted
record, the envelope carries a separate `retracted:` section holding the retracted
claim with `retracted: true`, the reason, and the superseding claim id when one exists —
so a consumer who previously cited the old id learns what happened to it and where to
go, from the same query that used to return it. Envelopes whose scope contains
retractions carry `retracted_count`; the field is absent when zero, so the common case
pays nothing. No new tool and no new parameter: retrieval-with-story is how exclusion
is served, not an opt-in mode.

Absence recomputes accordingly: an unreplaced retracted claim does not answer its key,
and the absence states (ADR-0036 D3) are computed as if it never had (Decision 5 for
which state).

## Decision 5 — Attestation effect is computed from the record, not authored

An attestation's promise is *fully transcribed at vocabulary V* (ADR-0035 D4). A
retraction is evidence that promise failed for one key — but re-authoring or annotating
the attestation would edit an existing record, and a per-retraction "attestation damage"
marker would be a second record that can disagree with the first. Instead the effect is
**computed**: `covered(document, key)` gains one clause — a retraction whose
`superseded_by` is empty and whose retracted claim's canonical key is K leaves K
uncovered for that document, so absence on K answers `absence_not_yet_meaningful` (the
attestation's promise for K is known-broken; nobody has re-established what the document
says) rather than `attested_silence`.

The rule is self-healing by construction. When the superseding claim lands,
`superseded_by` points at it, the retraction is no longer unreplaced, and the
attestation stands again at full strength — no record was touched in either direction.
A replaced retraction never weakens coverage: the correction re-establishes what the
document states for that key, which is all the attestation ever promised.

## Out of scope

Retraction of attestations themselves (an attestation found to be false is repaired by
the pass that completes the transcription, not by a retraction record), any notion of
claim deprecation short of retraction, and migration tooling for manifests citing a
retracted claim id — the `retracted:` envelope section gives an agent everything needed
to propose that migration, and the manifest layer's refusal machinery governs it.
