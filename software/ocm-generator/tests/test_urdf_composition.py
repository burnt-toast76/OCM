# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for ocm_generator.scene.urdf -- pure XML parsing/namespacing,
no tesseract_robotics involved. Kept separate from the Environment-backed
tests deliberately: this is where fragment-composition correctness
(root-link detection, renaming, mesh path resolution) actually gets
verified, without going anywhere near Tesseract's Python bindings.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ocm_generator.scene.errors import FragmentError
from ocm_generator.scene.urdf import find_root_link, load_fragment, namespace_fragment

from .conftest import fragment_xml


def _parse(xml_text: str) -> ET.Element:
    return ET.fromstring(xml_text)


def test_find_root_link_single_link():
    root = _parse(fragment_xml("origin"))
    assert find_root_link(root, Path("frag.urdf")) == "origin"


def test_find_root_link_two_links():
    root = _parse(fragment_xml("origin", extra_link="flange"))
    assert find_root_link(root, Path("frag.urdf")) == "origin"


def test_find_root_link_rejects_two_roots():
    xml_text = """<?xml version="1.0"?>
<robot name="frag">
  <link name="a"/>
  <link name="b"/>
</robot>"""
    with pytest.raises(FragmentError, match="expected exactly one root link"):
        find_root_link(_parse(xml_text), Path("frag.urdf"))


def test_find_root_link_rejects_zero_links():
    xml_text = '<?xml version="1.0"?><robot name="frag"></robot>'
    with pytest.raises(FragmentError, match="expected exactly one root link"):
        find_root_link(_parse(xml_text), Path("frag.urdf"))


def test_namespace_fragment_renames_links_and_joints(tmp_path: Path):
    root = _parse(fragment_xml("origin", extra_link="flange", extra_xyz=(0.0, 0.0, 0.4)))

    links, joints, root_link = namespace_fragment(root, "robot1", tmp_path, tmp_path / "frag.urdf")

    assert root_link == "robot1__origin"
    assert {link.get("name") for link in links} == {"robot1__origin", "robot1__flange"}
    (joint,) = joints
    assert joint.find("parent").get("link") == "robot1__origin"
    assert joint.find("child").get("link") == "robot1__flange"


def test_namespace_fragment_resolves_relative_mesh_paths(tmp_path: Path):
    xml_text = """<?xml version="1.0"?>
<robot name="frag">
  <link name="origin">
    <collision><geometry><mesh filename="meshes/foo_convex.stl"/></geometry></collision>
  </link>
</robot>"""
    root = _parse(xml_text)

    links, _joints, _root_link = namespace_fragment(root, "tool1", tmp_path, tmp_path / "frag.urdf")

    mesh = links[0].find(".//mesh")
    resolved = Path(mesh.get("filename"))
    assert resolved.is_absolute()
    assert resolved == (tmp_path / "meshes" / "foo_convex.stl").resolve()


def test_namespace_fragment_leaves_absolute_mesh_paths_alone(tmp_path: Path):
    absolute = (tmp_path / "elsewhere" / "foo.stl").resolve()
    xml_text = f"""<?xml version="1.0"?>
<robot name="frag">
  <link name="origin">
    <collision><geometry><mesh filename="{absolute.as_posix()}"/></geometry></collision>
  </link>
</robot>"""
    root = _parse(xml_text)

    links, _joints, _root_link = namespace_fragment(root, "tool1", tmp_path, tmp_path / "frag.urdf")

    mesh = links[0].find(".//mesh")
    assert Path(mesh.get("filename")) == absolute


def test_load_fragment_missing_file_raises_clearly(tmp_path: Path):
    with pytest.raises(FragmentError, match="not found"):
        load_fragment(tmp_path / "nope.urdf")


def test_load_fragment_malformed_xml_raises_clearly(tmp_path: Path):
    bad = tmp_path / "bad.urdf"
    bad.write_text("<robot><link name='unterminated></robot>", encoding="utf-8")
    with pytest.raises(FragmentError, match="not well-formed XML"):
        load_fragment(bad)


def test_joint_missing_child_element_raises_clearly():
    xml_text = """<?xml version="1.0"?>
<robot name="frag">
  <link name="a"/>
  <link name="b"/>
  <joint name="j1" type="fixed">
    <parent link="a"/>
  </joint>
</robot>"""
    with pytest.raises(FragmentError, match="no valid <child"):
        find_root_link(_parse(xml_text), Path("frag.urdf"))
