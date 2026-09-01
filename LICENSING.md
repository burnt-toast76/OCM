# Licensing

Three licenses. Three directories. This is **structural** — put a file in the wrong
directory and its license becomes ambiguous.

| Directory | License | Why |
|---|---|---|
| `software/` | **AGPL-3.0** | Strongly reciprocal. Closes the SaaS loophole — a competitor can't run our generator as a hosted service without contributing back. |
| `hardware/` | **CERN-OHL-S v2** | GPL doesn't work for hardware: it's a software copyright license, it covers CAD *files* but says nothing coherent about the manufactured object, and it grants no patent rights. CERN-OHL-S is the strongly-reciprocal hardware license, purpose-built. |
| `spec/`, `modules/`, `cells/`, `reference/`, `docs/` | **CC BY-SA 4.0** | The standard must be freely implementable by anyone, including commercially, as long as derivatives stay open. |
| `claims/` | **CC BY-SA 4.0** | The registry's compilation stays open and share-alike; the facts inside it are facts — see `claims/README.md` for the scope. |

---

## ⚠️ GPLv3. Never GPLv2.

**Apache-2.0 is one-way compatible with GPLv3 and INCOMPATIBLE with GPLv2** (patent-clause
conflict). Our entire planning stack is Apache-2.0:

- **Tesseract** (ROS-Industrial) — Apache-2.0
- **TrajOpt, Descartes, OMPL, MoveIt, ROS 2** — Apache-2.0 / BSD
- **Ruckig** — MIT

If we license GPLv2, we cannot legally link any of it and the project has no planner.

### Dependencies to watch

| Dependency | License | Status |
|---|---|---|
| Tesseract, OMPL, TrajOpt, Descartes | Apache-2.0 / BSD | ✅ Safe under GPLv3 |
| Ruckig | MIT | ✅ Safe |
| **SOEM 2.0** (EtherCAT master) | **GPLv3** or commercial | ✅ Safe — *SOEM 1.x was GPLv2. Use 2.0.* |
| **IgH EtherCAT Master** | GPLv**2** | ❌ **DO NOT USE.** Breaks the chain. |
| **LinuxCNC / Machinekit** | GPLv**2** | ❌ **DO NOT USE.** The obvious tool for gantry motion, and it's the trap. Use Ruckig. |
| **Beremiz IDE** | GPL | ⚠️ Keep at a **process/file boundary** (PLCopen XML + MatIEC CLI). Do not link. |
| Beremiz runtime | LGPL | ✅ Safe |

**Rule:** before adding any dependency, check its license against this table. A GPLv2
dependency is not a nuisance — it is a hard stop that silently poisons the whole toolchain.

## Why reciprocal licensing supports the business model

It looks restrictive. It isn't:

- **Customer builds a cell for their own use** → no distribution → **they owe nothing.** The
  "build it yourself" tier works exactly as advertised.
- **Competitor sells derived cells** → must publish their improvements. That's the point.
- **We hold the copyright** → we can always dual-license commercially to someone who wants a
  proprietary fork. (The MySQL/Qt play. It's real revenue.)

The open design drives demand for the assembled version. That's Prusa's model, and it works
*because* the design is open, not despite it.
