// SPDX-License-Identifier: AGPL-3.0-or-later
// Component-instance placement goes through update_module's own generic
// patch write -- never place_instance/move_instance (cell-specific verbs
// with cell-specific refusal codes that don't apply here). These tests
// pin down the exact patch shape built for each action, and that a
// refusal leaves `detail` untouched and surfaces the message verbatim
// (never reinterpreted), mirroring componentsStore.test.ts's own
// vi.mock("../api/client", ...) convention.

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, updateModule: vi.fn(), describeModule: vi.fn() };
});

import * as api from "../api/client";
import { useModulesStore } from "./modulesStore";
import type { DescribeModuleData } from "../api/types";

function detailFor(components: DescribeModuleData["manifest"]["components"]): DescribeModuleData {
  return {
    id: "com.example.pickhead.pk100",
    revision: "0.1.0",
    draft: true,
    manifest: {
      id: "com.example.pickhead.pk100",
      revision: "0.1.0",
      kind: "end_effector",
      mechanical: { mount: { interface: "custom" }, frames: {} },
      components,
    },
  };
}

beforeEach(() => {
  vi.mocked(api.updateModule).mockReset();
  vi.mocked(api.describeModule).mockReset();
  useModulesStore.setState({
    selectedModuleId: "com.example.pickhead.pk100",
    detail: detailFor([]),
    placementError: null,
    error: null,
  });
});

describe("placeComponentInstance", () => {
  it("appends a new components[] entry (as an 'add' when the list was empty) via update_module, then refreshes detail", async () => {
    vi.mocked(api.updateModule).mockResolvedValue({ ok: true, refusals: [], warnings: [], data: { id: "x", revision: "0.1.0", draft: true, path: "x" } });
    vi.mocked(api.describeModule).mockResolvedValue({
      ok: true,
      refusals: [],
      warnings: [],
      data: detailFor([{ refdes: "VG1", ref: "com.smc.ejector.zk2-agh@1.0.0", pose: { xyz_mm: [10, 20, 0], rpy_deg: [0, 0, 0] } }]),
    });

    await useModulesStore.getState().placeComponentInstance("VG1", "com.smc.ejector.zk2-agh@1.0.0", { xyz_mm: [10, 20, 0], rpy_deg: [0, 0, 0] });

    expect(api.updateModule).toHaveBeenCalledWith("com.example.pickhead.pk100", {
      patch: [{ op: "add", path: "/components", value: [{ refdes: "VG1", ref: "com.smc.ejector.zk2-agh@1.0.0", pose: { xyz_mm: [10, 20, 0], rpy_deg: [0, 0, 0] } }] }],
    });
    expect(useModulesStore.getState().detail?.manifest.components).toHaveLength(1);
    expect(useModulesStore.getState().placementError).toBeNull();
  });

  it("replaces the whole components[] array (not 'add') when instances already exist, appending the new one", async () => {
    useModulesStore.setState({ detail: detailFor([{ refdes: "IO1", ref: "com.example.io.io1@1.0.0" }]) });
    vi.mocked(api.updateModule).mockResolvedValue({ ok: true, refusals: [], warnings: [], data: { id: "x", revision: "0.1.0", draft: true, path: "x" } });
    vi.mocked(api.describeModule).mockResolvedValue({ ok: true, refusals: [], warnings: [], data: detailFor([]) });

    await useModulesStore.getState().placeComponentInstance("VG1", "com.smc.ejector.zk2-agh@1.0.0", { xyz_mm: [0, 0, 0], rpy_deg: [0, 0, 0] });

    const [, body] = vi.mocked(api.updateModule).mock.calls[0];
    expect(body.patch).toEqual([
      {
        op: "replace",
        path: "/components",
        value: [{ refdes: "IO1", ref: "com.example.io.io1@1.0.0" }, { refdes: "VG1", ref: "com.smc.ejector.zk2-agh@1.0.0", pose: { xyz_mm: [0, 0, 0], rpy_deg: [0, 0, 0] } }],
      },
    ]);
  });

  it("on refusal, leaves detail unchanged and surfaces the refusal message verbatim", async () => {
    const before = useModulesStore.getState().detail;
    vi.mocked(api.updateModule).mockResolvedValue({
      ok: false,
      refusals: [{ code: "SCHEMA_INVALID", path: "components/0/pose", message: "'xyz_mm' is a required property", allowed: null, hint: null }],
      warnings: [],
      data: null,
    });

    await useModulesStore.getState().placeComponentInstance("VG1", "com.smc.ejector.zk2-agh@1.0.0", { xyz_mm: [0, 0, 0], rpy_deg: [0, 0, 0] });

    expect(useModulesStore.getState().detail).toBe(before);
    expect(useModulesStore.getState().placementError).toBe("'xyz_mm' is a required property");
    expect(api.describeModule).not.toHaveBeenCalled();
  });
});

describe("moveComponentInstance", () => {
  it("patches /components/<index>/pose for the matching refdes", async () => {
    useModulesStore.setState({
      detail: detailFor([
        { refdes: "IO1", ref: "com.example.io.io1@1.0.0" },
        { refdes: "VG1", ref: "com.smc.ejector.zk2-agh@1.0.0", pose: { xyz_mm: [0, 0, 0], rpy_deg: [0, 0, 0] } },
      ]),
    });
    vi.mocked(api.updateModule).mockResolvedValue({ ok: true, refusals: [], warnings: [], data: { id: "x", revision: "0.1.0", draft: true, path: "x" } });
    vi.mocked(api.describeModule).mockResolvedValue({ ok: true, refusals: [], warnings: [], data: detailFor([]) });

    await useModulesStore.getState().moveComponentInstance("VG1", { xyz_mm: [50, 60, 0], rpy_deg: [0, 0, 180] });

    expect(api.updateModule).toHaveBeenCalledWith("com.example.pickhead.pk100", {
      patch: [{ op: "add", path: "/components/1/pose", value: { xyz_mm: [50, 60, 0], rpy_deg: [0, 0, 180] } }],
    });
  });

  it("does nothing if the refdes isn't found (e.g. removed by another tab)", async () => {
    await useModulesStore.getState().moveComponentInstance("NOPE", { xyz_mm: [0, 0, 0], rpy_deg: [0, 0, 0] });
    expect(api.updateModule).not.toHaveBeenCalled();
  });
});
