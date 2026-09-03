# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ocm-claims MCP server (ADR-0036) -- a thin stdio transport over
serving.py's pure functions. The contract lives there and in the golden
evals; this file only wires it to MCP. Read-only forever: no tool here
writes, transcribes, or mutates the registry.

The vocabulary rides in the server instructions (D1: no vocab tool) --
generated from the vocab file at startup so it always matches what the
envelopes' vocab_version names.

The registry may span two checkouts: OCM_ROOT (public: code, schema,
vocabulary, reference fixtures) and OCM_CORPUS (the production corpus,
optional). The instructions and every envelope name both states.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from ocm_api.workspace import CORPUS_ENV

from .index import ServingIndex, build_index
from .serving import get_claims as _get_claims
from .serving import get_document as _get_document
from .serving import search_parts as _search_parts


def _vocab_instructions(index: ServingIndex) -> str:
    keys = ", ".join(sorted(index.key_since))
    return (
        "ocm-claims serves transcribed datasheet/catalog claims, read-only, with "
        "provenance on every value (claim id + document hash + page + locator). "
        "Spreads are verbatim -- this server never converts units or picks an end "
        "of a range; that judgment is yours, visibly. Absence comes in four "
        "states: attested_silence (the documents genuinely don't answer), "
        "absence_not_yet_meaningful (transcription incomplete), "
        "unbound_key_never_attested (a key outside the vocabulary -- "
        "attestations never cover it), no_documents. "
        f"Vocabulary {index.vocab_version} keys: {keys}. Statements outside the "
        "vocabulary appear under x- prefixed keys and are unbound. "
        f"Serving registry state {index.serving_state}"
        + (f", corpus state {index.corpus_state}." if index.corpus_state else " (no corpus configured).")
    )


def create_server(root: str | Path | None = None, corpus: str | Path | None = None) -> FastMCP:
    """Wire the transport over one registry, which may span two checkouts.

    OCM_ROOT is the public checkout -- code, schema, vocabulary, reference
    fixtures. OCM_CORPUS, when set, appends the production corpus's claims
    root; unset serves the public registry alone, which is exactly what a
    contributor without the corpus gets. Both states ride in every
    envelope (ADR-0036 D8 as amended).
    """
    root = Path(root or os.environ.get("OCM_ROOT", "."))
    configured = corpus if corpus is not None else os.environ.get(CORPUS_ENV, "").strip()
    roots = [root, Path(configured)] if configured else [root]
    index = build_index(roots)  # refuses to serve a registry that fails validation

    mcp = FastMCP("ocm-claims", instructions=_vocab_instructions(index))

    @mcp.tool(description=(
        "Claims covering one part, every value with claim id and full citation. "
        "Omit `keys` to discover (summarized above 25 claims); name `keys` for full "
        "records. Part numbers match exactly after normalization (case, separators); "
        "a family NAME as the query resolves labeled matched_via: family."
    ))
    def get_claims(part_number: str, keys: list[str] | None = None) -> dict[str, Any]:
        return _get_claims(index, part_number, keys)

    @mcp.tool(description=(
        "Approximate lookup over part numbers and family strings (never claim text). "
        "Returns candidates for you to choose and query exactly; capped at 50."
    ))
    def search_parts(query: str) -> dict[str, Any]:
        return _search_parts(index, query)

    @mcp.tool(description=(
        "A document record by content hash: metadata, attestation versions, claim "
        "count, parts covered. Never document bytes -- the registry holds citations, "
        "not manufacturer documents."
    ))
    def get_document(hash: str) -> dict[str, Any]:
        return _get_document(index, hash)

    return mcp


def main() -> None:
    create_server().run()


if __name__ == "__main__":
    main()
