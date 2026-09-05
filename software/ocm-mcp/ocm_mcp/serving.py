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
  summary; full records come by asking with keys (D7);
- retracted claims are excluded from claims: by default and served with
  their story in the retracted: section instead -- the default consumer
  cannot quote a retracted value by accident, and a consumer holding the
  old id learns what happened to it from the same query that used to
  return it (ADR-0037 D4). Absence recomputes as if a retracted claim
  never answered.
"""

from __future__ import annotations

from typing import Any

from .index import ServingIndex, normalize

SUMMARY_THRESHOLD = 25  # ADR-0036 D7
SEARCH_CAP = 50  # ADR-0036 D7


def _envelope(index: ServingIndex, **payload: Any) -> dict[str, Any]:
    # Two states, always both present (ADR-0036 D8 as amended):
    # serving_state is the public checkout -- code, schema, vocabulary,
    # fixtures -- and corpus_state the production corpus, null when none
    # is configured. Null is an answer, not an omission: it says this
    # server serves the public registry alone, which a missing field
    # would leave the consumer to guess.
    return {
        "vocab_version": index.vocab_version,
        "serving_state": index.serving_state,
        "corpus_state": index.corpus_state,
        **payload,
    }


def _served_record(index: ServingIndex, document_hash: str, claim: dict[str, Any]) -> dict[str, Any]:
    record = dict(claim)
    citation = dict(claim["citation"])
    citation["document"] = document_hash  # the full citation, inline, always (D2)
    record["citation"] = citation
    # Provenance is the stored form -- the key is never relabeled. An
    # alias-bound record carries bound_via naming the promoted key
    # (ADR-0035 D3; shape-gated, so a packed outlier carries nothing).
    bound = index.bound_key(claim)
    if bound is not None:
        record["bound_via"] = bound
    return record


def _retracted_extras(
    index: ServingIndex, gone: list[tuple[str, dict[str, Any], dict[str, Any]]]
) -> dict[str, Any]:
    """The relocated story (ADR-0037 D4): retracted records the query
    would have matched, each flagged and carrying its retraction record
    verbatim -- reason, date, superseding claim id when one exists.
    Empty when the scope holds none, so the common case pays nothing."""
    if not gone:
        return {}
    retracted = []
    for document_hash, claim, retraction in gone:
        record = _served_record(index, document_hash, claim)
        record["retracted"] = True
        record["retraction"] = dict(retraction)
        retracted.append(record)
    return {"retracted_count": len(retracted), "retracted": retracted}


def _partition_retracted(
    index: ServingIndex, matches: list[tuple[str, dict[str, Any]]]
) -> tuple[list[tuple[str, dict[str, Any]]], list[tuple[str, dict[str, Any], dict[str, Any]]]]:
    live: list[tuple[str, dict[str, Any]]] = []
    gone: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for document_hash, claim in matches:
        retraction = index.retraction_of(document_hash, claim["id"])
        if retraction is None:
            live.append((document_hash, claim))
        else:
            gone.append((document_hash, claim, retraction))
    return live, gone


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
    key = index.canonical_key(key)  # both spellings are the same key (Q2a)
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
    # Exclusion by default (ADR-0037 D4): retracted records leave the
    # serving set entirely -- claims:, counts, and the summary threshold
    # all see live records only -- and every response whose scope touched
    # one carries the story in retracted:.
    live, gone = _partition_retracted(index, matches)

    if keys:
        # A query key matches a record's stored key, its canonical form
        # (querying the x- spelling still works after promotion), or --
        # shape-gated -- the promoted key an alias record binds to.
        wanted = {index.canonical_key(k) for k in keys} | set(keys)
        served = [
            (h, c) for h, c in live
            if c["key"] in wanted or (index.bound_key(c) in wanted)
        ]
        gone_served = [
            (h, c, r) for h, c, r in gone
            if c["key"] in wanted or (index.bound_key(c) in wanted)
        ]
        if not served:
            # One absence state for the whole query: meaningful only when
            # every consulted document covers every asked key (D3). A
            # retracted claim never answers -- covered() already treats an
            # unreplaced retraction as un-covering its key (ADR-0037 D5),
            # so a key answered only by a retracted record recomputes to
            # absence_not_yet_meaningful, with the story alongside.
            worst = [_absence(index, documents, key) for key in keys]
            state = next(
                (a for a in worst if a["absence_state"] == "absence_not_yet_meaningful"),
                worst[0],
            )
            return _envelope(index, part_number=part_number, resolved_part=resolved, matched_via=matched_via,
                             attestation_status=status, keys=keys, **state, **_retracted_extras(index, gone_served))
        return _envelope(
            index,
            part_number=part_number,
            resolved_part=resolved,
            matched_via=matched_via,
            attestation_status=status,
            mode="full",
            claim_count=len(served),
            claims=[_served_record(index, h, c) for h, c in served],
            **_retracted_extras(index, gone_served),
        )

    if len(live) > SUMMARY_THRESHOLD:
        summary: dict[str, dict[str, Any]] = {}
        for _, claim in live:
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
            claim_count=len(live),
            summary=summary,
            **_retracted_extras(index, gone),
        )

    return _envelope(
        index,
        part_number=part_number,
        resolved_part=resolved,
        matched_via=matched_via,
        attestation_status=status,
        mode="full",
        claim_count=len(live),
        claims=[_served_record(index, h, c) for h, c in live],
        **_retracted_extras(index, gone),
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
    # Counts describe what the document SERVES: retracted records are out
    # of claim_count and parts_covered, and announced by retracted_count
    # when any exist (ADR-0037 D4) -- absent when zero, like everywhere.
    live = [c for c in entry.claims if index.retraction_of(hash, c["id"]) is None]
    parts = sorted({p for c in live for p in c["applies_to"]})
    extras: dict[str, Any] = {"retracted_count": len(entry.retractions)} if entry.retractions else {}
    return _envelope(
        index,
        hash=hash,
        found=True,
        bytes_served=False,  # the registry holds citations, never real documents
        record=dict(entry.record),
        attestations=list(entry.attestations),
        claim_count=len(live),
        parts_covered=parts,
        **extras,
    )
