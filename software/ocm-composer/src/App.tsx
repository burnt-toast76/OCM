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
import { useComposerStore } from "./store/store";
import "./App.css";

type View = "cell" | "components";

function App() {
  const cellId = useComposerStore((s) => s.cellId);
  // No router (ADR-0012's minimal-surface house style already does view
  // switching this way for cellId itself) -- two top-level pages in a
  // single-user local tool don't need URL-addressable routes to be useful.
  const [view, setView] = useState<View>("cell");

  return (
    <div className="app">
      <header className="app__header">
        <h1>OCM Composer</h1>
        <nav className="app__nav">
          <button type="button" className={view === "cell" ? "app__nav-item app__nav-item--active" : "app__nav-item"} onClick={() => setView("cell")}>
            Cell
          </button>
          <button
            type="button"
            className={view === "components" ? "app__nav-item app__nav-item--active" : "app__nav-item"}
            onClick={() => setView("components")}
          >
            Components
          </button>
        </nav>
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
