# ADR-0003 — I/O lives on the module

**Status:** Accepted

## Context
If a module's I/O terminates in a central rack, then "adding a module" means pulling wires
back to the panel, finding spare points, re-terminating, and rebuilding the tag list. That
*is* the 400-hour custom-cell problem.

## Decision
**Every module carries its own fieldbus node.** One bus cable in, one out. One power cable
in, one out. That is the entire electrical interface.

## Consequences
- **Most "digital I/O" disappears.** Valve outputs live on the module's valve island. The
  vacuum switch is integral to the ejector. Smart modules report over EtherCAT process data.
  A typical module needs **2–8 discrete points**, not 32.
- **The IO-Link master IS the DI/DO block.** Each port does IO-Link *or* plain digital in
  *or* digital out, plus a second discrete point on Pin 2. An 8-port master = 8 smart
  devices or 16 discrete points, decided in config. **We do not buy separate DI and DO cards.**
- **IP67 box modules bolted to the module, not DIN rail in a panel.** A customer assembling a
  kit plugs M12 cordsets together. There are no terminals to land a wire on wrong. This is
  the difference between "anyone can build this" and "you need a panel shop."
- **Per-channel diagnostics is the support strategy.** When a customer's cell is down at 2 AM
  and we are not there, the module must report *wire break / short / overload, by channel* —
  which maps to `fault_code` in the manifest. For an open platform, self-diagnosing I/O is
  how we survive being absent. Pay for it.
- **Pays off hardest on the gantry.** The drag chain carries one bus cable, not twenty
  conductors. Drag-chain wire fatigue is a top cause of gantry downtime.
