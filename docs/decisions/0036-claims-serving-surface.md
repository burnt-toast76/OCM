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

## Decision 1 — Three tools, read-only, forever

The server exposes exactly three tools:

- `get_claims(part_number, keys?)` — the claims covering one part. With `keys` omitted it
  returns everything for the part (Decision 7's sizing applies): omission is the
  discovery path, naming keys is the retrieval path.
- `search_parts(query)` — approximate lookup over part numbers and `family` strings,
  returning candidates for the agent to choose from. Not claim text: that is a different
  product with real relevance problems, added when demand shows up, not before.
- `get_document(hash)` — a document record's metadata and its registry citations, never
  document bytes; the repository does not hold real manufacturer documents
  (ADR-0035 D5, `claims/README.md`) and the server cannot serve what the store
  deliberately excludes.

Nothing else in v1: no vocabulary tool (the vocabulary rides in the server's
instructions — it is small, changes by pull request, and every envelope names the version
it was served under), no manifest tools, and no write, transcription, or mutation surface
— not in v1, not ever. Ingestion is a separate concern with its own machinery. Additions
to this contract are backward-compatible; removals never are, which is why it starts
minimal.

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

A query for a key with no claim is answered with one of three distinct states, never a
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

The registry already exhibits all three, and flattening any pair fabricates certainty —
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
only ever knows more. No synthetic store version — git already provides the identity —
and no `get_store_info` tool: every response already answers the question, and the
contract starts minimal (Decision 1).

## Out of scope

Transport is out of scope beyond one sentence: the contract above is
transport-independent; stdio ships first (local, Cellwright, desktop clients), remote
Streamable HTTP with authentication comes later without contract changes. The ingestion
and extraction pipeline is its own track (ADR-0035 D6). Before implementation, the
serving surface gets an eval set — golden queries with known-correct answers over the
committed registry, the D6 move applied to serving — as the next task; the server is not
built until the questions it must answer correctly are written down.
