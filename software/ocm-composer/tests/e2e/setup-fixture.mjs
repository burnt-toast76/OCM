// SPDX-License-Identifier: AGPL-3.0-or-later
// Copies the repo's real spec/modules/cells/components into a throwaway
// fixture directory the e2e backend serves from -- NEVER point the e2e
// server at the actual working tree directly: every mutating verb this
// app calls (place_instance, move_instance, ...) writes for real
// (spec/09: "writes are unconditional"), and a test dragging a module
// out of bounds would otherwise permanently corrupt the real
// bracket-asm-01 cell on disk.
import { existsSync, rmSync, cpSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
// tests/e2e/setup-fixture.mjs -> ocm-composer -> software -> repo root
const repoRoot = path.resolve(here, "../../../..");
const fixtureDir = path.resolve(here, "../../.e2e-fixture");

if (existsSync(fixtureDir)) rmSync(fixtureDir, { recursive: true, force: true });
for (const dir of ["spec", "modules", "cells", "components"]) {
  cpSync(path.join(repoRoot, dir), path.join(fixtureDir, dir), { recursive: true });
}
console.log(`[setup-fixture] ready at ${fixtureDir}`);
