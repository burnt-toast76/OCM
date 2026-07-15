# SPDX-License-Identifier: AGPL-3.0-or-later
from ocm_core import load_module
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
