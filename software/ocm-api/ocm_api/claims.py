# SPDX-License-Identifier: AGPL-3.0-or-later
"""Claims validation and identity (ADR-0035) -- one validation surface
per artifact kind, no weaker sibling (ADR-0016). `validate_claims` is
both halves of that surface: schema validation of the claims file AND
the vocabulary binding the schema cannot see (a key's declared shape,
whether it takes a subject, x- keys marked unbound) AND the stored-id
verification that makes the store's append-only rule enforceable rather
than conventional -- any edit to an ingested record changes its true
hash, and the stored id gives it away.

`claim_id` is the ONE implementation of
spec/schema/ocm-claims-serialization-1.0.md (ADR-0016 again: no second
implementation anywhere, in any language). The canonicalization itself
is RFC 8785 via the `rfc8785` package -- borrowed rules, not owned ones;
this module only assembles the hash-scope object: the claim's content
members plus its citation with the file-level document hash re-attached,
and never `id` (the output) or `extraction` (metadata -- a human pass
and an automated pass of the same statement must converge on one id, or
ADR-0035 D6's parity test has no measuring stick).

Refusal codes are the existing generic ones (OCM_NOT_FOUND,
OCM_INVALID_ARGUMENT, schema violations via translate.py): ADR-0035 is
Proposed, and its dedicated codes enter the catalogue at acceptance,
per the house rule.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import rfc8785

from ocm_core.loader import load_schema, validate_module_dict

from .envelope import Codes, Envelope, Refusal, single_refusal
from .translate import schema_violation_to_refusal
from .workspace import Workspace, read_yaml

# Hash-scope members copied from the claim when present; everything else
# in scope (key, value, conditions, applies_to, citation) is mandatory.
# Serialization spec section 2: an omitted optional member is ABSENT from
# the canonical form, never null.
_HASH_SCOPE_OPTIONAL = ("subject", "family")

# A number followed by a short unit token ("30 V", "1.4 mA", "660 nm").
# Deliberately a heuristic: it feeds an ADVISORY, never a refusal -- some
# composite cells (a per-mode response-time table) are legitimately one
# statement, and D2 promises ingestion never refuses a true statement.
_QUANTITY = re.compile(r"\d[\d.,]*\s*([a-zA-Zµ°%]{1,3})(?![a-zA-Z])")
_QUANTITY_STOPWORDS = frozenset({"to", "or", "of", "and", "the", "per", "for", "at", "in", "on", "as", "by"})
_QUANTITY_ADVISORY_THRESHOLD = 3


def claim_id(claim: dict[str, Any], document_hash: str) -> str:
    """sha256 of the claim's canonical serialization, presented as
    "sha256:<64 lowercase hex>" -- the same content-address format the
    document hash uses. `document_hash` is the file-level document hash,
    re-attached into the hash-scope citation so identical text in two
    different documents never collides into one id.
    """
    scope: dict[str, Any] = {
        "key": claim["key"],
        "value": claim["value"],
        "conditions": claim["conditions"],
        "applies_to": claim["applies_to"],
        "citation": {
            "document": document_hash,
            "page": claim["citation"]["page"],
            "locator": claim["citation"]["locator"],
        },
    }
    for member in _HASH_SCOPE_OPTIONAL:
        if member in claim:
            scope[member] = claim[member]
    return "sha256:" + hashlib.sha256(rfc8785.dumps(scope)).hexdigest()


def _load_vocab(ws: Workspace) -> dict[str, dict[str, Any]]:
    doc = read_yaml(ws.claims_vocab_path) or {}
    return {entry["key"]: entry for entry in doc.get("keys", []) if isinstance(entry, dict) and "key" in entry}


def _value_shape(value: Any) -> str | None:
    """The shape a value's structure implies. The schema keeps the shapes
    structurally disjoint, so this is a classification, not a guess; None
    means the value fits no shape (the schema pass already refused it).
    """
    if isinstance(value, str):
        return "text"
    if isinstance(value, list):
        if value and all(isinstance(item, str) for item in value):
            return "list"
        if value and all(isinstance(item, dict) for item in value):
            return "record"
        return None
    if isinstance(value, dict):
        if "number" in value:
            return "scalar"
        if any(bound in value for bound in ("min", "typ", "max", "unqualified")):
            return "spread"
        if any(dim in value for dim in ("length", "width", "height")):
            return "dimensions"
    return None


def _key_takes_subject(entry: dict[str, Any]) -> bool:
    # Presence of the marker is what binds, not its spelling -- robust
    # across the vocab's `subject:` marker wording.
    return "subject" in entry


def _check_claim_binding(index: int, claim: dict[str, Any], vocab: dict[str, dict[str, Any]], refusals: list[Refusal], warnings: list[str]) -> None:
    key = claim.get("key")
    if not isinstance(key, str):
        return  # the schema pass already refused the claim's shape

    path = f"claims[{index}]"
    if key.startswith("x-"):
        # ADR-0035 D2: the escape hatch relaxes naming, never structure.
        # Well-formed (the schema pass applies in full) but unbound.
        warnings.append(
            f"{path}: {key!r} is well-formed but unbound -- not a vocabulary key; "
            "nothing downstream may consume an unbound claim as a manifest source (ADR-0035 D2)"
        )
        return

    entry = vocab.get(key)
    if entry is None:
        refusals.append(
            Refusal(
                code=Codes.OCM_INVALID_ARGUMENT,
                path=f"{path}.key",
                message=f"{key!r} is not in the claims vocabulary and is not x- prefixed",
                hint="Use the vocabulary key that answers this question, or record a true statement the vocabulary lacks under an x- key (ADR-0035 D2).",
            )
        )
        return

    declared = str(entry.get("shape", ""))
    actual = _value_shape(claim.get("value"))
    if actual is not None and actual != declared:
        refusals.append(
            Refusal(
                code=Codes.OCM_INVALID_ARGUMENT,
                path=f"{path}.value",
                message=f"{key!r} is declared shape {declared!r} in the vocabulary; this value is shaped as {actual!r}",
                hint="The vocabulary entry's shape is the contract two manufacturers' datasheets are judged against -- transcribe into it, never around it.",
            )
        )

    if "subject" in claim and not _key_takes_subject(entry):
        refusals.append(
            Refusal(
                code=Codes.OCM_INVALID_ARGUMENT,
                path=f"{path}.subject",
                message=f"{key!r} takes no subject; a designation that qualifies WHEN the value holds belongs in conditions",
                hint="Only keys the vocabulary marks subject-taking claim about one element among several. Omitting a subject is always legal; carrying one here is not.",
            )
        )
    # The reverse -- a subject-taking key with no subject -- is always
    # legal: the document may designate no element (a sole unlabeled
    # connector), and the absence is the transcription (ADR-0035 D1).


def validate_claims(ws: Workspace, document_hash: str) -> Envelope:
    """Schema validation, vocabulary binding, and stored-id verification
    for one document's claims file, addressed by its document hash.
    """
    if not ws.claims_exists(document_hash):
        return single_refusal(
            Codes.OCM_NOT_FOUND,
            path=f"claims['{document_hash}']",
            message=f"no claims file for document {document_hash!r} in this workspace",
        )

    doc = read_yaml(ws.claims_path(document_hash)) or {}

    schema = load_schema(ws.claims_schema_path)
    errors = validate_module_dict(doc, schema)  # schema-agnostic; reused, not duplicated
    refusals: list[Refusal] = [schema_violation_to_refusal(e) for e in errors]
    warnings: list[str] = []

    stated = doc.get("document", {}).get("hash") if isinstance(doc.get("document"), dict) else None
    addressed = document_hash if document_hash.startswith("sha256:") else f"sha256:{document_hash}"
    if isinstance(stated, str) and stated != addressed:
        refusals.append(
            Refusal(
                code=Codes.OCM_INVALID_ARGUMENT,
                path="document.hash",
                message=f"the file's document.hash {stated!r} does not match its storage location {addressed!r}",
                hint="Storage location is derived from the document hash, never chosen. A revised document is a NEW record in its own directory (ADR-0035 D5/D7).",
            )
        )

    # One pass per vocabulary version (ADR-0035 D4): the attestations array
    # accumulates across vocabulary versions, and a duplicate version would
    # be two "written once" statements about one pass -- the schema cannot
    # express the uniqueness, so it is checked here.
    attestations = doc.get("attestations") if isinstance(doc.get("attestations"), list) else []
    seen_versions: set[str] = set()
    for index, attestation in enumerate(attestations):
        version = attestation.get("vocab_version") if isinstance(attestation, dict) else None
        if isinstance(version, str) and version in seen_versions:
            refusals.append(
                Refusal(
                    code=Codes.OCM_INVALID_ARGUMENT,
                    path=f"attestations[{index}].vocab_version",
                    message=f"a second attestation at vocabulary version {version!r} -- one pass per vocabulary version, written once when it finishes",
                    hint="A later vocabulary gets its own pass and its own attestation; the same version attested twice says nothing new and breaks the written-once rule (ADR-0035 D4).",
                )
            )
        elif isinstance(version, str):
            seen_versions.add(version)

    vocab = _load_vocab(ws)
    claims = doc.get("claims") if isinstance(doc.get("claims"), list) else []
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            continue  # the schema pass already refused it
        _check_claim_binding(index, claim, vocab, refusals, warnings)

        # Advisory: a text value stuffed with quantities is usually several
        # statements wearing one claim -- D1 defines a claim as a SINGLE
        # datasheet-answerable statement. Applies to x- claims too.
        value = claim.get("value")
        if isinstance(value, str):
            quantities = [unit for unit in _QUANTITY.findall(value) if unit.lower() not in _QUANTITY_STOPWORDS]
            if len(quantities) >= _QUANTITY_ADVISORY_THRESHOLD:
                warnings.append(
                    f"claims[{index}].value: text value carries {len(quantities)} unit-bearing quantities -- "
                    "a claim is a single datasheet-answerable statement (ADR-0035 D1); split it, or nominate "
                    "vocabulary keys for the quantities"
                )

        # Stored-id verification -- only computable once the members the
        # hash scope needs are structurally present; anything missing was
        # already refused by the schema pass.
        try:
            recomputed = claim_id(claim, addressed)
        except (KeyError, TypeError):
            continue
        stored_id = claim.get("id")
        if isinstance(stored_id, str) and stored_id != recomputed:
            refusals.append(
                Refusal(
                    code=Codes.OCM_INVALID_ARGUMENT,
                    path=f"claims[{index}].id",
                    message=f"stored id {stored_id!r} does not match the recomputed id {recomputed!r}",
                    hint="Ingested claim records are append-only (ADR-0035 D3/D7). If the record changed, that is a new claim -- and if it shouldn't have changed, revert it.",
                )
            )

    if refusals:
        return Envelope.refuse(refusals, warnings=warnings)
    return Envelope.succeed({"document": addressed, "claims": len(claims), "valid": True}, warnings=warnings)
