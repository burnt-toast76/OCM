# ocm-mcp

The read-only claims serving surface — an MCP server presenting as `ocm-claims`
(ADR-0036): `get_claims`, `search_parts`, `get_document`, provenance on every
value, reading through `ocm-api` (ADR-0016).

**No server code exists yet, deliberately.** The contract is ADR-0036; the
golden queries in `evals/golden-queries.yaml` are the known-correct answers the
implementation must reproduce (ADR-0035 D6's move applied to serving), written
first. `ci/check_serving_evals.py` keeps their expectations referentially
honest against the `claims/` registry until the server's own test suite
executes them for real.
