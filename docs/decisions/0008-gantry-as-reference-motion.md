# ADR-0008 — The gantry is the flagship, not the fallback

**Status:** Accepted

## Context
The reflex is to treat the 6-axis arm as the primary motion system and the gantry as a cheap
alternative.

## Decision
**Invert it.** The gantry is the default. The 6-axis arm is the upgrade you buy for dexterity.

## Rationale
**You cannot open-source a UR5e. You can absolutely open-source a gantry.**

For a 6-axis arm the toolchain must bow to a vendor: a post-processor, a robot language, a
controller we don't own, and paid options just to talk to it. For a gantry, none of that
exists — the kinematics are the identity function. No IK, no singularities, no joint limits,
no vendor language.

```
Tesseract (Apache-2.0) → collision-checked Cartesian waypoints
Ruckig (MIT)           → jerk-limited trajectory
CiA 402 csp            → open ETG profile
SOEM (GPLv3)           → commodity servo drives
```

**Permissively licensed end to end. No robot vendor. No per-cell license.** And it covers a
large fraction of real assembly work.

## Design decisions
- **Moving-bridge portal**, not cantilever (Abbe error grows with Y extension).
- **Dual-drive X** — one motor per side rail. Past ~600 mm span, single-side drive racks the
  bridge. Coupling is done by *our controller* (same csp setpoint to both), **not** by a
  vendor's built-in gantry mode — that would fragment the tested-drive list.
- **Add theta.** XYZ + rotation = a Cartesian SCARA. XYZ alone can't orient a non-round part.
- **Ball screws are fine to ~1 m and fall apart past ~1.2 m** (whip). Beyond that: rack &
  pinion. A 16 mm screw at 500 mm gives ~1280 mm/s; the same screw at 1.5 m gives ~142 mm/s.
- ⚠️ **The Z motor MUST have a spring-applied holding brake.** Ball screws backdrive freely —
  a Z head *falls* on power loss, directly under where a human reaches in. Fail-safe by
  construction. This is a safety item, not an option.
- **Absolute encoders → no homing sequence, ever.** Plug-and-produce applied to motion.

## Drive placement
Cabinet drives for the **stationary X motors** (free — no flex). But Y/Z/theta ride the
gantry, so cabinet drives put ~36–42 flexing conductors in the drag chain — **the exact
failure mode EtherCAT was supposed to eliminate, reintroduced through the motors.**

Options: (a) chainflex-rated cable + separated chain compartments + 360° shield termination,
or (b) **integrated servos on the moving axes** — then the chain carries one EtherCAT cable,
DC bus, and STO. Six conductors instead of forty.

## The accuracy reality check
23-bit encoders are marketing. Real linearity gives ~100k counts/rev, and **the ball screw
grade dominates anyway**: C7 (the cheap default) has up to **35 µm cyclic error per rev**;
C5 is 8 µm; C3 is 6 µm.

**Spec it as a tier and publish the honest number:** C7 for the standard cell (±35 µm — fine
for pick/place/screw/dispense), C5 for the precision option. Otherwise customers buy a
"23-bit servo" and wonder why the machine is only good to a thousandth.
