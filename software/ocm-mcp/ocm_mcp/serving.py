# SPDX-License-Identifier: AGPL-3.0-or-later
"""The three serving tools (ADR-0036 D1), as pure functions over the
index -- what the golden evals execute and the MCP transport wraps.

Contract invariants enforced here, not in the transport:

- every envelope carries vocab_version, serving_state, and (for
  get_claims) the part's attestation_status (D2);
- every served claim record carries its id and full citation -- document
  hash re-attached inline beside page and locator -- and there is no
  path that strips them (D2);
- spreads are served verbatim; nothing here computes, converts, or
  summarizes a value (D2);
- absence is answered in one of four distinct states, never a bare
  empty list (D3) -- and silence on a key outside the vocabulary is
  never attested silence;
- resolution is exact after normalization; family resolution triggers
  only on the family NAME as the query, labeled matched_via: family
  (D4);
- an unfiltered response above SUMMARY_THRESHOLD claims is a per-key
  summary; full records come by asking with keys (D7).
"""

from __future__ import annotations

from typing import Any

from .index import ServingIndex, normalize

SUMMARY_THRESHOLD = 25  # ADR-0036 D7
SEARCH_CAP = 50  # ADR-0036 D7


def _envelope(index: ServingIndex, **payload: Any) -> dict[str, Any]:
    return {"vocab_version": index.vocab_version, "serving_state": index.serving_state, **payload}


def _served_record(document_hash: str, claim: dict[str, Any]) -> dict[str, Any]:
    record = dict(claim)
    citation = dict(claim["citation"])
    citation["document"] = document_hash  # the full citation, inline, always (D2)
    record["citation"] = citation
    return record


def _attestation_status(index: ServingIndex, document_hashes: set[str]) -> str:
    attested = [bool(index.documents[h].attestations) for h in document_hashes]
    if all(attested):
        return "all_attested"
    return "mixed" if any(attested) else "unattested"


def _absence(index: ServingIndex, documents: set[str], key: str) -> dict[str, Any]:
    # The caller resolved the document set (part- or family-scoped, D4);
    # absence is computed from THAT set, never re-derived from a token --
    # a family-resolved query's absence must consult the family's
    # documents, not answer no_documents while they sit on file.
    if not documents:
        return {"absence_state": "no_documents"}
    if key not in index.key_since:
        # An attestation promises full transcription against a VOCABULARY
        # (ADR-0035 D4); a statement outside the vocabulary is outside
        # that promise, so an absent x-/unknown key never earns attested
        # silence -- that would be fabricated certainty (ADR-0036 D3).
        return {"absence_state": "unbound_key_never_attested", "documents_on_file": sorted(documents)}
    if all(index.covered(h, key) for h in documents):
        return {"absence_state": "attested_silence", "documents_consulted": sorted(documents)}
    return {"absence_state": "absence_not_yet_meaningful", "documents_on_file": sorted(documents)}


def get_claims(index: ServingIndex, part_number: str, keys: list[str] | None = None) -> dict[str, Any]:
    token = normalize(part_number)

    if token in index.by_part:
        matches = index.by_part[token]
        matched_via = "exact"
        resolved = index.part_names[token]
        documents = index.part_documents[token]
    elif token in index.by_family:
        # D4: the query itself names a family. Unlisted members never
        # land here -- membership-by-prefix is refused as fuzzy matching.
        matches = index.by_family[token]
        matched_via = "family"
        resolved = index.family_names[token]
        documents = {h for h, _ in matches}
    else:
        return _envelope(index, part_number=part_number, absence_state="no_documents")

    status = _attestation_status(index, documents)

    if keys:
        served = [(h, c) for h, c in matches if c["key"] in keys]
        if not served:
            # One absence state for the whole query: meaningful only when
            # every consulted document covers every asked key (D3).
            worst = [_absence(index, documents, key) for key in keys]
            state = next(
                (a for a in worst if a["absence_state"] == "absence_not_yet_meaningful"),
                worst[0],
            )
            return _envelope(index, part_number=part_number, resolved_part=resolved, matched_via=matched_via,
                             attestation_status=status, keys=keys, **state)
        return _envelope(
            index,
            part_number=part_number,
            resolved_part=resolved,
            matched_via=matched_via,
            attestation_status=status,
            mode="full",
            claim_count=len(served),
            claims=[_served_record(h, c) for h, c in served],
        )

    if len(matches) > SUMMARY_THRESHOLD:
        summary: dict[str, dict[str, Any]] = {}
        for _, claim in matches:
            entry = summary.setdefault(claim["key"], {"count": 0, "subjects": []})
            entry["count"] += 1
            subject = claim.get("subject")
            if subject is not None and subject not in entry["subjects"]:
                entry["subjects"].append(subject)
        return _envelope(
            index,
            part_number=part_number,
            resolved_part=resolved,
            matched_via=matched_via,
            attestation_status=status,
            mode="summary",
            claim_count=len(matches),
            summary=summary,
        )

    return _envelope(
        index,
        part_number=part_number,
        resolved_part=resolved,
        matched_via=matched_via,
        attestation_status=status,
        mode="full",
        claim_count=len(matches),
        claims=[_served_record(h, c) for h, c in matches],
    )


def search_parts(index: ServingIndex, query: str) -> dict[str, Any]:
    token = normalize(query)
    results: list[dict[str, str]] = []
    for norm_part, display in sorted(index.part_names.items()):
        if token in norm_part:
            results.append({"identifier": display, "kind": "part"})
    for norm_family, display in sorted(index.family_names.items()):
        if token in norm_family:
            results.append({"identifier": display, "kind": "family"})
    truncated = len(results) > SEARCH_CAP
    return _envelope(index, query=query, results=results[:SEARCH_CAP], truncated=truncated)


def get_document(index: ServingIndex, hash: str) -> dict[str, Any]:
    entry = index.documents.get(hash)
    if entry is None:
        return _envelope(index, hash=hash, found=False)
    parts = sorted({p for c in entry.claims for p in c["applies_to"]})
    return _envelope(
        index,
        hash=hash,
        found=True,
        bytes_served=False,  # the registry holds citations, never real documents
        record=dict(entry.record),
        attestations=list(entry.attestations),
        claim_count=len(entry.claims),
        parts_covered=parts,
    )
