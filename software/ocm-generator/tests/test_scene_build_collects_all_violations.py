# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from ocm_core.cell import Cell
from ocm_generator.scene import SceneBuildError, build_scene
from ocm_resolve import resolve_cell

from .conftest import (
    build_cell_dict,
    fragment_xml,
    minimal_base_manifest,
    minimal_robot_manifest,
    minimal_tool_manifest,
    write_module,
)


def test_collects_every_violation_across_all_checks_not_just_the_first(tmp_path):
    # Trip a missing-fragment (base), a malformed-fragment (robot1), and a
    # dangling mount.on attachment (tool2 -> tool1, which has no 'aux_port'
    # link) all in the same cell. Stopping at the first would hide the rest.
    root = tmp_path / "modules"
    write_module(root, minimal_base_manifest())  # no fragment file -> missing
    write_module(root, minimal_robot_manifest(), "robot.urdf", "<robot><link name='x></robot>")  # malformed
    write_module(root, minimal_tool_manifest(), "tool.urdf", fragment_xml("origin"))  # fine, but no 'aux_port' link

    cell = Cell.from_dict(
        build_cell_dict(
            modules=[
                {
                    "instance": "robot1",
                    "module": "com.example.robot.tiny@1.0.0",
                    "mount": {"pose": {"xyz_mm": [0, 0, 0]}},
                },
                {
                    "instance": "tool1",
                    "module": "com.example.tool.tiny@1.0.0",
                    "mount": {"pose": {"xyz_mm": [100, 0, 0]}},
                },
                {
                    "instance": "tool2",
                    "module": "com.example.tool.tiny@1.0.0",
                    "mount": {"on": "tool1.aux_port"},
                },
            ]
        )
    )
    resolved = resolve_cell(cell, root)

    with pytest.raises(SceneBuildError) as exc:
        build_scene(resolved, root)

    errors = exc.value.errors
    assert len(errors) >= 3
    assert any("base" in e and "not found" in e for e in errors)
    assert any("robot1" in e and "not well-formed XML" in e for e in errors)
    assert any("tool2" in e and "aux_port" in e for e in errors)
