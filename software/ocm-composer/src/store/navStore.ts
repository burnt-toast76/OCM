// SPDX-License-Identifier: AGPL-3.0-or-later
// Which top-level page is showing -- lifted out of App.tsx's own local
// useState into a store specifically so a component nested arbitrarily
// deep (e.g. the Modules page's wiring canvas, linking to "this component
// has no transcribed connectors -- go fix it") can switch pages itself,
// without threading a callback down through every intermediate layer.
// Still no router (ADR-0012's minimal-surface house style): this is a
// page-switch flag, not a URL-addressable route.

import { create } from "zustand";

export type View = "cell" | "components" | "modules";

interface NavState {
  view: View;
  setView: (view: View) => void;
}

export const useNavStore = create<NavState>((set) => ({
  view: "cell",
  setView: (view) => set({ view }),
}));
