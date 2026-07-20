// SPDX-License-Identifier: AGPL-3.0-or-later
// Central app state. This is presentation/coordination state ONLY -- every
// mutation goes through api/client.ts and every field here is either data
// the server already returned (scene, refusals, warnings) or pure UI
// state (which instance is selected, which are hidden, pending toasts).
// Nothing here decides whether a placement is valid; it renders what the
// server decided.

import { create } from "zustand";
import * as api from "../api/client";
import { ApiTransportError } from "../api/client";
import type { CellInstanceRow, DescribeModuleData, Envelope, ModuleSummary, Mount, RawCellModule, Refusal, ScenePayload } from "../api/types";
import { TOOL_SLOT_OCCUPIED } from "../api/types";

export interface Toast {
  id: string;
  kind: "error" | "warning" | "info";
  title: string;
  message: string;
  hint: string | null;
}

export interface Ghost {
  moduleId: string;
  position: [number, number, number];
  rpyDeg: [number, number, number];
}

export interface PendingConfirm {
  warnings: string[];
  onConfirm: () => void;
}

let nextToastId = 0;
const moveSequence = new Map<string, number>();

interface ComposerState {
  cellId: string | null;
  scene: ScenePayload | null;
  cellInstances: CellInstanceRow[];
  rawCellModules: RawCellModule[];
  modules: ModuleSummary[];
  selectedInstance: string | null;
  inspector: DescribeModuleData | null;
  hiddenInstances: Set<string>;
  refusals: Refusal[];
  toasts: Toast[];
  ghost: Ghost | null;
  toolSlotIncumbent: string | null;
  pendingConfirm: PendingConfirm | null;
  loading: boolean;
  error: string | null;

  loadCell: (cellId: string) => Promise<void>;
  refreshScene: () => Promise<void>;
  selectInstance: (name: string | null) => Promise<void>;
  toggleVisibility: (name: string) => void;
  focusInstance: (name: string) => void;

  placeNewInstance: (moduleId: string, revision: string, instance: string, mount: Mount) => Promise<void>;
  moveExistingInstance: (instance: string, mount: Mount, isFinal?: boolean) => Promise<void>;
  deleteInstance: (instance: string) => void;

  dismissToast: (id: string) => void;
  clearGhost: () => void;
  cancelConfirm: () => void;
}

function pushToastFor(set: (fn: (s: ComposerState) => Partial<ComposerState>) => void, refusals: Refusal[]) {
  const toasts: Toast[] = refusals.map((r) => ({
    id: String(nextToastId++),
    kind: "error",
    title: r.code,
    // Verbatim -- never paraphrase the engine (spec/09 design principle #1).
    message: r.message,
    hint: r.hint,
  }));
  set((s) => ({ toasts: [...s.toasts, ...toasts] }));
}

function handleTransportError(set: (fn: (s: ComposerState) => Partial<ComposerState>) => void, e: unknown) {
  const message = e instanceof ApiTransportError ? e.message : e instanceof Error ? e.message : String(e);
  set((s) => ({
    toasts: [...s.toasts, { id: String(nextToastId++), kind: "error" as const, title: "Connection problem", message, hint: null }],
  }));
}

export const useComposerStore = create<ComposerState>((set, get) => ({
  cellId: null,
  scene: null,
  cellInstances: [],
  rawCellModules: [],
  modules: [],
  selectedInstance: null,
  inspector: null,
  hiddenInstances: new Set(),
  refusals: [],
  toasts: [],
  ghost: null,
  toolSlotIncumbent: null,
  pendingConfirm: null,
  loading: false,
  error: null,

  loadCell: async (cellId: string) => {
    set(() => ({ loading: true, error: null, cellId, selectedInstance: null, inspector: null, hiddenInstances: new Set(), refusals: [], ghost: null }));
    try {
      const [sceneEnv, cellEnv, modulesEnv] = await Promise.all([api.buildScene(cellId), api.describeCell(cellId), api.listModules()]);
      if (!sceneEnv.ok) {
        set(() => ({ loading: false, refusals: sceneEnv.refusals, scene: null }));
        pushToastFor(set, sceneEnv.refusals);
        return;
      }
      set(() => ({
        loading: false,
        scene: sceneEnv.data,
        cellInstances: cellEnv.data?.instances ?? [],
        rawCellModules: cellEnv.data?.cell.modules ?? [],
        modules: (modulesEnv.data ?? []).filter((m) => !m.draft),
      }));
    } catch (e) {
      set(() => ({ loading: false }));
      handleTransportError(set, e);
    }
  },

  refreshScene: async () => {
    const { cellId } = get();
    if (!cellId) return;
    try {
      const [sceneEnv, cellEnv] = await Promise.all([api.buildScene(cellId), api.describeCell(cellId)]);
      if (sceneEnv.ok) {
        set(() => ({ scene: sceneEnv.data, cellInstances: cellEnv.data?.instances ?? [], rawCellModules: cellEnv.data?.cell.modules ?? [] }));
      }
    } catch (e) {
      handleTransportError(set, e);
    }
  },

  selectInstance: async (name: string | null) => {
    set(() => ({ selectedInstance: name, inspector: null }));
    if (!name) return;
    const row = get().cellInstances.find((r) => r.instance === name);
    if (!row) return;
    const [moduleId] = row.module.split("@");
    try {
      const env = await api.describeModule(moduleId);
      if (env.ok) set(() => ({ inspector: env.data }));
    } catch (e) {
      handleTransportError(set, e);
    }
  },

  toggleVisibility: (name: string) =>
    set((s) => {
      const next = new Set(s.hiddenInstances);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return { hiddenInstances: next };
    }),

  focusInstance: (name: string) => {
    set((s) => {
      const next = new Set(s.hiddenInstances);
      next.delete(name);
      return { hiddenInstances: next };
    });
    void get().selectInstance(name);
  },

  placeNewInstance: async (moduleId: string, revision: string, instance: string, mount: Mount) => {
    const { cellId } = get();
    if (!cellId) return;
    try {
      const env: Envelope = await api.placeInstance(cellId, instance, `${moduleId}@${revision}`, mount);
      if (env.ok) {
        set(() => ({ ghost: null, refusals: [], toolSlotIncumbent: null }));
        await get().refreshScene();
        return;
      }
      const toolSlot = env.refusals.find((r) => r.code === TOOL_SLOT_OCCUPIED);
      // A ghost only makes sense for a POSE attempt (workspace overhang,
      // collision, ...) -- a mount.on conflict (TOOL_SLOT_OCCUPIED) has no
      // "attempted xyz" to draw; the incumbent highlight covers that case.
      const ghost: Ghost | null = mount.pose
        ? { moduleId, position: mount.pose.xyz_mm.map((v) => v / 1000) as [number, number, number], rpyDeg: mount.pose.rpy_deg }
        : null;
      set(() => ({
        refusals: env.refusals,
        ghost,
        toolSlotIncumbent: (toolSlot?.allowed?.incumbent as string | undefined) ?? null,
      }));
      pushToastFor(set, env.refusals);
    } catch (e) {
      handleTransportError(set, e);
    }
  },

  moveExistingInstance: async (instance: string, mount: Mount, isFinal = true) => {
    const { cellId } = get();
    if (!cellId) return;
    // A drag fires many debounced in-flight calls for the SAME instance;
    // network ordering doesn't guarantee the pointer-up (final) call's
    // response arrives last. Only the most-recently-STARTED call for this
    // instance is allowed to update refusals/toast/scene -- a late-arriving
    // stale response is silently dropped instead of clobbering the final
    // result.
    const sequence = (moveSequence.get(instance) ?? 0) + 1;
    moveSequence.set(instance, sequence);
    const isStale = () => moveSequence.get(instance) !== sequence;
    try {
      const env: Envelope = await api.moveInstance(cellId, instance, mount);
      if (isStale()) return;
      if (env.ok) {
        set(() => ({ refusals: [], toolSlotIncumbent: null }));
        await get().refreshScene();
        return;
      }
      const toolSlot = env.refusals.find((r) => r.code === TOOL_SLOT_OCCUPIED);
      set(() => ({ refusals: env.refusals, toolSlotIncumbent: (toolSlot?.allowed?.incumbent as string | undefined) ?? null }));
      // A drag fires many debounced intermediate calls -- only the FINAL
      // one (pointer-up) toasts, or a single continuous drag would spam
      // one toast per debounce tick. The issues panel still updates live.
      if (isFinal) pushToastFor(set, env.refusals);
      // The write still happened server-side even on refusal (spec/09:
      // writes are unconditional); re-fetch so the 3D view reflects
      // whatever landed, not a stale optimistic guess.
      await get().refreshScene();
    } catch (e) {
      handleTransportError(set, e);
    }
  },

  deleteInstance: (instance: string) => {
    const { cellId } = get();
    if (!cellId) return;

    // spec/09: writes are unconditional -- remove_instance always
    // actually removes the instance, there's no dry-run to preview the
    // impact before it happens. So the confirm step can't gate the
    // removal itself; it gates on the SERVER'S OWN warnings[] about what
    // that removal just orphaned (a plan step, a stale tool: reference)
    // -- an acknowledgment the user must dismiss, quoting the engine's
    // own words, not a generic "are you sure".
    void (async () => {
      try {
        const env = await api.removeInstance(cellId, instance);
        set((s) => ({
          selectedInstance: s.selectedInstance === instance ? null : s.selectedInstance,
          refusals: env.refusals,
        }));
        if (!env.ok) pushToastFor(set, env.refusals);
        if (env.warnings.length > 0) {
          set(() => ({ pendingConfirm: { warnings: env.warnings, onConfirm: () => set(() => ({ pendingConfirm: null })) } }));
        }
        await get().refreshScene();
      } catch (e) {
        handleTransportError(set, e);
      }
    })();
  },

  dismissToast: (id: string) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  clearGhost: () => set(() => ({ ghost: null, toolSlotIncumbent: null })),
  cancelConfirm: () => set(() => ({ pendingConfirm: null })),
}));
