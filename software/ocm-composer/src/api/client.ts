// SPDX-License-Identifier: AGPL-3.0-or-later
// A pure HTTP client of ocm-api (ADR-0012: "the web composer calls the
// exact same verbs" the MCP server exposes to agents). Every function
// here does nothing but build a request, parse the response JSON as an
// Envelope, and return it -- NO interpretation of what a refusal means,
// no re-validation, no rule logic. `ok:false` is a normal, successfully
// parsed result (spec/09 design principle #1), not a thrown error;
// `ApiTransportError` is reserved for genuine transport failures (network
// down, a non-2xx status, a body that isn't even valid JSON) that mean
// the call never reached the refusal engine at all.

import type {
  AgentModelsData,
  AttachmentResult,
  AttachmentRow,
  CellSummary,
  ChatMessage,
  ChatToolCallEvent,
  CompositionResult,
  ComponentSummary,
  DescribeCellData,
  DescribeComponentData,
  DescribeModuleData,
  DescribeSchemaData,
  Envelope,
  ModuleSummary,
  Mount,
  ScenePayload,
  UpdateComponentResult,
} from "./types";
import type { GetVerb, PostVerb } from "./verbs";

export class ApiTransportError extends Error {
  readonly status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "ApiTransportError";
    this.status = status;
  }
}

async function parseEnvelope<T>(res: Response, verb: string): Promise<Envelope<T>> {
  if (!res.ok) {
    throw new ApiTransportError(`${verb}: HTTP ${res.status} ${res.statusText}`, res.status);
  }
  try {
    return (await res.json()) as Envelope<T>;
  } catch {
    throw new ApiTransportError(`${verb}: response body was not valid JSON`);
  }
}

async function get<T>(verb: GetVerb, params?: Record<string, string>): Promise<Envelope<T>> {
  const qs = params ? `?${new URLSearchParams(params).toString()}` : "";
  let res: Response;
  try {
    res = await fetch(`/${verb}${qs}`);
  } catch (e) {
    throw new ApiTransportError(`${verb}: ${(e as Error).message}`);
  }
  return parseEnvelope<T>(res, verb);
}

async function post<T>(verb: PostVerb, body: unknown): Promise<Envelope<T>> {
  let res: Response;
  try {
    res = await fetch(`/${verb}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (e) {
    throw new ApiTransportError(`${verb}: ${(e as Error).message}`);
  }
  return parseEnvelope<T>(res, verb);
}

// -- Discovery ---------------------------------------------------

export const listCells = () => get<CellSummary[]>("list_cells");

export const listModules = () => get<ModuleSummary[]>("list_modules");

export const describeModule = (id: string) => get<DescribeModuleData>("describe_module", { id });

export const createModuleDraft = (id: string, kind: string) =>
  post<{ id: string; revision: string; draft: boolean }>("create_module_draft", { id, kind });

export const updateModule = (id: string, body: { manifest?: Record<string, unknown>; patch?: Record<string, unknown>[] }) =>
  post<{ id: string; revision: string; draft: boolean; path: string }>("update_module", { id, ...body });

export const validateModule = (id: string) => post<{ id: string; valid: boolean }>("validate_module", { id });

export const publishModule = (id: string, revision: string) =>
  post<{ id: string; revision: string; draft: boolean; published: boolean }>("publish_module", { id, revision });

export const describeCell = (id: string) => get<DescribeCellData>("describe_cell", { id });

// -- Checking & generation ---------------------------------------------------

export const buildScene = (cell: string) => post<ScenePayload>("build_scene", { cell });

// -- Cell composition ---------------------------------------------------

export const placeInstance = (cell: string, instance: string, module: string, mount: Mount) =>
  post<CompositionResult>("place_instance", { cell, instance, module, mount });

export const moveInstance = (cell: string, instance: string, mount: Mount) =>
  post<CompositionResult>("move_instance", { cell, instance, mount });

export const removeInstance = (cell: string, instance: string) => post<CompositionResult>("remove_instance", { cell, instance });

// -- Components (ADR-0014, spec/10) ---------------------------------------------------

export const listComponents = () => get<ComponentSummary[]>("list_components");

export const describeComponent = (id: string) => get<DescribeComponentData>("describe_component", { id });

export const describeSchema = (section?: string, target: "module" | "component" = "module") =>
  get<DescribeSchemaData>("describe_schema", { ...(section ? { section } : {}), target });

export const createComponentDraft = (id: string, kind: string) =>
  post<{ id: string; revision: string; draft: boolean }>("create_component_draft", { id, kind });

export const updateComponent = (id: string, body: { manifest?: Record<string, unknown>; patch?: Record<string, unknown>[] }) =>
  post<UpdateComponentResult>("update_component", { id, ...body });

export const validateComponent = (id: string) => post<{ id: string; valid: boolean }>("validate_component", { id });

export const publishComponent = (id: string, revision: string) =>
  post<{ id: string; revision: string; draft: boolean; published: boolean }>("publish_component", { id, revision });

export const deleteComponent = (id: string) => post<{ id: string; deleted: boolean }>("delete_component", { id });

// -- Component attachments (spec/09 "Agent orchestrator") ---------------------------------------------------
// Not JSON, and the response isn't an Envelope (an upload either reaches
// the filesystem or it doesn't -- there's no refusal-shaped outcome for
// it), so this doesn't go through get<T>/post<T>.

export async function listComponentAttachments(componentId: string): Promise<AttachmentRow[]> {
  let res: Response;
  try {
    res = await fetch(`/components/${encodeURIComponent(componentId)}/attachments`);
  } catch (e) {
    throw new ApiTransportError(`list attachments: ${(e as Error).message}`);
  }
  if (!res.ok) {
    throw new ApiTransportError(`list attachments: HTTP ${res.status} ${res.statusText}`, res.status);
  }
  const body = (await res.json()) as { files: AttachmentRow[] };
  return body.files;
}

// Same "not an Envelope" reasoning as attachments above -- /agent/models
// is static server config (which Claude models this server will accept),
// not an OcmApi verb with a refusal-shaped outcome.
export async function getAgentModels(): Promise<AgentModelsData> {
  let res: Response;
  try {
    res = await fetch("/agent/models");
  } catch (e) {
    throw new ApiTransportError(`agent/models: ${(e as Error).message}`);
  }
  if (!res.ok) {
    throw new ApiTransportError(`agent/models: HTTP ${res.status} ${res.statusText}`, res.status);
  }
  return (await res.json()) as AgentModelsData;
}

export function attachmentDownloadUrl(componentId: string, filename: string): string {
  return `/components/${encodeURIComponent(componentId)}/attachments/${encodeURIComponent(filename)}`;
}

export async function uploadComponentAttachment(componentId: string, file: File): Promise<AttachmentResult> {
  const form = new FormData();
  form.append("file", file, file.name);

  let res: Response;
  try {
    res = await fetch(`/components/${encodeURIComponent(componentId)}/attachments`, { method: "POST", body: form });
  } catch (e) {
    throw new ApiTransportError(`upload: ${(e as Error).message}`);
  }
  if (!res.ok) {
    throw new ApiTransportError(`upload: HTTP ${res.status} ${res.statusText}`, res.status);
  }
  try {
    return (await res.json()) as AttachmentResult;
  } catch {
    throw new ApiTransportError("upload: response body was not valid JSON");
  }
}

// -- Module attachments -- a module's own uploaded STEP file, a
// non-interactive visual backdrop for the Modules page (never sliced,
// never clicked -- cascadio doesn't expose meaningful per-part structure).
// Byte-for-byte the same shape as the component-attachment functions
// above, just against /modules/{id}/attachments -- same reasoning, not an
// Envelope, doesn't go through get<T>/post<T>.

export async function listModuleAttachments(moduleId: string): Promise<AttachmentRow[]> {
  let res: Response;
  try {
    res = await fetch(`/modules/${encodeURIComponent(moduleId)}/attachments`);
  } catch (e) {
    throw new ApiTransportError(`list attachments: ${(e as Error).message}`);
  }
  if (!res.ok) {
    throw new ApiTransportError(`list attachments: HTTP ${res.status} ${res.statusText}`, res.status);
  }
  const body = (await res.json()) as { files: AttachmentRow[] };
  return body.files;
}

export async function uploadModuleAttachment(moduleId: string, file: File): Promise<AttachmentResult> {
  const form = new FormData();
  form.append("file", file, file.name);

  let res: Response;
  try {
    res = await fetch(`/modules/${encodeURIComponent(moduleId)}/attachments`, { method: "POST", body: form });
  } catch (e) {
    throw new ApiTransportError(`upload: ${(e as Error).message}`);
  }
  if (!res.ok) {
    throw new ApiTransportError(`upload: HTTP ${res.status} ${res.statusText}`, res.status);
  }
  try {
    return (await res.json()) as AttachmentResult;
  } catch {
    throw new ApiTransportError("upload: response body was not valid JSON");
  }
}

export function moduleAttachmentDownloadUrl(moduleId: string, filename: string): string {
  return `/modules/${encodeURIComponent(moduleId)}/attachments/${encodeURIComponent(filename)}`;
}

// -- Agent chat (spec/09 "Agent orchestrator") ---------------------------------------------------
// SSE over a POST body -- native EventSource can't do that, so this hand-
// rolls the same "event: x\ndata: y\n\n" framing spec/09 defines, reading
// the response body as a stream rather than waiting for it to finish.

export interface AgentChatHandlers {
  onText: (delta: string) => void;
  onToolCall: (event: ChatToolCallEvent) => void;
  onError: (envelope: Envelope) => void;
  onDone: () => void;
}

function transportErrorEnvelope(message: string): Envelope {
  return { ok: false, refusals: [{ code: "OCM_UNAVAILABLE", path: "$", message, allowed: null, hint: null }], warnings: [], data: null };
}

function dispatchSseChunk(chunk: string, handlers: AgentChatHandlers): void {
  const lines = chunk.split("\n");
  const eventLine = lines.find((l) => l.startsWith("event: "));
  const dataLine = lines.find((l) => l.startsWith("data: "));
  if (!eventLine || !dataLine) return;
  const event = eventLine.slice("event: ".length);
  const data = JSON.parse(dataLine.slice("data: ".length));

  if (event === "text") handlers.onText(data.delta as string);
  else if (event === "tool_call") handlers.onToolCall(data as ChatToolCallEvent);
  else if (event === "error") handlers.onError(data.envelope as Envelope);
  else if (event === "done") handlers.onDone();
}

export function streamAgentChat(
  body: { component_id: string | null; messages: ChatMessage[]; attachment_filenames?: string[]; model?: string },
  handlers: AgentChatHandlers,
): { abort: () => void } {
  const controller = new AbortController();

  void (async () => {
    let res: Response;
    try {
      res = await fetch("/agent/chat", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      handlers.onError(transportErrorEnvelope(`agent/chat: ${(e as Error).message}`));
      return;
    }
    if (!res.ok || !res.body) {
      handlers.onError(transportErrorEnvelope(`agent/chat: HTTP ${res.status} ${res.statusText}`));
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let sep = buffer.indexOf("\n\n");
        while (sep !== -1) {
          dispatchSseChunk(buffer.slice(0, sep), handlers);
          buffer = buffer.slice(sep + 2);
          sep = buffer.indexOf("\n\n");
        }
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        handlers.onError(transportErrorEnvelope(`agent/chat: stream interrupted (${(e as Error).message})`));
      }
    }
  })();

  return { abort: () => controller.abort() };
}
