# SPDX-License-Identifier: AGPL-3.0-or-later
"""Resolves and attempts to scene-build the real, checked-in bracket-asm-01
cell against the real modules/ directory.

This currently -- correctly -- refuses. Of the 6 modules the cell
references (base + 5 instances): sd1 and robot1 declare a *placeholder*
mechanical.geometry.urdf_fragment path (e.g. "urdf/sd50.urdf.xacro") that
doesn't exist on disk; base/feed1/nest1/cam1 don't declare urdf_fragment at
all (it's only schema-required for kind=robot). No real CAD/URDF has been
authored for any module yet. Once it is, this test should be updated to
expect success -- that update is itself a meaningful signal that real
geometry landed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ocm_core import load_cell
from ocm_generator.scene import SceneBuildError, build_scene
from ocm_resolve import resolve_cell


def test_real_bracket_cell_scene_build_currently_refuses_on_missing_geometry(repo_root: Path):
    cell = load_cell(repo_root / "cells" / "bracket-asm-01" / "cell.yaml")
    resolved = resolve_cell(cell, repo_root / "modules")  # resolves fine (see ocm-resolve tests)

    with pytest.raises(SceneBuildError) as exc:
        build_scene(resolved, repo_root / "modules")

    errors = exc.value.errors
    # base + robot1 + sd1 + feed1 + nest1 + cam1: none have real geometry yet,
    # split across two honest failure modes (declares none / declared but missing).
    assert len(errors) >= 6
    assert any("not found" in e for e in errors)
    assert any("declares no" in e for e in errors)
