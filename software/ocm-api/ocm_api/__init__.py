# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm-api -- the one programmatic surface (ADR-0012, spec/09-ocm-api.md):
`OcmApi`, a library facade over ocm-core/ocm-resolve/ocm-generator that
every verb in spec/09 wraps exactly once, plus two thin transports over
the SAME facade -- `ocm_api.mcp_server` (stdio, for agents) and
`ocm_api.http_app` (FastAPI, for a GUI). "The refusal engine lives behind
this surface and nowhere else."
"""

from .api import OcmApi
from .envelope import Codes, Envelope, Refusal
from .workspace import Workspace

__all__ = ["Codes", "Envelope", "OcmApi", "Refusal", "Workspace"]
