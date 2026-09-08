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
beats a clean-looking one. Where a root is a baked snapshot rather than
a checkout, the commit comes from a `.ocm-state` file written when the
snapshot was built; where neither exists, the state is "untracked".

A registry can span two checkouts: the public repo (code, schema,
vocabulary, reference fixtures) and a production corpus read from a
second claims root. Each keeps its own state -- serving_state and
corpus_state, each with its own -dirty suffix (D8 as amended) -- because
two registries have two identities and joining them into one string
would only make consumers split it apart again.

The index also joins each document's RECORD to the claims that document
covers, which is what makes manufacturer searchable (ADR-0036 D9). The
join happens here and nowhere else: the record was always read at this
point and simply never reached the search structures, so no stored file
changes and no re-ingestion is required.
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
class ManufacturerEntry:
    """One manufacturer's reach across the registry (ADR-0036 D9).

    Built by joining every document record's `manufacturer` to the claims
    that document carries, then folding the printed spellings onto one
    canonical name through the manufacturer list.

    `families` and `parts_outside_families` are what a manufacturer query
    answers with, and together they cover every part without listing them
    all: a large vendor's parts arrive as a handful of family strings the
    agent can query exactly, and the parts NO family of this manufacturer
    covers are named individually so nothing becomes unreachable. A
    manufacturer whose documents state no family at all therefore still
    answers with its parts -- the rule degrades to naming them, never to
    silence.
    """

    canonical: str
    spellings: list[str] = field(default_factory=list)
    documents: set[str] = field(default_factory=set)
    families: list[str] = field(default_factory=list)
    parts: list[str] = field(default_factory=list)
    parts_outside_families: list[str] = field(default_factory=list)


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
    # --- manufacturer lookup (ADR-0036 D9) ---------------------------------
    # canonical name -> its reach. Keyed by the canonical name because
    # that is what every search result carries; the printed spellings
    # ride along on the entry, so get_document's verbatim answer and the
    # search surface's merged one never disagree about what was read.
    manufacturers: dict[str, ManufacturerEntry] = field(default_factory=dict)
    # every searchable normalized token -> canonical name. Holds the
    # canonical spelling AND each printed spelling, which is what lets
    # "keyence" reach a document whose record says KEYENCE AMERICA.
    manufacturer_names: dict[str, str] = field(default_factory=dict)
    # normalized part / family -> the canonical manufacturers covering it,
    # sorted. A list, not a string: one part can be covered by documents
    # from two manufacturers, and search emits one result per pair rather
    # than joining names into a field consumers would have to split.
    part_manufacturers: dict[str, list[str]] = field(default_factory=dict)
    family_manufacturers: dict[str, list[str]] = field(default_factory=dict)

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

    def find_claim(self, claim_id: str) -> tuple[str, dict[str, Any]] | None:
        """(document hash, claim) for a stored claim id, or None. The
        report intake's precision gate (ADR-0037 D3): served values carry
        their ids, so a genuine dispute always has one to copy."""
        for document_hash, entry in self.documents.items():
            for claim in entry.claims:
                if claim.get("id") == claim_id:
                    return document_hash, claim
        return None

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


# The canonical manufacturer list (ADR-0036 D9). Read from the PRIMARY
# root only, beside the schema and the vocabulary -- a corpus supplies
# documents, never the names they are searched under.
#
# Read here rather than through Workspace on purpose: this list is a
# serving artifact, consulted by no validator. Routing it through
# ocm_api would put a file validate_claims never opens into the
# validation surface, and ADR-0016's "one validation surface" is a claim
# about what validates, which this does not.
MANUFACTURERS_FILE = Path("spec") / "schema" / "ocm-manufacturers-1.0.yaml"


def _append_unique(mapping: dict[str, list[str]], token: str, value: str) -> None:
    bucket = mapping.setdefault(token, [])
    if value not in bucket:
        bucket.append(value)


def _load_manufacturers(root: Path) -> dict[str, list[str]]:
    """canonical name -> its printed spellings, from the manufacturer
    list. A missing or unreadable file is not an error: every document
    record then stands as its own canonical name, which is exactly the
    behavior for a manufacturer the list has not caught up with. The
    list merges spellings; it never grants visibility, so its absence
    costs merging and nothing else."""
    try:
        data = read_yaml(root / MANUFACTURERS_FILE) or {}
    except OSError:
        return {}
    listed: dict[str, list[str]] = {}
    for entry in data.get("manufacturers") or []:
        canonical = str(entry.get("canonical", "")).strip()
        if not canonical:
            continue
        listed[canonical] = [str(s) for s in (entry.get("spellings") or [])]
    return listed


# A build-time state file, for roots that are real but not checkouts.
STATE_FILE = ".ocm-state"
_COMMIT = re.compile(r"\A[0-9a-f]{40}\Z")


def _serving_state(root: Path) -> str:
    """Which commit of this root is being served (ADR-0036 D8).

    Three sources, in this order, and the order is the whole design.

    1. GIT, when the root is a checkout: the commit, suffixed `-dirty` when
       the claims tree carries uncommitted changes. This is the developer's
       case and the deployed case wherever `.git` survives, and it is
       unchanged in every particular -- an honest identity beats a
       clean-looking one.

    2. A `.ocm-state` FILE at the root, when git has nothing to say. A
       baked image may hold a registry copied as plain files, with the
       history left behind; the state is then recorded at build time by
       whatever did the copying, and read back verbatim. Deliberately NO
       `-dirty` suffix: an image is immutable, so there is nothing for
       `dirty` to mean, and appending it would invent a distinction the
       artifact cannot have.

    3. `untracked`, the honest floor. Non-null so the envelope always has
       an answer, and unmistakable so nobody reads it as a commit.

    Git wins over the file wherever both exist, because a checkout can
    move and a file recorded when it was built cannot. A stale `.ocm-state`
    in a working tree would otherwise pin the identity to whatever it said
    the day it was written, which is exactly the silent downgrade this
    whole field exists to prevent. For the same reason the file must
    contain one full 40-character hash and nothing else: anything else
    falls through to `untracked` rather than being served as though it
    were a commit.
    """
    try:
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "claims"], capture_output=True, text=True, check=True
        ).stdout.strip()
        return f"{commit}-dirty" if dirty else commit
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    try:
        recorded = (root / STATE_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return "untracked"
    return recorded if _COMMIT.match(recorded) else "untracked"


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

    # Printed spelling -> canonical, from the manufacturer list. Every
    # canonical name maps to itself too, so a record already spelled
    # canonically resolves without being listed as its own variant.
    listed = _load_manufacturers(root)
    canonical_of = {
        spelling: canonical for canonical, spellings in listed.items() for spelling in [canonical, *spellings]
    }
    # Accumulators for the walk, materialized as sorted lists once it
    # ends. Sets rather than the entry's own lists: a catalog appends the
    # same part on hundreds of claims, and membership on a list would
    # make that a scan per claim.
    #   family_covered -- normalized parts this manufacturer reaches
    #     through a family-carrying claim, subtracted at the end: a part
    #     covered by SOME family of the manufacturer is reachable through
    #     that family and is not listed on its own.
    family_covered: dict[str, set[str]] = {}
    seen_parts: dict[str, set[str]] = {}
    seen_families: dict[str, set[str]] = {}

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

        # The join (ADR-0036 D9). The document record is already in hand;
        # `manufacturer` is required by the schema, so a printed spelling
        # always exists. An UNLISTED spelling is its own canonical name --
        # the list merges spellings and never grants visibility, so a
        # manufacturer ingested before the list caught up is searchable
        # under exactly what its record says.
        printed = str(entry.record.get("manufacturer", "")).strip()
        canonical = canonical_of.get(printed, printed)
        maker = None
        if canonical:
            maker = index.manufacturers.get(canonical)
            if maker is None:
                maker = ManufacturerEntry(canonical=canonical, spellings=[])
                index.manufacturers[canonical] = maker
                for token in {normalize(s) for s in [canonical, *listed.get(canonical, [])] if s}:
                    index.manufacturer_names[token] = canonical
            if printed and printed not in maker.spellings:
                maker.spellings.append(printed)
                index.manufacturer_names.setdefault(normalize(printed), canonical)
            maker.documents.add(document_hash)
            family_covered.setdefault(canonical, set())
            seen_parts.setdefault(canonical, set())
            seen_families.setdefault(canonical, set())

        for claim in entry.claims:
            for part in claim["applies_to"]:
                token = normalize(part)
                index.part_names.setdefault(token, part)
                index.by_part.setdefault(token, []).append((document_hash, claim))
                index.part_documents.setdefault(token, set()).add(document_hash)
                if maker is not None:
                    # Retracted claims are indexed here exactly as they
                    # always were: search is discovery, and a part whose
                    # only live claim was retracted still exists to be
                    # asked about -- get_claims serves the retraction
                    # story (ADR-0037 D4). The join changes no part of
                    # that; it only says whose part it is.
                    _append_unique(index.part_manufacturers, token, canonical)
                    seen_parts[canonical].add(part)
                    if "family" in claim:
                        family_covered[canonical].add(token)
            if "family" in claim:
                token = normalize(claim["family"])
                index.family_names.setdefault(token, claim["family"])
                index.by_family.setdefault(token, []).append((document_hash, claim))
                if maker is not None:
                    _append_unique(index.family_manufacturers, token, canonical)
                    seen_families[canonical].add(claim["family"])

    for canonical, maker in index.manufacturers.items():
        maker.spellings.sort()
        maker.families = sorted(seen_families.get(canonical, set()))
        maker.parts = sorted(seen_parts.get(canonical, set()))
        covered = family_covered.get(canonical, set())
        maker.parts_outside_families = [p for p in maker.parts if normalize(p) not in covered]
    for mapping in (index.part_manufacturers, index.family_manufacturers):
        for token in mapping:
            mapping[token].sort()

    return index
