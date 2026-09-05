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

Same three tools, same envelopes, reached over the network by a caller holding a
bearer token — ADR-0036's "remote Streamable HTTP with authentication ...
without contract changes".

| Variable          | Default   | Meaning                                                    |
| ----------------- | --------- | ---------------------------------------------------------- |
| `OCM_TRANSPORT`   | `stdio`   | `stdio` or `http`. Anything else is refused, not ignored.   |
| `OCM_HOST`        | `0.0.0.0` | Interface to bind. Used only by `http`.                     |
| `OCM_PORT`        | `8000`    | Port to bind. Used only by `http`.                          |
| `OCM_AUTH_TOKEN`  | unset     | The bearer token, **required** by `http`, ignored by `stdio`. |

**There is no unauthenticated HTTP mode.** With `OCM_TRANSPORT=http`, a missing
`OCM_AUTH_TOKEN` — or one shorter than 32 characters — makes the server exit
before it binds, with the reason on stderr. That is not a nag; it is the only
behavior that keeps "we forgot to set the token" from being a deployment that
works.

Generate one:

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

The MCP endpoint is `/mcp`, and it answers `401` to any request without a valid
token:

```bash
claude mcp add --transport http ocm-claims http://localhost:8000/mcp \
  --header "Authorization: Bearer <token>"
```

The same registration works against the hosted URL later — only the host part
changes.

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

Under static-token auth every caller shares one client identity, so the daily cap
is N per day **total**, not per user — per-client caps arrive with per-client
identity (OAuth, phase two). A GitHub outage or bad credential answers
`status: unavailable` without consuming the cap; the diagnosis goes to the server
log, never the caller.

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
