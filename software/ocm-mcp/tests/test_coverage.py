# SPDX-License-Identifier: AGPL-3.0-or-later
"""request_coverage (ADR-0036 D1 as amended). The GitHub client is
mocked throughout -- CI never talks to GitHub -- and the structural
guarantee is tested alongside the behavior: the queue can file demand
and do nothing else."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ocm_mcp.coverage import (
    COVERAGE_LABEL,
    CoverageQueue,
    DailyCap,
    coverage_from_env,
    coverage_key,
)
from ocm_mcp.server import create_server

REPO_ROOT = Path(__file__).resolve().parents[3]


class FakeIssues:
    """The three-call surface, in memory."""

    def __init__(self, existing: list[dict[str, Any]] | None = None) -> None:
        self.issues = list(existing or [])
        self.comments: list[tuple[int, str]] = []
        self._next = 100

    def list_open(self, label: str) -> list[dict[str, Any]]:
        return [i for i in self.issues if label in i["labels"]]

    def create(self, title: str, body: str, labels: list[str]) -> dict[str, Any]:
        issue = {
            "number": self._next,
            "title": title,
            "body": body,
            "labels": labels,
            "html_url": f"https://github.com/example/ocm/issues/{self._next}",
        }
        self._next += 1
        self.issues.append(issue)
        return issue

    def comment(self, number: int, body: str) -> dict[str, Any]:
        self.comments.append((number, body))
        return {"id": len(self.comments)}


def _queue(existing=None, cap=10) -> tuple[CoverageQueue, FakeIssues]:
    fake = FakeIssues(existing)
    return CoverageQueue(repo="example/ocm", client=fake, limiter=DailyCap(cap=cap)), fake


def test_filing_creates_a_labeled_templated_issue():
    queue, fake = _queue()
    result = queue.request("KEYENCE", "LR-ZB250CN", note="needed for a module draft")

    assert result["status"] == "queued"
    assert result["issue_url"].startswith("https://github.com/")
    (issue,) = fake.issues
    assert COVERAGE_LABEL in issue["labels"]
    assert "manufacturer: KEYENCE" in issue["body"]
    assert f"key: {coverage_key('KEYENCE', 'LR-ZB250CN')}" in issue["body"]
    assert "source_url: (operator resolves)" in issue["body"]  # URL optional by design
    assert "note: needed for a module draft" in issue["body"]


def test_dedup_comments_on_the_existing_issue_and_returns_its_url():
    key = coverage_key("KEYENCE", "LR-ZB250CN")
    existing = [{
        "number": 7,
        "body": f"manufacturer: KEYENCE\npart_number: LR-ZB250CN\nkey: {key}\n",
        "labels": [COVERAGE_LABEL],
        "html_url": "https://github.com/example/ocm/issues/7",
    }]
    queue, fake = _queue(existing)
    # Spelling variants collapse onto the same key -- that is the point.
    result = queue.request("keyence", "lr zb250cn", source_url="https://example.test/doc.pdf")

    assert result["status"] == "already_queued"
    assert result["issue_url"] == "https://github.com/example/ocm/issues/7"
    assert len(fake.issues) == 1  # no second issue
    (number, body) = fake.comments[0]
    assert number == 7 and "https://example.test/doc.pdf" in body


def test_rate_limit_refuses_politely_naming_the_cap():
    queue, fake = _queue(cap=2)
    assert queue.request("A", "P-1")["status"] == "queued"
    assert queue.request("A", "P-2")["status"] == "queued"
    third = queue.request("A", "P-3")
    assert third["status"] == "refused"
    assert "2 per day" in third["reason"]
    assert len(fake.issues) == 2  # the refused request filed nothing


def test_note_over_500_chars_is_refused():
    queue, fake = _queue()
    result = queue.request("A", "P-1", note="x" * 501)
    assert result["status"] == "refused" and "500" in result["reason"]
    assert fake.issues == []


def test_tool_absent_without_env_and_present_with_injected_queue(monkeypatch):
    monkeypatch.delenv("OCM_COVERAGE_TOKEN", raising=False)
    monkeypatch.delenv("OCM_COVERAGE_REPO", raising=False)

    bare = create_server(REPO_ROOT)
    assert sorted(t.name for t in asyncio.run(bare.list_tools())) == ["get_claims", "get_document", "search_parts"]

    queue, _ = _queue()
    armed = create_server(REPO_ROOT, coverage=queue)
    assert sorted(t.name for t in asyncio.run(armed.list_tools())) == [
        "get_claims", "get_document", "request_coverage", "search_parts",
    ]


def test_env_gate_needs_both_variables():
    assert coverage_from_env({}) is None
    assert coverage_from_env({"OCM_COVERAGE_TOKEN": "t" * 40}) is None
    assert coverage_from_env({"OCM_COVERAGE_REPO": "o/r"}) is None
    queue = coverage_from_env({"OCM_COVERAGE_TOKEN": "t" * 40, "OCM_COVERAGE_REPO": "o/r", "OCM_COVERAGE_DAILY_CAP": "3"})
    assert queue is not None and queue.repo == "o/r" and queue.limiter.cap == 3


def test_the_queue_touches_no_registry_path():
    # Structural: the coverage module can file demand and do nothing else.
    # It has no import path to the index, the workspace, or any claims
    # root -- which is what keeps D1's founding rationale intact.
    import ocm_mcp.coverage as coverage_module

    source = Path(coverage_module.__file__).read_text(encoding="utf-8")
    for forbidden in ("build_index", "ServingIndex", "from ocm_api", "claims_path", "read_yaml", "write_yaml"):
        assert forbidden not in source, f"coverage.py must not reference {forbidden}"
    # And behaviorally: a full request cycle runs with no filesystem root at all.
    queue, _ = _queue()
    assert queue.request("A", "P-1")["status"] == "queued"
