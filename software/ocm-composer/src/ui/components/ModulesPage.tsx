// SPDX-License-Identifier: AGPL-3.0-or-later
import { useModulesStore } from "../../store/modulesStore";
import { ModulesList } from "./ModulesList";
import { ModuleDetail } from "./ModuleDetail";

export function ModulesPage() {
  const error = useModulesStore((s) => s.error);
  const clearError = useModulesStore((s) => s.clearError);

  return (
    <div className="modules-page">
      {error && (
        <div className="modules-page__error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={clearError} aria-label="Dismiss">
            ×
          </button>
        </div>
      )}
      <aside className="modules-page__list">
        <ModulesList />
      </aside>
      <main className="modules-page__detail">
        <ModuleDetail />
      </main>
    </div>
  );
}
