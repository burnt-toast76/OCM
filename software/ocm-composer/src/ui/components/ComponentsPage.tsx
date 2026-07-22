// SPDX-License-Identifier: AGPL-3.0-or-later
import { useComponentsStore } from "../../store/componentsStore";
import { ComponentsList } from "./ComponentsList";
import { ComponentDetail } from "./ComponentDetail";

export function ComponentsPage() {
  const error = useComponentsStore((s) => s.error);
  const clearError = useComponentsStore((s) => s.clearError);

  return (
    <div className="components-page">
      {error && (
        <div className="components-page__error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={clearError} aria-label="Dismiss">
            ×
          </button>
        </div>
      )}
      <aside className="components-page__list">
        <ComponentsList />
      </aside>
      <main className="components-page__detail">
        <ComponentDetail />
      </main>
    </div>
  );
}
