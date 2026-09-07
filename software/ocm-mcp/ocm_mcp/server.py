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

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import JSONResponse

from ocm_api.workspace import CORPUS_ENV

from .auth import (
    OPERATOR_IDENTITY,
    AuthKitVerifier,
    CompositeVerifier,
    OAuthConfig,
    StaticTokenVerifier,
)
from .coverage import COVERAGE_REPO_ENV, COVERAGE_TOKEN_ENV, CoverageQueue, coverage_from_env
from .index import ServingIndex, build_index
from .reports import ReportQueue, reports_from_queue
from .serving import get_claims as _get_claims
from .serving import get_document as _get_document
from .serving import search_parts as _search_parts

TRANSPORT_ENV = "OCM_TRANSPORT"
HOST_ENV = "OCM_HOST"
PORT_ENV = "OCM_PORT"
TOKEN_ENV = "OCM_AUTH_TOKEN"
OAUTH_ISSUER_ENV = "OCM_OAUTH_ISSUER"
OAUTH_AUDIENCE_ENV = "OCM_OAUTH_AUDIENCE"
OAUTH_JWKS_ENV = "OCM_OAUTH_JWKS"

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

    stdio ignores `token` and `oauth` entirely -- a pipe carries no
    Authorization header, and the peer is already whoever launched the
    process. http requires AT LEAST ONE credential kind, and that
    requirement is not a default something can override: there is no
    setting of these variables that produces an HTTP server anyone can
    talk to unauthenticated. Which is why the check lives at resolution
    time rather than in a request handler that only runs once the port is
    already open.

    Two kinds, either or both. The operator token is the credential that
    works when the identity provider is down, misconfigured, or being
    migrated; OAuth is how a stranger who has never met the operator gets
    in. Both configured together is the expected production state.
    """

    kind: str = "stdio"
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    token: str | None = None
    oauth: OAuthConfig | None = None

    @property
    def run_argument(self) -> str:
        """What FastMCP.run() calls this transport. OCM_TRANSPORT says
        `http` because that is what an operator types; MCP's spelling of
        the same thing is `streamable-http` (SSE is a deprecated third
        transport this server does not offer)."""
        return "streamable-http" if self.kind == "http" else "stdio"


def _refuse_short_token(token: str) -> str:
    if len(token) < MIN_TOKEN_CHARS:
        raise RuntimeError(
            f"{TOKEN_ENV} is {len(token)} characters; at least {MIN_TOKEN_CHARS} are "
            "required. Refusing to start rather than serving behind a placeholder: "
            "this server has no unauthenticated HTTP mode, and it does not quietly "
            "ignore a credential you set. Generate a token with "
            'python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    return token


def _require_absolute_url(name: str, value: str) -> str:
    """An OAuth URL variable, or a refusal naming it.

    A bare domain is the mistake an operator actually makes -- WorkOS
    prints the AuthKit domain as `your-project.authkit.app` in places, and
    pasting it verbatim leaves a value that reads perfectly and has no
    scheme. Without this, the failure surfaced deep in a JWKS client as
    "Invalid JWKS URI scheme ''" with a traceback, which names neither the
    variable nor the fix. Refused here, where the variable still has a
    name to put in the message.
    """
    if not value.startswith(("http://", "https://")):
        raise RuntimeError(
            f"{name}={value!r} is not an absolute URL. Refusing to start: it needs the "
            f"scheme, e.g. {name}=https://{value.lstrip('/') or 'your-project-12345.authkit.app'}. "
            "A bare domain reads correctly and fails later, inside a JWKS fetch that "
            "cannot tell you which variable was wrong."
        )
    return value


def _resolve_oauth(env: Mapping[str, str]) -> OAuthConfig | None:
    """A complete OAuth configuration, nothing, or a refusal.

    Half-configured is the case worth refusing. An operator who set the
    issuer and forgot the audience has plainly asked for OAuth, and the
    quiet alternative -- falling back to bearer-only -- would leave a
    server that looks configured, answers 401 to every OAuth client, and
    tells nobody why. Worse, a missing audience is not a cosmetic gap: it
    is the check that stops a token minted for a DIFFERENT resource on the
    same authorization server from opening this one (MCP authorization
    spec; RFC 8707).
    """
    issuer = env.get(OAUTH_ISSUER_ENV, "").strip()
    audience = env.get(OAUTH_AUDIENCE_ENV, "").strip()
    jwks = env.get(OAUTH_JWKS_ENV, "").strip()
    if not issuer and not audience:
        return None if not jwks else _refuse_partial_oauth(issuer, audience)
    if not issuer or not audience:
        return _refuse_partial_oauth(issuer, audience)
    _require_absolute_url(OAUTH_ISSUER_ENV, issuer)
    # The audience is the resource indicator AND becomes resource_server_url,
    # where pydantic's AnyHttpUrl would reject it with its own vocabulary.
    _require_absolute_url(OAUTH_AUDIENCE_ENV, audience)
    if jwks:
        _require_absolute_url(OAUTH_JWKS_ENV, jwks)
    return OAuthConfig(issuer=issuer, audience=audience, jwks_uri=jwks or OAuthConfig.jwks_uri_for(issuer))


def _refuse_partial_oauth(issuer: str, audience: str) -> OAuthConfig:
    missing = [name for name, value in ((OAUTH_ISSUER_ENV, issuer), (OAUTH_AUDIENCE_ENV, audience)) if not value]
    raise RuntimeError(
        f"OAuth is partly configured: {', '.join(missing)} "
        f"{'is' if len(missing) == 1 else 'are'} unset. Refusing to start rather than "
        "silently serving bearer-only -- a server that looks OAuth-enabled and answers "
        "401 to every OAuth client is the expensive kind of wrong. Set both "
        f"({OAUTH_ISSUER_ENV} is the AuthKit domain, {OAUTH_AUDIENCE_ENV} the resource "
        "indicator this server is reached at), or neither."
    )


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
    raw_token = env.get(TOKEN_ENV)
    token = _refuse_short_token(raw_token) if raw_token else None
    oauth = _resolve_oauth(env)
    if token is None and oauth is None:
        raise RuntimeError(
            f"{TRANSPORT_ENV}=http requires a credential: {TOKEN_ENV} (at least "
            f"{MIN_TOKEN_CHARS} characters), or a complete OAuth configuration "
            f"({OAUTH_ISSUER_ENV} and {OAUTH_AUDIENCE_ENV}), or both -- which is the "
            "expected production state. Refusing to start: this server has no "
            "unauthenticated HTTP mode. Generate a token with "
            'python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    port_text = env.get(PORT_ENV, "").strip() or str(DEFAULT_PORT)
    try:
        port = int(port_text)
    except ValueError:
        raise RuntimeError(f"{PORT_ENV}={port_text!r} is not a port number.") from None
    return Transport(
        kind="http",
        host=env.get(HOST_ENV, "").strip() or DEFAULT_HOST,
        port=port,
        token=token,
        oauth=oauth,
    )


def _http_settings(transport: Transport) -> dict[str, Any]:
    """The FastMCP keyword arguments http adds, and stdio does not.

    stdio gets `{}` -- the constructor call stays byte-for-byte the one
    that shipped, so every local registration, test, and eval sees the
    server it already saw.
    """
    if transport.kind != "http":
        return {}
    if transport.token is None and transport.oauth is None:
        raise RuntimeError(
            f"{TRANSPORT_ENV}=http requires {TOKEN_ENV} or a complete OAuth "
            "configuration. Refusing to start: this server has no unauthenticated "
            "HTTP mode."
        )
    static = StaticTokenVerifier(_refuse_short_token(transport.token)) if transport.token else None
    oauth = AuthKitVerifier(transport.oauth) if transport.oauth else None

    # A literal IPv6 host needs brackets or AnyHttpUrl refuses it -- and
    # refusing at startup over a URL nothing reads would be an absurd way
    # to lose an OCM_HOST=:: deployment.
    authority = f"[{transport.host}]" if ":" in transport.host else transport.host
    local_url = AnyHttpUrl(f"http://{authority}:{transport.port}")

    # THE METADATA REVERSAL. Step one set resource_server_url=None with a
    # comment explaining the absence: there was no authorization server to
    # name, the operator minted tokens by hand, and a discovery document
    # advertising an OAuth endpoint that did not exist would have sent
    # clients chasing a flow nobody could complete. That reasoning was
    # right then and is obsolete now -- AuthKit is a real authorization
    # server, and RFC 9728 metadata is how a client that has never met the
    # operator finds it. The MCP authorization spec makes it mandatory for
    # a protected server ("MCP servers MUST implement OAuth 2.0 Protected
    # Resource Metadata"), and the SDK publishes the route and the
    # WWW-Authenticate pointer once resource_server_url is set. So the
    # deliberate absence is deliberately reversed, and this comment
    # replaces the one that explained it.
    #
    # Bearer-only deployments keep the old posture exactly: with no OAuth
    # configured there is still no authorization server to name, so no
    # metadata is published and issuer_url stays inert -- required by
    # AuthSettings, never served, and pointing at this process so that if
    # it ever does surface it is not a fiction.
    return {
        "host": transport.host,
        "port": transport.port,
        "token_verifier": CompositeVerifier(static, oauth),
        # token_verifier and auth always travel together (FastMCP refuses
        # one without the other).
        "auth": AuthSettings(
            issuer_url=AnyHttpUrl(transport.oauth.issuer) if transport.oauth else local_url,
            resource_server_url=AnyHttpUrl(transport.oauth.audience) if transport.oauth else None,
            # No scope subdivision in v1: an authenticated caller gets
            # every tool this server has. They are all read-only and the
            # two queues are capped, so there is nothing to subdivide;
            # paid tiers can introduce scopes later without breaking any
            # client that registered against this.
            required_scopes=None,
        ),
    }


def _caller_identity() -> str:
    """Who this request's daily cap belongs to.

    The OAuth `sub`, or the operator sentinel. stdio reaches the second
    branch and should: a pipe carries no Authorization header and its peer
    is whoever launched the process, which is the operator.

    `sub` rather than `client_id` because `sub` is the claim AuthKit's
    access tokens are documented to carry; `client_id` is not guaranteed,
    and keying a budget on a claim that may be absent would silently
    collapse every such caller into one bucket -- the exact failure this
    replaces.
    """
    token = get_access_token()
    return token.client_id if token is not None else OPERATOR_IDENTITY


def _vocab_instructions(index: ServingIndex, coverage_active: bool = False) -> str:
    keys = ", ".join(sorted(index.key_since))
    coverage_sentence = (
        " When absence_state is no_documents or absence_not_yet_meaningful, you MAY "
        "OFFER the user a coverage request (request_coverage) -- never file one "
        "without the user's explicit yes. When the user disputes a served value, you "
        "MAY OFFER to file a claim report (report_claim, using the served claim id) "
        "-- never file one without the user's explicit yes."
        if coverage_active
        else ""
    )
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
        + coverage_sentence
    )


def create_server(
    root: str | Path | None = None,
    corpus: str | Path | None = None,
    transport: Transport | None = None,
    coverage: CoverageQueue | None = None,
    reports: ReportQueue | None = None,
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

    # Resolved before the instructions are built: the offer-only sentences
    # appear exactly when the tools they name are registered. The report
    # queue exists exactly when the coverage queue does -- one gate, one
    # repo, one PAT -- and shares its client and its DailyCap. Sharing the
    # cap object is not sharing a budget: the cap keys on the caller, so
    # each OAuth client and the operator each get their own, and the two
    # queues draw from that caller's single daily allowance.
    queue = coverage if coverage is not None else coverage_from_env()
    report_queue = reports if reports is not None else reports_from_queue(queue)

    mcp = FastMCP("ocm-claims", instructions=_vocab_instructions(index, coverage_active=queue is not None), **settings)

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

    # ADR-0036 D1 as amended: request_coverage exists only when its
    # credentials are configured -- a session without them sees the three
    # serving tools and nothing broken. The queue is NOT the registry:
    # coverage.py imports no index, workspace, or claims path.
    if queue is not None:
        @mcp.tool(description=(
            "File a coverage request when the store cannot answer (absence_state "
            "no_documents or absence_not_yet_meaningful) AND the user has said yes -- "
            "offer first, never file unasked. manufacturer + part_number are a complete "
            "request; source_url is optional context (vendor logins gate many), and no "
            "files are accepted. Repeat requests deduplicate onto one public issue whose "
            "URL is returned either way."
        ))
        def request_coverage(
            manufacturer: str,
            part_number: str,
            source_url: str | None = None,
            note: str | None = None,
        ) -> dict[str, Any]:
            return queue.request(
                manufacturer,
                part_number,
                source_url=source_url,
                note=note,
                client_id=_caller_identity(),
            )

        print(f"ocm-claims: request_coverage active (queue: {queue.repo})", file=sys.stderr)
    else:
        print(
            f"ocm-claims: request_coverage inactive ({COVERAGE_TOKEN_ENV}/{COVERAGE_REPO_ENV} unset)",
            file=sys.stderr,
        )

    # ADR-0037 D3: dispute intake, same gate and credentials as the
    # coverage queue. The unknown-id check lives HERE, where the read-only
    # index already is -- reports.py stays registry-free, checkably. No
    # tool writes a retraction; this one files the operator's homework.
    if report_queue is not None:
        @mcp.tool(description=(
            "Report a served claim value the user believes is wrong -- offer first, "
            "file only with the user's explicit yes. claim_id is required and must be "
            "an id this registry serves (every served value carries one); reason says "
            "what the cited page actually shows. Transcription errors get retracted "
            "and replaced; manufacturer misprints do not -- the erratum ingests as a "
            "new document. Repeat reports stack onto one public issue whose URL is "
            "returned either way."
        ))
        def report_claim(
            claim_id: str,
            reason: str,
            expected_value: str | None = None,
            note: str | None = None,
        ) -> dict[str, Any]:
            found = index.find_claim(claim_id)
            if found is None:
                return {
                    "status": "refused",
                    "reason": (
                        "no claim with this id is served by this registry. Copy the id from "
                        "a served value -- every value carries one -- and try again."
                    ),
                }
            document_hash, claim = found
            retraction = index.retraction_of(document_hash, claim_id)
            if retraction is not None:
                # Already handled: filing would queue the operator's own
                # finished work. The reporter gets the story instead.
                return {
                    "status": "already_retracted",
                    "reason": retraction.get("reason"),
                    **({"superseded_by": retraction["superseded_by"]} if "superseded_by" in retraction else {}),
                    "detail": "This claim is already retracted; nothing was filed.",
                }
            citation = claim.get("citation", {})
            return report_queue.report(
                claim_id,
                reason,
                expected_value=expected_value,
                note=note,
                client_id=_caller_identity(),
                key=str(claim.get("key", "")),
                document=document_hash,
                location=f"page {citation.get('page')}, {citation.get('locator')}",
            )

        print(f"ocm-claims: report_claim active (queue: {report_queue.repo})", file=sys.stderr)
    else:
        print(
            f"ocm-claims: report_claim inactive ({COVERAGE_TOKEN_ENV}/{COVERAGE_REPO_ENV} unset)",
            file=sys.stderr,
        )

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
