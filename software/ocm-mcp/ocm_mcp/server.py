# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ocm-claims MCP server (ADR-0036) -- a thin transport over
serving.py's pure functions. The contract lives there and in the golden
evals; this file only wires it to MCP. Read-only forever: no tool here
writes, transcribes, or mutates the registry.

The vocabulary rides in the server instructions (D1: no vocab tool) --
generated from the vocab file at startup so it always matches what the
envelopes' vocab_version names.

The registry may span two checkouts: OCM_ROOT (public: code, schema,
vocabulary, reference fixtures) and OCM_CORPUS (the production corpus,
optional). The instructions and every envelope name both states.

Two transports, selected by OCM_TRANSPORT. stdio (the default) is the
local one and is unchanged in every particular. http is ADR-0036's
"remote Streamable HTTP with authentication ... without contract
changes": the same three tools, the same envelopes, reached over the
network by a caller holding a bearer token. The contract is
transport-independent, so nothing below this wiring knows which one is
running.
"""

from __future__ import annotations

import os
import secrets
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import JSONResponse

from ocm_api.workspace import CORPUS_ENV

from .index import ServingIndex, build_index
from .serving import get_claims as _get_claims
from .serving import get_document as _get_document
from .serving import search_parts as _search_parts

TRANSPORT_ENV = "OCM_TRANSPORT"
HOST_ENV = "OCM_HOST"
PORT_ENV = "OCM_PORT"
TOKEN_ENV = "OCM_AUTH_TOKEN"

DEFAULT_HOST = "0.0.0.0"  # a hosted container publishes on every interface
DEFAULT_PORT = 8000

# 32 characters is far below what the README's token-generation one-liner
# produces. The floor exists to refuse a placeholder -- "changeme", a
# UUID fragment, a variable that expanded to nothing -- not to rate a
# good token.
MIN_TOKEN_CHARS = 32


@dataclass(frozen=True)
class Transport:
    """How this process serves, resolved from the environment ONCE,
    before anything is built or bound.

    stdio ignores `token` entirely -- a pipe carries no Authorization
    header, and the peer is already whoever launched the process. http
    requires one, and that requirement is not a default something can
    override: there is no setting of these four variables that produces
    an HTTP server anyone can talk to without a token. Which is why the
    check lives at resolution time rather than in a request handler that
    only runs once the port is already open.
    """

    kind: str = "stdio"
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    token: str | None = None

    @property
    def run_argument(self) -> str:
        """What FastMCP.run() calls this transport. OCM_TRANSPORT says
        `http` because that is what an operator types; MCP's spelling of
        the same thing is `streamable-http` (SSE is a deprecated third
        transport this server does not offer)."""
        return "streamable-http" if self.kind == "http" else "stdio"


def _refuse_without_token(token: str | None) -> str:
    if token is None or len(token) < MIN_TOKEN_CHARS:
        have = "unset" if not token else f"{len(token)} characters"
        raise RuntimeError(
            f"{TRANSPORT_ENV}=http requires {TOKEN_ENV} of at least {MIN_TOKEN_CHARS} "
            f"characters ({have}). Refusing to start: this server has no "
            "unauthenticated HTTP mode. Generate a token with "
            'python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    return token


def resolve_transport(env: Mapping[str, str] | None = None) -> Transport:
    """Read the four variables, or refuse.

    Every refusal here is a RuntimeError, never a fallback. A typo'd
    OCM_TRANSPORT that quietly served stdio would present as "the remote
    server is down"; a missing OCM_AUTH_TOKEN that quietly served stdio
    would present as the same thing, while the operator who asked for
    HTTP concluded the deployment was fine. Both cost far more to
    diagnose than a startup that says what is wrong.
    """
    env = os.environ if env is None else env
    kind = env.get(TRANSPORT_ENV, "").strip() or "stdio"
    if kind not in ("stdio", "http"):
        raise RuntimeError(
            f"{TRANSPORT_ENV}={kind!r} is not a transport (expected 'stdio' or 'http'). "
            "Refusing to start rather than falling back to one you did not ask for."
        )
    if kind == "stdio":
        return Transport()

    # Deliberately unstripped: the token is compared as the operator set
    # it, and silently trimming whitespace here would accept a value the
    # comparison then rejects.
    token = _refuse_without_token(env.get(TOKEN_ENV))
    port_text = env.get(PORT_ENV, "").strip() or str(DEFAULT_PORT)
    try:
        port = int(port_text)
    except ValueError:
        raise RuntimeError(f"{PORT_ENV}={port_text!r} is not a port number.") from None
    return Transport(kind="http", host=env.get(HOST_ENV, "").strip() or DEFAULT_HOST, port=port, token=token)


class StaticTokenVerifier(TokenVerifier):
    """One operator, one token, handed over out of band.

    This is FastMCP's supported bearer path -- a TokenVerifier paired
    with AuthSettings -- not hand-parsed headers: the library's
    BearerAuthBackend extracts the credential and RequireAuthMiddleware
    answers 401 before the request reaches any tool, so there is exactly
    one place an unauthenticated request could get through and it is not
    code written here.

    The comparison is constant-time and runs over bytes: a non-ASCII
    token is then a wrong token rather than a TypeError, and "wrong
    token" costs the same whether the first character differed or the
    last.
    """

    def __init__(self, token: str) -> None:
        self._token = token.encode("utf-8")

    async def verify_token(self, token: str) -> AccessToken | None:
        if not secrets.compare_digest(token.encode("utf-8"), self._token):
            return None
        # No scopes: the token IS the whole authorization decision, and
        # every tool behind it is read-only (D1), so there is nothing to
        # subdivide. required_scopes stays empty to match.
        return AccessToken(token=token, client_id="ocm-operator", scopes=[])


def _http_settings(transport: Transport) -> dict[str, Any]:
    """The FastMCP keyword arguments http adds, and stdio does not.

    stdio gets `{}` -- the constructor call stays byte-for-byte the one
    that shipped, so every local registration, test, and eval sees the
    server it already saw.
    """
    if transport.kind != "http":
        return {}
    token = _refuse_without_token(transport.token)
    # A literal IPv6 host needs brackets or AnyHttpUrl refuses it -- and
    # refusing at startup over a URL nothing reads would be an absurd way
    # to lose an OCM_HOST=:: deployment.
    authority = f"[{transport.host}]" if ":" in transport.host else transport.host
    return {
        "host": transport.host,
        "port": transport.port,
        "token_verifier": StaticTokenVerifier(token),
        # token_verifier and auth always travel together (FastMCP refuses
        # one without the other). There is no authorization server to
        # name -- the operator mints the token by hand, so this server is
        # its own issuer -- and resource_server_url stays None so NO
        # protected-resource metadata is published. A discovery document
        # advertising an OAuth endpoint that does not exist would send
        # clients chasing a flow nobody can complete; a client here is
        # configured with the token directly. With no metadata route and
        # no authorization-server provider, issuer_url is inert: it is
        # required, never served, and points at this process so that if
        # it ever does surface it is not a fiction.
        "auth": AuthSettings(
            issuer_url=AnyHttpUrl(f"http://{authority}:{transport.port}"),
            resource_server_url=None,
            required_scopes=None,
        ),
    }


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


def create_server(
    root: str | Path | None = None,
    corpus: str | Path | None = None,
    transport: Transport | None = None,
) -> FastMCP:
    """Wire the transport over one registry, which may span two checkouts.

    OCM_ROOT is the public checkout -- code, schema, vocabulary, reference
    fixtures. OCM_CORPUS, when set, appends the production corpus's claims
    root; unset serves the public registry alone, which is exactly what a
    contributor without the corpus gets. Both states ride in every
    envelope (ADR-0036 D8 as amended).
    """
    transport = transport or Transport()
    # Ahead of the index, deliberately: refusing an unauthenticated http
    # server costs nothing here, and validating a whole registry first
    # would only delay the message. resolve_transport already refused, so
    # reaching that raise means a caller built the Transport by hand.
    settings = _http_settings(transport)

    root = Path(root or os.environ.get("OCM_ROOT", "."))
    configured = corpus if corpus is not None else os.environ.get(CORPUS_ENV, "").strip()
    roots = [root, Path(configured)] if configured else [root]
    index = build_index(roots)  # refuses to serve a registry that fails validation

    mcp = FastMCP("ocm-claims", instructions=_vocab_instructions(index), **settings)

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

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        """Unauthenticated by design -- FastMCP exempts custom routes, and
        a hosting platform probes this before any token reaches it.

        It answers with D8's two identifiers and nothing else. Those ride
        in every envelope this server serves and are git commit hashes of
        a public repository, so they are public-safe by construction;
        they are also the only honest answer to "which registry state is
        live", which is the question a deploy actually needs answered.
        Nothing about claims, parts, or configuration joins them: an
        unauthenticated endpoint stays boring.
        """
        return JSONResponse(
            {
                "status": "ok",
                "serving_state": index.serving_state,
                "corpus_state": index.corpus_state,
            }
        )

    return mcp


def main() -> None:
    try:
        transport = resolve_transport()
    except RuntimeError as refusal:
        # The message, not a traceback: this is a configuration answer for
        # an operator reading a container log, not a bug report.
        print(f"ocm-claims: {refusal}", file=sys.stderr)
        raise SystemExit(2) from None
    create_server(transport=transport).run(transport.run_argument)


if __name__ == "__main__":
    main()
