# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every verb's happy path, called straight through the `OcmApi` facade
(the library layer the MCP server and the HTTP wrapper both sit on --
see test_transports.py for proof they respond identically).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ocm_api import Codes, OcmApi

from .conftest import CLEAN_MODULE_ID

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_describe_schema_whole_document(api: OcmApi):
    e = api.describe_schema()
    assert e.ok
    assert "1.1" in e.data["ocm_version"]
    assert e.data["schema"]["title"].startswith("OCM Module Definition")


def test_describe_schema_section(api: OcmApi):
    e = api.describe_schema("capabilities")
    assert e.ok
    assert e.data["section"] == "capabilities"
    assert e.data["schema"]["type"] == "array"


def test_describe_schema_defaults_to_module_target(api: OcmApi):
    e = api.describe_schema()
    assert e.ok
    assert e.data["target"] == "module"


def test_describe_schema_component_target(api: OcmApi):
    # ADR-0014 gave components their own schema (spec/10) -- target
    # selects which one, so a component-authoring caller (the Components
    # page's form, /agent/chat) isn't stuck reading the module schema.
    e = api.describe_schema(target="component")
    assert e.ok
    assert e.data["target"] == "component"
    assert e.data["schema"]["title"].startswith("OCM Component Definition")
    assert "vendor" in e.data["schema"]["properties"]
    assert "mechanical" not in e.data["schema"]["properties"]  # module-only section


def test_describe_schema_unknown_target_is_refused(api: OcmApi):
    e = api.describe_schema(target="cell")
    assert not e.ok
    assert e.refusals[0].code == Codes.INVALID_ARGUMENT


def test_get_example_for_every_registered_kind(api: OcmApi):
    from ocm_api.discovery import EXAMPLE_MODULE_BY_KIND

    for kind, module_id in EXAMPLE_MODULE_BY_KIND.items():
        e = api.get_example(kind)
        assert e.ok, (kind, e.refusals)
        assert e.data["module_id"] == module_id
        assert "ocm_version" in e.data["manifest_yaml"]


def test_list_modules(api: OcmApi):
    e = api.list_modules()
    assert e.ok
    ids = {row["id"] for row in e.data}
    assert "com.accelsolutions.screwdriver.sd50" in ids
    dh200 = next(row for row in e.data if row["id"] == "com.accelsolutions.dispense.dh200")
    assert dh200["draft"] is True  # a real, pre-existing 0.x manifest


def test_describe_module(api: OcmApi):
    e = api.describe_module("com.accelsolutions.screwdriver.sd50")
    assert e.ok
    assert e.data["revision"] == "1.2.0"
    assert e.data["draft"] is False
    assert e.data["manifest"]["kind"] == "end_effector"


def test_list_cells(api: OcmApi):
    e = api.list_cells()
    assert e.ok
    assert {"cell_id": "bracket-asm-01", "id": "com.accelsolutions.cell.bracket-asm-01", "name": "Bracket Assembly Cell 01"} in e.data


def test_describe_cell(api: OcmApi):
    e = api.describe_cell("bracket-asm-01")
    assert e.ok
    names = {row["instance"] for row in e.data["instances"]}
    assert names == {"robot1", "sd1", "feed1", "nest1", "cam1"}


def test_list_frames(api: OcmApi):
    e = api.list_frames("bracket-asm-01")
    assert e.ok
    assert "nest1.part_datum" in e.data
    assert "robot1.flange" in e.data
    assert "sd1.tcp" in e.data


# ---------------------------------------------------------------------------
# Module authoring
# ---------------------------------------------------------------------------


def test_create_module_draft_end_effector(api: OcmApi):
    e = api.create_module_draft("com.example.pickhead.pk100", "end_effector")
    assert e.ok
    assert e.data["draft"] is True
    assert e.data["revision"] == "0.1.0"

    # ADR-0016 Decision 3: a fresh draft omits its geometry artifact claim
    # rather than placeholder a collision path to a file that does not exist,
    # so it reaches a definite done state -- the manifest is complete,
    # artifacts are pending. validate_module is clean; publish_module is what
    # later requires the geometry (see test_publish_requires_geometry).
    validated = api.validate_module("com.example.pickhead.pk100")
    assert validated.ok, validated.refusals
    assert "collision" not in api.describe_module("com.example.pickhead.pk100").data["manifest"]["mechanical"]["geometry"]


def test_update_module_writes_and_validates(api: OcmApi):
    api.create_module_draft("com.example.pickhead.pk101", "end_effector")
    manifest = api.describe_module("com.example.pickhead.pk101").data["manifest"]
    manifest["name"] = "Pick Head 101"

    e = api.update_module("com.example.pickhead.pk101", manifest=manifest)
    assert e.ok
    assert api.describe_module("com.example.pickhead.pk101").data["manifest"]["name"] == "Pick Head 101"


def test_update_module_with_json_patch(api: OcmApi):
    api.create_module_draft("com.example.pickhead.pk102", "end_effector")
    e = api.update_module("com.example.pickhead.pk102", patch=[{"op": "replace", "path": "/name", "value": "Patched"}])
    assert e.ok
    assert api.describe_module("com.example.pickhead.pk102").data["manifest"]["name"] == "Patched"


def test_update_module_can_write_a_components_entry_pose(api: OcmApi):
    # Modules-page authoring: a component instance's own local placement in
    # the module's assembly scene. update_module is a fully generic patch
    # writer gated only by schema validation -- this proves the new
    # components[].pose schema field is writable with ZERO code changes to
    # update_module itself, not just asserted in prose.
    api.create_module_draft("com.example.pickhead.pk104", "end_effector")
    added = api.update_module(
        "com.example.pickhead.pk104",
        patch=[{"op": "add", "path": "/components", "value": [{"refdes": "VG1", "ref": "com.smc.ejector.zk2-agh@1.0.0"}]}],
    )
    assert added.ok, added.refusals

    posed = api.update_module(
        "com.example.pickhead.pk104",
        patch=[{"op": "add", "path": "/components/0/pose", "value": {"xyz_mm": [10.0, 20.0, 30.0], "rpy_deg": [0.0, 0.0, 90.0]}}],
    )
    assert posed.ok, posed.refusals

    manifest = api.describe_module("com.example.pickhead.pk104").data["manifest"]
    assert manifest["components"][0]["pose"] == {"xyz_mm": [10.0, 20.0, 30.0], "rpy_deg": [0.0, 0.0, 90.0]}


def test_update_module_rejects_a_malformed_components_pose(api: OcmApi):
    api.create_module_draft("com.example.pickhead.pk105", "end_effector")
    api.update_module(
        "com.example.pickhead.pk105",
        patch=[{"op": "add", "path": "/components", "value": [{"refdes": "VG1", "ref": "com.smc.ejector.zk2-agh@1.0.0"}]}],
    )

    # A 2-element xyz_mm and an extra, undeclared property are both real
    # schema violations -- plain validation already covers this, per
    # instance_pose's own additionalProperties: false / minItems/maxItems.
    e = api.update_module(
        "com.example.pickhead.pk105",
        patch=[{"op": "add", "path": "/components/0/pose", "value": {"xyz_mm": [10.0, 20.0], "bogus": True}}],
    )
    assert not e.ok
    assert any(r.code == Codes.SCHEMA_INVALID for r in e.refusals)


def test_generate_geometry_stub(api: OcmApi, workspace_root: Path):
    api.create_module_draft("com.example.pickhead.pk103", "end_effector")
    e = api.generate_geometry_stub("com.example.pickhead.pk103", (80, 60), 40)
    assert e.ok
    assert (workspace_root / "modules" / "com.example.pickhead.pk103" / e.data["urdf_fragment"]).is_file()

    validated = api.validate_module("com.example.pickhead.pk103")
    assert validated.ok, validated.refusals


def test_validate_module_happy_path(api: OcmApi):
    e = api.validate_module(CLEAN_MODULE_ID)
    assert e.ok
    assert e.data["valid"] is True


def test_publish_module(api: OcmApi):
    api.create_module_draft("com.example.pickhead.pk104", "end_effector")
    api.generate_geometry_stub("com.example.pickhead.pk104", (80, 60), 40)

    e = api.publish_module("com.example.pickhead.pk104", "1.0.0")
    assert e.ok
    assert e.data == {"id": "com.example.pickhead.pk104", "revision": "1.0.0", "draft": False, "published": True}
    assert api.describe_module("com.example.pickhead.pk104").data["draft"] is False


def test_validate_module_resolves_connectivity(api: OcmApi):
    # ADR-0016 Decision 1: validate_module runs the same connectivity
    # resolution a cell would -- a module port wired to nothing is refused
    # during authoring, not only later at cell resolution.
    api.create_module_draft("com.example.fix.conn1", "fixture")
    e = api.update_module(
        "com.example.fix.conn1",
        patch=[{"op": "add", "path": "/ports", "value": [{"id": "AIR_IN", "domain": "pneumatic", "thread": "G1/8", "function": "supply"}]}],
    )
    assert e.ok, e.refusals

    validated = api.validate_module("com.example.fix.conn1")
    assert not validated.ok
    assert any(r.code == Codes.PORT_UNCONNECTED for r in validated.refusals), [(r.code, r.message) for r in validated.refusals]


def test_publish_requires_geometry_a_draft_may_omit(api: OcmApi):
    # ADR-0016 Decision 3: a fresh draft omits its geometry artifact claim and
    # validates clean (a reachable done state); publish_module is what requires
    # the geometry, and generate_geometry_stub supplies it.
    api.create_module_draft("com.example.fix.pub1", "fixture")
    assert api.validate_module("com.example.fix.pub1").ok  # draft: artifacts pending, still valid

    refused = api.publish_module("com.example.fix.pub1", "1.0.0")
    assert not refused.ok
    assert any(r.code == Codes.NOT_FOUND and r.path == "mechanical.geometry.collision" for r in refused.refusals)

    api.generate_geometry_stub("com.example.fix.pub1", (100.0, 100.0), 50.0)
    assert api.publish_module("com.example.fix.pub1", "1.0.0").ok


# ---------------------------------------------------------------------------
# Cell composition
# ---------------------------------------------------------------------------


def test_create_cell(api: OcmApi):
    e = api.create_cell("my-new-cell", "com.accelsolutions.base.frame1200@2.0.0")
    assert e.ok
    assert e.data["cell_id"] == "my-new-cell"


def test_place_move_remove_instance(api: OcmApi):
    api.create_cell("assembly-a", "com.accelsolutions.base.frame1200@2.0.0")

    e = api.place_instance(
        "assembly-a", "robot1", "com.universal-robots.ur5e@3.1.0",
        {"pose": {"xyz_mm": [400, 300, 0], "rpy_deg": [0, 0, 0]}},
    )
    assert e.ok, e.refusals
    assert "robot1" in e.data["instances"]
    # frame1200's real footprint (deck + guard walls) extends beyond its
    # nominal 1200x900 footprint_mm -- an agent should be able to read that
    # tolerance from data, not discover it by tripping an overhang refusal.
    assert e.data["workspace_bounds"] == {"x_mm": [-50.0, 1250.0], "y_mm": [-50.0, 950.0]}

    e = api.move_instance("assembly-a", "robot1", {"pose": {"xyz_mm": [450, 300, 0], "rpy_deg": [0, 0, 0]}})
    assert e.ok, e.refusals

    e = api.remove_instance("assembly-a", "robot1")
    assert e.ok, e.refusals
    assert "robot1" not in e.data["instances"]


def test_set_plan(api: OcmApi):
    api.create_cell("assembly-b", "com.accelsolutions.base.frame1200@2.0.0")
    api.place_instance("assembly-b", "robot1", "com.universal-robots.ur5e@3.1.0", {"pose": {"xyz_mm": [400, 300, 0], "rpy_deg": [0, 0, 0]}})
    api.place_instance("assembly-b", "sd1", "com.accelsolutions.screwdriver.sd50@1.2.0", {"on": "robot1.flange"})
    api.set_joint_state("assembly-b", "robot1", {"shoulder_lift_joint": -1.5707963267948966, "elbow_joint": 1.5707963267948966})

    e = api.set_plan("assembly-b", [{"step": "fasten", "module": "sd1", "op": "drive_screw", "params": {"torque_nm": 2.4}}])
    assert e.ok, e.refusals


def test_set_joint_state(api: OcmApi):
    api.create_cell("assembly-c", "com.accelsolutions.base.frame1200@2.0.0")
    api.place_instance("assembly-c", "robot1", "com.universal-robots.ur5e@3.1.0", {"pose": {"xyz_mm": [400, 300, 0], "rpy_deg": [0, 0, 0]}})

    e = api.set_joint_state("assembly-c", "robot1", {"shoulder_lift_joint": -1.0})
    assert e.ok, e.refusals


# ---------------------------------------------------------------------------
# Checking & generation
# ---------------------------------------------------------------------------


def test_build_scene(api: OcmApi):
    e = api.build_scene("bracket-asm-01")
    assert e.ok
    assert e.data["n_links"] > 0
    assert e.data["n_joints"] > 0
    assert set(e.data["instances"]) == {"robot1", "sd1", "feed1", "nest1", "cam1"}
    # The composer's 3D view renders straight from this -- the same
    # primitives/colors/markers payload the debug HTML viewer embeds
    # (ocm_generator.scene.viewer.scene_to_payload), not a second
    # geometry-extraction path.
    assert e.data["primitives"], "expected at least one collision primitive"
    for prim in e.data["primitives"]:
        assert prim["kind"] in ("box", "cylinder", "sphere")
        assert len(prim["position"]) == 3
        assert len(prim["quaternion"]) == 4
    assert set(e.data["colors"]) == {"base", "robot1", "sd1", "feed1", "nest1", "cam1"}


def test_check_collision(api: OcmApi):
    pytest.importorskip("tesseract_robotics")
    e = api.check_collision("bracket-asm-01")
    assert e.ok, e.refusals
    assert e.data["margin_mm"] == 1.0


def test_plan_cell_and_emit(api: OcmApi, workspace_root: Path, tmp_path: Path):
    pytest.importorskip("tesseract_robotics")
    # The real bracket-asm-01's straight-line path to its holes is a
    # documented near-miss against cam1 (found empirically while building
    # ocm_generator.planner -- see its own test suite/README) that can
    # flip pass/fail between runs. Reposition cam1 out of the sweep for a
    # deterministic happy-path test; this is exactly what place_instance
    # exists to let an agent do.
    api.move_instance("bracket-asm-01", "cam1", {"pose": {"xyz_mm": [640, 300, 900], "rpy_deg": [180, 0, 0]}})

    e = api.plan_cell("bracket-asm-01")
    assert e.ok, e.refusals
    assert e.data["holes"] == ["hole_1", "hole_2", "hole_3"]
    assert e.data["naive_serial_total_s"] > 0
    assert len(e.data["cycle_table"]) > 0
    # Every row's full structure is populated -- the GUI/agent both need
    # duration/source AND which segment an overlapped load_screw hides
    # inside or a dwell is held at, not just a label.
    overlapped_rows = [row for row in e.data["cycle_table"] if row["source"] == "overlapped"]
    assert overlapped_rows
    for row in overlapped_rows:
        assert row["overlapped_with"]
        assert row["held_at_segment"]

    script_path = tmp_path / "out.script"
    view_path = tmp_path / "view.html"
    e = api.emit("bracket-asm-01", urscript=str(script_path), view=str(view_path))
    assert e.ok, e.refusals
    assert script_path.is_file()
    assert view_path.is_file()
    assert e.data["written"] == {"urscript": str(script_path), "view": str(view_path)}
