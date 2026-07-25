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
  return {
    ...actual,
    updateModule: vi.fn(),
    describeModule: vi.fn(),
    validateModule: vi.fn(),
    describeComponent: vi.fn(),
  };
});

import * as api from "../api/client";
import { useModulesStore } from "./modulesStore";
import type { ComponentDoc, DescribeModuleData, ModuleManifest } from "../api/types";

function detailFor(
  components: DescribeModuleData["manifest"]["components"],
  extra: Partial<ModuleManifest> = {},
): DescribeModuleData {
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
      ...extra,
    },
  };
}

beforeEach(() => {
  vi.mocked(api.updateModule).mockReset();
  vi.mocked(api.describeModule).mockReset();
  vi.mocked(api.validateModule).mockReset();
  vi.mocked(api.describeComponent).mockReset();
  vi.mocked(api.validateModule).mockResolvedValue({ ok: true, refusals: [], warnings: [], data: null });
  useModulesStore.setState({
    selectedModuleId: "com.example.pickhead.pk100",
    detail: detailFor([]),
    componentDocs: {},
    checklist: [],
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

describe("setElectricalNets", () => {
  const nets = [{ id: "N1", endpoints: [{ port: "PWR_IN" }, { refdes: "PS1", ref: "electrical", pin: "1" }] }];

  it("adds the whole /nets object (not a nested /nets/electrical patch) when the module has no nets yet", async () => {
    vi.mocked(api.updateModule).mockResolvedValue({ ok: true, refusals: [], warnings: [], data: { id: "x", revision: "0.1.0", draft: true, path: "x" } });
    vi.mocked(api.describeModule).mockResolvedValue({ ok: true, refusals: [], warnings: [], data: detailFor([], { nets: { electrical: nets } }) });

    await useModulesStore.getState().setElectricalNets(nets);

    expect(api.updateModule).toHaveBeenCalledWith("com.example.pickhead.pk100", {
      patch: [{ op: "add", path: "/nets", value: { electrical: nets } }],
    });
    expect(useModulesStore.getState().detail?.manifest.nets?.electrical).toEqual(nets);
  });

  it("replaces /nets as a whole object when nets already exist, preserving an existing pneumatic array untouched", async () => {
    const pneumaticNets = [{ id: "P1", endpoints: [{ port: "SUPPLY" }] }];
    useModulesStore.setState({ detail: detailFor([], { nets: { pneumatic: pneumaticNets } }) });
    vi.mocked(api.updateModule).mockResolvedValue({ ok: true, refusals: [], warnings: [], data: { id: "x", revision: "0.1.0", draft: true, path: "x" } });
    vi.mocked(api.describeModule).mockResolvedValue({ ok: true, refusals: [], warnings: [], data: detailFor([]) });

    await useModulesStore.getState().setElectricalNets(nets);

    expect(api.updateModule).toHaveBeenCalledWith("com.example.pickhead.pk100", {
      patch: [{ op: "replace", path: "/nets", value: { pneumatic: pneumaticNets, electrical: nets } }],
    });
  });

  it("re-validates after a successful write", async () => {
    vi.mocked(api.updateModule).mockResolvedValue({ ok: true, refusals: [], warnings: [], data: { id: "x", revision: "0.1.0", draft: true, path: "x" } });
    vi.mocked(api.describeModule).mockResolvedValue({ ok: true, refusals: [], warnings: [], data: detailFor([]) });

    await useModulesStore.getState().setElectricalNets(nets);

    expect(api.validateModule).toHaveBeenCalledWith("com.example.pickhead.pk100");
  });

  it("on refusal, leaves detail unchanged and surfaces the refusal message verbatim, never reinterpreted", async () => {
    const before = useModulesStore.getState().detail;
    vi.mocked(api.updateModule).mockResolvedValue({
      ok: false,
      refusals: [{ code: "NET_TOO_FEW_ENDPOINTS", path: "modules['x'].nets.electrical['N1']", message: "net 'N1' has fewer than two endpoints", allowed: null, hint: null }],
      warnings: [],
      data: null,
    });

    await useModulesStore.getState().setElectricalNets(nets);

    expect(useModulesStore.getState().detail).toBe(before);
    expect(useModulesStore.getState().placementError).toBe("net 'N1' has fewer than two endpoints");
    expect(api.describeModule).not.toHaveBeenCalled();
  });
});

describe("setLinks", () => {
  const links = [{ id: "L1", a: { port: "ETH" }, b: { refdes: "IO1", ref: "communication", pin: "1" }, protocol: "ethercat" }];

  it("adds /links (not a replace) when the module has no links yet", async () => {
    vi.mocked(api.updateModule).mockResolvedValue({ ok: true, refusals: [], warnings: [], data: { id: "x", revision: "0.1.0", draft: true, path: "x" } });
    vi.mocked(api.describeModule).mockResolvedValue({ ok: true, refusals: [], warnings: [], data: detailFor([], { links }) });

    await useModulesStore.getState().setLinks(links);

    expect(api.updateModule).toHaveBeenCalledWith("com.example.pickhead.pk100", {
      patch: [{ op: "add", path: "/links", value: links }],
    });
  });

  it("replaces /links wholesale when links already exist", async () => {
    useModulesStore.setState({ detail: detailFor([], { links: [{ id: "L0", a: { port: "A" }, b: { port: "B" } }] }) });
    vi.mocked(api.updateModule).mockResolvedValue({ ok: true, refusals: [], warnings: [], data: { id: "x", revision: "0.1.0", draft: true, path: "x" } });
    vi.mocked(api.describeModule).mockResolvedValue({ ok: true, refusals: [], warnings: [], data: detailFor([]) });

    await useModulesStore.getState().setLinks(links);

    expect(api.updateModule).toHaveBeenCalledWith("com.example.pickhead.pk100", {
      patch: [{ op: "replace", path: "/links", value: links }],
    });
  });

  it("on refusal, leaves detail unchanged and surfaces the refusal message verbatim", async () => {
    const before = useModulesStore.getState().detail;
    vi.mocked(api.updateModule).mockResolvedValue({
      ok: false,
      refusals: [{ code: "LINK_PROTOCOL_MISMATCH", path: "modules['x'].links['L1']", message: "link 'L1' has mismatched protocols", allowed: null, hint: null }],
      warnings: [],
      data: null,
    });

    await useModulesStore.getState().setLinks(links);

    expect(useModulesStore.getState().detail).toBe(before);
    expect(useModulesStore.getState().placementError).toBe("link 'L1' has mismatched protocols");
    expect(api.describeModule).not.toHaveBeenCalled();
  });
});

describe("refreshChecklist", () => {
  it("clears the checklist when validate_module reports ok", async () => {
    useModulesStore.setState({ checklist: [{ code: "PORT_UNCONNECTED", path: "x", message: "old refusal", allowed: null, hint: null }] });
    vi.mocked(api.validateModule).mockResolvedValue({ ok: true, refusals: [], warnings: [], data: null });

    await useModulesStore.getState().refreshChecklist();

    expect(useModulesStore.getState().checklist).toEqual([]);
  });

  it("stores validate_module's refusals verbatim, never reinterpreted", async () => {
    const refusals = [{ code: "PORT_UNCONNECTED", path: "modules['x'].ports['PWR_IN']", message: "port 'PWR_IN' is unconnected", allowed: null, hint: null }];
    vi.mocked(api.validateModule).mockResolvedValue({ ok: false, refusals, warnings: [], data: null });

    await useModulesStore.getState().refreshChecklist();

    expect(useModulesStore.getState().checklist).toEqual(refusals);
  });
});

describe("refreshComponentDocs", () => {
  function componentDoc(id: string): ComponentDoc {
    return { id, revision: "1.0.0", electrical: { connectors: [] } };
  }

  it("fetches a doc for each placed component's id, keyed by id, not refdes", async () => {
    useModulesStore.setState({
      detail: detailFor([
        { refdes: "VG1", ref: "com.smc.ejector.zk2-agh@1.0.0" },
        { refdes: "PS1", ref: "com.example.ps.ps1@2.0.0" },
      ]),
    });
    vi.mocked(api.describeComponent).mockImplementation(async (id: string) => ({
      ok: true,
      refusals: [],
      warnings: [],
      data: { id, revision: "1.0.0", draft: false, component: componentDoc(id) },
    }));

    await useModulesStore.getState().refreshComponentDocs();

    const docs = useModulesStore.getState().componentDocs;
    expect(Object.keys(docs).sort()).toEqual(["com.example.ps.ps1", "com.smc.ejector.zk2-agh"]);
    expect(api.describeComponent).toHaveBeenCalledWith("com.smc.ejector.zk2-agh");
    expect(api.describeComponent).toHaveBeenCalledWith("com.example.ps.ps1");
  });

  it("does not re-fetch a component doc that's already cached", async () => {
    useModulesStore.setState({
      detail: detailFor([{ refdes: "VG1", ref: "com.smc.ejector.zk2-agh@1.0.0" }]),
      componentDocs: { "com.smc.ejector.zk2-agh": componentDoc("com.smc.ejector.zk2-agh") },
    });

    await useModulesStore.getState().refreshComponentDocs();

    expect(api.describeComponent).not.toHaveBeenCalled();
  });

  it("two instances of the same component id only trigger one fetch", async () => {
    useModulesStore.setState({
      detail: detailFor([
        { refdes: "VG1", ref: "com.smc.ejector.zk2-agh@1.0.0" },
        { refdes: "VG2", ref: "com.smc.ejector.zk2-agh@1.0.0" },
      ]),
    });
    vi.mocked(api.describeComponent).mockResolvedValue({
      ok: true,
      refusals: [],
      warnings: [],
      data: { id: "com.smc.ejector.zk2-agh", revision: "1.0.0", draft: false, component: componentDoc("com.smc.ejector.zk2-agh") },
    });

    await useModulesStore.getState().refreshComponentDocs();

    expect(api.describeComponent).toHaveBeenCalledTimes(1);
  });
});
