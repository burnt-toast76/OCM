# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every test operates against a TEMP COPY of the real repo's spec/,
modules/, and cells/ -- real, committed manifests (sd50, dh200, gocator,
the real bracket-asm-01 cell) give tests something genuine to exercise
(dh200 is even already a real, pre-existing draft: revision 0.9.1),
without ever mutating the actual working tree ocm-api would otherwise
operate on. `pytest.importorskip`-style skip for the `tesseract` extra
lives per-test-module, not here, since only generation.py's checking
verbs need it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ocm_api import OcmApi, Workspace

# tests/conftest.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "spec", root / "spec")
    shutil.copytree(REPO_ROOT / "modules", root / "modules")
    shutil.copytree(REPO_ROOT / "cells", root / "cells")
    return root


@pytest.fixture
def ws(workspace_root: Path) -> Workspace:
    return Workspace(workspace_root)


@pytest.fixture
def api(workspace_root: Path) -> OcmApi:
    return OcmApi(workspace_root)


# A schema-valid, already-published module manifest whose declared files
# ALL genuinely exist on disk -- the one module in this pre-alpha repo
# whose geometry isn't a placeholder (see modules/com.universal-robots.ur5e's
# own NOTICE.md: "a real vendored-and-flattened UR5e"). Every other real
# module's mechanical.geometry.collision is schema-REQUIRED but declared as
# an honest "placeholder -- not authored yet" (frame1200, pneumatic-nest,
# sf20, gocator) or simply unauthored without the comment (dh200, sd50) --
# a real, pre-existing pre-alpha gap (CLAUDE.md: "no hardware built"), not
# something to work around by weakening validate_module's own cross-file
# checks. Useful whenever a test wants "a module that's simply, fully
# valid" with no cross-file gaps at all.
CLEAN_MODULE_ID = "com.universal-robots.ur5e"


def write_obstacle_module(workspace_root: Path) -> None:
    """A trivial 100mm-box fixture module -- purpose-built to sit in a
    known, empirically-verified spot along a two-hole plan's
    retract_1 -> standoff_2 transit (see ocm_generator's own planner test
    suite, which found this exact placement/geometry first). Used to make
    a PATH_COLLISION refusal deterministic rather than depending on any
    real cell's own borderline geometry.
    """
    import yaml

    obstacle_dir = workspace_root / "modules" / "com.example.obstacle.block"
    obstacle_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "ocm_version": "1.0",
        "id": "com.example.obstacle.block",
        "revision": "1.0.0",
        "kind": "fixture",
        "license": "CERN-OHL-S-2.0",
        "name": "Test obstacle block",
        "mechanical": {
            "mount": {"interface": "custom"},
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}},
            "geometry": {"collision": "meshes/block.stl", "urdf_fragment": "block.urdf"},
            "mass_kg": 1.0,
        },
        "state_machine": {"model": "packml", "abort_safe": True},
    }
    (obstacle_dir / "module.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    (obstacle_dir / "block.urdf").write_text(
        '<?xml version="1.0"?>\n'
        '<robot name="frag">\n'
        '  <link name="origin">\n'
        '    <collision><geometry><box size="0.1 0.1 0.1"/></geometry></collision>\n'
        "  </link>\n"
        "</robot>\n",
        encoding="utf-8",
    )


def build_two_hole_cell_with_obstacle(api, cell_id: str = "obstacle-cell") -> None:
    """A minimal cell (real UR5e/sd50/pneumatic-nest, camera-free) with
    two holes far enough apart that `com.example.obstacle.block` (see
    `write_obstacle_module`, must already be in the workspace) sits
    squarely in the straight-line joint-space sweep between them and
    nowhere else -- a real, deterministic PATH_COLLISION.
    """
    api.create_cell(cell_id, "com.accelsolutions.base.frame1200@2.0.0")
    api.place_instance(
        cell_id, "robot1", "com.universal-robots.ur5e@3.1.0",
        {"station": [400, 300], "pose": {"xyz_mm": [400, 300, 0], "rpy_deg": [0, 0, 0]}},
    )
    api.set_joint_state(cell_id, "robot1", {"shoulder_lift_joint": -1.5707963267948966, "elbow_joint": 1.5707963267948966})
    api.place_instance(cell_id, "sd1", "com.accelsolutions.screwdriver.sd50@1.2.0", {"on": "robot1.flange"})
    api.place_instance(cell_id, "nest1", "com.accelsolutions.fixture.pneumatic-nest@1.1.0", {"pose": {"xyz_mm": [640, 300, 0], "rpy_deg": [0, 0, 90]}})
    api.place_instance(cell_id, "blocker", "com.example.obstacle.block@1.0.0", {"pose": {"xyz_mm": [598.5, 473.9, 281.8], "rpy_deg": [0, 0, 0]}})

    part = {"id": "BRK-TEST", "features": {"hole_1": {"xyz_mm": [12, 12, 0], "normal": [0, 0, 1]}, "hole_2": {"xyz_mm": [300, 200, 0], "normal": [0, 0, 1]}}}
    plan = [
        {"step": "clamp", "module": "nest1", "op": "clamp", "params": {"force_n": 120}},
        {
            "step": "fasten",
            "for_each": ["hole_1", "hole_2"],
            "sequence": [
                {"module": "sd1", "op": "load_screw"},
                {"module": "sd1", "op": "drive_screw", "at": "part.features.${item}", "params": {"torque_nm": 2.4, "depth_mm": 8.0}},
            ],
        },
        {"step": "release", "module": "nest1", "op": "unclamp"},
    ]
    api.set_plan(cell_id, plan, part=part)
