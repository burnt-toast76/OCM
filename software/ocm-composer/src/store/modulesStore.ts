// SPDX-License-Identifier: AGPL-3.0-or-later
// Modules-page state ONLY -- a separate store from store.ts (the cell
// composer's) and componentsStore.ts, same convention: everything here is
// either data the server already returned or pure UI state. Component-
// instance placement goes through update_module's own generic patch/
// manifest write -- NEVER place_instance/move_instance (those are
// cell-specific verbs with cell-specific refusal codes like
// OCM_WORKSPACE_OVERHANG/OCM_TOOL_SLOT_OCCUPIED that don't apply to placing a
// component inside a module's own local assembly scene).

import { create } from "zustand";
import * as api from "../api/client";
import { ApiTransportError } from "../api/client";
import type {
  AttachmentRow,
  ComponentDoc,
  ComponentSummary,
  DescribeModuleData,
  ModuleLinkRow,
  ModuleNetRow,
  ModuleSummary,
  Pose6d,
  Refusal,
} from "../api/types";

interface ModulesState {
  modules: ModuleSummary[];
  selectedModuleId: string | null;
  detail: DescribeModuleData | null;
  attachments: AttachmentRow[]; // the module's own uploaded STEP/GLB backdrop file(s)
  componentOptions: ComponentSummary[]; // PUBLISHED components only -- the placement picker's own list
  // componentId -> that component's own ready STEP-derived GLB download
  // url, resolved once alongside componentOptions (not per drag frame,
  // not per render) -- absent entirely for a component with no converted
  // GLB yet, which ComponentInstance treats as "nothing to render".
  componentGlbUrls: Record<string, string>;
  // componentId -> that component's own full definition (electrical.
  // connectors[].pins[], etc.) -- the wiring canvas's only source of pin
  // data; never mutated locally, only ever replaced wholesale by a fresh
  // describe_component read (ADR-0015 Decision 4: no path to invent a pin).
  componentDocs: Record<string, ComponentDoc>;
  checklist: Refusal[]; // validate_module's own refusals -- ADR-0016: the same checks resolve_cell would run
  selectedRefdes: string | null; // which placed instance the rotate side-panel (next pass) edits
  dragging: boolean; // mirrors store.ts's own dragging flag -- ModuleSceneCanvas's OrbitControls enabled prop
  placementError: string | null; // a refusal/error message, rendered verbatim, never reinterpreted
  loading: boolean;
  error: string | null;

  loadModules: () => Promise<void>;
  selectModule: (id: string) => Promise<void>;
  createDraft: (id: string, kind: string) => Promise<void>;
  publish: (revision: string) => Promise<void>;
  refreshAttachments: () => Promise<void>;
  refreshChecklist: () => Promise<void>;
  refreshComponentDocs: () => Promise<void>;
  uploadStepAttachment: (file: File) => Promise<void>;
  setDragging: (dragging: boolean) => void;
  selectComponentInstance: (refdes: string | null) => void;
  placeComponentInstance: (refdes: string, ref: string, pose: Pose6d) => Promise<void>;
  moveComponentInstance: (refdes: string, pose: Pose6d) => Promise<void>;
  removeComponentInstance: (refdes: string) => Promise<void>;
  // ADR-0015: nets/links editing -- same round-trip as
  // placeComponentInstance/moveComponentInstance (edit the array locally,
  // send the WHOLE thing via update_module, re-read the server-confirmed
  // manifest), never a nested incremental patch. Domain-scoped
  // (setElectricalNets only ever touches nets.electrical) rather than one
  // "setNets" that could clobber a pneumatic array this UI doesn't even
  // show yet.
  setElectricalNets: (nets: ModuleNetRow[]) => Promise<void>;
  setLinks: (links: ModuleLinkRow[]) => Promise<void>;
  clearError: () => void;
  clearPlacementError: () => void;
}

// Component summaries are keyed by refdes for placement -- describe_module
// only gives us `ref` ("id@revision") per components[] row, so the index
// a refdes maps to (needed for RFC-6902 "/components/<index>/..." patch
// paths) is derived fresh from `detail.manifest.components` on every call,
// never cached -- the array can be reordered by the server on any write.
function indexOfRefdes(detail: DescribeModuleData, refdes: string): number {
  return (detail.manifest.components ?? []).findIndex((c) => c.refdes === refdes);
}

export const useModulesStore = create<ModulesState>((set, get) => ({
  modules: [],
  selectedModuleId: null,
  detail: null,
  attachments: [],
  componentOptions: [],
  componentGlbUrls: {},
  componentDocs: {},
  checklist: [],
  selectedRefdes: null,
  dragging: false,
  placementError: null,
  loading: false,
  error: null,

  loadModules: async () => {
    set(() => ({ loading: true, error: null }));
    try {
      const env = await api.listModules();
      set(() => ({ loading: false, modules: env.data ?? [] }));
    } catch (e) {
      set(() => ({ loading: false, error: e instanceof Error ? e.message : String(e) }));
    }
  },

  selectModule: async (id: string) => {
    set(() => ({
      selectedModuleId: id,
      detail: null,
      attachments: [],
      checklist: [],
      selectedRefdes: null,
      placementError: null,
      error: null,
    }));

    try {
      if (get().componentOptions.length === 0) {
        const componentsEnv = await api.listComponents();
        // Published only (revision >= 1.0.0, draft: false) -- a draft
        // component is refusable at cell-resolution time either way
        // (OCM_DRAFT_MODULE_REFERENCED), so offering it in the picker would
        // just be a save that's guaranteed to bite later.
        const published = (componentsEnv.data ?? []).filter((c) => !c.draft);
        set(() => ({ componentOptions: published }));

        // Resolved once here, not per drag frame or per render: each
        // published component's own ready STEP-derived GLB (if it has
        // one) becomes the mesh ComponentInstance renders once that
        // component is placed. A component with no converted GLB yet is
        // simply absent from the map -- still placeable (the manifest
        // entry and its pose are real either way), just invisible in the
        // 3D scene until a GLB exists.
        const glbEntries = await Promise.all(
          published.map(async (c): Promise<[string, string] | null> => {
            try {
              const files = await api.listComponentAttachments(c.id);
              const ready = files.find((f) => f.kind === "step" && f.glb_status === "ready" && f.glb);
              return ready?.glb ? [c.id, api.attachmentDownloadUrl(c.id, ready.glb)] : null;
            } catch {
              return null;
            }
          }),
        );
        const componentGlbUrls = Object.fromEntries(glbEntries.filter((e): e is [string, string] => e !== null));
        set(() => ({ componentGlbUrls }));
      }
      const [detailEnv] = await Promise.all([api.describeModule(id), get().refreshAttachments(), get().refreshChecklist()]);
      if (detailEnv.data) set(() => ({ detail: detailEnv.data }));
      await get().refreshComponentDocs();
    } catch (e) {
      set(() => ({ error: e instanceof Error ? e.message : String(e) }));
    }
  },

  createDraft: async (id: string, kind: string) => {
    set(() => ({ loading: true, error: null }));
    try {
      const env = await api.createModuleDraft(id, kind);
      if (!env.ok) {
        set(() => ({ loading: false, error: env.refusals[0]?.message ?? "create_module_draft was refused" }));
        return;
      }
      await get().loadModules();
      set(() => ({ loading: false }));
      await get().selectModule(id);
    } catch (e) {
      set(() => ({ loading: false, error: e instanceof Error ? e.message : String(e) }));
    }
  },

  publish: async (revision: string) => {
    const { selectedModuleId } = get();
    if (!selectedModuleId) return;
    try {
      const env = await api.publishModule(selectedModuleId, revision);
      if (!env.ok) {
        set(() => ({ error: env.refusals[0]?.message ?? "publish_module was refused" }));
        return;
      }
      await Promise.all([get().loadModules(), get().selectModule(selectedModuleId)]);
    } catch (e) {
      set(() => ({ error: e instanceof Error ? e.message : String(e) }));
    }
  },

  refreshAttachments: async () => {
    const { selectedModuleId } = get();
    if (!selectedModuleId) return;
    try {
      const files = await api.listModuleAttachments(selectedModuleId);
      set(() => ({ attachments: files }));
      // Same self-polling pattern as componentsStore.refreshAttachments --
      // STEP->GLB conversion runs in a background thread server-side and
      // can take minutes for a real file. Stops on its own once nothing's
      // pending, or the moment the user looks at something else.
      if (files.some((f) => f.glb_status === "pending")) {
        setTimeout(() => {
          if (get().selectedModuleId === selectedModuleId) void get().refreshAttachments();
        }, 4000);
      }
    } catch (e) {
      set(() => ({ error: e instanceof Error ? e.message : String(e) }));
    }
  },

  uploadStepAttachment: async (file: File) => {
    const { selectedModuleId } = get();
    if (!selectedModuleId) return;
    try {
      await api.uploadModuleAttachment(selectedModuleId, file);
      await get().refreshAttachments();
    } catch (e) {
      const message = e instanceof ApiTransportError ? e.message : e instanceof Error ? e.message : String(e);
      set(() => ({ error: message }));
    }
  },

  refreshChecklist: async () => {
    const { selectedModuleId } = get();
    if (!selectedModuleId) return;
    try {
      const env = await api.validateModule(selectedModuleId);
      const refusals = env.ok ? [] : env.refusals;
      set(() => ({ checklist: refusals }));
    } catch (e) {
      set(() => ({ error: e instanceof Error ? e.message : String(e) }));
    }
  },

  refreshComponentDocs: async () => {
    const { detail, componentDocs } = get();
    if (!detail) return;
    const ids = Array.from(new Set((detail.manifest.components ?? []).map((c) => c.ref.split("@")[0])));
    const missing = ids.filter((id) => !(id in componentDocs));
    if (missing.length === 0) return;
    try {
      const entries = await Promise.all(
        missing.map(async (id): Promise<[string, ComponentDoc] | null> => {
          try {
            const env = await api.describeComponent(id);
            return env.data ? [id, env.data.component] : null;
          } catch {
            return null;
          }
        }),
      );
      const newDocs = Object.fromEntries(entries.filter((e): e is [string, ComponentDoc] => e !== null));
      set((state) => ({ componentDocs: { ...state.componentDocs, ...newDocs } }));
    } catch (e) {
      set(() => ({ error: e instanceof Error ? e.message : String(e) }));
    }
  },

  setDragging: (dragging: boolean) => set(() => ({ dragging })),

  selectComponentInstance: (refdes: string | null) => set(() => ({ selectedRefdes: refdes })),

  placeComponentInstance: async (refdes: string, ref: string, pose: Pose6d) => {
    const { selectedModuleId, detail } = get();
    if (!selectedModuleId || !detail) return;
    const existing = detail.manifest.components ?? [];
    try {
      // A full replacement of the components: array, not an "add" op at
      // an index -- simplest correct way to append one entry without
      // needing to know the array's current length via a separate read.
      const env = await api.updateModule(selectedModuleId, {
        patch: [{ op: existing.length > 0 ? "replace" : "add", path: "/components", value: [...existing, { refdes, ref, pose }] }],
      });
      if (!env.ok) {
        set(() => ({ placementError: env.refusals[0]?.message ?? "update_module was refused" }));
        return;
      }
      set(() => ({ placementError: null }));
      const detailEnv = await api.describeModule(selectedModuleId);
      if (detailEnv.data) set(() => ({ detail: detailEnv.data }));
      await Promise.all([get().refreshChecklist(), get().refreshComponentDocs()]);
    } catch (e) {
      set(() => ({ placementError: e instanceof Error ? e.message : String(e) }));
    }
  },

  moveComponentInstance: async (refdes: string, pose: Pose6d) => {
    const { selectedModuleId, detail } = get();
    if (!selectedModuleId || !detail) return;
    const index = indexOfRefdes(detail, refdes);
    if (index === -1) return;
    try {
      const env = await api.updateModule(selectedModuleId, {
        patch: [{ op: "add", path: `/components/${index}/pose`, value: pose }],
      });
      if (!env.ok) {
        set(() => ({ placementError: env.refusals[0]?.message ?? "update_module was refused" }));
        return;
      }
      set(() => ({ placementError: null }));
      const detailEnv = await api.describeModule(selectedModuleId);
      if (detailEnv.data) set(() => ({ detail: detailEnv.data }));
      await get().refreshChecklist();
    } catch (e) {
      set(() => ({ placementError: e instanceof Error ? e.message : String(e) }));
    }
  },

  removeComponentInstance: async (refdes: string) => {
    const { selectedModuleId, detail } = get();
    if (!selectedModuleId || !detail) return;
    const index = indexOfRefdes(detail, refdes);
    if (index === -1) return;
    try {
      const env = await api.updateModule(selectedModuleId, {
        patch: [{ op: "remove", path: `/components/${index}` }],
      });
      if (!env.ok) {
        set(() => ({ placementError: env.refusals[0]?.message ?? "update_module was refused" }));
        return;
      }
      set((state) => ({ placementError: null, selectedRefdes: state.selectedRefdes === refdes ? null : state.selectedRefdes }));
      const detailEnv = await api.describeModule(selectedModuleId);
      if (detailEnv.data) set(() => ({ detail: detailEnv.data }));
      await get().refreshChecklist();
    } catch (e) {
      set(() => ({ placementError: e instanceof Error ? e.message : String(e) }));
    }
  },

  setElectricalNets: async (nets: ModuleNetRow[]) => {
    const { selectedModuleId, detail } = get();
    if (!selectedModuleId || !detail) return;
    // Whole-object replace at /nets, not a nested /nets/electrical patch:
    // RFC-6902 "add"/"replace" at a nested path requires the parent to
    // already exist, and /nets may not -- same reasoning
    // placeComponentInstance applies to /components. Preserves whatever
    // pneumatic nets already exist (this UI doesn't edit them yet).
    const existingNets = detail.manifest.nets;
    const nextNets = { ...existingNets, electrical: nets };
    try {
      const env = await api.updateModule(selectedModuleId, {
        patch: [{ op: existingNets ? "replace" : "add", path: "/nets", value: nextNets }],
      });
      if (!env.ok) {
        set(() => ({ placementError: env.refusals[0]?.message ?? "update_module was refused" }));
        return;
      }
      set(() => ({ placementError: null }));
      const detailEnv = await api.describeModule(selectedModuleId);
      if (detailEnv.data) set(() => ({ detail: detailEnv.data }));
      await get().refreshChecklist();
    } catch (e) {
      set(() => ({ placementError: e instanceof Error ? e.message : String(e) }));
    }
  },

  setLinks: async (links: ModuleLinkRow[]) => {
    const { selectedModuleId, detail } = get();
    if (!selectedModuleId || !detail) return;
    const existingLinks = detail.manifest.links ?? [];
    try {
      // Same top-level-array-replace shape as /components -- no nested
      // parent-existence concern here since links is a flat array, not an
      // object with domain-keyed sub-arrays like nets.
      const env = await api.updateModule(selectedModuleId, {
        patch: [{ op: existingLinks.length > 0 ? "replace" : "add", path: "/links", value: links }],
      });
      if (!env.ok) {
        set(() => ({ placementError: env.refusals[0]?.message ?? "update_module was refused" }));
        return;
      }
      set(() => ({ placementError: null }));
      const detailEnv = await api.describeModule(selectedModuleId);
      if (detailEnv.data) set(() => ({ detail: detailEnv.data }));
      await get().refreshChecklist();
    } catch (e) {
      set(() => ({ placementError: e instanceof Error ? e.message : String(e) }));
    }
  },

  clearError: () => set(() => ({ error: null })),
  clearPlacementError: () => set(() => ({ placementError: null })),
}));
