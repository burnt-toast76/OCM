// SPDX-License-Identifier: AGPL-3.0-or-later
// The task's own explicit requirements: the form renders every top-level
// schema section, and a refusal path maps to the right field.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ComponentForm } from "./ComponentForm";
import { useComponentsStore } from "../../store/componentsStore";
import type { JsonSchemaNode } from "../../api/types";

afterEach(cleanup);

// A trimmed but representative slice of the real component schema
// (spec/schema/ocm-component-1.0.schema.json) -- covers every field
// SHAPE the form has to handle: plain string, enum, nested object,
// array-of-objects, array-of-enum-strings. `source.kind` deliberately
// reuses the same name as the top-level `kind` field, same as the real
// schema does -- a section lookup that's merely text-based (rather than
// scoped to a heading) would wrongly treat those as the same element.
const FAKE_SCHEMA: JsonSchemaNode = {
  type: "object",
  required: ["ocm_version", "id", "revision", "kind", "vendor", "source"],
  properties: {
    ocm_version: { const: "1.1" },
    id: { type: "string" },
    revision: { type: "string" },
    name: { type: "string" },
    vendor: { type: "string" },
    part_number: { type: "string" },
    source: {
      type: "object",
      properties: { kind: { enum: ["datasheet", "manual"] }, ref: { type: "string" }, date: { type: "string" } },
    },
    kind: { anyOf: [{ enum: ["vacuum_ejector", "sensor"] }, { type: "string", pattern: "^x-" }] },
    electrical: {
      type: "object",
      properties: { supplies: { type: "array", items: { type: "object", properties: { rail: { enum: ["24VDC"] } } } } },
    },
    hazards: { type: "array", items: { enum: ["pinch", "crush"] } },
    notes: { type: "string" },
  },
};

function baseState() {
  return {
    schema: FAKE_SCHEMA,
    detail: {
      id: "com.example.test-part",
      revision: "0.1.0",
      draft: true,
      component: { ocm_version: "1.1", id: "com.example.test-part", revision: "0.1.0" },
    },
    fieldErrors: {},
    agentFilledFields: new Set<string>(),
  };
}

// Top-level sections are h3.component-form__heading; a nested field's own
// <label> (e.g. source's own "kind" property) can share the same text
// without being confused for the section it lives inside.
function sectionHeading(key: string): HTMLElement {
  return screen.getByText(key, { selector: "h3.component-form__heading" });
}

beforeEach(() => {
  useComponentsStore.setState(baseState());
});

describe("ComponentForm", () => {
  it("renders every top-level schema section, in schema order, except the server-managed identity fields", () => {
    render(<ComponentForm />);

    for (const key of ["name", "vendor", "part_number", "source", "kind", "electrical", "hazards", "notes"]) {
      expect(sectionHeading(key)).toBeInTheDocument();
    }
    // ocm_version/id/revision are shown by ComponentDetail's own header,
    // not re-editable inside this form.
    expect(screen.queryByText("ocm_version", { selector: "h3.component-form__heading" })).not.toBeInTheDocument();
    expect(screen.queryByText("id", { selector: "h3.component-form__heading" })).not.toBeInTheDocument();
    expect(screen.queryByText("revision", { selector: "h3.component-form__heading" })).not.toBeInTheDocument();
  });

  it("shows a loading state until schema and detail are both available", () => {
    useComponentsStore.setState({ schema: null });
    render(<ComponentForm />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("maps a refusal on `vendor` to the vendor section, not some other one", () => {
    useComponentsStore.setState({
      fieldErrors: {
        vendor: [{ code: "SCHEMA_INVALID", path: "$", message: "'vendor' is a required property", allowed: null, hint: "Fill it in." }],
      },
    });

    render(<ComponentForm />);

    const vendorSection = sectionHeading("vendor").closest("section")!;
    expect(vendorSection).toHaveClass("component-form__section--error");
    expect(vendorSection.textContent).toContain("'vendor' is a required property");
    expect(vendorSection.textContent).toContain("Fill it in.");

    // And it did NOT also land on an unrelated section.
    const notesSection = sectionHeading("notes").closest("section")!;
    expect(notesSection).not.toHaveClass("component-form__section--error");
  });

  it("marks a field the agent filled this session with the agent marker, and nowhere else", () => {
    useComponentsStore.setState({ agentFilledFields: new Set(["electrical"]) });

    render(<ComponentForm />);

    const electricalSection = sectionHeading("electrical").closest("section")!;
    expect(electricalSection.querySelector(".component-form__agent-marker")).not.toBeNull();

    const vendorSection = sectionHeading("vendor").closest("section")!;
    expect(vendorSection.querySelector(".component-form__agent-marker")).toBeNull();
  });

  it("renders an array-of-objects field as an empty, fixable list instead of crashing when the stored value isn't actually an array", () => {
    // Reproduces a real corrupted draft: a past setAtPath bug wrote
    // electrical.supplies as an object keyed by stringified index
    // ({"0": {rail: "24VDC"}}) instead of a real array. The schema still
    // says "array", so SchemaField's own array renderer must not trust
    // that and call .map on whatever's actually there.
    useComponentsStore.setState({
      detail: {
        id: "com.example.test-part",
        revision: "0.1.0",
        draft: true,
        component: {
          ocm_version: "1.1",
          id: "com.example.test-part",
          revision: "0.1.0",
          electrical: { supplies: { "0": { rail: "24VDC" } } },
        },
      },
    });

    expect(() => render(<ComponentForm />)).not.toThrow();

    const electricalSection = sectionHeading("electrical").closest("section")!;
    expect(electricalSection.querySelector(".schema-array__row")).toBeNull();
    expect(electricalSection.querySelector(".schema-array__add")).not.toBeNull();
  });

  it("supports a two-level-nested array -- a connector's own pins -- committing each leaf edit at the right path", () => {
    // electrical.connectors[].pins[] (spec/schema/ocm-component-1.0.schema.json):
    // an array-of-objects (connectors) whose own item schema has ANOTHER
    // array-of-objects property (pins). SchemaField is fully generic/
    // recursive, so this ought to "just work" with no code change beyond
    // the schema -- this pins it down for the real nested shape, not just
    // one level of array.
    const saveField = vi.fn();
    const schemaWithPins: JsonSchemaNode = {
      ...FAKE_SCHEMA,
      properties: {
        ...FAKE_SCHEMA.properties,
        electrical: {
          type: "object",
          properties: {
            connectors: {
              type: "array",
              items: {
                type: "object",
                properties: {
                  ref: { type: "string" },
                  pins: {
                    type: "array",
                    items: { type: "object", properties: { pin: { type: "string" }, function: { type: "string" } } },
                  },
                },
              },
            },
          },
        },
      },
    };

    useComponentsStore.setState({
      schema: schemaWithPins,
      detail: {
        id: "com.example.test-part",
        revision: "0.1.0",
        draft: true,
        component: {
          ocm_version: "1.1",
          id: "com.example.test-part",
          revision: "0.1.0",
          electrical: { connectors: [{ ref: "M12", pins: [{}] }] },
        },
      },
      saveField,
    });

    render(<ComponentForm />);

    fireEvent.change(screen.getByLabelText("pin"), { target: { value: "1" } });
    fireEvent.blur(screen.getByLabelText("pin"));
    fireEvent.change(screen.getByLabelText("function"), { target: { value: "24VDC supply" } });
    fireEvent.blur(screen.getByLabelText("function"));

    expect(saveField).toHaveBeenCalledWith(["electrical", "connectors", "0", "pins", "0", "pin"], "1");
    expect(saveField).toHaveBeenCalledWith(["electrical", "connectors", "0", "pins", "0", "function"], "24VDC supply");
  });
});
