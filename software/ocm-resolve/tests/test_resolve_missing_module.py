# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path

import pytest

from ocm_core.cell import Cell
from ocm_resolve import CellResolutionError, resolve_cell

from .conftest import build_cell_dict


def test_missing_module_instance_is_reported_clearly(search_root):
    data = build_cell_dict(
        modules=[{"instance": "ghost1", "module": "com.example.ghost.nope@9.9.9"}]
    )
    cell = Cell.from_dict(data)

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, search_root)

    assert any(
        "com.example.ghost.nope@9.9.9" in e and "not found" in e for e in exc.value.errors
    )


def test_missing_base_module_is_reported_clearly(search_root):
    data = build_cell_dict(base_ref="com.example.ghost.base@1.0.0")
    cell = Cell.from_dict(data)

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, search_root)

    assert any("com.example.ghost.base@1.0.0" in e and "not found" in e for e in exc.value.errors)


def test_revision_mismatch_is_reported_as_not_found(search_root):
    # The id resolves to a real module.yaml, but that manifest declares a
    # different revision than the cell asked for -- treat it the same as
    # "the referenced module id@revision can't be found", not a silent match.
    data = build_cell_dict(
        modules=[
            {"instance": "tool1", "module": "com.example.tool.tiny@9.9.9"},
        ]
    )
    cell = Cell.from_dict(data)

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, search_root)

    assert any("9.9.9" in e and "1.0.0" in e for e in exc.value.errors)


def test_real_bracket_cell_reports_every_module_missing_from_a_bare_search_path(
    tmp_path: Path, repo_root: Path
):
    # Using the actual dogfood cell against an empty search path: every
    # module it references is "missing", and every one of those should be
    # reported, not just the first (base, robot1, sd1, feed1, nest1, cam1).
    from ocm_core import load_cell

    cell = load_cell(repo_root / "cells" / "bracket-asm-01" / "cell.yaml")
    empty_search_path = tmp_path / "empty_modules"
    empty_search_path.mkdir()

    with pytest.raises(CellResolutionError) as exc:
        resolve_cell(cell, empty_search_path)

    errors = exc.value.errors
    not_found = [e for e in errors if "not found" in e]
    assert len(not_found) >= 6  # base + robot1 + sd1 + feed1 + nest1 + cam1
