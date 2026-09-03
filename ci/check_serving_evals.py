# SPDX-License-Identifier: AGPL-3.0-or-later
"""CI check for the serving-surface golden queries (ADR-0036).

The evals in software/ocm-mcp/evals/golden-queries.yaml are the
known-correct answers the future ocm-claims server must reproduce. Until
the server exists nothing executes them -- but their EXPECTATIONS can rot
against the registry today (a typo'd claim id, a part that never
existed, a count the store outgrew). This check keeps the goldens
referentially honest:

- every eval names a known tool, uniquely;
- every expected claim id exists in the registry;
- every document hash names a registry entry, and expected attestations
  match it;
- every part_number is consistent with its expectation: parts expected
  to resolve exist in some applies_to (or family, for matched_via:
  family) under ADR-0036 D4's normalization, and parts expected to be
  absence_state: no_documents match nothing;
- every key named exists in the vocabulary or is x- prefixed;
- claim_count expectations hold: exact counts equal the store's, and
  {minimum: true} counts never exceed it.

This is a check on the GOLDENS against the store -- deliberately not an
implementation of the serving semantics (that would be the weaker
sibling ADR-0016 forbids). The server's own test suite executes the
evals for real.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EVALS_PATH = REPO / "software" / "ocm-mcp" / "evals" / "golden-queries.yaml"
CLAIMS_DIR = REPO / "claims"
VOCAB_PATH = REPO / "spec" / "schema" / "ocm-claims-vocab-1.0.yaml"

KNOWN_TOOLS = {"get_claims", "search_parts", "get_document"}
SEPARATORS = " -_."


def norm(text: str) -> str:
    # ADR-0036 D4, normative: case-fold + strip space/hyphen/underscore/dot.
    return "".join(c for c in text.casefold() if c not in SEPARATORS)


def corpus_roots() -> list[Path]:
    """Extra claims roots from OCM_CORPUS (the production corpus), in
    order. Unset is public-only and changes nothing."""
    configured = os.environ.get("OCM_CORPUS", "").strip()
    return [Path(configured)] if configured else []


def load_registry():
    import yaml

    entries = {}
    for root in [CLAIMS_DIR, *(corpus / "claims" for corpus in corpus_roots())]:
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if entry.is_dir() and (entry / "claims.yaml").is_file():
                entries[f"sha256:{entry.name}"] = yaml.safe_load((entry / "claims.yaml").read_text(encoding="utf-8"))
    return entries


def eval_files() -> list[Path]:
    """Every golden file to check: this repo's, plus a corpus's own
    evals/golden-queries.yaml. The goldens whose expectations name
    real-document data live with that data (corpus layout: claims/,
    ci/alias-grandfather.txt, evals/golden-queries.yaml, tests/)."""
    paths = [EVALS_PATH]
    for corpus in corpus_roots():
        candidate = corpus / "evals" / "golden-queries.yaml"
        if candidate.is_file():
            paths.append(candidate)
    return paths


def expected_count_ok(expect_count, actual: int) -> bool:
    if isinstance(expect_count, dict):
        return actual >= int(expect_count["value"]) if expect_count.get("minimum") else actual == int(expect_count["value"])
    return actual == int(expect_count)


def main() -> int:
    import yaml

    problems: list[str] = []
    evals = []
    for path in eval_files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        evals.extend(doc.get("evals") or [])
    registry = load_registry()

    vocab = yaml.safe_load(VOCAB_PATH.read_text(encoding="utf-8"))
    vocab_keys = {entry["key"] for entry in vocab["keys"]}
    # Alias spellings credit their promoted key too (ADR-0035 D3) --
    # SPELLING-level only, no shape gate: gating is serving semantics the
    # server's own tests execute, so lint counts are upper bounds and
    # alias goldens use {minimum: true}.
    aliases = {alias: entry["key"] for entry in vocab["keys"] for alias in entry.get("aliases", [])}

    all_ids: set[str] = set()
    part_claims: dict[str, int] = {}
    per_key: dict[tuple[str, str], int] = {}
    families: set[str] = set()
    for entry in registry.values():
        for claim in entry["claims"]:
            all_ids.add(claim["id"])
            if "family" in claim:
                families.add(norm(claim["family"]))
            for part in claim["applies_to"]:
                part_claims[norm(part)] = part_claims.get(norm(part), 0) + 1
                per_key[(norm(part), claim["key"])] = per_key.get((norm(part), claim["key"]), 0) + 1
                canonical = aliases.get(claim["key"])
                if canonical is not None:
                    per_key[(norm(part), canonical)] = per_key.get((norm(part), canonical), 0) + 1

    names: set[str] = set()
    for e in evals:
        name = e.get("name", "<unnamed>")
        where = f"eval {name!r}"
        if name in names:
            problems.append(f"{where}: duplicate name")
        names.add(name)
        if e.get("tool") not in KNOWN_TOOLS:
            problems.append(f"{where}: unknown tool {e.get('tool')!r}")
        args, expect = e.get("args") or {}, e.get("expect") or {}

        for key in args.get("keys") or []:
            if key not in vocab_keys and not key.startswith("x-"):
                problems.append(f"{where}: key {key!r} is neither in the vocabulary nor x- prefixed")

        for cid in list(expect.get("claim_ids") or []) + list(expect.get("claim_ids_include") or []):
            if cid not in all_ids:
                problems.append(f"{where}: claim id {cid} not in the registry")

        part = args.get("part_number")
        if part is not None:
            known = norm(part) in part_claims or norm(part) in families
            if expect.get("absence_state") == "no_documents":
                if known:
                    problems.append(f"{where}: expects no_documents but {part!r} exists in the registry")
            elif expect.get("matched_via") == "family":
                if norm(part) not in families:
                    problems.append(f"{where}: expects matched_via family but no family string matches {part!r}")
            elif not known:
                problems.append(f"{where}: part {part!r} matches nothing in the registry")

            if "claim_count" in expect and expect.get("matched_via") != "family":
                keys = args.get("keys")
                actual = (
                    sum(per_key.get((norm(part), k), 0) for k in keys) if keys else part_claims.get(norm(part), 0)
                )
                if not expected_count_ok(expect["claim_count"], actual):
                    problems.append(f"{where}: claim_count {expect['claim_count']} inconsistent with store ({actual})")
            for key, minimum in (expect.get("summary_keys_include") or {}).items():
                actual = per_key.get((norm(part), key), 0)
                if actual < int(minimum):
                    problems.append(f"{where}: summary key {key!r} expects >= {minimum}, store has {actual}")

        doc_hash = args.get("hash")
        if doc_hash is not None:
            entry = registry.get(doc_hash)
            if entry is None:
                problems.append(f"{where}: document {doc_hash} not in the registry")
            else:
                stated = [a["vocab_version"] for a in entry.get("attestations", [])]
                if "attestations" in expect and expect["attestations"] != stated:
                    problems.append(f"{where}: attestations {expect['attestations']} != store {stated}")
                if "claim_count" in expect and not expected_count_ok(expect["claim_count"], len(entry["claims"])):
                    problems.append(f"{where}: claim_count inconsistent with store ({len(entry['claims'])})")

    print(f"evals: {len(evals)} | registry: {len(registry)} documents, {len(all_ids)} claim ids")
    if problems:
        print(f"\nFAIL: {len(problems)} problem(s)", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("OK: every golden expectation is consistent with the registry.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
