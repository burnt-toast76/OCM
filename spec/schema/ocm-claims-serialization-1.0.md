# OCM claims canonical serialization 1.0

Normative rules for computing a claim id (ADR-0035 D7). This document is versioned in
lockstep with `ocm-claims-1.0.schema.json`: the schema defines what a claim record may
say; this document defines the bytes its identity is computed from. A change to these
rules is a breaking change to the claims store — every existing citation names an id
these rules produced — so the rules are frozen from the moment the first claim record
is ingested.

There is exactly one implementation, `claim_id()`, beside `validate_claims`
(ADR-0016). No second implementation anywhere, in any language, in this repository.

## 1. The hash-scope object

A claim id is computed over a **hash-scope object** derived from the claim record. It
contains the claim's content and its citation, and nothing else:

| Member | In the hash | Notes |
|---|---|---|
| `key` | yes | |
| `subject` | when present | an omitted member is absent, never `null` (§2) |
| `value` | yes | |
| `conditions` | yes | always present on a record; may be `[]` |
| `applies_to` | yes | |
| `family` | when present | |
| `citation` | yes | `document`, `page`, `locator` — see below |
| `id` | **no** | it is the output |
| `extraction` | **no** | metadata; see below |

`extraction` is excluded deliberately: a human pass and an automated pass over the same
document differ exactly in extraction method, and ADR-0035 D6's parity test — and
corroboration generally — depends on the two producing the *same* id for the same
statement. Extraction method is a fact about the record, not about what the document
said.

The `citation` inside the hash-scope object always carries the document hash, even
though the stored claims file states that hash once at file level (ADR-0035 D7): the
hash-scope citation is `{document, page, locator}`, with `document` copied from the
file's document record. Without it, identical text in two different documents would
collide into one id, and corroboration would be indistinguishable from duplication.
With it, the same statement printed in two places in one document yields two ids —
accepted as two distinct claims, each citing exactly where it appears, so
intra-document discrepancies stay visible instead of silently merging.

`page` is the printed page number, as the document labels it; PDF position is used
only when the document's pages are unlabeled, and the locator should then say so.
Without this convention, two correct transcriptions of the same statement disagree on
`page` and mint two different ids — a fabricated discrepancy where the documents have
none.

## 2. Canonical bytes

The hash-scope object is serialized by **RFC 8785 (JSON Canonicalization Scheme)**:
UTF-8 encoding, members sorted lexicographically by UTF-16 code units, ES6 number
serialization, minimal string escaping, no insignificant whitespace. The rules are
RFC 8785's, not this document's — consult the RFC for edge cases; the reference
implementation used here is the `rfc8785` Python package.

This document adds exactly one rule on top of the RFC, which has no opinion on
absence: **an optional member that is not present is absent from the hash-scope
object.** No member is ever serialized as `null`; `null` is not a valid value anywhere
in a claim record. A claim with a subject and a claim without one therefore serialize
— and hash — differently, which is the point: the absence is itself transcription
(ADR-0035 D1).

## 3. Numbers

Numeric values are JSON numbers, serialized by RFC 8785's ES6 rules. A consequence,
accepted deliberately: printed trailing precision is not representable — a document's
"6.0" and another's "6" both canonicalize to `6`. If printed precision ever becomes
load-bearing, an additive optional verbatim field can carry it; being optional and
new, it is absent from every existing hash-scope object and changes no existing id.

## 4. The id

```
id = "sha256:" + lowercase hex SHA-256 of the canonical bytes
```

The same format the document record uses for its hash: one self-describing
content-address format everywhere a hash appears, algorithm named in-band.

Every claim record stores its `id`, and `validate_claims` recomputes and verifies it,
refusing on mismatch. That check is what makes the store's append-only property
enforceable rather than conventional: any edit to an ingested record — including a
well-meant typo fix — changes its true hash, and the stored id gives it away.

## 5. A claims file changes in exactly three ways

Informative restatement of ADR-0035 D7 and ADR-0037 D2: an existing claims file has
exactly three legal mutations — appending the claims a later transcription pass
produces, appending that pass's vocabulary-pinned completeness attestation (ADR-0035
D4), and appending a retraction record when a claim is found not to transcribe its
source faithfully (ADR-0037). Existing records are never edited or removed; this is
append-only in exactly D3's sense. Claim ids hash record content and citation, never
file context, so the appends move no identity; the stored-id verification above catches
anything else that moved. A retraction record itself carries no id and is outside every
hash scope — it names a claim id, it never has one — so retracting a claim changes no
identity either: the retracted record's bytes, id, and citation all still verify.

## 6. Worked examples

Both examples cite an example document whose hash is the SHA-256 of the ASCII bytes
`ocm example datasheet`:

```
sha256:c03286e02ea14374f3b7e69ffb4d9616125bc7db49b9f397a1cb716211a290bb
```

All values are obviously synthetic (ADR-0014); the arithmetic is real and
reproducible.

### 6.1 A subject-bearing claim (text shape)

The claim as stored in its claims file — `extraction` present, citation without the
document hash (stated at file level), `conditions: []` attesting the document states
none:

```yaml
- id: sha256:4a37e484097417013ebc6be947b0aeabefaa0ffa25de7f53715af7c812a99b13
  key: output_configuration
  subject: OUT2
  value: PNP/NPN selectable
  conditions: []
  applies_to: [EX-100]
  citation: {page: 2, locator: "spec table, row 'Output 2'"}
  extraction: {method: human}
```

The hash-scope object (document re-attached; `id` and `extraction` excluded), as
canonical bytes — one line, sorted members, no whitespace:

```json
{"applies_to":["EX-100"],"citation":{"document":"sha256:c03286e02ea14374f3b7e69ffb4d9616125bc7db49b9f397a1cb716211a290bb","locator":"spec table, row 'Output 2'","page":2},"conditions":[],"key":"output_configuration","subject":"OUT2","value":"PNP/NPN selectable"}
```

SHA-256 of those bytes:

```
sha256:4a37e484097417013ebc6be947b0aeabefaa0ffa25de7f53715af7c812a99b13
```

### 6.2 A spread with `unqualified` (and a family)

The document prints "6 bar (max 8 bar)" — an unqualified working value alongside a
qualified bound, transcribed as exactly that:

```yaml
- id: sha256:38fedc6c90e0700ad64da4fadbd70b20a9832e274e3a5d2adf5f2ee8e2d3f16e
  key: operating_pressure
  value: {unqualified: 6.0, max: 8, unit: bar}
  conditions: ["filtered, non-lubricated air"]
  applies_to: [EX-200, EX-201]
  family: EX series
  citation: {page: 1, locator: "table 'Specifications', row 'Operating pressure'"}
  extraction: {method: human}
```

Canonical bytes — note `unqualified` entered as `6.0` and canonicalized to `6` (§3),
no `subject` member because this key takes none, and `family` present because the
document states its coverage that way:

```json
{"applies_to":["EX-200","EX-201"],"citation":{"document":"sha256:c03286e02ea14374f3b7e69ffb4d9616125bc7db49b9f397a1cb716211a290bb","locator":"table 'Specifications', row 'Operating pressure'","page":1},"conditions":["filtered, non-lubricated air"],"family":"EX series","key":"operating_pressure","value":{"max":8,"unit":"bar","unqualified":6}}
```

SHA-256 of those bytes:

```
sha256:38fedc6c90e0700ad64da4fadbd70b20a9832e274e3a5d2adf5f2ee8e2d3f16e
```
