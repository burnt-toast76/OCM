// SPDX-License-Identifier: AGPL-3.0-or-later
// Every ocm-api HTTP route name (spec/09), by method -- the single source
// both vite.config.ts's dev-server proxy and api/client.ts's fetch calls
// read from, so the two can never drift apart. Plain data, no imports:
// vite.config.ts (Node/ESM, outside the app's own React bundle) needs to
// read this too.

export const GET_VERBS = [
  "describe_schema",
  "get_example",
  "list_modules",
  "describe_module",
  "list_cells",
  "describe_cell",
  "list_frames",
  "list_components",
  "describe_component",
] as const;

export const POST_VERBS = [
  "create_module_draft",
  "update_module",
  "generate_geometry_stub",
  "validate_module",
  "publish_module",
  "create_component_draft",
  "update_component",
  "validate_component",
  "publish_component",
  "create_cell",
  "place_instance",
  "move_instance",
  "remove_instance",
  "set_plan",
  "set_joint_state",
  "build_scene",
  "check_collision",
  "plan_cell",
  "emit",
] as const;

export type GetVerb = (typeof GET_VERBS)[number];
export type PostVerb = (typeof POST_VERBS)[number];
