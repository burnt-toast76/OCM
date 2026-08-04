#!/usr/bin/env python3
# Refusal-catalogue conformance check (ADR-0025).
#
# Three invariants, from ADR-0025's "Refusals this admits (checked in CI)":
#   1a. Every refusal code emitted anywhere in software/ appears in the
#       catalogue (spec/schema/ocm-refusals-1.0.yaml). A code an engine can emit
#       but the standard doesn't name is drift.
#   1b. Every catalogue entry that is ACTIVE (not deferred) appears as a literal
#       somewhere in software/. Catches a code deleted from an engine while the
#       catalogue still claims it is live.
#   2.  Every `outcome: degrade` entry carries a `records:` field. A degrade with
#       nothing recorded is absorption wearing a legible mask (ADR-0025 D3).
#
# DISCOVERY IS TOKEN-MATCHING, NOT PATTERN-MATCHING. The earlier version looked
# only at `Codes` members in one file and `code="..."` literals -- so a refusal
# code defined as a plain module constant, or hardcoded in the composer's
# TypeScript, escaped entirely. That is the exact hole this check exists to
# close, and it matters most for cycle-phase codes: ADR-0025 D1 emits those from
# generated PLC/ST, i.e. text the old two patterns never read. So instead this
# scans every code-carrying file for UPPER_SNAKE string literals and treats one
# as a refusal code by its SHAPE.
#
# Scanned: .py (engines), .ts/.tsx (composer frontend), and template suffixes
# for the generated PLC/ST that ADR-0025 D1 will add (none exist yet; the
# suffixes are here so the check already covers them the day they land).
#
# Dependency-light: PyYAML + stdlib only, no ocm-* imports, so it runs in the
# same minimal environment as fmt-check.

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "spec" / "schema" / "ocm-refusals-1.0.yaml"
SOFTWARE = ROOT / "software"

# Files that can carry a refusal code. Extend SCAN_SUFFIXES when a new code-
# emitting language lands (the generated-ST templates of ADR-0025 D1).
SCAN_SUFFIXES = {".py", ".ts", ".tsx", ".st", ".j2", ".jinja", ".tmpl", ".template"}
SKIP_DIRS = {"node_modules", ".git", "__pycache__", "dist", "build", ".venv", ".mypy_cache"}

# A refusal code's shape: UPPER_SNAKE with at least one underscore, as a string
# literal (single, double, or backtick-quoted). Matches both the bare live codes
# and the OCM_-namespaced ones, so this check is correct on both sides of the
# Task-3 rename. (`UNAVAILABLE`, the one live code with no underscore, is handled
# by the active-key membership test below, not by this shape.)
_CODE_SHAPE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")
# Broad literal grabber for the membership test in invariant 1b -- any quoted
# UPPER token, underscore or not.
_LITERAL = re.compile(r"""["'`]([A-Z][A-Z0-9_]{2,})["'`]""")

# ALLOWLIST -- UPPER_SNAKE string literals that share the code SHAPE but are NOT
# refusal codes. This is an explicit, curated list ON PURPOSE. The hole this
# check closes was born of a regex too narrow to see real codes; the fix is to
# scan broadly and name the exceptions here, never to re-narrow the shape until
# the noise (and the next real code with it) disappears. Add a token here only
# after confirming it is genuinely not a refusal code.
ALLOWLIST = {
    # ADR-0015 connectivity fixtures: net / link / port / pin identifiers.
    "PWR_IN", "PWR_OUT", "NET_IN", "NET_OUT", "NET_ID", "AIR_IN",
    "N_24V", "N_LONELY", "N_ALT", "L_EC_1", "L_BAD", "L_X",
    "C_AIR", "C_SUPPLY", "P_ELEC", "P_COMM", "P_A", "P_B", "IN_3", "SUPPLY_24V",
    # environment variables, config keys, and constants.
    "ANTHROPIC_API_KEY", "OCM_API_REPO", "DEFAULT_REGISTERED_PROTOCOLS",
    "UR_JOINT_ORDER", "PK100_DATASHEET",
    # ocm_core.carrier's exported constant naming the module-schema sections a
    # carrier must never carry (ADR-0031 D1) -- appears quoted in __all__.
    "CARRIER_CONTROL_FIELDS",
}


def _scan_files():
    for f in SOFTWARE.rglob("*"):
        if not f.is_file() or f.suffix not in SCAN_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in f.parts):
            continue
        yield f


def scan() -> tuple[set[str], set[str]]:
    """Returns (code_shaped, all_literals).

    code_shaped: UPPER_SNAKE-with-underscore literals, minus the allowlist --
        the candidate refusal codes for the emitted-but-uncatalogued check.
    all_literals: every quoted UPPER token -- used to test whether an active
        catalogue key (e.g. no-underscore `UNAVAILABLE`) is emitted at all.
    """
    code_shaped: set[str] = set()
    all_literals: set[str] = set()
    for f in _scan_files():
        for tok in _LITERAL.findall(f.read_text(encoding="utf-8", errors="ignore")):
            all_literals.add(tok)
            if tok not in ALLOWLIST and _CODE_SHAPE.match(tok):
                code_shaped.add(tok)
    return code_shaped, all_literals


def main() -> int:
    catalogue = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8")) or {}
    keys = set(catalogue)
    active = {k for k, v in catalogue.items() if isinstance(v, dict) and v.get("status") != "deferred"}
    errors: list[str] = []

    # Invariant 2: degrade => records.
    for code, entry in catalogue.items():
        if not isinstance(entry, dict):
            errors.append(f"catalogue entry {code!r} is not a mapping")
            continue
        if entry.get("outcome") == "degrade" and not entry.get("records"):
            errors.append(f"{code}: outcome is 'degrade' but no 'records' field (ADR-0025 D3)")

    code_shaped, all_literals = scan()

    # Invariant 1a: emitted (code-shaped) but not catalogued.
    for code in sorted(code_shaped - keys):
        errors.append(f"{code}: emitted in software/ but not in the catalogue (ADR-0025)")

    # Invariant 1b: catalogued active but emitted nowhere.
    for code in sorted(active - all_literals):
        errors.append(f"{code}: catalogue status is active but it is emitted nowhere in software/ (ADR-0025)")

    if errors:
        print("Refusal-catalogue check FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    deferred = len(catalogue) - len(active)
    print(f"OK: {len(catalogue)} catalogue entries ({len(active)} active, {deferred} deferred); "
          f"every code-shaped literal in software/ is catalogued; "
          f"every active entry is emitted; every degrade entry records a field.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
