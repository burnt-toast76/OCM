// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import { useComponentsStore } from "../../store/componentsStore";

// spec/10's own small, open kind set (plus x- extension, typed freely below).
const KNOWN_KINDS = [
  "vacuum_ejector",
  "io_link_master",
  "valve_island",
  "sensor",
  "camera",
  "actuator",
  "drive",
  "gripper_body",
  "dispenser",
  "feeder_body",
  "bracket",
  "other",
];

export function ComponentsList() {
  const components = useComponentsStore((s) => s.components);
  const selectedComponentId = useComponentsStore((s) => s.selectedComponentId);
  const loading = useComponentsStore((s) => s.loading);
  const loadComponents = useComponentsStore((s) => s.loadComponents);
  const selectComponent = useComponentsStore((s) => s.selectComponent);
  const createDraft = useComponentsStore((s) => s.createDraft);

  const [newId, setNewId] = useState("");
  const [newKind, setNewKind] = useState(KNOWN_KINDS[0]);

  useEffect(() => {
    void loadComponents();
  }, [loadComponents]);

  return (
    <div className="components-list">
      <h2>Components</h2>
      {components.length === 0 && !loading && <p className="components-list__empty">No components yet.</p>}
      <ul className="components-list__items">
        {components.map((c) => (
          <li key={c.id} className={c.id === selectedComponentId ? "components-list__row components-list__row--selected" : "components-list__row"}>
            <button type="button" className="components-list__name" onClick={() => void selectComponent(c.id)}>
              <span className="components-list__id">{c.id}</span>
              <span className="components-list__meta">
                {c.vendor ?? "—"} · {c.kind ?? "—"}
              </span>
            </button>
            {c.draft && <span className="components-list__badge">draft</span>}
          </li>
        ))}
      </ul>

      <form
        className="components-list__new"
        onSubmit={(e) => {
          e.preventDefault();
          const id = newId.trim();
          if (!id) return;
          void createDraft(id, newKind);
          setNewId("");
        }}
      >
        <input type="text" value={newId} onChange={(e) => setNewId(e.target.value)} placeholder="com.vendor.part.model" aria-label="New component id" />
        <select value={newKind} onChange={(e) => setNewKind(e.target.value)} aria-label="New component kind">
          {KNOWN_KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
        <button type="submit" disabled={!newId.trim()}>
          New draft
        </button>
      </form>
    </div>
  );
}
