// SPDX-License-Identifier: AGPL-3.0-or-later
// moveExistingInstance is the ONLY thing DraggableInstance calls, and it
// calls it exactly once per drag (see DraggableInstance.tsx's own
// docstring) -- these tests pin that contract down at the store level:
// one call in, one API call out, a refusal reverts rather than adopting
// the server's (unconditionally written) attempted pose, and a
// superseded in-flight call never clobbers a newer one's result.

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, moveInstance: vi.fn(), buildScene: vi.fn(), describeCell: vi.fn() };
});

import * as api from "../api/client";
import { useComposerStore } from "./store";
import type { Envelope, CompositionResult, RawCellModule } from "../api/types";

function okEnvelope(): Envelope<CompositionResult> {
  return { ok: true, refusals: [], warnings: [], data: { cell_id: "c1", instances: ["feed1"], base: "b", workspace_bounds: null } };
}

function refusalEnvelope(): Envelope<CompositionResult> {
  return {
    ok: false,
    warnings: [],
    data: null,
    refusals: [
      {
        code: "WORKSPACE_OVERHANG",
        path: "modules.feed1.mount",
        message: "module feed1: extends beyond the workspace footprint (X:[-50,1250] Y:[-50,950] mm): +X by 100.0 mm",
        allowed: { footprint: "X:[-50,1250] Y:[-50,950] mm" },
        hint: "Move feed1 inside the base footprint.",
      },
    ],
  };
}

const rawCellModules: RawCellModule[] = [
  { instance: "feed1", module: "com.accelsolutions.screwfeeder.sf20@1.0.0", mount: { pose: { xyz_mm: [180, 640, 0], rpy_deg: [0, 0, 0] } } },
];

beforeEach(() => {
  vi.mocked(api.buildScene).mockResolvedValue({ ok: true, refusals: [], warnings: [], data: null });
  vi.mocked(api.describeCell).mockResolvedValue({ ok: true, refusals: [], warnings: [], data: null });
  useComposerStore.setState({
    cellId: "c1",
    scene: null,
    rawCellModules,
    refusals: [],
    toasts: [],
    ghost: null,
    toolSlotIncumbent: null,
  });
  vi.mocked(api.moveInstance).mockReset();
  vi.mocked(api.buildScene).mockClear();
  vi.mocked(api.describeCell).mockClear();
});

describe("moveExistingInstance", () => {
  it("issues exactly one move_instance call for one drag-to-drop commit", async () => {
    vi.mocked(api.moveInstance).mockResolvedValue(okEnvelope());

    await useComposerStore.getState().moveExistingInstance("feed1", { pose: { xyz_mm: [555, 640, 0], rpy_deg: [0, 0, 0] } });

    expect(api.moveInstance).toHaveBeenCalledTimes(1);
    expect(api.moveInstance).toHaveBeenCalledWith("c1", "feed1", { pose: { xyz_mm: [555, 640, 0], rpy_deg: [0, 0, 0] } });
  });

  it("on success, clears refusals/ghost and reconciles via the scene refresh", async () => {
    vi.mocked(api.moveInstance).mockResolvedValue(okEnvelope());

    await useComposerStore.getState().moveExistingInstance("feed1", { pose: { xyz_mm: [555, 640, 0], rpy_deg: [0, 0, 0] } });

    expect(useComposerStore.getState().refusals).toEqual([]);
    expect(useComposerStore.getState().ghost).toBeNull();
    expect(api.buildScene).toHaveBeenCalledTimes(1);
  });

  it("on a refusal, reverts (no scene refresh) and shows a ghost + verbatim toast instead of adopting the attempted pose", async () => {
    vi.mocked(api.moveInstance).mockResolvedValue(refusalEnvelope());

    await useComposerStore.getState().moveExistingInstance("feed1", { pose: { xyz_mm: [5000, 640, 0], rpy_deg: [0, 0, 0] } });

    // spec/09: the server persisted the refused pose to disk anyway, but
    // the composer must NOT re-fetch and render it -- that's what lets
    // DraggableInstance's local offset reset snap back to the last
    // confirmed pose instead of jumping to the invalid one.
    expect(api.buildScene).not.toHaveBeenCalled();
    expect(api.describeCell).not.toHaveBeenCalled();

    const state = useComposerStore.getState();
    expect(state.refusals).toHaveLength(1);
    expect(state.refusals[0].code).toBe("WORKSPACE_OVERHANG");
    expect(state.ghost).toEqual({
      moduleId: "com.accelsolutions.screwfeeder.sf20@1.0.0",
      position: [5, 0.64, 0],
      rpyDeg: [0, 0, 0],
    });
    expect(state.toasts).toHaveLength(1);
    // Verbatim -- never paraphrased.
    expect(state.toasts[0].message).toBe(refusalEnvelope().refusals[0].message);
    expect(state.toasts[0].hint).toBe(refusalEnvelope().refusals[0].hint);
  });

  it("drops a stale response when a newer call for the same instance has already started", async () => {
    let resolveFirst!: (env: Envelope<CompositionResult>) => void;
    const firstCall = new Promise<Envelope<CompositionResult>>((resolve) => {
      resolveFirst = resolve;
    });
    (vi.mocked(api.moveInstance) as Mock).mockReturnValueOnce(firstCall).mockResolvedValueOnce(okEnvelope());

    const first = useComposerStore.getState().moveExistingInstance("feed1", { pose: { xyz_mm: [5000, 640, 0], rpy_deg: [0, 0, 0] } });
    const second = useComposerStore.getState().moveExistingInstance("feed1", { pose: { xyz_mm: [555, 640, 0], rpy_deg: [0, 0, 0] } });
    await second; // the newer call resolves and applies its (ok) result first

    expect(useComposerStore.getState().refusals).toEqual([]);

    // The older, now-stale call resolves with a refusal AFTER the newer
    // one already succeeded -- it must be dropped, not clobber the
    // already-applied ok result.
    resolveFirst(refusalEnvelope());
    await first;

    expect(useComposerStore.getState().refusals).toEqual([]);
    expect(useComposerStore.getState().toasts).toHaveLength(0);
  });
});
