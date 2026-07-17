# SPDX-License-Identifier: AGPL-3.0-or-later
"""SignalBus -- the coordinator's (and, in the loopback proof, the
simulated robot's) view of every module's fieldbus signals, stubbed
behind an interface so the real EtherCAT/SOEM layer (ADR-0002) can be
dropped in later without touching coordinator logic or the handshake
protocol at all. `SimulatedSignalBus` is an in-memory implementation for
the loopback proof and for exercising a generated coordinator before
hardware exists.

Deliberately not modeling per-signal `type`/`unit` (already validated at
the manifest layer, ocm_core.Signal) or EtherCAT process-data timing --
this is a synchronization primitive (read the last written value, write a
new one), same as what a real fieldbus master's process image gives a
coordinator process. Values are keyed by (instance, signal name), matching
`Comms.signals` naming -- not by role; role resolution is `.robot_link`'s
job (for the four handshake signals) and the coordinator's own job (for
everything else, e.g. precondition/process-result signals).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class SignalBus(ABC):
    """A module instance's signals, read/write by (instance, signal name)."""

    @abstractmethod
    async def read(self, instance: str, signal: str) -> Any:
        """The last written value, or None if it's never been written."""

    @abstractmethod
    async def write(self, instance: str, signal: str, value: Any) -> None: ...


class SimulatedSignalBus(SignalBus):
    """An in-memory signal table. No transport, no timing -- a write is
    visible to the next read immediately. Good enough to prove the
    coordinator/robot-program *logic* correct (the loopback test's whole
    point); a real transport's latency/jitter is `.robot_link`'s and a
    future SOEM-backed SignalBus's concern, not this protocol's.
    """

    def __init__(self) -> None:
        self._values: dict[tuple[str, str], Any] = {}

    async def read(self, instance: str, signal: str) -> Any:
        return self._values.get((instance, signal))

    async def write(self, instance: str, signal: str, value: Any) -> None:
        self._values[(instance, signal)] = value

    def snapshot(self) -> dict[tuple[str, str], Any]:
        """A plain-dict copy for test assertions / debugging -- not part
        of the SignalBus interface itself.
        """
        return dict(self._values)
