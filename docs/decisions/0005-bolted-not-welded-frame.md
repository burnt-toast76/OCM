# ADR-0005 — Bolted tab-and-slot frame, not welded

**Status:** Accepted

## Context
8020 with T-nut joints is too compliant. The instinctive fix is a welded, stress-relieved,
machined steel weldment.

## Decision
**Laser-cut steel plate + structural tube, tab-and-slot interlocked, bolted.**

## Rationale

**The problem with 8020 is the joint, not the aluminum.** A T-nut in a slot is a *friction*
joint with a tiny footprint and modest preload. It micro-slips and relaxes. Joint stiffness
is orders of magnitude below member stiffness. But "friction T-nut" ≠ "bolted" — conflating
them is what pushes people to weld when they don't need to.

**A properly designed bolted joint is as stiff as a weld.** Three conditions (this is how
large machine tools are assembled):
1. Flat, full-contact faying surfaces
2. Preload high enough that the joint never slips — friction-grip, not bearing
3. **Shear taken by dowels or interlocking geometry**, not bolt shanks in clearance holes

**A welded frame destroys the business model.** It needs a weld fixture, stress relief, and
a planer mill to machine the datum after it moves. That's a machine shop, not a customer.
It can't ship flat. **It collapses three tiers into one.**

> If the open design can't be built with commodity processes, then "customers can make it
> themselves" is marketing copy, not a fact.

## The strategic payoff
**The DXF is the deliverable.** A customer anywhere downloads the files and takes them to any
local laser shop. Laser cutting is a global commodity. We cannot ship a 400 lb weldment to
that person — we can email them a file.

## Consequences
- The **real** design criterion is not "stout," it's **first natural frequency** — a soft base
  means the arm rings after every fast move and you dwell before precision work. That dwell is
  cycle time, forever. Static deflection under process load is nearly a non-issue.
- **Acceptance test:** robot mounting face deflects **< 35 µm under 100 N lateral**
  (≈ 3000 N/mm ≈ 60 Hz first mode with a UR5e-class arm). Verifiable with a dial indicator
  and a luggage scale.
- **Measure it, don't argue about it.** Modal hammer test, publish the number and the
  procedure. Essentially nobody in open hardware does this. → `reference/measurements/`
- Bolted joints have *better damping* than welds (microslip dissipates energy).
- The "we build it complete" tier can still be welded. We give up nothing.
- Optional epoxy-granite fill for ~10× damping. Probably unnecessary for assembly (damping
  matters for *cutting* chatter). Offer it; don't require it.
- Welded is still right for: kN-level press/stake forces, or spans beyond ~2 m.

## Prior art
The welding-table industry already ships flat-pack, laser-cut, tab-and-slot table kits that
customers assemble themselves (CertiFlat and similar). The interlocking geometry *is* the
fixture.
