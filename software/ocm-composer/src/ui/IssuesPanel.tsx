// SPDX-License-Identifier: AGPL-3.0-or-later
import { useComposerStore } from "../store/store";
import { instanceFromRefusalPath } from "./refusalPath";

export function IssuesPanel() {
  const refusals = useComposerStore((s) => s.refusals);
  const focusInstance = useComposerStore((s) => s.focusInstance);

  if (refusals.length === 0) {
    return (
      <div className="issues-panel issues-panel--clean">
        <h2>Issues</h2>
        <p>No open refusals.</p>
      </div>
    );
  }

  return (
    <div className="issues-panel">
      <h2>Issues ({refusals.length})</h2>
      <ul className="issues-panel__list">
        {refusals.map((r, i) => {
          const instance = instanceFromRefusalPath(r.path);
          return (
            <li key={i} className="issues-panel__row">
              <button
                type="button"
                className="issues-panel__item"
                disabled={!instance}
                onClick={() => instance && focusInstance(instance)}
                title={instance ? `Focus ${instance}` : undefined}
              >
                <span className="issues-panel__code">{r.code}</span>
                <span className="issues-panel__message">{r.message}</span>
                {r.hint && <span className="issues-panel__hint">{r.hint}</span>}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
