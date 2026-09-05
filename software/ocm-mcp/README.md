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
