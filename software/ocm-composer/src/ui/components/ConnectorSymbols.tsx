// SPDX-License-Identifier: AGPL-3.0-or-later
// A schematic-style preview of each electrical.connectors[] entry -- a box
// labeled with vendor + part number, one line per documented pin
// protruding from its right edge, each labeled with that pin's number and
// function. Purely DERIVED from data the component definition already has
// (vendor, part_number, electrical.connectors[].pins[]) -- no new fields,
// nothing stored. This is the preview only; the future module-authoring
// "wire components together" tool this is meant to feed is a separate,
// later piece of work.

import { useComponentsStore } from "../../store/componentsStore";
import type { ComponentDoc } from "../../api/types";

interface ConnectorPin {
  pin?: string;
  function?: string;
  wire_color?: string;
}

interface ConnectorData {
  ref?: string;
  type?: string;
  pins?: ConnectorPin[];
}

// component.electrical is untyped passthrough (ComponentDoc's own index
// signature) -- a component in progress can have it missing, malformed,
// or (per the setAtPath bug fixed earlier this session) shaped wrong, so
// every level here is read defensively rather than trusted.
function extractConnectors(component: ComponentDoc): ConnectorData[] {
  const electrical = component.electrical;
  if (!electrical || typeof electrical !== "object") return [];
  const connectors = (electrical as Record<string, unknown>).connectors;
  if (!Array.isArray(connectors)) return [];
  return connectors.filter((c): c is ConnectorData => !!c && typeof c === "object");
}

function extractPins(connector: ConnectorData): ConnectorPin[] {
  return Array.isArray(connector.pins) ? connector.pins.filter((p): p is ConnectorPin => !!p && typeof p === "object") : [];
}

const BOX_WIDTH = 130;
const ROW_HEIGHT = 22;
const MIN_BOX_HEIGHT = 60;
const LINE_LENGTH = 36;
const LABEL_WIDTH = 200;
const PADDING = 12;

function ConnectorSymbol({ vendor, partNumber, connector }: { vendor: string; partNumber: string; connector: ConnectorData }) {
  const pins = extractPins(connector);
  const rowCount = Math.max(pins.length, 1);
  const boxHeight = Math.max(MIN_BOX_HEIGHT, rowCount * ROW_HEIGHT + PADDING);
  const width = PADDING + BOX_WIDTH + LINE_LENGTH + LABEL_WIDTH + PADDING;
  const height = PADDING + boxHeight + PADDING;
  const boxLeft = PADDING;
  const boxTop = PADDING;
  const boxRight = boxLeft + BOX_WIDTH;
  const caption = connector.type || connector.ref;

  return (
    <svg
      className="connector-symbol"
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      role="img"
      aria-label={`${connector.ref ?? "Connector"} pinout symbol`}
    >
      <rect x={boxLeft} y={boxTop} width={BOX_WIDTH} height={boxHeight} className="connector-symbol__box" />
      <text x={boxLeft + BOX_WIDTH / 2} y={boxTop + 18} textAnchor="middle" className="connector-symbol__vendor">
        {vendor || "vendor?"}
      </text>
      <text x={boxLeft + BOX_WIDTH / 2} y={boxTop + 34} textAnchor="middle" className="connector-symbol__part">
        {partNumber || "part number?"}
      </text>
      {caption && (
        <text x={boxLeft + BOX_WIDTH / 2} y={boxTop + boxHeight - 8} textAnchor="middle" className="connector-symbol__caption">
          {caption}
        </text>
      )}
      {pins.length === 0 ? (
        <text x={boxRight + 10} y={boxTop + boxHeight / 2} className="connector-symbol__empty">
          no pins recorded yet
        </text>
      ) : (
        pins.map((p, i) => {
          const y = boxTop + PADDING / 2 + ROW_HEIGHT * i + ROW_HEIGHT / 2;
          const lineEnd = boxRight + LINE_LENGTH;
          return (
            <g key={i}>
              <line x1={boxRight} y1={y} x2={lineEnd} y2={y} className="connector-symbol__pin-line" />
              <text x={boxRight + 4} y={y - 3} className="connector-symbol__pin-number">
                {p.pin ?? "?"}
              </text>
              <text x={lineEnd + 4} y={y + 4} className="connector-symbol__pin-function">
                {p.function ?? "?"}
                {p.wire_color ? ` · ${p.wire_color}` : ""}
              </text>
            </g>
          );
        })
      )}
    </svg>
  );
}

export function ConnectorSymbols() {
  const detail = useComponentsStore((s) => s.detail);
  if (!detail) return null;

  const connectors = extractConnectors(detail.component);
  if (connectors.length === 0) return null;

  const vendor = typeof detail.component.vendor === "string" ? detail.component.vendor : "";
  const partNumber = typeof detail.component.part_number === "string" ? detail.component.part_number : "";

  return (
    <div className="connector-symbols">
      <h2>Connectors</h2>
      <div className="connector-symbols__row">
        {connectors.map((connector, i) => (
          <ConnectorSymbol key={connector.ref ?? i} vendor={vendor} partNumber={partNumber} connector={connector} />
        ))}
      </div>
    </div>
  );
}
