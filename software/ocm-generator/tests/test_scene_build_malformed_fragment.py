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


def test_malformed_xml_fragment_is_reported_clearly(tmp_path):
    root = tmp_path / "modules"
    write_module(root, minimal_base_manifest(), "base.urdf", fragment_xml("origin"))
    write_module(root, minimal_robot_manifest(), "robot.urdf", fragment_xml("origin", extra_link="flange"))
    write_module(root, minimal_tool_manifest(), "tool.urdf", "<robot><link name='unterminated></robot>")

    cell = Cell.from_dict(build_cell_dict())
    resolved = resolve_cell(cell, root)

    with pytest.raises(SceneBuildError) as exc:
        build_scene(resolved, root)

    assert any("tool1" in e and "not well-formed XML" in e for e in exc.value.errors)


def test_disconnected_fragment_with_two_roots_is_reported_clearly(tmp_path):
    two_root_fragment = """<?xml version="1.0"?>
<robot name="frag">
  <link name="origin"><collision><geometry><box size="0.05 0.05 0.05"/></geometry></collision></link>
  <link name="stray"><collision><geometry><box size="0.02 0.02 0.02"/></geometry></collision></link>
</robot>"""
    root = tmp_path / "modules"
    write_module(root, minimal_base_manifest(), "base.urdf", fragment_xml("origin"))
    write_module(root, minimal_robot_manifest(), "robot.urdf", fragment_xml("origin", extra_link="flange"))
    write_module(root, minimal_tool_manifest(), "tool.urdf", two_root_fragment)

    cell = Cell.from_dict(build_cell_dict())
    resolved = resolve_cell(cell, root)

    with pytest.raises(SceneBuildError) as exc:
        build_scene(resolved, root)

    assert any("tool1" in e and "exactly one root link" in e for e in exc.value.errors)
