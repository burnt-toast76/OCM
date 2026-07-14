# Tested Servo Drives

**Nothing here has been tested yet.** This file is the template and the discipline.

The spec states a *requirement* ([ADR-0009](../docs/decisions/0009-spec-the-profile-not-the-part.md)).
This file records what we have **actually run**. It is the single most valuable document this
project can produce for its community, and no vendor will ever write it.

## Requirement

| | |
|---|---|
| Profile | CiA 402 over EtherCAT (CoE), **csp mode mandatory** |
| Sync | Distributed Clocks, ≤ 2 µs jitter |
| Cycle | 1 ms or better |
| Encoder | Multi-turn absolute |
| Safety | **Certified dual-channel STO**, PLd / SIL2 minimum |
| Brake | Brake output on the Z drive, spring-applied |
| ESI | Valid — **PDO map verified against firmware, not the datasheet** |

## Candidates

| Drive | Profile | STO | Absolute | DC jitter (measured) | ESI verified | Status |
|---|---|---|---|---|---|---|
| Leadshine **EL8** + ELM2 | CiA 402 / CoE | **SIL3** | 23-bit multi-turn | — | — | ⬜ untested |
| Leadshine EL7-EC + ELM2 | CiA 402 / CoE | yes | 23-bit multi-turn | — | — | ⬜ untested |
| Inovance SV660N | CiA 402 / CoE | ? | ? | — | — | ⬜ untested |
| LS Electric iX7NH | CiA 402 / CoE | ? | ? | — | — | ⬜ untested |
| Teknic ClearPath-EtherCAT | CiA 402 | ? | ? | — | — | ⬜ untested |
| Delta ASDA-B3/A3 | CiA 402 / CoE | yes | yes | — | — | ⬜ untested |

## Leadshine ordering traps ⚠️

Three ways to get this wrong:

1. **The absolute encoder cable is a different part number.**
   Incremental `CABLE-BMH*M*-114-TS` · Absolute `CABLE-BMAH*M*-124-TS`. Order the wrong one
   with an absolute motor and you've bought a homing sequence.
2. **You need the `ER14505` battery kit.** Multi-turn absolute is **battery-backed**. The
   "no homing, ever" promise depends on a AA-size lithium cell that dies in 2–5 years — after
   which the turn count is lost and the axis must be re-referenced.
   → The drive reports battery voltage over CoE. **Read it, alarm early, and put it in the
   manifest's `maintenance.wear_items`.** It's a consumable, same as a screwdriver bit.
3. **Order the flex cable variant.** `CABLE-RZ*M*H (V1.1)` is **fixed**;
   `CABLE-RZ*M*-H (V2.0)` is **flexible**. Fixed cable in a drag chain will fail.

**Spec EL8, not EL7** — the SIL3-certified STO is a certification the safety architecture
actually needs, for ~$40/axis.

## Sourcing (US)
- Leadshine USA warehouse, California — drop-ships
- **Automation Technologies, Streamwood IL** — stocks EL7/ELM2 EtherCAT kits (~2.5 h from Moline)
- Centroid (PA) — sells pre-tested EL7 + ELM2-absolute + cable packages. **Their tested BOM is
  free engineering** even if we don't buy from them.

Budget: EtherCAT servos carry a **$50–150/axis premium** over step/dir. On a 5-axis gantry
that's a few hundred dollars for the entire fieldbus architecture. Best money in the machine.

## The accuracy reality check

23 bits = 8.4M counts/rev. **You will not get that** — real linearity gives ~100k counts/rev.
And it doesn't matter, because **the ball screw dominates**:

| Screw grade | Cyclic error / rev |
|---|---|
| **C7** (rolled, the cheap default) | up to **35 µm** |
| C5 | 8 µm |
| C3 | 6 µm |

Spec it as a tier and publish the honest number: **C7 for the standard cell (±35 µm — fine for
pick/place/screw/dispense), C5 for precision.** Otherwise customers buy a "23-bit servo" and
wonder why the machine is only good to a thousandth.
