# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from ocm_core.cell import Cell
from ocm_resolve import CellResolutionError, resolve_cell

from .conftest import build_cell_dict


def test_dangling_mount_on_reference_is_reported_clearly(search_root):
    data = build_cell_dict(
        modules=[
            {
                "instance": "robot1",
                "module": "com.example.robot.tiny@1.0.0",
                "mount": {"station": [100, 100]},
            },
            {
                "instance": "tool1",
                "module": "com.example.tool.tiny@1.0.0",
                "mount": {"on": "robotX.flange"},  # robotX was never declared
            },
        ],
        plan=[],
    )
    cell = Cell.from_dict(data)

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, search_root)

    assert any(
        "tool1" in e and "robotX" in e and "unknown module instance" in e
        for e in exc.value.errors
    )


def test_malformed_mount_on_format_is_rejected(search_root):
    data = build_cell_dict(
        modules=[
            {
                "instance": "robot1",
                "module": "com.example.robot.tiny@1.0.0",
                "mount": {"station": [100, 100]},
            },
            {
                "instance": "tool1",
                "module": "com.example.tool.tiny@1.0.0",
                "mount": {"on": "robot1"},  # missing '.attachment'
            },
        ],
        plan=[],
    )
    cell = Cell.from_dict(data)

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, search_root)

    assert any("tool1" in e and "malformed" in e for e in exc.value.errors)


def test_mount_on_a_module_that_itself_failed_to_load_is_a_dangling_reference(search_root):
    # robot1's own manifest doesn't exist, so tool1's 'on: robot1.flange'
    # can't be resolved either -- both should be reported, not just one.
    data = build_cell_dict(
        modules=[
            {"instance": "robot1", "module": "com.example.ghost.robot@1.0.0"},
            {
                "instance": "tool1",
                "module": "com.example.tool.tiny@1.0.0",
                "mount": {"on": "robot1.flange"},
            },
        ],
        plan=[],
    )
    cell = Cell.from_dict(data)

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, search_root)

    errors = exc.value.errors
    assert any("com.example.ghost.robot@1.0.0" in e and "not found" in e for e in errors)
    assert any("tool1" in e and "robot1" in e and "unknown module instance" in e for e in errors)
