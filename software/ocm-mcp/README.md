# ocm-mcp

The read-only claims serving surface — an MCP server presenting as `ocm-claims`
(ADR-0036): `get_claims`, `search_parts`, `get_document`, provenance on every
value, reading through `ocm-api` (ADR-0016).

The contract is ADR-0036, and it is transport-independent: the golden queries in
`evals/golden-queries.yaml` are the known-correct answers (ADR-0035 D6's move
applied to serving), written before the server and executed by
`tests/test_golden_evals.py` now that it exists. `ci/check_serving_evals.py`
keeps their expectations referentially honest against the `claims/` registry.

## Registry

The registry may span two checkouts, and every envelope names both states
(ADR-0036 D8 as amended):

| Variable     | Default | Meaning                                                        |
| ------------ | ------- | -------------------------------------------------------------- |
| `OCM_ROOT`   | `.`     | The public checkout — code, schema, vocabulary, reference fixtures. `serving_state`. |
| `OCM_CORPUS` | unset   | The production corpus's checkout, optional. `corpus_state`, `null` when unset. |

The index is built at startup and never reloaded (D5): restart to pick up new
ingestion. A registry that fails `validate_claims` is not served at all.

## Local (stdio)

The default. No token, no port — the peer is whoever launched the process.

```bash
pip install -e ../ocm-core -e ../ocm-resolve -e ../ocm-generator -e ../ocm-api -e ".[test]"
OCM_ROOT=<REPO> python -m ocm_mcp.server
```

Registering it:

```bash
claude mcp add --env OCM_ROOT=<REPO> --transport stdio ocm-claims \
  -- <REPO>/.venv/bin/python -m ocm_mcp.server
```

## Remote (streamable HTTP)

Same tools, same envelopes, reached over the network — ADR-0036's "remote
Streamable HTTP with authentication ... without contract changes".

### Two kinds of credential

**An operator token** is a secret you generate and hand over out of band. It is
the credential that works when the identity provider is down, misconfigured, or
being migrated, which is exactly why it survives now that OAuth exists. Use it
for your own automation.

**An OAuth token** is issued by WorkOS AuthKit to a client that registered
itself. That is how a stranger — a person adding this server as a connector in
their AI client, an agent that has never met you — gets in without you minting
anything by hand.

This server's role is **resource server** and nothing else: it verifies tokens
and publishes protected-resource metadata. It never issues a token, hosts a
login page, or stores a user.

| Variable              | Default   | Meaning                                                    |
| --------------------- | --------- | ---------------------------------------------------------- |
| `OCM_TRANSPORT`       | `stdio`   | `stdio` or `http`. Anything else is refused, not ignored.   |
| `OCM_HOST`            | `0.0.0.0` | Interface to bind. Used only by `http`.                     |
| `OCM_PORT`            | `8000`    | Port to bind. Used only by `http`.                          |
| `OCM_AUTH_TOKEN`      | unset     | The operator's bearer token. Ignored by `stdio`.            |
| `OCM_OAUTH_ISSUER`    | unset     | The AuthKit domain that issues tokens, e.g. `https://your-project-12345.authkit.app`. |
| `OCM_OAUTH_AUDIENCE`  | unset     | The resource indicator clients ask tokens for — this server's public `/mcp` URL. |
| `OCM_OAUTH_JWKS`      | derived   | Signing keys. Defaults to `<issuer>/oauth2/jwks`; set it only for an authorization server that publishes elsewhere. |

**There is no unauthenticated HTTP mode.** With `OCM_TRANSPORT=http` the server
needs the operator token, or a complete OAuth configuration, or both — which is
the expected production state. With neither, it exits before it binds, with the
reason on stderr. That is not a nag; it is the only behavior that keeps "we
forgot to set the credentials" from being a deployment that works.

**Half-configured OAuth is also a refusal.** `OCM_OAUTH_ISSUER` without
`OCM_OAUTH_AUDIENCE` exits naming what is missing, rather than falling back to
bearer-only. An operator who set one has plainly asked for OAuth, and the quiet
fallback would leave a server that looks configured, answers `401` to every
OAuth client, and tells nobody why. The audience is not cosmetic either: it is
the check that stops a token minted for a *different* resource on the same
authorization server from opening this one.

Generate an operator token:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Smoke test it locally (PowerShell):

```powershell
$env:OCM_TRANSPORT="http"; $env:OCM_AUTH_TOKEN="<token>"
python -m ocm_mcp.server
# then from another terminal:
curl http://localhost:8000/health
```

`/health` is unauthenticated and GET-only, for the hosting platform's probe and
for answering "which commit is live":

```json
{ "status": "ok", "serving_state": "<git commit>", "corpus_state": null }
```

Those two identifiers are already in every envelope this server serves and are
commits of a public repository, so the endpoint gives away nothing the tools
don't. Nothing else joins them.

### Discovery, for OAuth clients

With OAuth configured, the server publishes RFC 9728 protected-resource metadata
and points at it from every `401`, which is how a client finds where to get a
token:

```bash
curl http://localhost:8000/.well-known/oauth-protected-resource/mcp
# {"resource": "...", "authorization_servers": ["https://your-project.authkit.app"], ...}
```

Without OAuth configured, no metadata is published — there is no authorization
server to name, and advertising a flow nobody can complete would send clients
chasing it.

### Registering a client

The MCP endpoint is `/mcp`, and it answers `401` to any request without a valid
token. With an operator token, register it directly:

```bash
claude mcp add --transport http ocm-claims http://localhost:8000/mcp \
  --header "Authorization: Bearer <token>"
```

The same registration works against the hosted URL — only the host part changes.

An OAuth client registers itself instead: point a client that speaks the MCP
authorization flow (the claude.ai connector UI, for instance) at the `/mcp` URL
and let it discover AuthKit, register, and complete the flow. You mint nothing
and add no configuration per client.

## Coverage queue (`request_coverage`)

When the store cannot answer (`no_documents`, `absence_not_yet_meaningful`), the
fourth tool files that demand as a GitHub issue labeled `coverage-request` on the
public repo, deduplicated on the normalized (manufacturer, part) key — repeat
requests stack onto one issue as comments, and either path returns the issue URL.
The queue is not the registry (ADR-0036 D1 as amended): it feeds the
human-supervised ingestion pipeline and can never place, alter, or delete a claim.
Manufacturer + part number is a complete request — source URLs are optional
(vendor logins gate many; the operator resolves the document) — and no files are
accepted, ever.

**Offer-only rule:** the agent may OFFER the user a coverage request on the two
absence states above; it never files one without the user's explicit yes. The
server instructions carry this sentence whenever the tool is active.

| Variable                 | Default | Meaning                                             |
| ------------------------ | ------- | --------------------------------------------------- |
| `OCM_COVERAGE_TOKEN`     | unset   | Fine-grained PAT for the queue repo. Both or nothing. |
| `OCM_COVERAGE_REPO`      | unset   | `owner/repo` the issues land on. Both or nothing.   |
| `OCM_COVERAGE_DAILY_CAP` | `10`    | Per-caller daily request cap (in-memory).           |

With either variable unset the tool is **not registered** — a session sees the
three serving tools and nothing broken — and the startup log states which mode is
live. The PAT is never baked into code, config, or images.

The daily cap is **per caller**, where a caller is an OAuth `sub` or the
operator's static token: one client exhausting its budget leaves everyone else
untouched, and the operator's allowance is on an identity no client token can
claim. (This is the phase-two change; before OAuth every caller shared one
identity, so the same cap meant N per day *total*.) It stays in memory and per
process, so a restart forgives everyone and two replicas keep two tallies — the
honest cost of not having a shared store, and acceptable while the cap blunts
accidents rather than metering a paid tier. A GitHub outage or bad credential
answers `status: unavailable` without consuming the cap; the diagnosis goes to
the server log, never the caller.

## Claim reports (`report_claim`)

The dispute channel (ADR-0037 D3): when a user believes a served value is wrong,
`report_claim(claim_id, reason, expected_value?, note?)` files it as a GitHub
issue labeled `claim-report` on the same repo, with the same PAT and the same
env gate as the coverage queue — configuring one configures both, and the two
tools **share** the daily cap (one client identity, one budget). Reports are
deduplicated on the claim id; repeats stack as comments.

`claim_id` is required and must be an id this registry serves — every served
value carries one, so a genuine dispute is precise by construction; an unknown
id is politely refused and files nothing. A report on an already-retracted
claim answers with the retraction's story (reason, superseding id) instead of
filing: the dispute is already settled.

**No tool ever writes a retraction.** The queue files the operator's homework;
the retraction — a judgment that our record contradicts its source, made after
reading the document — is written by the operator in a supervised session
(ADR-0037 D3). Every issue carries the triage line so reporters know the
asymmetry: a **transcription error** is retracted and replaced; a
**manufacturer misprint** is not retracted — the erratum ingests as a new
document (ADR-0035 D5). Either way a valid report resolves visibly in the
store's history.

**Offer-only rule:** the agent may OFFER a report when the user disputes a
served value; it never files one without the user's explicit yes. The server
instructions carry this sentence whenever the tool is active.

### PAT scoping walkthrough

GitHub → Settings → Developer settings → **Fine-grained personal access tokens** →
Generate new token:

1. **Resource owner:** the account/org that owns the queue repo.
2. **Repository access:** *Only select repositories* → the public OCM repo alone.
3. **Repository permissions:** **Issues: Read and write** (Metadata: Read is added
   automatically). Nothing else — no contents, no workflows.
4. Set an expiration and rotate on schedule; the server reads it only from
   `OCM_COVERAGE_TOKEN`.

(Endpoint set used, API version 2022-11-28: `GET /repos/{owner}/{repo}/issues`
filtered by label and state, `POST /repos/{owner}/{repo}/issues`,
`POST /repos/{owner}/{repo}/issues/{number}/comments`.)

### Operator setup

1. Create the labels once: `gh label create coverage-request
   --repo <owner>/OCM --description "Demand from the ocm-claims serving surface"`
   and `gh label create claim-report
   --repo <owner>/OCM --description "Disputed served value (ADR-0037)"`
   (or via the repo's Labels page).
2. Mint the PAT per the walkthrough; set `OCM_COVERAGE_TOKEN` and
   `OCM_COVERAGE_REPO=<owner>/OCM` in the local MCP registration (`claude mcp add
   --env …`) and in the eventual host's environment alongside the transport
   variables.
3. Triage from the label: the issue body's fixed template (`manufacturer:`,
   `part_number:`, `key:`, `source_url:`, `note:`, `requested_by:`, `date:`) is
   parseable by eye and by tooling; comment stacks on one issue are the demand
   ranking.
