// SPDX-License-Identifier: AGPL-3.0-or-later
// Components-page state ONLY -- a separate store from store.ts (the cell
// composer's), same convention: everything here is either data the
// server already returned or pure UI state, nothing decides whether a
// transcription is valid. Every commit goes through update_component;
// this store renders what the server decided, same as the cell composer
// renders refusals rather than re-deriving them.

import { create } from "zustand";
import * as api from "../api/client";
import { ApiTransportError } from "../api/client";
import type { AgentModel, AttachmentResult, AttachmentRow, ChatMessage, ChatToolCallEvent, ComponentDoc, ComponentSummary, DescribeComponentData, Envelope, JsonSchemaNode, Refusal } from "../api/types";
import { groupRefusalsByField } from "../ui/components/refusalField";

export interface ChatTurnToolCall {
  name: string;
  ok: boolean;
  refusalCount: number;
  envelope: Envelope;
}

export interface ChatTurn {
  id: string;
  role: "user" | "assistant";
  text: string;
  toolCalls: ChatTurnToolCall[];
  streaming?: boolean;
}

let nextTurnId = 0;

// Which top-level sections differ between two component docs -- used to
// mark fields the agent just filled (spec: "a subtle marker"). Top-level
// granularity only: enough to highlight "electrical" or "pneumatic" as
// agent-touched without tracking every nested path.
function diffTopLevelKeys(before: ComponentDoc | null, after: ComponentDoc): string[] {
  const beforeObj: Record<string, unknown> = before ?? {};
  const keys = new Set([...Object.keys(beforeObj), ...Object.keys(after)]);
  const changed: string[] = [];
  for (const key of keys) {
    if (JSON.stringify(beforeObj[key]) !== JSON.stringify(after[key])) changed.push(key);
  }
  return changed;
}

interface ComponentsState {
  components: ComponentSummary[];
  selectedComponentId: string | null;
  detail: DescribeComponentData | null;
  schema: JsonSchemaNode | null;
  checklist: Refusal[];
  fieldErrors: Record<string, Refusal[]>;
  agentFilledFields: Set<string>;
  attachments: AttachmentRow[]; // everything previously uploaded for this component, from disk
  stagedAttachments: AttachmentResult[]; // uploaded THIS session, pending inclusion in the next chat message
  chatTurns: ChatTurn[];
  chatStreaming: boolean;
  agentModels: AgentModel[];
  selectedModel: string | null; // null defers to the server's own default until the picker has loaded
  loading: boolean;
  error: string | null;

  loadComponents: () => Promise<void>;
  selectComponent: (id: string) => Promise<void>;
  createDraft: (id: string, kind: string, initialFields?: Record<string, unknown>) => Promise<void>;
  saveField: (path: string[], value: unknown) => Promise<void>;
  refreshChecklist: () => Promise<void>;
  refreshAttachments: () => Promise<void>;
  publish: (revision: string) => Promise<void>;
  deleteComponent: (id: string) => Promise<void>;
  setSelectedModel: (id: string) => void;
  sendChatMessage: (text: string) => void;
  uploadAttachment: (file: File) => Promise<void>;
  removeStagedAttachment: (filename: string) => void;
  clearError: () => void;
}

function setAtPath(doc: ComponentDoc, path: string[], value: unknown): ComponentDoc {
  const next: ComponentDoc = { ...doc };
  let cursor: Record<string, unknown> = next;
  for (let i = 0; i < path.length - 1; i++) {
    const key = path[i];
    const existing = cursor[key];
    // An array-of-objects field (electrical.supplies, comms.signals, ...)
    // walked through as an INTERMEDIATE segment -- e.g. committing row 0's
    // own "rail" field, path ["electrical","supplies","0","rail"] -- used
    // to fall through the `!Array.isArray` branch below and get replaced
    // with a fresh `{}`, silently turning the array into a plain object
    // keyed by the stringified index ("0") instead of a real array index.
    // Confirmed in the wild: a real draft's `supplies` ended up as
    // `{"0": {rail: "24VDC"}}`, which then crashed SchemaField's own
    // `rows.map` (it assumes an array, per the schema). Cloning an
    // existing array AS an array is what keeps it an array.
    const copy: Record<string, unknown> | unknown[] = Array.isArray(existing)
      ? [...existing]
      : existing && typeof existing === "object"
        ? { ...(existing as Record<string, unknown>) }
        : {};
    cursor[key] = copy;
    cursor = copy as Record<string, unknown>;
  }
  const lastKey = path[path.length - 1];
  if (value === undefined) {
    delete cursor[lastKey];
  } else {
    cursor[lastKey] = value;
  }
  return next;
}

let activeChatAbort: (() => void) | null = null;
// See saveField's own docstring -- serializes field commits so a fast
// second edit can't build off a stale pre-first-edit snapshot.
let saveQueue: Promise<void> = Promise.resolve();

export const useComponentsStore = create<ComponentsState>((set, get) => ({
  components: [],
  selectedComponentId: null,
  detail: null,
  schema: null,
  checklist: [],
  fieldErrors: {},
  agentFilledFields: new Set(),
  attachments: [],
  stagedAttachments: [],
  chatTurns: [],
  chatStreaming: false,
  agentModels: [],
  selectedModel: null,
  loading: false,
  error: null,

  loadComponents: async () => {
    set(() => ({ loading: true, error: null }));
    try {
      const env = await api.listComponents();
      set(() => ({ loading: false, components: env.data ?? [] }));
    } catch (e) {
      set(() => ({ loading: false, error: e instanceof Error ? e.message : String(e) }));
    }
  },

  selectComponent: async (id: string) => {
    set(() => ({
      selectedComponentId: id,
      detail: null,
      checklist: [],
      fieldErrors: {},
      agentFilledFields: new Set(),
      attachments: [],
      stagedAttachments: [],
      chatTurns: [],
      error: null,
    }));
    activeChatAbort?.();
    activeChatAbort = null;

    try {
      if (!get().schema) {
        const schemaEnv = await api.describeSchema(undefined, "component");
        if (schemaEnv.ok && schemaEnv.data) set(() => ({ schema: schemaEnv.data!.schema }));
      }
      if (get().agentModels.length === 0) {
        const modelsData = await api.getAgentModels();
        set(() => ({ agentModels: modelsData.models, selectedModel: get().selectedModel ?? modelsData.default }));
      }
      // describe_component succeeds (with warnings) even for an
      // incomplete draft (ADR-0014: that's the expected in-progress
      // state, not a broken one) -- gate on `data`, not `ok`.
      const [detailEnv] = await Promise.all([api.describeComponent(id), get().refreshChecklist(), get().refreshAttachments()]);
      if (detailEnv.data) set(() => ({ detail: detailEnv.data }));
    } catch (e) {
      set(() => ({ error: e instanceof Error ? e.message : String(e) }));
    }
  },

  refreshAttachments: async () => {
    const { selectedComponentId } = get();
    if (!selectedComponentId) return;
    try {
      const files = await api.listComponentAttachments(selectedComponentId);
      set(() => ({ attachments: files }));
      // STEP->GLB conversion runs in a background thread server-side and
      // can take minutes for a real file -- self-poll while anything is
      // still converting, so the viewer appears on its own once it's
      // ready instead of needing a manual reload. Stops on its own once
      // nothing's pending, or the moment the user looks at something else.
      if (files.some((f) => f.glb_status === "pending")) {
        setTimeout(() => {
          if (get().selectedComponentId === selectedComponentId) void get().refreshAttachments();
        }, 4000);
      }
    } catch (e) {
      set(() => ({ error: e instanceof Error ? e.message : String(e) }));
    }
  },

  createDraft: async (id: string, kind: string, initialFields?: Record<string, unknown>) => {
    set(() => ({ loading: true, error: null }));
    try {
      const env = await api.createComponentDraft(id, kind);
      if (!env.ok) {
        set(() => ({ loading: false, error: env.refusals[0]?.message ?? "create_component_draft was refused" }));
        return;
      }
      // Patched in right after the scaffold write, still part of the same
      // "create" gesture from the human's point of view -- create_component_draft
      // itself stays a bare (id, kind) scaffold (ADR-0014: never pre-filled
      // by the verb itself), same as it's always been for the AI chat path.
      if (initialFields && Object.keys(initialFields).length > 0) {
        const patch = Object.entries(initialFields).map(([path, value]) => ({ op: "add", path: `/${path}`, value }));
        await api.updateComponent(id, { patch });
      }
      await get().loadComponents();
      set(() => ({ loading: false }));
      await get().selectComponent(id);
    } catch (e) {
      set(() => ({ loading: false, error: e instanceof Error ? e.message : String(e) }));
    }
  },

  saveField: (path: string[], value: unknown) => {
    // Queued, not fired directly: two fields committed in quick
    // succession (e.g. blurring one input right after another, before
    // the first's own round trip lands) would otherwise both read the
    // SAME stale `detail.component` snapshot at call time and each build
    // their own full-manifest write from it -- the second write, landing
    // after the first, would silently overwrite the first field's change
    // with a document that never saw it (a lost update). Chaining onto
    // `saveQueue` means each save's own `get().detail` read only happens
    // once every save queued before it has actually landed (including
    // the describe_component refresh that updates `detail`), so it's
    // always building on the true latest state, never a stale one.
    const run = async () => {
      const { selectedComponentId, detail } = get();
      if (!selectedComponentId || !detail) return;
      const nextDoc = setAtPath(detail.component, path, value);
      try {
        // update_component ALWAYS writes, even when refused (spec/09) --
        // the doc on disk matches nextDoc either way, so refresh from the
        // server's own describe_component rather than trusting the
        // locally-computed nextDoc might have diverged from what actually
        // persisted (e.g. a schema coercion).
        await api.updateComponent(selectedComponentId, { manifest: nextDoc as Record<string, unknown> });
        const detailEnv = await api.describeComponent(selectedComponentId);
        if (detailEnv.data) set(() => ({ detail: detailEnv.data }));
        await get().refreshChecklist();
      } catch (e) {
        set(() => ({ error: e instanceof Error ? e.message : String(e) }));
      }
    };
    saveQueue = saveQueue.then(run);
    return saveQueue;
  },

  refreshChecklist: async () => {
    const { selectedComponentId } = get();
    if (!selectedComponentId) return;
    try {
      const env = await api.validateComponent(selectedComponentId);
      const refusals = env.ok ? [] : env.refusals;
      set(() => ({ checklist: refusals, fieldErrors: groupRefusalsByField(refusals) }));
    } catch (e) {
      set(() => ({ error: e instanceof Error ? e.message : String(e) }));
    }
  },

  publish: async (revision: string) => {
    const { selectedComponentId } = get();
    if (!selectedComponentId) return;
    try {
      const env = await api.publishComponent(selectedComponentId, revision);
      if (!env.ok) {
        set(() => ({ error: env.refusals[0]?.message ?? "publish_component was refused" }));
        return;
      }
      await Promise.all([get().loadComponents(), get().selectComponent(selectedComponentId)]);
    } catch (e) {
      set(() => ({ error: e instanceof Error ? e.message : String(e) }));
    }
  },

  deleteComponent: async (id: string) => {
    try {
      const env = await api.deleteComponent(id);
      if (!env.ok) {
        set(() => ({ error: env.refusals[0]?.message ?? "delete_component was refused" }));
        return;
      }
      const { selectedComponentId } = get();
      if (selectedComponentId === id) {
        activeChatAbort?.();
        activeChatAbort = null;
        set(() => ({
          selectedComponentId: null,
          detail: null,
          checklist: [],
          fieldErrors: {},
          agentFilledFields: new Set(),
          attachments: [],
          stagedAttachments: [],
          chatTurns: [],
        }));
      }
      // Same "server decided, this store just renders it" convention as
      // every other write here -- a reference warning goes through the
      // same `error` surface a refusal would, it just isn't fatal to the
      // delete itself (spec/09: writes are unconditional).
      set(() => ({ error: env.warnings[0] ?? null }));
      await get().loadComponents();
    } catch (e) {
      set(() => ({ error: e instanceof Error ? e.message : String(e) }));
    }
  },

  uploadAttachment: async (file: File) => {
    const { selectedComponentId } = get();
    if (!selectedComponentId) return;
    try {
      const result = await api.uploadComponentAttachment(selectedComponentId, file);
      set((s) => ({ stagedAttachments: [...s.stagedAttachments.filter((a) => a.filename !== result.filename), result] }));
      await get().refreshAttachments();
    } catch (e) {
      const message = e instanceof ApiTransportError ? e.message : e instanceof Error ? e.message : String(e);
      set(() => ({ error: message }));
    }
  },

  removeStagedAttachment: (filename: string) => set((s) => ({ stagedAttachments: s.stagedAttachments.filter((a) => a.filename !== filename) })),

  setSelectedModel: (id: string) => set(() => ({ selectedModel: id })),

  sendChatMessage: (text: string) => {
    const { selectedComponentId, chatTurns, stagedAttachments, selectedModel } = get();
    activeChatAbort?.();

    const userTurn: ChatTurn = { id: String(nextTurnId++), role: "user", text, toolCalls: [] };
    const assistantTurn: ChatTurn = { id: String(nextTurnId++), role: "assistant", text: "", toolCalls: [], streaming: true };
    set((s) => ({ chatTurns: [...s.chatTurns, userTurn, assistantTurn], chatStreaming: true, stagedAttachments: [] }));

    const history: ChatMessage[] = [...chatTurns.filter((t) => !t.streaming).map((t) => ({ role: t.role, content: t.text })), { role: "user", content: text }];

    const docBeforeThisMessage = get().detail?.component ?? null;

    const { abort } = api.streamAgentChat(
      {
        component_id: selectedComponentId,
        messages: history,
        attachment_filenames: stagedAttachments.map((a) => a.filename),
        ...(selectedModel ? { model: selectedModel } : {}),
      },
      {
        onText: (delta) => {
          set((s) => ({
            chatTurns: s.chatTurns.map((t) => (t.id === assistantTurn.id ? { ...t, text: t.text + delta } : t)),
          }));
        },
        onToolCall: (event: ChatToolCallEvent) => {
          set((s) => ({
            chatTurns: s.chatTurns.map((t) =>
              t.id === assistantTurn.id
                ? { ...t, toolCalls: [...t.toolCalls, { name: event.name, ok: event.ok, refusalCount: event.refusal_count, envelope: event.envelope }] }
                : t,
            ),
          }));
          if (event.ok && (event.name === "update_component" || event.name === "create_component_draft") && selectedComponentId) {
            void (async () => {
              const detailEnv = await api.describeComponent(selectedComponentId);
              if (detailEnv.data) {
                const changed = diffTopLevelKeys(docBeforeThisMessage, detailEnv.data.component);
                set((s) => ({ detail: detailEnv.data, agentFilledFields: new Set([...s.agentFilledFields, ...changed]) }));
              }
              await get().refreshChecklist();
            })();
          }
        },
        onError: (envelope) => {
          set((s) => ({
            chatStreaming: false,
            chatTurns: s.chatTurns.map((t) =>
              t.id === assistantTurn.id ? { ...t, streaming: false, text: t.text || (envelope.refusals[0]?.message ?? "The agent is unavailable.") } : t,
            ),
            error: envelope.refusals[0]?.message ?? "agent/chat failed",
          }));
        },
        onDone: () => {
          set((s) => ({ chatStreaming: false, chatTurns: s.chatTurns.map((t) => (t.id === assistantTurn.id ? { ...t, streaming: false } : t)) }));
        },
      },
    );
    activeChatAbort = abort;
  },

  clearError: () => set(() => ({ error: null })),
}));
