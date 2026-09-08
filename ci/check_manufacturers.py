# SPDX-License-Identifier: AGPL-3.0-or-later
"""Manufacturer spelling report for the claims registry (ADR-0036 D9).

The document record's `manufacturer` is free text, and deliberately stays
that way: it is descriptive metadata (ADR-0038 D3), and an enum would
stop an ingestion pass mid-session the first time it met a manufacturer
the schema had never heard of. What free text costs is drift --
"Keyence", "KEYENCE Corporation", and "KEYENCE CORPORATION" are three
strings and one company -- and this script is how that cost stays
visible instead of accumulating quietly.

It REPORTS. It rewrites nothing: corpus files hold what each document
printed, and `get_document` serves that verbatim. The remedy for a
variant is always a line in spec/schema/ocm-manufacturers-1.0.yaml,
which merges spellings for SEARCH and leaves every record alone.

Exit codes:

  0  the report printed. Unlisted spellings and suspected variants are
     flagged and do NOT fail: an unlisted manufacturer is its own
     canonical name and is searchable from the moment it lands, so
     failing here would make the list an ingestion gate by the back
     door -- the exact thing keeping the field free text avoids.

  1  the LIST contradicts itself: one spelling claimed by two canonical
     names, or an entry with no canonical name. That is not drift in
     the corpus, it is a broken artifact in this repository, and the
     serving index would fold documents onto whichever entry happened to
     load last.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLAIMS_DIR = REPO / "claims"
MANUFACTURERS_PATH = REPO / "spec" / "schema" / "ocm-manufacturers-1.0.yaml"

SEPARATORS = " -_."

# Tokens that distinguish a legal entity but not a manufacturer: two
# spellings differing only by these are the same company often enough to
# be worth a human look. Used ONLY to nominate suspected variants for the
# report -- nothing merges on this basis, because "KEYENCE AMERICA" and
# "KEYENCE CORPORATION" really are two companies and the decision to
# search them as one is a judgment somebody makes in the list, by hand.
ENTITY_TOKENS = {
    "corporation", "corp", "company", "co", "inc", "incorporated", "gmbh", "kg", "mbh",
    "ltd", "limited", "llc", "plc", "ag", "sa", "spa", "srl", "bv", "nv", "oy", "ab", "as",
    "kk", "pte", "pty", "group", "holdings", "international", "electronic", "electronics",
    "electric", "automation", "america", "americas", "usa", "us", "europe", "japan", "and",
}


def norm(text: str) -> str:
    # ADR-0036 D4, normative: case-fold + strip space/hyphen/underscore/dot.
    return "".join(c for c in text.casefold() if c not in SEPARATORS)


def entity_key(name: str) -> str:
    """A loose key for nominating suspected variants: the name's words,
    minus the entity-flavored ones, normalized and joined. "KEYENCE
    CORPORATION" and "Keyence" both key to "keyence"."""
    words = [w for w in name.replace("&", " ").replace(",", " ").split() if w]
    kept = [w for w in words if norm(w) not in ENTITY_TOKENS]
    return "".join(norm(w) for w in (kept or words))


def corpus_roots() -> list[Path]:
    """Extra claims roots from OCM_CORPUS (the production corpus), in
    order. Unset is public-only and changes nothing."""
    configured = os.environ.get("OCM_CORPUS", "").strip()
    return [Path(configured)] if configured else []


def load_registry() -> dict[str, dict]:
    import yaml

    entries: dict[str, dict] = {}
    for root in [CLAIMS_DIR, *(corpus / "claims" for corpus in corpus_roots())]:
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if entry.is_dir() and (entry / "claims.yaml").is_file():
                entries[f"sha256:{entry.name}"] = yaml.safe_load(
                    (entry / "claims.yaml").read_text(encoding="utf-8")
                )
    return entries


def main() -> int:
    import yaml

    problems: list[str] = []

    listed: dict[str, list[str]] = {}
    if MANUFACTURERS_PATH.is_file():
        data = yaml.safe_load(MANUFACTURERS_PATH.read_text(encoding="utf-8")) or {}
        for entry in data.get("manufacturers") or []:
            canonical = str(entry.get("canonical", "")).strip()
            if not canonical:
                problems.append(f"{MANUFACTURERS_PATH.name}: an entry has no canonical name")
                continue
            listed[canonical] = [str(s) for s in (entry.get("spellings") or [])]
    else:
        print(f"note: {MANUFACTURERS_PATH.name} is absent; every spelling is its own canonical name")

    # The self-contradiction check: one normalized spelling must resolve
    # to exactly one canonical name, or the index folds by load order.
    claimed_by: dict[str, list[str]] = {}
    for canonical, spellings in listed.items():
        for spelling in [canonical, *spellings]:
            claimed_by.setdefault(norm(spelling), []).append(canonical)
    for token, owners in sorted(claimed_by.items()):
        if len(set(owners)) > 1:
            problems.append(f"spelling {token!r} is claimed by {sorted(set(owners))} -- one spelling, one canonical")

    canonical_of = {
        spelling: canonical for canonical, spellings in listed.items() for spelling in [canonical, *spellings]
    }

    # What the registry actually prints.
    printed: dict[str, list[str]] = {}
    for doc_hash, entry in load_registry().items():
        name = str((entry.get("document") or {}).get("manufacturer", "")).strip()
        printed.setdefault(name, []).append(doc_hash)

    print(f"registry: {sum(len(v) for v in printed.values())} documents, {len(printed)} printed spellings")
    print(f"list: {len(listed)} canonical names, {len(canonical_of)} spellings\n")

    print("PRINTED SPELLING -> CANONICAL")
    unlisted: list[str] = []
    for name in sorted(printed):
        canonical = canonical_of.get(name)
        mark = " " if canonical else "?"
        if canonical is None:
            unlisted.append(name)
        docs = printed[name]
        print(f" {mark} {name!r} -> {(canonical or name)!r}  ({len(docs)} document{'s' if len(docs) != 1 else ''})")

    merged = {
        canonical: sorted(n for n in printed if canonical_of.get(n) == canonical)
        for canonical in sorted(listed)
    }
    merged = {c: names for c, names in merged.items() if len(names) > 1}
    if merged:
        print("\nMERGED FOR SEARCH (one canonical, several printed spellings)")
        for canonical, names in merged.items():
            print(f"   {canonical!r} <- {names}")
        print("   Each record still serves its own spelling through get_document.")

    if unlisted:
        print("\nUNLISTED (searchable under the printed spelling; add to the list to merge)")
        for name in unlisted:
            print(f" ? {name!r}")

    # Suspected variants: two names that survive to be DIFFERENT canonical
    # names while sharing a loose entity key. Listed canonicals join the
    # comparison, which is what catches the case that matters most -- a
    # freshly ingested "Keyence" sitting unlisted beside a "KEYENCE" the
    # list already knows. Nominated for a human, never merged
    # automatically: this key deliberately strips tokens like "America"
    # that sometimes distinguish a real company.
    listed_keys: dict[str, set[str]] = {}
    for canonical in listed:
        listed_keys.setdefault(entity_key(canonical), set()).add(canonical)

    groups: dict[str, set[str]] = {}
    for name in printed:
        resolved = canonical_of.get(name, name)
        key = entity_key(resolved)
        groups.setdefault(key, set()).add(resolved)
        groups[key] |= listed_keys.get(key, set())
    suspects = {key: sorted(names) for key, names in groups.items() if len(names) > 1}
    if suspects:
        print("\nSUSPECTED VARIANTS (same company under two canonical names?)")
        for key, names in sorted(suspects.items()):
            print(f" ! {key!r}: {names}")
        print("   Decide by hand: merge them in the list, or leave them apart and say why.")
    else:
        print("\nNo suspected variants: every printed spelling already folds onto one canonical name.")

    if problems:
        print(f"\nFAIL: {len(problems)} problem(s) in the manufacturer list", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("\nOK: the manufacturer list is self-consistent. Flags above are for a human, not failures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
