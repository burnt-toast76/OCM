// SPDX-License-Identifier: AGPL-3.0-or-later
// Live validate_component/validate_module refusals as a task list (spec/10:
// "the completion list"). Publish is enabled only once the list is empty --
// the button is a UX nicety, not enforcement; publish_component/
// publish_module gate on validity itself regardless of what this panel shows.
//
// Takes checklist/canPublish/onPublish/fieldKeyOf as props (same
// generalization AttachmentsList/ConnectorSymbols went through) so the
// Modules page's own wiring canvas can reuse this exact component for
// validate_module's connectivity refusals -- which have a different path
// shape than validate_component's (a module path looks like
// "modules['id'].nets.electrical['NET_ID']", not "electrical.supplies[0].
// current_nominal_a"), hence fieldKeyOf is pluggable rather than the
// hardcoded refusalFieldKey. The Components page passes none of the new
// props and renders byte-identical to before.

import { useState } from "react";
import type { Refusal } from "../../api/types";
import { refusalFieldKey } from "./refusalField";

function focusField(fieldKey: string | null): void {
  if (!fieldKey) return;
  const el = document.querySelector<HTMLElement>(`[data-field="${CSS.escape(fieldKey)}"]`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("component-form__section--focused");
  window.setTimeout(() => el.classList.remove("component-form__section--focused"), 1500);
}

export interface ChecklistPanelProps {
  checklist: Refusal[];
  canPublish: boolean;
  onPublish: (revision: string) => void;
  /** Defaults to refusalFieldKey (component-schema paths). The wiring canvas passes its own module-path extractor. */
  fieldKeyOf?: (refusal: Refusal) => string | null;
}

export function ChecklistPanel({ checklist, canPublish, onPublish, fieldKeyOf = refusalFieldKey }: ChecklistPanelProps) {
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
              <button type="button" className="checklist-panel__item" onClick={() => focusField(fieldKeyOf(r))}>
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
        <button type="button" disabled={!clean || !canPublish} onClick={() => onPublish(revision)}>
          Publish
        </button>
      </div>
    </div>
  );
}
