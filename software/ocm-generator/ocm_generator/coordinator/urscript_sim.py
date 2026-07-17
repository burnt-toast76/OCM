# SPDX-License-Identifier: AGPL-3.0-or-later
"""SimulatedRobot -- a stand-in for the physical UR controller in the
loopback proof. Parses an ACTUAL emitted URScript program's spec/08 sync
points (`write_output_integer_register(0, N)` / `while
read_input_integer_register(0) < N: ...`) out of the text itself and
replays them against a SignalBus. It does not know the plan, the hole
count, or the step numbering in advance -- if `.emitters.urscript`'s
output shape changes, this adapts with it; it is not a second,
hand-maintained copy of the protocol the emitter and the coordinator
already share (see `.planner.poses.standoff_step_number`/
`contact_step_number`).

Not a general URScript interpreter -- deliberately so. Motion lines
(`movej`/`movel`) are recognized only well enough to log them (their
Cartesian/joint values don't matter to this proof; only the ORDER and
STEP NUMBERS of the handshake do). Every other line that isn't a
recognized handshake construct (loop/if/halt/heartbeat-increment/sleep
inside a wait block, comments, blank lines) is intentionally not
interpreted line-by-line -- the whole wait block collapses to a single
`_wait` coroutine whose OBSERVABLE behavior (poll until hs_done_step >= N,
increment hs_heartbeat every iteration, halt on hs_abort) matches the
script's, which is what the loopback proof actually needs to exercise.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Literal

from .robot_link import RobotLink

_AT_STEP_RE = re.compile(r"write_output_integer_register\(\s*0\s*,\s*(\d+)\s*\)")
_WAIT_RE = re.compile(r"while\s+read_input_integer_register\(\s*0\s*\)\s*<\s*(\d+)\s*:")
_MOVE_RE = re.compile(r"^(movej|movel)\(")

RobotEventKind = Literal["move", "at_step", "wait_begin", "wait_end", "aborted"]


@dataclass(frozen=True)
class RobotEvent:
    kind: RobotEventKind
    detail: str | int | None = None


class RobotAborted(Exception):
    """The simulated robot saw hs_abort != 0 during a wait and halted --
    URScript's own `halt`, per spec/08's Abort section.
    """


def _parse(script: str) -> list[tuple[str, str | int]]:
    """The document-order sequence of (move | at_step | wait) actions a
    generated script contains. Everything else is either a motion line's
    own detail (ignored beyond logging it) or part of a wait block's body
    (already fully represented by the single "wait" action -- see module
    docstring).
    """
    actions: list[tuple[str, str | int]] = []
    for raw_line in script.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if _MOVE_RE.match(line):
            actions.append(("move", line))
            continue
        at_step_match = _AT_STEP_RE.search(line)
        if at_step_match:
            actions.append(("at_step", int(at_step_match.group(1))))
            continue
        wait_match = _WAIT_RE.search(line)
        if wait_match:
            actions.append(("wait", int(wait_match.group(1))))
    return actions


@dataclass
class SimulatedRobot:
    """Parses `script` once (at construction); `.run()` replays the
    resulting action sequence against `link.bus`.
    """

    script: str
    link: RobotLink
    poll_interval_s: float = 0.01

    events: list[RobotEvent] = field(default_factory=list, init=False)
    wait_iterations: dict[int, int] = field(default_factory=dict, init=False)
    _actions: list[tuple[str, str | int]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._actions = _parse(self.script)
        if not self._actions:
            raise ValueError("no movej/movel or handshake register lines found -- is this really a generated script?")

    @property
    def reached_steps(self) -> list[int]:
        """Every step number the robot actually announced arrival at, in
        order -- what an abort test checks to prove the walk stopped
        early (not just that SOME exception was raised).
        """
        return [e.detail for e in self.events if e.kind == "at_step"]  # type: ignore[misc]

    async def run(self) -> None:
        for action, value in self._actions:
            if action == "move":
                self.events.append(RobotEvent("move", value))
                await asyncio.sleep(0)  # yield control -- motion "completes" instantly in simulation
            elif action == "at_step":
                assert isinstance(value, int)
                await self.link.bus.write(self.link.instance, self.link.at_step_signal, value)
                self.events.append(RobotEvent("at_step", value))
            elif action == "wait":
                assert isinstance(value, int)
                await self._wait(value)

    async def _wait(self, step: int) -> None:
        """Mirrors the emitted script's own wait loop: check
        `hs_done_step >= step` first (the loop condition); if not yet
        met, check `hs_abort` (halts if set); otherwise increment
        `hs_heartbeat` and poll again.
        """
        self.events.append(RobotEvent("wait_begin", step))
        iterations = 0
        while True:
            done = await self.link.bus.read(self.link.instance, self.link.done_step_signal)
            if done is not None and int(done) >= step:
                break
            if await self.link.read_abort() != 0:
                self.events.append(RobotEvent("aborted", step))
                raise RobotAborted(f"hs_abort set while waiting for hs_done_step >= {step}")
            iterations += 1
            await self.link.bus.write(self.link.instance, self.link.heartbeat_signal, iterations)
            await asyncio.sleep(self.poll_interval_s)
        self.wait_iterations[step] = iterations
        self.events.append(RobotEvent("wait_end", step))
