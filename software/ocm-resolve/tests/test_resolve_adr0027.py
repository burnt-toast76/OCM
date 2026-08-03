# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0027 D5 resolve-time refusals: `derived` mode requires complete inputs
and refuses instead of approximating. Positive and negative for each of
OCM_DERIVED_POSE_MISSING / OCM_DERIVED_ENVELOPE_MISSING / OCM_UNIT_UNRECOGNISED
(as plain resolve strings; ocm-api's translate maps the codes)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ocm_core import Module
from ocm_resolve import resolve_module

from .test_resolve_components import minimal_ejector_component, write_component


def _component_with_envelope(id_: str = "com.example.ejector.demo1", units: str = "mm") -> dict[str, Any]:
    comp = minimal_ejector_component(id_)
    comp["geometry"] = {"envelope": {"length": 40.0, "width": 20.0, "height": 30.0, "units": units}}
    return comp


def _derived_module(components: list[dict[str, Any]], structure: list[dict[str, Any]] | None = None) -> Module:
    doc: dict[str, Any] = {
        "ocm_version": "1.1",
        "id": "com.example.tool.derived",
        "revision": "1.0.0",
        "kind": "fixture",
        "license": "CERN-OHL-S-2.0",
        "name": "Derived-mode test tool",
        "mechanical": {
            "mount": {"interface": "custom"},
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}},
            "geometry": {"collision_source": "derived", "urdf_fragment": "urdf/t.urdf"},
            "mass_kg": 1.0,
        },
        "state_machine": {"model": "packml", "abort_safe": True},
        "components": components,
    }
    if structure:
        doc["mechanical"]["structure"] = structure
    return Module.from_dict(doc)


def test_derived_with_complete_inputs_resolves_clean(tmp_path: Path):
    root = tmp_path / "components"
    write_component(root, _component_with_envelope())
    module = _derived_module([
        {"refdes": "EJ1", "ref": "com.example.ejector.demo1@1.0.0", "pose": {"xyz_mm": [0, 0, 10]}},
    ])
    errors = resolve_module(module, root)
    assert errors == []


def test_derived_component_without_pose_is_refused(tmp_path: Path):
    root = tmp_path / "components"
    write_component(root, _component_with_envelope())
    module = _derived_module([
        {"refdes": "EJ1", "ref": "com.example.ejector.demo1@1.0.0"},  # no pose
    ])
    errors = resolve_module(module, root)
    assert any("collision_source 'derived' but component EJ1 has no pose" in e for e in errors), errors


def test_derived_component_without_envelope_is_refused(tmp_path: Path):
    root = tmp_path / "components"
    write_component(root, minimal_ejector_component())  # no geometry.envelope at all
    module = _derived_module([
        {"refdes": "EJ1", "ref": "com.example.ejector.demo1@1.0.0", "pose": {"xyz_mm": [0, 0, 10]}},
    ])
    errors = resolve_module(module, root)
    assert any("declares no complete geometry.envelope" in e for e in errors), errors


def test_derived_envelope_with_unrecognised_unit_is_refused(tmp_path: Path):
    root = tmp_path / "components"
    write_component(root, _component_with_envelope(units="inches"))  # verbatim, but not in the table
    module = _derived_module([
        {"refdes": "EJ1", "ref": "com.example.ejector.demo1@1.0.0", "pose": {"xyz_mm": [0, 0, 10]}},
    ])
    errors = resolve_module(module, root)
    assert any("envelope unit 'inches' is unrecognised" in e for e in errors), errors


def test_structure_with_unrecognised_unit_is_refused(tmp_path: Path):
    root = tmp_path / "components"
    write_component(root, _component_with_envelope())
    module = _derived_module(
        [{"refdes": "EJ1", "ref": "com.example.ejector.demo1@1.0.0", "pose": {"xyz_mm": [0, 0, 10]}}],
        structure=[{"id": "plate", "shape": "box", "size": [180, 120, 8], "units": "millimetre",
                    "pose": {"xyz": [0, 0, 0]}}],
    )
    errors = resolve_module(module, root)
    assert any("structure plate unit 'millimetre' is unrecognised" in e for e in errors), errors


def test_authored_mode_skips_the_derived_completeness_checks(tmp_path: Path):
    # Same incomplete inputs, but authored mode: the derived checks do not
    # fire (the authored path has its own file-side checks in the generator).
    root = tmp_path / "components"
    write_component(root, minimal_ejector_component())
    module = _derived_module([
        {"refdes": "EJ1", "ref": "com.example.ejector.demo1@1.0.0"},
    ])
    object.__setattr__(module.mechanical.geometry, "collision_source", "authored")
    errors = resolve_module(module, root)
    assert not any("collision_source 'derived'" in e for e in errors), errors
