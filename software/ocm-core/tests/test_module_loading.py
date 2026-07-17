# SPDX-License-Identifier: AGPL-3.0-or-later
from ocm_core import Parameter, Signal, load_module
from ocm_core.module import Module


def test_loads_sd50_end_effector(sd50_path):
    module = load_module(sd50_path)
    assert isinstance(module, Module)
    assert module.id == "com.accelsolutions.screwdriver.sd50"
    assert module.kind == "end_effector"
    assert module.revision == "1.2.0"
    assert module.mechanical.mount.interface == "iso-9409-1-a50"
    assert module.mechanical.tcp.xyz_mm == (0, 0, 186.5)
    assert module.state_machine.abort_safe is False


def test_sd50_capability_bounds_are_hard_limits(sd50_path):
    module = load_module(sd50_path)
    drive = module.capability("drive_screw")
    torque = drive.parameters["torque_nm"]
    assert (torque.min, torque.max) == (0.20, 5.00)
    assert drive.motion.hold_still is True
    assert drive.motion.approach_vec == (0, 0, 1)
    assert drive.preconditions == ("screw_present == true",)
    assert drive.postconditions == ("screw_present == false", "result_ok == true")


def test_sd50_signals_carry_packml_roles(sd50_path):
    module = load_module(sd50_path)
    assert [s.name for s in module.comms.signals_with_role("packml_cmd")] == ["packml_cmd"]
    assert [s.name for s in module.comms.signals_with_role("fault_code")] == ["fault_code"]


def test_loads_dh200_process_module(dh200_path):
    module = load_module(dh200_path)
    assert module.kind == "process"
    assert module.process.warmup_s == 420
    assert module.process.idle_timeout_s == 180
    assert module.process.purge_required is True


def test_dh200_dispense_bead_moves_along_a_path(dh200_path):
    module = load_module(dh200_path)
    dispense = module.capability("dispense_bead")
    assert dispense.motion.hold_still is False
    assert dispense.motion.path.corner_radius_mm == 2.0
    assert dispense.motion.path.orientation == "normal_to_surface"
    assert dispense.parameters["bead_width_mm"].max == 6.0


def test_dh200_not_abort_safe(dh200_path):
    module = load_module(dh200_path)
    assert module.state_machine.abort_safe is False
    assert module.safety.required_performance_level == "PLc"
    assert module.safety.sto_required is False


# ---------------------------------------------------------------------------
# v1.1 composite types (spec/CHANGELOG.md): pose6d/vec3/struct carry `frame`
# and `fields` on Parameter (capability parameters/results) and Signal
# (comms.signals) alike -- everything else stays None.
# ---------------------------------------------------------------------------


def test_parameter_from_dict_carries_frame_for_pose6d():
    param = Parameter.from_dict({"type": "pose6d", "frame": "nest1.part_datum"})
    assert param.type == "pose6d"
    assert param.frame == "nest1.part_datum"
    assert param.fields is None


def test_parameter_from_dict_carries_fields_for_struct():
    param = Parameter.from_dict({"type": "struct", "fields": {"x": "number", "y": "number"}})
    assert param.type == "struct"
    assert param.fields == {"x": "number", "y": "number"}
    assert param.frame is None


def test_parameter_from_dict_leaves_frame_and_fields_none_for_scalars():
    param = Parameter.from_dict({"type": "number", "unit": "mm", "min": 0, "max": 10})
    assert param.frame is None
    assert param.fields is None


def test_signal_from_dict_carries_frame_for_pose6d():
    signal = Signal.from_dict(
        {"name": "part_pose", "direction": "input", "type": "pose6d", "frame": "nest1.part_datum", "role": "process_result"}
    )
    assert signal.type == "pose6d"
    assert signal.frame == "nest1.part_datum"
    assert signal.fields is None


def test_signal_from_dict_carries_fields_for_struct():
    signal = Signal.from_dict({"name": "blob", "direction": "input", "type": "struct", "fields": {"a": "int16", "b": "bool"}})
    assert signal.fields == {"a": "int16", "b": "bool"}
    assert signal.frame is None


def test_gocator_manifest_round_trips_through_the_object_model_with_frame_intact(gocator_path):
    module = load_module(gocator_path)

    assert module.ocm_version == "1.1"
    assert module.kind == "sensor"

    locate = module.capability("locate_part")
    part_pose = locate.results["part_pose"]
    assert part_pose.type == "pose6d"
    assert part_pose.frame == "nest1.part_datum"

    confidence = locate.results["confidence"]
    assert confidence.type == "number"
    assert confidence.unit == "%"
    assert confidence.frame is None
