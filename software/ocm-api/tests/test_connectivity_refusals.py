# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0015 connectivity refusals surface through the envelope with one
stable code apiece.

The messages are produced by ocm_resolve itself (built on disk and resolved
for real), then run through `resolve_error_to_refusal` -- so the translate
patterns are pinned against the resolver's actual output, never a copy of it
that could drift.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from ocm_api.envelope import Codes
from ocm_api.translate import resolve_error_to_refusal
from ocm_core.cell import Cell
from ocm_resolve import CellResolutionError, resolve_cell

MODULE_ID = "com.example.conn.demo1"


def _write(root: Path, name: str, manifest: dict[str, Any]) -> None:
    d = root / manifest["id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(yaml.safe_dump(manifest), encoding="utf-8")


def _base() -> dict[str, Any]:
    return {
        "ocm_version": "1.0",
        "id": "com.example.base.tiny",
        "revision": "1.0.0",
        "kind": "base",
        "license": "CERN-OHL-S-2.0",
        "mechanical": {
            "mount": {"interface": "custom"},
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}},
            "geometry": {"collision": "meshes/base.stl"},
            "mass_kg": 80.0,
        },
        "state_machine": {"model": "packml", "abort_safe": True},
    }


def _psu() -> dict[str, Any]:
    return {
        "ocm_version": "1.1",
        "id": "com.example.psu.demo1",
        "revision": "1.0.0",
        "kind": "other",
        "vendor": "Example Co",
        "source": {"kind": "datasheet", "ref": "demo"},
        "electrical": {"connectors": [{"ref": "electrical", "pins": [{"pin": "1", "function": "+24V"}]}]},
    }


def _slave() -> dict[str, Any]:
    return {
        "ocm_version": "1.1",
        "id": "com.example.slave.demo1",
        "revision": "1.0.0",
        "kind": "drive",
        "vendor": "Example Co",
        "source": {"kind": "datasheet", "ref": "demo"},
        "comms": {
            "protocol": "ethercat",
            "connectors": [{"ref": "X1", "role": "slave_in"}, {"ref": "X2", "role": "slave_out"}],
        },
    }


def _bare() -> dict[str, Any]:
    return {
        "ocm_version": "1.1",
        "id": "com.example.bare.demo1",
        "revision": "1.0.0",
        "kind": "sensor",
        "vendor": "Example Co",
        "source": {"kind": "datasheet", "ref": "demo"},
        "comms": {"protocol": "discrete-io", "signals": [{"name": "present", "direction_device": "output", "type": "bool"}]},
    }


def _valve() -> dict[str, Any]:
    return {
        "ocm_version": "1.1",
        "id": "com.example.valve.demo1",
        "revision": "1.0.0",
        "kind": "valve_island",
        "vendor": "Example Co",
        "source": {"kind": "datasheet", "ref": "demo"},
        "pneumatic": {"ports": [{"port": "P", "thread": "G1/8", "function": "supply"}, {"port": "A", "thread": "G1/8", "function": "work"}]},
    }


def _module(**blocks: Any) -> dict[str, Any]:
    m: dict[str, Any] = {
        "ocm_version": "1.1",
        "id": MODULE_ID,
        "revision": "1.0.0",
        "kind": "fixture",
        "license": "CERN-OHL-S-2.0",
        "mechanical": {
            "mount": {"interface": "ocm-base-grid-50", "footprint_mm": [200, 200]},
            "frames": {"origin": {"xyz_mm": [0, 0, 0]}},
            "geometry": {"collision": "meshes/f.stl"},
            "mass_kg": 2.0,
        },
        "state_machine": {"model": "packml", "abort_safe": True},
    }
    m.update(blocks)
    return m


def _codes_for(tmp_path: Path, module: dict[str, Any], components: list[dict[str, Any]]) -> set[str]:
    modules_root = tmp_path / "modules"
    _write(modules_root, "module.yaml", _base())
    _write(modules_root, "module.yaml", module)
    components_root = tmp_path / "components"
    for c in components:
        _write(components_root, "component.yaml", c)
    cell = Cell.from_dict(
        {
            "ocm_version": "1.0",
            "kind": "cell",
            "id": "com.example.cell.conn",
            "license": "CERN-OHL-S-2.0",
            "base": {"module": "com.example.base.tiny@1.0.0", "datum": "cell_origin", "grid": "ocm-base-grid-50"},
            "modules": [{"instance": "fix1", "module": f"{MODULE_ID}@1.0.0", "mount": {"station": [100, 100], "pose": {"xyz_mm": [100, 100, 0]}}}],
            "plan": [],
        }
    )
    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, modules_root, components_root)
    return {resolve_error_to_refusal(e).code for e in exc.value.errors}


def test_net_too_few_endpoints_code(tmp_path: Path):
    module = _module(
        components=[{"refdes": "PS1", "ref": "com.example.psu.demo1@1.0.0"}],
        nets={"electrical": [{"id": "N", "endpoints": [{"refdes": "PS1", "ref": "electrical", "pin": "1"}]}]},
    )
    assert Codes.NET_TOO_FEW_ENDPOINTS in _codes_for(tmp_path, module, [_psu()])


def test_pin_on_multiple_nets_code(tmp_path: Path):
    module = _module(
        components=[{"refdes": "PS1", "ref": "com.example.psu.demo1@1.0.0"}],
        ports=[{"id": "PWR", "domain": "electrical"}, {"id": "PWR2", "domain": "electrical"}],
        nets={
            "electrical": [
                {"id": "N1", "endpoints": [{"port": "PWR", "pin": "1"}, {"refdes": "PS1", "ref": "electrical", "pin": "1"}]},
                {"id": "N2", "endpoints": [{"port": "PWR2", "pin": "1"}, {"refdes": "PS1", "ref": "electrical", "pin": "1"}]},
            ]
        },
    )
    assert Codes.PIN_ON_MULTIPLE_NETS in _codes_for(tmp_path, module, [_psu()])


def test_unresolved_endpoint_code(tmp_path: Path):
    module = _module(
        components=[{"refdes": "PS1", "ref": "com.example.psu.demo1@1.0.0"}],
        ports=[{"id": "PWR", "domain": "electrical"}],
        nets={"electrical": [{"id": "N", "endpoints": [{"port": "PWR", "pin": "1"}, {"refdes": "PS1", "ref": "nope"}]}]},
    )
    assert Codes.UNRESOLVED_ENDPOINT in _codes_for(tmp_path, module, [_psu()])


def test_component_has_no_connectors_code(tmp_path: Path):
    module = _module(
        components=[
            {"refdes": "PS1", "ref": "com.example.psu.demo1@1.0.0"},
            {"refdes": "BR1", "ref": "com.example.bare.demo1@1.0.0"},
        ],
        ports=[{"id": "PWR", "domain": "electrical"}],
        nets={"electrical": [{"id": "N", "endpoints": [{"port": "PWR", "pin": "1"}, {"refdes": "BR1", "ref": "X"}]}]},
    )
    assert Codes.COMPONENT_HAS_NO_CONNECTORS in _codes_for(tmp_path, module, [_psu(), _bare()])


def test_port_unconnected_code(tmp_path: Path):
    module = _module(
        components=[{"refdes": "PS1", "ref": "com.example.psu.demo1@1.0.0"}],
        ports=[{"id": "PWR", "domain": "electrical"}, {"id": "SPARE", "domain": "electrical"}],
        nets={"electrical": [{"id": "N", "endpoints": [{"port": "PWR", "pin": "1"}, {"refdes": "PS1", "ref": "electrical", "pin": "1"}]}]},
    )
    assert Codes.PORT_UNCONNECTED in _codes_for(tmp_path, module, [_psu()])


def test_link_non_communication_port_code(tmp_path: Path):
    module = _module(
        ports=[{"id": "C", "domain": "communication", "protocol": "ethercat", "role": "port"}, {"id": "E", "domain": "electrical"}],
        links=[{"id": "L", "a": {"port": "C"}, "b": {"port": "E"}}],
    )
    assert Codes.LINK_NON_COMMUNICATION_PORT in _codes_for(tmp_path, module, [])


def test_link_protocol_mismatch_code(tmp_path: Path):
    module = _module(
        ports=[
            {"id": "A", "domain": "communication", "protocol": "ethercat", "role": "port"},
            {"id": "B", "domain": "communication", "protocol": "profinet", "role": "port"},
        ],
        links=[{"id": "L", "a": {"port": "A"}, "b": {"port": "B"}}],
    )
    assert Codes.LINK_PROTOCOL_MISMATCH in _codes_for(tmp_path, module, [])


def test_ethercat_chain_broken_code(tmp_path: Path):
    module = _module(
        components=[{"refdes": "DP1", "ref": "com.example.slave.demo1@1.0.0"}, {"refdes": "DP2", "ref": "com.example.slave.demo1@1.0.0"}],
        links=[{"id": "L", "protocol": "ethercat", "a": {"refdes": "DP1", "ref": "X2"}, "b": {"refdes": "DP2", "ref": "X1"}}],
    )
    assert Codes.ETHERCAT_CHAIN_BROKEN in _codes_for(tmp_path, module, [_slave()])


# ADR-0015 Erratum 1: pneumatic endpoint refusals keep their stable codes.
def test_pneumatic_two_ports_without_ref_code(tmp_path: Path):
    module = _module(
        components=[{"refdes": "V1", "ref": "com.example.valve.demo1@1.0.0"}],
        ports=[{"id": "AIR", "domain": "pneumatic", "thread": "G1/8", "function": "supply"}],
        nets={"pneumatic": [{"id": "C", "endpoints": [{"port": "AIR"}, {"refdes": "V1"}]}]},
    )
    assert Codes.UNRESOLVED_ENDPOINT in _codes_for(tmp_path, module, [_valve()])


def test_pneumatic_unknown_port_code(tmp_path: Path):
    module = _module(
        components=[{"refdes": "V1", "ref": "com.example.valve.demo1@1.0.0"}],
        ports=[{"id": "AIR", "domain": "pneumatic", "thread": "G1/8", "function": "supply"}],
        nets={"pneumatic": [{"id": "C", "endpoints": [{"port": "AIR"}, {"refdes": "V1", "ref": "Z"}]}]},
    )
    assert Codes.UNRESOLVED_ENDPOINT in _codes_for(tmp_path, module, [_valve()])
