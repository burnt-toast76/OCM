// SPDX-License-Identifier: AGPL-3.0-or-later
// Published modules only (drafts aren't resolvable into a cell --
// OCM_DRAFT_MODULE_REFERENCED -- so offering them here would just be a
// guaranteed refusal; the store already filters list_modules() to
// !draft). Drag an item onto the deck to place it (SceneCanvas's drop
// handler does the actual place_instance call).

import { useComposerStore } from "../store/store";

export function Palette() {
  const modules = useComposerStore((s) => s.modules);
  const cellId = useComposerStore((s) => s.cellId);

  if (!cellId) return null;

  return (
    <div className="palette">
      <h2>Palette</h2>
      {modules.length === 0 && <p className="palette__empty">No published modules available.</p>}
      <ul className="palette__list">
        {modules.map((m) => (
          <li
            key={m.id}
            className="palette__item"
            draggable
            onDragStart={(e) => {
              e.dataTransfer.setData("application/x-ocm-module", JSON.stringify({ id: m.id, revision: m.revision }));
              e.dataTransfer.effectAllowed = "copy";
            }}
            title={`Drag onto the deck to place — ${m.id}@${m.revision}`}
          >
            <span className="palette__kind">{m.kind}</span>
            <span className="palette__name">{m.name ?? m.id}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
