# ADR-0009 — Spec the profile, publish a tested list. Never a part number.

**Status:** Accepted

## Context
A customer in Poland can't easily get a Leadshine. A customer in Ohio can't easily get an
Inovance. If the open BOM names a part, the design is un-buildable for half the world.

## Decision
The spec states an **interface requirement**. A separate, living document lists what we have
**actually tested**.

```
Drive requirement (OCM v1)
  Profile   CiA 402 over EtherCAT (CoE), csp mode mandatory
  Sync      Distributed Clocks, <= 2 us jitter
  Cycle     1 ms or better
  Encoder   Multi-turn absolute
  Safety    Certified dual-channel STO, PLd/SIL2 minimum
  Brake     Brake output on the Z drive, spring-applied
  ESI       Valid, PDO map verified against firmware
```

→ `reference/drives-tested.md`

## Rationale
This is the same principle as the module manifest: **declare the interface, not the
implementation.** It's why an off-the-shelf Beckhoff I/O block and an open LAN9252 board can
serve the same manifest. Optionality *is* the abstraction working.

## The three things that actually separate a good drive from a cheap one
1. **DC sync jitter.** Everyone claims DC. Poor jitter racks a dual-drive gantry
   cycle-to-cycle. **Ask for the spec in writing.**
2. **STO.** Some budget drives have none; some have an uncertified single-channel input
   *labelled* STO that satisfies nothing. Without real STO you must drop motor power with a
   contactor. *Check the specific model, not the family.*
3. **ESI quality.** Cheap drives ship broken PDO maps. Since the whole toolchain generates
   from the ESI, a bad ESI is a hard stop. **Load it into SOEM and verify against firmware
   before adding anything to the tested list.**

## Prior art
Centroid ships their Hickory EtherCAT controller with exactly this: a curated tested list
(Leadshine EL7/EL8, Inovance SV660N, Teknic ClearPath-EtherCAT, LS Electric iX7NH) and an
explicit "no guarantee outside this list; we welcome testing others." That's the right posture.
