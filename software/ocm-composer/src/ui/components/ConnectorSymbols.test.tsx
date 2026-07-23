// SPDX-License-Identifier: AGPL-3.0-or-later
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ConnectorSymbols } from "./ConnectorSymbols";
import { useComponentsStore } from "../../store/componentsStore";

afterEach(cleanup);

beforeEach(() => {
  useComponentsStore.setState({ detail: null });
});

function detailWith(component: Record<string, unknown>) {
  return { id: "com.example.test-part", revision: "0.1.0", draft: true, component: component as never };
}

describe("ConnectorSymbols", () => {
  it("renders nothing when there's no detail, or no connectors at all", () => {
    const { container: empty1 } = render(<ConnectorSymbols />);
    expect(empty1).toBeEmptyDOMElement();

    useComponentsStore.setState({ detail: detailWith({ id: "x", revision: "0.1.0" }) });
    const { container: empty2 } = render(<ConnectorSymbols />);
    expect(empty2).toBeEmptyDOMElement();
  });

  it("renders one symbol per connector, labeled with vendor/part number, one line per pin, each labeled pin number + function", () => {
    useComponentsStore.setState({
      detail: detailWith({
        id: "com.example.test-part",
        revision: "0.1.0",
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
      }),
    });

    render(<ConnectorSymbols />);

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
    useComponentsStore.setState({
      detail: detailWith({
        id: "com.example.test-part",
        revision: "0.1.0",
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
      }),
    });

    expect(() => render(<ConnectorSymbols />)).not.toThrow();
    expect(screen.getAllByRole("img")).toHaveLength(2);
    expect(screen.getByText("no pins recorded yet")).toBeInTheDocument();
  });
});
