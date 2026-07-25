// SPDX-License-Identifier: AGPL-3.0-or-later
// ONE canvas, parameterized by domain -- instantiated once per wiring tab
// (Electrical/Pneumatic/Communication) on ModuleDetail, never copied. Only
// "electrical" has real behavior in this pass; the other two domains
// render a plain placeholder until their own instance lands (their data
// shape already exists -- nets.pneumatic, links -- this file just doesn't
// drive them yet).
//
// Data flow mirrors moveComponentInstance exactly: edit the nets array
// locally (wiring.ts's pure applyWireClick), send the WHOLE array via
// update_module (modulesStore.setElectricalNets), re-read the
// server-confirmed manifest. A refusal's message is stored and rendered
// verbatim, never reinterpreted -- same as placementError elsewhere.
//
// ADR-0015 Decision 4 (HARD CONSTRAINT): no path here creates, renames, or
// adds a PIN. Every clickable pin comes from ConnectorSymbols rendering a
// component's own already-transcribed connectors; a component with none
// gets a card saying so, the matching validate_module refusal if one has
// fired, and a link to that component's OWN authoring page (Components
// page) -- never an inline "add a pin" affordance. Only NETS (and their
// names) are created/renamed/deleted here.

import { useState } from "react";
import { useComponentsStore } from "../../store/componentsStore";
import { useModulesStore } from "../../store/modulesStore";
import { useNavStore } from "../../store/navStore";
import { applyWireClick, endpointsEqual, moduleRefusalFieldKey } from "../wiring";
import { ChecklistPanel } from "./ChecklistPanel";
import { ConnectorSymbols, hasConnectors } from "./ConnectorSymbols";
import type { ModuleEndpoint, ModulePortDomain } from "../../api/types";

export interface WiringCanvasProps {
  domain: ModulePortDomain;
}

const DOMAIN_LABEL: Record<ModulePortDomain, string> = {
  electrical: "Electrical",
  pneumatic: "Pneumatic",
  communication: "Communication",
};

export function WiringCanvas({ domain }: WiringCanvasProps) {
  const detail = useModulesStore((s) => s.detail);
  const componentDocs = useModulesStore((s) => s.componentDocs);
  const checklist = useModulesStore((s) => s.checklist);
  const setElectricalNets = useModulesStore((s) => s.setElectricalNets);
  const publish = useModulesStore((s) => s.publish);

  const [pending, setPending] = useState<ModuleEndpoint | null>(null);
  const [renamingNetId, setRenamingNetId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  if (domain !== "electrical") {
    return (
      <div className="wiring-canvas wiring-canvas--placeholder">
        <p>{DOMAIN_LABEL[domain]} wiring is not built yet -- this tab exists so the shell is complete.</p>
      </div>
    );
  }

  if (!detail) return null;

  const components = detail.manifest.components ?? [];
  const ports = (detail.manifest.ports ?? []).filter((p) => p.domain === "electrical");
  const nets = detail.manifest.nets?.electrical ?? [];

  const netContaining = (endpoint: ModuleEndpoint) => nets.find((n) => n.endpoints.some((e) => endpointsEqual(e, endpoint)));
  const isPending = (endpoint: ModuleEndpoint) => !!pending && endpointsEqual(pending, endpoint);
  const refusalForField = (key: string) => checklist.find((r) => moduleRefusalFieldKey(r) === key);

  const handleEndpointClick = (endpoint: ModuleEndpoint) => {
    if (!pending) {
      setPending(endpoint);
      return;
    }
    if (endpointsEqual(pending, endpoint)) {
      setPending(null); // clicking the same pin again cancels the pending wire
      return;
    }
    const next = applyWireClick(nets, pending, endpoint);
    setPending(null);
    void setElectricalNets(next);
  };

  const handleDeleteNet = (netId: string) => {
    if (pending) setPending(null);
    void setElectricalNets(nets.filter((n) => n.id !== netId));
  };

  const commitRename = (oldId: string) => {
    const trimmed = renameValue.trim();
    setRenamingNetId(null);
    if (!trimmed || trimmed === oldId || nets.some((n) => n.id === trimmed)) return;
    void setElectricalNets(nets.map((n) => (n.id === oldId ? { ...n, id: trimmed } : n)));
  };

  const goToComponent = (componentId: string) => {
    useComponentsStore.getState().selectComponent(componentId);
    useNavStore.getState().setView("components");
  };

  return (
    <div className="wiring-canvas">
      <div className="wiring-canvas__main">
        {ports.length > 0 && (
          <div className="wiring-canvas__rails">
            {ports.map((port) => {
              const endpoint: ModuleEndpoint = { port: port.id };
              const net = netContaining(endpoint);
              const classes = [
                "wiring-canvas__rail",
                isPending(endpoint) && "wiring-canvas__rail--pending",
                net && "wiring-canvas__rail--wired",
              ]
                .filter(Boolean)
                .join(" ");
              return (
                <button
                  key={port.id}
                  type="button"
                  className={classes}
                  data-field={`port:${port.id}`}
                  onClick={() => handleEndpointClick(endpoint)}
                >
                  <span className="wiring-canvas__rail-id">{port.id}</span>
                  {port.type && <span className="wiring-canvas__rail-type">{port.type}</span>}
                  {net && <span className="wiring-canvas__rail-net">{net.id}</span>}
                </button>
              );
            })}
          </div>
        )}

        <div className="wiring-canvas__cards">
          {components.length === 0 ? (
            <p className="wiring-canvas__empty">No components placed yet -- add one from the Assembly tab.</p>
          ) : (
            components.map((c) => {
              const componentId = c.ref.split("@")[0];
              const doc = componentDocs[componentId];
              const missingRefusal = refusalForField(`component:${c.refdes}`);

              if (!doc) {
                return (
                  <div key={c.refdes} className="wiring-canvas__card wiring-canvas__card--loading">
                    <h3>{c.refdes}</h3>
                    <p>Loading…</p>
                  </div>
                );
              }

              if (!hasConnectors(doc)) {
                return (
                  <div key={c.refdes} className="wiring-canvas__card wiring-canvas__card--missing" data-field={`component:${c.refdes}`}>
                    <h3>
                      {c.refdes} <span className="wiring-canvas__card-ref">{componentId}</span>
                    </h3>
                    <p className="wiring-canvas__card-missing-message">This component has no transcribed connectors yet.</p>
                    {missingRefusal && <p className="wiring-canvas__card-refusal">{missingRefusal.message}</p>}
                    <button type="button" onClick={() => goToComponent(componentId)}>
                      Go to {componentId}'s authoring page
                    </button>
                  </div>
                );
              }

              return (
                <div key={c.refdes} className="wiring-canvas__card">
                  <h3>
                    {c.refdes} <span className="wiring-canvas__card-ref">{componentId}</span>
                  </h3>
                  <ConnectorSymbols
                    component={doc}
                    dataFieldPrefix={c.refdes}
                    onPinClick={(ref, pin) => handleEndpointClick({ refdes: c.refdes, ref, pin })}
                    isPinSelected={(ref, pin) => isPending({ refdes: c.refdes, ref, pin })}
                    isPinHighlighted={(ref, pin) => !!refusalForField(`pin:${c.refdes}:${ref}:${pin}`)}
                  />
                </div>
              );
            })
          )}
        </div>
      </div>

      <aside className="wiring-canvas__side">
        <div className="wiring-canvas__net-list">
          <h2>Nets</h2>
          {nets.length === 0 ? (
            <p className="wiring-canvas__net-list-empty">
              No nets yet -- click a pin, then click another pin (or a rail) to wire them together.
            </p>
          ) : (
            <ul className="wiring-canvas__net-list-items">
              {nets.map((net) => (
                <li key={net.id} data-field={`net:${net.id}`} className="wiring-canvas__net-row">
                  {renamingNetId === net.id ? (
                    <input
                      autoFocus
                      className="wiring-canvas__net-rename"
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      onBlur={() => commitRename(net.id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") commitRename(net.id);
                        if (e.key === "Escape") setRenamingNetId(null);
                      }}
                      aria-label={`Rename net ${net.id}`}
                    />
                  ) : (
                    <button
                      type="button"
                      className="wiring-canvas__net-name"
                      onClick={() => {
                        setRenamingNetId(net.id);
                        setRenameValue(net.id);
                      }}
                    >
                      {net.id}
                    </button>
                  )}
                  <span className="wiring-canvas__net-count">{net.endpoints.length} endpoints</span>
                  <button
                    type="button"
                    className="wiring-canvas__net-delete"
                    onClick={() => handleDeleteNet(net.id)}
                    aria-label={`Delete net ${net.id}`}
                  >
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <ChecklistPanel
          checklist={checklist}
          canPublish={!!detail}
          onPublish={(revision) => void publish(revision)}
          fieldKeyOf={moduleRefusalFieldKey}
        />
      </aside>
    </div>
  );
}
