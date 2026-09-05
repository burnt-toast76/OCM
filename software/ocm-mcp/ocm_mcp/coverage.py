# SPDX-License-Identifier: AGPL-3.0-or-later
"""The coverage queue (ADR-0036 D1 as amended).

When the store cannot answer -- no_documents, absence_not_yet_meaningful
-- the miss is the service's best demand data. request_coverage files
that demand as a GitHub issue labeled `coverage-request` on the public
repository, deduplicated on the normalized (manufacturer, part) key so
repeat requests stack into ranked demand for the operator to triage.

The queue is NOT the registry. Nothing here imports the index, the
workspace, or any claims path; this module can file demand and do
nothing else -- it cannot place, alter, or delete a claim, which is what
keeps D1's founding rationale intact.

Design constraints carried from the operator: source URLs are often
behind vendor logins, so manufacturer + part number is a complete
request (the operator resolves the document); no file or PDF intake
through this tool, ever. The GitHub credential is a fine-grained PAT
scoped to issues on the one target repo, supplied via OCM_COVERAGE_TOKEN
and OCM_COVERAGE_REPO; when either is unset the tool is not registered
at all. A per-caller daily cap (OCM_COVERAGE_DAILY_CAP, default 10,
in-memory) answers over-cap requests with a polite refusal naming the
cap -- good enough until real abuse exists.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .index import normalize

_logger = logging.getLogger("ocm_mcp.coverage")

COVERAGE_TOKEN_ENV = "OCM_COVERAGE_TOKEN"
COVERAGE_REPO_ENV = "OCM_COVERAGE_REPO"
COVERAGE_CAP_ENV = "OCM_COVERAGE_DAILY_CAP"

COVERAGE_LABEL = "coverage-request"
DEFAULT_DAILY_CAP = 10
NOTE_MAX_CHARS = 500

_API = "https://api.github.com"


def coverage_key(manufacturer: str, part_number: str) -> str:
    """The dedup key: case-folded manufacturer, serving-normalized part.
    KEYENCE FS-N41N and a hypothetical other vendor's FS-N41N stay
    distinct; spelling and separator variants of one part collapse."""
    return f"{manufacturer.strip().casefold()}::{normalize(part_number)}"


class GitHubIssues:
    """The three REST calls the queue needs, and nothing else (API
    version 2022-11-28). Tests replace this whole object -- CI never
    talks to GitHub."""

    def __init__(self, repo: str, token: str) -> None:
        self.repo = repo
        self._token = token

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        request = urllib.request.Request(
            f"{_API}{path}",
            method=method,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def list_open(self, label: str) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        page = 1
        while True:
            batch = self._call("GET", f"/repos/{self.repo}/issues?labels={label}&state=open&per_page=100&page={page}")
            issues.extend(batch)
            if len(batch) < 100:
                return issues
            page += 1

    def create(self, title: str, body: str, labels: list[str]) -> dict[str, Any]:
        return self._call("POST", f"/repos/{self.repo}/issues", {"title": title, "body": body, "labels": labels})

    def comment(self, number: int, body: str) -> dict[str, Any]:
        return self._call("POST", f"/repos/{self.repo}/issues/{number}/comments", {"body": body})


@dataclass
class DailyCap:
    """Under static-token auth there is exactly ONE client identity (every
    caller shares the bearer token, and stdio's peer is whoever launched
    the process), so this cap is N per day GLOBAL -- correct for the
    single-operator phase, and deliberately not a per-user quota. When
    per-client identity arrives with OAuth (phase two), `client_id`
    becomes the OAuth client and this same machinery means per-client."""

    cap: int = DEFAULT_DAILY_CAP
    _counts: dict[tuple[str, str], int] = field(default_factory=dict)

    def take(self, client_id: str) -> bool:
        key = (date.today().isoformat(), client_id)
        used = self._counts.get(key, 0)
        if used >= self.cap:
            return False
        self._counts[key] = used + 1
        return True

    def refund(self, client_id: str) -> None:
        """An unavailable queue must not consume the caller's cap: the
        take gates GitHub work, so a failed attempt hands it back."""
        key = (date.today().isoformat(), client_id)
        if self._counts.get(key, 0) > 0:
            self._counts[key] -= 1


def _sanitize(text: str) -> str:
    """Backticks stripped so nothing can escape the fence it is served
    inside -- the note and URL land in a PUBLIC issue body, where raw
    markdown renders and @mentions ping real users through the PAT's
    identity. Fenced code is inert; a fence is only inert if the content
    cannot close it."""
    return text.replace("`", "")


def _context_lines(source_url: str | None, note: str | None, client_id: str) -> str:
    lines = [
        f"source_url: `{_sanitize(source_url)}`" if source_url else "source_url: (operator resolves)",
        f"requested_by: {client_id}",
        f"date: {date.today().isoformat()}",
    ]
    if note:
        lines += ["", "note:", "```text", _sanitize(note), "```"]
    else:
        lines.append("note: (none)")
    return "\n".join(lines)


_UNAVAILABLE_REASON = (
    "the coverage queue is temporarily unreachable; the store itself is "
    "unaffected -- please try again later."
)


@dataclass
class CoverageQueue:
    repo: str
    client: GitHubIssues
    limiter: DailyCap

    def request(
        self,
        manufacturer: str,
        part_number: str,
        source_url: str | None = None,
        note: str | None = None,
        client_id: str = "ocm-operator",
    ) -> dict[str, Any]:
        if not manufacturer.strip() or not part_number.strip():
            return {"status": "refused", "reason": "manufacturer and part_number are both required."}
        if note is not None and len(note) > NOTE_MAX_CHARS:
            return {"status": "refused", "reason": f"note is limited to {NOTE_MAX_CHARS} characters ({len(note)} given)."}
        # Global under static-token auth (one client identity) -- see
        # DailyCap. The take gates the GitHub calls; an unavailable
        # outcome below refunds it, so the queue's failure never burns
        # the caller's cap.
        if not self.limiter.take(client_id):
            return {
                "status": "refused",
                "reason": (
                    f"daily coverage-request cap reached ({self.limiter.cap} per day). "
                    "The queue is worked by a human; please try again tomorrow."
                ),
            }

        key = coverage_key(manufacturer, part_number)
        try:
            # The template's `key:` line is the dedup anchor -- exact-match
            # against issue bodies, no free-text guessing. It stays a bare
            # template line (never fenced or backticked) so this search
            # matches the bodies the template produces.
            for issue in self.client.list_open(COVERAGE_LABEL):
                if f"key: {key}" in (issue.get("body") or ""):
                    self.client.comment(
                        issue["number"],
                        "Another request for this coverage.\n\n" + _context_lines(source_url, note, client_id),
                    )
                    return {
                        "status": "already_queued",
                        "issue_url": issue.get("html_url"),
                        "detail": "This part was already requested; your context was added to the existing issue.",
                    }

            body = "\n".join(
                [
                    f"manufacturer: {manufacturer.strip()}",
                    f"part_number: {part_number.strip()}",
                    f"key: {key}",
                    _context_lines(source_url, note, client_id),
                    "",
                    "_Filed by request_coverage (ADR-0036 D1 as amended). This queue feeds the",
                    "human-supervised ingestion pipeline; it never writes the registry._",
                ]
            )
            issue = self.client.create(
                title=f"Coverage request: {manufacturer.strip()} {part_number.strip()}",
                body=body,
                labels=[COVERAGE_LABEL],
            )
            return {"status": "queued", "issue_url": issue.get("html_url")}
        except urllib.error.HTTPError as error:
            # Diagnosis lives in the server log; the caller gets a polite
            # refusal with no status code, exception text, or repo name.
            self.limiter.refund(client_id)
            _logger.warning("coverage queue: GitHub answered HTTP %s (%s)", error.code, error.reason)
            return {"status": "unavailable", "reason": _UNAVAILABLE_REASON}
        except (urllib.error.URLError, TimeoutError) as error:
            self.limiter.refund(client_id)
            _logger.warning("coverage queue: GitHub unreachable (%s: %s)", type(error).__name__, error)
            return {"status": "unavailable", "reason": _UNAVAILABLE_REASON}


def coverage_from_env(env: dict[str, str] | None = None) -> CoverageQueue | None:
    """The gate: both variables or no tool. Never a partial mode."""
    env = os.environ if env is None else env  # type: ignore[assignment]
    token = env.get(COVERAGE_TOKEN_ENV, "").strip()
    repo = env.get(COVERAGE_REPO_ENV, "").strip()
    if not token or not repo:
        return None
    cap_text = env.get(COVERAGE_CAP_ENV, "").strip()
    cap = int(cap_text) if cap_text else DEFAULT_DAILY_CAP
    return CoverageQueue(repo=repo, client=GitHubIssues(repo, token), limiter=DailyCap(cap=cap))
