# ADR-0035 — A manifest cites claims; a claim cites a document

**Status:** Proposed

**Builds on:** ADR-0014 (components vs modules, zero-assumption discipline),
ADR-0016 (one validation surface)

## Context

ADR-0014 established that a component manifest contains only what a datasheet answers, and
the component schema records provenance as `source.kind: [datasheet, manual, catalog,
measured]`. But `source.kind: datasheet` is currently an assertion, not a reference. Nothing
in the system can answer "which datasheet, which revision, which page" — the provenance chain
ends at a word.

A datasheet-ingestion service (planned as an MCP server) makes this gap load-bearing. If the
service returns manifest-shaped values, it must silently make the same judgment calls a human
transcriber makes: collapsing min/typ/max spreads to one number, dropping test conditions,
picking one variant out of a family table. Those are exactly the fabrications the refusal
engine exists to prevent, moved upstream where no refusal fires.

The distinction that resolves this is already latent in ADR-0014: what a datasheet describes
is not a manifest field. A datasheet makes **claims** — conditional, per-variant statements
with spreads, footnotes, and revision history. A manifest field is a projection of one or
more claims onto one part at one operating point. The projection is authorship and stays with
the manifest author (human or agent, subject to refusal). The claims are transcription and
can be stored, validated, and served.

## Decision 1 — Claims are a first-class artifact kind, distinct from manifests

A claim is a single datasheet-answerable statement with four mandatory parts:

1. **Key** — what is being claimed, drawn from a controlled vocabulary (Decision 2).
2. **Value** — a structured value preserving datasheet fidelity: min/typ/max where the
   document gives a spread, unit as printed, never collapsed to a scalar the document does
   not state.
3. **Conditions** — the test or operating conditions under which the value holds. A claim
   whose source states conditions and whose record omits them is invalid, not incomplete.
4. **Citation** — the document (by content hash, Decision 5), page, and locator (table, row,
   figure, or section) where the statement appears.

A claim additionally records its extraction method and applicable part numbers. Claims for a
document family carry per-variant applicability rather than being flattened to one part.

The schema lives at `spec/schema/ocm-claims-1.0.schema.json`. Per ADR-0016 there is exactly
one validator, `validate_claims`, and no weaker sibling.

Consequence: a component manifest field with `source.kind: datasheet` gains a resolvable
referent. The manifest cites a claim; the claim cites a document. Auditing a manifest value
becomes following two links, and the judgment call — which claim, which end of the spread,
which variant — is visible at the manifest layer where refusal governs it.

## Decision 2 — Claim keys come from a versioned controlled vocabulary, with an escape hatch

Claim keys are drawn from `spec/schema/ocm-claims-vocab-1.0.yaml`, a versioned artifact in
which every entry declares:

- the key name,
- the expected value shape (scalar, spread, enum, text),
- the unit dimension,
- a definition precise enough that two manufacturers' datasheets can be judged as answering
  the same question or not.

The vocabulary is seeded by demand, not supply: its initial entries are the fields the module
and component schemas already consume with `source.kind: datasheet`, not the union of
everything datasheets print.

Statements that do not match a vocabulary entry are recorded under an `x-` prefixed key.
An `x-` claim must still carry value, conditions, and citation — the escape hatch relaxes
naming, never structure. `validate_claims` accepts `x-` keys as well-formed but marks them
unbound; nothing downstream may consume an unbound claim as a manifest source.

Consequence: the manifest layer can only bind fields whose meaning is defined, and the
ingestion layer never has to refuse a true statement merely because the vocabulary hasn't
caught up.

## Decision 3 — Promotion is by alias; ingested claims are immutable

When an `x-` key recurs across documents, it becomes a candidate for promotion. Promotion is
a change to the vocabulary, made as a pull request adding a full entry — and the entry cannot
merge without a definition and unit dimension. Frequency nominates; a stable cross-
manufacturer meaning admits. `x-response_time` in ten datasheets is not promotable while
three define it at 10–90% rise and seven don't say.

The promoted entry carries an `aliases:` list naming the `x-` key it absorbs. Existing claim
records are not rewritten: a claim stored under `x-holding_torque` remains byte-identical and
becomes queryable as `holding_torque` through the alias. The claims store is append-only in
the same sense the ADR corpus is — promotion is a pure addition to the vocabulary, never an
edit to the record.

Consequence: document ingestion can be replayed, diffed, and hash-verified at any vocabulary
version, and no vocabulary change can silently alter what a datasheet was recorded as saying.

## Decision 4 — Absence is answered, not implied

When the claims service is asked for a key it has no claim for, it returns an explicit
`not_found` record naming the key, the part number, and the documents consulted — not an
empty result.

An empty result is ambiguous between "the datasheet doesn't specify this" and "nobody
looked." The first is information ADR-0014 depends on: an absent manifest field is only
legitimate when the datasheet genuinely doesn't answer. A `not_found` record is that
legitimacy, recorded. It composes with the refusal engine the same way validation refusals
do — the set of `not_found` responses for a component is the human's completion list, with
`measured` as the remaining source of supply.

## Decision 5 — A document is its hash

The document record identifies an ingested artifact by sha256 of the file, alongside
manufacturer, document type, revision string, publication date, and source URL. Citations
reference the hash, never the URL or the revision string alone.

Manufacturers revise datasheets in place at stable URLs, sometimes without bumping the
printed revision. A claim cited to a URL can silently change meaning; a claim cited to a hash
cannot. Re-ingesting a revised document creates a new document record and new claims; the old
claims remain valid citations of the old document. Whether a manifest should migrate to the
newer document's claims is an authorship decision at the manifest layer, taken visibly.

## Decision 6 — Human transcription is the trusted path until extraction earns parity

The claims store and its serving interface do not depend on automated extraction. Hand-
transcribed claims, validated by `validate_claims` against golden fixtures, are the initial
and reference content. Automated extraction is admitted per document type only when its
output matches the hand-built fixture for that type, and every claim records its extraction
method so the two populations remain distinguishable.

This is the generator-before-hardware sequencing (ADR-0010) applied to ingestion: the
consuming interface is proven with trusted content before the producing machinery is built.

## Out of scope

Authentication and deployment of the serving interface, the extraction pipeline's internal
design, and any change to the component or module schemas beyond giving `source.kind:
datasheet` a resolvable referent. A later ADR may bind manifest fields to claim references
explicitly; this ADR only makes that binding possible.
