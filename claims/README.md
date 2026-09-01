# Claims

This is the **claims registry** (ADR-0035): what each ingested document says, transcribed
as claims. One directory per document, named by the sha256 of the document file it
contains; `claims.yaml` holds the document record, its claims, and its completeness
attestations. Records are append-only; ids come from `claim_id()` per
`spec/schema/ocm-claims-serialization-1.0.md`; validate with `validate_claims`.

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
