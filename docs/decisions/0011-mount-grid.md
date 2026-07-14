# ADR-0011 — The module mount grid

**Status:** 🔴 **OPEN — this is the Step 0 decision that is still unmade**

## Context
Every module bolts to the base on a standard pattern. `ocm-base-grid-50` is a placeholder in
the schema. This must be frozen before anything else, because everything hangs off it.

## The choice

**Option A — Define our own 50 mm grid.**
- Clean, ours, sized to our modules
- ⚠️ It's a commitment. Every module, forever.
- No existing ecosystem

**Option B — Ride 8020 / item's existing T-slot pattern.**
- **Free adoption.** Anyone with extrusion in the shop can mount an OCM module today.
- Enormous existing accessory ecosystem
- ⚠️ Inherits a pattern we didn't design and can't change
- Note: ADR-0005 rejects 8020 as *structure*. Using its **hole pattern** as an interface
  standard is a different question and is not inconsistent.

**Option C — Ride the welding/fixture table grid** (16 mm or 28 mm hole, 50/100 mm pitch —
Siegmund/Demmeler style).
- Already a de facto standard in fabrication
- Commodity ground plates already exist in this pattern — **which is the part we planned to
  sell in the kit anyway** (ADR-0006)
- Clamping ecosystem comes free

## Not yet decided
This is strategic, not technical. It's a question about **adoption**, and it deserves more
thought than a default.
