// SPDX-License-Identifier: AGPL-3.0-or-later
// A small, harmless window hook so Playwright can find WHERE on screen a
// 3D instance currently renders (a WebGL canvas has no per-object DOM
// elements a locator can click) and drive a real pointer drag at that
// pixel. Nothing here affects app behavior -- it's read-only screen-space
// projection, always available, not gated behind a test/dev flag, the
// same way a real app might expose devtools hooks. No rule logic; it
// answers "where", never "is this allowed".

export interface ComposerTestHooks {
  getInstanceScreenXY(instance: string): { x: number; y: number } | null;
}

declare global {
  interface Window {
    __ocmComposerTestHooks?: ComposerTestHooks;
  }
}

export function registerTestHooks(hooks: ComposerTestHooks): () => void {
  window.__ocmComposerTestHooks = hooks;
  return () => {
    if (window.__ocmComposerTestHooks === hooks) delete window.__ocmComposerTestHooks;
  };
}
