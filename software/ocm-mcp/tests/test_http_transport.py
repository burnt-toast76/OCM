# SPDX-License-Identifier: AGPL-3.0-or-later
"""The remote transport (ADR-0036's "out of scope" sentence, now in
scope): streamable HTTP, one static bearer token, and the /health probe.

Two layers. The configuration tests are pure -- they pass a dict where
the environment would be, so the refusals are provable without binding a
port. The rest run a REAL server in a subprocess: the thing being
claimed is that an unauthenticated request over a socket gets a 401, and
an in-process app object with the middleware stack assembled by hand
would be a test of the assembly, not of what `python -m ocm_mcp.server`
actually starts.

The contract is not retested here -- test_golden_evals.py owns that.
What IS tested is that the envelope arriving over HTTP is the same
object the serving layer returns directly, which is the only claim
transport can falsify.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
import httpx
import pytest
from mcp import ClientSession

# The current spelling under the pinned mcp (ci/requirements.txt); the
# older `streamablehttp_client` alias still resolves but warns, and a
# DeprecationWarning on every CI run is how a suite stops being read.
from mcp.client.streamable_http import streamable_http_client

from ocm_mcp import get_claims
from ocm_mcp.server import MIN_TOKEN_CHARS, Transport, create_server, resolve_transport

REPO_ROOT = Path(__file__).resolve().parents[3]

# Generated per run, never committed and never reused: a token literal in
# a test file is a token somebody eventually pastes into a deployment.
TOKEN = secrets.token_urlsafe(48)


# --------------------------------------------------------------------
# Configuration: what the four variables mean, and what they refuse
# --------------------------------------------------------------------


def test_stdio_is_the_default():
    assert resolve_transport({}) == Transport(kind="stdio", host="0.0.0.0", port=8000, token=None)
    assert resolve_transport({}).run_argument == "stdio"


def test_stdio_ignores_the_token_entirely():
    # A pipe carries no Authorization header. A token set for some other
    # reason must not turn a local server into something it isn't, and
    # must not be carried around in a stdio Transport either.
    assert resolve_transport({"OCM_AUTH_TOKEN": "short"}) == Transport()
    assert resolve_transport({"OCM_TRANSPORT": "stdio", "OCM_AUTH_TOKEN": TOKEN}).token is None


def test_http_defaults_to_every_interface_on_8000():
    transport = resolve_transport({"OCM_TRANSPORT": "http", "OCM_AUTH_TOKEN": TOKEN})
    assert (transport.kind, transport.host, transport.port, transport.token) == ("http", "0.0.0.0", 8000, TOKEN)
    assert transport.run_argument == "streamable-http"


def test_http_honours_host_and_port():
    transport = resolve_transport(
        {"OCM_TRANSPORT": "http", "OCM_AUTH_TOKEN": TOKEN, "OCM_HOST": "127.0.0.1", "OCM_PORT": "9101"}
    )
    assert (transport.host, transport.port) == ("127.0.0.1", 9101)


@pytest.mark.parametrize(
    "env",
    [
        pytest.param({"OCM_TRANSPORT": "http"}, id="unset"),
        pytest.param({"OCM_TRANSPORT": "http", "OCM_AUTH_TOKEN": ""}, id="empty"),
        pytest.param({"OCM_TRANSPORT": "http", "OCM_AUTH_TOKEN": "x" * (MIN_TOKEN_CHARS - 1)}, id="one-short"),
    ],
)
def test_http_without_a_long_enough_token_refuses(env):
    with pytest.raises(RuntimeError, match="OCM_AUTH_TOKEN"):
        resolve_transport(env)


def test_the_floor_is_reachable():
    # The refusal is a floor, not a moat: exactly MIN_TOKEN_CHARS passes,
    # so a test proving refusal can't be passing for the wrong reason.
    assert resolve_transport({"OCM_TRANSPORT": "http", "OCM_AUTH_TOKEN": "x" * MIN_TOKEN_CHARS}).kind == "http"


def test_an_unknown_transport_is_refused_not_ignored():
    with pytest.raises(RuntimeError, match="not a transport"):
        resolve_transport({"OCM_TRANSPORT": "streamable-http"})


def test_an_unparseable_port_is_refused():
    with pytest.raises(RuntimeError, match="OCM_PORT"):
        resolve_transport({"OCM_TRANSPORT": "http", "OCM_AUTH_TOKEN": TOKEN, "OCM_PORT": "eight thousand"})


def test_create_server_refuses_a_tokenless_http_transport_too():
    # Belt and braces: resolve_transport is the gate an operator meets,
    # but a caller constructing Transport by hand must not be able to
    # build an unauthenticated HTTP server either.
    with pytest.raises(RuntimeError, match="OCM_AUTH_TOKEN"):
        create_server(REPO_ROOT, "", transport=Transport(kind="http", token=None))


def test_an_ipv6_host_still_builds():
    # The AuthSettings issuer URL is derived from OCM_HOST; a literal IPv6
    # address needs brackets, and losing an `OCM_HOST=::` deployment to a
    # URL nothing ever serves would be a silly way to fail.
    server = create_server(REPO_ROOT, "", transport=Transport(kind="http", host="::", token=TOKEN))
    assert server.settings.host == "::"


def test_stdio_builds_the_server_it_always_built():
    server = create_server(REPO_ROOT, "", transport=Transport())
    assert server.settings.auth is None
    assert {tool.name for tool in anyio.run(server.list_tools)} == {"get_claims", "search_parts", "get_document"}


# --------------------------------------------------------------------
# A real server on a real socket
# --------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _server_env(**overrides: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("OCM_TRANSPORT", "OCM_AUTH_TOKEN", "OCM_HOST", "OCM_PORT")}
    # The public checkout alone, whatever the developer's own OCM_CORPUS
    # says -- these assertions name serving_state and corpus_state.
    env |= {"OCM_ROOT": str(REPO_ROOT), "OCM_CORPUS": "", "PYTHONUNBUFFERED": "1"}
    return env | overrides


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """`python -m ocm_mcp.server` with OCM_TRANSPORT=http, exactly as the
    README tells an operator to start it."""
    port = _free_port()
    log = tmp_path_factory.mktemp("server") / "ocm-claims.log"
    env = _server_env(OCM_TRANSPORT="http", OCM_AUTH_TOKEN=TOKEN, OCM_HOST="127.0.0.1", OCM_PORT=str(port))
    base = f"http://127.0.0.1:{port}"
    with log.open("w", encoding="utf-8") as sink:
        process = subprocess.Popen(
            [sys.executable, "-m", "ocm_mcp.server"], env=env, stdout=sink, stderr=subprocess.STDOUT
        )
        try:
            _wait_until_listening(process, base, log)
            yield base
        finally:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:  # pragma: no cover -- a wedged server
                process.kill()


def _wait_until_listening(process: subprocess.Popen, base: str, log: Path) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process.poll() is not None:  # pragma: no cover -- startup failure
            pytest.fail(f"server exited {process.returncode} before listening:\n{log.read_text(encoding='utf-8')}")
        try:
            if httpx.get(f"{base}/health", timeout=5).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.25)
    process.kill()  # pragma: no cover -- startup timeout
    pytest.fail(f"server never answered /health:\n{log.read_text(encoding='utf-8')}")


def _initialize(base: str, **headers: str) -> httpx.Response:
    """A bare MCP initialize POST, for the cases where the answer must be
    a 401 -- RequireAuthMiddleware refuses before the body is read, so no
    session is needed to prove it."""
    return httpx.post(
        f"{base}/mcp",
        headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json", **headers},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "ocm-mcp-tests", "version": "0"},
            },
        },
        timeout=30,
    )


@asynccontextmanager
async def _session(base: str, token: str):
    """A real MCP client session over streamable HTTP, authorized the way
    a remote client is: the token in an Authorization header."""
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(headers=headers, timeout=30) as http_client:
        async with streamable_http_client(f"{base}/mcp", http_client=http_client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


async def _tool_names(base: str, token: str) -> list[str]:
    async with _session(base, token) as session:
        return sorted(tool.name for tool in (await session.list_tools()).tools)


async def _call(base: str, token: str, name: str, arguments: dict) -> dict:
    async with _session(base, token) as session:
        result = await session.call_tool(name, arguments)
        assert not result.isError, result.content
        return json.loads(result.content[0].text)


def test_health_answers_without_a_token(live_server, shared_index):
    response = httpx.get(f"{live_server}/health", timeout=30)
    assert response.status_code == 200
    # Exactly D8's two identifiers plus the liveness word -- an
    # unauthenticated endpoint that grows a field grows an audience.
    assert response.json() == {
        "status": "ok",
        "serving_state": shared_index.serving_state,
        "corpus_state": None,
    }


def test_an_anonymous_request_is_refused(live_server):
    assert _initialize(live_server).status_code == 401


def test_a_wrong_token_is_refused(live_server):
    assert _initialize(live_server, Authorization=f"Bearer {secrets.token_urlsafe(48)}").status_code == 401


def test_a_near_miss_token_is_still_a_wrong_token(live_server):
    # Same length, one character different -- the constant-time
    # comparison gives it the same answer as any other wrong token.
    assert _initialize(live_server, Authorization=f"Bearer {TOKEN[:-1]}~").status_code == 401


def test_a_prefix_of_the_token_is_refused(live_server):
    assert _initialize(live_server, Authorization=f"Bearer {TOKEN[:-1]}").status_code == 401


def test_the_scheme_matters(live_server):
    assert _initialize(live_server, Authorization=TOKEN).status_code == 401


def test_the_three_tools_are_unchanged_over_http(live_server):
    assert anyio.run(_tool_names, live_server, TOKEN) == ["get_claims", "get_document", "search_parts"]


def test_the_token_buys_the_ordinary_envelope(live_server, shared_index):
    # The whole point of a transport-independent contract: what comes
    # back over the socket is what the serving layer returns in-process,
    # citations, states and all.
    over_http = anyio.run(_call, live_server, TOKEN, "get_claims", {"part_number": "EPS25-100WC-1001"})
    direct = json.loads(json.dumps(get_claims(shared_index, "EPS25-100WC-1001")))
    assert over_http == direct
    assert over_http["serving_state"] == shared_index.serving_state
    assert over_http["corpus_state"] is None


def test_an_absence_state_survives_the_transport(live_server, shared_index):
    over_http = anyio.run(_call, live_server, TOKEN, "get_claims", {"part_number": "no-such-part-at-all"})
    assert over_http == json.loads(json.dumps(get_claims(shared_index, "no-such-part-at-all")))


# --------------------------------------------------------------------
# The mode that must not exist
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    [pytest.param(None, id="unset"), pytest.param("x" * (MIN_TOKEN_CHARS - 1), id="one-short")],
)
def test_the_process_exits_rather_than_serving_http_unauthenticated(token):
    env = _server_env(OCM_TRANSPORT="http", OCM_HOST="127.0.0.1", OCM_PORT=str(_free_port()))
    if token is not None:
        env["OCM_AUTH_TOKEN"] = token
    finished = subprocess.run(
        [sys.executable, "-m", "ocm_mcp.server"], env=env, capture_output=True, text=True, timeout=180
    )
    assert finished.returncode != 0
    assert "OCM_AUTH_TOKEN" in finished.stderr
    assert "no unauthenticated HTTP mode" in finished.stderr
    # The refusal is a message, not a traceback.
    assert "Traceback" not in finished.stderr
