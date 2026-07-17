# SPDX-License-Identifier: AGPL-3.0-or-later
"""Resolves and scene-builds the real, checked-in bracket-asm-01 cell
against the real modules/ directory.

Every module the cell references now has real collision geometry: the six
non-robot modules got a box primitive derived from mechanical.mount.
footprint_mm plus a height already present elsewhere in the manifest (a tcp/
pick/part_datum frame, or a documented estimate where none exists), and
com.universal-robots.ur5e got a real per-link mesh + kinematic chain
vendored and flattened from Universal_Robots_ROS2_Description (BSD-3-Clause;
see that module's NOTICE.md). None of this is real CAD -- the six box
primitives are explicitly placeholders -- but it's real enough for the
generator to actually assemble a connected, collision-checkable Tesseract
scene end-to-end, which is the point of this test.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ocm_core import load_cell
from ocm_generator.scene import Scene, SceneBuildError, build_scene, compute_world_poses, list_collision_primitives
from ocm_resolve import resolve_cell


def _link_names(scene: Scene) -> set[str]:
    return {el.get("name") for el in ET.fromstring(scene.urdf_xml).findall("link")}


def test_real_bracket_cell_scene_builds_end_to_end(repo_root: Path):
    cell = load_cell(repo_root / "cells" / "bracket-asm-01" / "cell.yaml")
    resolved = resolve_cell(cell, repo_root / "modules")

    scene = build_scene(resolved, repo_root / "modules")

    assert isinstance(scene, Scene)
    assert set(scene.instances) == {"robot1", "sd1", "feed1", "nest1", "cam1"}


def test_real_bracket_cell_sd1_is_kinematically_parented_to_the_real_ur5e_flange(repo_root: Path):
    cell = load_cell(repo_root / "cells" / "bracket-asm-01" / "cell.yaml")
    resolved = resolve_cell(cell, repo_root / "modules")

    scene = build_scene(resolved, repo_root / "modules")

    # "robot1__flange" only exists because it's a real link in the vendored
    # UR5e URDF (see NOTICE.md) -- not something ocm_generator invented.
    assert scene.instance("sd1").parent_link == "robot1__flange"
    assert "robot1__flange" in _link_names(scene)


def test_real_bracket_cell_base_grid_instances_attach_to_world(repo_root: Path):
    cell = load_cell(repo_root / "cells" / "bracket-asm-01" / "cell.yaml")
    resolved = resolve_cell(cell, repo_root / "modules")

    scene = build_scene(resolved, repo_root / "modules")

    assert scene.base.parent_link == "world"
    for name in ("robot1", "feed1", "nest1", "cam1"):
        assert scene.instance(name).parent_link == "world"


def test_real_bracket_cell_carries_robot1s_folded_joint_state(repo_root: Path):
    cell = load_cell(repo_root / "cells" / "bracket-asm-01" / "cell.yaml")
    resolved = resolve_cell(cell, repo_root / "modules")

    scene = build_scene(resolved, repo_root / "modules")

    assert scene.joint_state == pytest.approx(
        {
            "robot1__shoulder_lift_joint": -1.5707963267948966,
            "robot1__elbow_joint": 1.5707963267948966,
        }
    )


def test_real_bracket_cell_without_the_folded_joint_state_pokes_through_the_wall(
    repo_root: Path, tmp_path: Path
):
    # Regression test for the exact issue joint_state was added to fix:
    # at the arm's default (all-zero) pose, sd1 lands about 2mm past the
    # +X guard wall. Strip robot1's joint_state from a copy of the real
    # cell and confirm build_scene refuses it, naming sd1 and a small
    # X overhang -- proving the checked-in joint_state is load-bearing,
    # not decorative.
    # Text surgery, not a yaml.safe_load()/dict-edit/yaml.safe_dump()
    # round-trip: plain PyYAML resolves sd1's `on:` mount key as the
    # boolean True (a real YAML 1.1 quirk -- see ocm_core.loader, which
    # works around it for load_cell() but only for what IT reads off
    # disk). Editing via a plain dict would corrupt that key back to
    # `true:` on the way out, breaking sd1's mount for reasons unrelated
    # to what this test is actually checking. Strip the exact block this
    # test added instead, and load the result the normal way.
    original = (repo_root / "cells" / "bracket-asm-01" / "cell.yaml").read_text(encoding="utf-8")
    joint_state_block = (
        "\n    joint_state:"
        "\n      shoulder_lift_joint: -1.5707963267948966   # -90 deg"
        "\n      elbow_joint: 1.5707963267948966            #  90 deg"
    )
    assert joint_state_block in original, "cell.yaml's joint_state block text has changed; update this test"
    modified_path = tmp_path / "cell_no_joint_state.yaml"
    modified_path.write_text(original.replace(joint_state_block, ""), encoding="utf-8")
    cell = load_cell(modified_path)

    resolved = resolve_cell(cell, repo_root / "modules")
    with pytest.raises(SceneBuildError) as exc:
        build_scene(resolved, repo_root / "modules")

    assert any("sd1" in e and "+X" in e for e in exc.value.errors)


def test_real_bracket_cell_base_deck_and_all_four_guard_walls_are_rendered(repo_root: Path):
    # frame1200's "origin" link carries 5 <collision> boxes (deck + 4 guard
    # walls) on a single link -- regression test for the multi-collision
    # parsing fix (previously only the first was kept).
    cell = load_cell(repo_root / "cells" / "bracket-asm-01" / "cell.yaml")
    resolved = resolve_cell(cell, repo_root / "modules")
    scene = build_scene(resolved, repo_root / "modules")

    root = ET.fromstring(scene.urdf_xml)
    world_poses = compute_world_poses(root, scene.joint_state)
    (base_link,) = [link for link in root.findall("link") if link.get("name") == scene.base.root_link]

    primitives = list_collision_primitives(base_link, world_poses[scene.base.root_link])

    assert len(primitives) == 5
    assert all(p.kind == "box" for p in primitives)
