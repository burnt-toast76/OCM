# SPDX-License-Identifier: AGPL-3.0-or-later
"""Registry discovery across more than one claims root.

The production corpus lives in its own repository; the public checkout
keeps code, schema, vocabulary and the reference fixtures. A workspace
therefore reads an ORDERED list of claims roots, and three rules have to
hold no matter how many are configured: a document is found in whichever
root holds it, a new entry's location is always the primary root, and one
document under two roots is refused rather than resolved by root order.

Zero extra roots -- the contributor's case, and this repo's own CI -- must
behave exactly as it always did; that is asserted here too, because it is
the property most easily lost.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ocm_api import OcmApi
from ocm_api.workspace import CORPUS_ENV, Workspace, corpus_roots_from_env

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_A = "bc8792ff216e076f31c1d92d74a2bcc046a316231049ecf838e251c98bb0b662"
FIXTURE_B = "c704b86ff07863a38fc69681f8e6a993cd2067ca220c7966a8d151877c97b94d"


@pytest.fixture
def split_registry(tmp_path: Path) -> tuple[Path, Path]:
    """A public root carrying spec/ and one fixture entry, and a corpus
    root carrying the other -- the shape the corpus split produces."""
    public = tmp_path / "public"
    corpus = tmp_path / "corpus"
    shutil.copytree(REPO_ROOT / "spec", public / "spec")
    shutil.copytree(REPO_ROOT / "claims" / FIXTURE_A, public / "claims" / FIXTURE_A)
    shutil.copytree(REPO_ROOT / "claims" / FIXTURE_B, corpus / "claims" / FIXTURE_B)
    return public, corpus


def test_public_only_workspace_is_unchanged(split_registry):
    public, _ = split_registry
    ws = Workspace(public)

    assert ws.claims_roots == (public / "claims",)
    assert ws.list_claims_document_hashes() == [f"sha256:{FIXTURE_A}"]
    assert ws.claims_exists(f"sha256:{FIXTURE_A}")
    assert not ws.claims_exists(f"sha256:{FIXTURE_B}")
    assert ws.claims_path(f"sha256:{FIXTURE_A}") == public / "claims" / FIXTURE_A / "claims.yaml"


def test_a_document_is_found_in_whichever_root_holds_it(split_registry):
    public, corpus = split_registry
    ws = Workspace(public, (corpus,))

    assert ws.list_claims_document_hashes() == sorted([f"sha256:{FIXTURE_A}", f"sha256:{FIXTURE_B}"])
    assert ws.claims_path(f"sha256:{FIXTURE_A}") == public / "claims" / FIXTURE_A / "claims.yaml"
    assert ws.claims_path(f"sha256:{FIXTURE_B}") == corpus / "claims" / FIXTURE_B / "claims.yaml"


def test_a_new_entry_would_land_in_the_primary_root(split_registry):
    public, corpus = split_registry
    ws = Workspace(public, (corpus,))
    unknown = "sha256:" + "0" * 64

    # Not found anywhere: the would-be location is the primary root, never
    # the corpus -- storage location is derived, and the corpus is content
    # someone else's ingestion session commits to deliberately.
    assert not ws.claims_exists(unknown)
    assert ws.claims_path(unknown) == public / "claims" / ("0" * 64) / "claims.yaml"


def test_both_roots_validate_through_the_one_validator(split_registry):
    public, corpus = split_registry
    api = OcmApi(public, [corpus])

    for document in (FIXTURE_A, FIXTURE_B):
        envelope = api.validate_claims(f"sha256:{document}")
        assert envelope.ok, envelope.to_dict()


def test_one_document_under_two_roots_is_refused_naming_both(split_registry):
    public, corpus = split_registry
    shutil.copytree(REPO_ROOT / "claims" / FIXTURE_A, corpus / "claims" / FIXTURE_A)
    api = OcmApi(public, [corpus])

    envelope = api.validate_claims(f"sha256:{FIXTURE_A}")
    assert not envelope.ok
    (refusal,) = envelope.refusals
    assert refusal.code == "OCM_INVALID_ARGUMENT"
    # Both paths named: the operator has to know WHICH copy to remove.
    assert str(public / "claims" / FIXTURE_A / "claims.yaml") in refusal.message
    assert str(corpus / "claims" / FIXTURE_A / "claims.yaml") in refusal.message


def test_the_duplicate_refusal_also_guards_the_write_path(split_registry):
    public, corpus = split_registry
    shutil.copytree(REPO_ROOT / "claims" / FIXTURE_A, corpus / "claims" / FIXTURE_A)
    api = OcmApi(public, [corpus])

    envelope = api.append_claims(f"sha256:{FIXTURE_A}", [], attestation={"vocab_version": "1.2", "date": "2026-09-03"})
    assert not envelope.ok
    assert envelope.refusals[0].code == "OCM_INVALID_ARGUMENT"
    assert "filed under 2 claims roots" in envelope.refusals[0].message


def test_corpus_roots_come_from_the_environment(monkeypatch, tmp_path: Path):
    monkeypatch.delenv(CORPUS_ENV, raising=False)
    assert corpus_roots_from_env() == ()

    monkeypatch.setenv(CORPUS_ENV, str(tmp_path))
    assert corpus_roots_from_env() == (tmp_path,)

    # An empty value is "unset", not a root at the process's cwd.
    monkeypatch.setenv(CORPUS_ENV, "   ")
    assert corpus_roots_from_env() == ()
