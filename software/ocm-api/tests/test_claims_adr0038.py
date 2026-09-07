# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0038 Decisions 6, 11 and 12 where they are enforceable in code.

D6: `parsed` is a third extraction method, requiring tool and tool_version,
optionally naming what the source says produced it; and `document.encoding`
records what the FILE declares about itself -- descriptive, correctable under
D3, outside every hash scope.

D11: appending is idempotent per record and no file ever holds one id twice.
The two halves are tested separately on purpose -- the no-op prevents the
ordinary case, the refusal catches every other one, and each has to work
without the other.

D10 and D12 are transcription rules with no code surface: they govern what a
pass writes, not what the store will accept, and are enforced by review and
`docs/ingestion.md`. Encoding them as validation would mean the validator
deciding whether a value is a device's fact or a cell's configuration, which
it cannot see.
"""

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


def _parsed_claim(**extraction: Any) -> dict[str, Any]:
    claim = {
        "key": "protocol",
        "subject": "X1",
        "value": "EtherCAT",
        "conditions": [],
        "applies_to": ["EX-100"],
        "citation": {"page": 4, "locator": "Device[1] ELX1052, Type"},
        "extraction": {"method": "parsed", **extraction},
    }
    return claim


# -- D6: the parsed method ----------------------------------------------------


def test_parsed_extraction_validates_with_tool_and_version(api: OcmApi, workspace_root: Path):
    _write_claims(workspace_root, _claims_file([_subject_claim()]))
    e = api.append_claims(DOC_HASH, [_parsed_claim(tool="esi-parse", tool_version="0.3.1")])
    assert e.ok, e.refusals
    assert e.data["written"] == 1


def test_parsed_extraction_may_name_what_the_source_says_produced_it(api: OcmApi, workspace_root: Path):
    """source_generator is provenance about the DOCUMENT, not the pass, and is
    never required: an EDS announces its generator and an ESI declares none."""
    _write_claims(workspace_root, _claims_file([_subject_claim()]))
    e = api.append_claims(
        DOC_HASH,
        [_parsed_claim(tool="eds-parse", tool_version="1.0.0", source_generator="EZ-EDS Version 3.25.1.20181218")],
    )
    assert e.ok, e.refusals


def test_parsed_extraction_without_tool_version_is_refused(api: OcmApi, workspace_root: Path):
    """A parser's VERSION is what changes the transcription it emits, so it is
    required where `tool` alone would be a claim about nothing in particular."""
    _write_claims(workspace_root, _claims_file([_subject_claim()]))
    e = api.append_claims(DOC_HASH, [_parsed_claim(tool="esi-parse")])
    assert not e.ok
    assert any("tool_version" in (r.message or "") for r in e.refusals), e.refusals


def test_parsed_extraction_without_tool_is_refused(api: OcmApi, workspace_root: Path):
    _write_claims(workspace_root, _claims_file([_subject_claim()]))
    e = api.append_claims(DOC_HASH, [_parsed_claim(tool_version="0.3.1")])
    assert not e.ok


def test_automated_extraction_still_needs_neither(api: OcmApi, workspace_root: Path):
    """The requirement is conditional on `parsed`; it must not leak onto the
    method every existing record in the store uses."""
    _write_claims(workspace_root, _claims_file([_subject_claim()]))
    claim = _parsed_claim()
    claim["extraction"] = {"method": "automated"}
    assert api.append_claims(DOC_HASH, [claim]).ok


def test_extraction_stays_outside_the_hash_scope(api: OcmApi, workspace_root: Path):
    """The whole reason `parsed` can be added at all: a hand pass and a parser
    pass of one statement converge on one id, or the parity test has nothing to
    measure (ADR-0035 D6, ADR-0038 D6)."""
    by_hand = _parsed_claim()
    by_hand["extraction"] = {"method": "human"}
    by_parser = _parsed_claim(tool="esi-parse", tool_version="0.3.1")
    assert claim_id(by_hand, DOC_HASH) == claim_id(by_parser, DOC_HASH)


# -- D6: document.encoding ----------------------------------------------------


def test_document_encoding_is_optional_and_accepted(api: OcmApi, workspace_root: Path):
    doc = _claims_file([_subject_claim()])
    assert "encoding" not in doc["document"]
    _write_claims(workspace_root, doc)
    assert api.validate_claims(DOC_HASH).ok  # absent is fine

    doc["document"]["encoding"] = "ISO-8859-1"
    _write_claims(workspace_root, doc)
    assert api.validate_claims(DOC_HASH).ok


def test_correcting_the_declared_encoding_moves_no_claim_id(api: OcmApi, workspace_root: Path):
    """D3 governs it: descriptive metadata, correctable in place, outside every
    hash scope. A misread encoding is a description error, not a false claim."""
    def stored_ids() -> list[str]:
        path = workspace_root / "claims" / DOC_HASH.removeprefix("sha256:") / "claims.yaml"
        return [c["id"] for c in yaml.safe_load(path.read_text(encoding="utf-8"))["claims"]]

    doc = _claims_file([_subject_claim(), _spread_claim()])
    doc["document"]["encoding"] = "us-ascii"
    _write_claims(workspace_root, doc)
    assert api.validate_claims(DOC_HASH).ok
    before = stored_ids()

    doc["document"]["encoding"] = "ISO-8859-1"
    _write_claims(workspace_root, doc)
    e = api.validate_claims(DOC_HASH)
    assert e.ok, e.refusals  # stored-id verification passes: no id moved
    assert stored_ids() == before


# -- D11: idempotent append ---------------------------------------------------


def test_re_appending_identical_records_writes_nothing_and_reports_them_skipped(api: OcmApi, workspace_root: Path):
    _write_claims(workspace_root, _claims_file([_subject_claim()]))
    first = api.append_claims(DOC_HASH, [_parsed_claim(tool="esi-parse", tool_version="0.3.1")])
    assert first.ok and first.data["written"] == 1 and first.data["skipped"] == 0

    path = workspace_root / "claims" / DOC_HASH.removeprefix("sha256:") / "claims.yaml"
    bytes_before = path.read_bytes()

    again = api.append_claims(DOC_HASH, [_parsed_claim(tool="esi-parse", tool_version="0.3.1")])
    assert again.ok, again.refusals
    assert again.data["written"] == 0
    assert again.data["skipped"] == 1
    assert again.data["skipped_ids"] == first.data["ids"]
    assert again.data["claims"] == first.data["claims"]  # the file did not grow

    # Idempotent means the BYTES do not move either, not merely the records.
    assert path.read_bytes() == bytes_before


def test_a_batch_is_deduplicated_against_itself(api: OcmApi, workspace_root: Path):
    """The same duplicate arriving by a shorter route. Without this the call
    would build a file validate_claims must then refuse."""
    _write_claims(workspace_root, _claims_file([_subject_claim()]))
    claim = _parsed_claim(tool="esi-parse", tool_version="0.3.1")
    e = api.append_claims(DOC_HASH, [claim, dict(claim)])
    assert e.ok, e.refusals
    assert e.data["written"] == 1 and e.data["skipped"] == 1


def test_a_partly_new_batch_writes_only_the_new_records(api: OcmApi, workspace_root: Path):
    _write_claims(workspace_root, _claims_file([_subject_claim()]))
    old = _parsed_claim(tool="esi-parse", tool_version="0.3.1")
    assert api.append_claims(DOC_HASH, [old]).ok

    new = _parsed_claim(tool="esi-parse", tool_version="0.3.1")
    new["subject"] = "X2"
    e = api.append_claims(DOC_HASH, [old, new])
    assert e.ok, e.refusals
    assert e.data["written"] == 1 and e.data["skipped"] == 1
    assert e.data["claims"] == 3


# -- D11: the store-side invariant --------------------------------------------


def test_a_file_holding_one_id_twice_is_refused_naming_the_id(api: OcmApi, workspace_root: Path):
    """Hand-built, because the append path can no longer produce it -- which is
    exactly why the invariant is checked separately from the no-op."""
    duplicated = _subject_claim()
    _write_claims(workspace_root, _claims_file([duplicated, _spread_claim(), dict(duplicated)]))

    e = api.validate_claims(DOC_HASH)
    assert not e.ok
    assert any(duplicated["id"] in (r.message or "") for r in e.refusals), e.refusals
    assert any(r.code == Codes.OCM_INVALID_ARGUMENT for r in e.refusals)


def test_the_duplicate_refusal_does_not_fire_on_distinct_records(api: OcmApi, workspace_root: Path):
    _write_claims(workspace_root, _claims_file([_subject_claim(), _spread_claim()]))
    assert api.validate_claims(DOC_HASH).ok
