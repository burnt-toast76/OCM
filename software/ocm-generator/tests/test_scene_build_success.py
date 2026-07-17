# SPDX-License-Identifier: AGPL-3.0-or-later
"""build_scene() composes a Scene from a resolved cell -- pure Python/XML,
no Tesseract involved (see build.py's module docstring). Only
`test_composed_urdf_is_actually_loadable_by_tesseract` below deliberately
reaches for the optional `tesseract` extra, guarded so the rest of this
file (and the base ocm-generator install) doesn't need it.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import pytest

from ocm_generator.scene import Scene, build_scene


def _link_names(scene: Scene) -> set[str]:
    return {el.get("name") for el in ET.fromstring(scene.urdf_xml).findall("link")}


def _joint_names(scene: Scene) -> set[str]:
    return {el.get("name") for el in ET.fromstring(scene.urdf_xml).findall("joint")}


def test_builds_a_scene(tiny_resolved_cell, modules_root):
    scene = build_scene(tiny_resolved_cell, modules_root)

    assert isinstance(scene, Scene)
    assert scene.urdf_xml.startswith("<robot")


def test_base_and_instances_are_placed(tiny_resolved_cell, modules_root):
    scene = build_scene(tiny_resolved_cell, modules_root)

    assert scene.base.name == "base"
    assert scene.base.parent_link == "world"

    robot1 = scene.instance("robot1")
    assert robot1.parent_link == "world"  # placed by mount.pose

    tool1 = scene.instance("tool1")
    assert tool1.parent_link == "robot1__flange"  # kinematically parented, not a world pose


def test_combined_urdf_contains_every_namespaced_link(tiny_resolved_cell, modules_root):
    scene = build_scene(tiny_resolved_cell, modules_root)
    names = _link_names(scene)

    assert "world" in names
    assert scene.base.root_link in names
    assert "robot1__origin" in names
    assert "robot1__flange" in names
    assert "tool1__origin" in names


def test_scene_instances_agree_with_the_urdf_they_produced(tiny_resolved_cell, modules_root):
    scene = build_scene(tiny_resolved_cell, modules_root)

    xml_link_names = _link_names(scene)
    xml_joint_names = _joint_names(scene)

    assert {scene.base.joint_name, scene.instance("robot1").joint_name, scene.instance("tool1").joint_name} <= (
        xml_joint_names
    )
    for si in (scene.base, scene.instance("robot1"), scene.instance("tool1")):
        assert si.root_link in xml_link_names
        assert si.link_names <= xml_link_names


def test_mount_pose_is_converted_from_mm_deg_to_m_rad(tiny_resolved_cell, modules_root):
    # robot1's mount.pose is xyz_mm=[400,300,0], rpy_deg=[0,0,90] (conftest).
    scene = build_scene(tiny_resolved_cell, modules_root)
    root = ET.fromstring(scene.urdf_xml)

    robot1 = scene.instance("robot1")
    joint = next(j for j in root.findall("joint") if j.get("name") == robot1.joint_name)
    origin = joint.find("origin")

    xyz = [float(v) for v in origin.get("xyz").split()]
    rpy = [float(v) for v in origin.get("rpy").split()]

    assert xyz == pytest.approx([0.4, 0.3, 0.0])
    assert rpy == pytest.approx([0.0, 0.0, math.radians(90)])


def test_mount_on_uses_identity_offset_not_a_world_pose(tiny_resolved_cell, modules_root):
    # tool1 is mounted "on: robot1.flange" -- its joint origin must be
    # identity (kinematic parenting), never a computed world-frame pose.
    scene = build_scene(tiny_resolved_cell, modules_root)
    root = ET.fromstring(scene.urdf_xml)

    tool1 = scene.instance("tool1")
    joint = next(j for j in root.findall("joint") if j.get("name") == tool1.joint_name)
    origin = joint.find("origin")

    assert [float(v) for v in origin.get("xyz").split()] == pytest.approx([0.0, 0.0, 0.0])
    assert [float(v) for v in origin.get("rpy").split()] == pytest.approx([0.0, 0.0, 0.0])
    assert joint.find("parent").get("link") == "robot1__flange"
    assert joint.find("child").get("link") == "tool1__origin"


def test_composed_urdf_is_actually_loadable_by_tesseract(tiny_resolved_cell, modules_root):
    # build_scene() itself never touches Tesseract (see its module
    # docstring) -- but the URDF it produces still has to actually be
    # valid Tesseract input, since that's the whole point (ADR-0007) and
    # it's what --collision loads. One deliberately isolated, skippable
    # cross-check, rather than a hard dependency of every test in this file.
    tesseract_robotics = pytest.importorskip("tesseract_robotics")
    from tesseract_robotics.tesseract_common import GeneralResourceLocator
    from tesseract_robotics.tesseract_environment import Environment

    scene = build_scene(tiny_resolved_cell, modules_root)

    env = Environment()
    ok = env.init(scene.urdf_xml, GeneralResourceLocator())

    assert ok is True
    del tesseract_robotics  # imported only to trigger the skip; unused otherwise
