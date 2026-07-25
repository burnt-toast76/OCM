// SPDX-License-Identifier: AGPL-3.0-or-later
// A schematic-style preview of each electrical.connectors[] entry -- a box
// labeled with vendor + part number, one line per documented pin
// protruding from its right edge, each labeled with that pin's number and
// function. Purely DERIVED from data the component definition already has
// (vendor, part_number, electrical.connectors[].pins[]) -- no new fields,
// nothing stored.
//
// Takes `component` as a prop rather than reading useComponentsStore
// directly (same generalization AttachmentsList/ChecklistPanel went
// through) so the Modules page's own wiring canvas (WiringCanvas.tsx) can
// reuse this exact component to render EVERY placed instance's connectors,
// not just "whatever's open on the Components page." The optional
// onPinClick/isPinSelected/isPinHighlighted/dataFieldPrefix props exist
// ONLY for that wiring use case -- the Components page's own read-only
// preview passes none of them and renders byte-identical to before.
//
// ADR-0015 Decision 4 (hard constraint): this component provides NO path
// to create, rename, or add a pin. Every pin rendered here comes from
// `component`'s own already-transcribed data; onPinClick fires with the
// pin/connector exactly as transcribed, never a value the caller invented.

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

// Exported so the wiring canvas can tell "no connectors transcribed yet"
// apart from "connectors exist but this doc hasn't loaded" without
// re-implementing electrical.connectors' own defensive extraction.
export function hasConnectors(component: ComponentDoc): boolean {
  return extractConnectors(component).length > 0;
}

const BOX_WIDTH = 130;
const ROW_HEIGHT = 22;
const MIN_BOX_HEIGHT = 60;
const LINE_LENGTH = 36;
const LABEL_WIDTH = 200;
const PADDING = 12;

export interface ConnectorSymbolsProps {
  component: ComponentDoc;
  /** Fires with (connector.ref, pin.pin) exactly as transcribed -- never invented. Omit for the read-only preview. */
  onPinClick?: (connectorRef: string, pin: string) => void;
  isPinSelected?: (connectorRef: string, pin: string) => boolean;
  isPinHighlighted?: (connectorRef: string, pin: string) => boolean;
  /** e.g. "PS1" -- each pin gets data-field="pin:PS1:<connectorRef>:<pin>" for ChecklistPanel's focusField. */
  dataFieldPrefix?: string;
}

function ConnectorSymbol({
  vendor,
  partNumber,
  connector,
  onPinClick,
  isPinSelected,
  isPinHighlighted,
  dataFieldPrefix,
}: {
  vendor: string;
  partNumber: string;
  connector: ConnectorData;
} & Pick<ConnectorSymbolsProps, "onPinClick" | "isPinSelected" | "isPinHighlighted" | "dataFieldPrefix">) {
  const pins = extractPins(connector);
  const rowCount = Math.max(pins.length, 1);
  const boxHeight = Math.max(MIN_BOX_HEIGHT, rowCount * ROW_HEIGHT + PADDING);
  const width = PADDING + BOX_WIDTH + LINE_LENGTH + LABEL_WIDTH + PADDING;
  const height = PADDING + boxHeight + PADDING;
  const boxLeft = PADDING;
  const boxTop = PADDING;
  const boxRight = boxLeft + BOX_WIDTH;
  const caption = connector.type || connector.ref;
  const connectorRef = connector.ref ?? "";
  const interactive = !!onPinClick;

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
          const pinId = p.pin;
          const selected = pinId !== undefined && isPinSelected?.(connectorRef, pinId);
          const highlighted = pinId !== undefined && isPinHighlighted?.(connectorRef, pinId);
          const classes = [
            "connector-symbol__pin",
            interactive && pinId !== undefined && "connector-symbol__pin--clickable",
            selected && "connector-symbol__pin--selected",
            highlighted && "connector-symbol__pin--highlighted",
          ]
            .filter(Boolean)
            .join(" ");
          return (
            <g
              key={i}
              className={classes}
              data-field={dataFieldPrefix && pinId !== undefined ? `pin:${dataFieldPrefix}:${connectorRef}:${pinId}` : undefined}
              onClick={interactive && pinId !== undefined ? () => onPinClick(connectorRef, pinId) : undefined}
              role={interactive && pinId !== undefined ? "button" : undefined}
              aria-label={interactive && pinId !== undefined ? `Pin ${pinId} (${p.function ?? "?"})` : undefined}
              tabIndex={interactive && pinId !== undefined ? 0 : undefined}
            >
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

export function ConnectorSymbols({ component, onPinClick, isPinSelected, isPinHighlighted, dataFieldPrefix }: ConnectorSymbolsProps) {
  const connectors = extractConnectors(component);
  if (connectors.length === 0) return null;

  const vendor = typeof component.vendor === "string" ? component.vendor : "";
  const partNumber = typeof component.part_number === "string" ? component.part_number : "";

  return (
    <div className="connector-symbols">
      <h2>Connectors</h2>
      <div className="connector-symbols__row">
        {connectors.map((connector, i) => (
          <ConnectorSymbol
            key={connector.ref ?? i}
            vendor={vendor}
            partNumber={partNumber}
            connector={connector}
            onPinClick={onPinClick}
            isPinSelected={isPinSelected}
            isPinHighlighted={isPinHighlighted}
            dataFieldPrefix={dataFieldPrefix}
          />
        ))}
      </div>
    </div>
  );
}
