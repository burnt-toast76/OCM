# ocm-composer — Cellwright's cell composer

AGPL-3.0. See ../../LICENSING.md

The web GUI for composing OCM cells and authoring modules — one of Cellwright's clients of
`ocm-api` (ADR-0012: the GUI and the AI agent are clients of one API). React + TypeScript +
Vite. It talks to a running `ocm-api` HTTP server (`fetch('/<verb>')`), renders the API's
refusals in the Issues panel rather than re-implementing any rule, and carries the module
page's electrical / pneumatic / communication wiring tabs (ADR-0015). The agent chat panel
is wired to `ocm-api`'s `/agent/*` endpoints.

Under active development; not a released app.

## Develop

```
npm install
npm run dev        # Vite dev server (expects ocm-api reachable for /<verb> calls)
npm run test       # vitest unit tests
npm run test:e2e   # Playwright end-to-end
npm run build      # tsc -b && vite build
npm run lint       # oxlint
```
