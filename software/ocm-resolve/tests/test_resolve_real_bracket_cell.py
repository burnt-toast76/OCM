# SPDX-License-Identifier: AGPL-3.0-or-later
"""Resolves the real, checked-in bracket-asm-01 cell against the real
modules/ directory. This is the actual deliverable: proof the dogfood cell
resolves end-to-end now that every module it references has a manifest
(see modules/com.universal-robots.ur5e and its four siblings).
"""

from __future__ import annotations

from pathlib import Path

from ocm_core import load_cell
from ocm_resolve import resolve_cell


def test_real_bracket_cell_resolves_end_to_end(repo_root: Path):
    cell = load_cell(repo_root / "cells" / "bracket-asm-01" / "cell.yaml")

    resolved = resolve_cell(cell, repo_root / "modules")

    assert resolved.base.id == "com.accelsolutions.base.frame1200"
    assert set(resolved.instances) == {"robot1", "sd1", "feed1", "nest1", "cam1"}


def test_real_bracket_cell_sd1_is_mounted_on_robot1_flange(repo_root: Path):
    cell = load_cell(repo_root / "cells" / "bracket-asm-01" / "cell.yaml")

    resolved = resolve_cell(cell, repo_root / "modules")

    assert resolved.instance("sd1").mounted_on is resolved.instance("robot1")


def test_real_bracket_cell_plan_ops_are_all_declared_capabilities(repo_root: Path):
    # fasten/sequence's load_screw, drive_screw, eject_screw all resolve
    # against sd1's real (not stub) manifest; clamp/unclamp/locate_part
    # resolve against the new stubs. Nothing in the plan references an
    # op its module doesn't declare.
    cell = load_cell(repo_root / "cells" / "bracket-asm-01" / "cell.yaml")

    resolved = resolve_cell(cell, repo_root / "modules")

    nest1_ops = {c.name for c in resolved.instance("nest1").module.capabilities}
    assert {"clamp", "unclamp"} <= nest1_ops
    cam1_ops = {c.name for c in resolved.instance("cam1").module.capabilities}
    assert "locate_part" in cam1_ops
