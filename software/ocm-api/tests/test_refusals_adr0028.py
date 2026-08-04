# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0028 Erratum 1, api-side: a fragment that exists but is malformed XML
refuses at validate (OCM_FRAGMENT_MALFORMED) instead of silently disabling
every fragment-dependent check; and the joint_state limit messages route
through translate.py's scene_error_to_refusal rather than an embedded prefix.
"""

from __future__ import annotations

from pathlib import Path

from ocm_api import Codes, OcmApi
from ocm_api.translate import scene_error_to_refusal


def test_malformed_fragment_refuses_instead_of_validating_green(api: OcmApi, workspace_root: Path):
    api.create_module_draft("com.example.fix.badfrag", "fixture")
    e = api.update_module(
        "com.example.fix.badfrag",
        patch=[{"op": "add", "path": "/mechanical/geometry/urdf_fragment", "value": "urdf/broken.urdf"}],
    )
    assert e.ok, e.refusals

    frag = workspace_root / "modules" / "com.example.fix.badfrag" / "urdf" / "broken.urdf"
    frag.parent.mkdir(parents=True, exist_ok=True)
    frag.write_text("<robot><link name='unterminated></robot>", encoding="utf-8")

    validated = api.validate_module("com.example.fix.badfrag")
    assert not validated.ok
    r = next(r for r in validated.refusals if r.code == Codes.OCM_FRAGMENT_MALFORMED)
    assert r.path == "mechanical.geometry.urdf_fragment"
    assert "not well-formed XML" in r.message


def test_scene_error_maps_joint_state_range_violation():
    error = "instance 'robot1': joint_state drives 'wrist_pitch' to 2.5, outside its declared limit [-1.0, 1.0]"
    r = scene_error_to_refusal(error)
    assert r.code == Codes.OCM_JOINT_STATE_OUT_OF_LIMIT
    assert r.path == "modules['robot1'].joint_state['wrist_pitch']"
    assert r.hint is not None


def test_scene_error_maps_joint_state_missing_limit():
    error = "instance 'robot1': joint_state drives 'bad_pitch' but the revolute joint declares no <limit> -- malformed URDF; a value cannot be checked against a limit that is missing"
    r = scene_error_to_refusal(error)
    assert r.code == Codes.OCM_JOINT_STATE_OUT_OF_LIMIT
    assert r.path == "modules['robot1'].joint_state['bad_pitch']"
