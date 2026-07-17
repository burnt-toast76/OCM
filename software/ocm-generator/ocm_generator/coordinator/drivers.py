# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which `comms.protocol` values this coordinator build actually has a
transport driver for -- checked once, at go-live, so a cell with a module
speaking a protocol nothing implements fails loudly before motion starts,
not partway through a shift.

Per ADR-0012's escape hatch (spec/CHANGELOG.md v1.1): authoring, resolve,
scene, and plan all work with ANY protocol, including `x-<name>` custom
ones -- none of those stages ever touch a transport. The coordinator is
the one stage that actually has to talk to hardware, so it's the one
stage that has to know what it can and can't drive, and refuse cleanly
(naming the protocol and the instance) rather than hang on a signal that
will never arrive.

`DEFAULT_REGISTERED_PROTOCOLS` reflects what THIS v0 build actually has
wired, even if only in simulation: `ur-rtde` backs `.robot_link.RobotLink`
(spec/08's own binding), `ethercat` backs the loopback proof's
`SimulatedPackMLModule`. Real SOEM support (ADR-0002) replaces
`ethercat`'s simulated backing later without changing this set's shape --
a protocol either has SOME registered driver (simulated counts, today) or
it doesn't.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ocm_resolve import ResolvedCell

from .errors import DriverNotRegisteredError

DEFAULT_REGISTERED_PROTOCOLS = frozenset({"ur-rtde", "ethercat"})


@dataclass(frozen=True)
class DriverRegistry:
    protocols: frozenset[str] = field(default_factory=lambda: DEFAULT_REGISTERED_PROTOCOLS)

    @classmethod
    def default(cls) -> "DriverRegistry":
        return cls()

    def has_driver(self, protocol: str) -> bool:
        return protocol in self.protocols


def check_drivers_registered(resolved: ResolvedCell, registry: DriverRegistry) -> None:
    """Raises DriverNotRegisteredError, naming every (protocol, instance)
    pair with no registered driver, if any -- a go-live preflight over
    EVERY resolved instance (plus the base) that declares a `comms` block,
    not just the modules this coordinator's own fastening walk touches:
    a cell can't safely go live with ANY module it can't talk to, whether
    or not this particular sequence happens to need it.
    """
    missing: list[tuple[str, str]] = []

    if resolved.base.comms is not None and not registry.has_driver(resolved.base.comms.protocol):
        missing.append((resolved.base.comms.protocol, "base"))

    for name, ri in sorted(resolved.instances.items()):
        comms = ri.module.comms
        if comms is None:
            continue
        if not registry.has_driver(comms.protocol):
            missing.append((comms.protocol, name))

    if missing:
        raise DriverNotRegisteredError(missing)
