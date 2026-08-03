# spec

CC BY-SA 4.0. The standard, independently implementable.

**Parsing rule for every manifest:** YAML 1.2 core schema — bare `on`/`off`/`yes`/`no` are
strings, never booleans. A 1.1-resolving parser silently corrupts valid manifests
(`mount.on` becomes the key `True`). Normative statement in [00-overview.md](00-overview.md).

| | |
|---|---|
| [00-overview.md](00-overview.md) | The three layers — and the YAML 1.2 parsing rule |
| [02-mechanical-interface.md](02-mechanical-interface.md) | 🔴 **NOT FROZEN** — the bolt grid |
| [03-electrical-interface.md](03-electrical-interface.md) | ✅ M12 pinout, PNP, IO-Link |
| [04-fieldbus.md](04-fieldbus.md) | ✅ EtherCAT + IO-Link, pneumatics, vacuum |
| [05-state-machine.md](05-state-machine.md) | ✅ PackML, mandatory |
| [06-safety.md](06-safety.md) | ✅ The hard boundary |
| [08-robot-handshake.md](08-robot-handshake.md) | ✅ Step-counter handshake — RTDE binding, no coordination wiring |
| [09-ocm-api.md](09-ocm-api.md) | 🟡 Draft — the one API surface for agents + GUI (ADR-0012) |
| [10-components.md](10-components.md) | 🟡 Draft — components (transcribed) vs modules (designed), ADR-0014 |
| [11-refusals.md](11-refusals.md) | 🟡 Draft — the refusal vocabulary is part of OCM: codes, phases, outcomes (ADR-0025) |
| [schema/](schema/) | JSON Schema |
