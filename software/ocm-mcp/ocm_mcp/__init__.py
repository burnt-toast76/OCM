# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm-mcp -- the read-only claims serving surface (ADR-0036), presented
to MCP clients as `ocm-claims`. Reads through ocm-api (ADR-0016); the
contract is enforced in `serving`, proven by the golden evals in
evals/golden-queries.yaml, and transported by `server`.
"""

from .index import ServingIndex, build_index, normalize
from .serving import SEARCH_CAP, SUMMARY_THRESHOLD, get_claims, get_document, search_parts

__all__ = [
    "SEARCH_CAP",
    "SUMMARY_THRESHOLD",
    "ServingIndex",
    "build_index",
    "get_claims",
    "get_document",
    "normalize",
    "search_parts",
]
