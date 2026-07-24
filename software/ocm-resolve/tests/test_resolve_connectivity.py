# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0015: a module's nets/links/ports connectivity, cross-checked against
the transcribed connectors/pins of the components it places -- the same kind
of resolve-time cross-file check ocm-resolve already does for a module's
`components:` list (ADR-0014), one concern over.

One module per refusal, each a schema-valid baseline sabotaged in exactly one
place -- the style of the demo sabotage cells. Only the ADR's "implementable
against the current schema" table is exercised here; the deferred refusals
(driver contention, signal class, required pin, pneumatic function/size,
pressure) wait on component fields that aren't transcribed yet.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from ocm_core.cell import Cell
from ocm_resolve import CellResolutionError, resolve_cell

from .conftest import build_cell_dict, minimal_base_manifest, write_module


# --------------------------------------------------------------------------
# component fixtures (fictional demo parts, worked-example only)
# --------------------------------------------------------------------------


def psu_component() -> dict[str, Any]:
    """An electrical connector with a two-pin pinout."""
    return {
        "ocm_version": "1.1",
        "id": "com.example.psu.demo1",
        "revision": "1.0.0",
        "kind": "other",
        "vendor": "Example Co",
        "source": {"kind": "datasheet", "ref": "fictional demo datasheet, worked-example only"},
        "electrical": {
            "connectors": [
                {
                    "ref": "electrical",
                    "type": "M12-A-4P",
                    "pins": [{"pin": "1", "function": "+24V"}, {"pin": "2", "function": "0V"}],
                }
            ]
        },
    }


def slave_component(id_: str = "com.example.slave.demo1", protocol: str = "ethercat") -> dict[str, Any]:
    """An EtherCAT IN/OUT pair -- a daisy-chainable slave."""
    return {
        "ocm_version": "1.1",
        "id": id_,
        "revision": "1.0.0",
        "kind": "drive",
        "vendor": "Example Co",
        "source": {"kind": "datasheet", "ref": "fictional demo datasheet, worked-example only"},
        "comms": {
            "protocol": protocol,
            "connectors": [
                {"ref": "X1", "type": "M12-D-4P", "role": "slave_in"},
                {"ref": "X2", "type": "M12-D-4P", "role": "slave_out"},
            ],
        },
    }


def bare_component() -> dict[str, Any]:
    """A discrete-io device: comms signals, but no connectors enumerated --
    exactly the "pinout is missing" component ADR-0015 Decision 4 refuses."""
    return {
        "ocm_version": "1.1",
        "id": "com.example.bare.demo1",
        "revision": "1.0.0",
        "kind": "sensor",
        "vendor": "Example Co",
        "source": {"kind": "datasheet", "ref": "fictional demo datasheet, worked-example only"},
        "comms": {"protocol": "discrete-io", "signals": [{"name": "present", "direction_device": "output", "type": "bool"}]},
    }


def dispenser_component() -> dict[str, Any]:
    """Shaped like the real com.nordson-kline.dispenser.dp8: EtherCAT
    protocol with signals but NO comms connectors, a 24 VDC supply rail (not a
    connector), and exactly ONE pneumatic supply port with no `port` label --
    nothing to transcribe. ADR-0015 Erratum 1: this component DOES declare
    connectivity (its pneumatic port), so it must not be refused "pinout
    missing", and a bare pneumatic endpoint resolves to its sole port."""
    return {
        "ocm_version": "1.1",
        "id": "com.example.dispenser.demo1",
        "revision": "1.0.0",
        "kind": "dispenser",
        "vendor": "Example Co",
        "source": {"kind": "datasheet", "ref": "fictional demo datasheet, worked-example only"},
        "comms": {"protocol": "ethercat", "signals": [{"name": "volume", "direction_device": "output", "type": "real"}]},
        "electrical": {"supplies": [{"rail": "24VDC"}]},
        "pneumatic": {"pressure_min": 4, "pressure_max": 6, "pressure_units": "bar", "ports": [{"thread": "G1/8", "function": "supply"}]},
    }


def valve_component() -> dict[str, Any]:
    """A manifold declaring MORE than one pneumatic port, each labelled --
    so a bare {refdes} is ambiguous and `ref` must name a declared port."""
    return {
        "ocm_version": "1.1",
        "id": "com.example.valve.demo1",
        "revision": "1.0.0",
        "kind": "valve_island",
        "vendor": "Example Co",
        "source": {"kind": "datasheet", "ref": "fictional demo datasheet, worked-example only"},
        "pneumatic": {
            "ports": [
                {"port": "P", "thread": "G1/8", "function": "supply"},
                {"port": "A", "thread": "G1/8", "function": "work"},
            ]
        },
    }


# --------------------------------------------------------------------------
# module + cell plumbing
# --------------------------------------------------------------------------

MODULE_ID = "com.example.conn.demo1"


def conn_module(
    *,
    components: list[dict[str, Any]] | None = None,
    ports: list[dict[str, Any]] | None = None,
    nets: dict[str, Any] | None = None,
    links: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "ocm_version": "1.1",
        "id": MODULE_ID,
        "revision": "1.0.0",
        "kind": "fixture",
        "license": "CERN-OHL-S-2.0",
        "name": "Connectivity Demo Fixture",
        "mechanical": {
            "mount": {"interface": "ocm-base-grid-50", "footprint_mm": [200, 200]},
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}},
            "geometry": {"collision": "meshes/fixture_convex.stl"},
            "mass_kg": 2.0,
        },
        "state_machine": {"model": "packml", "abort_safe": True},
    }
    if components is not None:
        manifest["components"] = components
    if ports is not None:
        manifest["ports"] = ports
    if nets is not None:
        manifest["nets"] = nets
    if links is not None:
        manifest["links"] = links
    return manifest


def write_component(root: Path, manifest: dict[str, Any]) -> Path:
    component_dir = root / manifest["id"]
    component_dir.mkdir(parents=True, exist_ok=True)
    path = component_dir / "component.yaml"
    path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return path


def _cell() -> Cell:
    return Cell.from_dict(
        build_cell_dict(
            modules=[
                {
                    "instance": "fix1",
                    "module": f"{MODULE_ID}@1.0.0",
                    "mount": {"station": [100, 100], "pose": {"xyz_mm": [100, 100, 0]}},
                }
            ],
            plan=[],
        )
    )


def resolve_errors(
    tmp_path: Path, module_manifest: dict[str, Any], components: list[dict[str, Any]] = ()
) -> list[str]:
    """Resolve a cell placing `module_manifest` as fix1; return the list of
    violations (empty if it resolves cleanly)."""
    modules_root = tmp_path / "modules"
    write_module(modules_root, minimal_base_manifest())
    write_module(modules_root, module_manifest)
    components_root = tmp_path / "components"
    for c in components:
        write_component(components_root, c)
    try:
        resolve_cell(_cell(), modules_root, components_root)
        return []
    except CellResolutionError as e:
        return e.errors


# The one fully-wired, valid module every refusal test sabotages a copy of.
def valid_module() -> dict[str, Any]:
    return conn_module(
        components=[
            {"refdes": "PS1", "ref": "com.example.psu.demo1@1.0.0"},
            {"refdes": "DP1", "ref": "com.example.slave.demo1@1.0.0"},
            {"refdes": "DP2", "ref": "com.example.slave.demo1@1.0.0"},
        ],
        ports=[
            {"id": "PWR_IN", "domain": "electrical", "type": "M12-A-4P"},
            {"id": "NET_IN", "domain": "communication", "protocol": "ethercat", "role": "slave_in"},
            {"id": "NET_OUT", "domain": "communication", "protocol": "ethercat", "role": "slave_out"},
        ],
        nets={
            "electrical": [
                {
                    "id": "N_24V",
                    "endpoints": [
                        {"port": "PWR_IN", "pin": "1"},
                        {"refdes": "PS1", "ref": "electrical", "pin": "1"},
                    ],
                }
            ]
        },
        links=[
            {"id": "L1", "protocol": "ethercat", "a": {"port": "NET_IN"}, "b": {"refdes": "DP1", "ref": "X1"}},
            {"id": "L2", "protocol": "ethercat", "a": {"refdes": "DP1", "ref": "X2"}, "b": {"refdes": "DP2", "ref": "X1"}},
            {"id": "L3", "protocol": "ethercat", "a": {"refdes": "DP2", "ref": "X2"}, "b": {"port": "NET_OUT"}},
        ],
    )


ALL_COMPONENTS = [psu_component(), slave_component(), bare_component()]


# --------------------------------------------------------------------------
# the happy path
# --------------------------------------------------------------------------


def test_fully_wired_module_resolves_clean(tmp_path: Path):
    assert resolve_errors(tmp_path, valid_module(), ALL_COMPONENTS) == []


def test_module_with_no_connectivity_at_all_is_untouched(tmp_path: Path):
    # ADR-0015: a module declaring neither nets nor links nor ports stays
    # valid, the same way a module with no components: list does.
    assert resolve_errors(tmp_path, conn_module(), []) == []


# --------------------------------------------------------------------------
# one refusal at a time
# --------------------------------------------------------------------------


def test_net_with_fewer_than_two_endpoints(tmp_path: Path):
    module = conn_module(
        components=[{"refdes": "PS1", "ref": "com.example.psu.demo1@1.0.0"}],
        nets={"electrical": [{"id": "N_LONELY", "endpoints": [{"refdes": "PS1", "ref": "electrical", "pin": "1"}]}]},
    )
    errors = resolve_errors(tmp_path, module, [psu_component()])
    assert any("electrical net 'N_LONELY' has 1 endpoint(s)" in e and "at least 2" in e for e in errors), errors


def test_pin_appearing_on_more_than_one_net(tmp_path: Path):
    module = conn_module(
        components=[{"refdes": "PS1", "ref": "com.example.psu.demo1@1.0.0"}],
        ports=[{"id": "PWR_IN", "domain": "electrical", "type": "M12-A-4P"}],
        nets={
            "electrical": [
                {
                    "id": "N_24V",
                    "endpoints": [{"port": "PWR_IN", "pin": "1"}, {"refdes": "PS1", "ref": "electrical", "pin": "1"}],
                },
                {
                    "id": "N_ALT",
                    "endpoints": [{"refdes": "PS1", "ref": "electrical", "pin": "1"}, {"port": "PWR_IN", "pin": "2"}],
                },
            ]
        },
    )
    errors = resolve_errors(tmp_path, module, [psu_component()])
    assert any(
        "pin '1' of connector 'electrical' on refdes 'PS1'" in e and "more than one net" in e and "N_24V" in e and "N_ALT" in e
        for e in errors
    ), errors


def test_endpoint_naming_unknown_refdes(tmp_path: Path):
    module = conn_module(
        components=[{"refdes": "PS1", "ref": "com.example.psu.demo1@1.0.0"}],
        ports=[{"id": "PWR_IN", "domain": "electrical", "type": "M12-A-4P"}],
        nets={
            "electrical": [
                {"id": "N_24V", "endpoints": [{"port": "PWR_IN", "pin": "1"}, {"refdes": "PS9", "ref": "electrical", "pin": "1"}]}
            ]
        },
    )
    errors = resolve_errors(tmp_path, module, [psu_component()])
    assert any("references unknown refdes 'PS9'" in e for e in errors), errors


def test_endpoint_naming_unknown_ref_on_a_known_component(tmp_path: Path):
    module = conn_module(
        components=[{"refdes": "PS1", "ref": "com.example.psu.demo1@1.0.0"}],
        ports=[{"id": "PWR_IN", "domain": "electrical", "type": "M12-A-4P"}],
        nets={
            "electrical": [
                {"id": "N_24V", "endpoints": [{"port": "PWR_IN", "pin": "1"}, {"refdes": "PS1", "ref": "nope", "pin": "1"}]}
            ]
        },
    )
    errors = resolve_errors(tmp_path, module, [psu_component()])
    assert any("references unknown connector 'nope' on refdes 'PS1'" in e for e in errors), errors


def test_endpoint_naming_a_pin_the_connector_does_not_declare(tmp_path: Path):
    module = conn_module(
        components=[{"refdes": "PS1", "ref": "com.example.psu.demo1@1.0.0"}],
        ports=[{"id": "PWR_IN", "domain": "electrical", "type": "M12-A-4P"}],
        nets={
            "electrical": [
                {"id": "N_24V", "endpoints": [{"port": "PWR_IN", "pin": "1"}, {"refdes": "PS1", "ref": "electrical", "pin": "9"}]}
            ]
        },
    )
    errors = resolve_errors(tmp_path, module, [psu_component()])
    assert any("references pin '9' not on connector 'electrical' of refdes 'PS1'" in e for e in errors), errors


def test_instance_whose_component_declares_no_connectors(tmp_path: Path):
    module = conn_module(
        components=[
            {"refdes": "PS1", "ref": "com.example.psu.demo1@1.0.0"},
            {"refdes": "BR1", "ref": "com.example.bare.demo1@1.0.0"},
        ],
        ports=[{"id": "PWR_IN", "domain": "electrical", "type": "M12-A-4P"}],
        nets={
            "electrical": [
                {"id": "N_24V", "endpoints": [{"port": "PWR_IN", "pin": "1"}, {"refdes": "BR1", "ref": "X"}]}
            ]
        },
    )
    errors = resolve_errors(tmp_path, module, [psu_component(), bare_component()])
    assert any("references refdes 'BR1'" in e and "declares no connectors" in e for e in errors), errors


def test_module_port_declared_but_connected_to_nothing(tmp_path: Path):
    module = conn_module(
        components=[{"refdes": "PS1", "ref": "com.example.psu.demo1@1.0.0"}],
        ports=[
            {"id": "PWR_IN", "domain": "electrical", "type": "M12-A-4P"},
            {"id": "SPARE", "domain": "electrical", "type": "M12-A-4P"},
        ],
        nets={
            "electrical": [
                {"id": "N_24V", "endpoints": [{"port": "PWR_IN", "pin": "1"}, {"refdes": "PS1", "ref": "electrical", "pin": "1"}]}
            ]
        },
    )
    errors = resolve_errors(tmp_path, module, [psu_component()])
    assert any("port 'SPARE' is declared but connected to no net or link" in e for e in errors), errors


def test_link_referencing_a_non_communication_port(tmp_path: Path):
    module = conn_module(
        ports=[
            {"id": "P_COMM", "domain": "communication", "protocol": "ethercat", "role": "port"},
            {"id": "P_ELEC", "domain": "electrical", "type": "M12-A-4P"},
        ],
        links=[{"id": "L_BAD", "a": {"port": "P_COMM"}, "b": {"port": "P_ELEC"}}],
    )
    errors = resolve_errors(tmp_path, module, [])
    assert any(
        "link 'L_BAD' endpoint b references port 'P_ELEC'" in e and "not a communication port" in e for e in errors
    ), errors


def test_link_whose_endpoint_does_not_resolve(tmp_path: Path):
    module = conn_module(
        ports=[{"id": "NET_IN", "domain": "communication", "protocol": "ethercat", "role": "slave_in"}],
        components=[{"refdes": "DP1", "ref": "com.example.slave.demo1@1.0.0"}],
        links=[{"id": "L1", "protocol": "ethercat", "a": {"port": "NET_IN"}, "b": {"refdes": "DP1", "ref": "X9"}}],
    )
    errors = resolve_errors(tmp_path, module, [slave_component()])
    assert any("link 'L1' endpoint b" in e and "unknown connector 'X9' on refdes 'DP1'" in e for e in errors), errors


def test_protocol_mismatch_across_a_link(tmp_path: Path):
    module = conn_module(
        ports=[
            {"id": "P_A", "domain": "communication", "protocol": "ethercat", "role": "port"},
            {"id": "P_B", "domain": "communication", "protocol": "profinet", "role": "port"},
        ],
        links=[{"id": "L_X", "a": {"port": "P_A"}, "b": {"port": "P_B"}}],
    )
    errors = resolve_errors(tmp_path, module, [])
    assert any("link 'L_X' connects mismatched protocols" in e and "ethercat" in e and "profinet" in e for e in errors), errors


# --- EtherCAT chain, derived by walking the links (never a stored index) ---


def test_ethercat_chain_reaches_no_master(tmp_path: Path):
    # Two slaves cabled OUT -> IN, with no master terminal and no slave_in
    # port to anchor the chain upstream.
    module = conn_module(
        components=[
            {"refdes": "DP1", "ref": "com.example.slave.demo1@1.0.0"},
            {"refdes": "DP2", "ref": "com.example.slave.demo1@1.0.0"},
        ],
        links=[{"id": "L1", "protocol": "ethercat", "a": {"refdes": "DP1", "ref": "X2"}, "b": {"refdes": "DP2", "ref": "X1"}}],
    )
    errors = resolve_errors(tmp_path, module, [slave_component()])
    assert any("EtherCAT chain reaches no master" in e for e in errors), errors


def test_ethercat_chain_with_a_loop(tmp_path: Path):
    module = conn_module(
        components=[{"refdes": "DP1", "ref": "com.example.slave.demo1@1.0.0"}],
        ports=[{"id": "NET_IN", "domain": "communication", "protocol": "ethercat", "role": "slave_in"}],
        links=[
            {"id": "L1", "protocol": "ethercat", "a": {"port": "NET_IN"}, "b": {"refdes": "DP1", "ref": "X1"}},
            {"id": "L2", "protocol": "ethercat", "a": {"refdes": "DP1", "ref": "X2"}, "b": {"port": "NET_IN"}},
        ],
    )
    errors = resolve_errors(tmp_path, module, [slave_component()])
    assert any("EtherCAT chain loops back on itself" in e for e in errors), errors


def test_ethercat_slave_out_dangling_leaves_devices_unreached(tmp_path: Path):
    # DP1 is reached from NET_IN, but its slave_out is never cabled onward;
    # DP2 hangs off NET_OUT with its slave_in dangling -> beyond the break.
    module = conn_module(
        components=[
            {"refdes": "DP1", "ref": "com.example.slave.demo1@1.0.0"},
            {"refdes": "DP2", "ref": "com.example.slave.demo1@1.0.0"},
        ],
        ports=[
            {"id": "NET_IN", "domain": "communication", "protocol": "ethercat", "role": "slave_in"},
            {"id": "NET_OUT", "domain": "communication", "protocol": "ethercat", "role": "slave_out"},
        ],
        links=[
            {"id": "L1", "protocol": "ethercat", "a": {"port": "NET_IN"}, "b": {"refdes": "DP1", "ref": "X1"}},
            {"id": "L2", "protocol": "ethercat", "a": {"refdes": "DP2", "ref": "X2"}, "b": {"port": "NET_OUT"}},
        ],
    )
    errors = resolve_errors(tmp_path, module, [slave_component()])
    assert any("EtherCAT chain leaves slave(s) ['DP2'] unreached" in e for e in errors), errors


# --------------------------------------------------------------------------
# reuse -- the resolved-component map is shared with _check_module_components
# --------------------------------------------------------------------------


def test_connectivity_needs_the_components_search_path(tmp_path: Path):
    # No components search path: the component can't resolve, so its own
    # ADR-0014 refusal fires -- and connectivity does NOT pile a second
    # "unknown connector" refusal on the same unresolved refdes.
    module = conn_module(
        components=[{"refdes": "PS1", "ref": "com.example.psu.demo1@1.0.0"}],
        ports=[{"id": "PWR_IN", "domain": "electrical", "type": "M12-A-4P"}],
        nets={
            "electrical": [
                {"id": "N_24V", "endpoints": [{"port": "PWR_IN", "pin": "1"}, {"refdes": "PS1", "ref": "electrical", "pin": "1"}]}
            ]
        },
    )
    modules_root = tmp_path / "modules"
    write_module(modules_root, minimal_base_manifest())
    write_module(modules_root, module)
    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(_cell(), modules_root)  # no components_search_path
    errors = exc.value.errors
    assert any("no components search path was given" in e for e in errors), errors
    assert not any("unknown connector" in e for e in errors), errors


# --------------------------------------------------------------------------
# ADR-0015 Erratum 1 -- pneumatic endpoints resolve against pneumatic.ports
# --------------------------------------------------------------------------


def test_pneumatic_net_to_a_sole_port_component_resolves(tmp_path: Path):
    # Correction B: a component declaring exactly one pneumatic port is
    # referenceable by a bare {refdes} -- the port is unlabelled, so there is
    # no `ref` to cite, and demanding one would be unsatisfiable.
    module = conn_module(
        components=[{"refdes": "DISP1", "ref": "com.example.dispenser.demo1@1.0.0"}],
        ports=[{"id": "AIR_IN", "domain": "pneumatic", "thread": "G1/8", "function": "supply"}],
        nets={"pneumatic": [{"id": "C_AIR", "pressure": 5, "pressure_units": "bar", "endpoints": [{"port": "AIR_IN"}, {"refdes": "DISP1"}]}]},
    )
    assert resolve_errors(tmp_path, module, [dispenser_component()]) == []


def test_dispenser_with_only_a_pneumatic_port_is_not_pinout_missing(tmp_path: Path):
    # Correction C: a dp8-shaped part (24 VDC rail + one G1/8 supply port, no
    # connectors) used to report declares_any=False and be refused
    # "its pinout is missing". It now declares connectivity and resolves.
    module = conn_module(
        components=[{"refdes": "DP1", "ref": "com.example.dispenser.demo1@1.0.0"}],
        ports=[{"id": "AIR_IN", "domain": "pneumatic", "thread": "G1/8", "function": "supply"}],
        nets={"pneumatic": [{"id": "C_AIR", "endpoints": [{"port": "AIR_IN"}, {"refdes": "DP1"}]}]},
    )
    errors = resolve_errors(tmp_path, module, [dispenser_component()])
    assert errors == [], errors
    assert not any("pinout" in e for e in errors), errors


def test_pneumatic_two_port_component_without_ref_is_refused(tmp_path: Path):
    # Correction B: more than one port -> a bare {refdes} is ambiguous, `ref`
    # is required and must name a declared port.
    module = conn_module(
        components=[{"refdes": "V1", "ref": "com.example.valve.demo1@1.0.0"}],
        ports=[{"id": "AIR_IN", "domain": "pneumatic", "thread": "G1/8", "function": "supply"}],
        nets={"pneumatic": [{"id": "C_AIR", "endpoints": [{"port": "AIR_IN"}, {"refdes": "V1"}]}]},
    )
    errors = resolve_errors(tmp_path, module, [valve_component()])
    assert any(
        "references refdes 'V1'" in e and "without naming a pneumatic port `ref`" in e and "'P'" in e and "'A'" in e
        for e in errors
    ), errors


def test_pneumatic_ref_naming_a_declared_port_resolves(tmp_path: Path):
    # Correction A: `ref` names a pneumatic.ports[].port, exactly as declared.
    module = conn_module(
        components=[{"refdes": "V1", "ref": "com.example.valve.demo1@1.0.0"}],
        ports=[{"id": "AIR_IN", "domain": "pneumatic", "thread": "G1/8", "function": "supply"}],
        nets={"pneumatic": [{"id": "C_AIR", "endpoints": [{"port": "AIR_IN"}, {"refdes": "V1", "ref": "P"}]}]},
    )
    assert resolve_errors(tmp_path, module, [valve_component()]) == []


def test_pneumatic_ref_naming_an_undeclared_port_is_refused(tmp_path: Path):
    module = conn_module(
        components=[{"refdes": "V1", "ref": "com.example.valve.demo1@1.0.0"}],
        ports=[{"id": "AIR_IN", "domain": "pneumatic", "thread": "G1/8", "function": "supply"}],
        nets={"pneumatic": [{"id": "C_AIR", "endpoints": [{"port": "AIR_IN"}, {"refdes": "V1", "ref": "Z"}]}]},
    )
    errors = resolve_errors(tmp_path, module, [valve_component()])
    assert any("references unknown pneumatic port 'Z' on refdes 'V1'" in e for e in errors), errors
