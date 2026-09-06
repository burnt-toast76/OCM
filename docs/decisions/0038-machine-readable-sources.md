# ADR-0038 — Machine-readable sources

**Status:** Proposed — Decisions 1–3 taken; Questions 4–8 🔴 **OPEN**

**Builds on:** ADR-0035 (claims, citations, attestations), ADR-0036 (serving),
ADR-0037 (corrections under append-only), ADR-0014 (zero assumption)

## Context

Every document in the claims store so far has been a PDF written for a human: a datasheet,
a catalog. The discipline in `docs/ingestion.md` grew around that — preflight exists because
a PDF's text layer lies about what is printed, glyph inventories exist because a rendered
page is the arbiter, and `citation.page` exists because paper has pages.

Devices also ship **machine-readable descriptions**: EDS for CIP/EtherNet-IP, GSDML for
Profinet, ESI for EtherCAT, IODD for IO-Link. They state device facts a cell-design agent
needs — how many bytes an assembly carries, what a port can be configured to do, the range
an RPI accepts — and they state them in a form nobody reads. Whether they belong in the
claims store, and what breaks when they arrive, was unknown.

So one was mapped by hand: the **ifm electronic AL1326 IO-Link Master EDS**, 2401 lines,
ingested as `sha256:77e0fd12…` (corpus `0a8b2ba`). The pass was deliberately an evidence
pass — 40 claims, no parser, every strain recorded rather than fixed. What it found:

- **One vocabulary key binds in the entire file.** `protocol = EtherNetIP`, and 39 claims
  under 17 new `x-` keys. The vocabulary is datasheet-shaped — volts, millimetres,
  temperatures — and a network device description shares almost nothing with it.
- **No numeric shape is usable.** All 81 parameters declare an *empty* units string, and no
  other numeric entry states a unit either. `scalar` and `spread` both require a non-empty
  `unit`, so assembly sizes, the RPI range and the CIP vendor and product codes are all
  recorded as text: 38 of 40 values text, 2 list, **zero scalar or spread**.
- **`citation.page` had nothing to hold.** The file has no pages.
- **`document.type` had no honest value.** The entry records `datasheet` with a header
  paragraph disowning it.
- **A third of the ingestion discipline does not apply.** Preflight and glyph fidelity are
  properties of rendering; this file *is* text, with no second extraction to cross-check.

Decisions 1–3 settle what the pass proved. The open questions are the ones a second document
— a GSDML for the same device, or an EDS from another vendor — would answer better than
argument, and they are recorded now so the answers are deliberate rather than incidental.

## Decision 1 — Position in a citation is the source's own smallest addressable unit

`citation.page` carries the **1-based line number** for a source with no pages, and the
locator says which section and entry (`"[Device], ProdCode"`). The serialization spec's
existing rule is extended, not replaced: it already permits `page` to hold a PDF position
when a document's pages are unlabeled, provided the locator discloses it.

That rule exists for **convergence** — "two correct transcriptions of the same statement
disagree on `page` and mint two different ids — a fabricated discrepancy where the documents
have none." A line number serves that purpose better than anything else available: it is the
only positional coordinate two independent transcribers of an EDS both compute identically,
and it is more deterministic than the PDF index the rule already blesses.

The rejected alternatives both re-mint ids for records that are already correct. An optional
`line` member beside `page` would make `citation` a two-shape object every consumer must
handle, and (since `page` is required and `citation` is `additionalProperties: false`) it
cannot be added without changing what the hash scope contains. A typed
`{kind: line, value: 2336}` position is the cleanest model and the worst blast radius: it
re-mints every id in the store, not just this document's.

Accepted knowingly: the field is named `page` and holds a line. The locator is what
disambiguates, and it always begins with a section name no consumer can mistake for a page
label. If position ever becomes typed, this is the decision to revisit — and the cost of
revisiting grows with every machine-readable entry, which is why it was taken first.

## Decision 2 — `device_description` is a document kind

`document.type` gains **`device_description`**, and so does the component schema's
`source.kind`. The two enums are married by design — `type` is documented as "the component
schema's `source.kind` minus `measured`" — so a value added to one without the other makes
that stated relationship false, and leaves a component unable to say what it cited.

One value covers EDS, GSDML, ESI and IODD because they are one *kind*: machine-readable,
page-less, semantics defined by a format specification rather than by prose, published to be
consumed by tools. Per-format enum values (`eds`, `gsdml`, …) were rejected for conflating
kind with format — `type` does not say "PDF" for a catalog either — and because the enum
would then grow with every fieldbus and every revision of one.

The format itself is therefore *not* recorded in the document record today. `type` answers
what kind of document this is; which format it is written in is a different axis, and no
consumer yet needs to query it. Question 4 is where that changes: serving bytes is exactly
when a caller must know the format before it fetches.

The name is deliberately the one the component schema already uses. That schema has carried
a `comms.device_description` field since before any of this — a free-text string whose
description reads *"Citation for the ESI/IODD/EDS (e.g. 'ESI available from vendor'). NEVER
a path to a file that does not exist."* The project had already reserved a place for
machine-readable descriptions and could express them only as prose, with a warning against
pretending the file was reachable. That field and this enum value are the same concept at
two layers: one says a component has such a description somewhere, the other says a
transcribed value came from one. They do not collide — an enum value inside `$defs.source`
and a property under `comms` are different scopes — and sharing the word is the point. If
Question 4 lands, `comms.device_description` should stop being prose and start citing a
document by hash, which is the whole distance between "available from vendor" and a
verifiable source.

## Decision 3 — The document record is descriptive; only claim records are immutable

ADR-0035 D7 says "existing records are never edited or removed," and ADR-0037 added
retraction as the third legal mutation of a claims file. That immutability is scoped, here
and from now on, to **claim records and their retractions**. The **document record** —
`manufacturer`, `type`, `revision`, `date`, `url` — is descriptive metadata and may be
corrected in place, as an ordinary edit visible in git history.

The distinction is not a convenience; it is what the mechanism can actually enforce.
`claim_id()` hashes key, value, conditions, applies_to, subject, family, and the citation
with the document **hash** re-attached. It does not hash any other document-record field.
So the stored-id verification that makes append-only *enforceable* rather than conventional
is structurally blind to `type` and `url`: no claim identity depends on them, and an edit
there moves nothing. `document.hash` remains identity and remains untouchable — a document
whose bytes differ is a different document, always.

Consequence, applied immediately: the AL1326 entry's `type` becomes `device_description`,
and its 40 claims and their ids are untouched.

---

The remaining questions are open. Each is recorded with what the EDS pass observed, because
the evidence is the part that gets lost.

## Question 4 🔴 — Does the corpus hold, and does the server serve, source bytes?

ADR-0035 D5 keeps manufacturer documents out of the repository and cites them by hash,
because redistributing a vendor's copyrighted catalog is not ours to do. **That reasoning
may not transfer.** An EDS is published *to be* redistributed: it ships inside PLC vendor
tool libraries, gets committed to integrators' project repositories, and is worthless unless
copied. And the practical case is sharp — an agent that can retrieve the exact EDS can
configure a connection; one holding 40 claims about it cannot.

**The blocker is vendor terms, and they are unread.** The AL1326 EDS carries no license,
copyright, or redistribution text of any kind; its only notice is "ATTENTION: Changes in
this file can cause configuration or communication problems." The ifm product page shows no
visible terms for its downloads. ifm's general Terms and conditions were **not** inspected.
Silence is not permission.

- **Option A — Hold and serve bytes**, gated on a per-vendor terms check recorded in the
  document record (a `redistribution` field naming the terms URL and the verdict).
  ⚠️ `get_document` gains a bytes path, which needs a size cap and a content type — and
  ADR-0036 D2's "never document bytes" stops being true, so it must be amended, not bent.
- **Option B — Hold bytes, serve none.** The corpus can verify a hash it holds; callers
  still get citations only.
- **Option C — Neither.** Status quo; machine-readable sources stay cited, never carried.

## Question 5 🔴 — Are units defined by a format, rather than by an instance, expressible?

All 81 parameters declare an empty units string. CIP defines the RPI as microseconds and
assembly sizes as bytes; **the file says neither**. Transcribing "µs" would be fabrication
under ADR-0014, so every numeric fact in the document is text — which means it cannot be
compared, converted, or sorted downstream.

- **Option A — A format-defined unit is a unit**, carried with a marker naming its authority
  (`unit: µs`, `unit_source: CIP Vol 1`). ⚠️ It is no longer "as printed."
- **Option B — Numeric shapes stay unusable** for this document class; text is the honest
  answer and consumers parse at their own risk.
- **Option C — A parser supplies units from the format spec**, making it a property of
  `parsed` extraction (Question 6) rather than of the claim.

## Question 6 🔴 — Is `parsed` a third extraction method?

`extraction.method` is `human | automated`. A deterministic parser is neither: ADR-0035 D6's
parity test measures automated output against hand transcription, and a parser is a third
population whose failure modes are systematic rather than careless. This pass recorded
`automated` with a tool string saying no parser was used — honest, and the wrong shape.

A `parsed` method would record parser identity and version, the format and its specification
version, and possibly the generator string the source declares (this file announces
`EZ-EDS Version 3.25.1.20181218` — provenance about how the source was produced, not how it
was read). **The sharp part:** `extraction` is deliberately outside the hash scope so a human
and an automated pass of the same statement converge on one id. A parser version must not
re-mint ids, so it stays outside — which means the store cannot tell, from ids alone, which
parser version produced a record.

## Question 7 🔴 — Are network keys protocol-namespaced or generic?

The pass minted 17 `x-` keys, and they split cleanly. **Device identity** —
`x-vendor_id`, `x-product_code`, `x-product_name`, `x-catalog_number`,
`x-device_major_revision` — exists in every fieldbus format under different spellings
(`VendCode` in EDS, `VendorID` in GSDML, `VendorId` in ESI) and means the same thing.
**Transport structure** — `x-assembly_size`, `x-assembly_definition`, `x-connection_name`,
the RPI range — is CIP and only CIP. Profinet has no assemblies; it has modules, submodules
and slots. EtherCAT has PDOs and sync managers. IO-Link has process-data lengths and a
minimum cycle time.

The recommendation from this evidence is **generic keys for identity, namespaced keys for
transport structure** (`x-cip_assembly_size`, `x-profinet_module_*`), so that when a GSDML
for the same device lands under its own hash and joins via `applies_to: [AL1326]`, the two
documents visibly describe one device through two incompatible models rather than appearing
to contradict each other. It is recorded as a question, not a decision, because it is argued
from a single document — the weakness ADR-0035 D3 exists to guard against.

Related and unresolved: a **record shape for structured entries**. `x-assembly_definition`
holds `Assem100 = "Assembly 100 Input ", "20 04 24 64 30 03", 446, 0x0000` as text, which is
legal and unqueryable. A `record_assembly` (instance, name, path, size, direction, optional
members) would follow the `record_pinout` precedent — but Assem100 has ~223 members, so a
record shape must say whether members are optional, or a claim becomes a file.

## Question 8 🔴 — Can a format-defined key be promoted from one document?

ADR-0035 D3 promotes an `x-` key when frequency nominates and a stable cross-manufacturer
meaning admits. Every one of these 17 keys appears in exactly one document, so by that test
none is promotable. But `VendCode` means the same thing in **every EDS ever written** — its
meaning is fixed by the CIP specification, not by how many vendors happen to agree.

- **Option A — Format-defined keys promote on the specification's authority**, from one
  document plus a citation to the spec that defines the field.
- **Option B — The existing rule stands.** Wait for a second EDS; the discipline's value is
  that it does not bend for a convincing single case.

## Out of scope

The parser itself, any GSDML/ESI/IODD ingestion, and changes to the serving contract beyond
what Question 4 would require. `docs/ingestion.md` needs a machine-readable sources section —
preflight and glyph fidelity are inapplicable, and saying so belongs in the discipline rather
than in each entry's header — but that is a documentation task, not a decision.
