# SPDX-License-Identifier: AGPL-3.0-or-later
"""The loopback proof: a generated coordinator (`ocm_generator.coordinator`)
executing spec/08's handshake against a SimulatedRobot that PARSES (not
re-hardcodes) the exact URScript `ocm_generator.emitters.urscript` emits
for the same plan, plus a SimulatedPackMLModule standing in for sd1. Two
independently-generated programs, executing the same contract, proven
against each other -- no real robot, no real fieldbus, and (per this
task's own scope) none needed yet: the logic is what's being proven here,
transports are drivers to add later.

Guarded by the optional `tesseract` extra, same as test_planner.py --
building the FasteningPlan/URScript still needs it, even though
`ocm_generator.coordinator` itself doesn't.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("tesseract_robotics")

from ocm_core.cell import Cell  # noqa: E402
from ocm_generator.coordinator import (  # noqa: E402
    Coordinator,
    HeartbeatStaleError,
    RobotAborted,
    RobotLink,
    SimulatedPackMLModule,
    SimulatedRobot,
    SimulatedSignalBus,
    default_load_screw_recipe,
    make_drive_screw_recipe,
)
from ocm_generator.emitters import emit_urscript  # noqa: E402
from ocm_generator.planner import plan_fastening_sequence  # noqa: E402
from ocm_generator.scene import build_scene  # noqa: E402
from ocm_resolve import resolve_cell  # noqa: E402

_HOME_JOINT_STATE = {"shoulder_lift_joint": -1.5707963267948966, "elbow_joint": 1.5707963267948966}


def _coordinator_cell_dict(features: dict[str, list[float]], for_each: list[str]) -> dict[str, Any]:
    """Same real UR5e/sd50/pneumatic-nest/frame1200 cell shape
    test_planner.py's own fixtures use, and for the same reason (IK is
    UR5e-specific; part_datum is pneumatic-nest's own frame) -- camera-
    free, so this is about the handshake, not re-proving test_planner's
    own cam1 finding.
    """
    return {
        "ocm_version": "1.0",
        "kind": "cell",
        "id": "com.example.cell.coordinator-test",
        "name": "Coordinator loopback test cell",
        "license": "CERN-OHL-S-2.0",
        "base": {"module": "com.accelsolutions.base.frame1200@2.0.0", "datum": "cell_origin", "grid": "ocm-base-grid-50"},
        "modules": [
            {
                "instance": "robot1",
                "module": "com.universal-robots.ur5e@3.1.0",
                "mount": {"station": [400, 300], "pose": {"xyz_mm": [400, 300, 0], "rpy_deg": [0, 0, 0]}},
                "joint_state": dict(_HOME_JOINT_STATE),
            },
            {"instance": "sd1", "module": "com.accelsolutions.screwdriver.sd50@1.2.0", "mount": {"on": "robot1.flange"}},
            {
                "instance": "nest1",
                "module": "com.accelsolutions.fixture.pneumatic-nest@1.1.0",
                "mount": {"pose": {"xyz_mm": [640, 300, 0], "rpy_deg": [0, 0, 90]}},
            },
        ],
        "part": {
            "id": "BRK-TEST",
            "cad": "cad/BRK-TEST.step",
            "features": {name: {"xyz_mm": xyz, "normal": [0, 0, 1]} for name, xyz in features.items()},
        },
        "plan": [
            {"step": "clamp", "module": "nest1", "op": "clamp", "params": {"force_n": 120}},
            {
                "step": "fasten",
                "for_each": for_each,
                "sequence": [
                    {"module": "sd1", "op": "load_screw"},
                    {
                        "module": "sd1",
                        "op": "drive_screw",
                        "at": "part.features.${item}",
                        "params": {"torque_nm": 2.4, "depth_mm": 8.0},
                        "on_fail": [{"module": "sd1", "op": "eject_screw"}, {"action": "reject_part"}],
                    },
                ],
            },
            {"step": "release", "module": "nest1", "op": "unclamp"},
        ],
    }


_BRACKET_HOLES = {"hole_1": [12, 12, 0], "hole_2": [12, 88, 0], "hole_3": [64, 50, 0]}


def _build_script(repo_root: Path, features: dict[str, list[float]], for_each: list[str]):
    cell = Cell.from_dict(_coordinator_cell_dict(features, for_each))
    resolved = resolve_cell(cell, repo_root / "modules")
    scene = build_scene(resolved, repo_root / "modules")
    plan = plan_fastening_sequence(resolved, scene)
    return resolved, emit_urscript(plan)


class _Loopback:
    """Wires a Coordinator, a SimulatedRobot (parsing the real emitted
    script), and a SimulatedPackMLModule against one shared
    SimulatedSignalBus, and tears everything down cleanly afterwards.
    """

    def __init__(
        self,
        resolved,
        script: str,
        *,
        drive_screw_result_ok_for=None,
        op_delay_s: float = 0.01,
        trace_log_path=None,
        heartbeat_timeout_s: float | None = None,
    ):
        self.bus = SimulatedSignalBus()
        coordinator_kwargs = {}
        if heartbeat_timeout_s is not None:
            coordinator_kwargs["heartbeat_timeout_s"] = heartbeat_timeout_s
        self.coordinator = Coordinator(resolved, self.bus, poll_interval_s=0.005, trace_log_path=trace_log_path, **coordinator_kwargs)
        robot_link = RobotLink.bind(self.bus, self.coordinator.robot_instance, resolved.instance("robot1").module)
        self.robot = SimulatedRobot(script=script, link=robot_link, poll_interval_s=0.005)

        recipes = {
            "load_screw": default_load_screw_recipe,
            "drive_screw": make_drive_screw_recipe(result_ok_for=drive_screw_result_ok_for or (lambda hole_id: True)),
        }
        self.module = SimulatedPackMLModule(bus=self.bus, instance="sd1", recipes=recipes, op_delay_s=op_delay_s, poll_interval_s=0.005)

    async def run(self, timeout: float = 10.0):
        module_task = asyncio.create_task(self.module.run())
        coordinator_task = asyncio.ensure_future(self.coordinator.run())
        robot_task = asyncio.ensure_future(self.robot.run())
        try:
            results = await asyncio.wait_for(
                asyncio.gather(coordinator_task, robot_task, return_exceptions=True), timeout=timeout
            )
        finally:
            self.module.stop()
            module_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await module_task
        return results  # [CoordinatorResult, None | RobotAborted]


# ---------------------------------------------------------------------------
# The full sequence completes
# ---------------------------------------------------------------------------


def test_full_three_hole_sequence_completes(repo_root: Path):
    resolved, script = _build_script(repo_root, _BRACKET_HOLES, ["hole_1", "hole_2", "hole_3"])
    loop = _Loopback(resolved, script)

    coordinator_result, robot_outcome = asyncio.run(loop.run())

    assert robot_outcome is None  # the robot ran to completion, no RobotAborted
    assert not coordinator_result.aborted
    assert [entry.hole_id for entry in coordinator_result.trace] == ["hole_1", "hole_2", "hole_3"]
    assert all(entry.result_ok for entry in coordinator_result.trace)
    assert all(entry.torque_achieved is not None and entry.angle_achieved is not None for entry in coordinator_result.trace)
    assert loop.robot.reached_steps == [1, 2, 3, 4, 5, 6]


def test_trace_is_written_as_a_json_traceability_log(repo_root: Path, tmp_path: Path):
    resolved, script = _build_script(repo_root, _BRACKET_HOLES, ["hole_1", "hole_2", "hole_3"])
    log_path = tmp_path / "trace.json"
    loop = _Loopback(resolved, script, trace_log_path=log_path)

    coordinator_result, _ = asyncio.run(loop.run())

    assert log_path.is_file()
    logged = json.loads(log_path.read_text(encoding="utf-8"))
    assert logged["aborted"] is False
    assert [row["hole_id"] for row in logged["trace"]] == ["hole_1", "hole_2", "hole_3"]
    assert all(row["result_ok"] for row in logged["trace"])
    assert all(isinstance(row["torque_achieved"], float) for row in logged["trace"])
    assert len(logged["trace"]) == len(coordinator_result.trace)


# ---------------------------------------------------------------------------
# The coordinator withholds done_step while screw_present is false, and the
# robot provably waits (not an instant pass-through)
# ---------------------------------------------------------------------------


def test_coordinator_withholds_done_step_while_screw_present_is_false(repo_root: Path):
    # A deliberately slow load_screw: the coordinator can't write
    # hs_done_step for the standoff sync until drive_screw's own
    # screw_present precondition holds, and that precondition only
    # becomes true once this (simulated, but genuinely delayed) op
    # actually finishes.
    load_delay_s = 0.15
    resolved, script = _build_script(repo_root, {"hole_1": [12, 12, 0]}, ["hole_1"])
    loop = _Loopback(resolved, script, op_delay_s=load_delay_s / 2)  # STARTING + EXECUTE = load_delay_s

    t0 = time.monotonic()
    coordinator_result, robot_outcome = asyncio.run(loop.run())
    elapsed = time.monotonic() - t0

    assert robot_outcome is None
    assert not coordinator_result.aborted
    # Real elapsed wall-clock time, not merely "the coordinator's own
    # counters advanced" -- proves the wait was actually a wait.
    assert elapsed >= load_delay_s * 0.75, f"finished suspiciously fast ({elapsed:.3f}s) for a {load_delay_s}s op delay"
    # And the robot's own wait loop (spec/08's heartbeat-incrementing poll)
    # genuinely iterated more than once or twice -- not a single glance.
    assert loop.robot.wait_iterations[1] >= 5, loop.robot.wait_iterations


# ---------------------------------------------------------------------------
# A forced result_ok=false on hole 2 triggers abort
# ---------------------------------------------------------------------------


def test_forced_result_ok_false_on_hole_2_triggers_abort(repo_root: Path):
    resolved, script = _build_script(repo_root, _BRACKET_HOLES, ["hole_1", "hole_2", "hole_3"])
    loop = _Loopback(resolved, script, drive_screw_result_ok_for=lambda hole_id: hole_id != "hole_2")

    coordinator_result, robot_outcome = asyncio.run(loop.run())

    assert coordinator_result.aborted
    assert coordinator_result.abort_reason == "drive_screw result_ok=false @ hole_2"
    assert [entry.hole_id for entry in coordinator_result.trace] == ["hole_1", "hole_2"]
    assert coordinator_result.trace[0].result_ok is True
    assert coordinator_result.trace[1].result_ok is False

    # The robot actually halted (hs_abort, per spec/08's Abort section) --
    # not just "the coordinator decided to stop on its own side".
    assert isinstance(robot_outcome, RobotAborted)
    # It reached hole 2's contact sync (step 4) and stalled there -- it
    # never got anywhere near hole 3 (steps 5, 6).
    assert loop.robot.reached_steps == [1, 2, 3, 4]


# ---------------------------------------------------------------------------
# The robot dies mid-sequence -> HeartbeatStaleError within the timeout window
# ---------------------------------------------------------------------------


def test_robot_dying_mid_sequence_raises_heartbeat_stale_error_within_the_window(repo_root: Path):
    # spec/08: "hs_heartbeat static for > 2s while a program should be
    # running = robot program dead or connection lost -> coordinator
    # faults the cell." A short heartbeat_timeout_s here so the test
    # doesn't wait around for the real 2s default.
    heartbeat_timeout_s = 0.15
    resolved, script = _build_script(repo_root, _BRACKET_HOLES, ["hole_1", "hole_2", "hole_3"])
    loop = _Loopback(resolved, script, heartbeat_timeout_s=heartbeat_timeout_s)

    async def scenario() -> float:
        module_task = asyncio.create_task(loop.module.run())
        robot_task = asyncio.ensure_future(loop.robot.run())
        coordinator_task = asyncio.ensure_future(loop.coordinator.run())
        try:
            # Let the sequence make real progress -- all the way through
            # hole 1 and into hole 2's standoff sync -- before the robot
            # dies. hs_heartbeat has been genuinely advancing up to this
            # point; from here it's frozen forever, mid-sequence, with the
            # coordinator still waiting on it (screw_present for hole 2,
            # then its own contact sync).
            while len(loop.robot.reached_steps) < 3:  # standoff_1, contact_1, standoff_2
                assert not coordinator_task.done(), "coordinator finished before the robot could be killed"
                await asyncio.sleep(0.005)

            robot_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await robot_task
            robot_died_at = time.monotonic()

            with pytest.raises(HeartbeatStaleError):
                await coordinator_task

            return time.monotonic() - robot_died_at
        finally:
            loop.module.stop()
            module_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await module_task

    elapsed = asyncio.run(asyncio.wait_for(scenario(), timeout=5))

    # Fires close to heartbeat_timeout_s after the robot actually stopped
    # updating hs_heartbeat -- not immediately (it must genuinely observe
    # staleness, not just "no heartbeat yet") and not after some unrelated
    # longer timeout.
    assert heartbeat_timeout_s * 0.5 <= elapsed <= heartbeat_timeout_s * 4, (
        f"HeartbeatStaleError fired outside the expected window: {elapsed:.3f}s "
        f"(heartbeat_timeout_s={heartbeat_timeout_s})"
    )
