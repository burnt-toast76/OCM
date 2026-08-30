// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { applyWireClick, endpointKey, endpointsEqual, moduleRefusalFieldKey, nextNetId } from "./wiring";
import type { ModuleEndpoint, ModuleNetRow, Refusal } from "../api/types";

function refusal(overrides: Partial<Refusal>): Refusal {
  return { code: "OCM_SCHEMA_INVALID", path: "$", message: "", allowed: null, hint: null, ...overrides };
}

const port = (id: string): ModuleEndpoint => ({ port: id });
const pin = (refdes: string, ref: string, p: string): ModuleEndpoint => ({ refdes, ref, pin: p });

describe("endpointKey / endpointsEqual", () => {
  it("distinguishes a port endpoint from a component-pin endpoint with the same-looking id", () => {
    expect(endpointKey(port("X"))).not.toBe(endpointKey({ refdes: "X", ref: "", pin: "" }));
  });

  it("treats two endpoints naming the same refdes/ref/pin as equal", () => {
    expect(endpointsEqual(pin("PS1", "electrical", "1"), pin("PS1", "electrical", "1"))).toBe(true);
  });

  it("treats endpoints differing only by pin as unequal", () => {
    expect(endpointsEqual(pin("PS1", "electrical", "1"), pin("PS1", "electrical", "2"))).toBe(false);
  });
});

describe("nextNetId", () => {
  it("starts at N1 when there are no nets yet", () => {
    expect(nextNetId([])).toBe("N1");
  });

  it("skips ids that are already taken, including non-sequential ones", () => {
    const nets: ModuleNetRow[] = [
      { id: "N1", endpoints: [] },
      { id: "N3", endpoints: [] },
    ];
    expect(nextNetId(nets)).toBe("N2");
  });
});

describe("applyWireClick", () => {
  it("creates a brand new net when neither endpoint is wired yet", () => {
    const a = pin("PS1", "electrical", "1");
    const b = port("PWR_IN");
    const next = applyWireClick([], a, b);
    expect(next).toEqual([{ id: "N1", endpoints: [a, b] }]);
  });

  it("joins the unwired endpoint onto the other's existing net", () => {
    const a = pin("PS1", "electrical", "1");
    const b = pin("PS1", "electrical", "2");
    const c = port("PWR_IN");
    const nets: ModuleNetRow[] = [{ id: "N1", endpoints: [a, b] }];
    const next = applyWireClick(nets, a, c);
    expect(next).toEqual([{ id: "N1", endpoints: [a, b, c] }]);
  });

  it("is a no-op when both endpoints are already on the same net", () => {
    const a = pin("PS1", "electrical", "1");
    const b = port("PWR_IN");
    const nets: ModuleNetRow[] = [{ id: "N1", endpoints: [a, b] }];
    expect(applyWireClick(nets, a, b)).toEqual(nets);
  });

  it("merges two different nets into the earlier one when both endpoints are already wired", () => {
    const a = pin("PS1", "electrical", "1");
    const b = pin("VG1", "electrical", "1");
    const c = port("PWR_IN");
    const d = port("PWR_OUT");
    const nets: ModuleNetRow[] = [
      { id: "N1", endpoints: [a, c] },
      { id: "N2", endpoints: [b, d] },
    ];
    const next = applyWireClick(nets, a, b);
    expect(next).toEqual([{ id: "N1", endpoints: [a, c, b, d] }]);
  });

  it("merges into the earlier net regardless of click order", () => {
    const a = pin("PS1", "electrical", "1");
    const b = pin("VG1", "electrical", "1");
    const nets: ModuleNetRow[] = [
      { id: "N1", endpoints: [a] },
      { id: "N2", endpoints: [b] },
    ];
    const next = applyWireClick(nets, b, a);
    expect(next).toEqual([{ id: "N1", endpoints: [a, b] }]);
  });

  it("preserves an untouched third net when merging the other two", () => {
    const a = pin("PS1", "electrical", "1");
    const b = pin("VG1", "electrical", "1");
    const untouched: ModuleNetRow = { id: "N3", endpoints: [port("SPARE")] };
    const nets: ModuleNetRow[] = [{ id: "N1", endpoints: [a] }, { id: "N2", endpoints: [b] }, untouched];
    const next = applyWireClick(nets, a, b);
    expect(next).toContainEqual(untouched);
    expect(next).toHaveLength(2);
  });
});

describe("moduleRefusalFieldKey", () => {
  it("extracts refdes/connector/pin from a component-pin message", () => {
    const r = refusal({
      code: "OCM_PIN_ON_MULTIPLE_NETS",
      path: "modules['dp8'].nets",
      message: "pin '1' of connector 'electrical' on refdes 'PS1' is on multiple nets",
    });
    expect(moduleRefusalFieldKey(r)).toBe("pin:PS1:electrical:1");
  });

  it("extracts refdes/connector/pin from an unresolved-endpoint message", () => {
    const r = refusal({
      code: "OCM_UNRESOLVED_ENDPOINT",
      path: "modules['dp8']",
      message: "net 'N1' references pin '9' not on connector 'electrical' of refdes 'PS1'",
    });
    expect(moduleRefusalFieldKey(r)).toBe("pin:PS1:electrical:9");
  });

  it("extracts a port id from a port-pin message", () => {
    const r = refusal({
      code: "OCM_PIN_ON_MULTIPLE_NETS",
      path: "modules['dp8'].nets",
      message: "pin '1' of port 'PWR_IN' is on multiple nets",
    });
    expect(moduleRefusalFieldKey(r)).toBe("port:PWR_IN");
  });

  it("falls back to the net path when the message names nothing", () => {
    const r = refusal({
      code: "OCM_NET_TOO_FEW_ENDPOINTS",
      path: "modules['dp8'].nets.electrical['N1']",
      message: "net 'N1' has fewer than two endpoints",
    });
    expect(moduleRefusalFieldKey(r)).toBe("net:N1");
  });

  it("falls back to the component path for OCM_COMPONENT_HAS_NO_CONNECTORS", () => {
    const r = refusal({
      code: "OCM_COMPONENT_HAS_NO_CONNECTORS",
      path: "modules['dp8'].components['PS1']",
      message: "refdes 'PS1' has no connectors",
    });
    expect(moduleRefusalFieldKey(r)).toBe("component:PS1");
  });

  it("falls back to the port path for OCM_PORT_UNCONNECTED", () => {
    const r = refusal({
      code: "OCM_PORT_UNCONNECTED",
      path: "modules['dp8'].ports['PWR_IN']",
      message: "port 'PWR_IN' is unconnected",
    });
    expect(moduleRefusalFieldKey(r)).toBe("port:PWR_IN");
  });

  it("falls back to the link path for OCM_LINK_PROTOCOL_MISMATCH", () => {
    const r = refusal({
      code: "OCM_LINK_PROTOCOL_MISMATCH",
      path: "modules['dp8'].links['L1']",
      message: "link 'L1' has mismatched protocols",
    });
    expect(moduleRefusalFieldKey(r)).toBe("link:L1");
  });

  it("returns null for a whole-list refusal like OCM_ETHERCAT_CHAIN_BROKEN", () => {
    const r = refusal({
      code: "OCM_ETHERCAT_CHAIN_BROKEN",
      path: "modules['dp8'].links",
      message: "EtherCAT chain is broken",
    });
    expect(moduleRefusalFieldKey(r)).toBeNull();
  });
});
