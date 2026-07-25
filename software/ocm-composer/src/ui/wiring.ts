// SPDX-License-Identifier: AGPL-3.0-or-later
// Pure logic for the wiring canvas -- deliberately framework-free (same
// convention as dragMath.ts): endpoint identity, click-to-wire net
// editing, and module-connectivity refusal-to-DOM-field routing. No
// network call is even possible from this module; WiringCanvas.tsx is the
// only thing that turns its output into an update_module patch.
//
// ADR-0015 Decision 4 (hard constraint): nothing here can invent a pin.
// applyWireClick only ever copies the two Endpoint values it's given --
// which always come from an already-rendered, already-transcribed pin or
// port (WiringCanvas's own click handlers), never a typed-in value.

import type { ModuleEndpoint, ModuleNetRow, Refusal } from "../api/types";

export function endpointKey(e: ModuleEndpoint): string {
  if (e.port !== undefined) return `port:${e.port}:${e.pin ?? ""}`;
  return `refdes:${e.refdes ?? ""}:${e.ref ?? ""}:${e.pin ?? ""}`;
}

export function endpointsEqual(a: ModuleEndpoint, b: ModuleEndpoint): boolean {
  return endpointKey(a) === endpointKey(b);
}

export function findNetIndexContaining(nets: ModuleNetRow[], endpoint: ModuleEndpoint): number {
  const key = endpointKey(endpoint);
  return nets.findIndex((n) => n.endpoints.some((e) => endpointKey(e) === key));
}

export function nextNetId(nets: ModuleNetRow[]): string {
  const existing = new Set(nets.map((n) => n.id));
  let i = 1;
  while (existing.has(`N${i}`)) i++;
  return `N${i}`;
}

/**
 * Click pin -> click pin creates or joins a net; clicking a rail (a module
 * port's own endpoint) joins that net the same way -- ports and component
 * pins are just two Endpoint shapes to this function, treated identically.
 *
 * Four cases, in order:
 * - Neither endpoint is wired yet -> a brand new net joining exactly these two.
 * - One is already on a net, the other isn't -> the unwired one joins it.
 * - Both already on the SAME net -> no-op (already connected).
 * - Both already on DIFFERENT nets -> the two nets merge into one (the
 *   earlier one keeps its id/name), since clicking two already-wired
 *   things together is the natural way to say "these are the same net."
 */
export function applyWireClick(nets: ModuleNetRow[], a: ModuleEndpoint, b: ModuleEndpoint): ModuleNetRow[] {
  const aIndex = findNetIndexContaining(nets, a);
  const bIndex = findNetIndexContaining(nets, b);

  if (aIndex === -1 && bIndex === -1) {
    return [...nets, { id: nextNetId(nets), endpoints: [a, b] }];
  }
  if (aIndex !== -1 && bIndex === -1) {
    return nets.map((n, i) => (i === aIndex ? { ...n, endpoints: [...n.endpoints, b] } : n));
  }
  if (aIndex === -1 && bIndex !== -1) {
    return nets.map((n, i) => (i === bIndex ? { ...n, endpoints: [...n.endpoints, a] } : n));
  }
  if (aIndex === bIndex) {
    return nets;
  }
  const [keepIndex, dropIndex] = aIndex < bIndex ? [aIndex, bIndex] : [bIndex, aIndex];
  const keepKeys = new Set(nets[keepIndex].endpoints.map(endpointKey));
  const extra = nets[dropIndex].endpoints.filter((e) => !keepKeys.has(endpointKey(e)));
  return nets.filter((_, i) => i !== dropIndex).map((n, i) => {
    const originalIndex = i >= dropIndex ? i + 1 : i; // account for the filtered-out entry when re-indexing
    return originalIndex === keepIndex ? { ...n, endpoints: [...n.endpoints, ...extra] } : n;
  });
}

// -- Refusal -> DOM data-field routing -------------------------------------
// validate_module's connectivity refusals (ocm_resolve/connectivity.py,
// translated by ocm_api/translate.py) use a DIFFERENT path shape than
// validate_component's -- "modules['id'].nets.electrical['NET_ID']", every
// segment addressed by its own declared id, never an array index -- so
// this is a dedicated parser, not a reuse of refusalField.ts's
// first-path-segment heuristic (which assumes a component-schema path
// with no "modules['id'].' prefix at all). Two codes (PIN_ON_MULTIPLE_NETS,
// UNRESOLVED_ENDPOINT) have a coarse path -- the specific pin only lives
// in the message text, single-quoted, same as ocm_resolve's own
// _describe_pin already renders it.

const RE_PATH_NET = /^modules\['[^']*'\]\.nets\.(?:electrical|pneumatic)\['([^']+)'\]$/;
const RE_PATH_COMPONENT = /^modules\['[^']*'\]\.components\['([^']+)'\]$/;
const RE_PATH_PORT = /^modules\['[^']*'\]\.ports\['([^']+)'\]$/;
const RE_PATH_LINK = /^modules\['[^']*'\]\.links\['([^']+)'\](?:\.[ab])?$/;

const RE_MSG_PIN_ON_COMPONENT = /pin '([^']+)' of connector '([^']+)' on refdes '([^']+)'/;
const RE_MSG_PIN_ON_PORT = /pin '([^']+)' of port '([^']+)'/;
const RE_MSG_UNRESOLVED_COMPONENT = /references pin '([^']+)' not on connector '([^']+)' of refdes '([^']+)'/;
const RE_MSG_UNRESOLVED_PORT = /references pin '([^']+)' not on port '([^']+)'/;

/**
 * `data-field` value a matching rendered element (a pin, a net row, a
 * rail, a component card, a link row) carries -- see WiringCanvas.tsx for
 * where each is actually set. Null when a refusal names nothing this
 * canvas renders anything specific for (e.g. ETHERCAT_CHAIN_BROKEN names
 * the whole links list, not one link).
 */
export function moduleRefusalFieldKey(refusal: Refusal): string | null {
  // Message-derived pin identity takes priority -- strictly more specific
  // than what PIN_ON_MULTIPLE_NETS/UNRESOLVED_ENDPOINT's own coarse paths
  // ("modules['id'].nets" / "modules['id']") can address.
  let m = refusal.message.match(RE_MSG_PIN_ON_COMPONENT) ?? refusal.message.match(RE_MSG_UNRESOLVED_COMPONENT);
  if (m) return `pin:${m[3]}:${m[2]}:${m[1]}`; // refdes, connector ref, pin
  m = refusal.message.match(RE_MSG_PIN_ON_PORT) ?? refusal.message.match(RE_MSG_UNRESOLVED_PORT);
  if (m) return `port:${m[2]}`;

  const path = refusal.path;
  m = path.match(RE_PATH_NET);
  if (m) return `net:${m[1]}`;
  m = path.match(RE_PATH_COMPONENT);
  if (m) return `component:${m[1]}`;
  m = path.match(RE_PATH_PORT);
  if (m) return `port:${m[1]}`;
  m = path.match(RE_PATH_LINK);
  if (m) return `link:${m[1]}`;
  return null;
}
