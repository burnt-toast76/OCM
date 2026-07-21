// SPDX-License-Identifier: AGPL-3.0-or-later
import { ComponentsList } from "./ComponentsList";
import { ComponentDetail } from "./ComponentDetail";

export function ComponentsPage() {
  return (
    <div className="components-page">
      <aside className="components-page__list">
        <ComponentsList />
      </aside>
      <main className="components-page__detail">
        <ComponentDetail />
      </main>
    </div>
  );
}
