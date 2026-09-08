# SPDX-License-Identifier: AGPL-3.0-or-later
"""Manufacturer lookup and multi-token search (ADR-0036 D9).

Everything here runs against the reference fixtures, so a contributor
with no corpus checkout gets the same coverage CI does. The behaviors
that only real-document scale can exercise -- a vendor whose part list
would exhaust the 50-result cap, and two printed spellings folding onto
one canonical name -- live in the corpus repository's own suite, beside
the documents that produce them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ocm_mcp import build_index, search_parts
from ocm_mcp.index import _load_manufacturers

REPO_ROOT = Path(__file__).resolve().parents[3]


def _identifiers(response, kind: str) -> set[str]:
    return {r["identifier"] for r in response["results"] if r["kind"] == kind}


def test_manufacturer_query_returns_families_not_the_part_list(shared_index):
    # The reported gap: a manufacturer name matched nothing, because
    # manufacturer lives on the document record and never reached the
    # index. It now resolves, and it answers with the families the agent
    # can hand straight back to get_claims (D9).
    # "Automation", not "Example Automation": both fixture manufacturers
    # share the "Example" token, and an OR'd substring match returns both
    # -- correctly, which is what test_multi_token_query relies on.
    response = search_parts(shared_index, "Automation")
    assert _identifiers(response, "manufacturer") == {"Example Automation"}
    assert "EPS25 series" in _identifiers(response, "family")
    # The family's members are reachable THROUGH the family, so they are
    # not spent as individual rows.
    assert _identifiers(response, "part") == set()


def test_manufacturer_with_no_family_still_names_its_parts(shared_index):
    # Families-not-parts must not become families-or-nothing: a document
    # stating no family designation would otherwise make its part
    # unreachable from a manufacturer query.
    response = search_parts(shared_index, "Dispensing")
    assert _identifiers(response, "manufacturer") == {"Example Dispensing"}
    assert _identifiers(response, "family") == set()
    assert "DP-8" in _identifiers(response, "part")


def test_multi_token_query_returns_matches_for_each_token(shared_index):
    # "EPS25 DP-8" is one question with two subjects. Treating the whole
    # string as a single identifier matched nothing, which read as "the
    # store has neither" (D9).
    response = search_parts(shared_index, "EPS25 DP-8")
    identifiers = {r["identifier"] for r in response["results"]}
    assert "EPS25 series" in identifiers, "the first token's family"
    assert "DP-8" in identifiers, "the second token's part"


def test_a_token_that_matches_nothing_does_not_suppress_the_others(shared_index):
    # OR, not AND: an agent guessing three candidates gets the ones that
    # exist, not silence because one guess was wrong.
    response = search_parts(shared_index, "ZZ-NOTHING DP-8")
    assert "DP-8" in {r["identifier"] for r in response["results"]}


def test_every_result_carries_its_manufacturer(shared_index):
    response = search_parts(shared_index, "EPS25")
    assert response["results"], "the fixture family matches"
    for result in response["results"]:
        assert result["manufacturer"] == "Example Automation"
    # And a part result specifically, which is the case an agent reads
    # when choosing between two vendors' similar numbers.
    parts = [r for r in response["results"] if r["kind"] == "part"]
    assert parts and all(r["manufacturer"] == "Example Automation" for r in parts)


def test_unknown_manufacturer_returns_an_empty_result(shared_index):
    response = search_parts(shared_index, "Acme Widgets")
    assert response["results"] == []
    assert response["truncated"] is False
    # Empty is the honest answer HERE: search is approximate lookup, not
    # a claim query, so it has no absence state to report (D3 governs
    # get_claims). The envelope still names both states.
    assert "absence_state" not in response
    assert response["serving_state"] and "corpus_state" in response


def test_search_covers_manufacturer_but_never_claim_text(shared_index):
    # D1's boundary, restated as a test because D9 widened the scope
    # around it: identifiers yes, transcribed values no.
    response = search_parts(shared_index, "24")  # a supply_voltage value in the fixtures
    assert _identifiers(response, "manufacturer") == set()
    for result in response["results"]:
        assert result["kind"] in ("part", "family")


def test_canonical_name_is_served_not_the_printed_spelling(shared_index):
    # The list merges spellings for search; get_document keeps serving
    # what the record says. Both fixtures are listed under a canonical
    # name that drops the "(synthetic)" suffix their records carry.
    entry = shared_index.manufacturers["Example Automation"]
    assert entry.spellings == ["Example Automation (synthetic)"]
    document = next(iter(entry.documents))
    assert shared_index.documents[document].record["manufacturer"] == "Example Automation (synthetic)"


def test_an_unlisted_manufacturer_is_its_own_canonical_name(tmp_path):
    # The list merges spellings; it never grants visibility. A document
    # from a manufacturer the list has not caught up with must still be
    # searchable, or the list becomes an ingestion gate by the back door.
    listed = _load_manufacturers(REPO_ROOT)
    assert "Example Automation" in listed, "the fixture manufacturers are listed"

    index = build_index(REPO_ROOT)
    index.manufacturers["Novel Sensors GmbH"] = type(index.manufacturers["Example Automation"])(
        canonical="Novel Sensors GmbH", spellings=["Novel Sensors GmbH"]
    )
    index.manufacturer_names["novelsensorsgmbh"] = "Novel Sensors GmbH"
    response = search_parts(index, "Novel Sensors")
    assert _identifiers(response, "manufacturer") == {"Novel Sensors GmbH"}


def test_a_missing_manufacturer_list_costs_merging_and_nothing_else(tmp_path):
    assert _load_manufacturers(tmp_path) == {}


@pytest.mark.parametrize("query", ["", "   ", "\t\n"])
def test_an_empty_query_matches_nothing(shared_index, query):
    # Not everything: a bare "" is a substring of every identifier, so
    # the old single-token matcher would have returned the whole registry
    # truncated at 50. Tokenizing removes the empty token instead.
    assert search_parts(shared_index, query)["results"] == []
