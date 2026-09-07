# SPDX-License-Identifier: AGPL-3.0-or-later
"""propose_claim_split + append_claims (ADR-0035 D1/D6/D7). The parser's
golden vectors are the two splits a human already approved on the real
FS-N41N entry: the control-output blob (six bounds, exact values and
conditions) and the response-time alternates. That is D6's admission
rule in miniature -- automated splitting is trusted exactly as far as it
reproduces the hand-approved output. append_claims is the one write
path: ids computed server-side, whole-file validation before a byte
lands, structurally incapable of touching an existing record."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ocm_api import Codes, OcmApi
from ocm_api.claims import claim_id
from ocm_api.claims_split import split_text_value

DOC_HASH = "sha256:" + "d" * 64

CONTROL_OUTPUT_BLOB = (
    "Open-collector, 30 V or less 100 mA or less per output, 100 mA or less total for 2 outputs "
    "(when used as a solitary unit) /20 mA or less (when used as an expansion unit). "
    "Residual voltage: 1.4 V or less (output current: 10 mA or less) /2 V or less (output current: 10 to 100 mA)"
)

RESPONSE_TIME_BLOB = (
    "23 µs (S-HSPD*1) /50 µs (HSPD*2) /250 µs (FINE) /500 µs (TURBO) /1 ms (SUPER) "
    "/4 ms (ULTRA) /16 ms (MEGA) /64 ms (TERA)"
)


def _claim(key: str, value: Any, subject: str | None = None) -> dict[str, Any]:
    claim: dict[str, Any] = {"key": key}
    if subject is not None:
        claim["subject"] = subject
    claim.update(
        {
            "value": value,
            "conditions": [],
            "applies_to": ["EX-9"],
            "citation": {"page": 1, "locator": "spec table, row 'Example'"},
            "extraction": {"method": "human"},
        }
    )
    return claim


def _write_file(workspace_root: Path, claims: list[dict[str, Any]], attestations: list[dict[str, Any]] | None = None) -> None:
    for claim in claims:
        claim.setdefault("id", claim_id(claim, DOC_HASH))
    doc: dict[str, Any] = {
        "ocm_version": "1.0",
        "document": {"hash": DOC_HASH, "manufacturer": "Example Automation", "type": "datasheet"},
        "claims": claims,
    }
    if attestations is not None:
        doc["attestations"] = attestations
    target = workspace_root / "claims" / DOC_HASH.removeprefix("sha256:")
    target.mkdir(parents=True, exist_ok=True)
    (target / "claims.yaml").write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")


# -- the parser's golden vectors (the human-approved splits) -------------------


def test_control_output_golden_reproduces_the_approved_six():
    proposal = split_text_value(CONTROL_OUTPUT_BLOB)

    assert proposal.grammar == "bounds"
    assert [(c["value"], c["conditions"]) for c in proposal.candidates] == [
        ({"max": 30, "unit": "V"}, []),
        ({"max": 100, "unit": "mA"}, ["per output"]),
        ({"max": 100, "unit": "mA"}, ["total for 2 outputs", "when used as a solitary unit"]),
        ({"max": 20, "unit": "mA"}, ["when used as an expansion unit"]),
        ({"max": 1.4, "unit": "V"}, ["output current: 10 mA or less"]),
        ({"max": 2, "unit": "V"}, ["output current: 10 to 100 mA"]),
    ]
    # Heterogeneous statements: no parser may assign vocabulary keys.
    assert all(c["key"] is None for c in proposal.candidates)
    # Unparsed text is surfaced, never dropped.
    assert proposal.leftovers == ["Open-collector", "Residual voltage"]


def test_response_time_golden_is_eight_alternates():
    proposal = split_text_value(RESPONSE_TIME_BLOB)

    assert proposal.grammar == "alternates"
    assert [(c["value"], c["conditions"]) for c in proposal.candidates] == [
        ({"unqualified": 23, "unit": "µs"}, ["S-HSPD*1"]),
        ({"unqualified": 50, "unit": "µs"}, ["HSPD*2"]),
        ({"unqualified": 250, "unit": "µs"}, ["FINE"]),
        ({"unqualified": 500, "unit": "µs"}, ["TURBO"]),
        ({"unqualified": 1, "unit": "ms"}, ["SUPER"]),
        ({"unqualified": 4, "unit": "ms"}, ["ULTRA"]),
        ({"unqualified": 16, "unit": "ms"}, ["MEGA"]),
        ({"unqualified": 64, "unit": "ms"}, ["TERA"]),
    ]
    assert proposal.leftovers == []


def test_a_whole_string_range_is_one_candidate():
    proposal = split_text_value("-5 to +100.4 inches of water column")
    assert proposal.grammar == "range"
    assert proposal.candidates == [{"key": None, "value": {"min": -5, "max": 100.4, "unit": "inches of water column"}, "conditions": []}]

    hyphen = split_text_value("0.3-2.5 uL")
    assert hyphen.candidates[0]["value"] == {"min": 0.3, "max": 2.5, "unit": "uL"}


def test_unparseable_text_is_all_leftover():
    proposal = split_text_value("Ceramic, FKM, 316 stainless steel")
    assert proposal.grammar is None
    assert proposal.candidates == []
    assert proposal.leftovers == ["Ceramic, FKM, 316 stainless steel"]


# -- the propose verb ----------------------------------------------------------


def test_propose_inherits_the_key_for_a_uniform_grammar(api: OcmApi, workspace_root: Path):
    source = _claim("x-response_time", RESPONSE_TIME_BLOB)
    _write_file(workspace_root, [source])

    e = api.propose_claim_split(DOC_HASH, source["id"])
    assert e.ok, e.refusals
    assert e.data["grammar"] == "alternates"
    assert all(c["key"] == "x-response_time" for c in e.data["candidates"])


def test_propose_leaves_keys_unassigned_for_heterogeneous_bounds(api: OcmApi, workspace_root: Path):
    source = _claim("output_configuration", CONTROL_OUTPUT_BLOB, subject="OUT1")
    _write_file(workspace_root, [source])

    e = api.propose_claim_split(DOC_HASH, source["id"])
    assert e.ok, e.refusals
    assert e.data["grammar"] == "bounds"
    assert len(e.data["candidates"]) == 6
    assert all(c["key"] is None for c in e.data["candidates"])
    assert "Nothing was written" in e.data["note"]


def test_propose_refuses_a_structured_value(api: OcmApi, workspace_root: Path):
    source = _claim("mass", {"number": 78, "unit": "g"})
    _write_file(workspace_root, [source])

    e = api.propose_claim_split(DOC_HASH, source["id"])
    assert not e.ok
    assert e.refusals[0].code == Codes.OCM_INVALID_ARGUMENT


def test_propose_refuses_an_unknown_claim_id(api: OcmApi, workspace_root: Path):
    _write_file(workspace_root, [_claim("ip_rating", "IP67")])
    e = api.propose_claim_split(DOC_HASH, "sha256:" + "0" * 64)
    assert not e.ok
    assert e.refusals[0].code == Codes.OCM_NOT_FOUND


# -- append_claims -------------------------------------------------------------


def _read_file(workspace_root: Path) -> dict[str, Any]:
    return yaml.safe_load((workspace_root / "claims" / DOC_HASH.removeprefix("sha256:") / "claims.yaml").read_text(encoding="utf-8"))


def test_append_computes_ids_and_never_touches_existing_records(api: OcmApi, workspace_root: Path):
    original = _claim("ip_rating", "IP67")
    _write_file(workspace_root, [original], attestations=[{"vocab_version": "1.0", "date": "2026-09-01"}])

    new = _claim("mass", {"number": 78, "unit": "g"})
    new.pop("id", None)
    e = api.append_claims(DOC_HASH, [new], attestation={"vocab_version": "1.1", "date": "2026-09-02"})
    assert e.ok, e.refusals
    assert e.data["written"] == 1 and e.data["skipped"] == 0 and e.data["claims"] == 2

    doc = _read_file(workspace_root)
    assert doc["claims"][0]["id"] == original["id"]  # untouched
    assert doc["claims"][1]["id"] == e.data["ids"][0]
    assert [a["vocab_version"] for a in doc["attestations"]] == ["1.0", "1.1"]
    assert api.validate_claims(DOC_HASH).ok


def test_append_refuses_a_supplied_id(api: OcmApi, workspace_root: Path):
    _write_file(workspace_root, [_claim("ip_rating", "IP67")])
    new = _claim("mass", {"number": 78, "unit": "g"})
    new["id"] = "sha256:" + "0" * 64

    e = api.append_claims(DOC_HASH, [new])
    assert not e.ok
    assert "never supplied" in e.refusals[0].message


def test_append_refusal_writes_nothing(api: OcmApi, workspace_root: Path):
    _write_file(workspace_root, [_claim("ip_rating", "IP67")])
    before = _read_file(workspace_root)

    bad = _claim("holding_torque", "lots")  # not in the vocabulary, not x-
    bad.pop("id", None)
    e = api.append_claims(DOC_HASH, [bad])
    assert not e.ok
    assert _read_file(workspace_root) == before


def test_append_refuses_a_duplicate_attestation_version(api: OcmApi, workspace_root: Path):
    _write_file(workspace_root, [_claim("ip_rating", "IP67")], attestations=[{"vocab_version": "1.0", "date": "2026-09-01"}])

    e = api.append_claims(DOC_HASH, [], attestation={"vocab_version": "1.0", "date": "2026-09-02"})
    assert not e.ok
    assert any("one pass per vocabulary version" in r.message for r in e.refusals)


def test_append_with_nothing_to_append_refuses(api: OcmApi, workspace_root: Path):
    _write_file(workspace_root, [_claim("ip_rating", "IP67")])
    e = api.append_claims(DOC_HASH, [])
    assert not e.ok
    assert "nothing to append" in e.refusals[0].message
