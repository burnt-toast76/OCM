// SPDX-License-Identifier: AGPL-3.0-or-later
import { useComposerStore } from "../store/store";

export function Inspector() {
  const selectedInstance = useComposerStore((s) => s.selectedInstance);
  const inspector = useComposerStore((s) => s.inspector);

  if (!selectedInstance) {
    return (
      <div className="inspector">
        <h2>Inspector</h2>
        <p className="inspector__empty">Click an instance to inspect it.</p>
      </div>
    );
  }

  if (!inspector) {
    return (
      <div className="inspector">
        <h2>Inspector</h2>
        <p className="inspector__empty">Loading {selectedInstance}…</p>
      </div>
    );
  }

  const { manifest } = inspector;

  return (
    <div className="inspector">
      <h2>{selectedInstance}</h2>
      <dl className="inspector__facts">
        <dt>Module</dt>
        <dd>{inspector.id}</dd>
        <dt>Revision</dt>
        <dd>
          {inspector.revision} {inspector.draft && <span className="inspector__badge">draft</span>}
        </dd>
        <dt>Kind</dt>
        <dd>{manifest.kind}</dd>
        <dt>Mount</dt>
        <dd>{manifest.mechanical?.mount?.interface ?? "—"}</dd>
      </dl>

      <h3>Capabilities</h3>
      {manifest.capabilities && manifest.capabilities.length > 0 ? (
        <ul className="inspector__capabilities">
          {manifest.capabilities.map((cap) => (
            <li key={cap.name}>
              <strong>{cap.name}</strong>
              <p>{cap.summary}</p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="inspector__empty">No capabilities declared.</p>
      )}
    </div>
  );
}
