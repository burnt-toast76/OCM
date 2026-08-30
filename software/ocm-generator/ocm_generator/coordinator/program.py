# SPDX-License-Identifier: AGPL-3.0-or-later
"""The generated coordinator: an asyncio program that walks a resolved
cell's fastening for_each sequence in lockstep with the robot program
`.emitters.urscript` emits, over spec/08's handshake (`.robot_link`) and
the module signals it gates on (`.packml`) -- both via `.signals.SignalBus`,
so the real EtherCAT/SOEM layer (ADR-0002) is a driver this v0 doesn't
need yet, not a rewrite later.

## Step numbering

Uses the exact same `standoff_step_number`/`contact_step_number` functions
`.emitters.urscript` uses, both sourced from `.planner.poses`. Two
independently-generated programs (this one, the URScript one) agree on
what "step 4" means because they call the same function, not because they
happen to implement the same arithmetic twice.

## What happens at each sync point

- **Standoff** (`hs_at_step >= 2i-1`): withhold `hs_done_step` until
  `drive_screw`'s own declared `preconditions` (e.g. `screw_present ==
  true`) hold against the tool module's live signals. This is spec/08's
  "interlocks become motion gates" made real: the robot is physically
  unable to descend to contact until the manifest's own precondition is
  satisfied -- not a comment, an actual polled gate.
- **Contact** (`hs_at_step >= 2i`): run `drive_screw`'s PackML
  start->Execute->Complete cycle against the tool module (simulated for
  now -- see `.packml`'s own module docstring on why the numeric encoding
  is this project's placeholder, not a spec), read back
  torque_achieved/angle_achieved/result_ok, append a trace entry. A false
  `result_ok` raises `hs_abort` instead of `hs_done_step` and stops the
  walk right there -- on_fail's eject_screw/reject_part routing is PLC
  logic this v0 coordinator doesn't implement yet, but the abort signal
  that would trigger it is real.

`load_screw` is fired (not awaited) immediately before each hole's
standoff wait begins -- for hole 1, that's before waiting on step 1 at
all -- mirroring exactly where `.emitters.urscript` places its "overlaps
following transit" comment. Its own completion is never watched directly;
it's observed indirectly, through drive_screw's `screw_present`
precondition at the following standoff gate.

## Go-live

Before any of the above, `.drivers.check_drivers_registered` walks every
resolved instance's own declared `comms.protocol` against the
`DriverRegistry` this coordinator was built with, and refuses (naming
every protocol/instance pair with no registered driver) if the cell can't
actually be talked to yet -- a custom `x-<name>` protocol (ADR-0012) is
perfectly valid to author, resolve, and plan against, but the coordinator
is the stage that has to actually drive it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ocm_core import Capability, Module
from ocm_resolve import ResolvedCell

from .drivers import DriverRegistry, check_drivers_registered
from .errors import CoordinatorError, HeartbeatStaleError, OpTimeoutError, PostconditionError
from .packml import (
    PackMLCommand,
    PackMLState,
    failing_postconditions,
    preconditions_met,
    read_signals,
)
from .robot_link import RobotLink
from .signals import SignalBus

DEFAULT_POLL_INTERVAL_S = 0.02
DEFAULT_HEARTBEAT_TIMEOUT_S = 2.0  # spec/08: "static for > 2s ... -> coordinator faults the cell"

# Process-result signal names this v0 coordinator expects `drive_screw`'s
# module to declare (role: process_result in its own comms.signals block --
# see sd50's manifest). Referencing these by name is not the same kind of
# hardcoding spec/08 rules out for the *handshake*: the handshake's
# transport/register layout varies by robot vendor, which is exactly what
# role-based binding (.robot_link) exists to abstract. A capability's own
# result signal names are just its own declared names.
_RESULT_OK_SIGNAL = "result_ok"
_TORQUE_SIGNAL = "torque_achieved"
_ANGLE_SIGNAL = "angle_achieved"


@dataclass(frozen=True)
class TraceEntry:
    hole_id: str
    tool_instance: str
    step: int
    torque_achieved: float | None
    angle_achieved: float | None
    result_ok: bool
    timestamp: str  # ISO 8601, UTC

    def to_dict(self) -> dict[str, Any]:
        return {
            "hole_id": self.hole_id,
            "tool_instance": self.tool_instance,
            "step": self.step,
            "torque_achieved": self.torque_achieved,
            "angle_achieved": self.angle_achieved,
            "result_ok": self.result_ok,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class CoordinatorResult:
    trace: tuple[TraceEntry, ...] = ()
    aborted: bool = False
    abort_reason: str | None = None
    # ADR-0023 Decision 6: a capability whose `on_timeout` is `hold` lands
    # the cell in PackML Held, not Aborted -- the part stays put and waits
    # for a human. That's a distinct outcome from an abort (which routes to
    # on_fail), so it gets its own field rather than overloading `aborted`.
    held: bool = False
    hold_reason: str | None = None


def write_trace_log(path: str | Path, result: CoordinatorResult) -> None:
    """The JSON traceability log -- one record per hole actually reached,
    in the order the coordinator processed them.
    """
    Path(path).write_text(
        json.dumps(
            {
                "aborted": result.aborted,
                "abort_reason": result.abort_reason,
                "held": result.held,
                "hold_reason": result.hold_reason,
                "trace": [entry.to_dict() for entry in result.trace],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _process_result_signal_names(module: Module) -> set[str]:
    if module.comms is None:
        return set()
    return {s.name for s in module.comms.signals_with_role("process_result")}


class Coordinator:
    """Bound to one resolved cell's fastening sequence. Construct once
    (checks driver coverage for the whole cell, the handshake binding, and
    the tool module's result-signal contract up front -- fail at startup,
    not mid-cycle), then `await .run()`.
    """

    def __init__(
        self,
        resolved: ResolvedCell,
        bus: SignalBus,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        heartbeat_timeout_s: float = DEFAULT_HEARTBEAT_TIMEOUT_S,
        trace_log_path: str | Path | None = None,
        driver_registry: DriverRegistry | None = None,
    ) -> None:
        from ocm_generator.planner import find_fastening_plan

        self.resolved = resolved
        self.bus = bus
        self.poll_interval_s = poll_interval_s
        self.heartbeat_timeout_s = heartbeat_timeout_s
        self.trace_log_path = trace_log_path
        self.driver_registry = driver_registry if driver_registry is not None else DriverRegistry.default()

        check_drivers_registered(resolved, self.driver_registry)

        self.fasten = find_fastening_plan(resolved.cell)
        self.tool_instance = self.fasten.steps[0].tool_instance
        tool_ri = resolved.instance(self.tool_instance)
        if tool_ri.mounted_on is None:
            raise CoordinatorError(f"{self.tool_instance} is not mounted on a robot -- nothing to hand-shake with")
        self.tool_module: Module = tool_ri.module
        self.robot_instance = tool_ri.mounted_on.name
        self.robot_link = RobotLink.bind(bus, self.robot_instance, tool_ri.mounted_on.module)

        self.drive_screw: Capability = self.tool_module.capability("drive_screw")

        # ADR-0023: resolve the tool instance's `requires` bindings to
        # concrete `(instance, signal)` pairs ONCE, up front -- a
        # capability that gates on a peer's signal (e.g. drive_screw's
        # `workpiece_secured` bound to `nest1.clamped`) reads that peer
        # through this map. Resolve time already checked every binding
        # names a real instance/signal, so this is a pure parse.
        self.bindings: dict[str, tuple[str, str]] = self._resolve_bindings(
            resolved.cell.module(self.tool_instance)
        )

        result_names = _process_result_signal_names(self.tool_module)
        missing = {_RESULT_OK_SIGNAL, _TORQUE_SIGNAL, _ANGLE_SIGNAL} - result_names
        if missing:
            raise CoordinatorError(
                f"{self.tool_module.id} declares no process_result signal(s) named {sorted(missing)} -- "
                "this coordinator needs result_ok/torque_achieved/angle_achieved to record drive_screw's outcome"
            )

    async def run(self) -> CoordinatorResult:
        heartbeat_task = asyncio.create_task(self._watch_heartbeat())
        walk_task = asyncio.ensure_future(self._walk())
        try:
            done, _ = await asyncio.wait({walk_task, heartbeat_task}, return_when=asyncio.FIRST_COMPLETED)
            if heartbeat_task in done:
                exc = heartbeat_task.exception()
                if exc is not None:
                    walk_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await walk_task
                    raise exc
            result = await walk_task
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task

        if self.trace_log_path is not None:
            write_trace_log(self.trace_log_path, result)
        return result

    async def _walk(self) -> CoordinatorResult:
        from ocm_generator.planner import contact_step_number, standoff_step_number

        trace: list[TraceEntry] = []
        for index, step in enumerate(self.fasten.steps, start=1):
            if self.fasten.load_screw_module is not None:
                await self._start_op(self.fasten.load_screw_module, "load_screw", step.hole_id)

            standoff_step = standoff_step_number(index)
            await self._wait_for_at_step(standoff_step)
            # Interlocks become motion gates (ADR-0023): the robot is
            # physically unable to proceed to contact until every one of
            # drive_screw's declared preconditions holds -- including any
            # bound to a peer instance's signal. Bounded by the
            # capability's own `timeout_s`; on expiry the part is disposed
            # per its own `on_timeout` (hold -> Held, abort -> Aborted).
            try:
                await self._wait_for_preconditions(self.tool_instance, self.drive_screw)
            except OpTimeoutError as err:
                return await self._dispose_timeout(err, trace)
            await self.robot_link.write_done_step(standoff_step)

            contact_step = contact_step_number(index)
            await self._wait_for_at_step(contact_step)
            try:
                entry = await self._run_drive_screw(step, contact_step)
            except OpTimeoutError as err:
                return await self._dispose_timeout(err, trace)
            trace.append(entry)

            if not entry.result_ok:
                # A false result_ok is a legitimate, expected protocol
                # outcome -- not a bug -- so it's reported back, not
                # raised: hs_abort (real, over the bus) plus an aborted
                # CoordinatorResult the caller can inspect. on_fail's
                # eject_screw/reject_part routing is PLC logic this v0
                # coordinator doesn't implement yet; the abort signal that
                # would trigger it is real.
                await self.robot_link.write_abort(1)
                return CoordinatorResult(
                    trace=tuple(trace),
                    aborted=True,
                    abort_reason=f"drive_screw result_ok=false @ {step.hole_id}",
                )

            # ADR-0023 Decision 2: PackML Complete alone no longer advances
            # the walk. Verify drive_screw's own declared postconditions
            # against the live bus; if one reads false, the module reported
            # Complete without actually reaching it -- fault the cell,
            # naming the capability and the condition it lied about.
            failing = await failing_postconditions(
                self.bus, self.tool_instance, self.drive_screw, self.bindings
            )
            if failing:
                # Fault the cell (this raise surfaces out of .run(), like a
                # stale heartbeat) -- but drop hs_abort first so the robot,
                # still parked at the contact sync waiting for done_step,
                # halts instead of hanging on a coordinator that just died.
                await self.robot_link.write_abort(1)
                raise PostconditionError(
                    f"drive_screw reported PackML Complete @ {step.hole_id} but "
                    f"postcondition(s) {failing} read false against the live bus"
                )

            await self.robot_link.write_done_step(contact_step)

        return CoordinatorResult(trace=tuple(trace))

    @staticmethod
    def _resolve_bindings(instance) -> dict[str, tuple[str, str]]:
        """`{requirement name: (target instance, target signal)}` from a
        cell instance's `requires:` map (`"nest1.clamped"` ->
        `("nest1", "clamped")`). Resolve time already validated the target
        exists and is well-formed, so this only has to split on the first
        dot.
        """
        bindings: dict[str, tuple[str, str]] = {}
        for req_name, target in instance.requires.items():
            target_instance, _, signal = target.partition(".")
            bindings[req_name] = (target_instance, signal)
        return bindings

    async def _dispose_timeout(self, err: OpTimeoutError, trace: list[TraceEntry]) -> CoordinatorResult:
        """Dispose a timed-out op per the capability's own `on_timeout`
        (ADR-0023 Decision 6). `hold` commands PackML Hold and returns a
        Held result -- the part stays put for a human. `abort` raises the
        real `hs_abort` and returns an Aborted result so on_fail's routing
        (PLC logic this v0 doesn't implement) has its trigger.
        """
        if err.on_timeout == "hold":
            await self.bus.write(self.tool_instance, "packml_cmd", int(PackMLCommand.HOLD))
            return CoordinatorResult(trace=tuple(trace), held=True, hold_reason=str(err))
        await self.robot_link.write_abort(1)
        return CoordinatorResult(trace=tuple(trace), aborted=True, abort_reason=str(err))

    async def _start_op(self, instance: str, op: str, hole_id: str) -> None:
        # `_active_op`/`_active_hole` are simulation-only routing signals --
        # see .packml's own module docstring on why: real firmware already
        # knows which of its own operations a given start command means,
        # through means outside spec/08's scope; the loopback proof's
        # simulated module needs an explicit way to know instead.
        await self.bus.write(instance, "_active_op", op)
        await self.bus.write(instance, "_active_hole", hole_id)
        # Clear any COMPLETE left over from a PRIOR op (e.g. the load_screw
        # this v0 never explicitly waits on/acknowledges) *before* asking
        # for a new one -- otherwise a poll landing between this write and
        # the module noticing it could read a stale COMPLETE and mistake
        # someone else's finished cycle for this request's.
        await self.bus.write(instance, "packml_state", int(PackMLState.IDLE))
        await self.bus.write(instance, "packml_cmd", int(PackMLCommand.START))

    async def _run_drive_screw(self, step, contact_step: int) -> TraceEntry:
        await self._start_op(self.tool_instance, "drive_screw", step.hole_id)
        await self._wait_for_state(self.tool_instance, PackMLState.COMPLETE, self.drive_screw)
        values = await read_signals(
            self.bus,
            {name: (self.tool_instance, name) for name in (_RESULT_OK_SIGNAL, _TORQUE_SIGNAL, _ANGLE_SIGNAL)},
        )
        return TraceEntry(
            hole_id=step.hole_id,
            tool_instance=self.tool_instance,
            step=contact_step,
            torque_achieved=values.get(_TORQUE_SIGNAL),
            angle_achieved=values.get(_ANGLE_SIGNAL),
            result_ok=bool(values.get(_RESULT_OK_SIGNAL)),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    async def _wait_for_at_step(self, step: int) -> None:
        while (await self.robot_link.read_at_step()) < step:
            await asyncio.sleep(self.poll_interval_s)

    async def _wait_for_preconditions(self, instance: str, capability: Capability) -> None:
        """Poll until every precondition holds, bounded by the capability's
        own `timeout_s` (ADR-0023 Decision 6). On expiry, raise
        OpTimeoutError carrying `on_timeout` so `_walk` can dispose the part
        per the module's declaration.
        """
        deadline = time.monotonic() + capability.timeout_s if capability.timeout_s else None
        while not await preconditions_met(self.bus, instance, capability, self.bindings):
            if deadline is not None and time.monotonic() >= deadline:
                raise OpTimeoutError(capability.name, "preconditions", capability.on_timeout, capability.timeout_s)
            await asyncio.sleep(self.poll_interval_s)

    async def _wait_for_state(self, instance: str, state: PackMLState, capability: Capability) -> None:
        """Poll until the module reports `state`, bounded by the
        capability's `timeout_s` (ADR-0023 Decision 6) -- a module that
        never reaches Complete is timed out and disposed, not waited on
        forever.
        """
        deadline = time.monotonic() + capability.timeout_s if capability.timeout_s else None
        while (await self.bus.read(instance, "packml_state")) != int(state):
            if deadline is not None and time.monotonic() >= deadline:
                raise OpTimeoutError(capability.name, "completion", capability.on_timeout, capability.timeout_s)
            await asyncio.sleep(self.poll_interval_s)

    async def _watch_heartbeat(self) -> None:
        """spec/08: "hs_heartbeat static for > 2s while a program should
        be running = robot program dead or connection lost -> coordinator
        faults the cell." Runs for the lifetime of `.run()`; cancelled
        (not faulted) the moment the walk finishes on its own.
        """
        last_value = await self.robot_link.read_heartbeat()
        last_change = time.monotonic()
        while True:
            await asyncio.sleep(self.poll_interval_s)
            current = await self.robot_link.read_heartbeat()
            now = time.monotonic()
            if current != last_value:
                last_value = current
                last_change = now
            elif now - last_change > self.heartbeat_timeout_s:
                raise HeartbeatStaleError(
                    f"hs_heartbeat has not advanced for over {self.heartbeat_timeout_s:g}s -- "
                    "robot program dead or connection lost"
                )
