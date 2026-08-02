# software — Cellwright

AGPL-3.0. See ../LICENSING.md

**Cellwright** is Accel Solutions' implementation of the OCM standard (ADR-0018): the
software that reads OCM manifests and generates everything downstream. The packages keep
their `ocm-*` names — they implement OCM; Cellwright is the product that bundles them.

- `ocm-core/` — manifest load + validate
- `ocm-resolve/` — cross-file resolution: mount chains, plan/param checks, and the
  module-connectivity refusals (ADR-0015, ADR-0016)
- `ocm-api/` — the one programmatic surface (ADR-0012): authoring verbs + refusal engine,
  exposed over MCP and HTTP
- `ocm-generator/` — **the thesis** — a resolved cell → Tesseract scene → collision-checked
  joint-space plan → URScript, cycle-time, animation, and a PackML coordinator on
  **simulated** I/O. *(The PLCopen-XML emitter is not built yet.)*
- `ocm-composer/` — React/TypeScript web composer: cell composition + module wiring, an
  `ocm-api` HTTP client
- `ocm-runtime/` — *planned:* SOEM + PackML coordinator as a separate process. Empty stub
  today; the coordinator currently lives, simulated, in `ocm-generator`.
- `ocm-agent/` — tool layer. **LAST, not first.** Empty stub.
- `ocm-viewer/` — R3F cell viewer. Empty stub.

## Connecting an AI agent (MCP)

Copy `.mcp.json.example` (repo root) to `.mcp.json`, replace `<REPO>` with your
absolute repo path, and launch Claude Code from the repo directory. The `ocm`
server exposes the spec/09 tool surface; approve it on first run, then `/mcp`
to confirm the tools are listed. `.mcp.json` is gitignored (machine-specific
paths); the example is the committed contract.
