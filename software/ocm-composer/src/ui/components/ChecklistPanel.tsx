// SPDX-License-Identifier: AGPL-3.0-or-later
// Live validate_component refusals as a task list (spec/10: "the
// completion list"). Publish is enabled only once the list is empty --
// the button is a UX nicety, not enforcement; publish_component gates on
// validity itself regardless of what this panel shows.

import { useState } from "react";
import { useComponentsStore } from "../../store/componentsStore";
import { refusalFieldKey } from "./refusalField";

function focusField(fieldKey: string | null): void {
  if (!fieldKey) return;
  const el = document.querySelector<HTMLElement>(`[data-field="${CSS.escape(fieldKey)}"]`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("component-form__section--focused");
  window.setTimeout(() => el.classList.remove("component-form__section--focused"), 1500);
}

export function ChecklistPanel() {
  const checklist = useComponentsStore((s) => s.checklist);
  const detail = useComponentsStore((s) => s.detail);
  const publish = useComponentsStore((s) => s.publish);
  const [revision, setRevision] = useState("1.0.0");

  const clean = checklist.length === 0;

  return (
    <div className="checklist-panel">
      <h2>Completion checklist</h2>
      {clean ? (
        <p className="checklist-panel__clean">Nothing outstanding -- ready to publish.</p>
      ) : (
        <ul className="checklist-panel__list">
          {checklist.map((r, i) => (
            <li key={i}>
              <button type="button" className="checklist-panel__item" onClick={() => focusField(refusalFieldKey(r))}>
                <span className="checklist-panel__code">{r.code}</span>
                <span className="checklist-panel__message">{r.message}</span>
                {r.hint && <span className="checklist-panel__hint">{r.hint}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="checklist-panel__publish">
        <input
          type="text"
          value={revision}
          onChange={(e) => setRevision(e.target.value)}
          placeholder="1.0.0"
          disabled={!clean}
          aria-label="Publish revision"
        />
        <button type="button" disabled={!clean || !detail} onClick={() => void publish(revision)}>
          Publish
        </button>
      </div>
    </div>
  );
}
