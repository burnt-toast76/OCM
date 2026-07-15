# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import pytest

from ocm_generator.scene import build_scene, render_html, scene_to_payload


def test_payload_has_one_color_per_instance_including_base(tiny_resolved_cell, modules_root):
    scene = build_scene(tiny_resolved_cell, modules_root)

    payload = scene_to_payload(scene, tiny_resolved_cell)

    assert payload["instances"] == ["base", "robot1", "tool1"]
    assert set(payload["colors"]) == {"base", "robot1", "tool1"}
    assert len(set(payload["colors"].values())) == 3  # all distinct


def test_payload_has_one_box_primitive_per_collision_link(tiny_resolved_cell, modules_root):
    # base: 1 link (origin). robot1: 2 links (origin, flange). tool1: 1 link
    # (origin) -- all box collisions per conftest's fragment_xml. 4 total.
    scene = build_scene(tiny_resolved_cell, modules_root)

    payload = scene_to_payload(scene, tiny_resolved_cell)

    boxes = [p for p in payload["primitives"] if p["kind"] == "box"]
    assert len(boxes) == 4
    assert all(not p["placeholder"] for p in boxes)

    by_link = {p["link"]: p for p in payload["primitives"]}
    assert by_link["robot1__flange"]["instance"] == "robot1"
    assert by_link["tool1__origin"]["instance"] == "tool1"
    assert by_link["robot1__flange"]["dims"] == {"x": 0.02, "y": 0.02, "z": 0.02}


def test_mount_attachment_marker_lands_on_the_real_flange_position(tiny_resolved_cell, modules_root):
    # robot1's mount.pose is xyz_mm=[400,300,0], rpy_deg=[0,0,90] (0.4, 0.3, 0
    # m, 90 deg yaw). Its 'flange' link is a further +0.4m along LOCAL Z from
    # its own fragment (conftest's fragment_xml extra_xyz=(0,0,0.4)) -- since
    # a rotation about Z leaves a Z-offset unchanged, the flange lands
    # exactly at (0.4, 0.3, 0.4) regardless of the yaw.
    scene = build_scene(tiny_resolved_cell, modules_root)

    payload = scene_to_payload(scene, tiny_resolved_cell)

    mount_markers = [m for m in payload["markers"] if "mount for tool1" in m["label"]]
    assert len(mount_markers) == 1
    assert mount_markers[0]["label"].startswith("robot1__flange")
    assert mount_markers[0]["position"] == pytest.approx([0.4, 0.3, 0.4], abs=1e-9)


def test_tcp_marker_present_for_tool1_and_positioned_past_the_flange(tiny_resolved_cell, modules_root):
    # tool1 is mounted (identity offset) directly on robot1's flange, so
    # tool1's own origin is also at (0.4, 0.3, 0.4). Its frames.tcp is
    # xyz_mm=[0,0,100] (+0.1m local Z) with no rotation of its own -- and
    # since the whole chain above it is a pure Z-axis rotation, that +0.1m
    # local-Z offset survives untouched into world space.
    scene = build_scene(tiny_resolved_cell, modules_root)

    payload = scene_to_payload(scene, tiny_resolved_cell)

    tcp_markers = [m for m in payload["markers"] if m["label"] == "tool1 TCP"]
    assert len(tcp_markers) == 1
    assert tcp_markers[0]["position"] == pytest.approx([0.4, 0.3, 0.5], abs=1e-9)


def test_render_html_is_self_contained_and_includes_expected_pieces(tiny_resolved_cell, modules_root):
    scene = build_scene(tiny_resolved_cell, modules_root)

    page = render_html(scene, tiny_resolved_cell)

    assert page.startswith("<!doctype html>")
    assert '<script type="importmap">' in page
    assert "unpkg.com/three" in page
    assert "OrbitControls.js" in page
    assert "CSS2DRenderer.js" in page
    assert "com.example.cell.tiny01" in page  # title + legend heading
    assert "tool1 TCP" in page
    assert "robot1__flange" in page
    # no accidental premature script close from the embedded JSON
    assert "</script" not in page.split('<script type="module">')[1].split("</script>")[0]
    assert "<title>OCM scene: com.example.cell.tiny01</title>" in page
