# ADR-0038 — Machine-readable sources

**Status:** Accepted — all twelve decisions taken

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

Decisions 1–5 settle what the pass proved. The open questions were the ones a second document
— a GSDML for the same device, or an EDS from another vendor — would answer better than
argument, and they were recorded so the answers would be deliberate rather than incidental.

### The second document

Two of those questions rested on a single file, which is the weakness ADR-0035 D3 exists to
guard against, so a second was mapped: the **Beckhoff ELX ESI**, `sha256:13359101…` (corpus
`bf3b11d`), 26 claims hand-selected from a 101,452-line, 2.8 MB EtherCAT description covering
42 devices. It was chosen to be as unlike the first as a device description can be — another
protocol (ADR-0002's), another format, another vendor, another specification body — because a
question about what generalizes is not answered by a second example of the same thing.

- **Identity generalized; transport did not.** Reaching for the EDS's generic keys first, five
  carried over unchanged and every EtherCAT structure key had to be minted. Decision 7.
- **The ordinary frequency test now fires.** Five identity keys appear in two documents from
  two manufacturers in two formats. Decision 8, which is why no special rule was needed.
- **Zero vocabulary keys bind** — worse than the EDS's one. The EDS at least declared
  `protocol = EtherNetIP`; the ESI never names its protocol, because being an ESI is how it
  says EtherCAT.
- **Still no units.** 26 values, 26 text, which is Decision 5 holding rather than failing.
- **New strains, none of them predicted:** the file is a catalog of 42 devices repeated per
  revision, it is bilingual throughout, it is ISO-8859-1, and Decision 1's line numbers work
  on it only because Beckhoff happens to pretty-print. Decisions 9 and 10.

### The third pass, over the second document again

Both passes so far read small devices, so neither met the content that makes these files
large: the **CoE object dictionary**. A third pass took ELX3184 from the same ESI (corpus
`41efad4`) — 4,191 elements against ELX1052's 53, with 73 objects, 128 data types and 140
subitems — to ask one question the earlier passes could not: *is a dictionary entry a claim?*

**It is sometimes, and the file says which.** 106 of the device's 140 subitems are `ro` — the
device stating facts about itself, `#x1000 Device type` and `#x1008 Device name` among them.
34 are `rw` and 24 carry `Flags/Setting 1`: values a master *writes* at commissioning. A
setting is not a property of a component; it is a property of a configured cell. The
transcription keeps them under separate keys so the distinction survives into the store, and
Decision 12 settles what of a setting belongs in this store at all.

That answer is what makes the scope question tractable. Transcribing every dictionary entry in
this file would be roughly ten thousand records, most of them settings and all of them `x-`,
which nothing downstream may consume (ADR-0035 D2). Vocabulary-complete for all 42 devices is
one to two hundred claims. The gap between those numbers is not a budget decision; it is the
difference between transcribing a document and transcribing a configuration.

Three further strains, each recorded rather than fixed: a parameter's facts are spread over
**three** elements up to 3,175 lines apart (Decision 1); values are printed as hexadecimal byte
strings whose meaning requires decoding (`454c5833313834` is the ASCII of `ELX3184`), and
decoding is interpretation ADR-0014 does not permit; and the only units in the device are
*inside labels* — `4-20mA` in a product name, `50 Hz FIR` in an enumeration — where a unit
qualifies a string rather than a number, so Decision 5 still has nothing to fire on.

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

**A strain this decision does not resolve, found by the third pass.** It assumes a statement
*has* a position. In XML a statement is frequently assembled from several. The ELX3184
parameter `Filter settings` is defined in `DataType DT8000` (line 33516), its default is
stated in `Object #x8000` (line 35491), and its legal values are enumerated in
`DataType DT0801EN16` (line 32333 onward) — three elements up to 3,175 lines apart, none of
which states the parameter by itself. The pass recorded three claims rather than one, which is
faithful and leaves the reader to reassemble; the alternative — one claim citing one of the
three lines with the rest in conditions — would cite a position the value did not come from,
which is worse than fragmentation. Whether a citation should be able to name several positions
is left open deliberately: it changes the hash scope, so it is the same blast radius as typed
positions, and it should be decided once, with that.

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

The format itself is a different axis, recorded in its own field rather than in this enum.
When this decision was taken no consumer needed to query it and the field was deferred; the
second document made the absence concrete, and Decision 9 added `document.format` — required
for this kind, meaningless for the others. `type` answers what kind of document this is;
`format` answers which format it is written in.

The name is deliberately the one the component schema already uses. That schema has carried
a `comms.device_description` field since before any of this — a free-text string whose
description reads *"Citation for the ESI/IODD/EDS (e.g. 'ESI available from vendor'). NEVER
a path to a file that does not exist."* The project had already reserved a place for
machine-readable descriptions and could express them only as prose, with a warning against
pretending the file was reachable. That field and this enum value are the same concept at
two layers: one says a component has such a description somewhere, the other says a
transcribed value came from one. They do not collide — an enum value inside `$defs.source`
and a property under `comms` are different scopes — and sharing the word is the point. If
the bytes an entry now holds (Decision 4) become reachable, `comms.device_description`
should stop being prose and start citing a document by hash, which is the whole distance
between "available from vendor" and a verifiable source.

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

Each decision below records what the passes observed before it was taken, because the
evidence is the part that gets lost — the reasoning can be re-derived from it, and cannot be
re-derived without it.

## Decision 4 — A machine-readable source's bytes may be held; none are served

Holding and serving were one question until the terms were actually read, and they are not
one question. They are separated here, and only the first is decided.

**Holding.** An entry may carry the ingested document's bytes as `document.<ext>` beside
`claims.yaml`, when a **terms check recorded in the document record** finds redistribution
permitted or unaddressed. The `redistribution` field states the terms consulted, the ISO
date they were read, and a verdict of `permitted`, `silent`, or `prohibited`; bytes may be
held on the first two and never on the third. `ci/check_claims.py` enforces both halves — an
entry holding bytes must record a verdict, and a `prohibited` verdict with bytes present is
a failure, not a warning.

**Serving stays off.** ADR-0036 D2 promises the registry never serves document bytes, and
that promise is not amended here. Serving is redistribution however authorized the caller,
it would need a size cap and a content type, and nothing currently asks for it. It becomes a
decision when a caller needs it — and it should require a `permitted` verdict, not a silent
one.

Why hold at all, given serving is off? Because it makes the hash **verifiable**. Until now
the store asserted `sha256:77e0fd12…` and no one — including its authors — could re-derive
it. An entry that holds its bytes turns the citation from a claim about a file into a
checkable fact, which is the same move ADR-0035 D7 made for claim ids. That value is
independent of anyone ever fetching the file.

ADR-0035 D5's reasoning is respected, not overturned. It keeps documents out because
redistributing a vendor's copyrighted catalog is not ours to do — and a 56 MB PDF written to
be read is a different artifact from a 103 KB device description written to be copied into
every integrator's project folder and shipped inside PLC vendor tool libraries. The class
boundary is explicit: bytes are held for documents whose terms were read and recorded, and
in practice that is the `device_description` kind. Every other entry remains cited by hash
alone.

What was read, for the AL1326: the file carries no license, copyright, or redistribution
text of any kind — its only notice is *"ATTENTION: Changes in this file can cause
configuration or communication problems."* The product page carries no terms for its
downloads. ifm's Terms of Service is a sales-and-software-licence document whose IP clauses
are scoped to ifm's own software products (*"the Cloud Software, Documentation, and related
services are provided under license, and not sold"*) and which says nothing about
downloading or redistributing website materials. Verdict: **`silent`** — not permission and
not prohibition, recorded as exactly that. A written answer from the vendor would upgrade it
to `permitted`, and that is the prerequisite for ever serving these bytes.

Consequence, applied immediately: the synthetic fixtures already held bytes and now record
why they may — authored by the project, CC BY-SA 4.0, verdict `permitted`. The question "by
what right are these bytes here?" is answered on every entry that holds any, including the
easy ones.

## Decision 5 — A unit defined by the format is a unit; the instance need not repeat it

All 81 parameters in the EDS declare an *empty* units string. CIP defines the RPI in
microseconds and assembly sizes in bytes; the file says neither, so every numeric fact in it
was recorded as text.

**A unit defined by the specification that governs an instance may be recorded as the
claim's unit.** The number stays exactly as printed — this is an attribution, never a
conversion, and ADR-0014's prohibition on converting units is untouched.

The distinction that makes this transcription rather than invention is where the unit is
read from. A datasheet routinely prints `[MPa]` in a row header and bare numbers in the
cells; the unit is transcribed from the header, because it is stated elsewhere in the same
document. A format specification is "elsewhere" one step further out — normative, published,
and binding on every instance of the format. The unit is stated; it is simply not restated
per file.

Two guard rails, and they are the decision as much as the principle is:

1. **The unit comes from the format specification or from nowhere.** Not from the
   transcriber's general knowledge, not from a sibling product's datasheet, not from what
   the number "obviously" is. If the specification does not define it, the value stays text.
2. **The entry must name the format and its edition** in the document record. A unit
   attributed to an unnamed authority is indistinguishable from one invented, and the whole
   provenance chain — claim → document → specification — depends on that last link being
   written down.

The mechanism for guard rail 2 now exists: `document.format`, Decision 9, added once a second
document made the absence concrete rather than theoretical. **A claim may carry a
format-defined unit only where the record names the format**; until a pass actually writes
one, machine-readable numerics stay text, as both passes so far have left them.

**What the field does not carry, and what that costs.** It names the format, not the format's
version. This ESI declares its own schema version — `EtherCATInfo/@Version` 1.2 — and the EDS
declares its equivalent differently, so a version field would have been defined against two
documents that could not fill it consistently. The cost is real and belongs here rather than
in a footnote: a unit this decision treats as fixed by a specification is fixed by a
specification that can be revised, and the record does not pin which revision it meant. That
is an honest gap. A field that looked precise and was not would be worse, and pinning becomes
answerable the moment a format's specification version is something a pass reads rather than
guesses.

Not retroactive. The AL1326 entry's 40 text claims stand as an honest hand pass over a file
that states no units. A later parser pass over the same document is a *new pass*, and the
store carrying both populations is exactly what ADR-0035 D6 anticipates.

The rejected alternatives. Leaving numerics as text forever is faithful and pushes CIP unit
knowledge into every consumer, privately and unrecorded — the implicit knowledge this store
exists to make explicit. Making units a property of `parsed` extraction (Decision 6) breaks
convergence outright: a hand pass would write text and a parser pass `{min: 1000, unit: µs}`,
two different values and two different ids for one statement, which leaves ADR-0035 D6's
parity test with nothing to measure. Format-defined units must therefore be applied by every
pass or by none — which is why this is a rule about claims, not about extraction.

## Decision 6 — `parsed` is the third extraction method

`extraction.method` becomes `human | automated | parsed`. A **`parsed`** record was produced
by a deterministic parser reading a format whose grammar is specified: neither hand judgment
nor model judgment, and a third population whose failure modes are systematic rather than
careless. When the method is `parsed`, `extraction` **requires `tool` and `tool_version`**,
and **may** carry `source_generator` — what the file declares about its own producer, never
required, because it is format-dependent.

The evidence for a third member rather than a stretched second one. Both passes so far
recorded `automated` with a tool string saying no parser was used — honest, and the wrong
shape, twice. And scale makes the parser inevitable rather than optional: 26 hand claims
covered one device at one revision out of 42 devices in 101,452 lines, about 0.03% of the
file. Hand transcription cannot reach the rest, and when a parser does it will emit claims by
the tens of thousands, whose provenance has to be distinguishable from those 26 by something
better than a sentence in a header comment. `source_generator` is optional for a reason the
two documents demonstrate between them: the EDS announces `EZ-EDS Version 3.25.1.20181218`,
and the ESI declares no generator at all.

`tool_version` is required where `tool` alone is not, because a parser's *version* is the
thing that changes what it emits. Two runs of "the ESI parser" over one file are the same
claim to a reader and potentially different transcriptions in fact, and the difference is
exactly what a parity test needs to see.

**Extraction stays outside the hash scope.** A parser version must never re-mint an id: the
whole point of excluding `extraction` is that a human pass and a machine pass of one statement
converge on one id, and the parity test needs that convergence to have anything to measure.
The consequence is accepted with open eyes — the store cannot tell, from ids alone, which
parser version produced a record. It can tell from the record.

### The encoding division

**A declared encoding is a property of the file, not of a pass.** It is recorded as
`document.encoding` — optional, descriptive metadata governed by Decision 3, so correctable in
place, and outside every hash scope. It holds what the source declares about itself
(`ISO-8859-1` for the Beckhoff ESI, `us-ascii` for the ifm EDS). A pass's obligation is then
simply stated: **transcode faithfully from the declared encoding.**

That division is what makes the problem tractable, and it does not make it disappear. The ESI
is ISO-8859-1, so transcribing it *is* transcoding — 174 non-ASCII bytes, `°`, `µ`, `ä`. Two
passes that resolve the encoding differently produce different `value` strings and therefore
different claim ids from identical source bytes. **The transcoding decision sits inside the
value, and therefore inside the id, while everything that records it — the document's declared
encoding, the parser, its version — sits outside.** That is the accepted trade, stated here
rather than discovered later: identity is over what a document was read to *say*, and reading
requires a decision that identity cannot hold. Recording the declaration on the document
record is what makes a disagreement diagnosable instead of invisible; it is not what makes it
impossible. The EDS was pure ASCII and never raised this, which is why one document could not
have decided it.

### Parity

**Parser-produced claims for a format are trusted once a `parsed` pass matches a hand pass
over the same document.** That is ADR-0035 D6's parity test with its third population finally
named: the hand pass is the measuring stick, the parser is the candidate, and agreement on ids
— not on prose, on ids — is the pass condition. Extraction being outside the hash scope is
what makes the comparison meaningful at all, since the two records differ in nothing else.
Trust earned this way is *per format*, not per parser: a parser that agrees on an EDS has
demonstrated nothing about its ESI path.

## Decision 7 — Identity keys are generic; transport-structure keys are protocol-namespaced

A key naming **what a device is** — vendor, product code, product name, catalogue number,
revision — is minted without a protocol prefix and shared across formats. A key naming **how a
protocol moves data** — assemblies, connections, FMMUs, sync managers, PDOs, modules and
slots — is prefixed with its protocol (`x-cip_assembly_size`, `x-ethercat_pdo`,
`x-profinet_module_*`).

The reason is what happens when two descriptions of one device meet. Joined by
`applies_to`, generic identity keys let a GSDML and an EDS corroborate or contradict each
other on the facts they both state, while namespaced transport keys let them describe one
device through two incompatible models without appearing to disagree about a shared one. A
CIP assembly and an EtherCAT PDO are not two answers to one question; flattening both onto
`x-io_size` would manufacture a conflict the specifications do not have.

**This was tested, not asserted.** The EDS pass predicted the split from one document. The ESI
pass ran it as an experiment: reach for the existing generic keys first, mint only what
nothing fits. Five identity keys carried over unchanged — `x-vendor_id`, `x-vendor_name`,
`x-product_code`, `x-product_name`, `x-catalog_number` — across two protocols, two formats and
two vendors. Every transport key had to be new, and not one of the EDS's assembly or
connection keys fit anything in an ESI. The prediction was falsifiable and survived.

**Where it did not survive, and what that teaches.** The prediction also named
`x-device_major_revision` as portable. It was not. An EDS prints `MajRev` and `MinRev` as two
fields; the ESI prints one `RevisionNo` of `#x00100000`. The concept is shared, the granularity
is not, and inventing a split the file does not make would have been exactly the conversion
ADR-0014 forbids — so the ESI records `x-device_revision` and the two documents remain honest
about their own shapes. Identity keys are portable at the level of *concept*, not at the level
of the source field. Any promotion of one (Decision 8) must therefore define the concept and
its value shape, and say what a format does when its granularity does not match — a question
the key's name alone will hide.

**Left unresolved by this decision: protocols nest.** The rule says "prefix with its
protocol" and does not say which protocol when there are two. A CoE object is CANopen,
carried over EtherCAT's mailbox, described in an ESI. The third pass minted `x-coe_object`,
`x-coe_parameter`, `x-coe_default_data` and `x-coe_enum_value` — naming the payload rather
than the carrier — on the reasoning that the same CANopen dictionary appears over CAN and over
Powerlink, so `coe` describes what the entry *is* while `ethercat` describes only how it
arrived. That reasoning is defensible and untested; a CANopen EDS would test it, exactly as
the ESI tested this decision's main clause.

**Also left unresolved:** a **record shape for structured entries**.
`x-assembly_definition` holds `Assem100 = "Assembly 100 Input ", "20 04 24 64 30 03", 446,
0x0000` as text, which is legal and unqueryable. A `record_assembly` (instance, name, path,
size, direction, optional members) would follow the `record_pinout` precedent — but Assem100
has ~223 members, so a record shape must say whether members are optional, or a claim becomes
a file. The ESI raises the same question in its own dialect: a PDO entry carries index,
subindex, bit length, data type and name, recorded here as one text value with the rest in
conditions.

## Decision 8 — No special promotion rule; ADR-0035 D3 stands

A key defined by a format specification is promoted the same way every other key is: frequency
nominates it, a stable cross-manufacturer meaning admits it. There is no shortcut for keys
whose meaning a specification fixes.

The question was whether to add one. `VendCode` means the same thing in every EDS ever
written, fixed by the CIP specification rather than by how many vendors happen to agree, and
with a corpus of one document the frequency test could never fire — so the discipline looked
like it was blocking a key nobody disputes.

It was not blocking; it was waiting, and it waited about a day. `vendor_id`, `vendor_name`,
`product_code`, `product_name` and `catalog_number` now appear in **two documents, two
manufacturers, two formats, two specification bodies** — the vendor identifier spelled
`VendCode` in one and `Vendor/Id` in the other.
That is precisely what D3 asks for, arrived at by the ordinary route. Adopting a
specification-authority shortcut would have bought a day and spent the property that makes D3
worth having: that it does not bend for a convincing single case, because a convincing single
case is what every over-generalization looks like from the inside.

Promotion of the identity keys is therefore unblocked on ordinary grounds. Which keys, and in
what shape — including the granularity problem Decision 7 records — is a separate and smaller
decision, taken against the vocabulary rather than here.

## Decision 9 — The document record names the format

A `device_description` record carries `document.format`: `eds`, `esi`, `gsdml`, `iodd`, with
the component schema's `x-` escape hatch for a format not yet enumerated. It is **required for
that kind and meaningless for every other** — a datasheet has no format in this sense.

Decision 2 said `type` names the kind, and the schema said in as many words that "which format
a document is written in is a separate axis". The axis did not exist. Two documents made the
absence concrete: an EDS and an ESI were distinguishable only by prose a human wrote in a
header comment and by the extension of the held file, and a consumer asking for ESI-sourced
claims had nothing to filter on. More sharply, Decision 5 *presupposes* the field — a unit
defined by the format can only be applied by a reader who knows which specification to
consult, and the record never said.

The field is **descriptive metadata**, so Decision 3 governs it: correctable, because
misidentifying a file's format is a description error rather than a false claim. It sits
outside every claim's hash scope, so correcting one moves no claim id — which is what made
backfilling the two existing entries a correction rather than a rewrite.

**Name only, not version.** The reasoning and its cost are recorded in Decision 5 rather than
repeated here.

Rejected: growing `document.type` a member per fieldbus, which Decision 2 already rejected for
the same reason — kind and format are different axes, and a `type` enum that grows with the
industry's protocol list stops naming a kind at all. Also rejected: inferring format from the
held file's extension, which works only for entries that hold bytes and makes a queryable
property of a document depend on whether this repository happens to store it.

## Decision 10 — A claim's `applies_to` carries the document's stated scope

**`applies_to` names the parts the DOCUMENT states the statement covers — never the subset a
pass happened to transcribe.** A file-level fact applies to every part the document
enumerates. The ESI's vendor block is a statement about all 42 devices in the file, so a claim
transcribing it names all 42, whether the pass that wrote it read one device or every one.

File-level facts stay **claims**. The alternative of moving them to the document record was
tempting and wrong: it would concede that vendor identity is provenance rather than a
transcription, and Decision 3 would then make it correctable — a fact cited to a line in a
file, silently editable, while everything around it is immutable. A document-level claim with
no `applies_to` was also rejected: ADR-0035 D1 says a claim is a datasheet-answerable
statement about a part, and a second kind of claim with a different shape is a cost paid by
every consumer forever.

**Enumerating the covered parts is part of transcribing a file-level statement**, not overhead
added to it. This is what family claims already do when a catalog states a series-wide
specification — the scope of the statement is itself something the document says, and reading
it is reading the document. It is also cheap: the enumeration is a list of `Type` elements.

Convergence follows, which is the whole point. **Two faithful passes of any scope mint one id
for one statement**, because the id no longer depends on how much of the file a transcriber
chose to read. The failure this replaces was the sharp one: `applies_to` is inside the hash
scope, so a one-device pass and a 42-device pass over the same vendor block produced *different
ids for the same statement* — not a disagreement about what the document says, but one
manufactured by the reading. Both passes faithful, both correct, and failing to corroborate.
That is exactly the convergence failure ADR-0035 D6's parity test exists to detect, arriving
from a direction the test cannot see. A datasheet never raised it, because a datasheet
describes the parts it names; a catalog file describing 42 devices under one vendor block does.

**Not retroactive, and nothing is retracted here.** The evidence passes' narrowly-scoped
records predate this rule. They are faithful artifacts of documented evidence passes — each
one says truthfully what it transcribed and how far it read — and they stand. A future full
pass over either document mints the correctly-scoped ids alongside them; whether the earlier,
narrower records then warrant cleanup under ADR-0037 is the operator's call at that time, on
evidence this decision does not have. Rewriting them now would be the store editing its own
history to look as though it had known better, which is the one thing an append-only store
exists to prevent.

## Decision 11 — Appends are idempotent; a store never holds one id twice

Two halves, at their proper layers, and neither is safe without the other.

**`append_claims` is an idempotent no-op per record.** A claim whose id is already present in
the file is skipped, not appended, and the result reports **`written`** and **`skipped`**
counts along with the skipped ids — so a caller sees exactly what happened rather than
inferring it. A retried, replayed, or nervously repeated submission is harmless and says so.

**`validate_claims` refuses a file holding two records with one id**, naming the id. That is
the invariant, and it is what makes trusting the no-op safe: duplication can never silently
persist, whether it arrives through the append path, a hand edit, or a merge that resolved
badly. The no-op prevents the ordinary case; the refusal catches every other one.

Refusing the append instead was rejected. It makes duplication visible at exactly the moment
nobody needs to see it — a retry that should be harmless fails, and the caller's only recourse
is to inspect the store and decide which of its records it already wrote. Visibility belongs
in the validator, where it is a property of the file rather than an accident of who called
what twice.

The evidence: `append_claims` computed each claim's id and appended it without ever asking
whether that id was present. Two transcribers reading the same statement in the same document
produce byte-identical records with the same id, and the file would hold both. Nothing is
corrupted by that — a matching id is *proof* the two records are identical, which is the
property content-addressing was chosen for — but nothing caught it either, and the store grew
a second copy of a record saying exactly what the first one said. That becomes ordinary rather
than hypothetical the moment a document has more than one contributor: a 2.8 MB ESI describing
42 devices is a document many passes will touch, each re-stating the file-level facts it needs
(Decision 10 is the same soft spot seen from the other side).

What is **not** at stake here: corroboration. Two different documents stating the same fact
produce different ids — the document hash is inside the hash scope — and are already distinct
claims, correctly. This decision is only about one document, one statement, twice.

## Decision 12 — A parameter's shape is a claim; its configured value never is

**The existence, shape, default and legal values of a parameter are claims.** That a device
has a parameter at this index and subindex, of this type and bit length, defaulting to this
value, admitting these enumerated values, is a datasheet-answerable fact about the part,
fully within ADR-0035 D1. A cell-design agent needs precisely this: it is how a configuration
is known to be *expressible* before anything is configured.

**A parameter's configured value is not a claim and never enters this store.** `Enable user
scale = 00` in some cell is not a fact about what an ELX3184 is; it is the state one
particular cell puts one into, and the identical device in the next cell holds a different
value. It belongs to whatever describes a configured cell — ADR-0014's layer — and the claims
store would be recording values true of nobody's device.

**The file's own access flags are the transcription cue.** A CoE dictionary holds both kinds
and distinguishes them itself: `Access ro` entries are the device stating facts about itself;
`Access rw` entries carrying `Flags/Setting 1` are values a master writes at commissioning.
For ELX3184 the split is 106 to 34, with 24 flagged as settings. A transcriber does not have
to adjudicate what is a fact and what is configuration — the format already did, and the
discipline records how to read that (`docs/ingestion.md`).

Note what this does *not* say: an `rw` parameter is not excluded. Its existence, type, bit
length, default and enumerated values are all transcribed — they are facts about the device.
What is excluded is the value some deployment happens to have written into it. The third pass
drew exactly this line in practice, transcribing shape and default and no configured values;
this decision is that line stated as a rule rather than left as one pass's good judgment.

The cost of getting it wrong in either direction is asymmetric and worth naming. Too
permissive, and the store fills with values true of nobody's device, which is worse than
useless because it looks authoritative. Too strict, and a design agent cannot tell whether a
device can be made to do what a cell needs — which is most of what a device description is
*for*.

## Out of scope

The parser itself, any GSDML or IODD ingestion, changes to the serving contract beyond what
Decision 4 already took, and any serving of bytes, which stays out until asked for. ESI
ingestion was out of scope when this ADR was drafted and is no longer: one was mapped by hand
to answer Decisions 7 and 8, and read a second time to answer the object-dictionary question,
on the same evidence-pass terms as the EDS — 59 claims across the two passes, no parser, every
strain recorded rather than fixed. `docs/ingestion.md` needs a machine-readable sources section —
preflight and glyph fidelity are inapplicable, and saying so belongs in the discipline rather
than in each entry's header — but that is a documentation task, not a decision.
