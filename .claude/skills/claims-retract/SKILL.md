---
name: claims-retract
description: Work a claim-report issue — verify a disputed claim against its source document and, if the report is valid, author the retraction and correction under ADR-0037. Use when the user asks to work, resolve, or triage a claim report or dispute, or to retract a claim. Expects an issue number or claim id, and requires the source document available locally for verification.
---

# Claim retraction session (ADR-0037)

You are resolving a dispute about whether a stored claim faithfully
transcribes its cited source. `docs/decisions/0037-corrections-under-append-only.md`
is NORMATIVE for this session — read it first. The one assertion you may act
on is Decision 1's: *the record does not match the cited page.* You never
judge whether the document itself is true.

## Setup, every time

1. Two checkouts. Public OCM repo (this directory): read-only for tooling and
   fixtures. Corpus: `../ocm-claims-corpus` — production retractions commit
   THERE. Fetch both, state both branches. A retraction to a synthetic
   fixture (rare; only if the user says so) commits to the public repo
   instead.
2. From the user's message, take the claim-report issue number (or a claim
   id). Fetch the issue; extract the claim id, the reporter's reason, and
   any expected value. Locate the claim in its claims file and its document
   record.
3. The user must have the source document locally — ask for the path. Verify
   `sha256(local bytes)` equals the document hash in the claims file. If it
   does not match, STOP: you cannot verify a dispute against different bytes
   than the claim cites. Report the mismatch and what the user should fetch.

## Verify — the only judgment in this session

4. Open the cited page at the cited locator (render it; do not trust a text
   layer over a table). Read what the document actually prints. Then decide,
   with the user, which of three outcomes this is:

   - **Transcription error** — the record does not match the page. Proceed
     to retraction.
   - **Faithful transcription** — the record matches the page; the reporter
     disputes the document's truth. Per Decision 1, NO retraction: draft a
     reply for the issue explaining the line (a manufacturer misprint
     resolves by ingesting the erratum or revision as a new document — offer
     to open a coverage request for it), and close as not-a-transcription-
     error after the user approves the reply.
   - **Unclear** — the page is ambiguous (merged cells, conflicting
     restatements). Do not guess — that rule is why this store has so few
     retractions. Summarize the ambiguity on the issue, leave it open, stop.

## Author — transcription errors only

5. Append to the claims file, per Decision 2:
   - The retraction entry: `retracts` (the claim id), `reason` (precise
     enough that a reader with the document can verify the error — quote
     what the page actually prints), `date`.
   - The correction, when the document states a value: an ORDINARY claim —
     same citation, correct value, transcribed under the full ingestion
     discipline (binding, units, glyphs), id from `claim_id()`, validated
     like any other. Set `superseded_by` to its id.
   - A retraction may stand alone when the record fabricated something the
     document doesn't state — then no correction, no `superseded_by`, and
     the absence machinery answers per Decision 5.
6. `extraction.method` on the correction states how it was produced —
   drafted by you and approved by the user is `automated`.
7. `validate_claims` green. If the retracted claim was on an attested
   document, state in your summary what the absence answer for that key now
   is (Decision 5) so the user knows what consumers will see.

## Gates — stop and wait for go-ahead at each

1. **After verification:** what the page prints, what the record says, your
   outcome call (error / faithful / unclear), and — for errors — the drafted
   retraction reason and correction value.
2. **Before commit:** the diff, validation output, and the drafted issue
   comment (what was retracted, the superseding id or its absence, a link
   the reporter can follow once pushed).
3. **After commit and push** (`git status -sb` even with origin — the
   session is not done before that): post the comment, close the issue,
   remind the user to redeploy/restart the ocm-claims server so the
   retraction serves.

## Hard rules

- Never edit or remove an existing record — retraction is a pure append;
  the three legal mutations in ADR-0037 D2 are the entire list.
- Never retract for document error, vocabulary disagreement, or unit
  preference. Decision 1's line is the whole authority of this session.
- One issue per session unless the user says otherwise; a batch invites the
  exact skim-verification this discipline exists to prevent.
