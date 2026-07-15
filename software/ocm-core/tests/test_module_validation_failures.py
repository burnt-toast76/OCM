# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest
import yaml

from ocm_core import load_module
from ocm_core.errors import ManifestValidationError


def _write(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_missing_required_top_level_field_is_rejected(schema_path, tmp_path, sd50_path):
    data = yaml.safe_load(sd50_path.read_text(encoding="utf-8"))
    del data["state_machine"]
    bad_path = _write(tmp_path, "bad.yaml", data)

    with pytest.raises(ManifestValidationError) as exc:
        load_module(bad_path, schema_path)
    assert "state_machine" in str(exc.value)


def test_unknown_kind_is_rejected(schema_path, tmp_path, sd50_path):
    data = yaml.safe_load(sd50_path.read_text(encoding="utf-8"))
    data["kind"] = "not_a_real_kind"
    bad_path = _write(tmp_path, "bad_kind.yaml", data)

    with pytest.raises(ManifestValidationError):
        load_module(bad_path, schema_path)


def test_unknown_top_level_property_is_rejected(schema_path, tmp_path, sd50_path):
    # additionalProperties: false at the schema root.
    data = yaml.safe_load(sd50_path.read_text(encoding="utf-8"))
    data["totally_made_up_field"] = True
    bad_path = _write(tmp_path, "bad_extra.yaml", data)

    with pytest.raises(ManifestValidationError):
        load_module(bad_path, schema_path)


def test_process_kind_without_process_block_is_rejected(schema_path, tmp_path, dh200_path):
    # allOf: kind=process REQUIRES capabilities, comms, process, safety.
    data = yaml.safe_load(dh200_path.read_text(encoding="utf-8"))
    del data["process"]
    bad_path = _write(tmp_path, "bad_process.yaml", data)

    with pytest.raises(ManifestValidationError) as exc:
        load_module(bad_path, schema_path)
    assert "process" in str(exc.value)


def test_reports_every_violation_not_just_the_first(schema_path, tmp_path, sd50_path):
    data = yaml.safe_load(sd50_path.read_text(encoding="utf-8"))
    del data["state_machine"]
    del data["license"]
    bad_path = _write(tmp_path, "bad_multi.yaml", data)

    with pytest.raises(ManifestValidationError) as exc:
        load_module(bad_path, schema_path)
    assert len(exc.value.errors) >= 2
