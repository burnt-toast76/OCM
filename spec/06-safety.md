# OCM Spec — Safety v1.0

## The hard boundary

**You cannot open-source a safety controller.** There is no path to certification for a design
anyone can modify. This is not a gap to be filled later; it is a permanent boundary.

## What the manifest does

Declares hazards, required performance level, STO requirement, guarding, and safe state.

## What the manifest does NOT do

**It is not a risk assessment and must never pretend to be.** `cell.yaml` carries a
`verified_by` field that reads:

> `"(human signature required — the tool will not sign this)"`

Keep it that way.

## What the generator does

Exactly one narrow, valuable thing:

> **Refuse to build a cell whose declared safety hardware does not meet the union of its
> modules' declared PL requirements.**

It will not design your safety system. It will stop you from shipping one that doesn't add up.

## Architecture

- Each module declares `sto_required: true`
- That STO lands on a **hardwired circuit through a certified relay** (Pilz PNOZ, Banner, AB
  Guardmaster). **A physical wire, not a network message.**
- FSoE exists. The certified devices are closed and expensive. Not for v1.
- ⚠️ **Z-axis gantry brake** (spring-applied, electrically released) is a safety item, not a
  convenience. Ball screws backdrive — a Z head falls on power loss, under where a human
  reaches in.
