# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from ocm_core.cell import Cell
from ocm_resolve import CellResolutionError, resolve_cell

from .conftest import build_cell_dict


def test_collects_every_violation_across_all_checks_not_just_the_first(search_root):
    # Deliberately trip a missing-module, a dangling-mount, and an
    # unknown-op violation in the same cell. If resolve_cell stopped at the
    # first problem, only one of these three would show up in the errors.
    data = build_cell_dict(
        modules=[
            {
                "instance": "robot1",
                "module": "com.example.robot.tiny@1.0.0",
                "mount": {"station": [100, 100]},
            },
            {"instance": "ghost1", "module": "com.example.ghost.nope@9.9.9"},
            {
                "instance": "tool1",
                "module": "com.example.tool.tiny@1.0.0",
                "mount": {"on": "robotX.flange"},  # dangling
            },
        ],
        plan=[
            {"step": "fasten", "module": "tool1", "op": "levitate", "params": {"torque_nm": 2.4}},
        ],
    )
    cell = Cell.from_dict(data)

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, search_root)

    errors = exc.value.errors
    assert len(errors) >= 3
    assert any("com.example.ghost.nope@9.9.9" in e and "not found" in e for e in errors)
    assert any(
        "tool1" in e and "robotX" in e and "unknown module instance" in e for e in errors
    )
    assert any("levitate" in e and "no op" in e for e in errors)
