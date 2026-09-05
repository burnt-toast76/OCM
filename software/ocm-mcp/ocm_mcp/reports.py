# SPDX-License-Identifier: AGPL-3.0-or-later
"""The claim-report queue (ADR-0037 D3).

The party most likely to notice a transcription error is a consumer
holding the document, and report_claim is their channel: a dispute about
one served value, filed as a GitHub issue labeled `claim-report` on the
same repository, with the same credentials, as the coverage queue
(ADR-0036 D1 as amended). Reports are deduplicated on the claim id --
served values carry their ids, so a report is precise by construction --
and repeat reports stack onto one issue as the operator's triage
ranking.

Like the coverage queue, this queue is NOT the registry, and it is one
step further removed: no tool ever writes a retraction (ADR-0037 D3) --
a retraction is the operator's judgment that our record contradicts its
source, made after reading the document, in a supervised session. This
module can file a dispute and do nothing else; it imports no index,
workspace, or claims path. The unknown-id refusal lives in the server's
tool wrapper, where the read-only serving index already is -- keeping
this module registry-free stays checkable.

Every coverage hardening applies unchanged: free text (reason,
expected_value, note) is fenced with backticks stripped before it lands
in a public issue body, the shared daily cap gates the GitHub calls and
is refunded when GitHub is unreachable, and the polite unavailable
answer leaks nothing. The cap is SHARED with request_coverage -- one
limiter across both tools, because under static-token auth they are one
client identity filing into one queue repo.
"""

from __future__ import annotations

import logging
import urllib.error
from dataclasses import dataclass
from datetime import date
from typing import Any

from .coverage import NOTE_MAX_CHARS, DailyCap, GitHubIssues, _sanitize

_logger = logging.getLogger("ocm_mcp.reports")

REPORT_LABEL = "claim-report"

_UNAVAILABLE_REASON = (
    "the claim-report queue is temporarily unreachable; the store itself is "
    "unaffected -- please try again later."
)

# The triage line every issue carries, so the reporter's expectation
# matches ADR-0037 D1 without them having read it.
_TRIAGE_FOOTER = (
    "_Filed by report_claim (ADR-0037 D3). Triage: a TRANSCRIPTION error is\n"
    "retracted and replaced; a manufacturer MISPRINT is not retracted -- the\n"
    "erratum ingests as a new document (ADR-0035 D5). Either way a valid report\n"
    "resolves visibly in the store's history. This queue never writes the\n"
    "registry, and no tool ever writes a retraction._"
)


def _fenced(label: str, text: str | None) -> list[str]:
    """A free-text field as inert, fenced lines -- or its honest absence."""
    if not text:
        return [f"{label}: (none)"]
    return ["", f"{label}:", "```text", _sanitize(text), "```"]


@dataclass
class ReportQueue:
    repo: str
    client: GitHubIssues
    limiter: DailyCap

    def report(
        self,
        claim_id: str,
        reason: str,
        expected_value: str | None = None,
        note: str | None = None,
        *,
        key: str = "",
        document: str = "",
        location: str = "",
        client_id: str = "ocm-operator",
    ) -> dict[str, Any]:
        """File one dispute. The caller (the server's tool wrapper) has
        already resolved claim_id against the serving index -- key,
        document, and location arrive as read-only context strings, so
        the operator can triage from the issue alone."""
        if not reason.strip():
            return {"status": "refused", "reason": "a report needs a reason -- what does the cited page actually say?"}
        for label, text in (("reason", reason), ("expected_value", expected_value), ("note", note)):
            if text is not None and len(text) > NOTE_MAX_CHARS:
                return {"status": "refused", "reason": f"{label} is limited to {NOTE_MAX_CHARS} characters ({len(text)} given)."}
        # SHARED with request_coverage (one limiter instance, wired by the
        # server): one client identity, one queue repo, one daily budget.
        if not self.limiter.take(client_id):
            return {
                "status": "refused",
                "reason": (
                    f"daily queue cap reached ({self.limiter.cap} per day, shared with coverage requests). "
                    "The queue is worked by a human; please try again tomorrow."
                ),
            }

        context = "\n".join(
            [
                f"requested_by: {client_id}",
                f"date: {date.today().isoformat()}",
                *_fenced("reason", reason),
                *_fenced("expected_value", expected_value),
                *_fenced("note", note),
            ]
        )
        try:
            # `claim:` is the dedup anchor -- a bare template line holding
            # a content-hash id, exact-matched against issue bodies.
            for issue in self.client.list_open(REPORT_LABEL):
                if f"claim: {claim_id}" in (issue.get("body") or ""):
                    self.client.comment(issue["number"], "Another report for this claim.\n\n" + context)
                    return {
                        "status": "already_queued",
                        "issue_url": issue.get("html_url"),
                        "detail": "This claim was already reported; your report was added to the existing issue.",
                    }

            body = "\n".join(
                [
                    f"claim: {claim_id}",
                    f"key: {key}",
                    f"document: {document}",
                    f"location: {location}",
                    context,
                    "",
                    _TRIAGE_FOOTER,
                ]
            )
            issue = self.client.create(
                title=f"Claim report: {key} ({claim_id.removeprefix('sha256:')[:12]})",
                body=body,
                labels=[REPORT_LABEL],
            )
            return {"status": "queued", "issue_url": issue.get("html_url")}
        except urllib.error.HTTPError as error:
            # Diagnosis to the server log; the caller learns nothing but
            # "later", and keeps the cap they spent on nothing.
            self.limiter.refund(client_id)
            _logger.warning("claim-report queue: GitHub answered HTTP %s (%s)", error.code, error.reason)
            return {"status": "unavailable", "reason": _UNAVAILABLE_REASON}
        except (urllib.error.URLError, TimeoutError) as error:
            self.limiter.refund(client_id)
            _logger.warning("claim-report queue: GitHub unreachable (%s: %s)", type(error).__name__, error)
            return {"status": "unavailable", "reason": _UNAVAILABLE_REASON}


def reports_from_queue(coverage: Any) -> ReportQueue | None:
    """One gate for both intake tools: the report queue exists exactly
    when the coverage queue does (same repo, same PAT), and SHARES its
    client and limiter -- one identity, one daily budget."""
    if coverage is None:
        return None
    return ReportQueue(repo=coverage.repo, client=coverage.client, limiter=coverage.limiter)
