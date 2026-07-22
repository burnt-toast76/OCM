// SPDX-License-Identifier: AGPL-3.0-or-later
// setAtPath is the one thing saveField trusts to build the next document
// from a field edit -- these tests pin down that an existing ARRAY field
// (electrical.supplies, comms.signals, ...) survives being walked through
// as an intermediate path segment (committing one row's OWN nested field)
// as an array, not silently downgraded to a plain object keyed by
// stringified index. Confirmed in the wild: a real draft's `supplies`
// ended up as `{"0": {rail: "24VDC"}}`, which then crashed SchemaField's
// own `rows.map` (it assumes an array, per the schema).

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, updateComponent: vi.fn(), describeComponent: vi.fn(), validateComponent: vi.fn() };
});

import * as api from "../api/client";
import { useComponentsStore } from "./componentsStore";
import type { ComponentDoc, DescribeComponentData } from "../api/types";

function detailFor(component: ComponentDoc): DescribeComponentData {
  return { id: component.id, revision: component.revision, draft: true, component };
}

beforeEach(() => {
  vi.mocked(api.validateComponent).mockResolvedValue({ ok: true, refusals: [], warnings: [], data: { id: "c1", valid: true } });
  useComponentsStore.setState({
    selectedComponentId: "com.example.pressure-sensor",
    detail: detailFor({
      ocm_version: "1.1",
      id: "com.example.pressure-sensor",
      revision: "0.1.0",
      kind: "sensor",
      electrical: { supplies: [{}] }, // one empty row, as if "+ Add" had just been clicked
    }),
    error: null,
  });
});

describe("saveField / setAtPath", () => {
  it("keeps an existing array an array when committing a nested field inside one of its rows", async () => {
    vi.mocked(api.updateComponent).mockResolvedValue({
      ok: true,
      refusals: [],
      warnings: [],
      data: { id: "com.example.pressure-sensor", revision: "0.1.0", draft: true, path: "x" },
    });
    vi.mocked(api.describeComponent).mockResolvedValue({
      ok: true,
      refusals: [],
      warnings: [],
      data: detailFor({
        ocm_version: "1.1",
        id: "com.example.pressure-sensor",
        revision: "0.1.0",
        kind: "sensor",
        electrical: { supplies: [{ rail: "24VDC" }] },
      }),
    });

    await useComponentsStore.getState().saveField(["electrical", "supplies", "0", "rail"], "24VDC");

    expect(api.updateComponent).toHaveBeenCalledTimes(1);
    const [, body] = vi.mocked(api.updateComponent).mock.calls[0];
    const supplies = (body.manifest as ComponentDoc).electrical as { supplies: unknown };

    // The bug produced { supplies: { "0": { rail: "24VDC" } } } -- an
    // object keyed by stringified index, not a real array.
    expect(Array.isArray(supplies.supplies)).toBe(true);
    expect(supplies.supplies).toEqual([{ rail: "24VDC" }]);
  });
});
