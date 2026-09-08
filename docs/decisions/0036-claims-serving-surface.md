# ADR-0036 — Claims are served read-only, with provenance on every value

**Status:** Proposed

**Builds on:** ADR-0035 (claims, citations, attestations), ADR-0016 (one validation
surface), ADR-0014 (zero assumption)

## Context

ADR-0035 built the write side of the claims store, and the registry now holds real
content: two synthetic golden fixtures, an ingested datasheet, and an ingested catalog —
229 claims across four documents, every value citing its document by hash. Nothing can
read any of it except a human with a YAML editor.

The consumer this store exists for is an AI agent authoring components and modules —
Cellwright's own agent first, third parties later — and the natural interface is an MCP
server. That ordering has a consequence: the read contract (tool names, parameters,
response shapes) is cheap to change until the first third party connects, and effectively
frozen after. So the contract is decided here, before any server code exists, and the
implementation follows the contract rather than the reverse.

One asymmetry drives most of what follows. The write side's discipline (verbatim
transcription, conditions, attestations, content-hash identity) is worthless if the read
side leaks bare values: a consumer that receives "30 V" with no citation has learned a
rumor with good posture. Provenance is the product.

## Decision 1 — The tool set: nothing writes to the registry, ever

The server exposes three serving tools:

- `get_claims(part_number, keys?)` — the claims covering one part. With `keys` omitted it
  returns everything for the part (Decision 7's sizing applies): omission is the
  discovery path, naming keys is the retrieval path.
- `search_parts(query)` — approximate lookup over part numbers and `family` strings,
  returning candidates for the agent to choose from. Not claim text: that is a different
  product with real relevance problems, added when demand shows up, not before.
  *(Widened by Decision 9 to cover manufacturer names, which are identifiers on the
  document record rather than claim text. The exclusion of claim text is unchanged.)*
- `get_document(hash)` — a document record's metadata and its registry citations, never
  document bytes; the repository does not hold real manufacturer documents
  (ADR-0035 D5, `claims/README.md`) and the server cannot serve what the store
  deliberately excludes.

Nothing else serves in v1: no vocabulary tool (the vocabulary rides in the server's
instructions — it is small, changes by pull request, and every envelope names the version
it was served under), and no manifest tools. **No tool writes to the registry — not in
v1, not ever.** Ingestion is a separate concern with its own machinery. Additions to
this contract are backward-compatible; removals never are, which is why it starts
minimal.

One tool exists outside the serving set, added by amendment and registered only when its
credentials are configured: `request_coverage(manufacturer, part_number, source_url?,
note?)` appends a demand record to the **coverage queue** — GitHub issues labeled
`coverage-request` on the public repository, deduplicated on the normalized
(manufacturer, part number) key so repeat requests stack visibly into ranked demand. The
queue is not the registry: it feeds the human-supervised ingestion pipeline and cannot
place, alter, or delete a claim, so the rationale this decision began with — nothing can
pollute the store — survives intact. The two absence states that mean "the store cannot
answer" (`no_documents`, `absence_not_yet_meaningful`, Decision 3) are the trigger: the
consuming agent may OFFER the user a coverage request on them and files one only when
the user says yes. A source URL is optional by design — vendor logins gate many of
them, so manufacturer plus part number is a complete request and the operator resolves
the document — and no file or document intake passes through this tool.

## Decision 2 — Provenance on every value; the serving layer never computes

Every response envelope carries the vocabulary version, the serving-state identifier
(Decision 8), and the queried part's attestation status. Every served value carries its
claim id and its full citation — document hash, page, locator — inline. There is no
envelope path, flag, or convenience mode that strips citations: response size is managed
by Decision 7's sizing, never by dropping provenance, because a provenance-optional
default becomes the rumor mode agents actually use.

Spreads are served verbatim and only verbatim: no normalized-SI convenience block, no
derived numbers of any kind. The claims layer never computes (ADR-0035 D1 gives it no
single-number accessor; ADR-0014 makes conversion a downstream-code concern), and the
consumer of this server is an agent — precisely the consumer capable of doing its own
conversion visibly, in its own layer. A server-side conversion would also be the one bug
that poisons every consumer at once.

## Decision 3 — Absence has three answers

A query for a key with no claim is answered with one of four distinct states, never a
bare empty list:

1. **Attested silence** — every document on file for the part is attested complete at the
   current vocabulary and none states the key. This is ADR-0035 D4's `not_found`, served:
   the consulted documents are listed, and the absence is information an author may rely
   on (an omitted manifest field is legitimate exactly when the datasheet genuinely
   doesn't answer, ADR-0014).
2. **Absence not yet meaningful** — documents are on file but at least one lacks an
   attestation at the current vocabulary. Nobody has established the document is silent;
   the envelope says so.
3. **No documents on file** for the part at all.
4. **Unbound key, never attested** — the queried key is outside the vocabulary (an `x-`
   key, or no vocabulary key at all) and documents are on file. An attestation's promise
   is full transcription against a vocabulary (ADR-0035 D4), and a statement outside the
   vocabulary is outside that promise — so silence on an unbound key is never attested
   silence, whatever the part's attestation status. State 3 still wins when nothing is
   on file.

The registry already exhibits all four, and flattening any pair fabricates certainty —
the exact ambiguity the attestation machinery exists to kill.

## Decision 4 — Exact resolution after stated normalization

`get_claims` resolves a part number by exact match after normalization, and the
normalization is normative here so implementations cannot drift: case-fold both sides and
strip the separator characters space, hyphen, underscore, and dot. `FS-N41N`,
`FS N41N`, and `fs-n41n` are the same part; nothing else is.

A part covered only through a `family` claim still resolves, and the envelope labels it
(`matched_via: family`) — family coverage is served as family coverage, never passed off
as part-exact. Family resolution triggers when the query itself, normalized, exactly
matches a family string: `get_claims("EPS25 series")` resolves. An *unlisted* member
(EPS25-50WC-1001) does not — inferring membership from a prefix is fuzzy matching wearing
a different hat, and `search_parts` surfaces the family for the agent to query
explicitly.

There is no fuzzy matching in `get_claims`. A near-miss that quietly resolves FS-N41N to
FS-N41P would serve the wrong part's electrical ratings with full provenance attached —
confidently wrong, the worst failure this system can produce. Approximate lookup lives in
`search_parts`, which returns candidates for the agent to choose rather than choosing
itself.

## Decision 5 — A disposable index; the files are the truth

The server builds an index (in-memory or SQLite) from the claims files at startup,
reading through `ocm_api`. The files remain the sole source of truth; the index is
rebuilt on every start, never committed, and carries no state a restart loses. Building
the index runs the registry through `validate_claims`, and a registry that fails does not
get served — a guarantee no per-query design provides cheaply.

Reload is startup-only: restart the server to pick up new ingestion. Ingestion is
git-commit-paced, not real-time, and one process lifetime serving exactly one registry
state is what makes Decision 8's identity coherent — a file-watching reload would let one
conversation's answers silently span two registry states.

## Decision 6 — `software/ocm-mcp/`, presented as `ocm-claims`

The server is a new package, `software/ocm-mcp/`, a sibling of `ocm-api` that imports it:
validation, id computation, and claims access have exactly one implementation
(ADR-0016), and the serving layer reads through that surface, never around it. The
read-only boundary is a package boundary — distinct from `ocm_api.mcp_server`, which is
the read-write *authoring* surface — so future serving dependencies (remote transport,
auth) never ride along on an authoring install. `software/` licensing applies: AGPL-3.0.

To MCP clients the server presents as `ocm-claims`: it serves claims, and does not squat
on the umbrella name a future server family may need.

## Decision 7 — Summaries above a threshold, full records by request

An unfiltered `get_claims` returns full records while the part's claim set is small, and
a per-key summary above a threshold: for each key, the claim count, the subjects present,
and the part's attestation status. The threshold is **25 claims**. Full records for any
key are always available by asking again with `keys` — the summary-then-keys two-step is
the pagination, shaped like how agents actually work, so there are no pagination tokens
and no server-side cursor state. `search_parts` returns at most **50** candidates.

A catalog part can carry hundreds of claims and MCP responses land in a context window;
the alternative — serving everything always — holds until the first catalog part
flattens a consumer, after which every client grows its own truncation, each differently
lossy.

## Decision 8 — The serving state is the registry's git commit

Every envelope carries the git commit hash of the registry checkout being served. Two
servers at different commits may answer the same question differently; the commit hash is
how a consumer tells, and the append-only store (ADR-0035 D3/D7) means a newer commit
only ever knows more. A checkout whose `claims/` tree carries uncommitted changes serves
the hash suffixed `-dirty` — an identity that admits it names no committed state, rather
than one that borrows the last commit's authority. No synthetic store version — git already provides the identity —
and no `get_store_info` tool: every response already answers the question, and the
contract starts minimal (Decision 1).

*(Amended pre-freeze, when the production corpus moved to its own private repository and
the registry became two checkouts: the public one carrying code, schema, vocabulary and the
reference fixtures, and the corpus carrying the real-document entries. Every envelope now
carries **two** fields — `serving_state` for the public checkout, unchanged in meaning, and
`corpus_state` for the corpus, `null` when no corpus is configured. Each is that checkout's
own commit with its own `-dirty` suffix, computed from its own `claims/` tree.*

*The property D8 exists to provide is unchanged, now spelled as a pair: two consumers at the
same pair of states answer identically, and append-only means a newer pair only ever knows
more. The rejected alternative was one composite string, `<public>+<corpus>`: fewer fields,
but the server would join what every consumer then has to re-split, and a reader written
against the single-hash contract would silently start comparing a string that is no longer
a commit. `null` is an answer rather than an omission — it says this server serves the
public registry alone, which a missing field would leave the consumer to infer.*

*Two states, not N: a third claims root cannot be named in an envelope that carries two
identities, so the index refuses to build over one rather than serve content it cannot
identify.)*

## Decision 9 — `search_parts` covers manufacturer names, and OR's query tokens

*(Added by amendment, after the serving surface met its first real vendor catalogs.)*

Decision 1 scoped `search_parts` to "part numbers and `family` strings," and the
implementation followed it exactly. Two consequences showed up in use, both of which
made the store look emptier than it is:

- **A manufacturer name matched nothing.** `search_parts("Keyence")` returned zero
  results while the registry held four KEYENCE documents, 13 families, and more than
  200 parts. Manufacturer lives on the document record (ADR-0035 D5) and the index only
  ever walked claims, so the field was read at build time and never reached a search
  structure. The store knew the answer and had no path to say it.
- **A multi-token query matched nothing.** `search_parts("PZ-G LR-Z FS-N")` returned
  zero while FS-N existed, because the matcher normalized the whole string into one
  identifier. An agent holding three candidates has to make three calls, and the one
  call it naturally makes reads back as "the store has none of these."

Both are fixed here, and the fix costs no re-ingestion: the join happens at index-build
time from records already being read.

**The scope of `search_parts` becomes part numbers, `family` strings, and manufacturer
names.** Not claim text — Decision 1's exclusion is unchanged and is the reason this
amendment enumerates what it adds rather than relaxing the rule. Manufacturer is an
identifier, in the same sense a family designation is: it names something you can ask a
further question about, and it appears in the store as a field, not as a transcribed
sentence. Claim text remains a different product with real relevance problems, added
when demand shows up.

**The result `kind` enum gains `manufacturer`, and every result carries a
`manufacturer` field.** One row per (kind, identifier, manufacturer): a part covered by
two manufacturers' documents is two honest rows, never one row whose field a consumer
has to split.

**A manufacturer match answers with that manufacturer's families, not its parts.** The
50-result cap (Decision 7) is the reason. KEYENCE covers 205 parts in the registry
today; spending the whole budget on one token would crowd out every other token in the
same query and hand back a truncated list the agent cannot act on. Families are the
better answer anyway — they are exactly the identifiers `get_claims` resolves under
`matched_via: family` (Decision 4). Parts that no family of that manufacturer covers are
named individually, so the shorter answer is never a smaller one: a document stating no
family designation still reaches its part.

**Query tokens are split on whitespace and OR'd.** Each token normalizes on its own
under Decision 4's rules, so a token means exactly what it would have meant alone, and a
token matching nothing costs only its own matches. OR rather than AND because the query
this fixes is a list of candidates, not a conjunction of constraints.

### Manufacturer is metadata, and the surface says so

The document record's `manufacturer` is descriptive provenance, correctable in place
(ADR-0038 D3). The transcription of a stated vendor name is the `vendor_name` claim
(vocabulary 1.3), which cites the page it is printed on and which a manifest sources
`component.vendor` from. A manufacturer hit therefore carries the authority of metadata
and never that of a claim, which is why the tool description says so in the same breath
as the widened scope. Decision 2 is untouched: no served *value* gained or lost a
citation here, because a search result was never a value.

### Free text, plus a list, rather than an enum

`manufacturer` stays free text in the schema. The canonical list lives beside the
schema and the vocabulary, at `spec/schema/ocm-manufacturers-1.0.yaml`, naming each
manufacturer and the printed spellings that denote it. The serving index builds a search
token from every spelling and resolves all of them to one canonical name.

The rejected alternative was a schema `enum`, and it fails in a specific way: a pass
meeting a manufacturer the list had never heard of would fail validation mid-session and
wait on a pull request. That turns a descriptive field into an ingestion gate, and
ADR-0035 D6's trusted path is a human transcriber whose session should not stop for a
naming decision. The list therefore *merges* spellings and never *grants* visibility: an
unlisted manufacturer is its own canonical name and is searchable under exactly what its
record prints, from the moment it lands. `ci/check_manufacturers.py` reports unlisted
spellings and suspected variants without failing the build, and fails only when the list
contradicts itself — one spelling claimed by two canonical names, which would make the
index fold documents by load order.

No corpus file is rewritten to match a canonical name. `get_document` keeps serving each
record's printed spelling verbatim, which is what makes the merge safe: KEYENCE
CORPORATION and KEYENCE AMERICA are two legal entities folded onto one search name
because an operator typing "Keyence" wants both, and anyone who needs the distinction
reads it where it was never touched.

### What this amendment knowingly accepts

Substring matching over manufacturer names is as approximate as it is over part numbers,
and picks up the same kind of noise: the query `"keyence corporation"` also matches
`SMC Corporation`, because `corporation` is a substring of its name. That is the
matcher Decision 4 already chose for `search_parts`, applied consistently rather than
special-cased, and `search_parts` returns candidates for the agent to choose rather than
choosing itself. A stopword list or a scoring model would be a relevance product, which
Decision 1 declined to build until demand shows up.

The vocabulary version is untouched. This amendment adds no claim key, promotes none,
and aliases none; `manufacturer` is document metadata and attestations pin a key-set
version (ADR-0035 D4) that this change does not move.

## Out of scope

Transport is out of scope beyond one sentence: the contract above is
transport-independent; stdio ships first (local, Cellwright, desktop clients), remote
Streamable HTTP with authentication comes later without contract changes. The ingestion
and extraction pipeline is its own track (ADR-0035 D6). Before implementation, the
serving surface gets an eval set — golden queries with known-correct answers over the
committed registry, the D6 move applied to serving — as the next task; the server is not
built until the questions it must answer correctly are written down.
