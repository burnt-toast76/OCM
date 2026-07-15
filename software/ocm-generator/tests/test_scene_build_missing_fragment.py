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


def test_urdf_fragment_file_not_on_disk_is_reported_clearly(tmp_path):
    root = tmp_path / "modules"
    write_module(root, minimal_base_manifest(), "base.urdf", fragment_xml("origin"))
    # manifest declares a urdf_fragment path, but the file is never written
    write_module(root, minimal_robot_manifest())
    write_module(root, minimal_tool_manifest(), "tool.urdf", fragment_xml("origin"))

    cell = Cell.from_dict(build_cell_dict())
    resolved = resolve_cell(cell, root)

    with pytest.raises(SceneBuildError) as exc:
        build_scene(resolved, root)

    assert any("robot1" in e and "not found" in e for e in exc.value.errors)


def test_urdf_fragment_field_absent_is_reported_clearly(tmp_path):
    root = tmp_path / "modules"
    write_module(root, minimal_base_manifest(), "base.urdf", fragment_xml("origin"))
    write_module(root, minimal_robot_manifest(), "robot.urdf", fragment_xml("origin", extra_link="flange"))
    # tool1's manifest has no urdf_fragment at all (schema-valid: only kind=robot requires it)
    write_module(root, minimal_tool_manifest(urdf_fragment=None))

    cell = Cell.from_dict(build_cell_dict())
    resolved = resolve_cell(cell, root)

    with pytest.raises(SceneBuildError) as exc:
        build_scene(resolved, root)

    assert any("tool1" in e and "declares no" in e for e in exc.value.errors)


def test_base_missing_fragment_is_reported_clearly(tmp_path):
    root = tmp_path / "modules"
    write_module(root, minimal_base_manifest())  # no fragment file written
    write_module(root, minimal_robot_manifest(), "robot.urdf", fragment_xml("origin", extra_link="flange"))
    write_module(root, minimal_tool_manifest(), "tool.urdf", fragment_xml("origin"))

    cell = Cell.from_dict(build_cell_dict())
    resolved = resolve_cell(cell, root)

    with pytest.raises(SceneBuildError) as exc:
        build_scene(resolved, root)

    assert any("base" in e and "not found" in e for e in exc.value.errors)
