# Ingestion discipline

Normative rules for every claims-ingestion pass, codified from the first three
real-document entries — the FS-N40 (`cfdb33d3…`), LR-X (`7d467249…`), and NEO
(`ee031e7c…`) catalogs — and governed by ADR-0035 D4–D7. Where a rule here restates
an ADR decision, the ADR is the authority; where it codifies a precedent, the named
entry is the precedent. A pass that cannot follow a rule stops and says so; it does
not improvise (ADR-0014).

## Where a pass commits

**Real-document entries are committed to the production corpus repository**, not to
this one. `claims/` here holds the reference fixtures (see `claims/README.md`); the
corpus is a separate, private repository read as a second claims root through
`OCM_CORPUS` (ADR-0036 D8 as amended). The precedent entries named above live there
now, and their transcription history stays in this repository's commits, cited from
the corpus rather than replayed into it.

An ingestion session therefore needs both checkouts: this one for the tooling, the
schema, and the vocabulary — everything a pass reads — and the corpus for the store it
writes. Nothing else in the discipline changes: the same preflight, the same verbatim
transcription, the same attestation rule, the same one validator. Only the working
tree the new entry lands in is different.

## Source acquisition

Prefer the manufacturer's own un-gated URL (ADR-0035 D5; `claims/README.md`) and
record it in the document record's `url`. When the ingested copy carries no URL, the
entry's header comment MUST carry an **acquisition note** — where and when the copy
was obtained — so provenance survives without a re-fetch path. This rule is
forward-looking: the LR-X and NEO entries note the absence of a URL without an
acquisition note and are not edited retroactively. When a URL exists, a Wayback
Machine save of it at ingest time is recommended: the hash pins the bytes forever
(D5), but a mirrored copy is what lets a future reader obtain them.

## Vocabulary binding

Every pass reads the CURRENT vocabulary before transcribing a single claim, and the
header comment states the version bound against ("bound against vocabulary 1.2").
New claims use bound keys wherever the vocabulary — its entries and their
`aliases:` — covers the statement's meaning; `x-` spellings are for statements the
vocabulary genuinely lacks, nothing else. **An alias's old spelling is never written
in a new pass.** Aliases exist so immutable history binds (ADR-0035 D3), not as
go-forward spellings: the NEO pass wrote 225 claims under alias spellings of
already-promoted keys — legal via binding, but exactly the drift this rule stops,
and `ci/check_alias_drift.py` now refuses it.

## Preflight

Mandatory, every page in scope: run the extraction preflight
(`ocm_api.claims_preflight`) and resolve every hazard against the rendered page
image before transcribing from that page. A hazard that cannot be resolved makes its
cell a named skip, never a guess — the FS-N40's FU-67TG bend radius, skipped and
later resolved from the render against the plausible guess, is the standing example
of why.

## Units

Values are recorded in the exact unit printed (ADR-0014). When the document declares
one unit system original and the other converted — the FS-N40, LR-X, and NEO
catalogs all print "The specifications are expressed in metric units. The English
units have been converted from the original metric units" (p24 / p68) — only the
original system is transcribed, and the header cites the declaration. The converted
figures are the document's own arithmetic, not separate statements.

## Glyphs

Each page is transcribed with the codepoints it prints. A document that mixes
confusable glyphs notes it in the header: the NEO catalog prints U+03BC on
pp.17/42/57 and U+00B5 on p65, so two response-time claims that read alike differ in
bytes, and in id, on purpose. The preflight's glyph inventory is the detection; the
header note is the record.

## Restatements

A statement the document prints at multiple locators is transcribed **once, at its
most authoritative locator** — a specifications table over a lineup summary — and
the header names the restatement locators that were checked and skipped (the LR-X
p15 note is the form). Exception, absolute: when restatements **disagree**, every
disagreeing statement is transcribed at its own locator — a document contradicting
itself is a fact the store carries, never resolves. Cross-document corroboration is
unaffected (distinct documents always transcribe independently), and the eps25
fixture's deliberate duplicate remains as the serialization spec's
distinct-ids-by-design golden, not a precedent for passes.

## Partial passes and attestation

A pass states its scope page-by-page in the header — transcribed and
not-transcribed both — so an absent key reads as "not yet checked", never "the
document is silent" (ADR-0035 D4, ADR-0036 D3). The attestation is appended only
when every applicable vocabulary key at the bound version is covered for the whole
document; a partial pass carries none. `extraction.method` states how the claims
were actually produced: drafted by an agent — however carefully reviewed — is
`automated`, with the tool named; `human` means a human transcribed. The FS-N41N
relabel (commit `18b63d8`) is the precedent: mislabeling agent output as `human`
contaminates the trusted population D6's parity test measures against.

## End-of-pass report

Every ingestion session ends by reporting its `x-` key frequency table — count,
documents, value shapes — as the demand signal for the next vocabulary revision
(ADR-0035 D2/D3: frequency nominates). The table is reported, not committed: the
store itself is the tally, and the report is recomputed from it.
