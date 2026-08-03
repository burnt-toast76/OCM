# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0023 coordinator logic, exercised WITHOUT the tesseract extra: binding
resolution, cross-instance preconditions, postcondition verification, and
per-op timeout disposition. None of this needs IK or a built scene -- resolve
loads the real sd50/pneumatic-nest manifests, and the coordinator's own
condition/timeout machinery runs against a plain SimulatedSignalBus. The full
loopback proof (which does need tesseract to emit the URScript it runs) lives
in test_coordinator.py.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from ocm_core import Capability
from ocm_core.cell import Cell
from ocm_resolve import resolve_cell
from ocm_generator.coordinator import Coordinator, SimulatedSignalBus
from ocm_generator.coordinator.errors import PreconditionError, OpTimeoutError
from ocm_generator.coordinator.packml import (
    PackMLCommand,
    PackMLState,
    _check_condition,
    failing_postconditions,
    preconditions_met,
)

_HOME = {"shoulder_lift_joint": -1.5707963267948966, "elbow_joint": 1.5707963267948966}


def _camera_free_cell() -> dict[str, Any]:
    """robot1 + sd1 (sd50) + nest1 (pneumatic-nest), sd1 binding its
    workpiece_secured requirement to nest1.clamped -- the dogfood interlock,
    minus the camera (whose x-gocator-gsdk protocol has no coordinator driver).
    """
    return {
        "ocm_version": "1.0",
        "kind": "cell",
        "id": "com.example.cell.coordinator-conditions",
        "license": "CERN-OHL-S-2.0",
        "base": {"module": "com.accelsolutions.base.frame1200@2.0.0", "datum": "cell_origin", "grid": "ocm-base-grid-50"},
        "modules": [
            {"instance": "robot1", "module": "com.universal-robots.ur5e@3.1.0",
             "mount": {"station": [400, 300], "pose": {"xyz_mm": [400, 300, 0], "rpy_deg": [0, 0, 0]}}, "joint_state": dict(_HOME)},
            {"instance": "sd1", "module": "com.accelsolutions.screwdriver.sd50@1.2.0",
             "mount": {"on": "robot1.flange"}, "requires": {"workpiece_secured": "nest1.clamped"}},
            {"instance": "nest1", "module": "com.accelsolutions.fixture.pneumatic-nest@1.1.0",
             "mount": {"pose": {"xyz_mm": [640, 300, 0], "rpy_deg": [0, 0, 90]}}},
        ],
        "part": {"id": "BRK", "features": {"hole_1": {"xyz_mm": [12, 12, 0], "normal": [0, 0, 1]}}},
        "plan": [
            {"step": "clamp", "module": "nest1", "op": "clamp", "params": {"force_n": 120}},
            {"step": "fasten", "for_each": ["hole_1"], "sequence": [
                {"module": "sd1", "op": "load_screw"},
                {"module": "sd1", "op": "drive_screw", "at": "part.features.${item}", "params": {"torque_nm": 2.4, "depth_mm": 8.0}},
            ]},
            {"step": "release", "module": "nest1", "op": "unclamp"},
        ],
    }


@pytest.fixture
def coordinator(repo_root: Path) -> Coordinator:
    cell = Cell.from_dict(_camera_free_cell())
    resolved = resolve_cell(cell, repo_root / "modules")
    return Coordinator(resolved, SimulatedSignalBus())


def test_bindings_resolve_the_requires_key_to_the_peer_instance_signal(coordinator: Coordinator):
    assert coordinator.bindings == {"workpiece_secured": ("nest1", "clamped")}


# ---------------------------------------------------------------------------
# The ADR's whole point: sd1 will not descend to contact until nest1 reports
# the part clamped -- a cross-INSTANCE interlock, expressed with no plan syntax.
# ---------------------------------------------------------------------------


def test_drive_screw_blocks_while_nest1_clamped_is_false_and_proceeds_when_it_goes_true(coordinator: Coordinator):
    async def scenario() -> None:
        bus = coordinator.bus
        await bus.write("sd1", "screw_present", True)   # sd1's own local precondition satisfied
        await bus.write("nest1", "clamped", False)      # ...but the peer says the part is not held

        assert not await preconditions_met(bus, "sd1", coordinator.drive_screw, coordinator.bindings)

        waiter = asyncio.ensure_future(coordinator._wait_for_preconditions("sd1", coordinator.drive_screw))
        await asyncio.sleep(0.05)
        assert not waiter.done(), "drive_screw proceeded while nest1.clamped was still false"

        await bus.write("nest1", "clamped", True)       # the nest finishes clamping
        await asyncio.wait_for(waiter, timeout=2.0)     # ...and only now does the gate open
        assert await preconditions_met(bus, "sd1", coordinator.drive_screw, coordinator.bindings)

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Decision 2: PackML Complete is not believed on its own.
# ---------------------------------------------------------------------------


def test_complete_with_a_false_postcondition_is_detected(coordinator: Coordinator):
    async def scenario() -> None:
        bus = coordinator.bus
        # The C.2/C.4 lie: result_ok true (happy path) but the screw is still
        # on the bit, so drive_screw's `screw_present == false` postcondition
        # reads false against the live bus.
        await bus.write("sd1", "result_ok", True)
        await bus.write("sd1", "screw_present", True)
        failing = await failing_postconditions(bus, "sd1", coordinator.drive_screw, coordinator.bindings)
        assert "screw_present == false" in failing
        assert "result_ok == true" not in failing  # that one genuinely holds

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Decision 6: per-op timeout, disposed by the capability's own on_timeout.
# ---------------------------------------------------------------------------


def _cap_with(on_timeout: str, timeout_s: float, preconditions: list[str]) -> Capability:
    return Capability.from_dict({
        "name": "test_op",
        "summary": "x",
        "preconditions": preconditions,
        "timeout_s": timeout_s,
        "on_timeout": on_timeout,
    })


def test_precondition_timeout_with_on_timeout_hold_lands_in_held_not_aborted(coordinator: Coordinator):
    hold_cap = _cap_with("hold", 0.05, ["clamped == true"])  # local to nest1, never satisfied

    async def scenario() -> None:
        bus = coordinator.bus
        await bus.write("nest1", "clamped", False)

        with pytest.raises(OpTimeoutError) as exc:
            await coordinator._wait_for_preconditions("nest1", hold_cap)
        assert exc.value.on_timeout == "hold"

        result = await coordinator._dispose_timeout(exc.value, [])
        assert result.held is True
        assert result.aborted is False
        # command PackML Hold, not Abort
        assert await bus.read(coordinator.tool_instance, "packml_cmd") == int(PackMLCommand.HOLD)

    asyncio.run(scenario())


def test_precondition_timeout_with_on_timeout_abort_surfaces_for_on_fail(coordinator: Coordinator):
    abort_cap = _cap_with("abort", 0.05, ["screw_present == true"])  # local to sd1, never satisfied

    async def scenario() -> None:
        bus = coordinator.bus
        await bus.write("sd1", "screw_present", False)

        with pytest.raises(OpTimeoutError) as exc:
            await coordinator._wait_for_preconditions("sd1", abort_cap)
        assert exc.value.on_timeout == "abort"

        result = await coordinator._dispose_timeout(exc.value, [])
        assert result.aborted is True
        assert result.held is False

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Decision 5: the runtime PreconditionError is now a backstop -- present, but
# unreachable from a validated manifest (whose condition signals all resolve).
# ---------------------------------------------------------------------------


def test_check_condition_still_raises_on_an_unknown_signal_as_a_backstop():
    # This is the raise CONDITION_UNKNOWN_SIGNAL now pre-empts at resolve time.
    with pytest.raises(PreconditionError):
        _check_condition("bogus == true", {})


def test_validated_manifest_never_reaches_the_runtime_precondition_error(coordinator: Coordinator):
    # Every signal drive_screw's conditions name resolves to a value the
    # coordinator supplies, so _check_condition's "unknown signal" raise is
    # unreachable: preconditions_met evaluates cleanly, never raising.
    async def scenario() -> None:
        bus = coordinator.bus
        await bus.write("sd1", "screw_present", True)
        await bus.write("nest1", "clamped", True)
        # No PreconditionError -- the validated manifest's conditions all resolve.
        assert await preconditions_met(bus, "sd1", coordinator.drive_screw, coordinator.bindings) is True

    asyncio.run(scenario())
