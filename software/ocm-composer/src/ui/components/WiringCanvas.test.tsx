// SPDX-License-Identifier: AGPL-3.0-or-later
// WiringCanvas is a thin UI over wiring.ts's pure functions and
// modulesStore's setElectricalNets/publish actions -- these tests drive
// real clicks and assert the store action was called with the right
// argument, mirroring modulesStore.test.ts's "assert the exact patch
// shape" style but at the component layer. The no-create-pin test is the
// one ADR-0015 Decision 4 explicitly asked for: nothing rendered here may
// let a user type in a new pin id, connector ref, or port id.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { WiringCanvas } from "./WiringCanvas";
import { useModulesStore } from "../../store/modulesStore";
import { useComponentsStore } from "../../store/componentsStore";
import { useNavStore } from "../../store/navStore";
import type { ComponentDoc, DescribeModuleData, ModuleNetRow, Refusal } from "../../api/types";

afterEach(cleanup);

const PS1_ID = "com.example.ps.ps1";
const NOVG_ID = "com.example.novg.novg1";

function psDoc(): ComponentDoc {
  return {
    id: PS1_ID,
    revision: "1.0.0",
    vendor: "Example Co",
    part_number: "PS-1",
    electrical: {
      connectors: [{ ref: "electrical", pins: [{ pin: "1", function: "L+" }, { pin: "2", function: "L-" }] }],
    },
  };
}

function noConnectorsDoc(): ComponentDoc {
  return { id: NOVG_ID, revision: "1.0.0" };
}

function detailWith(opts: {
  components?: DescribeModuleData["manifest"]["components"];
  ports?: DescribeModuleData["manifest"]["ports"];
  nets?: ModuleNetRow[];
}): DescribeModuleData {
  return {
    id: "com.example.pickhead.pk100",
    revision: "0.1.0",
    draft: true,
    manifest: {
      id: "com.example.pickhead.pk100",
      revision: "0.1.0",
      kind: "end_effector",
      mechanical: { mount: { interface: "custom" }, frames: {} },
      components: opts.components ?? [],
      ports: opts.ports ?? [],
      nets: opts.nets ? { electrical: opts.nets } : undefined,
    },
  };
}

let setElectricalNets: ReturnType<typeof vi.fn>;
let publish: ReturnType<typeof vi.fn>;
let selectComponent: ReturnType<typeof vi.fn>;
let setView: ReturnType<typeof vi.fn>;

beforeEach(() => {
  setElectricalNets = vi.fn().mockResolvedValue(undefined);
  publish = vi.fn().mockResolvedValue(undefined);
  selectComponent = vi.fn().mockResolvedValue(undefined);
  setView = vi.fn();

  useModulesStore.setState({
    detail: detailWith({}),
    componentDocs: {},
    checklist: [],
    setElectricalNets,
    publish,
  });
  useComponentsStore.setState({ selectComponent });
  useNavStore.setState({ setView });
});

describe("WiringCanvas -- non-electrical domains", () => {
  it("renders a placeholder for pneumatic/communication, with no rails, cards, or click affordances", () => {
    render(<WiringCanvas domain="pneumatic" />);
    expect(screen.getByText(/Pneumatic wiring is not built yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("WiringCanvas -- electrical, empty module", () => {
  it("shows the empty-components message and an empty net-list hint", () => {
    render(<WiringCanvas domain="electrical" />);
    expect(screen.getByText(/No components placed yet/)).toBeInTheDocument();
    expect(screen.getByText(/No nets yet/)).toBeInTheDocument();
  });
});

describe("WiringCanvas -- component cards", () => {
  it("renders a loading card when the component doc hasn't arrived yet", () => {
    useModulesStore.setState({
      detail: detailWith({ components: [{ refdes: "PS1", ref: `${PS1_ID}@1.0.0` }] }),
    });
    render(<WiringCanvas domain="electrical" />);
    expect(screen.getByText("PS1")).toBeInTheDocument();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("renders a missing-connectors card with the refusal and a link to the component's authoring page, for a component with none transcribed", () => {
    useModulesStore.setState({
      detail: detailWith({ components: [{ refdes: "VG1", ref: `${NOVG_ID}@1.0.0` }] }),
      componentDocs: { [NOVG_ID]: noConnectorsDoc() },
      checklist: [
        {
          code: "COMPONENT_HAS_NO_CONNECTORS",
          path: `modules['x'].components['VG1']`,
          message: "refdes 'VG1' has no connectors",
          allowed: null,
          hint: null,
        } satisfies Refusal,
      ],
    });

    render(<WiringCanvas domain="electrical" />);

    expect(screen.getByText("This component has no transcribed connectors yet.")).toBeInTheDocument();
    // Both the card and the ChecklistPanel render the same refusal message
    // verbatim -- assert the card's own copy specifically.
    const card = screen.getByText("This component has no transcribed connectors yet.").closest(".wiring-canvas__card--missing");
    expect(card).not.toBeNull();
    expect(card!.querySelector(".wiring-canvas__card-refusal")?.textContent).toBe("refdes 'VG1' has no connectors");

    fireEvent.click(screen.getByRole("button", { name: `Go to ${NOVG_ID}'s authoring page` }));
    expect(selectComponent).toHaveBeenCalledWith(NOVG_ID);
    expect(setView).toHaveBeenCalledWith("components");
  });

  it("renders a full card with clickable pins for a component with transcribed connectors", () => {
    useModulesStore.setState({
      detail: detailWith({ components: [{ refdes: "PS1", ref: `${PS1_ID}@1.0.0` }] }),
      componentDocs: { [PS1_ID]: psDoc() },
    });

    render(<WiringCanvas domain="electrical" />);

    expect(screen.getByText("PS1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pin 1 (L+)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pin 2 (L-)" })).toBeInTheDocument();
  });
});

describe("WiringCanvas -- wiring interactions", () => {
  function twoComponentDetail(nets: ModuleNetRow[] = []) {
    return detailWith({
      components: [
        { refdes: "PS1", ref: `${PS1_ID}@1.0.0` },
        { refdes: "PS2", ref: `${PS1_ID}@1.0.0` },
      ],
      ports: [{ id: "PWR_IN", domain: "electrical", type: "M12" }],
      nets,
    });
  }

  it("click pin -> click pin on a different component creates a new net via setElectricalNets", () => {
    useModulesStore.setState({
      detail: twoComponentDetail(),
      componentDocs: { [PS1_ID]: psDoc() },
    });
    render(<WiringCanvas domain="electrical" />);

    const pin1Buttons = screen.getAllByRole("button", { name: "Pin 1 (L+)" });
    fireEvent.click(pin1Buttons[0]);
    fireEvent.click(pin1Buttons[1]);

    expect(setElectricalNets).toHaveBeenCalledTimes(1);
    expect(setElectricalNets).toHaveBeenCalledWith([
      {
        id: "N1",
        endpoints: [
          { refdes: "PS1", ref: "electrical", pin: "1" },
          { refdes: "PS2", ref: "electrical", pin: "1" },
        ],
      },
    ]);
  });

  it("clicking a rail after a pin joins that net", () => {
    useModulesStore.setState({
      detail: twoComponentDetail(),
      componentDocs: { [PS1_ID]: psDoc() },
    });
    render(<WiringCanvas domain="electrical" />);

    fireEvent.click(screen.getAllByRole("button", { name: "Pin 1 (L+)" })[0]);
    fireEvent.click(screen.getByText("PWR_IN"));

    expect(setElectricalNets).toHaveBeenCalledWith([
      { id: "N1", endpoints: [{ refdes: "PS1", ref: "electrical", pin: "1" }, { port: "PWR_IN" }] },
    ]);
  });

  it("clicking the same pin twice cancels the pending wire instead of wiring it to itself", () => {
    useModulesStore.setState({
      detail: twoComponentDetail(),
      componentDocs: { [PS1_ID]: psDoc() },
    });
    render(<WiringCanvas domain="electrical" />);

    const pin1 = screen.getAllByRole("button", { name: "Pin 1 (L+)" })[0];
    fireEvent.click(pin1);
    fireEvent.click(pin1);

    expect(setElectricalNets).not.toHaveBeenCalled();
  });

  it("net-list rename commits a new id via setElectricalNets", () => {
    const nets = [{ id: "N1", endpoints: [{ port: "PWR_IN" }, { refdes: "PS1", ref: "electrical", pin: "1" }] }];
    useModulesStore.setState({ detail: twoComponentDetail(nets) });
    render(<WiringCanvas domain="electrical" />);

    fireEvent.click(screen.getByRole("button", { name: "N1" }));
    const input = screen.getByLabelText("Rename net N1");
    fireEvent.change(input, { target: { value: "SUPPLY_24V" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(setElectricalNets).toHaveBeenCalledWith([{ ...nets[0], id: "SUPPLY_24V" }]);
  });

  it("net-list delete removes that net via setElectricalNets", () => {
    const nets = [{ id: "N1", endpoints: [{ port: "PWR_IN" }, { refdes: "PS1", ref: "electrical", pin: "1" }] }];
    useModulesStore.setState({ detail: twoComponentDetail(nets) });
    render(<WiringCanvas domain="electrical" />);

    fireEvent.click(screen.getByRole("button", { name: "Delete net N1" }));

    expect(setElectricalNets).toHaveBeenCalledWith([]);
  });
});

describe("WiringCanvas -- ADR-0015 Decision 4 (no path to create, rename, or add a pin)", () => {
  it("renders no text input anywhere except the net-rename box and the publish-revision box -- never a pin/connector/port id field", () => {
    useModulesStore.setState({
      detail: detailWith({
        components: [
          { refdes: "PS1", ref: `${PS1_ID}@1.0.0` },
          { refdes: "VG1", ref: `${NOVG_ID}@1.0.0` },
        ],
        ports: [{ id: "PWR_IN", domain: "electrical", type: "M12" }],
        nets: [{ id: "N1", endpoints: [{ port: "PWR_IN" }, { refdes: "PS1", ref: "electrical", pin: "1" }] }],
      }),
      componentDocs: { [PS1_ID]: psDoc(), [NOVG_ID]: noConnectorsDoc() },
    });

    render(<WiringCanvas domain="electrical" />);

    const textInputs = screen.queryAllByRole("textbox");
    // Only the publish-revision input from ChecklistPanel; the net-rename
    // input only mounts once a net name is clicked into edit mode, which
    // this test never does.
    expect(textInputs).toHaveLength(1);
    expect(textInputs[0]).toHaveAttribute("aria-label", "Publish revision");

    // No button anywhere offers to add/create/rename a pin, connector, or port.
    const buttonNames = screen.getAllByRole("button").map((b) => b.textContent ?? b.getAttribute("aria-label") ?? "");
    for (const name of buttonNames) {
      expect(name.toLowerCase()).not.toMatch(/add pin|new pin|create pin|add connector|new connector|add port/);
    }
  });
});
