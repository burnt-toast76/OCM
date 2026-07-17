# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm_generator.scene.collision -- discrete contact checking, guarded by
the optional `tesseract` extra. The whole file is skipped, not failed,
when tesseract-robotics isn't installed (see the importorskip below) --
consistent with the base ocm-generator install not needing it.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

pytest.importorskip("tesseract_robotics")

from ocm_core.cell import Cell  # noqa: E402
from ocm_core import load_cell  # noqa: E402
from ocm_generator.scene import Scene, build_scene  # noqa: E402
from ocm_generator.scene.collision import check_collisions  # noqa: E402
from ocm_resolve import resolve_cell  # noqa: E402

from .conftest import (  # noqa: E402
    base_fragment_xml,
    build_cell_dict,
    fragment_xml,
    minimal_base_manifest,
    minimal_tool_manifest,
    write_module,
)


# ---------------------------------------------------------------------------
# (a) the real bracket cell, at its committed home pose -> clean
# ---------------------------------------------------------------------------


def test_real_bracket_cell_at_home_pose_is_clean(repo_root: Path):
    cell = load_cell(repo_root / "cells" / "bracket-asm-01" / "cell.yaml")
    resolved = resolve_cell(cell, repo_root / "modules")
    scene = build_scene(resolved, repo_root / "modules")

    result = check_collisions(scene)

    assert result.violations == ()


def test_real_bracket_cell_feed1_and_nest1_resting_on_the_deck_is_not_a_violation(repo_root: Path):
    # feed1 and nest1 sit directly on the base deck at z=0 -- touching by
    # design (they're bolted down), exactly like robot1 is. That's a
    # *direct* mount relationship (mount.pose is relative to the base's
    # own datum -- see collision.py's module docstring), so it's excluded
    # from the report entirely, not just marked non-violating: no amount
    # of margin tuning should ever make "bolted to the thing it's bolted
    # to" look like a crash.
    cell = load_cell(repo_root / "cells" / "bracket-asm-01" / "cell.yaml")
    resolved = resolve_cell(cell, repo_root / "modules")
    scene = build_scene(resolved, repo_root / "modules")

    result = check_collisions(scene)

    resting = [c for c in result.contacts if {c.instance_a, c.instance_b} & {"feed1", "nest1", "robot1"}]
    assert resting == []


# ---------------------------------------------------------------------------
# (b) two overlapping boxes -> refused
# ---------------------------------------------------------------------------


@pytest.fixture
def overlapping_boxes_scene(tmp_path: Path) -> Scene:
    modules_root = tmp_path / "modules"
    write_module(modules_root, minimal_base_manifest(), "base.urdf", base_fragment_xml("origin"))
    write_module(modules_root, minimal_tool_manifest(), "tool.urdf", fragment_xml("origin"))

    # boxA and boxB: same module, two instances, mounted dead center on top
    # of each other -- deliberately overlapping, and well inside the 1x1m
    # deck so this is purely a collision-check case, not a containment one.
    modules = [
        {
            "instance": "boxA",
            "module": "com.example.tool.tiny@1.0.0",
            "mount": {"pose": {"xyz_mm": [500, 500, 50], "rpy_deg": [0, 0, 0]}},
        },
        {
            "instance": "boxB",
            "module": "com.example.tool.tiny@1.0.0",
            "mount": {"pose": {"xyz_mm": [500, 500, 50], "rpy_deg": [0, 0, 0]}},
        },
    ]
    cell = Cell.from_dict(build_cell_dict(modules=modules))
    resolved = resolve_cell(cell, modules_root)
    return build_scene(resolved, modules_root)


def test_two_overlapping_boxes_are_refused(overlapping_boxes_scene: Scene):
    result = check_collisions(overlapping_boxes_scene)

    assert result.violations
    v = result.violations[0]
    assert {v.instance_a, v.instance_b} == {"boxA", "boxB"}
    assert v.distance_mm < 0


def test_two_overlapping_boxes_penetration_depth_is_reported_in_mm(overlapping_boxes_scene: Scene):
    # Both boxes are 0.05m cubes centered at the exact same point --
    # substantial overlap, not a hairline. Bullet's actual penetration
    # number needn't match a naive AABB-overlap guess exactly (GJK/EPA on
    # two coincident boxes isn't that simple a computation), but it must
    # be a real, clearly-nonzero negative number, in millimeters.
    result = check_collisions(overlapping_boxes_scene)

    assert result.violations
    assert result.violations[0].distance_mm < -1.0  # at least 1mm of real penetration


# ---------------------------------------------------------------------------
# (c) the real bracket cell with joint_state zeroed -> tool/wall contact
# ---------------------------------------------------------------------------


def test_real_bracket_cell_with_joint_state_zeroed_reports_wall_contact(repo_root: Path):
    # build_scene() itself already refuses this exact configuration (its
    # own static workspace-containment check catches the ~2mm overhang --
    # see test_scene_build_real_bracket_cell.py). That's a different,
    # earlier gate than this one: this test is specifically about the
    # discrete contact check itself, so it builds the real (containment
    # -passing) scene first and then swaps in a zeroed joint_state --
    # Scene.urdf_xml never bakes in a joint angle (see kinematics.py), so
    # this is exactly equivalent to evaluating the same composed cell at a
    # different configuration, not a fabricated scenario.
    cell = load_cell(repo_root / "cells" / "bracket-asm-01" / "cell.yaml")
    resolved = resolve_cell(cell, repo_root / "modules")
    scene = build_scene(resolved, repo_root / "modules")
    zeroed_scene = dataclasses.replace(scene, joint_state={})

    result = check_collisions(zeroed_scene)

    assert result.violations, "expected sd1 to poke into the guard wall at the arm's all-zero pose"
    tool_wall = [v for v in result.violations if "sd1" in (v.instance_a, v.instance_b)]
    assert tool_wall, f"expected a sd1 violation, got: {result.violations}"
    assert "base" in (tool_wall[0].instance_a, tool_wall[0].instance_b)


def test_mount_adjacency_exemption_is_direct_only_not_transitive(repo_root: Path):
    # Regression test for the actual bug found while writing these tests:
    # sd1 is mounted on robot1, and robot1 is mounted on base -- a naive
    # transitive "exempt anything in the mount ancestor chain" reading
    # wrongly exempted sd1-vs-base too, which silently swallowed the
    # exact wall-punch-through this whole check exists to catch (see
    # collision.py's module docstring). Pin both halves down together:
    # sd1-vs-robot1 (direct, exempt) never appears even when they're
    # obviously touching (any pose); sd1-vs-base (two hops, NOT exempt)
    # is still checked and still fires at the zeroed pose.
    cell = load_cell(repo_root / "cells" / "bracket-asm-01" / "cell.yaml")
    resolved = resolve_cell(cell, repo_root / "modules")
    scene = build_scene(resolved, repo_root / "modules")
    zeroed_scene = dataclasses.replace(scene, joint_state={})

    result = check_collisions(zeroed_scene)

    sd1_vs_robot1 = [c for c in result.contacts if {c.instance_a, c.instance_b} == {"sd1", "robot1"}]
    sd1_vs_base = [c for c in result.contacts if {c.instance_a, c.instance_b} == {"sd1", "base"}]
    assert sd1_vs_robot1 == [], "sd1 is directly mounted on robot1 -- must be exempt, not just non-violating"
    assert sd1_vs_base and sd1_vs_base[0].is_violation


def test_real_bracket_cell_with_its_real_joint_state_has_no_such_violation(repo_root: Path):
    # The flip side of the above, spelled out explicitly: the committed
    # folded pose is what makes this cell collision-clean in the first
    # place, not an accident of margins.
    cell = load_cell(repo_root / "cells" / "bracket-asm-01" / "cell.yaml")
    resolved = resolve_cell(cell, repo_root / "modules")
    scene = build_scene(resolved, repo_root / "modules")

    result = check_collisions(scene)

    assert not any("sd1" in (v.instance_a, v.instance_b) for v in result.violations)
