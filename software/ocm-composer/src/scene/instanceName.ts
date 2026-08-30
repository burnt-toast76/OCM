// SPDX-License-Identifier: AGPL-3.0-or-later
// A starting-point instance name for a freshly dropped module -- purely a
// UI convenience default, editable later via rename (not built yet) and
// fully subject to place_instance's own OCM_ALREADY_EXISTS refusal if it
// somehow still collides (e.g. a race with another client).

export function suggestInstanceName(moduleId: string, existing: string[]): string {
  const base = moduleId.split(".").pop() ?? "instance";
  const taken = new Set(existing);
  if (!taken.has(base)) return base;
  for (let i = 2; i < 1000; i++) {
    const candidate = `${base}${i}`;
    if (!taken.has(candidate)) return candidate;
  }
  return `${base}${Date.now()}`;
}
