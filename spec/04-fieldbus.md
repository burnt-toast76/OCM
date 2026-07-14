# OCM Spec — Fieldbus v1.0

**EtherCAT** backbone. **IO-Link** beneath it. See [ADR-0002](../docs/decisions/0002-ethercat-fieldbus.md).

## Topology

Every module carries its own node. **One bus cable in, one out. One power cable in, one out.**
That is the entire electrical interface.

## Requirements

| | |
|---|---|
| Fieldbus | EtherCAT (CoE), Hot Connect groups |
| Addressing | **By physical position.** `ethercat_position: N` in `cell.yaml` maps 1:1. |
| Device description | ESI (XML) — the tag list generates from it. Zero transcription. |
| Master | **SOEM 2.0** (GPLv3). ⚠️ *Not IgH — that's GPLv2 and breaks the license chain.* |
| Master hardware | **x86 + Intel i210/i225 NIC + PREEMPT_RT.** Not a Pi — SOEM's jitter is dominated by the NIC driver. |
| Servo drives | CiA 402, csp mode. See [`reference/drives-tested.md`](../reference/drives-tested.md). |

## Analog

**Push analog into IO-Link.** Modern pressure/vacuum/distance/temperature sensors have IO-Link
variants giving the digital value + device identity + remote parameterization over a 3-wire
unshielded M12 cable. That eliminates scaling errors, shielding problems, transcribed
calibration values, and manual AI card config. IO-Link devices carry an **IODD** — machine
readable, same story as ESI.

**True analog only where bandwidth demands it:**
- Load cells for press-fit force at kHz → EtherCAT strain-gauge terminal
- Proportional pressure regulators in a servo loop → EtherCAT AO terminal
- Thermocouple/RTD → dedicated terminal with cold-junction comp at the node

> **Rule of thumb:** read once per operation → IO-Link. In a closed loop → EtherCAT analog
> terminal. There is almost no legitimate use for a generic 0–10 V input card in this design.

## Pneumatics and vacuum

**Valves on the module. Not a central island.**
- Plug-and-produce: a central manifold means adding a module = re-plumbing the panel
- 3 m of tube adds 30–80 ms of dead time, every actuation
- Spec: 2–4 station valve island with integrated IO-Link/EtherCAT node, on the module

**Vacuum: generate it at the gripper. Always.**
Never plumb vacuum from a panel — slow to build, slow to break, every fitting is a leak that
degrades the part-present signal. Use an integrated venturi ejector (SMC ZK2, Festo OVEM, Piab
piCOMPACT) at the end effector. One 40 mm package gives you: fast ejector, **vacuum switch (=
your `part_present` signal — no separate sensor)**, blow-off valve, and air-saving latch that
cuts consumption 60–90%.

The air-saving check valve also satisfies `safe_state: "vacuum HELD on trip"` **mechanically,
without power.** Satisfy safe-state declarations with physics, not logic, wherever you can.

The central panel keeps only: FRL, main dump valve, soft-start, safety exhaust.
