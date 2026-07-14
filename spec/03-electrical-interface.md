# OCM Spec — Electrical Interface v1.0

**Status: FROZEN.** Decide once. Never argue about it again.

## Sensor / actuator connector

```
M12 A-coded, 5-pin, female on the module

  Pin 1   +24 V      brown
  Pin 2   DI / DO    white    <- second discrete point
  Pin 3   0 V        blue
  Pin 4   C/Q        black    <- IO-Link, or SIO digital
  Pin 5   n.c. / FE  grey
```

**One cordset part number for every sensor in the cell.** A customer building from a kit buys
one reel of M12 cable.

## Electrical standard

| | |
|---|---|
| **Logic** | **PNP (sourcing). No NPN. No exceptions.** |
| Inputs | IEC 61131-2 Type 3 |
| Outputs | 0.5 A/ch, per-channel short-circuit protection, integral flyback clamp, **per-channel diagnostics** |
| Supply | 24 VDC, separate actuator and sensor rails |

⚠️ **PNP is a compatibility requirement, not a preference.** IO-Link's SIO mode *is* PNP. Mix
NPN in and you get a cell where half the sensors work and nobody can explain why.
Japanese-legacy equipment will tempt you toward NPN. Don't.

## Why the IO-Link master IS the DI/DO block

Each port is configurable as **IO-Link**, **plain digital input (SIO)**, or **digital output**.
Plus Pin 2 gives a second discrete point per port.

**An 8-port master = 8 smart devices, or 16 discrete points, or any mix — decided in config,
not in hardware.** We do not buy separate DI and DO cards. See ADR-0003.

## Form factor

**IP67 box modules bolted to the module.** Not DIN rail in a panel.

No enclosure, no gland plate, no wire duct, no ferrules, no terminal blocks. A customer
assembling a kit **plugs M12 cordsets together** — they cannot land a wire on the wrong
terminal because there are no terminals.

## Safety

E-stop, light curtain, door interlock: **hardwired, dual-channel, to the certified relay.
Never on the standard I/O.**

Reading the safety circuit's *status contacts* as ordinary DI (so the HMI can say "e-stop
pressed, station 2") is fine and encouraged. **The safety function itself stays a wire.**
