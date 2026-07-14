# ADR-0010 — Build the generator before the hardware

**Status:** Accepted

## Context
The instinct is to start with mechanical design: frame, then module mounting, then drive
mounting, then HMI placement.

## Decision
**No.** The generator comes first. Mechanical design is step 4.

## Rationale
We already know how to build a frame. The probability we fail at it is near zero — **so it
carries no information.** Months of mechanical design would tell us nothing we didn't know,
cost real money in steel and servos, and leave the actual risk untouched.

The question that decides whether this project is real:

> Can the generator go from `cell.yaml` + `plan.yaml` to a collision-checked robot program
> and a PLC sequence, with **no human writing waypoints**?

**That is testable on a laptop in two or three weeks with zero hardware.** If false, we found
out cheap. If true, we have the demo that makes everything else credible — and *the working
generator is itself the marketing artifact*. A video of a cell being generated from a YAML
file, collision-checked, with the tool refusing an out-of-spec torque, gets attention that
"here's my open frame design" never will.

## The validation loop that costs nothing
**Dogfood on a job we're already paid for.** The next custom cell we're contracted for: write
OCM manifests for the modules we're already specifying, run the generator, compare its output
to the logic we were going to hand-write.

Zero speculative time. Real modules, real part, real deadline, real customer. **Every gap the
schema can't express is a finding.** A toy demo cell built to convince ourselves proves nothing.

## Consequences
- **Step 0 is still needed:** freeze the module interface spec (bolt grid + pinout + bus).
  But that's *a page of decisions, not a CAD model.* An afternoon.
- **The agent layer comes LAST.** It's a thin tool-calling wrapper over a generator that
  already works. Building it first is building a UI for nothing.
- **If HMI placement ever feels urgent, we've drifted** — from building a standard to
  building a cell. Those are different projects.
