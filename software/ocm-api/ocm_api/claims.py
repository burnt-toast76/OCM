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
from .workspace import Workspace, read_yaml, write_yaml

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


def ambiguous_document(ws: Workspace, document_hash: str) -> Refusal | None:
    """One document, one entry -- a hash filed under two claims roots is
    refused, never resolved by root order (ADR-0035 D5).

    The corpus split makes this reachable: a migration that copies an
    entry into the corpus and forgets to remove the public copy leaves two
    files claiming the same identity. Preferring the first root would make
    every answer depend on configuration order, and the two copies can
    drift; refusing names both paths and stops the registry from being
    served at all (ADR-0036 D5's "a registry that fails does not get
    served"), which is the loud failure this case deserves.
    """
    paths = ws.claims_paths(document_hash)
    if len(paths) < 2:
        return None
    return Refusal(
        code=Codes.OCM_INVALID_ARGUMENT,
        path=f"claims['{document_hash}']",
        message=(
            f"document {document_hash!r} is filed under {len(paths)} claims roots: "
            + ", ".join(str(path) for path in paths)
        ),
        hint=(
            "A document is its hash and a hash names one entry (ADR-0035 D5). Remove the copy that "
            "should not be there -- do not let root order decide which one answers."
        ),
    )


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


def _alias_map(vocab: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """alias spelling -> the promoted entry that absorbs it (ADR-0035 D3)."""
    return {alias: entry for entry in vocab.values() for alias in entry.get("aliases", [])}


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


def _check_claim_binding(index: int, claim: dict[str, Any], vocab: dict[str, dict[str, Any]], aliases: dict[str, dict[str, Any]], refusals: list[Refusal], warnings: list[str]) -> None:
    key = claim.get("key")
    if not isinstance(key, str):
        return  # the schema pass already refused the claim's shape

    path = f"claims[{index}]"
    if key.startswith("x-"):
        promoted = aliases.get(key)
        if promoted is not None:
            # ADR-0035 D3: the promoted entry absorbs this spelling, and
            # binding is SHAPE-GATED (vocab header): the record binds --
            # consumable, no warning -- only when its value fits the
            # promoted shape. A mismatched record (the packed blob class)
            # stays unbound and warned, never refused.
            declared = str(promoted.get("shape", ""))
            actual = _value_shape(claim.get("value"))
            if actual == declared:
                return
            warnings.append(
                f"{path}: {key!r} aliases promoted key {promoted['key']!r} but this value is "
                f"shaped {actual!r}, not {declared!r} -- record remains unbound (shape-gated binding)"
            )
            return
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
    ambiguous = ambiguous_document(ws, document_hash)
    if ambiguous is not None:
        return Envelope.refuse([ambiguous])

    doc = read_yaml(ws.claims_path(document_hash)) or {}
    addressed = document_hash if document_hash.startswith("sha256:") else f"sha256:{document_hash}"
    refusals, warnings = _validate_doc(ws, doc, addressed)

    if refusals:
        return Envelope.refuse(refusals, warnings=warnings)
    claims = doc.get("claims") if isinstance(doc.get("claims"), list) else []
    return Envelope.succeed({"document": addressed, "claims": len(claims), "valid": True}, warnings=warnings)


def _validate_doc(ws: Workspace, doc: dict[str, Any], addressed: str) -> tuple[list[Refusal], list[str]]:
    """The whole check, on an in-memory document: schema, storage-location
    agreement, attestation uniqueness, retraction references (ADR-0037),
    vocabulary binding, the stuffed-text advisory, and stored-id
    verification. validate_claims wraps it for the
    on-disk file; append_claims runs it on the candidate document BEFORE
    writing -- one validation surface, no weaker sibling (ADR-0016).
    """
    schema = load_schema(ws.claims_schema_path)
    errors = validate_module_dict(doc, schema)  # schema-agnostic; reused, not duplicated
    refusals: list[Refusal] = [schema_violation_to_refusal(e) for e in errors]
    warnings: list[str] = []

    stated = doc.get("document", {}).get("hash") if isinstance(doc.get("document"), dict) else None
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

    # Retractions (ADR-0037 D2): each must name a claim in THIS file --
    # a retraction crossing document files would let one document's pass
    # damage another's record -- retract it at most once, and never name
    # the retracted claim as its own replacement. The schema checks the
    # entry's shape; these referential checks are the validator's half.
    claims = doc.get("claims") if isinstance(doc.get("claims"), list) else []
    claim_ids = {c.get("id") for c in claims if isinstance(c, dict)}

    # No file holds one id twice (ADR-0038 D11). append_claims skips a record
    # whose id is already present, so the ordinary path cannot produce this --
    # but a hand edit, a badly resolved merge, or a future writer can, and a
    # duplicate is exactly what content-addressing makes meaningless: the two
    # records are provably identical, so the second says nothing and the store
    # has grown for no reason. Refused rather than warned, because a store that
    # tolerates it cannot be trusted to have deduplicated anything.
    counted: dict[str, int] = {}
    for claim in claims:
        if isinstance(claim, dict) and isinstance(claim.get("id"), str):
            counted[claim["id"]] = counted.get(claim["id"], 0) + 1
    for duplicate_id, count in counted.items():
        if count > 1:
            first = next(i for i, c in enumerate(claims) if isinstance(c, dict) and c.get("id") == duplicate_id)
            refusals.append(
                Refusal(
                    code=Codes.OCM_INVALID_ARGUMENT,
                    path=f"claims[{first}].id",
                    message=f"claim id {duplicate_id!r} appears {count} times in this file",
                    hint="Ids are content hashes, so records sharing one are identical -- keep one and delete the rest. Appends are idempotent and skip an id already present (ADR-0038 D11); a duplicate means something else wrote this file.",
                )
            )

    retractions = doc.get("retractions") if isinstance(doc.get("retractions"), list) else []
    retracted_ids: set[str] = set()
    for index, retraction in enumerate(retractions):
        if not isinstance(retraction, dict):
            continue  # the schema pass already refused it
        target = retraction.get("retracts")
        if isinstance(target, str) and target not in claim_ids:
            refusals.append(
                Refusal(
                    code=Codes.OCM_NOT_FOUND,
                    path=f"retractions[{index}].retracts",
                    message=f"retracted claim {target!r} is not in this document's file",
                    hint="A retraction names a claim in its own file (ADR-0037 D2) -- check the id, or retract in the file that holds the claim.",
                )
            )
        elif isinstance(target, str) and target in retracted_ids:
            refusals.append(
                Refusal(
                    code=Codes.OCM_INVALID_ARGUMENT,
                    path=f"retractions[{index}].retracts",
                    message=f"claim {target!r} is retracted twice",
                    hint="A claim is retracted at most once; two retractions of one claim can disagree about the replacement, and the second says nothing the first did not (ADR-0037 D2).",
                )
            )
        elif isinstance(target, str):
            retracted_ids.add(target)
        replacement = retraction.get("superseded_by")
        if isinstance(replacement, str) and replacement not in claim_ids:
            refusals.append(
                Refusal(
                    code=Codes.OCM_NOT_FOUND,
                    path=f"retractions[{index}].superseded_by",
                    message=f"superseding claim {replacement!r} is not in this document's file",
                    hint="The correction is an ordinary claim, appended through the normal path FIRST -- then the retraction points at its id (ADR-0037 D2).",
                )
            )
        elif isinstance(replacement, str) and replacement == target:
            refusals.append(
                Refusal(
                    code=Codes.OCM_INVALID_ARGUMENT,
                    path=f"retractions[{index}].superseded_by",
                    message="a claim cannot supersede its own retraction",
                    hint="superseded_by names the NEW claim that replaces the retracted one; a record that does not transcribe its source cannot be its own correction (ADR-0037 D2).",
                )
            )

    vocab = _load_vocab(ws)
    aliases = _alias_map(vocab)
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            continue  # the schema pass already refused it
        _check_claim_binding(index, claim, vocab, aliases, refusals, warnings)

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
                    "vocabulary keys for the quantities (propose_claim_split drafts candidates)"
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

    return refusals, warnings


def propose_claim_split(ws: Workspace, document_hash: str, claim_id_ref: str) -> Envelope:
    """Draft a split of one stuffed text value into candidate claims --
    read-only. Candidates from a uniform grammar inherit the source key;
    heterogeneous statements come back with key: None, because choosing a
    vocabulary key is design judgment (the control-output split created
    three NEW keys). Leftover text the grammars cannot place is returned,
    never dropped. Nothing is written; review, assign keys, then
    append_claims.
    """
    from .claims_split import INHERITING_GRAMMARS, split_text_value

    if not ws.claims_exists(document_hash):
        return single_refusal(
            Codes.OCM_NOT_FOUND,
            path=f"claims['{document_hash}']",
            message=f"no claims file for document {document_hash!r} in this workspace",
        )
    ambiguous = ambiguous_document(ws, document_hash)
    if ambiguous is not None:
        return Envelope.refuse([ambiguous])
    doc = read_yaml(ws.claims_path(document_hash)) or {}
    claims = doc.get("claims") if isinstance(doc.get("claims"), list) else []
    source = next((c for c in claims if isinstance(c, dict) and c.get("id") == claim_id_ref), None)
    if source is None:
        return single_refusal(Codes.OCM_NOT_FOUND, path="claim", message=f"no claim {claim_id_ref!r} in this document's file")
    value = source.get("value")
    if not isinstance(value, str):
        return single_refusal(
            Codes.OCM_INVALID_ARGUMENT,
            path="claim.value",
            message="only text values can be split; this value is already structured",
        )

    proposal = split_text_value(value)
    source_key = source.get("key")
    inherit = proposal.grammar in INHERITING_GRAMMARS
    candidates = [dict(c, key=source_key if inherit else None) for c in proposal.candidates]
    return Envelope.succeed(
        {
            "source": claim_id_ref,
            "source_key": source_key,
            "grammar": proposal.grammar,
            "candidates": candidates,
            "leftovers": proposal.leftovers,
            "note": (
                "Nothing was written. Candidates with key: null need a human key assignment "
                "(a vocabulary decision); complete each candidate (applies_to, citation, "
                "extraction) and append via append_claims. The source claim stays as the "
                "verbatim record either way (ADR-0035 D3/D7)."
            ),
        }
    )


def append_claims(
    ws: Workspace,
    document_hash: str,
    new_claims: list[dict[str, Any]],
    attestation: dict[str, Any] | None = None,
) -> Envelope:
    """The one TOOL write path into an existing claims file: append
    reviewed claims, and optionally the pass's attestation -- two of
    ADR-0035 D7's three legal mutations. The third, a retraction, is
    deliberately absent here: no tool writes a retraction, the operator
    does (ADR-0037 D3). Ids are computed here, never supplied. The updated
    document is built from the on-disk records plus the appends --
    structurally incapable of editing or removing an existing record --
    and the WHOLE result must pass the full validation before a byte is
    written.

    Appending is IDEMPOTENT per record (ADR-0038 D11): a claim whose id the
    file already holds is skipped and reported, never written twice.
    """
    if not ws.claims_exists(document_hash):
        return single_refusal(
            Codes.OCM_NOT_FOUND,
            path=f"claims['{document_hash}']",
            message=f"no claims file for document {document_hash!r} in this workspace",
        )
    ambiguous = ambiguous_document(ws, document_hash)
    if ambiguous is not None:
        return Envelope.refuse([ambiguous])
    if not new_claims and attestation is None:
        return single_refusal(Codes.OCM_INVALID_ARGUMENT, path="$", message="nothing to append")
    addressed = document_hash if document_hash.startswith("sha256:") else f"sha256:{document_hash}"

    refusals: list[Refusal] = []
    appended: list[dict[str, Any]] = []
    for index, claim in enumerate(new_claims):
        path = f"append[{index}]"
        if not isinstance(claim, dict):
            refusals.append(Refusal(code=Codes.OCM_INVALID_ARGUMENT, path=path, message="a claim must be a mapping"))
            continue
        if "id" in claim:
            refusals.append(
                Refusal(
                    code=Codes.OCM_INVALID_ARGUMENT,
                    path=f"{path}.id",
                    message="ids are computed from the canonical serialization, never supplied",
                )
            )
            continue
        try:
            record = {"id": claim_id(claim, addressed)}
        except (KeyError, TypeError) as e:
            refusals.append(
                Refusal(
                    code=Codes.OCM_INVALID_ARGUMENT,
                    path=path,
                    message=f"claim is missing a member the id hashes over: {e}",
                )
            )
            continue
        record.update(claim)
        appended.append(record)
    if refusals:
        return Envelope.refuse(refusals)

    doc = read_yaml(ws.claims_path(document_hash)) or {}
    existing = doc.get("claims") if isinstance(doc.get("claims"), list) else []

    # Idempotent per record (ADR-0038 D11). An id already in the file is
    # SKIPPED, not appended: ids are content hashes, so a match is proof the
    # incoming record is byte-for-byte the one already stored, and writing it
    # twice would grow the store a second copy of a record saying exactly what
    # the first one says. A retried or replayed submission is therefore
    # harmless -- and the caller is told which records were skipped rather than
    # left to infer it from a count that did not move.
    #
    # The batch is deduplicated against itself as well as against the file: two
    # identical records in one call are the same duplicate arriving by a
    # shorter route, and validate_claims would refuse the result either way.
    seen: set[str] = {c.get("id") for c in existing if isinstance(c, dict) and isinstance(c.get("id"), str)}
    written: list[dict[str, Any]] = []
    skipped_ids: list[str] = []
    for record in appended:
        if record["id"] in seen:
            skipped_ids.append(record["id"])
            continue
        seen.add(record["id"])
        written.append(record)

    updated = dict(doc)
    updated["claims"] = list(existing) + written
    if attestation is not None:
        updated["attestations"] = list(doc.get("attestations") or []) + [attestation]

    refusals, warnings = _validate_doc(ws, updated, addressed)
    if refusals:
        return Envelope.refuse(refusals, warnings=warnings)

    # Nothing new and no attestation: the file is already exactly what this
    # call asked for, so it is not rewritten. Idempotent means the bytes do
    # not move either, not merely that the records do not.
    if written or attestation is not None:
        write_yaml(ws.claims_path(document_hash), updated)
    return Envelope.succeed(
        {
            "document": addressed,
            "written": len(written),
            "skipped": len(skipped_ids),
            "skipped_ids": skipped_ids,
            "ids": [record["id"] for record in written],
            "claims": len(updated["claims"]),
        },
        warnings=warnings,
    )
