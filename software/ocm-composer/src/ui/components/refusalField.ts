// SPDX-License-Identifier: AGPL-3.0-or-later
// Best-effort extraction of a top-level component-schema field name from a
// refusal, so the form can render it inline instead of only in the
// checklist panel. Two shapes to handle, both from the server's own
// words, never re-derived as a rule:
//
// - A real path ("electrical.supplies[0].current_nominal_a") -- take the
//   first segment.
// - A missing-required-property refusal reports path "$" (jsonschema
//   validates the PARENT object, not the absent child), with the field
//   name only inside the message ("'vendor' is a required property") --
//   see ocm-api's own tests/test_components.py for the same caveat on
//   the server side.

import type { Refusal } from "../../api/types";

const MISSING_REQUIRED = /'([a-zA-Z0-9_]+)' is a required property/;

export function refusalFieldKey(refusal: Refusal): string | null {
  if (refusal.path && refusal.path !== "$") {
    const first = refusal.path.split(/[.[]/)[0];
    return first || null;
  }
  const match = refusal.message.match(MISSING_REQUIRED);
  return match ? match[1] : null;
}

export function groupRefusalsByField(refusals: Refusal[]): Record<string, Refusal[]> {
  const grouped: Record<string, Refusal[]> = {};
  for (const refusal of refusals) {
    const key = refusalFieldKey(refusal);
    if (!key) continue;
    (grouped[key] ??= []).push(refusal);
  }
  return grouped;
}
