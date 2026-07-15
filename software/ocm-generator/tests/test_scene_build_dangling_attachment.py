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


def test_mount_on_unknown_attachment_link_is_reported_clearly(modules_root):
    # robot1's fragment only has links "origin" and "flange" -- "gripper_port"
    # doesn't exist. ocm_resolve has no way to catch this (it doesn't parse
    # URDF); this is specifically what the scene loader adds.
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
                    "mount": {"on": "robot1.gripper_port"},
                },
            ]
        )
    )
    resolved = resolve_cell(cell, modules_root)

    with pytest.raises(SceneBuildError) as exc:
        build_scene(resolved, modules_root)

    assert any(
        "tool1" in e and "gripper_port" in e and "robot1__flange" in e for e in exc.value.errors
    )


def test_mount_on_a_target_whose_own_geometry_failed_to_load_is_reported_clearly(tmp_path):
    # robot1's manifest declares a urdf_fragment, but the file is missing --
    # tool1 mounted on it should fail too, and BOTH should show up.
    root = tmp_path / "modules"
    write_module(root, minimal_base_manifest(), "base.urdf", fragment_xml("origin"))
    write_module(root, minimal_robot_manifest())  # no fragment file
    write_module(root, minimal_tool_manifest(), "tool.urdf", fragment_xml("origin"))

    cell = Cell.from_dict(build_cell_dict())  # tool1 mounts on robot1.flange
    resolved = resolve_cell(cell, root)

    with pytest.raises(SceneBuildError) as exc:
        build_scene(resolved, root)

    errors = exc.value.errors
    assert any("robot1" in e and "not found" in e for e in errors)
    assert any("tool1" in e and "cannot attach on 'robot1'" in e for e in errors)
