# SPDX-License-Identifier: AGPL-3.0-or-later
"""Who is calling: the operator's static token, or an OAuth client.

Step one shipped one credential -- a bearer token the operator minted by
hand and handed over out of band. That works for one operator and does
not scale to strangers: there is no way to tell two callers apart, no way
to revoke one without rotating everyone, and no way for a client that has
never met the operator to obtain a credential at all. This module adds
the second kind without removing the first.

The server's role is RESOURCE SERVER and nothing else (MCP authorization
spec, "Roles"). It verifies tokens and publishes protected-resource
metadata. It never issues a token, never hosts a login page, never stores
a user. Issuance belongs to WorkOS AuthKit, which is also where clients
register themselves -- so opening registration costs this process no code
at all.

Why the verification is written here rather than imported. The documented
FastMCP AuthKit integration (`fastmcp.server.auth.providers.workos`)
belongs to the STANDALONE FastMCP v2 package; this server runs the MCP
SDK's bundled FastMCP, which `pyproject.toml` pins deliberately
("mcp 2.0.0 removed mcp.server.fastmcp; migrate both packages together or
not at all"). Adopting that provider would mean a framework migration and
would take the single `auth=` slot a composite verifier needs. The SDK
already publishes RFC 9728 metadata and already answers 401 through
RequireAuthMiddleware; only JWT validation was missing, and that is the
part below.

Leaving the library's paved path means the classic JWT footguns are ours
to shut, so they are shut explicitly and tested explicitly rather than
left to a library default that a future version may change:

  * RS256 ONLY. The algorithm is checked against the token header before
    any verification, so `alg: none` and every HS* variant are refused by
    name -- the confused-deputy trick where a token signed with the
    PUBLIC key as an HMAC secret is presented as valid.
  * `aud` and `iss` are always verified, never optional. The MCP spec is
    explicit: a server MUST validate that a token was issued for it
    (RFC 8707), and MUST NOT accept or transit any other token. Without
    the audience check, a token minted for any other AuthKit resource
    would open this one.
  * `exp`, `iat`, `aud`, `iss` and `sub` are all REQUIRED to be present.
    A missing claim is a refusal, not a skipped check.
  * Clock skew leeway is small and fixed. Enough for ordinary NTP drift
    between two hosts, nowhere near enough to keep an expired token
    usable.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any, Protocol

import jwt
from jwt import PyJWKClient
from mcp.server.auth.provider import AccessToken, TokenVerifier

# The operator's cap identity. Deliberately NOT a plausible `sub`: AuthKit
# subjects are opaque single-token identifiers (`user_01H...`), and this
# contains spaces and parentheses, so no registered client can ever be
# issued a token that collides with the operator's daily budget. The
# collision would not be a security hole -- it is a quota bug -- but it
# would be an invisible one, so it is made impossible rather than
# unlikely.
OPERATOR_IDENTITY = "ocm-operator (static token)"

# RS256 is what AuthKit signs with, and the only algorithm this server
# will consider. A list of one, named once.
ALLOWED_ALGORITHMS = ("RS256",)

# Ordinary NTP drift between two hosts. Not a grace period.
CLOCK_SKEW_LEEWAY_SECONDS = 30

# Every claim the verifier refuses to proceed without. `sub` earns its
# place here for a reason beyond correctness: it is the per-client cap
# identity, so a token without one would silently share a budget.
REQUIRED_CLAIMS = ("exp", "iat", "aud", "iss", "sub")


class SigningKeyResolver(Protocol):
    """The JWKS lookup, narrowed to what the verifier needs.

    `PyJWKClient` satisfies it in production, fetching and caching the
    authorization server's keys. A test satisfies it with a fixture key
    and never touches the network -- which is the difference between
    testing this verifier and testing WorkOS's uptime.
    """

    def get_signing_key_from_jwt(self, token: str) -> Any: ...


@dataclass(frozen=True)
class OAuthConfig:
    """A COMPLETE OAuth configuration, or none at all.

    Half-configured is not a state this server runs in: see
    `server.resolve_transport`, where a partial configuration is a startup
    refusal rather than a silent fall back to bearer-only. An operator who
    set the issuer and forgot the audience has said what they wanted, and
    serving strangers with the audience check missing is not it.
    """

    issuer: str
    audience: str
    jwks_uri: str

    @property
    def accepted_issuers(self) -> tuple[str, ...]:
        """The configured issuer, with and without a trailing slash.

        An `iss` claim is compared by exact string, and an operator pastes
        what the console shows -- WorkOS's dashboard displays the AuthKit
        domain with a trailing slash while the tokens it mints carry the
        issuer without one. Configured with the slash, every token would
        then fail as "Invalid issuer": a 401 on a correctly signed,
        unexpired token minted for the right audience, which is about the
        worst symptom to debug from the outside.

        Accepting both spellings is tolerance about punctuation, not about
        identity. They name the same origin, and forging either still
        requires a key from that origin's JWKS -- so nothing an attacker
        could not already do becomes possible.
        """
        bare = self.issuer.rstrip("/")
        return (bare, bare + "/")

    @staticmethod
    def jwks_uri_for(issuer: str) -> str:
        """AuthKit publishes its keys at a fixed path under the domain
        that issues the tokens (WorkOS AuthKit MCP guide). Derived rather
        than configured so the two cannot drift apart, and overridable for
        an authorization server that publishes elsewhere."""
        return f"{issuer.rstrip('/')}/oauth2/jwks"


class StaticTokenVerifier(TokenVerifier):
    """One operator, one token, handed over out of band.

    Unchanged from step one in every particular that matters: the
    comparison is constant-time and runs over bytes, so a non-ASCII token
    is a wrong token rather than a TypeError, and "wrong token" costs the
    same whether the first character differed or the last.

    What changed is only the identity it reports. It is now one of two
    kinds of caller, and its name says which -- see OPERATOR_IDENTITY.
    """

    def __init__(self, token: str) -> None:
        self._token = token.encode("utf-8")

    async def verify_token(self, token: str) -> AccessToken | None:
        if not secrets.compare_digest(token.encode("utf-8"), self._token):
            return None
        # No scopes: an authenticated caller gets every tool this server
        # has (all read-only, the queues capped), so there is nothing to
        # subdivide. required_scopes stays empty to match.
        return AccessToken(token=token, client_id=OPERATOR_IDENTITY, scopes=[])


class AuthKitVerifier(TokenVerifier):
    """An OAuth access token issued by WorkOS AuthKit for THIS resource.

    Returns None for every failure, never raises: RequireAuthMiddleware
    turns None into the 401 the spec requires, and an exception escaping
    here would be a 500 telling a caller that their expired token broke
    the server.

    The reported `client_id` is the token's `sub`. That is the claim
    AuthKit's access tokens are documented to carry; `client_id` is not
    guaranteed to be present, so keying the daily caps on it would mean
    keying them on something that may not exist. `sub` is stable per
    authenticated identity, which is exactly what a per-client budget
    should follow.
    """

    def __init__(self, config: OAuthConfig, keys: SigningKeyResolver | None = None) -> None:
        self._config = config
        # cache_keys: a JWKS fetch per request would put WorkOS in the
        # path of every call and rate-limit us into 401s that look like
        # bad tokens.
        self._keys = keys if keys is not None else PyJWKClient(config.jwks_uri, cache_keys=True)

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            # The algorithm is read from the UNVERIFIED header and checked
            # first, on purpose. Passing `algorithms=` alone would already
            # refuse these, but only as a side effect of a library
            # default; naming the refusal makes `alg: none` and the
            # HS256-signed-with-the-public-key trick explicit failures
            # with tests that say so.
            algorithm = jwt.get_unverified_header(token).get("alg")
            if algorithm not in ALLOWED_ALGORITHMS:
                return None
            signing_key = self._keys.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(ALLOWED_ALGORITHMS),
                audience=self._config.audience,
                issuer=self._config.accepted_issuers,
                leeway=CLOCK_SKEW_LEEWAY_SECONDS,
                options={
                    "require": list(REQUIRED_CLAIMS),
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
        except Exception:
            # Every JWT failure is one answer to the caller -- invalid
            # token -- and the differences between them (expired, wrong
            # audience, unknown key) are exactly what an attacker would
            # like narrated back.
            return None

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            return None
        return AccessToken(token=token, client_id=subject, scopes=[])


class CompositeVerifier(TokenVerifier):
    """The operator's token first, then OAuth.

    Order is deliberate and cheap: the static comparison is constant-time
    and local, so trying it first costs nothing and keeps the operator's
    credential working when the IdP is down, misconfigured, or being
    migrated. That is the whole reason the static path survives -- an
    identity provider is a dependency, and the operator needs a way in
    that does not have one.

    A caller presenting an OAuth token pays one failed byte-comparison
    before JWT verification, which is not a cost worth reordering for.
    """

    def __init__(self, static: StaticTokenVerifier | None, oauth: AuthKitVerifier | None) -> None:
        if static is None and oauth is None:
            raise RuntimeError("a composite verifier with no verifiers would authenticate nobody")
        self._static = static
        self._oauth = oauth

    async def verify_token(self, token: str) -> AccessToken | None:
        if self._static is not None:
            operator = await self._static.verify_token(token)
            if operator is not None:
                return operator
        if self._oauth is not None:
            return await self._oauth.verify_token(token)
        return None
