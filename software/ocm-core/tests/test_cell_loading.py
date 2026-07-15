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
    assert {m.instance for m in cell.modules} == {"robot1", "sd1", "feed1", "nest1", "cam1"}


def test_module_instance_mount_and_address(bracket_cell_path):
    cell = load_cell(bracket_cell_path)

    robot1 = cell.module("robot1")
    assert robot1.mount.station == (400, 300)
    assert robot1.address.ip == "192.168.1.10"

    sd1 = cell.module("sd1")
    assert sd1.mount.on == "robot1.flange"
    assert sd1.address.ethercat_position == 4
    assert sd1.consumables["screw"].part == "M3x8 SHCS"
    assert sd1.consumables["screw"].source == "feed1"


def test_controller_and_safety(bracket_cell_path):
    cell = load_cell(bracket_cell_path)
    assert cell.controller.runtime == "beremiz"
    assert cell.controller.fieldbus == "ethercat"
    assert cell.safety.performance_level == "PLd"
    assert cell.safety.relay == "Pilz PNOZ s4"


def test_part_and_plan_are_passed_through_untyped(bracket_cell_path):
    # part/plan are the planner's DSL; ocm-core loads them as raw data
    # rather than interpreting them (ocm-generator's job, not this one).
    cell = load_cell(bracket_cell_path)
    assert cell.part["id"] == "BRK-4471"
    assert cell.plan[0]["step"] == "clamp"
    assert cell.plan[2]["for_each"] == ["hole_1", "hole_2", "hole_3"]


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
