# SPDX-License-Identifier: AGPL-3.0-or-later
"""SimulatedPackMLModule -- a stand-in for a real EtherCAT slave's
firmware in the loopback proof: watches `packml_cmd` for a start request
and, after a short simulated processing delay, runs an explicit per-op
*recipe* that writes concrete signal values (for sd50: `load_screw` sets
`screw_present`; `drive_screw` clears it and reports
`torque_achieved`/`angle_achieved`/`result_ok`).

## Recipes are explicit, NOT derived from the manifest's postconditions

ADR-0023 Decision 2 turns a capability's postconditions into a check the
*coordinator* runs after Complete -- so this simulated firmware must be
able to lie: report Complete while a postcondition reads false, exactly as
a real misbehaving device would. If a recipe were generated *from* the
postconditions it could never produce that mismatch, and the coordinator's
post-Complete verification would be untestable. So each recipe is written
out by hand (`make_drive_screw_recipe(clear_screw_present=False)` is the
fixture that leaves `screw_present` true after reporting Complete), and the
coordinator's belief in Complete is the thing under test, not an identity.

This is intentionally where the "simulated screwdriver" domain knowledge
lives, not in `.program` -- the coordinator only ever reads/writes signals
by name and role (see that module's own docstring); it has no idea sd50
exists. A different module's simulated firmware would be a different set
of recipes behind the same `run()` loop.

`_active_op`/`_active_hole` are simulation-only routing signals, not part
of spec/08 or any real manifest -- see `.program._start_op`'s own note on
why: real firmware already knows which of its own operations a given
start command means, through means outside spec/08's scope (it's a single
device with a fixed recipe, or a separate recipe-select signal a real
integration would define); this stand-in needs an explicit way to know
instead, since it can run more than one op recipe.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .packml import PackMLCommand, PackMLState
from .signals import SignalBus

OpRecipe = Callable[[SignalBus, str, str], Awaitable[None]]


async def default_load_screw_recipe(bus: SignalBus, instance: str, hole_id: str) -> None:
    """sd50's own declared postcondition for load_screw: `screw_present == true`."""
    await bus.write(instance, "screw_present", True)


def make_drive_screw_recipe(
    result_ok_for: Callable[[str], bool] = lambda hole_id: True,
    torque_achieved: float = 2.4,
    angle_achieved: float = 45.0,
    clear_screw_present: bool = True,
) -> OpRecipe:
    """A `drive_screw` recipe. `result_ok_for` lets a test force a
    specific hole's result to fail (the abort proof) without the
    simulated module needing to know about test scenarios itself --
    sd50's own declared postconditions: `screw_present == false`,
    `result_ok == true` (the happy path; `result_ok_for` can say
    otherwise).

    `clear_screw_present=False` is the ADR-0023 Decision 2 fixture: the
    recipe reports Complete (result_ok true) while deliberately leaving
    `screw_present` true, so the capability's `screw_present == false`
    postcondition reads false against the live bus. The coordinator must
    catch that and fault the cell rather than believe Complete.
    """

    async def recipe(bus: SignalBus, instance: str, hole_id: str) -> None:
        await bus.write(instance, "screw_present", not clear_screw_present)
        await bus.write(instance, "torque_achieved", torque_achieved)
        await bus.write(instance, "angle_achieved", angle_achieved)
        await bus.write(instance, "result_ok", bool(result_ok_for(hole_id)))

    return recipe


@dataclass
class SimulatedPackMLModule:
    """Runs as a background asyncio task for the lifetime of a loopback
    run -- `.stop()` (checked once per poll interval) is how a test tears
    it down after the coordinator finishes.
    """

    bus: SignalBus
    instance: str
    recipes: dict[str, OpRecipe]
    op_delay_s: float = 0.05
    poll_interval_s: float = 0.01
    _stopped: bool = field(default=False, init=False)

    def stop(self) -> None:
        self._stopped = True

    async def run(self) -> None:
        await self.bus.write(self.instance, "packml_state", int(PackMLState.IDLE))
        last_cmd = int(PackMLCommand.IDLE)
        while not self._stopped:
            cmd = await self._read_cmd()
            if cmd == int(PackMLCommand.START) and last_cmd != int(PackMLCommand.START):
                await self._execute()
                # Re-read: `_execute()` can take a while (a real op delay),
                # during which the bus's cmd could change again (e.g. a
                # fresh request queued while this one ran, or this one's
                # own internal reset). Comparing against the value read
                # BEFORE `_execute()` here would compare against a stale
                # snapshot and could silently miss the next edge -- the
                # same "missed edge" failure mode spec/08 designs its own
                # (real) handshake to be immune to by being level-based;
                # this internal cmd/state cycle is edge-based and has to
                # earn that immunity explicitly instead.
                cmd = await self._read_cmd()
            last_cmd = cmd
            await asyncio.sleep(self.poll_interval_s)

    async def _read_cmd(self) -> int:
        raw_cmd = await self.bus.read(self.instance, "packml_cmd")
        return int(raw_cmd) if raw_cmd is not None else int(PackMLCommand.IDLE)

    async def _execute(self) -> None:
        op = await self.bus.read(self.instance, "_active_op")
        hole_id = await self.bus.read(self.instance, "_active_hole")
        recipe = self.recipes.get(op)

        # Consume the request immediately: resets the edge-detector for
        # the NEXT request right away, so a fire-and-forget op (e.g.
        # load_screw, never explicitly acknowledged by the coordinator)
        # doesn't leave `packml_cmd` parked at START forever, which would
        # make a later, genuinely new START invisible (no edge to detect).
        await self.bus.write(self.instance, "packml_cmd", int(PackMLCommand.IDLE))

        await self.bus.write(self.instance, "packml_state", int(PackMLState.STARTING))
        await asyncio.sleep(self.op_delay_s)
        await self.bus.write(self.instance, "packml_state", int(PackMLState.EXECUTE))
        await asyncio.sleep(self.op_delay_s)

        if recipe is not None:
            await recipe(self.bus, self.instance, hole_id)

        await self.bus.write(self.instance, "packml_state", int(PackMLState.COMPLETE))
