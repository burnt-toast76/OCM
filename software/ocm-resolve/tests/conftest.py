# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared fixtures: minimal, schema-valid module manifests and a small
synthetic cell, built as plain dicts. Deliberately not reusing the real
bracket-asm-01 cell for the pass/fail-mode tests -- most of the modules it
references (robot1, feed1, nest1, cam1, base) don't have manifests checked
in yet, so it can't fully resolve. It's still useful as a real-world
"multiple modules genuinely missing" case; see test_resolve_missing_module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from ocm_core.cell import Cell

# tests/conftest.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


def minimal_base_manifest(id_: str = "com.example.base.tiny", revision: str = "1.0.0") -> dict[str, Any]:
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
            "geometry": {"collision": "meshes/base_convex.stl"},
            "mass_kg": 80.0,
        },
        "state_machine": {"model": "packml", "abort_safe": True},
    }


def minimal_robot_manifest(id_: str = "com.example.robot.tiny", revision: str = "1.0.0") -> dict[str, Any]:
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
            "geometry": {
                "collision": "meshes/robot_convex.stl",
                "urdf_fragment": "urdf/robot.urdf.xacro",
            },
            "mass_kg": 20.0,
        },
        "comms": {"protocol": "ethercat", "signals": []},
        "state_machine": {"model": "packml", "implements": ["idle", "execute"], "abort_safe": True},
    }


def minimal_tool_manifest(
    id_: str = "com.example.tool.tiny",
    revision: str = "1.0.0",
    capabilities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "ocm_version": "1.0",
        "id": id_,
        "revision": revision,
        "kind": "end_effector",
        "license": "CERN-OHL-S-2.0",
        "name": "Tiny Test Tool",
        "mechanical": {
            "mount": {"interface": "iso-9409-1-a50", "footprint_mm": [70, 70]},
            "frames": {
                "origin": {"xyz_mm": [0, 0, 0]},
                "tcp": {"xyz_mm": [0, 0, 100]},
            },
            "geometry": {"collision": "meshes/tool_convex.stl"},
            "mass_kg": 1.0,
            "com_mm": [0, 0, 50],
        },
        "comms": {"protocol": "ethercat", "signals": []},
        "capabilities": (
            capabilities
            if capabilities is not None
            else [
                {
                    "name": "drive_screw",
                    "summary": "Drive a screw to a target torque.",
                    "parameters": {
                        "torque_nm": {"type": "number", "unit": "N.m", "min": 0.2, "max": 5.0},
                        "strategy": {
                            "type": "enum",
                            "values": ["torque_control", "angle_control"],
                            "default": "torque_control",
                            "required": False,
                        },
                    },
                    # ADR-0023: timeout_s/on_timeout are required on every capability.
                    # abort_safe is False below, so on_timeout must be "abort"
                    # (hold would be a TIMEOUT_DISPOSITION_CONFLICT).
                    "timeout_s": 6.0,
                    "on_timeout": "abort",
                }
            ]
        ),
        "state_machine": {
            "model": "packml",
            "implements": ["idle", "execute"],
            "abort_safe": False,
        },
    }


def write_module(root: Path, manifest: dict[str, Any]) -> Path:
    module_dir = root / manifest["id"]
    module_dir.mkdir(parents=True, exist_ok=True)
    path = module_dir / "module.yaml"
    path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return path


def build_cell_dict(
    modules: list[dict[str, Any]] | None = None,
    plan: list[Any] | None = None,
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
                    "mount": {"station": [100, 100], "pose": {"xyz_mm": [100, 100, 0]}},
                },
                {
                    "instance": "tool1",
                    "module": "com.example.tool.tiny@1.0.0",
                    "mount": {"on": "robot1.flange"},
                },
            ]
        ),
        "plan": (
            plan
            if plan is not None
            else [
                {
                    "step": "fasten",
                    "module": "tool1",
                    "op": "drive_screw",
                    "params": {"torque_nm": 2.4},
                }
            ]
        ),
    }


@pytest.fixture
def search_root(tmp_path: Path) -> Path:
    """A module search path with a base, a robot, and a tool, all schema-valid."""
    root = tmp_path / "modules"
    write_module(root, minimal_base_manifest())
    write_module(root, minimal_robot_manifest())
    write_module(root, minimal_tool_manifest())
    return root


@pytest.fixture
def tiny_cell() -> Cell:
    return Cell.from_dict(build_cell_dict())
