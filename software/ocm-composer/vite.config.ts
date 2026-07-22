/// <reference types="vitest/config" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { GET_VERBS, POST_VERBS } from "./src/api/verbs.ts";

// ADR-0012: the composer is a pure HTTP client of ocm-api -- no bundled
// backend logic. In dev, ocm-api-http runs separately (default
// 127.0.0.1:8000); proxy every known verb path there so the app can
// always fetch("/verb_name") -- the exact same root-relative path that
// works once the production build is served from the SAME origin under
// /composer (see ocm_api/http_app.py's StaticFiles mount).
const API_TARGET = process.env.OCM_API_URL ?? "http://127.0.0.1:8000";
const proxy = Object.fromEntries([...GET_VERBS, ...POST_VERBS].map((verb) => [`/${verb}`, { target: API_TARGET, changeOrigin: true }]));
// /agent/chat, /agent/models, and /components/{id}/attachments (spec/09
// "Agent orchestrator") aren't in GET_VERBS/POST_VERBS -- none of the
// three is an OcmApi verb wrapped in the standard Envelope shape (the
// first is SSE, the second is static server config, the third is path-
// parameterized and can't be expressed as one of those literal strings at
// all). Three explicit rules, same target as everything else -- Vite
// treats a leading `^` proxy key as a regex, not a literal prefix.
proxy["/agent/chat"] = { target: API_TARGET, changeOrigin: true };
proxy["/agent/models"] = { target: API_TARGET, changeOrigin: true };
proxy["^/components/.+/attachments"] = { target: API_TARGET, changeOrigin: true };

export default defineConfig({
  base: "/composer/",
  plugins: [react()],
  server: { proxy },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    exclude: ["**/node_modules/**", "**/tests/e2e/**"],
  },
});
