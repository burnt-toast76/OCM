// SPDX-License-Identifier: AGPL-3.0-or-later
import { CellPicker } from "./ui/CellPicker";
import { Sidebar } from "./ui/Sidebar";
import { Inspector } from "./ui/Inspector";
import { Palette } from "./ui/Palette";
import { IssuesPanel } from "./ui/IssuesPanel";
import { ToastHost } from "./ui/ToastHost";
import { ConfirmDialog } from "./ui/ConfirmDialog";
import { SceneCanvas } from "./scene/SceneCanvas";
import { useComposerStore } from "./store/store";
import "./App.css";

function App() {
  const cellId = useComposerStore((s) => s.cellId);

  return (
    <div className="app">
      <header className="app__header">
        <h1>OCM Composer</h1>
        <CellPicker />
      </header>

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

      <ToastHost />
      <ConfirmDialog />
    </div>
  );
}

export default App;
