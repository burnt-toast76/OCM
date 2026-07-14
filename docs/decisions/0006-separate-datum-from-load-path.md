# ADR-0006 — Separate the load path from the datum

**Status:** Accepted

## Context
"Weld it, then machine it" exists because we try to make one part both stiff *and* precise.

## Decision
Two different parts for two different requirements.

```
┌─────────────────────────────────────┐
│  Datum plate — Mic-6 / ATP-5        │  ← precision lives HERE
│  Flat ~0.005"/ft, stress-relieved   │     ONE part. Bolt-on. Purchased.
│  Carries ocm-base-grid-50           │
├─────────────────────────────────────┤
│  Load structure                     │  ← stiffness lives HERE
│  Laser-cut plate + tube, bolted     │     ±1 mm is FINE. No machining.
└─────────────────────────────────────┘
```

## Consequences
- The frame can be sloppy as long as it's stiff. **The expensive machining step disappears.**
- **The datum plate is the part we sell in the kit** — the one thing a customer genuinely
  can't source or make.
- **It does double duty as the gantry's rail reference.** Two parallel profile rails must be
  parallel to 20–50 µm or the carriages bind — and laser-cut edges (±0.1–0.2 mm, with taper)
  are nowhere near good enough. The datum plate carries the one machined reference edge.
- **Rail alignment needs no machine tools:** master-and-float. Rail 1 against the machined
  edge. Rail 2 on slotted holes — bolt a bridge across one carriage from each rail, run it
  down the length, snug as you go. *The carriages are the alignment gauge.* A torque wrench
  and an afternoon.
