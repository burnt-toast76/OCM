# Architecture Decision Records

One file per decision. Context → Decision → Consequences.

**Read these before proposing a change.** Most "obvious" alternatives were considered and
rejected for reasons that aren't obvious. The reasoning matters more than the conclusion —
if the context changes, the decision should be revisited, and these tell you what the
context was.

| # | Decision | Status |
|---|---|---|
| [0001](0001-licensing.md) | AGPLv3 / CERN-OHL-S / CC BY-SA. **GPLv3, never v2.** | Accepted |
| [0002](0002-ethercat-fieldbus.md) | EtherCAT as the fieldbus | Accepted |
| [0003](0003-distributed-io.md) | I/O lives on the module, not in a central panel | Accepted |
| [0004](0004-packml-mandatory.md) | Every module implements PackML. Rigid. | Accepted |
| [0005](0005-bolted-not-welded-frame.md) | Bolted tab-and-slot frame. **The DXF is the deliverable.** | Accepted |
| [0006](0006-separate-datum-from-load-path.md) | The frame carries load; a ground plate carries precision | Accepted |
| [0007](0007-tesseract-not-robodk.md) | Tesseract + Ruckig. Not RoboDK, not LinuxCNC. | Accepted |
| [0008](0008-gantry-as-reference-motion.md) | The gantry is the flagship; the 6-axis arm is the upgrade | Accepted |
| [0009](0009-spec-the-profile-not-the-part.md) | Spec CiA 402, publish a tested list. Never a part number. | Accepted |
| [0010](0010-generator-before-hardware.md) | Build the generator first. The frame is step 4. | Accepted |
| [0011](0011-mount-grid.md) | Bolt grid: own 50 mm pattern vs. ride 8020? | **OPEN** |
| [0012](0012-api-before-pixels.md) | **API before pixels.** One refusal engine, three clients. | Accepted |
| [0013](0013-generated-hmis.md) | Operator & engineer HMIs are generated from manifests | Accepted |
| [0014](0014-components-vs-modules.md) | Components are transcribed; modules are designed | Accepted |
| [0015](0015-module-connectivity.md) | Module connectivity: nets + links; pins are transcribed | Accepted (Erratum 1) |
| [0016](0016-one-validation-surface.md) | One validation surface: authoring sees what resolution sees | Accepted |
| [0017](0017-context-is-layered.md) | Context is layered — component, module, cell | Accepted |
| [0018](0018-ocm-standard-cellwright-product.md) | OCM is the standard, Cellwright is the product | Accepted |
| [0019](0019-cell-interconnect.md) | Cells interconnect by discrete I/O, not by fieldbus | Accepted (D1 superseded in part by 0034) |
| [0020](0020-carrier-identity.md) | Unit identity travels on the carrier | Accepted (Erratum 1) |
| [0021](0021-record-journal.md) | The journal is the write; the store is declared | Accepted |
| [0022](0022-lifecycle-and-agent-authority.md) | Lifecycle governs write authority; the agent edits manifests only | Accepted |
| [0023](0023-plans-are-verbs.md) | The plan is verbs; conditions belong to modules | Accepted |
| [0024](0024-manifest-authority-vs-command-authority.md) | Manifest authority and command authority are different axes | Accepted |
| [0025](0025-refusal-phases-and-catalogue.md) | One refusal source, three evaluation phases | Accepted |
| [0026](0026-a-port-is-what-a-net-can-name.md) | A port is what a net can name; everything else is a subsystem block | Accepted (Errata 1–2) |
| [0027](0027-collision-geometry-derived-or-checked.md) | Collision geometry is derived from posed components, or authored and checked | Accepted |
| [0028](0028-capabilities-actuate-joints.md) | A capability declares the joints it actuates | Accepted (Erratum 1) |
| [0029](0029-plan-is-the-timeline.md) | The plan is the timeline | Accepted |
| [0031](0031-carriers-locate-themselves.md) | Carriers are passive, pass through, and locate themselves | **Proposed** (part 2 of 3 landed) |
| [0033](0033-manifest-authority-is-enforced-in-copper.md) | Manifest authority is enforced in copper | **Proposed** |
| [0034](0034-safety-internal-to-cell.md) | The safety domain does not cross a cell boundary | **Proposed** |
| [0035](0035-manifests-cite-claims.md) | A manifest cites claims; a claim cites a document | **Proposed** |
| [0036](0036-claims-serving-surface.md) | Claims are served read-only, with provenance on every value | **Proposed** |
| [0037](0037-corrections-under-append-only.md) | Corrections under append-only: retraction is a pure addition | **Proposed** |
| [0038](0038-machine-readable-sources.md) | Machine-readable sources (EDS/GSDML/ESI/IODD): position, kind, record mutability, key namespacing | **Proposed** (Q6, Q10-Q12 open) |

Numbers are allocated by claim, not by write order: a number is claimed the moment an accepted
or proposed ADR forward-references it, and a later ADR takes the next free one instead.
Currently reserved: **0030** (`ocm-viewer`, claimed by ADR-0029) and **0032** (pick and place,
claimed by ADR-0031). The next free number is **0039**.
