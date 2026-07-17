# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from ocm_core.cell import Cell
from ocm_resolve import CellResolutionError, resolve_cell

from .conftest import build_cell_dict, minimal_tool_manifest, write_module


def test_param_above_max_is_reported_clearly(search_root):
    data = build_cell_dict(
        plan=[
            {
                "step": "fasten",
                "module": "tool1",
                "op": "drive_screw",
                "params": {"torque_nm": 6.0},  # tool1's drive_screw caps at 5.0
            }
        ]
    )
    cell = Cell.from_dict(data)

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, search_root)

    assert any(
        "torque_nm" in e and "6.0" in e and "exceeds" in e and "5.0" in e
        for e in exc.value.errors
    )


def test_param_below_min_is_reported_clearly(search_root):
    data = build_cell_dict(
        plan=[
            {
                "step": "fasten",
                "module": "tool1",
                "op": "drive_screw",
                "params": {"torque_nm": 0.05},  # min is 0.2
            }
        ]
    )
    cell = Cell.from_dict(data)

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, search_root)

    assert any("torque_nm" in e and "below" in e and "0.2" in e for e in exc.value.errors)


def test_enum_param_not_in_declared_values_is_reported_clearly(search_root):
    data = build_cell_dict(
        plan=[
            {
                "step": "fasten",
                "module": "tool1",
                "op": "drive_screw",
                "params": {"torque_nm": 2.4, "strategy": "levitation_control"},
            }
        ]
    )
    cell = Cell.from_dict(data)

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, search_root)

    assert any(
        "strategy" in e and "levitation_control" in e and "not one of" in e
        for e in exc.value.errors
    )


def test_undeclared_param_name_is_reported_clearly(search_root):
    data = build_cell_dict(
        plan=[
            {
                "step": "fasten",
                "module": "tool1",
                "op": "drive_screw",
                "params": {"torque_nm": 2.4, "made_up_param": 1},
            }
        ]
    )
    cell = Cell.from_dict(data)

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, search_root)

    assert any(
        "made_up_param" in e and "no parameter" in e for e in exc.value.errors
    )


def test_param_within_bounds_does_not_error(search_root, tiny_cell):
    # tiny_cell's default plan already drives at 2.4 N.m, well within [0.2, 5.0].
    resolve_cell(tiny_cell, search_root)  # should not raise


# ---------------------------------------------------------------------------
# v1.1 composite types (pose6d/vec3/struct -- spec/CHANGELOG.md): opaque to
# bounds checking. min/max are a scalar concept; a pose or a struct blob has
# no ordering to check a number against.
# ---------------------------------------------------------------------------


def test_pose6d_param_is_not_bounds_checked(search_root):
    # Overwrite tool1's manifest (same id, same search_root) with a
    # capability whose parameter is composite-typed and not numeric --
    # if _check_param's old "not isinstance(value, (int, float))" branch
    # ran on this, it would wrongly report "is not numeric".
    write_module(
        search_root,
        minimal_tool_manifest(
            capabilities=[
                {
                    "name": "place_part",
                    "summary": "Place a part at a given pose.",
                    "parameters": {"target_pose": {"type": "pose6d", "frame": "tool1.tcp"}},
                }
            ]
        ),
    )
    data = build_cell_dict(
        plan=[
            {
                "step": "place",
                "module": "tool1",
                "op": "place_part",
                "params": {"target_pose": {"xyz_mm": [999999, -999999, 0], "rpy_deg": [0, 0, 0]}},
            }
        ]
    )
    cell = Cell.from_dict(data)

    resolve_cell(cell, search_root)  # should not raise -- no bounds apply to a pose6d


def test_vec3_and_struct_params_are_not_bounds_checked(search_root):
    write_module(
        search_root,
        minimal_tool_manifest(
            capabilities=[
                {
                    "name": "calibrate",
                    "summary": "Apply a calibration offset and a raw blob.",
                    "parameters": {
                        "offset": {"type": "vec3"},
                        "blob": {"type": "struct", "fields": {"a": "integer", "b": "boolean"}},
                    },
                }
            ]
        ),
    )
    data = build_cell_dict(
        plan=[
            {
                "step": "calibrate",
                "module": "tool1",
                "op": "calibrate",
                "params": {"offset": [1.0, 2.0, 3.0], "blob": {"a": 7, "b": True}},
            }
        ]
    )
    cell = Cell.from_dict(data)

    resolve_cell(cell, search_root)  # should not raise -- composite types are opaque to bounds checking
