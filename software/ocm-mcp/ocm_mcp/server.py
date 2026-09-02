# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ocm-claims MCP server (ADR-0036) -- a thin stdio transport over
serving.py's pure functions. The contract lives there and in the golden
evals; this file only wires it to MCP. Read-only forever: no tool here
writes, transcribes, or mutates the registry.

The vocabulary rides in the server instructions (D1: no vocab tool) --
generated from the vocab file at startup so it always matches what the
envelopes' vocab_version names.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

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
        "of a range; that judgment is yours, visibly. Absence comes in three "
        "states: attested_silence (the documents genuinely don't answer), "
        "absence_not_yet_meaningful (transcription incomplete), no_documents. "
        f"Vocabulary {index.vocab_version} keys: {keys}. Statements outside the "
        "vocabulary appear under x- prefixed keys and are unbound. "
        f"Serving registry state {index.serving_state}."
    )


def create_server(root: str | Path | None = None) -> FastMCP:
    root = Path(root or os.environ.get("OCM_ROOT", "."))
    index = build_index(root)  # refuses to serve a registry that fails validation

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
