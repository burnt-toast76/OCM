# SPDX-License-Identifier: AGPL-3.0-or-later
"""Executes every golden query in evals/golden-queries.yaml against the
real serving implementation over the real committed registry (ADR-0036;
ADR-0035 D6's admission rule applied to serving). The server does not
ship until all of these pass -- and the envelope invariants (provenance
on every value, vocab_version and serving_state present) are asserted on
EVERY response, not just where an eval mentions them."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from ocm_mcp import build_index, get_claims, get_document, search_parts

REPO_ROOT = Path(__file__).resolve().parents[3]
EVALS = yaml.safe_load((REPO_ROOT / "software" / "ocm-mcp" / "evals" / "golden-queries.yaml").read_text(encoding="utf-8"))

_TOOLS = {"get_claims": get_claims, "search_parts": search_parts, "get_document": get_document}


@pytest.fixture(scope="session")
def index():
    return build_index(REPO_ROOT)


def _assert_envelope_invariants(response: dict[str, Any]) -> None:
    assert response.get("vocab_version"), "every envelope names its vocab version"
    assert response.get("serving_state"), "every envelope names the serving state"
    # D8 as amended: the corpus state is always PRESENT, null when no
    # corpus is configured -- a missing field would leave the consumer to
    # infer which registry answered.
    assert "corpus_state" in response, "every envelope names the corpus state, null when unconfigured"
    for record in response.get("claims", []):
        assert record.get("id", "").startswith("sha256:"), "no bare values: claim id required"
        citation = record.get("citation", {})
        assert citation.get("document", "").startswith("sha256:"), "citation carries the document hash inline"
        assert citation.get("page") and citation.get("locator"), "citation carries page and locator"


def _count_ok(expected, actual: int) -> bool:
    if isinstance(expected, dict):
        return actual >= int(expected["value"]) if expected.get("minimum") else actual == int(expected["value"])
    return actual == int(expected)


@pytest.mark.parametrize("eval_case", EVALS["evals"], ids=[e["name"] for e in EVALS["evals"]])
def test_golden(eval_case: dict[str, Any], index) -> None:
    response = _TOOLS[eval_case["tool"]](index, **eval_case["args"])
    _assert_envelope_invariants(response)

    expect = eval_case["expect"]
    served_ids = [c["id"] for c in response.get("claims", [])]
    results = [r["identifier"] for r in response.get("results", [])]

    for field, expected in expect.items():
        if field in ("matched_via", "resolved_part", "mode", "absence_state", "attestation_status", "bytes_served"):
            assert response.get(field) == expected, f"{field}: {response.get(field)!r} != {expected!r}"
        elif field == "claim_count":
            assert _count_ok(expected, response.get("claim_count", 0)), f"claim_count {response.get('claim_count')} vs {expected}"
        elif field == "claim_ids":
            assert set(served_ids) == set(expected)
        elif field == "claim_ids_include":
            assert set(expected) <= set(served_ids)
        elif field == "claim_ids_exclude":
            assert not set(expected) & set(served_ids)
        elif field == "served_keys_include":
            assert set(expected) <= {c["key"] for c in response.get("claims", [])}
        elif field == "bound_via_all":
            assert all(c.get("bound_via") == expected for c in response.get("claims", [])), "every served record binds"
        elif field == "summary_keys_include":
            for key, minimum in expected.items():
                assert response["summary"][key]["count"] >= int(minimum), f"summary[{key}]"
        elif field == "documents_consulted":
            assert sorted(response.get("documents_consulted", [])) == sorted(expected)
        elif field == "results_include":
            assert set(expected) <= set(results), f"missing from search: {set(expected) - set(results)}"
        elif field == "results_exclude":
            assert not set(expected) & set(results)
        elif field in ("manufacturer", "type"):
            assert response["record"].get(field) == expected
        elif field == "attestations":
            assert response.get("attestations") == expected
        else:
            raise AssertionError(f"eval {eval_case['name']!r} uses unknown expectation field {field!r}")
