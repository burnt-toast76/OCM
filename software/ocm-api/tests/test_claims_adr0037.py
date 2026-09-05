# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0037: corrections under append-only. A retraction is a pure
addition -- the wrong record's bytes never change, the correction is an
ordinary claim appended through the normal path, and validate_claims
enforces the referential rules the schema cannot see: same-file targets,
at most one retraction per claim, no self-supersession."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ocm_api import Codes, OcmApi
from ocm_api.claims import claim_id

from .test_claims_adr0035 import (
    DOC_HASH,
    _claims_file,
    _spread_claim,
    _subject_claim,
    _write_claims,
)


def _retraction(retracts: str, superseded_by: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "retracts": retracts,
        "reason": "row slip: value transcribed from the neighboring row",
        "date": "2026-09-05",
    }
    if superseded_by is not None:
        entry["superseded_by"] = superseded_by
    return entry


def _correction_of_subject_claim() -> dict[str, Any]:
    # The correction re-reads the same statement: same citation, new
    # value, id computed -- never invented (serialization spec).
    claim = _subject_claim()
    del claim["id"]
    claim["value"] = "NPN only"
    claim["id"] = claim_id(claim, DOC_HASH)
    return claim


def _with_retractions(claims: list[dict[str, Any]], retractions: list[dict[str, Any]]) -> dict[str, Any]:
    doc = _claims_file(claims, attestations=[{"vocab_version": "1.0", "date": "2026-09-01"}])
    doc["retractions"] = retractions
    return doc


def test_a_standalone_retraction_validates(api: OcmApi, workspace_root: Path):
    # No superseded_by: the record was wrong and the document states
    # nothing in its place. The retracted claim's bytes are untouched --
    # its stored id still verifies, which IS the append-only proof.
    wrong = _subject_claim()
    _write_claims(workspace_root, _with_retractions([wrong, _spread_claim()], [_retraction(wrong["id"])]))
    e = api.validate_claims(DOC_HASH)
    assert e.ok, e.refusals


def test_a_replaced_retraction_validates_and_the_correction_is_ordinary(api: OcmApi, workspace_root: Path):
    wrong = _subject_claim()
    correction = _correction_of_subject_claim()
    _write_claims(workspace_root, _with_retractions([wrong, correction], [_retraction(wrong["id"], correction["id"])]))
    e = api.validate_claims(DOC_HASH)
    assert e.ok, e.refusals
    # The correction is a claim like any other: content-hash id, same
    # citation as the record it replaces, distinct identity.
    assert correction["id"] != wrong["id"]
    assert correction["citation"] == wrong["citation"]


def test_the_correction_arrives_through_append_claims(api: OcmApi, workspace_root: Path):
    # The tool path writes the correction (id computed server-side); the
    # retraction is the operator's mutation, made directly to the file --
    # append_claims deliberately has no way to write one (ADR-0037 D3).
    wrong = _subject_claim()
    _write_claims(workspace_root, _claims_file([wrong], attestations=[{"vocab_version": "1.0", "date": "2026-09-01"}]))

    candidate = _correction_of_subject_claim()
    del candidate["id"]
    appended = api.append_claims(DOC_HASH, [candidate])
    assert appended.ok, appended.refusals
    (correction_id,) = appended.data["ids"]

    path = workspace_root / "claims" / DOC_HASH.removeprefix("sha256:") / "claims.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["retractions"] = [_retraction(wrong["id"], correction_id)]
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")

    e = api.validate_claims(DOC_HASH)
    assert e.ok, e.refusals


def test_append_claims_carries_an_existing_retraction_forward_untouched(api: OcmApi, workspace_root: Path):
    wrong = _subject_claim()
    _write_claims(workspace_root, _with_retractions([wrong], [_retraction(wrong["id"])]))
    candidate = _spread_claim()
    del candidate["id"]
    assert api.append_claims(DOC_HASH, [candidate]).ok

    path = workspace_root / "claims" / DOC_HASH.removeprefix("sha256:") / "claims.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["retractions"] == [_retraction(wrong["id"])]


def test_an_unknown_retracted_id_refuses(api: OcmApi, workspace_root: Path):
    ghost = "sha256:" + "0" * 64
    _write_claims(workspace_root, _with_retractions([_subject_claim()], [_retraction(ghost)]))
    e = api.validate_claims(DOC_HASH)
    assert not e.ok
    assert any(r.code == Codes.OCM_NOT_FOUND and r.path == "retractions[0].retracts" for r in e.refusals)


def test_an_unknown_superseding_id_refuses(api: OcmApi, workspace_root: Path):
    # The correction is appended FIRST, then the retraction points at it
    # -- a superseded_by naming nothing is a dangling promise.
    wrong = _subject_claim()
    ghost = "sha256:" + "1" * 64
    _write_claims(workspace_root, _with_retractions([wrong], [_retraction(wrong["id"], ghost)]))
    e = api.validate_claims(DOC_HASH)
    assert not e.ok
    assert any(r.code == Codes.OCM_NOT_FOUND and r.path == "retractions[0].superseded_by" for r in e.refusals)


def test_a_claim_retracted_twice_refuses(api: OcmApi, workspace_root: Path):
    wrong = _subject_claim()
    _write_claims(workspace_root, _with_retractions([wrong], [_retraction(wrong["id"]), _retraction(wrong["id"])]))
    e = api.validate_claims(DOC_HASH)
    assert not e.ok
    assert any(r.path == "retractions[1].retracts" and "retracted twice" in r.message for r in e.refusals)


def test_self_supersession_refuses(api: OcmApi, workspace_root: Path):
    wrong = _subject_claim()
    _write_claims(workspace_root, _with_retractions([wrong], [_retraction(wrong["id"], wrong["id"])]))
    e = api.validate_claims(DOC_HASH)
    assert not e.ok
    assert any(r.path == "retractions[0].superseded_by" and "own retraction" in r.message for r in e.refusals)


def test_a_retraction_without_a_reason_is_a_schema_error(api: OcmApi, workspace_root: Path):
    wrong = _subject_claim()
    entry = _retraction(wrong["id"])
    del entry["reason"]
    _write_claims(workspace_root, _with_retractions([wrong], [entry]))
    assert not api.validate_claims(DOC_HASH).ok


def test_a_non_iso_retraction_date_is_a_schema_error(api: OcmApi, workspace_root: Path):
    # ISO-constrained deliberately: ADR-0037 D5's freshness test orders
    # attestations against this date, and lexicographic ISO comparison is
    # what makes that well-defined.
    wrong = _subject_claim()
    entry = _retraction(wrong["id"])
    entry["date"] = "Sept 5, 2026"
    _write_claims(workspace_root, _with_retractions([wrong], [entry]))
    assert not api.validate_claims(DOC_HASH).ok
