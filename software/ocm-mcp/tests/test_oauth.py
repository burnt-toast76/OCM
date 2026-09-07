# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phase-two auth: two credential kinds, per-caller caps, and the JWT
footguns nailed shut.

The provider is mocked, deliberately and completely: an RSA key is
generated per run and handed to the verifier as its signing-key resolver,
so every token here is one this suite minted. Nothing reaches WorkOS.
That is the point -- these tests must fail when OUR verification is
wrong, and must not fail when someone else's uptime is.

The negative cases are the valuable half. A JWT verifier that accepts a
valid token is easy; one that refuses `alg: none`, refuses an HS256 token
signed with the public key as its secret, and refuses a token minted for a
different audience on the same authorization server is the whole job.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

import anyio
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from ocm_mcp.auth import (
    OPERATOR_IDENTITY,
    AuthKitVerifier,
    CompositeVerifier,
    OAuthConfig,
    StaticTokenVerifier,
)
from ocm_mcp.coverage import DailyCap
from ocm_mcp.server import (
    MIN_TOKEN_CHARS,
    OAUTH_AUDIENCE_ENV,
    OAUTH_ISSUER_ENV,
    OAUTH_JWKS_ENV,
    Transport,
    resolve_transport,
)

ISSUER = "https://cellwright-test-00000.authkit.app"
AUDIENCE = "https://mcp.cellwright.ai/mcp"
OPERATOR_TOKEN = "o" * (MIN_TOKEN_CHARS + 16)


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, key.public_key()


@dataclass
class StaticKeys:
    """The JWKS lookup, satisfied by one fixed key.

    PyJWKClient's shape without PyJWKClient's network: the verifier asks
    for a signing key and gets this one, whatever `kid` the token names.
    """

    public_key: Any

    def get_signing_key_from_jwt(self, token: str) -> Any:
        return self

    @property
    def key(self) -> Any:
        return self.public_key


@pytest.fixture
def verifier(keypair):
    _, public = keypair
    config = OAuthConfig(issuer=ISSUER, audience=AUDIENCE, jwks_uri=OAuthConfig.jwks_uri_for(ISSUER))
    return AuthKitVerifier(config, keys=StaticKeys(public))


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _token(keypair, *, algorithm="RS256", key=None, **claims: Any) -> str:
    private, _ = keypair
    now = int(time.time())
    payload = {
        "sub": "user_01TESTSUBJECT",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 300,
        **claims,
    }
    signing_key = key if key is not None else private
    return jwt.encode(payload, signing_key, algorithm=algorithm)


def _verify(verifier, token: str):
    return anyio.run(verifier.verify_token, token)


# --------------------------------------------------------------------
# The happy path, and what identity it reports
# --------------------------------------------------------------------


def test_a_valid_token_authenticates(verifier, keypair):
    access = _verify(verifier, _token(keypair))
    assert access is not None
    assert access.scopes == []  # no scope subdivision in v1


def test_the_reported_identity_is_the_subject_not_the_client_id(verifier, keypair):
    """`sub` is the claim AuthKit's access tokens are documented to carry;
    `client_id` is not guaranteed. Keying caps on an absent claim would
    silently collapse every such caller into one bucket."""
    access = _verify(verifier, _token(keypair, sub="user_01ALICE", client_id="client_ignored"))
    assert access is not None and access.client_id == "user_01ALICE"


def test_a_token_without_a_subject_is_refused(verifier, keypair):
    """No subject means no cap identity, so it is refused rather than
    quietly bucketed with somebody else."""
    now = int(time.time())
    private, _ = keypair
    token = jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 300}, private, algorithm="RS256"
    )
    assert _verify(verifier, token) is None


# --------------------------------------------------------------------
# The 401 set
# --------------------------------------------------------------------


def test_an_expired_token_is_refused(verifier, keypair):
    now = int(time.time())
    assert _verify(verifier, _token(keypair, iat=now - 7200, exp=now - 3600)) is None


def test_the_skew_leeway_does_not_forgive_an_expired_token(verifier, keypair):
    """Leeway is for NTP drift between two hosts, not a grace period."""
    now = int(time.time())
    assert _verify(verifier, _token(keypair, exp=now - 600)) is None


def test_a_token_for_another_audience_is_refused(verifier, keypair):
    """The confused-deputy case the MCP spec names: a token minted for a
    DIFFERENT resource on the SAME authorization server, correctly signed
    by a key this server trusts, must not open this one (RFC 8707)."""
    assert _verify(verifier, _token(keypair, aud="https://someone-elses-mcp.example.com/mcp")) is None


def test_a_token_from_another_issuer_is_refused(verifier, keypair):
    assert _verify(verifier, _token(keypair, iss="https://attacker.authkit.app")) is None


def test_an_unsigned_alg_none_token_is_refused(verifier, keypair):
    """The oldest JWT footgun. Refused on the header, before any
    verification is attempted."""
    now = int(time.time())
    unsigned = jwt.encode(
        {"sub": "user_01ALICE", "iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 300},
        key=None,
        algorithm="none",
    )
    assert _verify(verifier, unsigned) is None


def test_an_hs256_token_signed_with_the_public_key_is_refused(verifier, keypair):
    """The algorithm-confusion attack, exactly as it is performed: take
    the PUBLIC key -- which anyone can fetch from the JWKS -- and use it
    as an HMAC secret. Refused because RS256 is the only algorithm this
    server will consider."""
    _, public = keypair
    pem = public.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    # Assembled by hand rather than with jwt.encode, because PyJWT refuses
    # to SIGN this ("asymmetric key ... should not be used as an HMAC
    # secret") -- a guard rail on the encoding side that an attacker
    # simply does not use. The token below is what actually arrives.
    now = int(time.time())
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url(
        json.dumps({"sub": "user_01MALLORY", "iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 300}).encode()
    )
    signing_input = f"{header}.{payload}".encode()
    signature = _b64url(hmac.new(pem, signing_input, hashlib.sha256).digest())
    forged = f"{header}.{payload}.{signature}"

    assert _verify(verifier, forged) is None


def test_a_token_signed_by_an_unknown_key_is_refused(verifier):
    stranger = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    token = jwt.encode(
        {"sub": "user_01MALLORY", "iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 300},
        stranger,
        algorithm="RS256",
    )
    assert _verify(verifier, token) is None


@pytest.mark.parametrize("garbage", ["", "not-a-jwt", "a.b.c", "Bearer eyJ"])
def test_garbage_is_refused_without_raising(verifier, garbage):
    """A malformed token is a 401, never a 500 telling the caller their
    input reached an exception handler."""
    assert _verify(verifier, garbage) is None


# --------------------------------------------------------------------
# The composite: the operator's token survives
# --------------------------------------------------------------------


@pytest.fixture
def composite(verifier):
    return CompositeVerifier(StaticTokenVerifier(OPERATOR_TOKEN), verifier)


def test_the_operator_token_still_works_alongside_oauth(composite):
    access = _verify(composite, OPERATOR_TOKEN)
    assert access is not None and access.client_id == OPERATOR_IDENTITY


def test_an_oauth_token_works_through_the_composite(composite, keypair):
    access = _verify(composite, _token(keypair, sub="user_01ALICE"))
    assert access is not None and access.client_id == "user_01ALICE"


def test_a_wrong_credential_of_neither_kind_is_refused(composite):
    assert _verify(composite, "x" * (MIN_TOKEN_CHARS + 16)) is None


def test_the_operator_identity_is_unreachable_by_any_subject(composite, keypair):
    """A registered client must never be able to spend the operator's
    daily allowance. The sentinel is not a plausible `sub`, and a token
    claiming it as one still reports it as that subject -- it does not
    become the operator."""
    access = _verify(composite, _token(keypair, sub=OPERATOR_IDENTITY))
    assert access is not None
    # It authenticated as a client, and the cap identity it carries is the
    # subject it presented -- but no AuthKit-issued `sub` can contain
    # spaces, so this token cannot exist outside this test.
    assert access.client_id == OPERATOR_IDENTITY
    assert _verify(composite, OPERATOR_TOKEN).client_id == OPERATOR_IDENTITY


def test_oauth_alone_authenticates_when_no_operator_token_is_configured(verifier, keypair):
    oauth_only = CompositeVerifier(None, verifier)
    assert _verify(oauth_only, _token(keypair)) is not None
    assert _verify(oauth_only, OPERATOR_TOKEN) is None


def test_the_operator_token_works_when_the_idp_is_unreachable(keypair):
    """The reason the static path survives at all: an identity provider is
    a dependency, and the operator needs a way in that does not have one."""

    class Unreachable:
        def get_signing_key_from_jwt(self, token: str):
            raise ConnectionError("the IdP is down")

    config = OAuthConfig(issuer=ISSUER, audience=AUDIENCE, jwks_uri=OAuthConfig.jwks_uri_for(ISSUER))
    composite = CompositeVerifier(StaticTokenVerifier(OPERATOR_TOKEN), AuthKitVerifier(config, keys=Unreachable()))

    assert _verify(composite, OPERATOR_TOKEN).client_id == OPERATOR_IDENTITY
    assert _verify(composite, _token(keypair)) is None  # and OAuth degrades to a 401, not a 500


def test_a_verifier_with_no_verifiers_is_refused_at_construction():
    with pytest.raises(RuntimeError):
        CompositeVerifier(None, None)


# --------------------------------------------------------------------
# Configuration: half-configured OAuth is a startup refusal
# --------------------------------------------------------------------


def _http_env(**extra: str) -> dict[str, str]:
    return {"OCM_TRANSPORT": "http", **extra}


def test_both_credential_kinds_together_is_the_expected_production_state():
    transport = resolve_transport(
        _http_env(OCM_AUTH_TOKEN=OPERATOR_TOKEN, **{OAUTH_ISSUER_ENV: ISSUER, OAUTH_AUDIENCE_ENV: AUDIENCE})
    )
    assert transport.token == OPERATOR_TOKEN
    assert transport.oauth == OAuthConfig(issuer=ISSUER, audience=AUDIENCE, jwks_uri=f"{ISSUER}/oauth2/jwks")


def test_oauth_alone_is_a_complete_configuration():
    transport = resolve_transport(_http_env(**{OAUTH_ISSUER_ENV: ISSUER, OAUTH_AUDIENCE_ENV: AUDIENCE}))
    assert transport.token is None and transport.oauth is not None


def test_the_operator_token_alone_is_still_a_complete_configuration():
    """Step one's deployment must keep starting, unchanged."""
    transport = resolve_transport(_http_env(OCM_AUTH_TOKEN=OPERATOR_TOKEN))
    assert transport == Transport(kind="http", host="0.0.0.0", port=8000, token=OPERATOR_TOKEN, oauth=None)


@pytest.mark.parametrize(
    "env,missing",
    [
        pytest.param({OAUTH_ISSUER_ENV: ISSUER}, OAUTH_AUDIENCE_ENV, id="issuer-without-audience"),
        pytest.param({OAUTH_AUDIENCE_ENV: AUDIENCE}, OAUTH_ISSUER_ENV, id="audience-without-issuer"),
        pytest.param({OAUTH_JWKS_ENV: f"{ISSUER}/oauth2/jwks"}, OAUTH_ISSUER_ENV, id="jwks-alone"),
    ],
)
def test_half_configured_oauth_refuses_at_startup(env, missing):
    """Not a silent fall back to bearer-only. A missing audience is the
    check that stops another resource's token from opening this one, so a
    server that looks configured and answers 401 to every OAuth client is
    the expensive kind of wrong."""
    with pytest.raises(RuntimeError) as refusal:
        resolve_transport(_http_env(OCM_AUTH_TOKEN=OPERATOR_TOKEN, **env))
    assert missing in str(refusal.value)


def test_half_configured_oauth_refuses_even_with_no_operator_token():
    with pytest.raises(RuntimeError):
        resolve_transport(_http_env(**{OAUTH_ISSUER_ENV: ISSUER}))


def test_http_with_neither_credential_kind_refuses():
    with pytest.raises(RuntimeError) as refusal:
        resolve_transport(_http_env())
    assert "no unauthenticated HTTP mode" in str(refusal.value)


def test_stdio_ignores_oauth_configuration_entirely():
    transport = resolve_transport({OAUTH_ISSUER_ENV: ISSUER, OAUTH_AUDIENCE_ENV: AUDIENCE})
    assert transport == Transport()


def test_the_jwks_uri_is_derived_from_the_issuer_and_overridable():
    assert OAuthConfig.jwks_uri_for(ISSUER) == f"{ISSUER}/oauth2/jwks"
    assert OAuthConfig.jwks_uri_for(ISSUER + "/") == f"{ISSUER}/oauth2/jwks"
    elsewhere = "https://keys.example.com/jwks.json"
    transport = resolve_transport(
        _http_env(**{OAUTH_ISSUER_ENV: ISSUER, OAUTH_AUDIENCE_ENV: AUDIENCE, OAUTH_JWKS_ENV: elsewhere})
    )
    assert transport.oauth.jwks_uri == elsewhere


# --------------------------------------------------------------------
# The caps finally mean per-client
# --------------------------------------------------------------------


def test_each_client_gets_its_own_daily_budget():
    cap = DailyCap(cap=2)
    assert cap.take("user_01ALICE") and cap.take("user_01ALICE")
    assert not cap.take("user_01ALICE")  # Alice is done
    assert cap.take("user_01BOB")  # Bob is untouched


def test_the_operator_budget_is_separate_from_every_client():
    cap = DailyCap(cap=1)
    assert cap.take("user_01ALICE")
    assert not cap.take("user_01ALICE")
    assert cap.take(OPERATOR_IDENTITY), "a client exhausting its cap must not spend the operator's"


def test_a_refund_returns_the_callers_own_take():
    cap = DailyCap(cap=1)
    assert cap.take("user_01ALICE")
    cap.refund("user_01ALICE")
    assert cap.take("user_01ALICE")
    assert not cap.take("user_01ALICE")


# --------------------------------------------------------------------
# A URL variable without a scheme is a refusal, not a traceback
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "env,named",
    [
        pytest.param(
            {OAUTH_ISSUER_ENV: "cellwright-12345.authkit.app", OAUTH_AUDIENCE_ENV: AUDIENCE},
            OAUTH_ISSUER_ENV,
            id="issuer-without-scheme",
        ),
        pytest.param(
            {OAUTH_ISSUER_ENV: ISSUER, OAUTH_AUDIENCE_ENV: "mcp.cellwright.ai/mcp"},
            OAUTH_AUDIENCE_ENV,
            id="audience-without-scheme",
        ),
        pytest.param(
            {
                OAUTH_ISSUER_ENV: ISSUER,
                OAUTH_AUDIENCE_ENV: AUDIENCE,
                OAUTH_JWKS_ENV: "keys.example.com/jwks.json",
            },
            OAUTH_JWKS_ENV,
            id="jwks-without-scheme",
        ),
    ],
)
def test_a_url_variable_without_a_scheme_refuses_and_names_itself(env, named):
    """The mistake an operator actually makes: WorkOS prints the AuthKit
    domain bare in places, and pasting it verbatim leaves a value that
    reads perfectly and has no scheme.

    Before this check it surfaced as `PyJWKClientError: Invalid JWKS URI
    scheme ''` with a traceback, naming neither the variable nor the fix
    -- and for the audience it would have been pydantic's vocabulary
    instead. Both are now one refusal that names the variable while the
    variable still has a name.
    """
    with pytest.raises(RuntimeError) as refusal:
        resolve_transport(_http_env(**env))
    message = str(refusal.value)
    assert named in message
    assert "absolute URL" in message


def test_the_refusal_shows_the_corrected_value():
    """A message an operator can act on without reading the source."""
    with pytest.raises(RuntimeError) as refusal:
        resolve_transport(_http_env(**{OAUTH_ISSUER_ENV: "cellwright.authkit.app", OAUTH_AUDIENCE_ENV: AUDIENCE}))
    assert "https://cellwright.authkit.app" in str(refusal.value)


def test_a_well_formed_configuration_is_untouched_by_the_check():
    transport = resolve_transport(_http_env(**{OAUTH_ISSUER_ENV: ISSUER, OAUTH_AUDIENCE_ENV: AUDIENCE}))
    assert transport.oauth.issuer == ISSUER and transport.oauth.audience == AUDIENCE


# --------------------------------------------------------------------
# The trailing slash, which the console shows and the tokens omit
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "configured", [ISSUER, ISSUER + "/"], ids=["configured-bare", "configured-with-slash"]
)
@pytest.mark.parametrize("in_token", [ISSUER, ISSUER + "/"], ids=["token-bare", "token-with-slash"])
def test_the_issuers_trailing_slash_does_not_decide_authentication(keypair, configured, in_token):
    """WorkOS's dashboard shows the AuthKit domain WITH a trailing slash and
    its tokens carry the issuer WITHOUT one. Configured as displayed, every
    token would fail as "Invalid issuer" -- a 401 on a correctly signed,
    unexpired token minted for the right audience, which is the worst kind
    of symptom to debug from outside."""
    _, public = keypair
    config = OAuthConfig(issuer=configured, audience=AUDIENCE, jwks_uri=OAuthConfig.jwks_uri_for(configured))
    verifier = AuthKitVerifier(config, keys=StaticKeys(public))
    assert _verify(verifier, _token(keypair, iss=in_token)) is not None


def test_a_different_issuer_is_still_refused_whatever_the_punctuation(verifier, keypair):
    """The tolerance is about punctuation, never about identity."""
    assert _verify(verifier, _token(keypair, iss="https://attacker.authkit.app/")) is None
    assert _verify(verifier, _token(keypair, iss=ISSUER + "x")) is None


def test_the_jwks_uri_ignores_a_trailing_slash_too():
    assert OAuthConfig(issuer=ISSUER + "/", audience=AUDIENCE, jwks_uri=OAuthConfig.jwks_uri_for(ISSUER + "/")).jwks_uri == f"{ISSUER}/oauth2/jwks"
