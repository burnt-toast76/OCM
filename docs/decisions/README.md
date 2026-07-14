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
