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

A registry can span two checkouts: the public repo (code, schema,
vocabulary, reference fixtures) and a production corpus read from a
second claims root. Each keeps its own state -- serving_state and
corpus_state, each with its own -dirty suffix (D8 as amended) -- because
two registries have two identities and joining them into one string
would only make consumers split it apart again.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ocm_api import OcmApi

# Private-but-stable, imported deliberately (same posture as ocm_api's own
# use of ocm_core._read_yaml): shape classification has exactly ONE
# implementation (ADR-0016), and the shape-gated alias binding here must
# agree byte-for-byte with validate_claims' binding.
from ocm_api.claims import _value_shape
from ocm_api.workspace import Workspace, read_yaml

# ADR-0036 D4, normative: case-fold + strip these separators, both sides.
_SEPARATORS = " -_."


def normalize(text: str) -> str:
    return "".join(c for c in text.casefold() if c not in _SEPARATORS)


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _dated_after(candidate: str | None, reference: str) -> bool:
    """ISO dates order lexicographically; anything not ISO-shaped is
    conservatively NOT after (the attestation stays masked rather than
    borrowing freshness from an unparseable date)."""
    return (
        isinstance(candidate, str)
        and bool(_ISO_DATE.match(candidate))
        and bool(_ISO_DATE.match(reference))
        and candidate > reference
    )


@dataclass
class DocumentEntry:
    hash: str
    record: dict[str, Any]
    attestations: list[str]
    claims: list[dict[str, Any]]
    retractions: list[dict[str, Any]] = field(default_factory=list)
    # vocab version -> the attestation's date, for the freshness test in
    # covered() (ADR-0037 D5).
    attestation_dates: dict[str, str] = field(default_factory=dict)


@dataclass
class ServingIndex:
    root: Path
    vocab_version: str
    serving_state: str
    key_since: dict[str, str]
    # The corpus checkout's own commit, or None when none is configured
    # (ADR-0036 D8 as amended). Never folded into serving_state: two
    # registries have two identities, and joining them would only make
    # every consumer re-split the string.
    corpus_state: str | None = None
    # Every claims root served, primary first -- the public checkout, then
    # any corpus. `root` stays the primary: it is the only one carrying
    # code, schema, and vocabulary.
    roots: tuple[Path, ...] = ()
    # alias spelling -> promoted key (ADR-0035 D3), and every vocab key's
    # declared shape (the gate for alias binding).
    aliases: dict[str, str] = field(default_factory=dict)
    key_shapes: dict[str, str] = field(default_factory=dict)
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

        One more clause, computed from the record and never authored
        (ADR-0037 D5): an UNREPLACED retraction whose claim answered `key`
        is evidence the attesting pass's promise failed for this key --
        nobody has re-established what the document says -- so the key is
        uncovered until a replacement claim or a FRESH attestation lands.
        Fresh means dated strictly after the retraction: a later pass
        re-read the whole document knowing the retraction stood, so its
        promise for this key is unbroken. Dates compare as ISO strings
        (the retraction schema requires the shape; an attestation date
        that is not ISO-shaped is conservatively never fresh). A replaced
        retraction never weakens coverage, and no record is touched in
        either direction -- the rule heals itself.
        """
        entry = self.documents[document_hash]
        masks: list[str] = []
        for retraction in entry.retractions:
            if "superseded_by" in retraction:
                continue
            claim = next((c for c in entry.claims if c.get("id") == retraction["retracts"]), None)
            if claim is None:
                continue  # validate_claims refused this file at build time
            # The key the retracted claim answered: a vocabulary key
            # directly, or through shape-gated alias binding. An unbound
            # x- claim answered no vocabulary key and un-covers none.
            answered = claim["key"] if claim["key"] in self.key_since else self.bound_key(claim)
            if answered == key:
                masks.append(str(retraction.get("date", "")))
        since = _version_tuple(self.key_since[key])
        return any(
            _version_tuple(v) >= since
            and all(_dated_after(entry.attestation_dates.get(v), mask) for mask in masks)
            for v in entry.attestations
        )

    def retraction_of(self, document_hash: str, claim_id: str) -> dict[str, Any] | None:
        """The retraction naming this claim, or None. At most one exists
        -- validate_claims refuses a claim retracted twice (ADR-0037)."""
        return next(
            (r for r in self.documents[document_hash].retractions if r["retracts"] == claim_id),
            None,
        )

    def canonical_key(self, key: str) -> str:
        """Both spellings are the same key after promotion (ADR-0036 Q2a):
        an alias spelling canonicalizes to its promoted key; everything
        else is already canonical."""
        return self.aliases.get(key, key)

    def bound_key(self, claim: dict[str, Any]) -> str | None:
        """The promoted key this stored record binds to through an alias,
        or None. Shape-gated exactly as validate_claims gates it: a record
        whose value does not fit the promoted shape stays unbound."""
        canonical = self.aliases.get(claim["key"])
        if canonical is None:
            return None
        return canonical if _value_shape(claim.get("value")) == self.key_shapes.get(canonical) else None


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


def build_index(roots: str | Path | Sequence[str | Path]) -> ServingIndex:
    """Build the serving index over one or more claims roots, in order.

    One root is the whole story for a contributor and for public CI. A
    second -- the production corpus, configured by OCM_CORPUS -- is read
    as if its claims/ tree were part of the primary checkout, while code,
    schema, and vocabulary always come from the primary.

    Exactly two states are servable, because the envelope names exactly
    two (ADR-0036 D8 as amended): a third root would be served under an
    identity that cannot describe it, so it is refused rather than
    silently misreported.
    """
    if isinstance(roots, (str, Path)):
        roots = [roots]
    resolved = tuple(Path(root) for root in roots)
    if not resolved:
        raise ValueError("build_index needs at least one claims root")
    if len(resolved) > 2:
        raise ValueError(
            f"build_index was given {len(resolved)} roots; the envelope's identity contract names "
            "exactly two states (serving_state, corpus_state), so a third root could not be "
            "identified in any answer (ADR-0036 D8 as amended)"
        )
    root, extra = resolved[0], resolved[1:]
    ws = Workspace(root, extra)
    api = OcmApi(root, extra)

    vocab = read_yaml(ws.claims_vocab_path) or {}
    entries = vocab.get("keys", [])
    key_since = {entry["key"]: str(entry.get("since", "1.0")) for entry in entries}

    index = ServingIndex(
        root=root,
        vocab_version=str(vocab.get("ocm_version", "unknown")),
        serving_state=_serving_state(root),
        key_since=key_since,
        corpus_state=_serving_state(extra[0]) if extra else None,
        roots=resolved,
        aliases={alias: entry["key"] for entry in entries for alias in entry.get("aliases", [])},
        key_shapes={entry["key"]: str(entry.get("shape", "")) for entry in entries},
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
            retractions=doc.get("retractions", []),
            attestation_dates={a["vocab_version"]: str(a.get("date", "")) for a in doc.get("attestations", [])},
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
