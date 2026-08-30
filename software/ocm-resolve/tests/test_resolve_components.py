# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0014: a module's own `components:` list, and its signals' `source`
provenance into that list, are cross-file references resolve_cell checks
the same way it already checks module refs and mount chains.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from ocm_core.cell import Cell
from ocm_resolve import CellResolutionError, resolve_cell

from .conftest import build_cell_dict, minimal_base_manifest, minimal_robot_manifest, write_module


def minimal_ejector_component(id_: str = "com.example.ejector.demo1", revision: str = "1.0.0") -> dict[str, Any]:
    return {
        "ocm_version": "1.1",
        "id": id_,
        "revision": revision,
        "kind": "vacuum_ejector",
        "vendor": "Example Co",
        "source": {"kind": "datasheet", "ref": "fictional demo datasheet, worked-example only"},
        "comms": {
            "protocol": "discrete-io",
            "signals": [{"name": "vacuum_switch", "direction_device": "output", "type": "bool"}],
        },
    }


def write_component(root: Path, manifest: dict[str, Any]) -> Path:
    component_dir = root / manifest["id"]
    component_dir.mkdir(parents=True, exist_ok=True)
    path = component_dir / "component.yaml"
    path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return path


def tool_with_components(components: list[dict[str, Any]], signal_source: str | None = None) -> dict[str, Any]:
    signal: dict[str, Any] = {"name": "part_present", "direction": "input", "type": "bool"}
    if signal_source is not None:
        signal["source"] = signal_source
    return {
        "ocm_version": "1.1",
        "id": "com.example.tool.tiny",
        "revision": "1.0.0",
        "kind": "end_effector",
        "license": "CERN-OHL-S-2.0",
        "name": "Tiny Test Tool",
        "mechanical": {
            "mount": {"interface": "iso-9409-1-a50", "footprint_mm": [70, 70]},
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}, "tcp": {"xyz_mm": [0, 0, 100]}},
            "geometry": {"collision": "meshes/tool_convex.stl"},
            "mass_kg": 1.0,
            "com_mm": [0, 0, 50],
        },
        "comms": {"protocol": "ethercat", "signals": [signal]},
        "capabilities": [
            {
                "name": "drive_screw",
                "summary": "Drive a screw to a target torque.",
                "parameters": {"torque_nm": {"type": "number", "unit": "N.m", "min": 0.2, "max": 5.0}},
                "timeout_s": 6.0,  # ADR-0023: required on every capability
                "on_timeout": "abort",  # abort_safe is False below
            }
        ],
        "state_machine": {"model": "packml", "implements": ["idle", "execute"], "abort_safe": False},
        "components": components,
    }


@pytest.fixture
def modules_and_components_root(tmp_path: Path) -> tuple[Path, Path]:
    modules_root = tmp_path / "modules"
    write_module(modules_root, minimal_base_manifest())
    write_module(modules_root, minimal_robot_manifest())
    components_root = tmp_path / "components"
    return modules_root, components_root


def _cell_with_tool(tool_manifest: dict[str, Any]) -> Cell:
    return Cell.from_dict(
        build_cell_dict(
            modules=[
                {
                    "instance": "robot1",
                    "module": "com.example.robot.tiny@1.0.0",
                    "mount": {"station": [100, 100], "pose": {"xyz_mm": [100, 100, 0]}},
                },
                {"instance": "tool1", "module": f"{tool_manifest['id']}@{tool_manifest['revision']}", "mount": {"on": "robot1.flange"}},
            ]
        )
    )


def test_module_with_no_components_list_is_untouched(modules_and_components_root: tuple[Path, Path]):
    modules_root, components_root = modules_and_components_root
    write_module(modules_root, tool_with_components([]))
    cell = _cell_with_tool(tool_with_components([]))

    resolved = resolve_cell(cell, modules_root, components_root)

    assert resolved.instance("tool1").module.components == ()


def test_component_reference_resolves_end_to_end(modules_and_components_root: tuple[Path, Path]):
    modules_root, components_root = modules_and_components_root
    write_component(components_root, minimal_ejector_component())
    tool = tool_with_components(
        [{"refdes": "VG1", "ref": "com.example.ejector.demo1@1.0.0"}],
        signal_source="VG1.vacuum_switch",
    )
    write_module(modules_root, tool)
    cell = _cell_with_tool(tool)

    resolved = resolve_cell(cell, modules_root, components_root)

    assert resolved.instance("tool1").module.components[0].refdes == "VG1"


def test_unknown_component_id_is_refused(modules_and_components_root: tuple[Path, Path]):
    modules_root, components_root = modules_and_components_root
    # components_root exists but has nothing in it.
    components_root.mkdir()
    tool = tool_with_components([{"refdes": "VG1", "ref": "com.example.ejector.demo1@1.0.0"}])
    write_module(modules_root, tool)
    cell = _cell_with_tool(tool)

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, modules_root, components_root)
    assert any("component not found" in e for e in exc.value.errors)


def test_component_revision_mismatch_is_refused(modules_and_components_root: tuple[Path, Path]):
    modules_root, components_root = modules_and_components_root
    write_component(components_root, minimal_ejector_component(revision="2.0.0"))
    tool = tool_with_components([{"refdes": "VG1", "ref": "com.example.ejector.demo1@1.0.0"}])
    write_module(modules_root, tool)
    cell = _cell_with_tool(tool)

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, modules_root, components_root)
    assert any("declares com.example.ejector.demo1@2.0.0, not" in e for e in exc.value.errors)


def test_duplicate_refdes_is_refused(modules_and_components_root: tuple[Path, Path]):
    modules_root, components_root = modules_and_components_root
    write_component(components_root, minimal_ejector_component())
    tool = tool_with_components(
        [
            {"refdes": "VG1", "ref": "com.example.ejector.demo1@1.0.0"},
            {"refdes": "VG1", "ref": "com.example.ejector.demo1@1.0.0"},
        ]
    )
    write_module(modules_root, tool)
    cell = _cell_with_tool(tool)

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, modules_root, components_root)
    assert any("duplicate component refdes" in e for e in exc.value.errors)


def test_source_referencing_unknown_refdes_is_refused(modules_and_components_root: tuple[Path, Path]):
    modules_root, components_root = modules_and_components_root
    write_component(components_root, minimal_ejector_component())
    tool = tool_with_components(
        [{"refdes": "VG1", "ref": "com.example.ejector.demo1@1.0.0"}],
        signal_source="VG9.vacuum_switch",
    )
    write_module(modules_root, tool)
    cell = _cell_with_tool(tool)

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, modules_root, components_root)
    assert any("references unknown refdes 'VG9'" in e for e in exc.value.errors)


def test_source_referencing_a_signal_the_component_does_not_declare_is_refused(
    modules_and_components_root: tuple[Path, Path]
):
    modules_root, components_root = modules_and_components_root
    write_component(components_root, minimal_ejector_component())
    tool = tool_with_components(
        [{"refdes": "VG1", "ref": "com.example.ejector.demo1@1.0.0"}],
        signal_source="VG1.not_a_real_signal",
    )
    write_module(modules_root, tool)
    cell = _cell_with_tool(tool)

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, modules_root, components_root)
    assert any("references unknown signal 'not_a_real_signal'" in e for e in exc.value.errors)


def test_components_list_without_a_components_search_path_is_refused(modules_and_components_root: tuple[Path, Path]):
    modules_root, _components_root = modules_and_components_root
    tool = tool_with_components([{"refdes": "VG1", "ref": "com.example.ejector.demo1@1.0.0"}])
    write_module(modules_root, tool)
    cell = _cell_with_tool(tool)

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, modules_root)  # no components_search_path
    assert any("no components search path was given" in e for e in exc.value.errors)
