# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0029 D7, tesseract-free: the trace is the artifact and the
animated HTML is one consumer of it. Built on the same synthetic
jaw-fixture cell test_timeline.py uses, with the Bullet backend stubbed
(`no_collision_backend`) so the real walk/check machinery runs everywhere
-- rendering itself is pure Python (forward kinematics + templating)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ocm_generator.emitters import build_animation_payload, build_trace, render_html_animation
from ocm_generator.emitters.animation import _dynamic_instances
from ocm_generator.planner import build_timeline

import xml.etree.ElementTree as ET

from .test_timeline import _DOGFOOD_SHAPE_PLAN, _SAMPLES, _fake_plan, _resolved_scene


def _trace(tmp_path: Path):
    resolved, scene = _resolved_scene(tmp_path, _DOGFOOD_SHAPE_PLAN)
    timeline = build_timeline(resolved, scene, _fake_plan(["hole_1", "hole_2"]), path_samples=_SAMPLES)
    return scene, resolved, timeline, build_trace(scene, resolved, timeline)


def test_dynamic_set_includes_a_module_instance_whose_joint_moves(tmp_path: Path, no_collision_backend: None):
    scene, resolved, timeline, trace = _trace(tmp_path)

    dynamic = _dynamic_instances(ET.fromstring(trace["urdf_xml"]), trace)
    # fix1's jaw sweeps in the clamp/unclamp actuation rows: it is dynamic
    # BY ITS FRAMES, with no mount-topology reasoning anywhere. (The
    # synthetic robot's fragment has no movable joints -- the fake plan's
    # UR joint values name joints that don't exist in this URDF -- so
    # nothing else in this cell actually moves.)
    assert "fix1" in dynamic
    assert "base" not in dynamic


def test_every_trace_row_renders_one_animation_entry(tmp_path: Path, no_collision_backend: None):
    scene, resolved, timeline, trace = _trace(tmp_path)

    payload = build_animation_payload(trace)

    assert [seg["name"] for seg in payload["animation"]] == [row.label for row in timeline.rows]
    by_name = {seg["name"]: seg for seg in payload["animation"]}
    # Actuation rows carry a full checked sweep (D6), dwells one held frame.
    assert len(by_name["fix1.clamp"]["frames"]) == _SAMPLES
    assert len(by_name["fix1.unclamp"]["frames"]) == _SAMPLES
    assert len(by_name["load_screw @ hole_1"]["frames"]) == 1
    assert len(by_name["home -> standoff_1"]["frames"]) == _SAMPLES
    assert payload["total_duration_s"] == pytest.approx(timeline.total_s)


def test_the_jaws_actually_move_on_screen_during_clamp(tmp_path: Path, no_collision_backend: None):
    scene, resolved, timeline, trace = _trace(tmp_path)

    payload = build_animation_payload(trace)
    clamp = next(seg for seg in payload["animation"] if seg["name"] == "fix1.clamp")
    # The jaw link's transform changes across the sweep -- swept motion on
    # screen, not a held pose (phase 1's behaviour, now gone).
    assert clamp["frames"][0] != clamp["frames"][-1]


def test_trace_round_trip_renders_identically(tmp_path: Path, no_collision_backend: None):
    # D7: emitting the trace to JSON and rendering from what was read back
    # produces the same frames (and the same page) as rendering directly
    # -- the trace really is the interface, with nothing living only in
    # memory alongside it.
    scene, resolved, timeline, trace = _trace(tmp_path)

    round_tripped = json.loads(json.dumps(trace))
    assert build_animation_payload(round_tripped) == build_animation_payload(trace)
    assert render_html_animation(round_tripped) == render_html_animation(trace)


def test_dwell_after_actuation_is_drawn_at_the_post_actuation_state(tmp_path: Path, no_collision_backend: None):
    # The stale-held-frame hazard, at the RENDERED level: the dwell right
    # after clamp draws the exact transforms of the clamp sweep's final
    # frame -- jaws closed -- not any earlier state.
    scene, resolved, timeline, trace = _trace(tmp_path)

    payload = build_animation_payload(trace)
    by_name = {seg["name"]: seg for seg in payload["animation"]}
    assert by_name["load_screw @ hole_1"]["frames"][0] == by_name["fix1.clamp"]["frames"][-1]
