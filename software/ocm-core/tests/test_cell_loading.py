# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest
import yaml

from ocm_core import load_cell, load_module
from ocm_core.cell import Cell
from ocm_core.errors import CellLoadError
from ocm_core.loader import load_schema, validate_module_dict


def test_loads_bracket_cell(bracket_cell_path):
    cell = load_cell(bracket_cell_path)
    assert isinstance(cell, Cell)
    assert cell.id == "com.accelsolutions.cell.bracket-asm-01"
    assert cell.base.module.id == "com.accelsolutions.base.frame1200"
    assert cell.base.module.revision == "2.0.0"
    assert {m.instance for m in cell.modules} == {"robot1", "sd1", "feed1", "nest1", "cam1", "disp1"}


def test_module_instance_mount_and_address(bracket_cell_path):
    cell = load_cell(bracket_cell_path)

    robot1 = cell.module("robot1")
    assert robot1.mount.station == (400, 300)
    assert robot1.address.ip == "192.168.1.10"

    sd1 = cell.module("sd1")
    assert sd1.mount.on == "robot1.flange"

    feed1 = cell.module("feed1")
    assert feed1.address.ethercat_position == 5


def test_module_instance_consumables_are_parsed(tmp_path, bracket_cell_path):
    # sd1 doesn't declare `consumables` in the real, checked-in cell
    # either -- inject one into a copy so this structural parse path
    # stays covered, same pattern test_duplicate_instance_name_is_rejected
    # already uses below.
    data = yaml.safe_load(bracket_cell_path.read_text(encoding="utf-8"))
    feed1 = next(m for m in data["modules"] if m["instance"] == "feed1")
    feed1["consumables"] = {"screw": {"part": "M3x8 SHCS", "source": "feed1"}}
    path = tmp_path / "cell_with_consumables.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    cell = load_cell(path)
    feed1_loaded = cell.module("feed1")
    assert feed1_loaded.consumables["screw"].part == "M3x8 SHCS"
    assert feed1_loaded.consumables["screw"].source == "feed1"


def test_module_instance_joint_state_defaults_to_empty(bracket_cell_path):
    cell = load_cell(bracket_cell_path)
    assert cell.module("sd1").joint_state == {}


def test_robot1_carries_its_folded_home_joint_state(bracket_cell_path):
    # robot1 is the one instance in the real cell that actually needs
    # this: without it, the arm defaults to all-zero, which puts sd1
    # outside the workspace footprint (see ocm-generator's containment
    # check and its regression test for this exact cell).
    cell = load_cell(bracket_cell_path)
    joint_state = cell.module("robot1").joint_state
    assert joint_state["shoulder_lift_joint"] == pytest.approx(-1.5707963267948966)
    assert joint_state["elbow_joint"] == pytest.approx(1.5707963267948966)


def test_module_instance_joint_state_is_parsed_as_radians(tmp_path, bracket_cell_path):
    data = yaml.safe_load(bracket_cell_path.read_text(encoding="utf-8"))
    robot1 = next(m for m in data["modules"] if m["instance"] == "robot1")
    robot1["joint_state"] = {"shoulder_lift_joint": -1.5707963267948966, "elbow_joint": 1}
    path = tmp_path / "cell_with_joint_state.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    cell = load_cell(path)

    joint_state = cell.module("robot1").joint_state
    assert joint_state["shoulder_lift_joint"] == pytest.approx(-1.5707963267948966)
    assert joint_state["elbow_joint"] == pytest.approx(1.0)
    assert isinstance(joint_state["elbow_joint"], float)  # coerced, not left as a YAML int


def test_controller_and_safety(bracket_cell_path):
    cell = load_cell(bracket_cell_path)
    assert cell.controller.runtime == "beremiz"
    assert cell.controller.fieldbus == "ethercat"
    assert cell.safety.performance_level == "PLd"
    assert cell.safety.relay == "Pilz PNOZ s4"


def test_part_and_plan_are_passed_through_untyped(tmp_path, bracket_cell_path):
    # part/plan are the planner's DSL; ocm-core loads them as raw data
    # rather than interpreting them (ocm-generator's job, not this one).
    # The real cell's own `plan:` is currently empty (its fastening plan
    # hasn't been redesigned since robot1's end effector was swapped from
    # a screwdriver to a gripper) -- inject a representative plan into a
    # copy so the passthrough itself stays covered.
    data = yaml.safe_load(bracket_cell_path.read_text(encoding="utf-8"))
    assert data["part"]["id"] == "BRK-4471"
    data["plan"] = [
        {"step": "clamp", "module": "nest1", "op": "clamp"},
        {"step": "fasten", "for_each": ["hole_1", "hole_2", "hole_3"], "sequence": []},
        {"step": "release", "module": "nest1", "op": "unclamp"},
    ]
    path = tmp_path / "cell_with_plan.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    cell = load_cell(path)
    assert cell.part["id"] == "BRK-4471"
    assert cell.plan[0]["step"] == "clamp"
    assert cell.plan[1]["for_each"] == ["hole_1", "hole_2", "hole_3"]


def test_module_ref_referenced_by_a_cell_can_load_the_real_manifest(bracket_cell_path, repo_root):
    # The cell references sd1 by id@revision; confirm that ref actually
    # resolves to the real manifest on disk (loose but useful cross-check).
    cell = load_cell(bracket_cell_path)
    sd1_ref = cell.module("sd1").module
    manifest_path = repo_root / "modules" / sd1_ref.id / "module.yaml"
    module = load_module(manifest_path)
    assert module.id == sd1_ref.id
    assert module.revision == sd1_ref.revision


def test_cell_yaml_is_not_a_valid_module_manifest(bracket_cell_path, schema_path):
    # cell.yaml is a different shape entirely (composition, not a module).
    # ocm-core doesn't validate it against the module schema -- pin that.
    data = yaml.safe_load(bracket_cell_path.read_text(encoding="utf-8"))
    errors = validate_module_dict(data, load_schema(schema_path))
    assert errors


def test_duplicate_instance_name_is_rejected(tmp_path, bracket_cell_path):
    data = yaml.safe_load(bracket_cell_path.read_text(encoding="utf-8"))
    dup = dict(data["modules"][0])
    dup["instance"] = data["modules"][1]["instance"]
    data["modules"].append(dup)
    bad_path = tmp_path / "bad_cell.yaml"
    bad_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(CellLoadError):
        load_cell(bad_path)


def test_missing_base_is_rejected(tmp_path, bracket_cell_path):
    data = yaml.safe_load(bracket_cell_path.read_text(encoding="utf-8"))
    del data["base"]
    bad_path = tmp_path / "bad_no_base.yaml"
    bad_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(CellLoadError) as exc:
        load_cell(bad_path)
    assert "base" in str(exc.value)


def test_malformed_module_ref_is_rejected(tmp_path, bracket_cell_path):
    data = yaml.safe_load(bracket_cell_path.read_text(encoding="utf-8"))
    data["modules"][0]["module"] = "not-a-valid-ref-missing-revision"
    bad_path = tmp_path / "bad_ref.yaml"
    bad_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(CellLoadError):
        load_cell(bad_path)
