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
export const OCM_TOOL_SLOT_OCCUPIED = "OCM_TOOL_SLOT_OCCUPIED";
export const OCM_WORKSPACE_OVERHANG = "OCM_WORKSPACE_OVERHANG";
export const OCM_AGENT_UNAVAILABLE = "OCM_AGENT_UNAVAILABLE";

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

// A 6-DOF pose -- the identical wire shape place_instance/move_instance's
// own Mount.pose already used, and now also components[].pose (a module's
// own component-instance placement, Modules-page authoring UI). One type,
// not two copies that could drift.
export interface Pose6d {
  xyz_mm: [number, number, number];
  rpy_deg: [number, number, number];
}

// One entry in a module's `components:` list (ADR-0014) -- a purchased
// part this module is assembled from, by its own reference designator.
// `pose` is optional: a components: entry with no pose is still valid,
// it's just not placed anywhere in the Modules page's own local scene yet.
export interface ModuleComponentRow {
  refdes: string;
  ref: string; // "id@revision"
  pose?: Pose6d;
}

// ADR-0015: module connectivity. Mirrors ocm_core.module's Endpoint/Net/
// Nets/Port/Link dataclasses field-for-field -- no renaming, no alias
// layer, same rule the schema/dataclasses themselves follow. `port` is a
// ModulePort.id; `refdes` is a ModuleComponentRow.refdes; `ref`/`pin` are
// exactly what the referenced component's own connector/pin calls itself
// (ComponentConnector.ref / ComponentPin.pin, ocm-core's component side).
export interface ModuleEndpoint {
  port?: string;
  refdes?: string;
  ref?: string;
  pin?: string;
}

export interface ModuleNetRow {
  id: string;
  endpoints: ModuleEndpoint[];
  pressure?: number; // pneumatic nets only, in practice
  pressure_units?: string;
}

export interface ModuleNets {
  electrical?: ModuleNetRow[];
  pneumatic?: ModuleNetRow[];
}

export type ModulePortDomain = "electrical" | "pneumatic" | "communication";

export interface ModulePortRow {
  id: string;
  domain: ModulePortDomain;
  type?: string; // electrical
  thread?: string; // pneumatic
  function?: "supply" | "exhaust" | "work"; // pneumatic
  protocol?: string; // communication
  role?: "master" | "slave_in" | "slave_out" | "port"; // communication
}

export interface ModuleLinkRow {
  id: string;
  a: ModuleEndpoint;
  b: ModuleEndpoint;
  protocol?: string;
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
  components?: ModuleComponentRow[];
  ports?: ModulePortRow[];
  nets?: ModuleNets;
  links?: ModuleLinkRow[];
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
  pose?: Pose6d;
  on?: string;
}

export interface CompositionResult {
  cell_id: string;
  instances: string[];
  base: string;
  workspace_bounds: { x_mm: [number, number]; y_mm: [number, number] } | null;
}

// -- Components (ADR-0014, spec/10) ---------------------------------------------------

export interface ComponentSummary {
  id: string;
  revision: string;
  kind: string | null;
  vendor: string | null;
  name: string | null;
  draft: boolean;
}

// The component document itself -- deliberately loose (Record passthrough
// on every nested object) rather than a field-by-field type. The FORM
// that edits this is schema-driven (describe_schema), not hand-typed
// against spec/10 a second time; a stricter type here would just be a
// second, driftable copy of the same shape the schema already states.
export interface ComponentDoc {
  ocm_version?: string;
  id: string;
  revision: string;
  kind?: string;
  name?: string;
  vendor?: string;
  part_number?: string;
  source?: { kind?: string; ref?: string; date?: string };
  [section: string]: unknown;
}

export interface DescribeComponentData {
  id: string;
  revision: string;
  draft: boolean;
  component: ComponentDoc;
}

export interface UpdateComponentResult {
  id: string;
  revision: string;
  draft: boolean;
  path: string;
}

// glb_status is only meaningful for kind: "step" -- null for everything
// else. STEP->GLB conversion runs in a background thread server-side
// (a real manufacturer STEP file can take minutes, not the near-instant
// conversion a tiny test fixture suggests), so "pending" is a real,
// often-observed state, not just a theoretical one.
export type GlbStatus = "pending" | "ready" | "failed" | null;

export interface AttachmentResult {
  filename: string;
  kind: "pdf" | "text" | "step" | "other";
  measured_envelope_mm: [number, number, number] | null;
  glb: string | null;
  glb_status: GlbStatus;
}

export interface AttachmentRow {
  filename: string;
  kind: "pdf" | "text" | "step" | "other";
  glb: string | null;
  glb_status: GlbStatus;
  measured_envelope_mm: [number, number, number] | null;
}

// -- JSON Schema (describe_schema's own output) ---------------------------------------------------
// Loosely typed on purpose -- this IS the schema-driven form's source of
// truth; a fuller JSON Schema type wouldn't make the form any more
// correct, just harder to read.

export interface JsonSchemaNode {
  type?: string | string[];
  properties?: Record<string, JsonSchemaNode>;
  required?: string[];
  enum?: unknown[];
  anyOf?: JsonSchemaNode[];
  items?: JsonSchemaNode;
  additionalProperties?: boolean | JsonSchemaNode;
  description?: string;
  pattern?: string;
  const?: unknown;
  minItems?: number;
  maxItems?: number;
  [key: string]: unknown;
}

export interface DescribeSchemaData {
  ocm_version: string[];
  target: "module" | "component";
  section: string | null;
  schema: JsonSchemaNode;
  changelog: string;
}

// -- Agent chat (spec/09 "Agent orchestrator") ---------------------------------------------------

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatToolCallEvent {
  name: string;
  ok: boolean;
  refusal_count: number;
  envelope: Envelope;
}

export interface AgentModel {
  id: string;
  label: string;
}

export interface AgentModelsData {
  models: AgentModel[];
  default: string;
}
