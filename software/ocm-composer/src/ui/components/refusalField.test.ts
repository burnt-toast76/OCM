// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from "vitest";
import { groupRefusalsByField, refusalFieldKey } from "./refusalField";
import type { Refusal } from "../../api/types";

function refusal(overrides: Partial<Refusal>): Refusal {
  return { code: "SCHEMA_INVALID", path: "$", message: "", allowed: null, hint: null, ...overrides };
}

describe("refusalFieldKey", () => {
  it("takes the first segment of a real path", () => {
    expect(refusalFieldKey(refusal({ path: "electrical.supplies[0].current_nominal_a" }))).toBe("electrical");
  });

  it("takes the first segment even for a bracket-first path", () => {
    expect(refusalFieldKey(refusal({ path: "hazards[0]" }))).toBe("hazards");
  });

  it("extracts the field name from a missing-required-property message when path is '$'", () => {
    // jsonschema reports a missing required property against the PARENT
    // object (path "$"), not a path into the absent child -- see
    // ocm-api's own tests/test_components.py for the server-side version
    // of this same caveat.
    expect(refusalFieldKey(refusal({ path: "$", message: "'vendor' is a required property" }))).toBe("vendor");
    expect(refusalFieldKey(refusal({ path: "$", message: "'source' is a required property" }))).toBe("source");
  });

  it("returns null when neither the path nor the message name a field", () => {
    expect(refusalFieldKey(refusal({ path: "$", message: "something else entirely" }))).toBeNull();
  });
});

describe("groupRefusalsByField", () => {
  it("groups refusals by their mapped field key", () => {
    const refusals = [
      refusal({ path: "$", message: "'vendor' is a required property" }),
      refusal({ path: "$", message: "'source' is a required property" }),
      refusal({ path: "electrical.supplies[0].rail", message: "bad rail" }),
    ];

    const grouped = groupRefusalsByField(refusals);

    expect(Object.keys(grouped).sort()).toEqual(["electrical", "source", "vendor"]);
    expect(grouped.vendor).toHaveLength(1);
    expect(grouped.vendor[0].message).toBe("'vendor' is a required property");
  });

  it("drops refusals that map to no field rather than losing them silently in a wrong bucket", () => {
    const grouped = groupRefusalsByField([refusal({ path: "$", message: "nothing nameable here" })]);
    expect(grouped).toEqual({});
  });
});
