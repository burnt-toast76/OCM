# SPDX-License-Identifier: AGPL-3.0-or-later
"""spec/00: OCM manifests are parsed under YAML 1.2 core-schema resolution --
bare `on`/`off`/`yes`/`no` are strings, not booleans.

That immunity lives in `_Loader` (loader.py), which strips PyYAML's YAML 1.1
bool resolvers. This test keeps the hazard visible from the spec side: every
manifest in the repo parses under 1.2 resolution with no boolean-corrupted
keys, and the repo's own dogfood cell DEMONSTRABLY mis-parses under stock 1.1
resolution (`mount.on` becomes the key True and the mount silently vanishes).
A third party implementing against OCM manifests with a stock YAML 1.1 library
hits exactly this; spec/00 now says so normatively.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ocm_core.loader import _read_yaml


def _repo_manifests(repo_root: Path) -> list[Path]:
    files = sorted(
        list((repo_root / "modules").rglob("module.yaml"))
        + list((repo_root / "components").rglob("component.yaml"))
        + list((repo_root / "cells").rglob("cell.yaml"))
    )
    assert files, "manifest walk found nothing -- repo layout changed?"
    return files


def _has_bool_key(node) -> bool:
    if isinstance(node, dict):
        return any(isinstance(k, bool) for k in node) or any(_has_bool_key(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_bool_key(v) for v in node)
    return False


def test_every_manifest_parses_cleanly_under_yaml_12_resolution(repo_root):
    # Under 1.2 resolution no mapping key in any manifest resolves to a boolean
    # -- `on` stays the string 'on'. (Boolean VALUES like `abort_safe: false`
    # are spelled true/false and stay booleans; only the 1.1 legacy tokens are
    # at issue, and they must stay strings.)
    for f in _repo_manifests(repo_root):
        data = _read_yaml(f)
        assert not _has_bool_key(data), f"{f}: YAML 1.2 loader produced a boolean mapping key"


def test_dogfood_cell_demonstrably_mis_parses_under_yaml_11(repo_root):
    # The load-bearing example from spec/00: stock yaml.safe_load (1.1
    # resolution) turns sd1's `mount: {on: robot1.flange}` into {True: ...} --
    # the mount silently vanishes. If this test ever fails because the cell no
    # longer contains an affected token, the spec/00 example needs a new one;
    # the hazard must stay demonstrated, not just asserted.
    cell_path = repo_root / "cells" / "bracket-asm-01" / "cell.yaml"
    corrupted = yaml.safe_load(cell_path.read_text(encoding="utf-8"))
    sd1_11 = next(m for m in corrupted["modules"] if m["instance"] == "sd1")
    assert True in sd1_11["mount"], "yaml 1.1 no longer corrupts mount.on -- update the spec/00 example"
    assert "on" not in sd1_11["mount"]

    faithful = _read_yaml(cell_path)
    sd1_12 = next(m for m in faithful["modules"] if m["instance"] == "sd1")
    assert sd1_12["mount"]["on"] == "robot1.flange"


def test_manifests_round_trip_identically_under_12_and_the_differing_set_is_known(repo_root):
    # Whole-repo comparison of 1.1-parse vs 1.2-parse. Exactly one shipped
    # manifest is affected today (the dogfood cell's mount.on). If this set
    # grows, that is a manifest newly carrying a 1.1-hazardous token -- fine
    # under the spec, but this list is updated CONSCIOUSLY so nobody ships one
    # without knowing a 1.1 parser would corrupt it.
    differing: list[str] = []
    for f in _repo_manifests(repo_root):
        parsed_11 = yaml.safe_load(f.read_text(encoding="utf-8"))
        parsed_12 = _read_yaml(f)
        if parsed_11 != parsed_12:
            differing.append(str(f.relative_to(repo_root)))
    assert differing == ["cells/bracket-asm-01/cell.yaml"], differing
