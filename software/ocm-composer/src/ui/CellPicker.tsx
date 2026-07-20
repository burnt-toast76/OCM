// SPDX-License-Identifier: AGPL-3.0-or-later
import { useEffect, useState } from "react";
import * as api from "../api/client";
import { ApiTransportError } from "../api/client";
import type { CellSummary } from "../api/types";
import { useComposerStore } from "../store/store";

export function CellPicker() {
  const cellId = useComposerStore((s) => s.cellId);
  const loadCell = useComposerStore((s) => s.loadCell);
  const [cells, setCells] = useState<CellSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .listCells()
      .then((env) => {
        if (cancelled) return;
        if (env.ok) setCells(env.data ?? []);
        else setError(env.refusals[0]?.message ?? "list_cells was refused");
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof ApiTransportError ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="cell-picker">
      <label htmlFor="cell-select">Cell</label>
      <select
        id="cell-select"
        value={cellId ?? ""}
        onChange={(e) => {
          if (e.target.value) void loadCell(e.target.value);
        }}
      >
        <option value="" disabled>
          {cells === null ? "Loading…" : "Select a cell…"}
        </option>
        {cells?.map((c) => (
          <option key={c.cell_id} value={c.cell_id}>
            {c.name} ({c.cell_id})
          </option>
        ))}
      </select>
      {error && <div className="cell-picker__error">{error}</div>}
    </div>
  );
}
