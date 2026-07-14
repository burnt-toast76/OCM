# ADR-0001 — Licensing

**Status:** Accepted

## Context
We want three fulfillment tiers: customer builds it themselves, customer buys a kit, or we
build it complete. That requires the design to be genuinely open. We also want improvements
to flow back, and we don't want a competitor closing a fork.

## Decision
- `software/` → **AGPL-3.0**
- `hardware/` → **CERN-OHL-S v2**
- `spec/`, `modules/`, `cells/`, `docs/` → **CC BY-SA 4.0**

**GPLv3, never GPLv2.**

## Consequences
- ⚠️ Apache-2.0 (Tesseract, ROS 2, TrajOpt) is compatible with GPLv3 but **NOT GPLv2**. A
  GPLv2 choice would leave us with no motion planner. This is the single most expensive
  mistake available to us and it's invisible until it's too late.
- ⚠️ **IgH EtherCAT Master and LinuxCNC are both GPLv2.** Both are the "obvious" tool for
  their job. Both are traps. Use SOEM 2.0 (GPLv3) and Ruckig (MIT).
- AGPL (not plain GPL) because our IDE will be web-served. Plain GPLv3 would let a
  competitor host it as SaaS and contribute nothing.
- GPL is wrong for hardware — it's a software copyright license; it covers the CAD files but
  not the manufactured object, and grants no patents. CERN-OHL-S was written for this.
- A customer building for internal use isn't distributing, so **they owe nothing.** The
  DIY tier works as advertised.
- We hold copyright, so commercial dual-licensing stays available (MySQL/Qt model).
