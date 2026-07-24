# SPDX-License-Identifier: AGPL-3.0-or-later
import yaml

from ocm_core import Parameter, Signal, load_module
from ocm_core.module import ComponentRef, Electrical, Module, ModuleComponent

# ADR-0015's own worked example, verbatim except `connector` -> `ref`: the
# ADR's example predates the "no renaming, no alias layer" instruction --
# `ref` is the field ComponentConnector/ComponentCommsConnector actually
# call themselves (ocm_core.component), so an endpoint reuses that name
# rather than inventing a new one.
_CONNECTIVITY_MODULE = {
    "ocm_version": "1.1",
    "id": "com.example.pickhead.pk100",
    "revision": "0.1.0",
    "kind": "fixture",
    "license": "CERN-OHL-S-2.0",
    "mechanical": {
        "mount": {"interface": "custom"},
        "frames": {"origin": {"xyz_mm": [0, 0, 0]}},
        "geometry": {"collision": "x.stl"},
        "mass_kg": 1.0,
    },
    "state_machine": {"model": "packml"},
    "components": [
        {"refdes": "PS1", "ref": "com.smc.ejector.zk2-agh@1.0.0"},
        {"refdes": "DP1", "ref": "com.nordson-kline.dispenser.dp8@1.0.0"},
    ],
    "ports": [
        {"id": "PWR_IN", "domain": "electrical", "type": "M12-A-4P"},
        {"id": "AIR_IN", "domain": "pneumatic", "thread": "G1/8", "function": "supply"},
        {"id": "NET_IN", "domain": "communication", "protocol": "ethercat", "role": "slave_in"},
    ],
    "nets": {
        "electrical": [
            {
                "id": "N_24V",
                "endpoints": [
                    {"port": "PWR_IN", "pin": "1"},
                    {"refdes": "PS1", "ref": "electrical", "pin": "1"},
                ],
            }
        ],
        "pneumatic": [
            {
                "id": "C_SUPPLY",
                "pressure": 6,
                "pressure_units": "bar",
                "endpoints": [
                    {"port": "AIR_IN"},
                    {"refdes": "DP1", "ref": "air_in"},
                ],
            }
        ],
    },
    "links": [
        {
            "id": "L_EC_1",
            "protocol": "ethercat",
            "a": {"port": "NET_IN"},
            "b": {"refdes": "DP1", "ref": "X1"},
        }
    ],
}


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


def test_electrical_connector_pins_round_trip():
    electrical = Electrical.from_dict(
        {
            "connectors": [
                {
                    "ref": "J1",
                    "type": "M12-A-5P",
                    "carries": "power",
                    "pins": [
                        {"pin": "1", "function": "24VDC supply", "wire_color": "brown"},
                        {"pin": "3", "function": "0V return"},
                    ],
                }
            ]
        }
    )
    connector = electrical.connectors[0]
    assert connector.pins[0].pin == "1"
    assert connector.pins[0].wire_color == "brown"
    assert connector.pins[1].wire_color is None


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


# ---------------------------------------------------------------------------
# ADR-0014 additive fields: a module's own `components:` list and a
# signal's `source` provenance into one of those components.
# ---------------------------------------------------------------------------


def test_module_with_no_components_list_stays_empty_tuple_not_none():
    module = Module.from_dict(
        {
            "ocm_version": "1.1",
            "id": "com.example.pickhead.pk100",
            "revision": "0.1.0",
            "kind": "end_effector",
            "license": "CERN-OHL-S-2.0",
            "mechanical": {
                "mount": {"interface": "custom"},
                "frames": {"origin": {"xyz_mm": [0, 0, 0]}},
                "geometry": {"collision": "x.stl"},
                "mass_kg": 1.0,
            },
            "state_machine": {"model": "packml"},
        }
    )
    assert module.components == ()


def test_module_components_list_and_signal_source_are_parsed():
    module = Module.from_dict(
        {
            "ocm_version": "1.1",
            "id": "com.example.pickhead.pk100",
            "revision": "0.1.0",
            "kind": "end_effector",
            "license": "CERN-OHL-S-2.0",
            "mechanical": {
                "mount": {"interface": "custom"},
                "frames": {"origin": {"xyz_mm": [0, 0, 0]}},
                "geometry": {"collision": "x.stl"},
                "mass_kg": 1.0,
            },
            "state_machine": {"model": "packml"},
            "components": [{"refdes": "VG1", "ref": "com.smc.ejector.zk2-agh@1.0.0"}],
            "comms": {
                "protocol": "discrete-io",
                "signals": [{"name": "part_present", "direction": "input", "type": "bool", "source": "VG1.vacuum_switch"}],
            },
        }
    )
    assert module.components == (ModuleComponent(refdes="VG1", ref=ComponentRef(id="com.smc.ejector.zk2-agh", revision="1.0.0")),)
    assert str(module.components[0].ref) == "com.smc.ejector.zk2-agh@1.0.0"
    assert module.comms.signals[0].source == "VG1.vacuum_switch"
    # No pose stated -- stays None, not a fabricated default position.
    assert module.components[0].pose is None


def test_module_component_pose_round_trips_and_defaults_rpy_when_omitted():
    base = {
        "ocm_version": "1.1",
        "id": "com.example.pickhead.pk100",
        "revision": "0.1.0",
        "kind": "end_effector",
        "license": "CERN-OHL-S-2.0",
        "mechanical": {
            "mount": {"interface": "custom"},
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}},
            "geometry": {"collision": "x.stl"},
            "mass_kg": 1.0,
        },
        "state_machine": {"model": "packml"},
        "comms": {
            "protocol": "discrete-io",
            "signals": [{"name": "part_present", "direction": "input", "type": "bool", "source": "VG1.vacuum_switch"}],
        },
    }

    # A component instance's own local placement within the module's
    # assembly scene (Modules-page authoring UI) -- relative to the
    # module's own origin, never to a named frame.
    module = Module.from_dict(
        {**base, "components": [{"refdes": "VG1", "ref": "com.smc.ejector.zk2-agh@1.0.0", "pose": {"xyz_mm": [10.0, 20.0, 30.0], "rpy_deg": [0.0, 0.0, 90.0]}}]}
    )
    pose = module.components[0].pose
    assert pose is not None
    assert pose.xyz_mm == (10.0, 20.0, 30.0)
    assert pose.rpy_deg == (0.0, 0.0, 90.0)

    # rpy_deg omitted -- defaults to no rotation, not a schema violation.
    module2 = Module.from_dict({**base, "components": [{"refdes": "VG1", "ref": "com.smc.ejector.zk2-agh@1.0.0", "pose": {"xyz_mm": [1.0, 2.0, 3.0]}}]})
    assert module2.components[0].pose.rpy_deg == (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# ADR-0015: module connectivity -- ports (the external interface), nets
# (electrical/pneumatic, N unordered endpoints), links (communication,
# exactly two endpoints). Schema and dataclasses only -- no resolver
# cross-reference checks, so an endpoint naming an unknown refdes/ref/pin
# is not asserted against here; that's deliberately out of scope.
# ---------------------------------------------------------------------------


def test_module_with_no_ports_nets_links_stays_valid_and_empty():
    base = _CONNECTIVITY_MODULE
    module = Module.from_dict({k: v for k, v in base.items() if k not in ("ports", "nets", "links")})
    assert module.ports == ()
    assert module.nets is None
    assert module.links == ()


def test_adr0015_worked_example_round_trips_through_the_object_model():
    module = Module.from_dict(_CONNECTIVITY_MODULE)

    pwr_in, air_in, net_in = module.ports
    assert pwr_in.id == "PWR_IN"
    assert pwr_in.domain == "electrical"
    assert pwr_in.type == "M12-A-4P"
    assert air_in.domain == "pneumatic"
    assert air_in.thread == "G1/8"
    assert air_in.function == "supply"
    assert net_in.domain == "communication"
    assert net_in.protocol == "ethercat"
    assert net_in.role == "slave_in"

    assert module.nets is not None
    electrical_net = module.nets.electrical[0]
    assert electrical_net.id == "N_24V"
    assert electrical_net.pressure is None  # electrical -- a stated pneumatic-only field
    port_endpoint, component_endpoint = electrical_net.endpoints
    assert port_endpoint.port == "PWR_IN"
    assert port_endpoint.pin == "1"
    assert port_endpoint.refdes is None
    # "No renaming, no alias layer": the component's own connector name
    # lands in `ref`, exactly as ComponentConnector.ref calls itself --
    # not a module-invented field like "connector".
    assert component_endpoint.refdes == "PS1"
    assert component_endpoint.ref == "electrical"
    assert component_endpoint.pin == "1"

    pneumatic_net = module.nets.pneumatic[0]
    assert pneumatic_net.id == "C_SUPPLY"
    assert pneumatic_net.pressure == 6
    assert pneumatic_net.pressure_units == "bar"
    assert len(pneumatic_net.endpoints) == 2

    link = module.links[0]
    assert link.id == "L_EC_1"
    assert link.protocol == "ethercat"
    assert link.a.port == "NET_IN"
    assert link.b.refdes == "DP1"
    assert link.b.ref == "X1"


def test_a_net_endpoint_referencing_a_component_omits_port_and_a_module_port_endpoint_omits_refdes():
    # The two endpoint KINDS are distinguished by which fields are present,
    # not by a discriminator field -- confirm from_dict doesn't fabricate
    # the other kind's fields as some default instead of None.
    module = Module.from_dict(_CONNECTIVITY_MODULE)
    port_endpoint, component_endpoint = module.nets.electrical[0].endpoints
    assert port_endpoint.refdes is None and port_endpoint.ref is None
    assert component_endpoint.port is None


def test_adr0015_worked_example_actually_validates_against_the_real_schema(tmp_path):
    # Module.from_dict (used by every test above) never runs schema
    # validation -- it's a plain dict-to-dataclass mapper. load_module does
    # both (Draft202012Validator, then the same from_dict), against this
    # repo's own real, committed schema (its default schema_path) -- this
    # is the proof the shape this file exercises is actually SCHEMA-valid,
    # not just parseable if you already hand it a matching dict.
    path = tmp_path / "module.yaml"
    yaml.safe_dump(_CONNECTIVITY_MODULE, path.open("w", encoding="utf-8"))

    module = load_module(path)

    assert module.ports[0].id == "PWR_IN"
    assert module.nets.electrical[0].id == "N_24V"
    assert module.links[0].id == "L_EC_1"
