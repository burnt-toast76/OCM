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
2. **Value** — a structured value preserving datasheet fidelity, shaped by the key's
   vocabulary entry. A spread is the object `{min, typ, max, unqualified, unit}` — any
   subset of the bounds the document states, at least one present, `unit` verbatim as
   printed. `unqualified` holds a single number the document prints with no qualifier;
   filing such a number under `typ` would fabricate a qualifier the document does not
   state. No bare scalar is a valid spread, no bound is ever inferred from another, and
   the claims layer offers no single-number accessor — picking an end of a spread is
   authorship and happens at the manifest layer, where refusal governs it.
3. **Conditions** — the test or operating conditions under which the value holds. A claim
   whose source states conditions and whose record omits them is invalid, not incomplete.
   No validator can read the source to enforce that, so the schema encodes it as an
   attestation discipline: `conditions` is a required field, and an empty list is a
   positive statement that the document states none — distinct from a missing field,
   which is a schema error.
4. **Citation** — the document (by content hash, Decision 5), page, and locator (table, row,
   figure, or section) where the statement appears.

A claim about one element among several — one connector, one port, one output, one process
element — additionally carries a **subject**: that element's designation, verbatim as
printed. The subject is not a condition. Conditions say under what circumstances a value
holds; the subject says which thing the claim is about, and conflating them reduces
which-thing queries and Decision 4's absence answers to free-text matching. Whether a key
takes a subject is declared in its vocabulary entry. When a subject-taking key's document
designates no element (a sole unlabeled connector, say), the subject is omitted — the
absence is the transcription, exactly as ADR-0014 treats an unlabeled pneumatic port.

A claim also records its extraction method and its applicability: the part numbers covered
(`applies_to`, at least one) and, when the document states its coverage as a family
designation, that designation verbatim (`family`) — so the enumeration stays auditable as
the judgment it is. Claims for a document family carry per-variant applicability rather
than being flattened to one part.

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
- the expected value shape, drawn from the set the vocabulary header defines — a shape
  enters that set when a key demands it, never speculatively,
- whether the key takes a subject (Decision 1),
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

The response is computed per query, but its legitimacy is stored. Computation alone cannot
distinguish "the document doesn't answer" from "transcription stopped at page 3" — this
decision's ambiguity reproduced one level down — while a stored per-query record goes stale
the day a new document is ingested. The stored fact is therefore scoped to what cannot rot:
a per-document **completeness attestation**, pinned to a vocabulary version — "this document
is fully transcribed against vocabulary 1.0; any vocabulary key without a claim here is a
genuine document silence." The attestation is document-level and written once, when a
transcription pass finishes; a half-transcribed document carries none, and its absences stay
untrusted until the pass completes. The computed answer names the documents consulted and
which of them are attested complete at which vocabulary version — a later vocabulary's new
keys are honestly uncovered by an older attestation.

## Decision 5 — A document is its hash

The document record identifies an ingested artifact by sha256 of the file, alongside
manufacturer, document type, revision string, publication date, and source URL. Citations
reference the hash, never the URL or the revision string alone.

Manufacturers revise datasheets in place at stable URLs, sometimes without bumping the
printed revision. A claim cited to a URL can silently change meaning; a claim cited to a hash
cannot. Re-ingesting a revised document creates a new document record and new claims; the old
claims remain valid citations of the old document. Whether a manifest should migrate to the
newer document's claims is an authorship decision at the manifest layer, taken visibly.

One limitation is accepted knowingly: some distribution channels watermark every download —
a stamped email, timestamp, or order number — so two copies of the identical revision hash
differently. Byte-hash remains identity anyway. The bytes cited are the bytes read, and the
alternative — hashing a normalized extraction — lets a normalization bug merge documents
that genuinely differ, the one failure this decision exists to make impossible. Watermarked
twins are separate document records whose manufacturer, type, revision, and date fields keep
the duplication visible to a human; ingestion prefers the manufacturer's own un-gated URL
where one exists; and if fragmentation ever hurts in practice, the remedy is an append-only
document-equivalence record that aggregation queries may traverse and citations never do.

## Decision 6 — Human transcription is the trusted path until extraction earns parity

The claims store and its serving interface do not depend on automated extraction. Hand-
transcribed claims, validated by `validate_claims` against golden fixtures, are the initial
and reference content. Automated extraction is admitted per document type only when its
output matches the hand-built fixture for that type, and every claim records its extraction
method so the two populations remain distinguishable.

This is the generator-before-hardware sequencing (ADR-0010) applied to ingestion: the
consuming interface is proven with trusted content before the producing machinery is built.

## Decision 7 — A claim is its hash; the store is one file per document

A claim is addressed by the sha256 of its canonical serialization — Decision 5's move,
applied to the record itself. The serialization rules (member order, encoding) are defined
alongside the schema, before any record exists; they are load-bearing, because the id is
what a manifest cites, and together with Decisions 1 and 2 they freeze the record's shape
the moment the first claim is ingested. Content addressing needs no allocation authority,
makes Decision 3's append-only property checkable — a rewritten record is a different
claim — and lets two independent transcriptions of the same statement converge on one id,
which is what corroboration looks like as data.

The rejected alternatives fail in known ways: an id derived from position in a file
renumbers its neighbors when a claim is inserted, silently retargeting existing citations —
the URL-instability failure of Decision 5, rebuilt internally; an assigned id needs an
allocator, guarantees nothing about content, and gives identical transcriptions different
identities, so corroboration stops being detectable.

The stored artifact is one file per ingested document, in a top-level `claims/` registry
beside `components/`: the Decision 5 document record at the top, the document's claims and
its completeness attestation (Decision 4) under it. A claim's stored citation carries page
and locator; the document hash is stated once at file level, and the claim's canonical,
served form re-attaches it. Re-ingesting a revised document is one new file, never an edit —
with one named exception: appending the completeness attestation when a transcription pass
finishes is the sole legal mutation of an existing claims file. The claim records themselves
stay append-only, and because a claim id hashes record content and citation — never file
context — the append moves no identity; the stored-id verification catches anything else
that moved.

## Out of scope

Authentication and deployment of the serving interface, the extraction pipeline's internal
design, and any change to the component or module schemas beyond giving `source.kind:
datasheet` a resolvable referent. A later ADR may bind manifest fields to claim references
explicitly; this ADR only makes that binding possible.
