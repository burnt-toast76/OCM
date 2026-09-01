# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic blob-splitting proposals (ADR-0035 D1/D6).

A text value stuffed with several statements is several claims wearing
one record. This module PROPOSES the split; it never writes. Automated
extraction is admitted only against golden fixtures (D6), so the parser
is pure regex over the micro-grammars datasheets actually use -- its
output is testable byte-for-byte against splits a human already
approved -- and everything it cannot parse is returned as leftover
text, never dropped.

Grammars, tried in order:

- alternates:  ``23 µs (S-HSPD) /50 µs (HSPD) /...`` -- a slash-
  separated list of number-unit pairs, each optionally qualified in
  parentheses. One candidate per alternate; the qualifier becomes its
  condition. Uniform lists like this legitimately inherit the source
  claim's key.
- bounds scan: ``30 V or less 100 mA or less per output (...)`` --
  every top-level ``<number> <unit> or less/more`` becomes a candidate
  ({max}/{min}); the text between one bound and the next supplies its
  conditions (parenthesized groups and trailing qualifiers), and a
  chunk ending in ':' is a label for what FOLLOWS, so it is leftover,
  not a condition. Heterogeneous statements like these need per-
  candidate vocabulary keys no parser may assign: key stays None.
- range: ``10 to 30 VDC`` / ``0.3-2.5 uL`` as the whole value -- one
  {min, max} candidate.

Key assignment is the boundary: choosing a vocabulary key is design
judgment (the FS-N41N control-output split created three NEW keys), so
candidates carry ``key: None`` unless the grammar makes inheritance
safe, and ``append_claims`` refuses a keyless record.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_NUMBER = r"[+-]?\d+(?:\.\d+)?"
_UNIT = r"[a-zA-Zµ°%]+"
_ALTERNATE = re.compile(rf"^\s*({_NUMBER})\s*({_UNIT})\s*(?:\((.+)\))?\s*$")
_BOUND = re.compile(rf"({_NUMBER})\s*({_UNIT})\s+or\s+(less|more)\b")
_RANGE = re.compile(rf"^\s*({_NUMBER})\s*(?:to|-)\s*({_NUMBER})\s+(.+?)\s*$")


@dataclass
class SplitProposal:
    grammar: str | None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    leftovers: list[str] = field(default_factory=list)


def _num(text: str) -> int | float:
    value = float(text)
    return int(value) if value.is_integer() and "." not in text else value


def _clean(chunk: str) -> str:
    return chunk.strip().strip("/.,;").strip()


def _top_level_paren_spans(text: str) -> list[tuple[int, int]]:
    spans, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
            if depth == 0:
                spans.append((start, i + 1))
    return spans


def _try_alternates(text: str) -> SplitProposal | None:
    segments = text.split("/")
    if len(segments) < 2:
        return None
    parsed = [_ALTERNATE.match(segment) for segment in segments]
    if not all(parsed):
        return None
    proposal = SplitProposal(grammar="alternates")
    for m in parsed:
        number, unit, qualifier = m.group(1), m.group(2), m.group(3)
        proposal.candidates.append(
            {
                "key": None,
                "value": {"unqualified": _num(number), "unit": unit},
                "conditions": [qualifier.strip()] if qualifier else [],
            }
        )
    return proposal


def _gap_tokens(gap: str) -> tuple[list[str], list[str]]:
    """Split one inter-bound gap into (conditions, leftovers), walking
    left to right so a qualifier printed before its parenthetical keeps
    that order in the condition list."""
    conditions: list[str] = []
    leftovers: list[str] = []
    cursor = 0
    for start, end in _top_level_paren_spans(gap):
        chunk = _clean(gap[cursor:start])
        if chunk:
            (leftovers if chunk.endswith(":") else conditions).append(chunk.rstrip(":").strip())
        conditions.append(_clean(gap[start + 1 : end - 1]))
        cursor = end
    tail = _clean(gap[cursor:])
    if tail:
        (leftovers if tail.endswith(":") else conditions).append(tail.rstrip(":").strip())
    return conditions, leftovers


def _try_bounds_scan(text: str) -> SplitProposal | None:
    paren_spans = _top_level_paren_spans(text)
    masked = list(text)
    for start, end in paren_spans:
        masked[start:end] = " " * (end - start)
    matches = list(_BOUND.finditer("".join(masked)))
    if not matches:
        return None

    proposal = SplitProposal(grammar="bounds")
    prefix = _clean(text[: matches[0].start()])
    if prefix:
        proposal.leftovers.append(prefix.rstrip(":").strip())
    for i, m in enumerate(matches):
        gap_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        conditions, leftovers = _gap_tokens(text[m.end() : gap_end])
        bound = "max" if m.group(3) == "less" else "min"
        proposal.candidates.append(
            {
                "key": None,
                "value": {bound: _num(m.group(1)), "unit": m.group(2)},
                "conditions": conditions,
            }
        )
        proposal.leftovers.extend(leftovers)
    return proposal


def _try_range(text: str) -> SplitProposal | None:
    m = _RANGE.match(text)
    if not m:
        return None
    proposal = SplitProposal(grammar="range")
    proposal.candidates.append(
        {
            "key": None,
            "value": {"min": _num(m.group(1)), "max": _num(m.group(2)), "unit": m.group(3)},
            "conditions": [],
        }
    )
    return proposal


# Grammars whose candidates may safely inherit the source claim's key: a
# uniform list (or a single range) is the same question answered several
# times, not several questions.
INHERITING_GRAMMARS = ("alternates", "range")


def split_text_value(text: str) -> SplitProposal:
    for grammar in (_try_alternates, _try_bounds_scan, _try_range):
        proposal = grammar(text)
        if proposal is not None:
            return proposal
    return SplitProposal(grammar=None, leftovers=[text])
