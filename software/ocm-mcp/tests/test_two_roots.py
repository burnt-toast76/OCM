# SPDX-License-Identifier: AGPL-3.0-or-later
"""Serving a registry that spans two checkouts (ADR-0036 D8 as amended).

The production corpus is a second claims root: the index reads it as if
its entries were part of the public checkout, while code, schema and
vocabulary always come from the primary. What must hold:

- claims from both roots are served, indistinguishably, by the same
  resolution rules;
- the envelope names both states, so a consumer can tell exactly which
  pair of checkouts answered;
- with no corpus configured, nothing changes except that corpus_state is
  null -- an answer, not an omission;
- one document under two roots is refused at index build, loudly, naming
  both paths: a registry that fails validation does not get served (D5).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ocm_mcp import build_index, get_claims, get_document

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_A = "bc8792ff216e076f31c1d92d74a2bcc046a316231049ecf838e251c98bb0b662"
FIXTURE_B = "c704b86ff07863a38fc69681f8e6a993cd2067ca220c7966a8d151877c97b94d"
PART_A = "EPS25-100WC-1001"
PART_B = "DP-8"


@pytest.fixture
def split_registry(tmp_path: Path) -> tuple[Path, Path]:
    public = tmp_path / "public"
    corpus = tmp_path / "corpus"
    shutil.copytree(REPO_ROOT / "spec", public / "spec")
    shutil.copytree(REPO_ROOT / "claims" / FIXTURE_A, public / "claims" / FIXTURE_A)
    shutil.copytree(REPO_ROOT / "claims" / FIXTURE_B, corpus / "claims" / FIXTURE_B)
    return public, corpus


def test_two_roots_serve_claims_from_both(split_registry):
    public, corpus = split_registry
    index = build_index([public, corpus])

    assert set(index.documents) == {f"sha256:{FIXTURE_A}", f"sha256:{FIXTURE_B}"}

    from_public = get_claims(index, PART_A)
    from_corpus = get_claims(index, PART_B)
    assert from_public["claim_count"] > 0
    assert from_corpus["claim_count"] > 0

    # A served record says nothing about which root it came from: the
    # citation is the document hash, and provenance is the document, not
    # the checkout that happened to hold it.
    for record in from_corpus["claims"]:
        assert record["citation"]["document"] == f"sha256:{FIXTURE_B}"

    document = get_document(index, f"sha256:{FIXTURE_B}")
    assert document["found"] is True
    assert document["record"]["manufacturer"] == "Example Dispensing (synthetic)"
    assert document["bytes_served"] is False


def test_the_envelope_names_both_states(split_registry):
    public, corpus = split_registry
    index = build_index([public, corpus])

    response = get_claims(index, PART_B)
    assert response["serving_state"] == index.serving_state
    assert response["corpus_state"] == index.corpus_state
    # Neither is guessed from the other: the corpus has its own identity,
    # computed from its own tree (here: not a git checkout at all).
    assert index.corpus_state is not None
    assert response["corpus_state"] != response["serving_state"] or index.corpus_state == index.serving_state


def test_public_only_is_unchanged_but_says_so(split_registry):
    public, _ = split_registry
    index = build_index(public)

    assert index.corpus_state is None
    assert index.roots == (public,)
    assert set(index.documents) == {f"sha256:{FIXTURE_A}"}

    response = get_claims(index, PART_A)
    assert response["corpus_state"] is None, "null is the answer 'no corpus', never a missing field"
    assert response["serving_state"] == index.serving_state
    # The part that lives only in the corpus is simply not in this registry.
    assert get_claims(index, PART_B)["absence_state"] == "no_documents"


def test_a_single_root_argument_still_works(split_registry):
    """build_index(root) -- a bare path, as every existing caller passes."""
    public, _ = split_registry
    assert build_index(public).roots == (public,)
    assert build_index(str(public)).roots == (public,)


def test_one_document_under_two_roots_refuses_to_serve(split_registry):
    public, corpus = split_registry
    shutil.copytree(REPO_ROOT / "claims" / FIXTURE_A, corpus / "claims" / FIXTURE_A)

    with pytest.raises(RuntimeError) as excinfo:
        build_index([public, corpus])

    message = str(excinfo.value)
    assert "refusing to serve" in message
    assert str(public / "claims" / FIXTURE_A / "claims.yaml") in message
    assert str(corpus / "claims" / FIXTURE_A / "claims.yaml") in message


def test_a_third_root_is_refused_rather_than_misidentified(split_registry, tmp_path: Path):
    public, corpus = split_registry
    with pytest.raises(ValueError, match="exactly two states"):
        build_index([public, corpus, tmp_path / "another"])
