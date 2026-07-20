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
  CellSummary,
  CompositionResult,
  DescribeCellData,
  DescribeModuleData,
  Envelope,
  ModuleSummary,
  Mount,
  ScenePayload,
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

export const describeCell = (id: string) => get<DescribeCellData>("describe_cell", { id });

// -- Checking & generation ---------------------------------------------------

export const buildScene = (cell: string) => post<ScenePayload>("build_scene", { cell });

// -- Cell composition ---------------------------------------------------

export const placeInstance = (cell: string, instance: string, module: string, mount: Mount) =>
  post<CompositionResult>("place_instance", { cell, instance, module, mount });

export const moveInstance = (cell: string, instance: string, mount: Mount) =>
  post<CompositionResult>("move_instance", { cell, instance, mount });

export const removeInstance = (cell: string, instance: string) => post<CompositionResult>("remove_instance", { cell, instance });
