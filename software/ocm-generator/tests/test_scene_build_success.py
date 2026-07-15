# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests that actually exercise tesseract_robotics. Deliberately narrow in
what it reads back from the Environment: state.link_transforms[...] proxies
segfault if you hold onto them across statements (a real, reproduced
lifetime bug in this binding, not caution for its own sake) -- so pose
correctness is verified against the URDF *string* build_scene produces
(parsed back with ElementTree), and Tesseract itself is only asked for
link/joint *names*, via index-based access (`getLinks()[i]`, not
`for l in getLinks()`, which has its own broken iteration protocol here).
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import pytest
from tesseract_robotics.tesseract_environment import Environment

from ocm_generator.scene import Scene, build_scene


def _link_names(scene: Scene) -> set[str]:
    sg = scene.environment.getSceneGraph()
    links = sg.getLinks()
    return {links[i].getName() for i in range(len(links))}


def _joint_names(scene: Scene) -> set[str]:
    sg = scene.environment.getSceneGraph()
    joints = sg.getJoints()
    return {joints[i].getName() for i in range(len(joints))}


def test_builds_a_real_tesseract_environment(tiny_resolved_cell, modules_root):
    scene = build_scene(tiny_resolved_cell, modules_root)

    assert isinstance(scene, Scene)
    assert isinstance(scene.environment, Environment)


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


def test_tesseract_environment_agrees_on_link_and_joint_names(tiny_resolved_cell, modules_root):
    # Cross-check: what Tesseract actually parsed out of the URDF string
    # matches the same string re-parsed independently with ElementTree.
    scene = build_scene(tiny_resolved_cell, modules_root)

    xml_link_names = {el.get("name") for el in ET.fromstring(scene.urdf_xml).findall("link")}
    xml_joint_names = {el.get("name") for el in ET.fromstring(scene.urdf_xml).findall("joint")}

    assert _link_names(scene) == xml_link_names
    assert _joint_names(scene) == xml_joint_names
    assert {scene.base.joint_name, scene.instance("robot1").joint_name, scene.instance("tool1").joint_name} <= xml_joint_names


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
