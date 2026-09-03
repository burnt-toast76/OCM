# Claims

This is the **claims registry** (ADR-0035): what each ingested document says, transcribed
as claims. One directory per document, named by the sha256 of the document file it
contains; `claims.yaml` holds the document record, its claims, and its completeness
attestations. Records are append-only; ids come from `claim_id()` per
`spec/schema/ocm-claims-serialization-1.0.md`; validate with `validate_claims`.

## What is here, and what is not

**The entries here are reference fixtures.** The two synthetic example documents and
their claims are what the schema, the validator, the vocabulary binding, and the serving
goldens are exercised against — a contributor can clone this repository alone and run
every check green. They stay here forever, with the `document.txt` bytes they are
hash-anchored to.

**The production corpus is private and served, not distributed.** The real-document
entries — manufacturer datasheets and catalogs transcribed under ADR-0035 — live in a
separate repository, read as a second claims root when `OCM_CORPUS` names its checkout
(ADR-0036 D8 as amended). Nothing about the format differs: same layout, same schema,
same ids, same one validator. Only the location and the license differ.

**Entries previously published here remain in this repository's history, under the
license they were published with.** The FS-N41N datasheet and the FS-N40, LR-X, and NEO
catalog entries were public here before the split; those commits are unchanged and
CC BY-SA 4.0 still covers those published versions. No history was rewritten to pretend
otherwise — the corpus repository cites those commits rather than replaying them.

## License scope (CC BY-SA 4.0 — see [LICENSING.md](../LICENSING.md))

- The **compilation** — the selection, arrangement, and transcription apparatus of this
  registry — and the **synthetic example documents** are © the OCM project, licensed
  CC BY-SA 4.0.
- Individual claims record **facts** (a voltage range, a pin assignment, a temperature
  limit). Facts are not copyrightable; nothing here asserts ownership of a fact, and
  citing or using facts from this registry creates no obligation under this license.
  Share-alike reaches redistribution or adaptation of the registry as a compilation.
- **Source manufacturer documents** are never included in this repository and remain
  their publishers'. Claims cite them by content hash (ADR-0035 D5) precisely so the
  documents themselves stay out.
