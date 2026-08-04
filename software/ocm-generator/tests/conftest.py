# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared fixtures: minimal, schema-valid module manifests paired with real
(tiny) URDF fragment files, and a small synthetic cell -- same approach
ocm-resolve's tests use, extended with an actual urdf_fragment on disk
since that's the one field ocm-core/ocm-resolve never had to touch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from ocm_core.cell import Cell
from ocm_resolve import ResolvedCell, resolve_cell

# tests/conftest.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def sd50_manifest_path(repo_root: Path) -> Path:
    return repo_root / "modules" / "com.accelsolutions.screwdriver.sd50" / "module.yaml"


def base_fragment_xml(root_link: str) -> str:
    """A base module's deck, sized to comfortably contain the default
    build_cell_dict() layout (robot1 at xyz_mm=[400,300,...], so tool1's
    X/Y lands at 0.4, 0.3 m too -- see build.py's workspace containment
    check) rather than the tiny 5cm box fragment_xml() gives everything
    else.
    """
    return f"""<?xml version="1.0"?>
<robot name="frag">
  <link name="{root_link}">
    <collision>
      <origin xyz="0.5 0.5 -0.05" rpy="0 0 0"/>
      <geometry><box size="1.0 1.0 0.1"/></geometry>
    </collision>
  </link>
</robot>"""


def fragment_xml(root_link: str, extra_link: str | None = None, extra_xyz=(0.0, 0.0, 0.05)) -> str:
    """A tiny, valid, standalone URDF fragment: one link, or two joined by a
    fixed joint (the second link is used as a mount.on attachment point).
    """
    if extra_link is None:
        return f"""<?xml version="1.0"?>
<robot name="frag">
  <link name="{root_link}">
    <collision><geometry><box size="0.05 0.05 0.05"/></geometry></collision>
  </link>
</robot>"""
    x, y, z = extra_xyz
    return f"""<?xml version="1.0"?>
<robot name="frag">
  <link name="{root_link}">
    <collision><geometry><box size="0.05 0.05 0.05"/></geometry></collision>
  </link>
  <link name="{extra_link}">
    <collision><geometry><box size="0.02 0.02 0.02"/></geometry></collision>
  </link>
  <joint name="{root_link}_to_{extra_link}" type="fixed">
    <parent link="{root_link}"/>
    <child link="{extra_link}"/>
    <origin xyz="{x} {y} {z}" rpy="0 0 0"/>
  </joint>
</robot>"""


def minimal_base_manifest(
    id_: str = "com.example.base.tiny", revision: str = "1.0.0", urdf_fragment: str | None = "base.urdf"
) -> dict[str, Any]:
    geometry: dict[str, Any] = {"collision": "meshes/base_convex.stl"}
    if urdf_fragment is not None:
        geometry["urdf_fragment"] = urdf_fragment
    return {
        "ocm_version": "1.0",
        "id": id_,
        "revision": revision,
        "kind": "base",
        "license": "CERN-OHL-S-2.0",
        "name": "Tiny Test Base",
        "mechanical": {
            "mount": {"interface": "custom"},
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}},
            "geometry": geometry,
            "mass_kg": 80.0,
        },
        "state_machine": {"model": "packml", "abort_safe": True},
    }


def minimal_robot_manifest(
    id_: str = "com.example.robot.tiny", revision: str = "1.0.0", urdf_fragment: str | None = "robot.urdf"
) -> dict[str, Any]:
    return {
        "ocm_version": "1.0",
        "id": id_,
        "revision": revision,
        "kind": "robot",
        "license": "CERN-OHL-S-2.0",
        "name": "Tiny Test Robot",
        "mechanical": {
            "mount": {"interface": "ocm-base-grid-50", "footprint_mm": [300, 300]},
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}},
            "geometry": {"collision": "meshes/robot_convex.stl", "urdf_fragment": urdf_fragment},
            "mass_kg": 20.0,
        },
        "comms": {"protocol": "ethercat", "signals": []},
        "state_machine": {"model": "packml", "implements": ["idle", "execute"], "abort_safe": True},
    }


def minimal_tool_manifest(
    id_: str = "com.example.tool.tiny", revision: str = "1.0.0", urdf_fragment: str | None = "tool.urdf"
) -> dict[str, Any]:
    geometry: dict[str, Any] = {"collision": "meshes/tool_convex.stl"}
    if urdf_fragment is not None:
        geometry["urdf_fragment"] = urdf_fragment
    return {
        "ocm_version": "1.0",
        "id": id_,
        "revision": revision,
        "kind": "end_effector",
        "license": "CERN-OHL-S-2.0",
        "name": "Tiny Test Tool",
        "mechanical": {
            "mount": {"interface": "iso-9409-1-a50", "footprint_mm": [70, 70]},
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}, "tcp": {"xyz_mm": [0, 0, 100]}},
            "geometry": geometry,
            "mass_kg": 1.0,
            "com_mm": [0, 0, 50],
        },
        "comms": {"protocol": "ethercat", "signals": []},
        "capabilities": [
            {
                "name": "drive_screw",
                "summary": "Drive a screw to a target torque.",
                "parameters": {"torque_nm": {"type": "number", "unit": "N.m", "min": 0.2, "max": 5.0}},
                # ADR-0023: timeout_s/on_timeout required; abort_safe is False so on_timeout must be "abort".
                "timeout_s": 6.0,
                "on_timeout": "abort",
            }
        ],
        "state_machine": {"model": "packml", "implements": ["idle", "execute"], "abort_safe": False},
    }


def write_module(
    root: Path,
    manifest: dict[str, Any],
    fragment_name: str | None = None,
    fragment_xml_text: str | None = None,
) -> Path:
    module_dir = root / manifest["id"]
    module_dir.mkdir(parents=True, exist_ok=True)
    path = module_dir / "module.yaml"
    path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    if fragment_name and fragment_xml_text is not None:
        (module_dir / fragment_name).write_text(fragment_xml_text, encoding="utf-8")
    return path


def build_cell_dict(
    modules: list[dict[str, Any]] | None = None,
    base_ref: str = "com.example.base.tiny@1.0.0",
) -> dict[str, Any]:
    return {
        "ocm_version": "1.0",
        "kind": "cell",
        "id": "com.example.cell.tiny01",
        "name": "Tiny Test Cell",
        "license": "CERN-OHL-S-2.0",
        "base": {"module": base_ref, "datum": "cell_origin", "grid": "ocm-base-grid-50"},
        "modules": (
            modules
            if modules is not None
            else [
                {
                    "instance": "robot1",
                    "module": "com.example.robot.tiny@1.0.0",
                    "mount": {"pose": {"xyz_mm": [400, 300, 0], "rpy_deg": [0, 0, 90]}},
                },
                {
                    "instance": "tool1",
                    "module": "com.example.tool.tiny@1.0.0",
                    "mount": {"on": "robot1.flange"},
                },
            ]
        ),
        "plan": [],
    }


@pytest.fixture
def modules_root(tmp_path: Path) -> Path:
    """A module search path with a base, a robot (with a 'flange' link), and
    a tool -- all schema-valid, all with real, tiny, on-disk URDF fragments.
    """
    root = tmp_path / "modules"
    write_module(root, minimal_base_manifest(), "base.urdf", base_fragment_xml("origin"))
    write_module(
        root,
        minimal_robot_manifest(),
        "robot.urdf",
        fragment_xml("origin", extra_link="flange", extra_xyz=(0.0, 0.0, 0.4)),
    )
    write_module(root, minimal_tool_manifest(), "tool.urdf", fragment_xml("origin"))
    return root


@pytest.fixture
def tiny_resolved_cell(modules_root: Path) -> ResolvedCell:
    cell = Cell.from_dict(build_cell_dict())
    return resolve_cell(cell, modules_root)


@pytest.fixture
def no_collision_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the Bullet contact backend (`planner.path.check_collisions`)
    with a no-violation stub, so the REAL check_joint_segment /
    check_actuation_segment interpolation and the REAL timeline walk run
    without the tesseract extra (CI never installs it -- test.yml). The
    unit under test is the sweep/walk machinery, not Bullet; tests of the
    actual contact math stay tesseract-gated.
    """
    from ocm_generator.scene.collision import CollisionCheckResult

    monkeypatch.setattr(
        "ocm_generator.planner.path.check_collisions",
        lambda scene, contact_distance_mm=1.0: CollisionCheckResult(contacts=(), margin_mm=contact_distance_mm),
    )
