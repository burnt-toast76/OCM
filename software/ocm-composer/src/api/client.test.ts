// SPDX-License-Identifier: AGPL-3.0-or-later
// Every ocm-api refusal code, round-tripped through the client unchanged.
// The client has no rule logic and no per-code branching of its own (see
// client.ts's own module docstring) -- these tests exist to pin that
// down: whatever code/message/hint/allowed the server sends is exactly
// what a caller gets back, verbatim, never paraphrased or dropped.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiTransportError, buildScene, listCells, moveInstance, placeInstance, removeInstance } from "./client";
import type { Envelope, Refusal } from "./types";

// Every code envelope.Codes (ocm_api/envelope.py) defines -- kept as a
// flat literal list, not imported from the server, so a change on either
// side that silently drops a code is caught by a failing test, not by
// the two sides just agreeing with themselves.
const ALL_REFUSAL_CODES = [
  "SCHEMA_INVALID",
  "CELL_INVALID",
  "NOT_FOUND",
  "ALREADY_EXISTS",
  "HUMAN_SIGNATURE_REQUIRED",
  "DRAFT_NOT_PUBLISHABLE",
  "UNKNOWN_MODULE",
  "REVISION_MISMATCH",
  "DANGLING_MOUNT",
  "DRAFT_MODULE_REFERENCED",
  "WORKSPACE_OVERHANG",
  "UNKNOWN_OP",
  "UNKNOWN_PARAM",
  "PARAM_OUT_OF_BOUNDS",
  "NO_FASTENING_STEP",
  "POSE_UNREACHABLE",
  "PATH_COLLISION",
  "COLLISION_DETECTED",
  "UNAVAILABLE",
  "INVALID_ARGUMENT",
  "UNKNOWN_COMPONENT",
  "DUPLICATE_REFDES",
  "INVALID_SOURCE",
  "TOOL_SLOT_OCCUPIED",
] as const;

function mockEnvelopeResponse<T>(envelope: Envelope<T>, status = 200): Response {
  return new Response(JSON.stringify(envelope), { status, headers: { "content-type": "application/json" } });
}

function refusalEnvelope(code: string): Envelope<never> {
  return {
    ok: false,
    data: null,
    warnings: [],
    refusals: [
      {
        code,
        path: "modules['pk1'].mount",
        message: `${code.toLowerCase()}: a verbatim engine message an agent would also see`,
        allowed: { example: true },
        hint: `${code.toLowerCase()}: a verbatim engine hint an agent would also see`,
      },
    ],
  };
}

describe("client refusal round-trip", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  for (const code of ALL_REFUSAL_CODES) {
    it(`passes ${code} through place_instance unchanged`, async () => {
      const envelope = refusalEnvelope(code);
      fetchMock.mockResolvedValueOnce(mockEnvelopeResponse(envelope));

      const result = await placeInstance("bracket-asm-01", "pk1", "com.example.pickhead.pk100@1.0.0", {
        pose: { xyz_mm: [2000, 300, 0], rpy_deg: [0, 0, 0] },
      });

      expect(result.ok).toBe(false);
      expect(result.refusals).toHaveLength(1);
      const refusal: Refusal = result.refusals[0];
      expect(refusal.code).toBe(code);
      // Byte-for-byte, not just "contains" -- the whole point is the
      // client never paraphrases the engine's own words.
      expect(refusal.message).toBe(envelope.refusals[0].message);
      expect(refusal.hint).toBe(envelope.refusals[0].hint);
      expect(refusal.allowed).toEqual(envelope.refusals[0].allowed);
      expect(refusal.path).toBe(envelope.refusals[0].path);
    });
  }
});

describe("client happy paths", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("listCells GETs the root-relative path with no body", async () => {
    fetchMock.mockResolvedValueOnce(
      mockEnvelopeResponse({
        ok: true,
        data: [{ cell_id: "bracket-asm-01", id: "com.accelsolutions.cell.bracket-asm-01", name: "Bracket Assembly Cell 01" }],
        warnings: [],
        refusals: [],
      }),
    );

    const result = await listCells();

    expect(fetchMock).toHaveBeenCalledWith("/list_cells");
    expect(result.ok).toBe(true);
    expect(result.data?.[0].cell_id).toBe("bracket-asm-01");
  });

  it("buildScene POSTs the cell id and returns the primitives payload untouched", async () => {
    const scenePayload = {
      cell_id: "bracket-asm-01",
      n_links: 18,
      n_joints: 17,
      base: "__base____origin",
      instances: ["cam1", "feed1", "nest1", "robot1", "sd1"],
      colors: { base: "#e6194b", robot1: "#911eb4" },
      primitives: [{ link: "feed1__origin", instance: "feed1", instance_kind: "feeder", kind: "box", dims: { x: 0.4, y: 0.3, z: 0.2 }, position: [0.18, 0.64, 0.1], quaternion: [0, 0, 0, 1], placeholder: false }],
      markers: [],
    };
    fetchMock.mockResolvedValueOnce(mockEnvelopeResponse({ ok: true, data: scenePayload, warnings: [], refusals: [] }));

    const result = await buildScene("bracket-asm-01");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/build_scene");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({ cell: "bracket-asm-01" });
    expect(result.data?.primitives).toEqual(scenePayload.primitives);
  });

  it("moveInstance and removeInstance send the expected bodies", async () => {
    const okEnvelope = { ok: true, data: { cell_id: "c", instances: [], base: "b", workspace_bounds: null }, warnings: [], refusals: [] };
    fetchMock.mockImplementation(async () => mockEnvelopeResponse(okEnvelope));

    await moveInstance("bracket-asm-01", "pk1", { pose: { xyz_mm: [500, 300, 0], rpy_deg: [0, 0, 90] } });
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      cell: "bracket-asm-01",
      instance: "pk1",
      mount: { pose: { xyz_mm: [500, 300, 0], rpy_deg: [0, 0, 90] } },
    });

    await removeInstance("bracket-asm-01", "pk1");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ cell: "bracket-asm-01", instance: "pk1" });
  });

  it("a warning on an otherwise-ok response survives untouched", async () => {
    fetchMock.mockResolvedValueOnce(
      mockEnvelopeResponse({
        ok: true,
        data: { cell_id: "bracket-asm-01", instances: [], base: "b", workspace_bounds: null },
        warnings: ["removing sd1 orphans 3 plan steps (drive_screw ×3); the plan will no longer resolve."],
        refusals: [],
      }),
    );

    const result = await removeInstance("bracket-asm-01", "sd1");

    expect(result.ok).toBe(true);
    expect(result.warnings).toEqual(["removing sd1 orphans 3 plan steps (drive_screw ×3); the plan will no longer resolve."]);
  });
});

describe("client transport failures", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("throws ApiTransportError on a non-2xx status instead of returning a fake envelope", async () => {
    fetchMock.mockResolvedValueOnce(new Response("Internal Server Error", { status: 500, statusText: "Internal Server Error" }));

    await expect(listCells()).rejects.toBeInstanceOf(ApiTransportError);
  });

  it("throws ApiTransportError when the network request itself fails", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(listCells()).rejects.toBeInstanceOf(ApiTransportError);
  });

  it("throws ApiTransportError on a non-JSON 200 body", async () => {
    fetchMock.mockResolvedValueOnce(new Response("<html>not json</html>", { status: 200 }));

    await expect(listCells()).rejects.toBeInstanceOf(ApiTransportError);
  });
});
