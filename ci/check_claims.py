# SPDX-License-Identifier: AGPL-3.0-or-later
"""CI check for the claims store and its vocabulary (ADR-0035).

Two halves:

1. The vocabulary file is lint-checked structurally: parseable YAML 1.2
   (ocm-core's own loader -- the one every other YAML in this repo goes
   through), unique keys, every entry carrying key/shape/dimension/
   definition, shapes drawn from the header's set, subject markers
   spelled `takes`, and every `record_schema` resolving to a
   `record_<name>` def in the claims schema. The vocab once merged as
   invalid YAML; this is the check that was missing.

2. Every entry in claims/ is verified with the REAL `validate_claims` --
   not a re-implementation. ADR-0016 forbids a second, weaker validation
   surface, so this script imports the one validator even though that
   costs CI the full ocm-api install; a stdlib-only shadow of the schema
   + vocab-binding + stored-id checks would drift, and its green would
   mean nothing. On top of that per-file validation, the store layout
   itself is checked: every claims/ directory is named by the sha256 of
   the document.txt it contains (storage location is derived from
   identity, never chosen), with both files present.

Exit 0 with a summary when everything holds; exit 1 naming every
violation otherwise. validate_claims warnings (e.g. an x- claim's
unbound notice) are printed but do not fail the check.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VOCAB_PATH = REPO / "spec" / "schema" / "ocm-claims-vocab-1.0.yaml"
CLAIMS_SCHEMA_PATH = REPO / "spec" / "schema" / "ocm-claims-1.0.schema.json"
CLAIMS_DIR = REPO / "claims"

KNOWN_SHAPES = {"scalar", "spread", "dimensions", "text", "list", "record"}
ENTRY_REQUIRED = ("key", "shape", "dimension", "definition")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def check_vocab(problems: list[str]) -> None:
    from ocm_core.loader import _read_yaml

    try:
        doc = _read_yaml(VOCAB_PATH)
    except Exception as e:  # noqa: BLE001 -- any parse failure is the finding
        problems.append(f"vocab: {VOCAB_PATH.name} does not parse: {e}")
        return

    entries = doc.get("keys") if isinstance(doc, dict) else None
    if not isinstance(entries, list) or not entries:
        problems.append("vocab: no `keys:` list")
        return

    schema = json.loads(CLAIMS_SCHEMA_PATH.read_text(encoding="utf-8"))
    record_defs = {name for name in schema.get("$defs", {}) if name.startswith("record_")}

    seen: set[str] = set()
    for i, entry in enumerate(entries):
        where = f"vocab keys[{i}]"
        if not isinstance(entry, dict):
            problems.append(f"{where}: not a mapping")
            continue
        missing = [f for f in ENTRY_REQUIRED if f not in entry]
        if missing:
            problems.append(f"{where} ({entry.get('key', '?')}): missing {missing}")
        key = entry.get("key")
        if isinstance(key, str):
            if key in seen:
                problems.append(f"{where}: duplicate key {key!r}")
            seen.add(key)
        shape = entry.get("shape")
        if shape not in KNOWN_SHAPES:
            problems.append(f"{where} ({key}): unknown shape {shape!r} (known: {sorted(KNOWN_SHAPES)})")
        if "subject" in entry and entry["subject"] != "takes":
            problems.append(f"{where} ({key}): subject marker is {entry['subject']!r}, must be 'takes'")
        if "record_schema" in entry and f"record_{entry['record_schema']}" not in record_defs:
            problems.append(
                f"{where} ({key}): record_schema {entry['record_schema']!r} has no "
                f"record_{entry['record_schema']} def in {CLAIMS_SCHEMA_PATH.name}"
            )
        if shape == "record" and "record_schema" not in entry:
            problems.append(f"{where} ({key}): shape record without a record_schema")

    print(f"vocab: {len(entries)} entries, {len(seen)} unique keys")


def check_store(problems: list[str]) -> None:
    from ocm_api import OcmApi

    api = OcmApi(REPO)
    entries = sorted(p for p in CLAIMS_DIR.iterdir() if p.is_dir()) if CLAIMS_DIR.is_dir() else []

    for entry in entries:
        name = entry.name
        if not HEX64.match(name):
            problems.append(f"claims/{name}: directory name is not 64 hex digits of a sha256")
            continue
        document = entry / "document.txt"
        claims_file = entry / "claims.yaml"
        if not document.is_file():
            problems.append(f"claims/{name}: no document.txt -- a citation without bytes is unverifiable (ADR-0035 D5)")
            continue
        if not claims_file.is_file():
            problems.append(f"claims/{name}: no claims.yaml")
            continue

        actual = hashlib.sha256(document.read_bytes()).hexdigest()
        if actual != name:
            problems.append(
                f"claims/{name}: document.txt hashes to {actual} -- storage location is derived "
                "from the document hash, never chosen (ADR-0035 D5/D7)"
            )
            continue

        envelope = api.validate_claims(f"sha256:{name}")
        for warning in envelope.warnings:
            print(f"claims/{name[:8]}...: warning: {warning}")
        if not envelope.ok:
            for refusal in envelope.refusals:
                problems.append(f"claims/{name}: [{refusal.code}] {refusal.path}: {refusal.message}")
        else:
            print(f"claims/{name[:8]}...: {envelope.data['claims']} claims valid")

    print(f"store: {len(entries)} document entr{'y' if len(entries) == 1 else 'ies'}")


def main() -> int:
    problems: list[str] = []
    check_vocab(problems)
    check_store(problems)
    if problems:
        print(f"\nFAIL: {len(problems)} problem(s)", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("OK: vocabulary well-formed; every claims entry hash-anchored and validate_claims-clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
