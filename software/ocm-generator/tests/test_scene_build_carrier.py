# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0031 D2 + D4: the carrier's chain is ROOTED AT THE LOCATED DATUM
(both transit joints at zero IS the located pose; transit is negative
offset), and the part datum is DECLARED on the carrier and composed
through its root link -- never scraped from a clamp verb. Tesseract-free:
scene composition and forward kinematics are pure Python. Fixture values
are inline and obviously synthetic (ADR-0014)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest
import yaml

from ocm_core.cell import Cell
from ocm_generator.planner.poses import compute_part_datum_world
from ocm_generator.scene import build_scene, compute_world_poses
from ocm_generator.scene.build import WORLD_LINK
from ocm_resolve import resolve_cell

from .conftest import base_fragment_xml, build_cell_dict, fragment_xml, minimal_base_manifest, write_module

_MM = {"value": 0.05, "unit": "mm"}
_DEG = {"value": 0.02, "unit": "deg"}


def _conveyor_manifest() -> dict[str, Any]:
    return {
        "ocm_version": "1.1",
        "id": "com.example.conveyor.locating",
        "revision": "1.0.0",
        "kind": "transport",
        "license": "CERN-OHL-S-2.0",
        "mechanical": {
            "mount": {"interface": "custom"},
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}, "located_datum": {"xyz_mm": [100, 0, 50]}},
            "geometry": {"urdf_fragment": "conv.urdf"},
            "mass_kg": 40.0,
            "located": {
                "frame": "located_datum",
                "constraints": [
                    {"feature": "lift_stop_surface", "governs": ["z", "rx", "ry"],
                     "tolerance": {"z": dict(_MM), "rx": dict(_DEG), "ry": dict(_DEG)}, "source": "measured"},
                    {"feature": "locating_pins", "governs": ["x", "y", "rz"],
                     "tolerance": {"x": dict(_MM), "y": dict(_MM), "rz": dict(_DEG)}, "source": "measured"},
                ],
            },
        },
        "state_machine": {"model": "packml", "abort_safe": True},
    }


def _carrier_manifest() -> dict[str, Any]:
    return {
        "ocm_version": "1.1",
        "id": "com.example.carrier.test-pallet",
        "revision": "1.0.0",
        "license": "CERN-OHL-S-2.0",
        "mechanical": {
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}, "part_datum": {"xyz_mm": [120, 120, 40]}},
            "geometry": {"urdf_fragment": "urdf/pallet.urdf"},
            "mass_kg": 2.5,
        },
    }


def _build(tmp_path: Path, carrier_block: dict[str, Any]):
    root = tmp_path / "modules"
    write_module(root, minimal_base_manifest(), "base.urdf", base_fragment_xml("origin"))
    write_module(root, _conveyor_manifest(), "conv.urdf", fragment_xml("origin"))

    carrier_dir = tmp_path / "carriers" / "com.example.carrier.test-pallet"
    (carrier_dir / "urdf").mkdir(parents=True, exist_ok=True)
    (carrier_dir / "carrier.yaml").write_text(yaml.safe_dump(_carrier_manifest()), encoding="utf-8")
    (carrier_dir / "urdf" / "pallet.urdf").write_text(fragment_xml("origin"), encoding="utf-8")

    cell_dict = build_cell_dict(modules=[
        {"instance": "conv1", "module": "com.example.conveyor.locating@1.0.0",
         "mount": {"pose": {"xyz_mm": [600, 300, 0], "rpy_deg": [0, 0, 0]}}},
    ])
    cell_dict["carrier"] = carrier_block
    cell = Cell.from_dict(cell_dict)
    resolved = resolve_cell(cell, root)
    scene = build_scene(resolved, root)
    return resolved, scene


def _world_pose_of(scene, link: str):
    root = ET.fromstring(scene.urdf_xml)
    return compute_world_poses(root, scene.joint_state, WORLD_LINK)[link]


# conv1 at (0.6, 0.3, 0) + located_datum (0.1, 0, 0.05) = the located pose.
_LOCATED_WORLD = (0.7, 0.3, 0.05)

_SEATED = {"instance": "pal1", "type": "com.example.carrier.test-pallet@1.0.0", "located_on": "conv1"}
_WITH_ENTRY = dict(_SEATED, entry_mm={"travel": -200, "lift": -12})


def test_both_transit_joints_at_zero_is_the_located_pose(tmp_path: Path):
    # Entry declared, no transit: the chain exists (real prismatic joints)
    # and both sit at ZERO -- which IS the located pose, by construction,
    # not by any joint value having been commanded.
    resolved, scene = _build(tmp_path, dict(_WITH_ENTRY))

    assert scene.joint_state["pal1__travel"] == 0.0
    assert scene.joint_state["pal1__lift"] == 0.0
    pose = _world_pose_of(scene, scene.instance("pal1").root_link)
    assert pose.translation == pytest.approx(_LOCATED_WORLD)


def test_seated_carrier_with_no_entry_is_welded_at_the_located_pose(tmp_path: Path):
    # No entry_mm: no transit is modelled at all -- no prismatic joints,
    # no joint values, nothing that could claim a commanded travel.
    resolved, scene = _build(tmp_path, dict(_SEATED))

    assert "pal1__travel" not in scene.joint_state
    root = ET.fromstring(scene.urdf_xml)
    assert root.find("joint[@name='pal1__travel']") is None
    pose = _world_pose_of(scene, scene.instance("pal1").root_link)
    assert pose.translation == pytest.approx(_LOCATED_WORLD)


def test_transit_is_negative_offset_and_the_sign_convention_holds(tmp_path: Path):
    # D2: transit is a DEPARTURE from the located pose -- negative travel
    # moves the carrier back along the datum frame's +X approach axis,
    # negative lift drops it below the seated plane. Asserted in world
    # coordinates, not assumed.
    resolved, scene = _build(tmp_path, dict(_WITH_ENTRY, transit_mm={"travel": -200, "lift": -12}))

    assert scene.joint_state["pal1__travel"] == pytest.approx(-0.2)
    assert scene.joint_state["pal1__lift"] == pytest.approx(-0.012)
    pose = _world_pose_of(scene, scene.instance("pal1").root_link)
    assert pose.translation == pytest.approx((_LOCATED_WORLD[0] - 0.2, _LOCATED_WORLD[1], _LOCATED_WORLD[2] - 0.012))


def test_transit_joint_limits_are_declared_facts_not_fabrications(tmp_path: Path):
    # [entry, 0]: 0 is the machined hard stop the datum sits at (true by
    # construction), entry is the cell's own declared entry offset. No
    # commanded travel is declared anywhere in the chain.
    resolved, scene = _build(tmp_path, dict(_WITH_ENTRY))

    root = ET.fromstring(scene.urdf_xml)
    travel = root.find("joint[@name='pal1__travel']")
    lift = root.find("joint[@name='pal1__lift']")
    assert travel.get("type") == "prismatic" and lift.get("type") == "prismatic"
    assert float(travel.find("limit").get("lower")) == pytest.approx(-0.2)
    assert float(travel.find("limit").get("upper")) == 0.0
    assert float(lift.find("limit").get("lower")) == pytest.approx(-0.012)
    assert float(lift.find("limit").get("upper")) == 0.0
    # The chain is rooted at the located datum: the fixed located joint
    # parents the datum link off the conveyor, and the prismatics hang
    # BELOW the datum -- never the conveyor-base-forward direction the ADR
    # rejects.
    located = root.find("joint[@name='pal1__located']")
    assert located.get("type") == "fixed"
    assert located.find("parent").get("link") == scene.instance("conv1").root_link
    assert travel.find("parent").get("link") == "pal1__located_datum"


def test_part_datum_composes_through_the_carrier_root_link(tmp_path: Path):
    # D4: the carrier's DECLARED frames.part_datum, composed through the
    # root link the D2 chain places -- seated, that is the located pose
    # plus the carrier's own offset, machined geometry and nothing else.
    resolved, scene = _build(tmp_path, dict(_WITH_ENTRY))

    root = ET.fromstring(scene.urdf_xml)
    world_poses = compute_world_poses(root, scene.joint_state, WORLD_LINK)
    owner, pose = compute_part_datum_world(resolved, scene, world_poses)
    assert owner == "pal1"
    assert pose.translation == pytest.approx((_LOCATED_WORLD[0] + 0.12, _LOCATED_WORLD[1] + 0.12, _LOCATED_WORLD[2] + 0.04))


def test_two_fixtures_with_part_datum_and_no_carrier_is_ambiguous(tmp_path: Path):
    # D4: it does not guess. Two declarations and no carrier is two answers
    # to one question -- refused, not disambiguated by a clamp verb.
    from ocm_generator.planner.errors import PlanningError

    root = tmp_path / "modules"
    write_module(root, minimal_base_manifest(), "base.urdf", base_fragment_xml("origin"))
    for i in (1, 2):
        manifest = _conveyor_manifest()
        manifest["id"] = f"com.example.fixture.nest{i}"
        manifest["kind"] = "fixture"
        del manifest["mechanical"]["located"]
        manifest["mechanical"]["frames"]["part_datum"] = {"xyz_mm": [0, 0, 10]}
        write_module(root, manifest, "conv.urdf", fragment_xml("origin"))

    cell_dict = build_cell_dict(modules=[
        {"instance": "nest1", "module": "com.example.fixture.nest1@1.0.0",
         "mount": {"pose": {"xyz_mm": [500, 300, 0], "rpy_deg": [0, 0, 0]}}},
        {"instance": "nest2", "module": "com.example.fixture.nest2@1.0.0",
         "mount": {"pose": {"xyz_mm": [700, 300, 0], "rpy_deg": [0, 0, 0]}}},
    ])
    cell = Cell.from_dict(cell_dict)
    resolved = resolve_cell(cell, root)
    scene = build_scene(resolved, root)
    root_el = ET.fromstring(scene.urdf_xml)
    world_poses = compute_world_poses(root_el, scene.joint_state, WORLD_LINK)

    with pytest.raises(PlanningError) as exc:
        compute_part_datum_world(resolved, scene, world_poses)
    assert "multiple fixtures declare frames.part_datum" in str(exc.value)
    assert "nest1" in str(exc.value) and "nest2" in str(exc.value)
