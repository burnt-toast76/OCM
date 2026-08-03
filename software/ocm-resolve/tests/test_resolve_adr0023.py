# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0023 resolve-time refusals: conditions and requirement bindings resolve
statically, not at runtime. Each of the four codes, positive and negative.

The refusals here are plain strings (ocm-resolve's contract); ocm-api's
translate.py maps them to the CONDITION_UNKNOWN_SIGNAL / REQUIREMENT_UNBOUND /
REQUIREMENT_UNKNOWN_TARGET / TIMEOUT_DISPOSITION_CONFLICT codes. These tests
assert the detection; the code mapping is exercised in ocm-api's own suite.
"""

from __future__ import annotations

from typing import Any

import pytest

from ocm_core.cell import Cell
from ocm_resolve import resolve_cell
from ocm_resolve.errors import CellResolutionError

from .conftest import (
    build_cell_dict,
    minimal_base_manifest,
    minimal_robot_manifest,
    minimal_tool_manifest,
    write_module,
)


def _cap(**overrides: Any) -> dict[str, Any]:
    # torque_nm matches the op params build_cell_dict's default plan passes,
    # so a resolve that's meant to be clean isn't polluted by UNKNOWN_PARAM.
    cap: dict[str, Any] = {
        "name": "drive_screw",
        "summary": "Drive a screw.",
        "parameters": {"torque_nm": {"type": "number", "unit": "N.m", "min": 0.2, "max": 5.0}},
        "timeout_s": 6.0,
        "on_timeout": "abort",
    }
    cap.update(overrides)
    return cap


def _tool_with(cap: dict[str, Any], *, signals: list[dict[str, Any]] | None = None, abort_safe: bool = False) -> dict[str, Any]:
    tool = minimal_tool_manifest(capabilities=[cap])
    tool["comms"] = {"protocol": "ethercat", "signals": signals or []}
    tool["state_machine"] = {"model": "packml", "implements": ["idle", "execute"], "abort_safe": abort_safe}
    return tool


def _search_root(tmp_path, tool: dict[str, Any]):
    root = tmp_path / "modules"
    write_module(root, minimal_base_manifest())
    write_module(root, minimal_robot_manifest())
    write_module(root, tool)
    return root


def _resolve(root, cell_dict: dict[str, Any]) -> list[str]:
    """Return the list of resolution error strings (empty if the cell resolves)."""
    try:
        resolve_cell(Cell.from_dict(cell_dict), root)
        return []
    except CellResolutionError as e:
        return list(e.errors)


# ---------------------------------------------------------------------------
# CONDITION_UNKNOWN_SIGNAL
# ---------------------------------------------------------------------------


def test_condition_unknown_signal_is_refused(tmp_path):
    tool = _tool_with(_cap(preconditions=["nonexistent_flag == true"]))
    root = _search_root(tmp_path, tool)
    errors = _resolve(root, build_cell_dict())
    assert any("'nonexistent_flag'" in e and "neither a comms signal nor a declared requires key" in e for e in errors), errors


def test_condition_naming_a_real_signal_is_accepted(tmp_path):
    tool = _tool_with(
        _cap(preconditions=["ready == true"]),
        signals=[{"name": "ready", "direction": "input", "type": "bool"}],
    )
    root = _search_root(tmp_path, tool)
    assert _resolve(root, build_cell_dict()) == []


def test_condition_naming_a_requires_key_is_accepted(tmp_path):
    # A precondition may name a requires key (bound by the cell), not only a
    # local comms signal -- and a `>` operator resolves on its identifier.
    tool = _tool_with(
        _cap(
            requires={"workpiece_secured": {"type": "bool", "summary": "held"}},
            preconditions=["workpiece_secured == true"],
        ),
        signals=[{"name": "held_here", "direction": "input", "type": "bool"}],
    )
    root = _search_root(tmp_path, tool)
    modules = [
        {"instance": "robot1", "module": "com.example.robot.tiny@1.0.0", "mount": {"station": [100, 100], "pose": {"xyz_mm": [100, 100, 0]}}},
        {
            "instance": "tool1",
            "module": "com.example.tool.tiny@1.0.0",
            "mount": {"on": "robot1.flange"},
            "requires": {"workpiece_secured": "tool1.held_here"},
        },
    ]
    assert _resolve(root, build_cell_dict(modules=modules)) == []


# ---------------------------------------------------------------------------
# REQUIREMENT_UNBOUND
# ---------------------------------------------------------------------------


def test_requirement_unbound_is_refused_and_hint_names_input_bool_instances(tmp_path):
    tool = _tool_with(
        _cap(requires={"workpiece_secured": {"type": "bool", "summary": "held"}}),
        signals=[{"name": "held_here", "direction": "input", "type": "bool"}],
    )
    root = _search_root(tmp_path, tool)
    errors = _resolve(root, build_cell_dict())  # default cell places tool1 with NO binding
    unbound = [e for e in errors if "requires 'workpiece_secured'" in e and "binds to nothing" in e]
    assert unbound, errors
    # the hint lists this cell's instances that declare an input bool -- here, tool1 itself
    assert "'tool1'" in unbound[0]


def test_requirement_bound_to_a_real_signal_resolves(tmp_path):
    tool = _tool_with(
        _cap(requires={"workpiece_secured": {"type": "bool", "summary": "held"}}),
        signals=[{"name": "held_here", "direction": "input", "type": "bool"}],
    )
    root = _search_root(tmp_path, tool)
    modules = [
        {"instance": "robot1", "module": "com.example.robot.tiny@1.0.0", "mount": {"station": [100, 100], "pose": {"xyz_mm": [100, 100, 0]}}},
        {
            "instance": "tool1",
            "module": "com.example.tool.tiny@1.0.0",
            "mount": {"on": "robot1.flange"},
            "requires": {"workpiece_secured": "tool1.held_here"},
        },
    ]
    assert _resolve(root, build_cell_dict(modules=modules)) == []


# ---------------------------------------------------------------------------
# REQUIREMENT_UNKNOWN_TARGET
# ---------------------------------------------------------------------------


def test_requirement_bound_to_unknown_instance_is_refused(tmp_path):
    tool = _tool_with(_cap(requires={"workpiece_secured": {"type": "bool", "summary": "held"}}))
    root = _search_root(tmp_path, tool)
    modules = [
        {"instance": "robot1", "module": "com.example.robot.tiny@1.0.0", "mount": {"station": [100, 100], "pose": {"xyz_mm": [100, 100, 0]}}},
        {
            "instance": "tool1",
            "module": "com.example.tool.tiny@1.0.0",
            "mount": {"on": "robot1.flange"},
            "requires": {"workpiece_secured": "ghost.clamped"},
        },
    ]
    errors = _resolve(root, build_cell_dict(modules=modules))
    assert any("no instance 'ghost'" in e for e in errors), errors


def test_requirement_bound_to_unknown_signal_is_refused(tmp_path):
    tool = _tool_with(
        _cap(requires={"workpiece_secured": {"type": "bool", "summary": "held"}}),
        signals=[{"name": "held_here", "direction": "input", "type": "bool"}],
    )
    root = _search_root(tmp_path, tool)
    modules = [
        {"instance": "robot1", "module": "com.example.robot.tiny@1.0.0", "mount": {"station": [100, 100], "pose": {"xyz_mm": [100, 100, 0]}}},
        {
            "instance": "tool1",
            "module": "com.example.tool.tiny@1.0.0",
            "mount": {"on": "robot1.flange"},
            "requires": {"workpiece_secured": "tool1.no_such_signal"},
        },
    ]
    errors = _resolve(root, build_cell_dict(modules=modules))
    assert any("declares no signal 'no_such_signal'" in e for e in errors), errors


# ---------------------------------------------------------------------------
# TIMEOUT_DISPOSITION_CONFLICT
# ---------------------------------------------------------------------------


def test_on_timeout_hold_on_a_not_abort_safe_capability_is_refused(tmp_path):
    tool = _tool_with(_cap(on_timeout="hold"), abort_safe=False)
    root = _search_root(tmp_path, tool)
    errors = _resolve(root, build_cell_dict())
    assert any("on_timeout 'hold'" in e and "abort_safe is false" in e for e in errors), errors


def test_on_timeout_hold_on_an_abort_safe_capability_resolves(tmp_path):
    tool = _tool_with(_cap(on_timeout="hold"), abort_safe=True)
    root = _search_root(tmp_path, tool)
    assert _resolve(root, build_cell_dict()) == []


# ---------------------------------------------------------------------------
# Every committed module resolves without a CONDITION_UNKNOWN_SIGNAL -- the
# resolve-time replacement for the runtime PreconditionError is satisfied by
# the real manifests (including dh200's `>` conditions).
# ---------------------------------------------------------------------------


def test_real_bracket_cell_has_no_condition_or_requirement_refusals(repo_root):
    from ocm_core.loader import load_cell

    cell = load_cell(repo_root / "cells" / "bracket-asm-01" / "cell.yaml")
    resolve_cell(cell, repo_root / "modules")  # must not raise
