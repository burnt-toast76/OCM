# SPDX-License-Identifier: AGPL-3.0-or-later
"""report_claim (ADR-0037 D3). The GitHub client is mocked throughout --
CI never talks to GitHub -- and the structural guarantee is tested
alongside the behavior: the queue can file a dispute and do nothing
else, and no tool writes a retraction."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ocm_mcp.coverage import CoverageQueue, DailyCap
from ocm_mcp.reports import REPORT_LABEL, ReportQueue, reports_from_queue
from ocm_mcp.server import create_server

from test_coverage import FakeIssues  # rootdir import: this tests/ dir is not a package

REPO_ROOT = Path(__file__).resolve().parents[3]

# The eps25 fixture's ip_rating records (ADR-0037 golden retraction
# content): the live, correct IP67 claim, and the retracted IP65 misread
# it supersedes.
LIVE_ID = "sha256:8d63dafd7d0573a0f5d6aec5c84f0acf3e0015c366613e9814cb1d7f4a38b47b"
RETRACTED_ID = "sha256:e74d4f8bb8ed70e438d4670372570816c27f5b49d8b2ce8dd2ffe7e1cf8577fc"
EPS25 = "sha256:bc8792ff216e076f31c1d92d74a2bcc046a316231049ecf838e251c98bb0b662"


def _queue(existing=None, cap=10) -> tuple[ReportQueue, FakeIssues]:
    fake = FakeIssues(existing)
    return ReportQueue(repo="example/ocm", client=fake, limiter=DailyCap(cap=cap)), fake


def _serve(queue: ReportQueue):
    return create_server(REPO_ROOT, reports=queue)


def _call(server, **arguments: Any) -> dict[str, Any]:
    _content, structured = asyncio.run(server.call_tool("report_claim", arguments))
    return structured


# -- the queue itself ----------------------------------------------------------


def test_filing_creates_a_labeled_templated_issue():
    queue, fake = _queue()
    result = queue.report(
        LIVE_ID, "the page prints IP67, the served value says IP68",
        expected_value="IP67",
        key="ip_rating", document=EPS25, location="page 1, overview, row 'Protection rating'",
    )

    assert result["status"] == "queued"
    assert result["issue_url"].startswith("https://github.com/")
    (issue,) = fake.issues
    assert REPORT_LABEL in issue["labels"]
    assert f"claim: {LIVE_ID}" in issue["body"]
    assert "key: ip_rating" in issue["body"]
    assert f"document: {EPS25}" in issue["body"]
    assert "location: page 1, overview, row 'Protection rating'" in issue["body"]
    assert "reason:\n```text\nthe page prints IP67" in issue["body"]
    assert "expected_value:\n```text\nIP67\n```" in issue["body"]
    # The triage line rides on every issue: the reporter learns the
    # transcription-vs-misprint asymmetry without having read ADR-0037.
    assert "MISPRINT is not retracted" in issue["body"]
    assert "no tool ever writes a retraction" in issue["body"]


def test_dedup_round_trips_against_a_body_the_template_produced():
    queue, fake = _queue()
    first = queue.report(LIVE_ID, "original report", key="ip_rating", document=EPS25)
    assert first["status"] == "queued"

    result = queue.report(LIVE_ID, "second report, same claim", key="ip_rating", document=EPS25)

    assert result["status"] == "already_queued"
    assert result["issue_url"] == first["issue_url"]
    assert len(fake.issues) == 1  # no second issue
    (number, body) = fake.comments[0]
    assert number == fake.issues[0]["number"] and "second report, same claim" in body


def test_hostile_free_text_is_fenced_and_inert():
    queue, fake = _queue()
    hostile = "@octocat look **NOW** ``` \n@ghost <img src=x>"
    result = queue.report(LIVE_ID, hostile, expected_value="`42 V`", note=hostile, key="ip_rating")
    assert result["status"] == "queued"

    body = fake.issues[0]["body"]
    # Backticks inside every free-text field are stripped, so nothing can
    # close its own fence; mentions and markdown survive as text only
    # inside fences.
    assert "`42 V`" not in body and "42 V" in body
    for start in ("reason:\n```text\n", "note:\n```text\n"):
        fenced = body[body.index(start) + len(start): body.index("\n```", body.index(start) + len(start))]
        assert "@octocat" in fenced and "`" not in fenced
    head = body[: body.index("reason:")]
    assert "@octocat" not in head and "@ghost" not in head


def test_unavailable_github_refuses_politely_and_refunds_the_cap(caplog):
    import urllib.error

    class Exploding(FakeIssues):
        def list_open(self, label):
            raise urllib.error.HTTPError("https://api.github.com/x", 503, "Service Unavailable", None, None)

    limiter = DailyCap(cap=1)
    queue = ReportQueue(repo="example/ocm", client=Exploding(), limiter=limiter)
    with caplog.at_level("WARNING", logger="ocm_mcp.reports"):
        result = queue.report(LIVE_ID, "looks wrong")

    assert result["status"] == "unavailable"
    assert "temporarily unreachable" in result["reason"]
    assert "503" not in result["reason"] and "example/ocm" not in result["reason"]
    assert any("claim-report queue" in record.message for record in caplog.records)

    # The cap was refunded: with cap=1, a working client still succeeds.
    queue.client = FakeIssues()
    assert queue.report(LIVE_ID, "looks wrong")["status"] == "queued"


def test_the_daily_cap_is_shared_with_the_coverage_queue():
    # One limiter, wired by the server across both intake tools: one
    # client identity, one queue repo, one daily budget.
    fake = FakeIssues()
    limiter = DailyCap(cap=1)
    coverage = CoverageQueue(repo="example/ocm", client=fake, limiter=limiter)
    reports = reports_from_queue(coverage)
    assert reports is not None and reports.limiter is limiter and reports.client is fake

    assert coverage.request("A", "P-1")["status"] == "queued"
    refused = reports.report(LIVE_ID, "looks wrong")
    assert refused["status"] == "refused" and "shared with coverage" in refused["reason"]


def test_free_text_over_the_cap_is_refused():
    queue, fake = _queue()
    for field in ("reason", "expected_value", "note"):
        arguments = {"reason": "x"} | {field: "x" * 501}
        result = queue.report(LIVE_ID, **arguments)
        assert result["status"] == "refused" and "500" in result["reason"], field
    assert fake.issues == []


# -- the server wrapper: precision gate, story, registration -------------------


def test_an_unknown_claim_id_is_politely_refused_and_files_nothing():
    queue, fake = _queue()
    result = _call(_serve(queue), claim_id="sha256:" + "0" * 64, reason="looks wrong")
    assert result["status"] == "refused"
    assert "served value" in result["reason"]
    assert fake.issues == [] and fake.comments == []


def test_a_served_claim_id_files_with_its_index_context():
    queue, fake = _queue()
    result = _call(_serve(queue), claim_id=LIVE_ID, reason="the page prints IP67")
    assert result["status"] == "queued"
    (issue,) = fake.issues
    assert f"claim: {LIVE_ID}" in issue["body"]
    assert "key: ip_rating" in issue["body"]
    assert f"document: {EPS25}" in issue["body"]
    assert "location: page 1, overview, row 'Protection rating'" in issue["body"]


def test_a_report_on_a_retracted_claim_gets_the_story_not_an_issue():
    # The dispute is already settled: the reporter learns the retraction
    # reason and where to go, and the operator's queue stays clean.
    queue, fake = _queue()
    result = _call(_serve(queue), claim_id=RETRACTED_ID, reason="IP65 looks wrong")
    assert result["status"] == "already_retracted"
    assert "IP67" in result["reason"]  # the retraction's own reason
    assert result["superseded_by"] == LIVE_ID
    assert fake.issues == [] and fake.comments == []


def test_tool_absent_without_env_and_gated_with_coverage(monkeypatch):
    monkeypatch.delenv("OCM_COVERAGE_TOKEN", raising=False)
    monkeypatch.delenv("OCM_COVERAGE_REPO", raising=False)

    bare = create_server(REPO_ROOT)
    assert sorted(t.name for t in asyncio.run(bare.list_tools())) == ["get_claims", "get_document", "search_parts"]

    # One gate: configuring the coverage queue brings BOTH intake tools.
    coverage = CoverageQueue(repo="example/ocm", client=FakeIssues(), limiter=DailyCap(cap=10))
    armed = create_server(REPO_ROOT, coverage=coverage)
    assert sorted(t.name for t in asyncio.run(armed.list_tools())) == [
        "get_claims", "get_document", "report_claim", "request_coverage", "search_parts",
    ]


def test_the_queue_touches_no_registry_path():
    # Structural: reports.py can file a dispute and do nothing else. The
    # unknown-id check lives in the server wrapper, where the read-only
    # index already is -- so this module needs no registry import at all,
    # which is what keeps "no tool writes a retraction" checkable.
    import ocm_mcp.reports as reports_module

    source = Path(reports_module.__file__).read_text(encoding="utf-8")
    for forbidden in ("build_index", "ServingIndex", "from ocm_api", "claims_path", "read_yaml", "write_yaml", "retractions"):
        assert forbidden not in source, f"reports.py must not reference {forbidden}"
    # And behaviorally: a full report cycle runs with no filesystem root.
    queue, _ = _queue()
    assert queue.report(LIVE_ID, "looks wrong")["status"] == "queued"
