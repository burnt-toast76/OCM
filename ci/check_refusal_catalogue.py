#!/usr/bin/env python3
# Refusal-catalogue conformance check (ADR-0025).
#
# Two invariants, both from ADR-0025's "Refusals this admits (checked in CI)":
#   1. Every refusal code emitted anywhere in software/ appears in the catalogue
#      (spec/schema/ocm-refusals-1.0.yaml). A code an engine can emit but the
#      standard doesn't name is drift.
#   2. Every `outcome: degrade` entry carries a `records:` field. A degrade with
#      nothing recorded is absorption wearing a legible mask (ADR-0025 D3).
#
# Deliberately dependency-light: PyYAML + stdlib only, no ocm-* imports, so it
# runs in the same minimal environment as fmt-check.
#
# The authoritative set of "emitted codes" is the `Codes` class in
# software/ocm-api/ocm_api/envelope.py (every refusal routes through it), plus
# any bare `code="LITERAL"` string passed to a Refusal in software/. Both are
# scanned so a future literal that bypasses `Codes` still gets caught.

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "spec" / "schema" / "ocm-refusals-1.0.yaml"
ENVELOPE = ROOT / "software" / "ocm-api" / "ocm_api" / "envelope.py"
SOFTWARE = ROOT / "software"

# A refusal code: UPPER_SNAKE, >=4 chars (excludes stray 2-3 letter constants).
_CODE = re.compile(r"[A-Z][A-Z0-9_]{3,}")
# `Codes` class member: `    NAME = "NAME"` (4-space class-body indent).
_MEMBER = re.compile(r'^\s{4}([A-Z][A-Z0-9_]{3,})\s*=\s*["\']', re.M)
# A bare literal passed as a refusal code anywhere in software/.
_LITERAL = re.compile(r'code\s*=\s*["\']([A-Z][A-Z0-9_]{3,})["\']')


def emitted_codes() -> set[str]:
    codes: set[str] = set()
    codes |= set(_MEMBER.findall(ENVELOPE.read_text(encoding="utf-8")))
    for py in SOFTWARE.rglob("*.py"):
        codes |= set(_LITERAL.findall(py.read_text(encoding="utf-8")))
    return codes


def main() -> int:
    catalogue = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8")) or {}
    keys = set(catalogue)
    errors: list[str] = []

    # Invariant 2: degrade => records.
    for code, entry in catalogue.items():
        if not isinstance(entry, dict):
            errors.append(f"catalogue entry {code!r} is not a mapping")
            continue
        if entry.get("outcome") == "degrade" and not entry.get("records"):
            errors.append(f"{code}: outcome is 'degrade' but no 'records' field (ADR-0025 D3)")

    # Invariant 1: emitted code => catalogued.
    missing = sorted(c for c in emitted_codes() if c not in keys)
    for code in missing:
        errors.append(f"{code}: emitted in software/ but not in the catalogue (ADR-0025)")

    if errors:
        print("Refusal-catalogue check FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    live = sum(1 for e in catalogue.values() if isinstance(e, dict) and e.get("status") != "deferred")
    deferred = len(catalogue) - live
    print(f"OK: {len(catalogue)} catalogue entries ({live} live, {deferred} deferred); "
          f"all emitted codes catalogued; all degrade entries record a field.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
