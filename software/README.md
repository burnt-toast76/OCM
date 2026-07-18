# software

AGPL-3.0. See ../LICENSING.md

- `ocm-core/` manifest load + validate
- `ocm-generator/` **the thesis** — cell.yaml -> Tesseract -> URScript + PLCopen XML
- `ocm-runtime/` SOEM + PackML coordinator (separate process by design)
- `ocm-agent/` tool layer. **LAST, not first.**
- `ocm-viewer/` R3F cell viewer

## Connecting an AI agent (MCP)

Copy `.mcp.json.example` (repo root) to `.mcp.json`, replace `<REPO>` with your
absolute repo path, and launch Claude Code from the repo directory. The `ocm`
server exposes the spec/09 tool surface; approve it on first run, then `/mcp`
to confirm the tools are listed. `.mcp.json` is gitignored (machine-specific
paths); the example is the committed contract.
