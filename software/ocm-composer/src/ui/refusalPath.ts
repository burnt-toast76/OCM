// SPDX-License-Identifier: AGPL-3.0-or-later
// Best-effort extraction of an instance name from a refusal's `path`
// (e.g. "modules['pk1'].mount.on" or "modules.pk1.mount") so the issues
// panel can focus the offending instance on click. This reads the
// server's own path string; it never re-derives WHICH instance is at
// fault -- that's already encoded in `path` by the refusal itself.

export function instanceFromRefusalPath(path: string): string | null {
  const match = path.match(/^modules(?:\.|\['|\[")([^'"\.\]]+)/);
  return match ? match[1] : null;
}
