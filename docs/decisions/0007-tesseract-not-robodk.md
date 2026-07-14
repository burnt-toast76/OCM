# ADR-0007 — Tesseract + Ruckig. Not RoboDK, not LinuxCNC.

**Status:** Accepted

## Context
We need collision-checked offline programming. RoboDK is the obvious commercial tool.

## Decision
**Tesseract** (ROS-Industrial, Apache-2.0, v1.0) for planning and collision.
**Ruckig** (MIT) for jerk-limited trajectory generation.

## Rationale
- A proprietary tool in the middle of an open platform poisons the model. We cannot ship a
  cell whose programming requires a customer to buy a $4k seat.
- Tesseract is purpose-built for industrial OLP: continuous *and* discrete collision checking,
  OMPL/TrajOpt/Descartes planners, ROS-agnostic core with a self-contained PyPI package —
  **we do not have to swallow the whole ROS stack.**
- **`tesseract_command_language`** is a generic teach-pendant-like motion IR. That is exactly
  the neutral representation to post-process into URScript / TP-LS / PacScript / SPEL+.

## Rejected
- **RoboDK.** Genuinely good, and worth 1–2 *engineering seats* if we were only building
  cells for ourselves (it's a development-time tool, not a runtime — the robot runs native
  code standalone, so it's not per-cell). But it can't be a dependency of an open platform.
- **LinuxCNC / Machinekit.** The obvious tool for gantry motion, and **GPLv2** — would break
  the Apache-2.0 planning chain. See ADR-0001.

## Consequences
- The **`urdf_fragment`** field in the module manifest is the load-bearing design decision:
  `cell.yaml` compiles *directly* into a Tesseract scene graph. Add a module, and the planner
  instantly knows it's there and won't drive through it. **Everything else in the spec is
  convenience; this is the part that makes the platform function.**
- Viewer reuses the existing R3F + Fusion 360 → Blender → GLB asset pipeline.
