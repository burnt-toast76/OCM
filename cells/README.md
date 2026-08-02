# cells

This is the **cell** layer — the third of OCM's three context layers (ADR-0017): which
modules are present and how they connect.

Real cell definitions. **Including the ones we build for paying customers** — that is the
validation loop (ROADMAP step 2).

```
<cell-id>/
  cell.yaml       <- composition: which modules, where, wired how
  plan.yaml       <- the assembly sequence
  cal/            <- per-cell calibration (camera extrinsics etc)
  generated/      <- COMMIT THIS. The diff against hand-written logic is the proof.
```
