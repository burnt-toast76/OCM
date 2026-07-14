# OCM Spec — State Machine v1.0

**PackML (ISA-TR88.00.02). Mandatory.** A module that doesn't implement it is not an OCM
module. See [ADR-0004](../docs/decisions/0004-packml-mandatory.md).

This is the one rigid part of the spec. Keep it rigid:

- The cell coordinator's logic is written **once**, not per-module
- An integrator who has never seen OCM already knows how our modules behave
- The agent has a fixed, small control vocabulary — it never invents a handshake

## `abort_safe` must be declared honestly

A screwdriver stopped mid-drive leaves a half-seated fastener a human must clear. A half-laid
adhesive bead cannot be resumed — the part is **scrap** and must be routed to reject, not back
into flow.

**Encoding this honestly is more useful than pretending recovery is possible.**
