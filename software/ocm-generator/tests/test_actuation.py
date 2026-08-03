# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0028 fragment-dependent checks (scene/actuation.py): one test per code,
the unactuated advisory, and a clean pass. Fragments are built INLINE with
obviously-synthetic values -- authoring a real module's fragment (jaw stroke,
axis, limits) is the owner's design work, out of scope per ADR-0014."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ocm_core import Module
from ocm_generator.scene.actuation import check_module_actuation

# A synthetic two-jaw fixture fragment: one prismatic joint with limits, one
# revolute with limits, one revolute WITHOUT limits (malformed), one fixed.
_FRAGMENT = """<robot name="synthetic-test-fixture">
  <link name="base"/>
  <link name="jaw"/>
  <link name="arm"/>
  <link name="bad_arm"/>
  <link name="cover"/>
  <joint name="jaw_slide" type="prismatic">
    <parent link="base"/><child link="jaw"/>
    <axis xyz="1 0 0"/>
    <limit lower="0.0" upper="0.012" effort="10" velocity="0.1"/>
  </joint>
  <joint name="arm_pivot" type="revolute">
    <parent link="base"/><child link="arm"/>
    <axis xyz="0 0 1"/>
    <limit lower="-1.57" upper="1.57" effort="10" velocity="1"/>
  </joint>
  <joint name="bad_pivot" type="revolute">
    <parent link="base"/><child link="bad_arm"/>
    <axis xyz="0 0 1"/>
  </joint>
  <joint name="cover_mount" type="fixed">
    <parent link="base"/><child link="cover"/>
  </joint>
</robot>
"""


def _module(tmp_path: Path, actuates_by_cap: dict[str, list[dict[str, Any]]]) -> tuple[Module, Path]:
    module_dir = tmp_path / "mod"
    (module_dir / "urdf").mkdir(parents=True, exist_ok=True)
    (module_dir / "urdf" / "t.urdf").write_text(_FRAGMENT, encoding="utf-8")
    caps = [
        {"name": name, "summary": "x", "timeout_s": 3.0, "on_timeout": "hold", "actuates": acts}
        for name, acts in actuates_by_cap.items()
    ]
    module = Module.from_dict({
        "ocm_version": "1.1",
        "id": "com.example.fixture.synthetic",
        "revision": "1.0.0",
        "kind": "fixture",
        "license": "CERN-OHL-S-2.0",
        "mechanical": {
            "mount": {"interface": "custom"},
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}},
            "geometry": {"urdf_fragment": "urdf/t.urdf"},
            "mass_kg": 1.0,
        },
        "state_machine": {"model": "packml", "abort_safe": True},
        "capabilities": caps,
    })
    return module, module_dir


def _codes(refusals: list[tuple[str, str, str]]) -> list[str]:
    return [code for code, _p, _m in refusals]


def test_clean_actuation_passes_with_no_refusals(tmp_path: Path):
    module, module_dir = _module(tmp_path, {
        "clamp": [{"joint": "jaw_slide", "to": 10.0, "units": "mm"}],   # 0.010 m, inside [0, 0.012]
        "swing": [{"joint": "arm_pivot", "to": 45.0, "units": "deg"}],  # ~0.785 rad, inside [-1.57, 1.57]
    })
    refusals, advisories = check_module_actuation(module, module_dir)
    assert refusals == []
    # bad_pivot is movable and unactuated -> exactly one advisory
    assert len(advisories) == 1 and "bad_pivot" in advisories[0]


def test_unknown_joint_is_refused_listing_known_names(tmp_path: Path):
    module, module_dir = _module(tmp_path, {
        "clamp": [{"joint": "ghost_joint", "to": 1.0, "units": "mm"}],
    })
    refusals, _ = check_module_actuation(module, module_dir)
    assert _codes(refusals) == ["OCM_ACTUATION_JOINT_UNKNOWN"]
    assert "(has: ['arm_pivot', 'bad_pivot', 'cover_mount', 'jaw_slide'])" in refusals[0][2]


def test_fixed_joint_is_refused(tmp_path: Path):
    module, module_dir = _module(tmp_path, {
        "clamp": [{"joint": "cover_mount", "to": 1.0, "units": "mm"}],
    })
    refusals, _ = check_module_actuation(module, module_dir)
    assert _codes(refusals) == ["OCM_ACTUATION_JOINT_FIXED"]


def test_angular_unit_on_prismatic_joint_is_refused(tmp_path: Path):
    module, module_dir = _module(tmp_path, {
        "clamp": [{"joint": "jaw_slide", "to": 45.0, "units": "deg"}],
    })
    refusals, _ = check_module_actuation(module, module_dir)
    assert _codes(refusals) == ["OCM_ACTUATION_UNIT_MISMATCH"]
    assert "prismatic joint takes a length" in refusals[0][2]


def test_length_unit_on_revolute_joint_is_refused(tmp_path: Path):
    module, module_dir = _module(tmp_path, {
        "swing": [{"joint": "arm_pivot", "to": 10.0, "units": "mm"}],
    })
    refusals, _ = check_module_actuation(module, module_dir)
    assert _codes(refusals) == ["OCM_ACTUATION_UNIT_MISMATCH"]
    assert "revolute joint takes an angle" in refusals[0][2]


def test_target_beyond_limit_is_refused_in_urdf_native_units(tmp_path: Path):
    # 20 mm -> 0.020 m, outside jaw_slide's [0, 0.012]; and 1 inch -> 0.0254 m,
    # also outside -- the conversion goes through ocm_core.units, not ad hoc.
    module, module_dir = _module(tmp_path, {
        "clamp": [{"joint": "jaw_slide", "to": 20.0, "units": "mm"}],
        "clamp2": [{"joint": "jaw_slide", "to": 1.0, "units": "in"}],
    })
    refusals, _ = check_module_actuation(module, module_dir)
    assert _codes(refusals) == ["OCM_ACTUATION_OUT_OF_LIMIT", "OCM_ACTUATION_OUT_OF_LIMIT"]
    assert "outside its declared limit [0.0, 0.012]" in refusals[0][2]


def test_revolute_target_beyond_limit_is_refused(tmp_path: Path):
    module, module_dir = _module(tmp_path, {
        "swing": [{"joint": "arm_pivot", "to": 180.0, "units": "deg"}],  # pi > 1.57
    })
    refusals, _ = check_module_actuation(module, module_dir)
    assert _codes(refusals) == ["OCM_ACTUATION_OUT_OF_LIMIT"]


def test_revolute_joint_with_no_limit_is_refused_not_silently_passed(tmp_path: Path):
    module, module_dir = _module(tmp_path, {
        "swing": [{"joint": "bad_pivot", "to": 10.0, "units": "deg"}],
    })
    refusals, _ = check_module_actuation(module, module_dir)
    assert _codes(refusals) == ["OCM_ACTUATION_OUT_OF_LIMIT"]
    assert "declares no <limit>" in refusals[0][2]


def test_every_movable_joint_actuated_yields_no_advisory(tmp_path: Path):
    module, module_dir = _module(tmp_path, {
        "clamp": [{"joint": "jaw_slide", "to": 10.0, "units": "mm"}],
        "swing": [{"joint": "arm_pivot", "to": 45.0, "units": "deg"}],
        "wave": [{"joint": "bad_pivot", "to": 0.0, "units": "deg"}],  # actuated (refuses no-limit, but not unactuated)
    })
    _refusals, advisories = check_module_actuation(module, module_dir)
    assert advisories == []


def test_no_actuates_anywhere_renders_static_and_advises_per_movable_joint(tmp_path: Path):
    # D4: absence is legitimate (a capability that moves nothing) -- no
    # refusal; every movable joint lands on the completion list as advice.
    module, module_dir = _module(tmp_path, {"observe": []})
    refusals, advisories = check_module_actuation(module, module_dir)
    assert refusals == []
    assert len(advisories) == 3  # jaw_slide, arm_pivot, bad_pivot; cover_mount is fixed
    assert all(a.startswith("OCM_JOINT_UNACTUATED:") for a in advisories)
