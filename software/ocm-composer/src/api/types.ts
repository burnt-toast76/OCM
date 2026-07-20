// SPDX-License-Identifier: AGPL-3.0-or-later
// The envelope shape spec/09-ocm-api.md defines and every ocm-api
// transport returns byte-identically (see ocm-api's own
// tests/test_transports.py). This file only TYPES that shape -- it
// contains no rule logic; refusal codes are read, never re-derived.

export interface Refusal {
  code: string;
  path: string;
  message: string;
  allowed: Record<string, unknown> | null;
  hint: string | null;
}

export interface Envelope<T = unknown> {
  ok: boolean;
  refusals: Refusal[];
  warnings: string[];
  data: T | null;
}

// -- Refusal codes this UI renders specially (envelope.Codes on the server;
// mirrored here as string literals, not re-implemented -- the server is
// still the only place that DECIDES when one applies). --------------------
export const TOOL_SLOT_OCCUPIED = "TOOL_SLOT_OCCUPIED";
export const WORKSPACE_OVERHANG = "WORKSPACE_OVERHANG";

// -- Data shapes for the verbs this app actually calls (M1 + M2 only). ----

export interface CellSummary {
  cell_id: string;
  id: string;
  name: string;
}

export interface CellInstanceRow {
  instance: string;
  module: string; // "id@revision"
  mounted_on: string | null;
}

export interface RawCellModule {
  instance: string;
  module: string;
  mount: Mount;
  tool?: string;
  [key: string]: unknown;
}

export interface DescribeCellData {
  cell_id: string;
  id: string;
  name: string;
  cell: { modules?: RawCellModule[]; [key: string]: unknown };
  instances?: CellInstanceRow[];
  plan_step_count?: number;
}

export interface ScenePrimitive {
  link: string;
  instance: string;
  instance_kind: string;
  kind: "box" | "cylinder" | "sphere";
  dims: Record<string, number>;
  position: [number, number, number];
  quaternion: [number, number, number, number];
  placeholder: boolean;
}

export interface SceneMarker {
  label: string;
  position: [number, number, number];
}

export interface ScenePayload {
  cell_id: string;
  n_links: number;
  n_joints: number;
  base: string;
  instances: string[];
  colors: Record<string, string>;
  primitives: ScenePrimitive[];
  markers: SceneMarker[];
}

export interface ModuleSummary {
  id: string;
  revision: string;
  kind: string;
  name: string | null;
  draft: boolean;
}

export interface ModuleFrame {
  xyz_mm: [number, number, number];
  rpy_deg?: [number, number, number];
  note?: string;
}

export interface ModuleCapability {
  name: string;
  summary: string;
  parameters?: Record<string, unknown>;
}

export interface ModuleManifest {
  id: string;
  revision: string;
  kind: string;
  name?: string;
  vendor?: string;
  mechanical: {
    mount: { interface: string; footprint_mm?: [number, number] };
    frames: Record<string, ModuleFrame>;
  };
  capabilities?: ModuleCapability[];
  [key: string]: unknown;
}

export interface DescribeModuleData {
  id: string;
  revision: string;
  draft: boolean;
  manifest: ModuleManifest;
  aggregates?: Record<string, unknown>;
}

export interface Mount {
  pose?: { xyz_mm: [number, number, number]; rpy_deg: [number, number, number] };
  on?: string;
}

export interface CompositionResult {
  cell_id: string;
  instances: string[];
  base: string;
  workspace_bounds: { x_mm: [number, number]; y_mm: [number, number] } | null;
}
