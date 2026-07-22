# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0014 / spec/10: components/<id>/component.yaml, loaded and typed
the same way a module manifest is -- see test_module_validation_failures.py
for the module-side mirror of every one of these.
"""

from __future__ import annotations

import yaml
import pytest

from ocm_core import Component, load_component
from ocm_core.errors import ManifestValidationError


def _write(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _minimal_component() -> dict:
    return {
        "ocm_version": "1.1",
        "id": "com.example.ejector.demo1",
        "revision": "1.0.0",
        "kind": "vacuum_ejector",
        "vendor": "Example Co",
        "source": {"kind": "datasheet", "ref": "fictional demo datasheet, worked-example only"},
    }


def test_loads_a_minimal_valid_component(tmp_path, component_schema_path):
    path = _write(tmp_path, "component.yaml", _minimal_component())

    component = load_component(path, component_schema_path)

    assert isinstance(component, Component)
    assert component.id == "com.example.ejector.demo1"
    assert component.revision == "1.0.0"
    assert component.vendor == "Example Co"
    assert component.source.kind == "datasheet"
    assert component.source.ref == "fictional demo datasheet, worked-example only"


def test_loads_a_component_with_ranged_pneumatic_and_signals(tmp_path, component_schema_path):
    data = _minimal_component()
    data["pneumatic"] = {"pressure_min": 4.0, "pressure_max": 6.0, "units": "bar", "flow_nl_min": 25.0, "port": "M5"}
    data["comms"] = {
        "protocol": "discrete-io",
        "signals": [
            {"name": "vacuum_switch", "direction_device": "output", "type": "bool", "electrical": "PNP"},
        ],
    }
    data["geometry"] = {"envelope_mm": [40.0, 20.0, 15.0], "mass_kg": 0.05}
    data["hazards"] = ["pinch"]
    path = _write(tmp_path, "component.yaml", data)

    component = load_component(path, component_schema_path)

    # A stated RANGE, not a chosen operating point -- ADR-0014: choosing
    # within a stated range is design, a module-layer decision.
    assert component.pneumatic.pressure_min == 4.0
    assert component.pneumatic.pressure_max == 6.0
    assert component.pneumatic.units == "bar"
    assert component.comms.signal("vacuum_switch").direction_device == "output"
    assert component.geometry.mass_kg == 0.05
    assert component.hazards == ("pinch",)


def test_missing_required_source_is_rejected(tmp_path, component_schema_path):
    data = _minimal_component()
    del data["source"]
    path = _write(tmp_path, "bad_no_source.yaml", data)

    with pytest.raises(ManifestValidationError) as exc:
        load_component(path, component_schema_path)
    assert "source" in str(exc.value)


def test_module_layer_fields_are_rejected(tmp_path, component_schema_path):
    # spec/10: "What a component must NOT contain" -- capabilities, mount,
    # TCP/frames, PackML, and safety-PERFORMANCE fields are module-layer
    # judgment, not transcribable datasheet facts. additionalProperties:
    # false at the schema root rejects them outright.
    data = _minimal_component()
    data["capabilities"] = [{"name": "pick", "summary": "not a component's job"}]
    path = _write(tmp_path, "bad_capabilities.yaml", data)

    with pytest.raises(ManifestValidationError):
        load_component(path, component_schema_path)


def test_reports_every_violation_not_just_the_first(tmp_path, component_schema_path):
    data = _minimal_component()
    del data["source"]
    del data["vendor"]
    path = _write(tmp_path, "bad_multi.yaml", data)

    with pytest.raises(ManifestValidationError) as exc:
        load_component(path, component_schema_path)
    assert len(exc.value.errors) >= 2
