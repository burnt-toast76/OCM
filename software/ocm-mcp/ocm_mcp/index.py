# SPDX-License-Identifier: AGPL-3.0-or-later
"""The disposable serving index (ADR-0036 D5).

Built from the claims files at startup, reading through ocm_api (ADR-0016
-- the one implementation of validation and claims access); the files
remain the sole source of truth, the index is rebuilt on every start and
never persisted. Building it runs every registry entry through
validate_claims, and a registry that refuses does not get served.

One process lifetime serves exactly one registry state, identified by
the git commit of the checkout (D8) -- suffixed "-dirty" when the
claims/ tree carries uncommitted changes, because an honest identity
beats a clean-looking one.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ocm_api import OcmApi
from ocm_api.workspace import Workspace, read_yaml

# ADR-0036 D4, normative: case-fold + strip these separators, both sides.
_SEPARATORS = " -_."


def normalize(text: str) -> str:
    return "".join(c for c in text.casefold() if c not in _SEPARATORS)


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


@dataclass
class DocumentEntry:
    hash: str
    record: dict[str, Any]
    attestations: list[str]
    claims: list[dict[str, Any]]


@dataclass
class ServingIndex:
    root: Path
    vocab_version: str
    serving_state: str
    key_since: dict[str, str]
    documents: dict[str, DocumentEntry] = field(default_factory=dict)
    # normalized part -> display spelling (first seen, from applies_to)
    part_names: dict[str, str] = field(default_factory=dict)
    # normalized family -> display spelling
    family_names: dict[str, str] = field(default_factory=dict)
    # normalized part -> [(document hash, claim), ...]
    by_part: dict[str, list[tuple[str, dict[str, Any]]]] = field(default_factory=dict)
    # normalized family -> [(document hash, claim), ...]
    by_family: dict[str, list[tuple[str, dict[str, Any]]]] = field(default_factory=dict)
    # normalized part -> document hashes on file for the part
    part_documents: dict[str, set[str]] = field(default_factory=dict)

    def covered(self, document_hash: str, key: str) -> bool:
        """A document's absence for `key` is meaningful iff some attestation
        on it pins a vocabulary version that already contained the key
        (ADR-0035 D4: a later vocabulary's new keys are honestly uncovered
        by an older attestation). Only vocabulary keys can be covered at
        all -- an attestation's promise is scoped to the vocabulary, so
        callers check membership first; an unknown key here is a
        programming error, never silently treated as a 1.0 key.
        """
        since = _version_tuple(self.key_since[key])
        return any(_version_tuple(v) >= since for v in self.documents[document_hash].attestations)


def _serving_state(root: Path) -> str:
    try:
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "claims"], capture_output=True, text=True, check=True
        ).stdout.strip()
        return f"{commit}-dirty" if dirty else commit
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "untracked"


def build_index(root: str | Path) -> ServingIndex:
    root = Path(root)
    ws = Workspace(root)
    api = OcmApi(root)

    vocab = read_yaml(ws.claims_vocab_path) or {}
    key_since = {entry["key"]: str(entry.get("since", "1.0")) for entry in vocab.get("keys", [])}

    index = ServingIndex(
        root=root,
        vocab_version=str(vocab.get("ocm_version", "unknown")),
        serving_state=_serving_state(root),
        key_since=key_since,
    )

    for document_hash in ws.list_claims_document_hashes():
        envelope = api.validate_claims(document_hash)
        if not envelope.ok:
            details = "; ".join(f"{r.path}: {r.message}" for r in envelope.refusals)
            raise RuntimeError(f"refusing to serve: {document_hash} fails validate_claims ({details})")
        doc = read_yaml(ws.claims_path(document_hash)) or {}
        entry = DocumentEntry(
            hash=document_hash,
            record=doc.get("document", {}),
            attestations=[a["vocab_version"] for a in doc.get("attestations", [])],
            claims=doc.get("claims", []),
        )
        index.documents[document_hash] = entry

        for claim in entry.claims:
            for part in claim["applies_to"]:
                token = normalize(part)
                index.part_names.setdefault(token, part)
                index.by_part.setdefault(token, []).append((document_hash, claim))
                index.part_documents.setdefault(token, set()).add(document_hash)
            if "family" in claim:
                token = normalize(claim["family"])
                index.family_names.setdefault(token, claim["family"])
                index.by_family.setdefault(token, []).append((document_hash, claim))

    return index
