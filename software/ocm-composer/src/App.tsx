// SPDX-License-Identifier: AGPL-3.0-or-later
import { useState } from "react";
import { CellPicker } from "./ui/CellPicker";
import { Sidebar } from "./ui/Sidebar";
import { Inspector } from "./ui/Inspector";
import { Palette } from "./ui/Palette";
import { IssuesPanel } from "./ui/IssuesPanel";
import { ToastHost } from "./ui/ToastHost";
import { ConfirmDialog } from "./ui/ConfirmDialog";
import { SceneCanvas } from "./scene/SceneCanvas";
import { ComponentsPage } from "./ui/components/ComponentsPage";
import { NavMenu } from "./ui/NavMenu";
import type { NavPage } from "./ui/NavMenu";
import { useComposerStore } from "./store/store";
import "./App.css";

type View = "cell" | "components";

// One list, in menu order -- add a page here and it shows up in the
// hamburger menu with no other wiring.
const PAGES: NavPage[] = [
  { id: "cell", label: "Cell" },
  { id: "components", label: "Components" },
];

function App() {
  const cellId = useComposerStore((s) => s.cellId);
  // No router (ADR-0012's minimal-surface house style already does view
  // switching this way for cellId itself) -- top-level pages in a
  // single-user local tool don't need URL-addressable routes to be useful.
  const [view, setView] = useState<View>("cell");

  return (
    <div className="app">
      <header className="app__header">
        <NavMenu pages={PAGES} activePage={view} onSelect={(id) => setView(id as View)} />
        <h1>OCM Composer</h1>
        {view === "cell" && <CellPicker />}
      </header>

      {view === "cell" ? (
        <div className="app__body">
          <aside className="app__left">
            <Sidebar />
            {cellId && <Palette />}
          </aside>

          <main className="app__scene">
            {cellId ? <SceneCanvas /> : <div className="app__placeholder">Select a cell to begin.</div>}
          </main>

          <aside className="app__right">
            <Inspector />
            <IssuesPanel />
          </aside>
        </div>
      ) : (
        <ComponentsPage />
      )}

      <ToastHost />
      <ConfirmDialog />
    </div>
  );
}

export default App;
