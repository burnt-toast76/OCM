// SPDX-License-Identifier: AGPL-3.0-or-later
import { useComposerStore } from "../store/store";

export function Sidebar() {
  const scene = useComposerStore((s) => s.scene);
  const selectedInstance = useComposerStore((s) => s.selectedInstance);
  const hiddenInstances = useComposerStore((s) => s.hiddenInstances);
  const selectInstance = useComposerStore((s) => s.selectInstance);
  const toggleVisibility = useComposerStore((s) => s.toggleVisibility);
  const deleteInstance = useComposerStore((s) => s.deleteInstance);

  if (!scene) {
    return (
      <div className="sidebar">
        <h2>Instances</h2>
        <p className="sidebar__empty">No cell loaded.</p>
      </div>
    );
  }

  return (
    <div className="sidebar">
      <h2>Instances</h2>
      <ul className="sidebar__list">
        {scene.instances.map((instance) => {
          const hidden = hiddenInstances.has(instance);
          return (
            <li key={instance} className={instance === selectedInstance ? "sidebar__row sidebar__row--selected" : "sidebar__row"}>
              <button
                type="button"
                className="sidebar__visibility"
                title={hidden ? "Show" : "Hide"}
                aria-pressed={!hidden}
                onClick={() => toggleVisibility(instance)}
              >
                {hidden ? "○" : "●"}
              </button>
              <button type="button" className="sidebar__name" onClick={() => void selectInstance(instance)}>
                <span className="sidebar__swatch" style={{ background: scene.colors[instance] ?? "#888" }} />
                {instance}
              </button>
              <button
                type="button"
                className="sidebar__delete"
                title={`Delete ${instance}`}
                onClick={() => deleteInstance(instance)}
              >
                ×
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
