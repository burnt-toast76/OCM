# SPDX-License-Identifier: AGPL-3.0-or-later
import pytest

from ocm_core.cell import Cell
from ocm_resolve import CellResolutionError, resolve_cell

from .conftest import build_cell_dict


def test_unknown_op_is_reported_clearly(search_root):
    data = build_cell_dict(
        plan=[{"step": "oops", "module": "tool1", "op": "levitate", "params": {}}]
    )
    cell = Cell.from_dict(data)

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, search_root)

    assert any("levitate" in e and "no op" in e for e in exc.value.errors)


def test_unknown_op_error_names_the_available_ops(search_root):
    data = build_cell_dict(
        plan=[{"step": "oops", "module": "tool1", "op": "levitate", "params": {}}]
    )
    cell = Cell.from_dict(data)

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, search_root)

    assert any("drive_screw" in e for e in exc.value.errors)


def test_op_referencing_undeclared_module_instance_is_reported_clearly(search_root):
    # Plan references an instance name that was never declared under `modules:`.
    data = build_cell_dict(
        plan=[{"step": "oops", "module": "nonexistent_instance", "op": "drive_screw"}]
    )
    cell = Cell.from_dict(data)

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, search_root)

    assert any(
        "nonexistent_instance" in e and "unknown module instance" in e for e in exc.value.errors
    )


def test_unknown_op_inside_nested_sequence_is_found(search_root):
    # Mirrors the fasten/sequence/on_fail nesting used by the real dogfood
    # cell -- op-step checking must walk into 'sequence', not just the
    # top-level plan list.
    data = build_cell_dict(
        plan=[
            {
                "step": "fasten",
                "for_each": ["hole_1"],
                "sequence": [
                    {"module": "tool1", "op": "drive_screw", "params": {"torque_nm": 2.4}},
                    {
                        "module": "tool1",
                        "op": "drive_screw",
                        "params": {"torque_nm": 2.4},
                        "on_fail": [{"module": "tool1", "op": "eject_screw"}],
                    },
                ],
            }
        ]
    )
    cell = Cell.from_dict(data)

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, search_root)

    assert any(
        "eject_screw" in e and "no op" in e and "sequence[1].on_fail[0]" in e
        for e in exc.value.errors
    )
