# ADR-0002 — EtherCAT as the fieldbus

**Status:** Accepted

## Context
Modules must be hot-composable: add one, and the tag list, the collision scene, and the PLC
sequence regenerate with no human configuration.

## Decision
**EtherCAT.** IO-Link beneath it for sensors and simple actuators.

## Rationale (in order of importance to *this* project)
1. **Hot Connect.** Slave groups can be added/removed at runtime. Plug-and-produce is *in
   the spec* — no other mainstream fieldbus offers this.
2. **Position addressing.** `ethercat_position: 4` in `cell.yaml` maps 1:1 to physical
   position. No DIP switches, no IP assignment.
3. **ESI files are machine-readable XML.** The tag list generates from them. Zero
   transcription. SOEM 2.0's ENI parser closes the design-time → runtime gap.
4. **It's the only open-hardware-friendly industrial fieldbus.** ETG membership and vendor
   IDs are free. EtherNet/IP requires ODVA money; PROFINET requires PI money and
   certification. We can ship a LAN9252-based slave under CERN-OHL-S. We could not do that
   with the alternatives.

## Rejected
- **Modbus TCP (e.g. Brainboxes).** Good hardware, wrong architecture. No hot connect, no
  position addressing, no machine-readable device description, non-deterministic, and every
  node needs a human-assigned IP. Fails the "add a module and it just works" test.
- **EtherNet/IP, PROFINET.** Vendor-ID and certification costs are incompatible with open
  hardware.

## Consequences
- Full open stack available: SOEM (master, GPLv3) + SOES (slave) + LAN9252.
- **The EtherCAT master needs a good NIC.** Use x86 + Intel i210/i225 + PREEMPT_RT. A
  Raspberry Pi-class board is *not* where the master goes — SOEM's jitter is dominated by
  the NIC driver. (This corrects an earlier assumption.)
- Every layer is now self-describing: ESI (EtherCAT), IODD (IO-Link), and our manifest on
  top. Three XML schemas, machine-readable all the way down. **That is what lets an agent
  reason about a cell it has never seen.**
