// SPDX-License-Identifier: AGPL-3.0-or-later
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ConnectorSymbols, hasConnectors } from "./ConnectorSymbols";
import type { ComponentDoc } from "../../api/types";

afterEach(cleanup);

function doc(overrides: Record<string, unknown>): ComponentDoc {
  return { id: "com.example.test-part", revision: "0.1.0", ...overrides } as ComponentDoc;
}

describe("ConnectorSymbols", () => {
  it("renders nothing when the component has no connectors at all", () => {
    const { container } = render(<ConnectorSymbols component={doc({})} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders one symbol per connector, labeled with vendor/part number, one line per pin, each labeled pin number + function", () => {
    const component = doc({
      vendor: "AutomationDirect",
      part_number: "EPS25-100WC-1001",
      electrical: {
        connectors: [
          {
            ref: "electrical",
            type: "4-pin M12 quick-disconnect",
            pins: [
              { pin: "1", function: "L+ (supply)", wire_color: "BN" },
              { pin: "2", function: "OUT2" },
            ],
          },
        ],
      },
    });

    render(<ConnectorSymbols component={component} />);

    expect(screen.getByText("AutomationDirect")).toBeInTheDocument();
    expect(screen.getByText("EPS25-100WC-1001")).toBeInTheDocument();
    expect(screen.getByText("4-pin M12 quick-disconnect")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("L+ (supply) · BN")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("OUT2")).toBeInTheDocument();
    expect(screen.getAllByRole("img")).toHaveLength(1);
  });

  it("renders one symbol per connector when there's more than one, and never crashes on a connector with a malformed pins field", () => {
    const component = doc({
      vendor: "Example Co",
      electrical: {
        connectors: [
          { ref: "power", pins: [{ pin: "1", function: "24VDC" }] },
          // A shape the setAtPath bug fixed earlier this session could
          // have produced -- an object keyed by index instead of a real
          // array. Must render as "no pins recorded yet", never crash.
          { ref: "signal", pins: { "0": { pin: "1", function: "signal" } } },
        ],
      },
    });

    expect(() => render(<ConnectorSymbols component={component} />)).not.toThrow();
    expect(screen.getAllByRole("img")).toHaveLength(2);
    expect(screen.getByText("no pins recorded yet")).toBeInTheDocument();
  });

  it("without onPinClick, renders pins as inert -- no click affordance, no data-field, no click handler", () => {
    const component = doc({
      electrical: { connectors: [{ ref: "electrical", pins: [{ pin: "1", function: "L+" }] }] },
    });

    render(<ConnectorSymbols component={component} dataFieldPrefix="PS1" />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("with onPinClick, fires it with exactly the transcribed connector ref and pin -- never an invented value (ADR-0015 Decision 4)", () => {
    const onPinClick = vi.fn();
    const component = doc({
      electrical: {
        connectors: [{ ref: "electrical", pins: [{ pin: "1", function: "L+" }, { pin: "2", function: "L-" }] }],
      },
    });

    render(<ConnectorSymbols component={component} dataFieldPrefix="PS1" onPinClick={onPinClick} />);

    fireEvent.click(screen.getByRole("button", { name: "Pin 2 (L-)" }));

    expect(onPinClick).toHaveBeenCalledTimes(1);
    expect(onPinClick).toHaveBeenCalledWith("electrical", "2");
  });

  it("marks a pin selected/highlighted only when the matching predicate says so, keyed by connector ref + pin", () => {
    const component = doc({
      electrical: {
        connectors: [{ ref: "electrical", pins: [{ pin: "1", function: "L+" }, { pin: "2", function: "L-" }] }],
      },
    });

    render(
      <ConnectorSymbols
        component={component}
        dataFieldPrefix="PS1"
        onPinClick={() => {}}
        isPinSelected={(ref, pin) => ref === "electrical" && pin === "1"}
        isPinHighlighted={(ref, pin) => ref === "electrical" && pin === "2"}
      />,
    );

    const pin1 = screen.getByRole("button", { name: "Pin 1 (L+)" });
    const pin2 = screen.getByRole("button", { name: "Pin 2 (L-)" });
    expect(pin1.getAttribute("class")).toContain("connector-symbol__pin--selected");
    expect(pin1.getAttribute("class")).not.toContain("connector-symbol__pin--highlighted");
    expect(pin2.getAttribute("class")).toContain("connector-symbol__pin--highlighted");
    expect(pin2.getAttribute("class")).not.toContain("connector-symbol__pin--selected");
  });

  it("sets data-field as pin:<prefix>:<connectorRef>:<pin> for ChecklistPanel's focusField to find", () => {
    const component = doc({
      electrical: { connectors: [{ ref: "electrical", pins: [{ pin: "1", function: "L+" }] }] },
    });

    const { container } = render(<ConnectorSymbols component={component} dataFieldPrefix="PS1" onPinClick={() => {}} />);

    expect(container.querySelector('[data-field="pin:PS1:electrical:1"]')).toBeInTheDocument();
  });
});

describe("hasConnectors", () => {
  it("is false when the component has no connectors at all", () => {
    expect(hasConnectors(doc({}))).toBe(false);
  });

  it("is false when electrical.connectors is present but empty or malformed", () => {
    expect(hasConnectors(doc({ electrical: { connectors: [] } }))).toBe(false);
    expect(hasConnectors(doc({ electrical: { connectors: "not an array" } }))).toBe(false);
  });

  it("is true once at least one real connector is transcribed", () => {
    expect(hasConnectors(doc({ electrical: { connectors: [{ ref: "electrical", pins: [] }] } }))).toBe(true);
  });
});
