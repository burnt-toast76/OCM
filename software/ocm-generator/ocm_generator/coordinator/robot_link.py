# SPDX-License-Identifier: AGPL-3.0-or-later
"""RobotLink -- the coordinator's spec/08 handshake interface to one robot
instance, bound from that robot module's own `comms.signals` block BY
ROLE (`handshake_at_step` / `handshake_done_step` / `handshake_abort` /
`handshake_heartbeat`) -- never a hardcoded register number. Built on top
of a SignalBus; which transport that bus actually talks (RTDE, discrete
I/O, ...) is entirely the SignalBus implementation's concern, exactly as
spec/08's "Transport bindings" section describes: "the generated
coordinator logic is identical across all bindings; only the I/O driver
differs."

`RobotLink.bind` is where a missing/ambiguous role binding is caught --
at startup, not three hours into a shift the first time a hole is
unreachable for a *manifest* reason rather than a kinematic one.
"""

from __future__ import annotations

from dataclasses import dataclass

from ocm_core import Module

from .errors import HandshakeBindingError
from .signals import SignalBus

ROLE_AT_STEP = "handshake_at_step"
ROLE_DONE_STEP = "handshake_done_step"
ROLE_ABORT = "handshake_abort"
ROLE_HEARTBEAT = "handshake_heartbeat"


def _signal_name_for_role(module: Module, role: str) -> str:
    if module.comms is None:
        raise HandshakeBindingError(
            f"{module.id} declares no comms/signals block -- can't bind spec/08 handshake role {role!r}"
        )
    matches = module.comms.signals_with_role(role)
    if not matches:
        raise HandshakeBindingError(f"{module.id} declares no signal with role {role!r} (spec/08 handshake)")
    if len(matches) > 1:
        names = [s.name for s in matches]
        raise HandshakeBindingError(f"{module.id} declares multiple signals with role {role!r}: {names}")
    return matches[0].name


@dataclass(frozen=True)
class RobotLink:
    """One robot instance's bound handshake signals. `at_step`/`heartbeat`
    are the robot's own writes (this side reads them); `done_step`/`abort`
    are this side's writes (the robot reads them) -- see spec/08's
    direction column, and ocm_generator's schema convention (module.py's
    Comms docstring) for why the manifest's own `direction:` matches that.
    """

    bus: SignalBus
    instance: str
    at_step_signal: str
    done_step_signal: str
    abort_signal: str
    heartbeat_signal: str

    @classmethod
    def bind(cls, bus: SignalBus, instance: str, module: Module) -> "RobotLink":
        return cls(
            bus=bus,
            instance=instance,
            at_step_signal=_signal_name_for_role(module, ROLE_AT_STEP),
            done_step_signal=_signal_name_for_role(module, ROLE_DONE_STEP),
            abort_signal=_signal_name_for_role(module, ROLE_ABORT),
            heartbeat_signal=_signal_name_for_role(module, ROLE_HEARTBEAT),
        )

    async def read_at_step(self) -> int:
        value = await self.bus.read(self.instance, self.at_step_signal)
        return int(value) if value is not None else 0

    async def read_heartbeat(self) -> int:
        value = await self.bus.read(self.instance, self.heartbeat_signal)
        return int(value) if value is not None else 0

    async def write_done_step(self, n: int) -> None:
        await self.bus.write(self.instance, self.done_step_signal, n)

    async def write_abort(self, value: int = 1) -> None:
        await self.bus.write(self.instance, self.abort_signal, value)

    async def read_abort(self) -> int:
        value = await self.bus.read(self.instance, self.abort_signal)
        return int(value) if value is not None else 0
