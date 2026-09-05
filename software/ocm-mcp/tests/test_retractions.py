# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0037 D5 at the index: attestation effect is computed from the
retraction record, never authored. An UNREPLACED retraction un-covers
the key its claim answered; the superseding claim -- or a fresh
attestation dated after the retraction -- heals it, with no record
touched in either direction."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from ocm_api.claims import claim_id
from ocm_mcp import build_index

REPO_ROOT = Path(__file__).resolve().parents[3]

# The eps25 synthetic fixture: attested at 1.0 (dated 2026-09-01), one
# ip_rating claim.
EPS25 = "sha256:bc8792ff216e076f31c1d92d74a2bcc046a316231049ecf838e251c98bb0b662"


def _registry(tmp_path: Path, mutate) -> Path:
    """Copy the real registry, hand the eps25 file's parsed document to
    `mutate` (the operator's supervised edit, in miniature), rewrite,
    return the root."""
    root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "spec", root / "spec")
    shutil.copytree(REPO_ROOT / "claims", root / "claims")
    path = root / "claims" / EPS25.removeprefix("sha256:") / "claims.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(doc)
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return root


def _ip_rating_claim(doc: dict[str, Any]) -> dict[str, Any]:
    # The ORIGINAL, correct record -- the fixture also carries the
    # already-retracted IP65 misread (the committed ADR-0037 golden),
    # which these tests replace with scenarios of their own.
    (claim,) = [c for c in doc["claims"] if c["key"] == "ip_rating" and c["value"] == "IP67"]
    return claim


def _retract_ip_rating(doc: dict[str, Any], superseded_by: str | None = None) -> None:
    entry: dict[str, Any] = {
        "retracts": _ip_rating_claim(doc)["id"],
        "reason": "row slip: rating transcribed from the neighboring row",
        "date": "2026-09-04",
    }
    if superseded_by is not None:
        entry["superseded_by"] = superseded_by
    doc["retractions"] = [entry]


def test_an_unreplaced_retraction_uncovers_its_key_and_only_its_key(tmp_path: Path):
    root = _registry(tmp_path, _retract_ip_rating)
    index = build_index(root)
    # The 1.0 attestation (2026-09-01) predates the retraction
    # (2026-09-04): its promise for ip_rating is known-broken.
    assert not index.covered(EPS25, "ip_rating")
    # The mask is per-key -- every other key keeps its coverage.
    assert index.covered(EPS25, "supply_voltage")


def test_a_replaced_retraction_leaves_the_attestation_standing(tmp_path: Path):
    def mutate(doc: dict[str, Any]) -> None:
        correction = dict(_ip_rating_claim(doc))
        del correction["id"]
        correction["value"] = "IP66"
        correction["id"] = claim_id(correction, EPS25)
        _retract_ip_rating(doc, superseded_by=correction["id"])
        doc["claims"].append(correction)

    index = build_index(_registry(tmp_path, mutate))
    # The correction re-established what the document states -- which is
    # all the attestation ever promised.
    assert index.covered(EPS25, "ip_rating")


def test_a_fresh_attestation_recovers_a_standalone_retraction(tmp_path: Path):
    # The retracted claim was noise and the document is silent on the key:
    # nothing to supersede. The next pass -- necessarily at a new vocab
    # version (one pass per version) -- re-reads the document knowing the
    # retraction stood, and its attestation, dated after the retraction,
    # re-covers.
    def mutate(doc: dict[str, Any]) -> None:
        _retract_ip_rating(doc)
        doc["attestations"].append({"vocab_version": "1.1", "date": "2026-09-06"})

    index = build_index(_registry(tmp_path, mutate))
    assert index.covered(EPS25, "ip_rating")


def test_an_attestation_dated_before_the_retraction_is_not_fresh(tmp_path: Path):
    # Same shape, but the extra attestation predates the retraction: its
    # pass never saw the retraction, so its promise is broken too.
    def mutate(doc: dict[str, Any]) -> None:
        _retract_ip_rating(doc)
        doc["attestations"].append({"vocab_version": "1.1", "date": "2026-09-02"})

    index = build_index(_registry(tmp_path, mutate))
    assert not index.covered(EPS25, "ip_rating")


def test_a_registry_with_a_dangling_retraction_is_not_served(tmp_path: Path):
    # The referential rule is validate_claims' (one validation surface);
    # the index inherits it by refusing to build -- same posture as every
    # other broken store.
    import pytest

    def mutate(doc: dict[str, Any]) -> None:
        doc["retractions"] = [{"retracts": "sha256:" + "0" * 64, "reason": "x", "date": "2026-09-04"}]

    with pytest.raises(RuntimeError, match="refusing to serve"):
        build_index(_registry(tmp_path, mutate))
