# SPDX-License-Identifier: AGPL-3.0-or-later
"""CI guard against alias-spelling drift (docs/ingestion.md, vocabulary
binding).

Once a key is promoted, its old x- spelling exists so that IMMUTABLE
HISTORY binds (ADR-0035 D3) -- a new pass writes the bound key, never the
alias. This check fails when any claim in the store uses an alias
spelling of a promoted key and is not in the frozen grandfather
inventory (ci/alias-grandfather.txt): the content-hash ids of every
alias-spelling claim that existed when the guard was introduced.

Mechanism note -- inventory, not git diffing, on purpose: claim ids are
content hashes, so the inventory is exact and reorder-proof; it needs no
git history (the workflows use shallow checkouts); it behaves
identically locally and in CI; and append-only means the inventory never
legally grows -- which is precisely the rule being guarded. The
inventory must also stay a subset of the store: a grandfathered id
vanishing means store surgery happened, and the guard says so rather
than rotting silently. (If an entry is ever removed by explicit
user-directed reset, regenerate the inventory in the same commit.)

Vocabulary growth is handled automatically: promoting another key adds
its alias spelling to the guarded set, and any store claims under that
spelling at promotion time must be added to the inventory in the
promotion commit -- the failure message says exactly which ids.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLAIMS_DIR = REPO / "claims"
VOCAB_PATH = REPO / "spec" / "schema" / "ocm-claims-vocab-1.0.yaml"
GRANDFATHER_PATH = REPO / "ci" / "alias-grandfather.txt"


def main() -> int:
    import yaml

    vocab = yaml.safe_load(VOCAB_PATH.read_text(encoding="utf-8"))
    alias_spellings = {alias for entry in vocab["keys"] for alias in entry.get("aliases", [])}
    grandfathered = {
        line.strip()
        for line in GRANDFATHER_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }

    problems: list[str] = []
    seen: set[str] = set()
    for entry in sorted(CLAIMS_DIR.iterdir()):
        claims_file = entry / "claims.yaml"
        if not entry.is_dir() or not claims_file.is_file():
            continue
        doc = yaml.safe_load(claims_file.read_text(encoding="utf-8"))
        for claim in doc.get("claims", []):
            if claim["key"] not in alias_spellings:
                continue
            seen.add(claim["id"])
            if claim["id"] not in grandfathered:
                problems.append(
                    f"claims/{entry.name[:8]}...: {claim['id']} uses alias spelling {claim['key']!r} "
                    "-- new passes write the promoted key, never the alias (docs/ingestion.md)"
                )

    for stale in sorted(grandfathered - seen):
        problems.append(
            f"grandfathered id {stale} is no longer in the store -- store surgery? "
            "Regenerate ci/alias-grandfather.txt in the same commit as any user-directed entry reset."
        )

    print(f"alias spellings guarded: {len(alias_spellings)} | grandfathered ids: {len(grandfathered)} | in store: {len(seen)}")
    if problems:
        print(f"\nFAIL: {len(problems)} problem(s)", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("OK: no alias-spelling drift; every alias-spelling claim predates the guard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
