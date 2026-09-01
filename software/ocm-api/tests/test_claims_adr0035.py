# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0035: validate_claims is the one validation surface for a claims
file (ADR-0016 -- schema + vocabulary binding + stored-id verification in
one verb, no weaker sibling), and claim_id is the one implementation of
spec/schema/ocm-claims-serialization-1.0.md. The two worked examples in
that spec are GOLDEN VECTORS here: if claim_id ever drifts from the
published bytes-and-hash, these tests fail before any citation dangles.
Fixtures are inline and obviously synthetic (ADR-0014)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from ocm_api import Codes, OcmApi
from ocm_api.claims import claim_id

# The example document from the serialization spec, section 6:
# sha256 of the ASCII bytes "ocm example datasheet".
DOC_HASH = "sha256:c03286e02ea14374f3b7e69ffb4d9616125bc7db49b9f397a1cb716211a290bb"

SPEC_SCHEMA_DIR = Path(__file__).resolve().parents[3] / "spec" / "schema"


def _subject_claim() -> dict[str, Any]:
    # Serialization spec section 6.1, verbatim.
    return {
        "id": "sha256:4a37e484097417013ebc6be947b0aeabefaa0ffa25de7f53715af7c812a99b13",
        "key": "output_configuration",
        "subject": "OUT2",
        "value": "PNP/NPN selectable",
        "conditions": [],
        "applies_to": ["EX-100"],
        "citation": {"page": 2, "locator": "spec table, row 'Output 2'"},
        "extraction": {"method": "human"},
    }


def _spread_claim() -> dict[str, Any]:
    # Serialization spec section 6.2, verbatim -- `unqualified: 6.0`
    # deliberately, to pin the 6.0 -> 6 canonicalization (spec section 3).
    return {
        "id": "sha256:38fedc6c90e0700ad64da4fadbd70b20a9832e274e3a5d2adf5f2ee8e2d3f16e",
        "key": "operating_pressure",
        "value": {"unqualified": 6.0, "max": 8, "unit": "bar"},
        "conditions": ["filtered, non-lubricated air"],
        "applies_to": ["EX-200", "EX-201"],
        "family": "EX series",
        "citation": {"page": 1, "locator": "table 'Specifications', row 'Operating pressure'"},
        "extraction": {"method": "human"},
    }


def _claims_file(claims: list[dict[str, Any]], attestations: list[dict[str, Any]] | None = None, doc_hash: str = DOC_HASH) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "ocm_version": "1.0",
        "document": {"hash": doc_hash, "manufacturer": "Example Automation", "type": "datasheet"},
        "claims": claims,
    }
    if attestations is not None:
        doc["attestations"] = attestations
    return doc


def _write_claims(workspace_root: Path, doc: dict[str, Any], doc_hash: str = DOC_HASH) -> None:
    claims_dir = workspace_root / "claims" / doc_hash.removeprefix("sha256:")
    claims_dir.mkdir(parents=True, exist_ok=True)
    (claims_dir / "claims.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")


# -- claim_id: the spec's golden vectors --------------------------------------


def test_claim_id_matches_the_specs_subject_bearing_example():
    assert claim_id(_subject_claim(), DOC_HASH) == "sha256:4a37e484097417013ebc6be947b0aeabefaa0ffa25de7f53715af7c812a99b13"


def test_claim_id_matches_the_specs_spread_example():
    assert claim_id(_spread_claim(), DOC_HASH) == "sha256:38fedc6c90e0700ad64da4fadbd70b20a9832e274e3a5d2adf5f2ee8e2d3f16e"


def test_extraction_is_outside_the_hash_so_passes_converge():
    # A human pass and an automated pass of the same statement share one
    # id -- ADR-0035 D6's parity test depends on this.
    human = _subject_claim()
    automated = dict(_subject_claim(), extraction={"method": "automated", "tool": "extractor 0.1"})
    assert claim_id(human, DOC_HASH) == claim_id(automated, DOC_HASH)


def test_the_document_hash_is_inside_the_hash_so_documents_stay_distinct():
    other = "sha256:" + "0" * 64
    assert claim_id(_subject_claim(), DOC_HASH) != claim_id(_subject_claim(), other)


def test_an_omitted_subject_hashes_differently_from_a_present_one():
    # Serialization spec section 2: an omitted optional member is absent,
    # never null -- absence is itself transcription.
    without = _subject_claim()
    del without["subject"]
    assert claim_id(without, DOC_HASH) != claim_id(_subject_claim(), DOC_HASH)


# -- validate_claims: the happy path ------------------------------------------


def test_a_clean_claims_file_validates_with_no_warnings(api: OcmApi, workspace_root: Path):
    _write_claims(workspace_root, _claims_file([_subject_claim(), _spread_claim()], attestations=[{"vocab_version": "1.0", "date": "2026-09-01"}]))
    e = api.validate_claims(DOC_HASH)
    assert e.ok, e.refusals
    assert e.data == {"document": DOC_HASH, "claims": 2, "valid": True}
    assert e.warnings == ()


def test_a_document_accumulates_one_attestation_per_vocab_version(api: OcmApi, workspace_root: Path):
    # Vocabulary 1.1 adds keys: the already-attested document gets a second
    # pass and a second, 1.1-pinned attestation (ADR-0035 D4/D7).
    _write_claims(workspace_root, _claims_file(
        [_subject_claim()],
        attestations=[
            {"vocab_version": "1.0", "date": "2026-09-01"},
            {"vocab_version": "1.1", "date": "2026-11-15"},
        ],
    ))
    e = api.validate_claims(DOC_HASH)
    assert e.ok, e.refusals


def test_two_attestations_at_the_same_vocab_version_refuse(api: OcmApi, workspace_root: Path):
    # One pass per vocabulary version, written once when it finishes.
    _write_claims(workspace_root, _claims_file(
        [_subject_claim()],
        attestations=[
            {"vocab_version": "1.0", "date": "2026-09-01"},
            {"vocab_version": "1.0", "date": "2026-09-02"},
        ],
    ))
    e = api.validate_claims(DOC_HASH)
    assert not e.ok
    (refusal,) = e.refusals
    assert refusal.path == "attestations[1].vocab_version"
    assert "one pass per vocabulary version" in refusal.message


def test_an_x_claim_is_well_formed_but_unbound(api: OcmApi, workspace_root: Path):
    x_claim = dict(_subject_claim(), key="x-response_time", value="10 ms")
    del x_claim["subject"]
    x_claim["id"] = claim_id(x_claim, DOC_HASH)
    _write_claims(workspace_root, _claims_file([x_claim]))

    e = api.validate_claims(DOC_HASH)
    assert e.ok, e.refusals
    assert any("unbound" in w and "x-response_time" in w for w in e.warnings)


def test_missing_file_refuses_not_found(api: OcmApi):
    e = api.validate_claims("sha256:" + "e" * 64)
    assert not e.ok
    assert e.refusals[0].code == Codes.OCM_NOT_FOUND


# -- validate_claims: append-only, enforced -----------------------------------


def test_an_edited_record_is_caught_by_its_stored_id(api: OcmApi, workspace_root: Path):
    # The well-meant typo fix: the value changes, the stored id doesn't.
    edited = dict(_subject_claim(), value="PNP/NPN selectable, N.O.")
    _write_claims(workspace_root, _claims_file([edited]))

    e = api.validate_claims(DOC_HASH)
    assert not e.ok
    (refusal,) = e.refusals
    assert refusal.path == "claims[0].id"
    assert "does not match the recomputed id" in refusal.message


def test_a_file_stored_under_the_wrong_hash_refuses(api: OcmApi, workspace_root: Path):
    other = "sha256:" + "a" * 64
    _write_claims(workspace_root, _claims_file([_subject_claim()]), doc_hash=other)

    e = api.validate_claims(other)
    assert not e.ok
    assert any(r.path == "document.hash" and "storage location" in r.message for r in e.refusals)


# -- validate_claims: schema half ---------------------------------------------


def test_a_missing_conditions_field_is_a_schema_error(api: OcmApi, workspace_root: Path):
    claim = _subject_claim()
    del claim["conditions"]  # ADR-0035 D1: [] attests none; absence refuses
    _write_claims(workspace_root, _claims_file([claim]))

    e = api.validate_claims(DOC_HASH)
    assert not e.ok
    assert any("conditions" in r.message for r in e.refusals)


def test_a_bare_number_is_never_a_valid_spread(api: OcmApi, workspace_root: Path):
    claim = dict(_spread_claim(), value=6)
    _write_claims(workspace_root, _claims_file([claim]))

    e = api.validate_claims(DOC_HASH)
    assert not e.ok
    assert any("claims/0/value" in r.path.replace(".", "/") or "value" in r.path for r in e.refusals)


def test_null_is_not_a_valid_value_anywhere(api: OcmApi, workspace_root: Path):
    claim = dict(_subject_claim(), subject=None)
    _write_claims(workspace_root, _claims_file([claim]))

    e = api.validate_claims(DOC_HASH)
    assert not e.ok


def test_a_spread_with_only_a_unit_refuses(api: OcmApi, workspace_root: Path):
    claim = dict(_spread_claim(), value={"unit": "bar"})
    _write_claims(workspace_root, _claims_file([claim]))

    e = api.validate_claims(DOC_HASH)
    assert not e.ok


def test_unqualified_may_coexist_with_a_bound(api: OcmApi, workspace_root: Path):
    # "6 bar (max 8 bar)" -- any combination is legal; requalifying or
    # dropping a printed value is the fabrication the slot exists to stop.
    claim = _spread_claim()
    assert "unqualified" in claim["value"] and "max" in claim["value"]
    _write_claims(workspace_root, _claims_file([claim]))
    assert api.validate_claims(DOC_HASH).ok


# -- validate_claims: vocabulary half -----------------------------------------


def test_an_unknown_key_without_x_prefix_refuses(api: OcmApi, workspace_root: Path):
    claim = dict(_subject_claim(), key="holding_torque")
    del claim["subject"]
    claim["id"] = claim_id(claim, DOC_HASH)
    _write_claims(workspace_root, _claims_file([claim]))

    e = api.validate_claims(DOC_HASH)
    assert not e.ok
    assert any("not in the claims vocabulary" in r.message for r in e.refusals)


def test_a_shape_mismatch_against_the_vocabulary_refuses(api: OcmApi, workspace_root: Path):
    # operating_pressure is declared shape spread; a text value is a
    # different answer to a different question.
    claim = dict(_spread_claim(), value="4-6 bar")
    claim["id"] = claim_id(claim, DOC_HASH)
    _write_claims(workspace_root, _claims_file([claim]))

    e = api.validate_claims(DOC_HASH)
    assert not e.ok
    assert any("declared shape 'spread'" in r.message for r in e.refusals)


def test_a_subject_on_a_non_taking_key_refuses(api: OcmApi, workspace_root: Path):
    claim = {
        "key": "mass",
        "subject": "the heavy end",
        "value": {"number": 2.5, "unit": "kg"},
        "conditions": [],
        "applies_to": ["EX-100"],
        "citation": {"page": 3, "locator": "spec table, row 'Weight'"},
        "extraction": {"method": "human"},
    }
    claim["id"] = claim_id(claim, DOC_HASH)
    _write_claims(workspace_root, _claims_file([claim]))

    e = api.validate_claims(DOC_HASH)
    assert not e.ok
    assert any("takes no subject" in r.message for r in e.refusals)


def test_an_omitted_subject_on_a_taking_key_is_legal(api: OcmApi, workspace_root: Path):
    # The sole unlabeled connector: the document designates no element,
    # and the absence is the transcription (ADR-0035 D1).
    claim = dict(_subject_claim())
    del claim["subject"]
    claim["id"] = claim_id(claim, DOC_HASH)
    _write_claims(workspace_root, _claims_file([claim]))
    assert api.validate_claims(DOC_HASH).ok


def test_a_pinout_claim_needs_only_pin_per_row(api: OcmApi, workspace_root: Path):
    # The deliberate divergence from the component schema: a printed pin
    # table without a function column is still a true statement.
    claim = {
        "key": "connector_pinout",
        "subject": "X1",
        "value": [{"pin": "1", "wire_color": "BN (brown)"}, {"pin": "3"}],
        "conditions": [],
        "applies_to": ["EX-100"],
        "citation": {"page": 2, "locator": "wiring diagram"},
        "extraction": {"method": "human"},
    }
    claim["id"] = claim_id(claim, DOC_HASH)
    _write_claims(workspace_root, _claims_file([claim]))
    e = api.validate_claims(DOC_HASH)
    assert e.ok, e.refusals


def test_a_stuffed_text_value_gets_the_single_statement_advisory(api: OcmApi, workspace_root: Path):
    # Several statements wearing one claim (D1: a claim is a SINGLE
    # datasheet-answerable statement) -- advised, never refused.
    claim = dict(_subject_claim(), value="Open-collector, 30 V or less, 100 mA per output, residual 1.4 V")
    claim["id"] = claim_id(claim, DOC_HASH)
    _write_claims(workspace_root, _claims_file([claim]))

    e = api.validate_claims(DOC_HASH)
    assert e.ok, e.refusals
    assert any("single datasheet-answerable statement" in w for w in e.warnings)


def test_a_short_analog_range_text_stays_below_the_advisory(api: OcmApi, workspace_root: Path):
    # Two quantities is an ordinary analog-range statement, not stuffing.
    claim = dict(_subject_claim(), value="4-20 mA / 0-10 VDC analog")
    claim["id"] = claim_id(claim, DOC_HASH)
    _write_claims(workspace_root, _claims_file([claim]))

    e = api.validate_claims(DOC_HASH)
    assert e.ok, e.refusals
    assert not any("single datasheet-answerable statement" in w for w in e.warnings)


# -- the pinout fragment drift guard ------------------------------------------


def test_pinout_properties_mirror_the_component_schema_verbatim():
    """The record fragment's property definitions are embedded (a plain
    Draft202012Validator resolves no cross-file $refs) and must stay
    byte-identical to the component schema's pins definition. `required`
    is the one deliberate divergence: ['pin'] alone, per the transcription
    rule the fragment's description states."""
    claims_schema = json.loads((SPEC_SCHEMA_DIR / "ocm-claims-1.0.schema.json").read_text(encoding="utf-8"))
    component_schema = json.loads((SPEC_SCHEMA_DIR / "ocm-component-1.0.schema.json").read_text(encoding="utf-8"))

    fragment = claims_schema["$defs"]["record_pinout"]["items"]
    pins = component_schema["properties"]["electrical"]["properties"]["connectors"]["items"]["properties"]["pins"]["items"]

    assert fragment["properties"] == pins["properties"]
    assert fragment["required"] == ["pin"]
    assert pins["required"] == ["pin", "function"]  # the divergence is real, not vacuous
