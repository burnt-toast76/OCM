// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useModulesStore } from "../../store/modulesStore";

// spec/schema/ocm-module-1.0.schema.json's own kind enum, exactly --
// unlike ComponentsList's KNOWN_KINDS (an open, extensible set), this one
// is closed: additionalProperties/enum on the schema side, so there's no
// "other" escape hatch to offer here.
const MODULE_KINDS = [
  "end_effector",
  "process",
  "feeder",
  "fixture",
  "transport",
  "robot",
  "sensor",
  "safety",
  "base",
];

// create_module_draft takes a bare (id, kind) -- no vendor/part_number
// derivation like components have, so this form is just the id itself,
// typed directly (the human already knows what they're naming this).
export function ModulesList() {
  const modules = useModulesStore((s) => s.modules);
  const selectedModuleId = useModulesStore((s) => s.selectedModuleId);
  const loading = useModulesStore((s) => s.loading);
  const loadModules = useModulesStore((s) => s.loadModules);
  const selectModule = useModulesStore((s) => s.selectModule);
  const createDraft = useModulesStore((s) => s.createDraft);

  const [newId, setNewId] = useState("");
  const [newKind, setNewKind] = useState(MODULE_KINDS[0]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    void loadModules();
  }, [loadModules]);

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault();
    const id = newId.trim();
    if (!id || submitting) return;
    setSubmitting(true);
    try {
      await createDraft(id, newKind);
      if (useModulesStore.getState().selectedModuleId !== id) return;
      setNewId("");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modules-list">
      <h2>Modules</h2>
      {modules.length === 0 && !loading && <p className="modules-list__empty">No modules yet.</p>}
      <ul className="modules-list__items">
        {modules.map((m) => (
          <li key={m.id} className={m.id === selectedModuleId ? "modules-list__row modules-list__row--selected" : "modules-list__row"}>
            <button type="button" className="modules-list__name" onClick={() => void selectModule(m.id)}>
              <span className="modules-list__id">{m.id}</span>
              <span className="modules-list__meta">{m.kind}</span>
            </button>
            {m.draft && <span className="modules-list__badge">draft</span>}
          </li>
        ))}
      </ul>

      <form className="modules-list__new" onSubmit={(e) => void handleCreate(e)}>
        <input
          type="text"
          value={newId}
          onChange={(e) => setNewId(e.target.value)}
          placeholder="com.vendor.product-line"
          aria-label="New module id"
        />
        <select value={newKind} onChange={(e) => setNewKind(e.target.value)} aria-label="New module kind">
          {MODULE_KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
        <button type="submit" disabled={!newId.trim() || submitting}>
          New draft
        </button>
      </form>
    </div>
  );
}
