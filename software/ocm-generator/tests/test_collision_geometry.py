# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0027 file-side checks and the derived collision proxy -- pure Python,
no tesseract. A real (binary) cube STL is authored in-test so the containment
check runs against actual mesh half-spaces, not a mock."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

from ocm_core import Module
from ocm_core.component import Component
from ocm_generator.scene.collision_geometry import (
    check_module_collision_geometry,
    derived_collision_elements,
    load_stl_half_spaces_mm,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_cube_stl(path: Path, half_extent_m: float) -> None:
    """A closed axis-aligned cube centred at origin, binary STL, metres."""
    h = half_extent_m
    v = [
        (-h, -h, -h), (h, -h, -h), (h, h, -h), (-h, h, -h),  # bottom (z=-h)
        (-h, -h, h), (h, -h, h), (h, h, h), (-h, h, h),      # top (z=+h)
    ]
    quads = [
        (0, 1, 2, 3),  # bottom
        (4, 7, 6, 5),  # top
        (0, 4, 5, 1),  # front (y=-h)
        (2, 6, 7, 3),  # back (y=+h)
        (0, 3, 7, 4),  # left (x=-h)
        (1, 5, 6, 2),  # right (x=+h)
    ]
    tris = []
    for a, b, c, d in quads:
        tris.append((v[a], v[b], v[c]))
        tris.append((v[a], v[c], v[d]))
    blob = bytearray(b"\x00" * 80)
    blob += struct.pack("<I", len(tris))
    for tri in tris:
        blob += struct.pack("<3f", 0.0, 0.0, 0.0)  # junk normal on purpose: recomputed from winding
        for p in tri:
            blob += struct.pack("<3f", *p)
        blob += b"\x00\x00"
    path.write_bytes(bytes(blob))


def _component(id_: str, envelope: dict[str, Any] | None) -> Component:
    doc: dict[str, Any] = {
        "ocm_version": "1.1",
        "id": id_,
        "revision": "1.0.0",
        "kind": "vacuum_ejector",
        "vendor": "Example Co",
        "source": {"kind": "datasheet", "ref": "worked example"},
    }
    if envelope is not None:
        doc["geometry"] = {"envelope": envelope}
    return Component.from_dict(doc)


_FRAGMENT = """<robot name="t">
  <link name="base"/>
  <link name="z_carriage"/>
  <joint name="z" type="prismatic"><parent link="base"/><child link="z_carriage"/></joint>
</robot>
"""


def _module(tmp_path: Path, geometry: dict[str, Any], components: list[dict[str, Any]] = (), structure: list[dict[str, Any]] | None = None) -> tuple[Module, Path]:
    module_dir = tmp_path / "mod"
    (module_dir / "urdf").mkdir(parents=True, exist_ok=True)
    (module_dir / "urdf" / "t.urdf").write_text(_FRAGMENT, encoding="utf-8")
    doc: dict[str, Any] = {
        "ocm_version": "1.1",
        "id": "com.example.tool.geom",
        "revision": "1.0.0",
        "kind": "fixture",
        "license": "CERN-OHL-S-2.0",
        "mechanical": {
            "mount": {"interface": "custom"},
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}},
            "geometry": {"urdf_fragment": "urdf/t.urdf", **geometry},
            "mass_kg": 1.0,
        },
        "state_machine": {"model": "packml", "abort_safe": True},
        "components": list(components),
    }
    if structure:
        doc["mechanical"]["structure"] = structure
    return Module.from_dict(doc), module_dir


_ENV_SMALL = {"length": 40.0, "width": 40.0, "height": 40.0, "units": "mm"}  # 40mm cube envelope


# ---------------------------------------------------------------------------
# STL parsing / containment (authored, convex-hull semantics)
# ---------------------------------------------------------------------------


def test_cube_stl_half_spaces_contain_and_exclude(tmp_path: Path):
    stl = tmp_path / "cube.stl"
    _write_cube_stl(stl, 0.1)  # 200 mm cube
    hs = load_stl_half_spaces_mm(stl)
    assert len(hs.planes) == 12
    from ocm_generator.scene.collision_geometry import _point_inside
    assert _point_inside(hs, (0.0, 0.0, 0.0))
    assert _point_inside(hs, (99.0, 99.0, 99.0))
    assert not _point_inside(hs, (101.0, 0.0, 0.0))


def test_authored_containment_passes_when_envelope_inside(tmp_path: Path):
    module, module_dir = _module(
        tmp_path,
        {"collision_source": "authored", "collision": "cube.stl"},
        components=[{"refdes": "EJ1", "ref": "com.example.ej.a@1.0.0", "pose": {"xyz_mm": [0, 0, 0]}}],
    )
    _write_cube_stl(module_dir / "cube.stl", 0.1)  # 200mm cube; 40mm envelope centred at origin fits
    refusals, advisories = check_module_collision_geometry(
        module, module_dir, {"EJ1": _component("com.example.ej.a", _ENV_SMALL)}
    )
    assert refusals == []
    assert advisories == []


def test_authored_containment_refuses_a_protruding_component(tmp_path: Path):
    # The dangerous case ADR-0027 D2 exists for: a component the planner does
    # not know is there. Envelope centred at x=190mm pokes out of the 200mm cube.
    module, module_dir = _module(
        tmp_path,
        {"collision_source": "authored", "collision": "cube.stl"},
        components=[{"refdes": "EJ1", "ref": "com.example.ej.a@1.0.0", "pose": {"xyz_mm": [190, 0, 0]}}],
    )
    _write_cube_stl(module_dir / "cube.stl", 0.1)
    refusals, _ = check_module_collision_geometry(
        module, module_dir, {"EJ1": _component("com.example.ej.a", _ENV_SMALL)}
    )
    assert any(code == "OCM_COMPONENT_OUTSIDE_COLLISION" for code, _p, _m in refusals), refusals


def test_authored_with_no_collision_file_is_refused(tmp_path: Path):
    module, module_dir = _module(tmp_path, {"collision_source": "authored", "collision": "missing.stl"})
    refusals, _ = check_module_collision_geometry(module, module_dir, {})
    assert any(code == "OCM_AUTHORED_COLLISION_MISSING" for code, _p, _m in refusals)

    module2, module_dir2 = _module(tmp_path, {"collision_source": "authored"})  # no path at all
    refusals2, _ = check_module_collision_geometry(module2, module_dir2, {})
    assert any(code == "OCM_AUTHORED_COLLISION_MISSING" for code, _p, _m in refusals2)


# ---------------------------------------------------------------------------
# D4: link names resolve into the fragment
# ---------------------------------------------------------------------------


def test_component_naming_unknown_link_is_refused(tmp_path: Path):
    module, module_dir = _module(
        tmp_path,
        {"collision_source": "derived"},
        components=[{"refdes": "EJ1", "ref": "com.example.ej.a@1.0.0",
                     "pose": {"xyz_mm": [0, 0, 0]}, "link": "ghost_axis"}],
    )
    refusals, _ = check_module_collision_geometry(module, module_dir, {"EJ1": _component("com.example.ej.a", _ENV_SMALL)})
    assert any(code == "OCM_LINK_UNKNOWN" for code, _p, _m in refusals), refusals


def test_component_naming_real_link_is_accepted(tmp_path: Path):
    module, module_dir = _module(
        tmp_path,
        {"collision_source": "derived"},
        components=[{"refdes": "EJ1", "ref": "com.example.ej.a@1.0.0",
                     "pose": {"xyz_mm": [0, 0, 0]}, "link": "z_carriage"}],
    )
    refusals, _ = check_module_collision_geometry(module, module_dir, {"EJ1": _component("com.example.ej.a", _ENV_SMALL)})
    assert not any(code == "OCM_LINK_UNKNOWN" for code, _p, _m in refusals), refusals


def test_structure_naming_unknown_link_is_refused(tmp_path: Path):
    module, module_dir = _module(
        tmp_path,
        {"collision_source": "derived"},
        structure=[{"id": "plate", "shape": "box", "size": [100, 100, 8], "units": "mm",
                    "pose": {"xyz": [0, 0, 0]}, "link": "nope"}],
    )
    refusals, _ = check_module_collision_geometry(module, module_dir, {})
    assert any(code == "OCM_LINK_UNKNOWN" for code, _p, _m in refusals), refusals


# ---------------------------------------------------------------------------
# D5: overlap is advise, never refuse
# ---------------------------------------------------------------------------


def test_overlapping_envelopes_advise_and_do_not_refuse(tmp_path: Path):
    module, module_dir = _module(
        tmp_path,
        {"collision_source": "derived"},
        components=[
            {"refdes": "A1", "ref": "com.example.ej.a@1.0.0", "pose": {"xyz_mm": [0, 0, 0]}},
            {"refdes": "B1", "ref": "com.example.ej.b@1.0.0", "pose": {"xyz_mm": [10, 0, 0]}},  # 40mm boxes, 10mm apart
        ],
    )
    comps = {
        "A1": _component("com.example.ej.a", _ENV_SMALL),
        "B1": _component("com.example.ej.b", _ENV_SMALL),
    }
    refusals, advisories = check_module_collision_geometry(module, module_dir, comps)
    assert refusals == []
    assert len(advisories) == 1
    assert advisories[0].startswith("OCM_ENVELOPE_OVERLAP:")
    assert "A1" in advisories[0] and "B1" in advisories[0]


# ---------------------------------------------------------------------------
# The derived proxy
# ---------------------------------------------------------------------------


def test_derived_elements_emit_boxes_per_link_with_units_converted(tmp_path: Path):
    module, _ = _module(
        tmp_path,
        {"collision_source": "derived"},
        components=[{"refdes": "EJ1", "ref": "com.example.ej.a@1.0.0",
                     "pose": {"xyz_mm": [0, 0, 94]}, "link": "z_carriage"}],
        structure=[{"id": "plate", "shape": "box", "size": [180, 120, 8], "units": "mm",
                    "pose": {"xyz": [0, 0, 0]}},
                   {"id": "riser", "shape": "cylinder", "radius": 1, "length": 2, "units": "in",
                    "pose": {"xyz": [0, 0, 0]}, "link": "base"}],
    )
    # envelope in INCHES: 1in cube -> 0.0254 m box in the URDF
    env_in = {"length": 1.0, "width": 1.0, "height": 1.0, "units": "in"}
    elements = derived_collision_elements(module, {"EJ1": _component("com.example.ej.a", env_in)})

    # component riding z_carriage
    carriage = elements["z_carriage"]
    assert len(carriage) == 1
    box = carriage[0].find("geometry/box")
    assert box.get("size") == "0.0254 0.0254 0.0254"
    assert carriage[0].find("origin").get("xyz") == "0 0 0.094"

    # structure: plate on the root (None), riser on 'base'
    root_elems = elements[None]
    assert root_elems[0].find("geometry/box").get("size") == "0.18 0.12 0.008"
    base_elems = elements["base"]
    cyl = base_elems[0].find("geometry/cylinder")
    assert cyl.get("radius") == "0.0254"
    assert cyl.get("length") == "0.0508"
