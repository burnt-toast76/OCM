# SPDX-License-Identifier: AGPL-3.0-or-later
"""Serving behaviors the goldens can't express: the index refuses a
broken registry, and the contract's structural rules hold beyond the
specific golden answers.

Two tests that lived here -- summary mode above the threshold, and keyed
retrieval always full -- moved to the production corpus repository with
the data they need. Both queried FS-N41N, and the summary-mode test needs
a part carrying more than SUMMARY_THRESHOLD claims: no fixture here has
one (the largest is EPS25 at 15), and inventing a bigger fixture to keep
the test local would be fabricating reference content. The corpus runs
them against both roots, which is the configuration that actually serves
them."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ocm_mcp import build_index, get_claims, normalize

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_normalization_is_the_adr_rule():
    # ADR-0036 D4, normative: case-fold + strip space/hyphen/underscore/dot.
    assert normalize("FS-N41N") == normalize("fs n41n") == normalize("FS_N41.n") == "fsn41n"


def test_a_registry_that_fails_validation_is_not_served(tmp_path: Path):
    # Copy the real registry (and the spec/ the validator needs), then
    # edit one ingested record -- the stored-id check must refuse, and
    # the index must refuse to build on top of it.
    root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "spec", root / "spec")
    shutil.copytree(REPO_ROOT / "claims", root / "claims")
    victim = root / "claims" / "bc8792ff216e076f31c1d92d74a2bcc046a316231049ecf838e251c98bb0b662" / "claims.yaml"
    text = victim.read_text(encoding="utf-8")
    assert "min: 18" in text  # the eps25 supply_voltage bound -- hash-scope content
    victim.write_text(text.replace("min: 18", "min: 17", 1), encoding="utf-8")

    with pytest.raises(RuntimeError, match="refusing to serve"):
        build_index(root)


def test_family_claims_are_never_served_as_part_exact(shared_index):
    response = get_claims(shared_index, "EPS25 series")
    assert response["matched_via"] == "family"
    response = get_claims(shared_index, "EPS25-100WC-1001")
    assert response["matched_via"] == "exact"
