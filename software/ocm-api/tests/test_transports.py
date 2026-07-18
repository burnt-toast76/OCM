# SPDX-License-Identifier: AGPL-3.0-or-later
"""All three clients (library, MCP, HTTP) must produce byte-identical
refusal-shaped responses for identical calls (this turn's explicit
requirement). "Byte-identical" is checked as canonical-JSON equality
(`json.dumps(..., sort_keys=True)`) rather than literal transport bytes,
since indentation/compactness legitimately differs across transports but
content must not.
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ocm_api.http_app import build_app
from ocm_api.mcp_server import build_server


def _canon(d: dict[str, Any]) -> str:
    return json.dumps(d, sort_keys=True)


def _mcp_call(server, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    _content, structured = asyncio.run(server.call_tool(tool, args))
    return structured


@pytest.fixture
def transports(workspace_root: Path):
    from ocm_api import OcmApi

    lib = OcmApi(workspace_root)
    mcp = build_server(str(workspace_root))
    http = TestClient(build_app(str(workspace_root)))
    return lib, mcp, http


def _assert_all_equal(
    transports,
    lib_envelope,
    mcp_tool: str,
    mcp_args: dict[str, Any],
    http_method: str,
    http_path: str,
    http_kwargs: dict[str, Any],
) -> None:
    _lib, mcp, http = transports

    lib_json = _canon(lib_envelope.to_dict())

    mcp_result = _mcp_call(mcp, mcp_tool, mcp_args)
    mcp_json = _canon(mcp_result)

    http_response = getattr(http, http_method)(http_path, **http_kwargs)
    assert http_response.status_code == 200
    http_json = _canon(http_response.json())

    assert lib_json == mcp_json, f"library vs MCP mismatch:\n{lib_json}\n!=\n{mcp_json}"
    assert lib_json == http_json, f"library vs HTTP mismatch:\n{lib_json}\n!=\n{http_json}"


def test_happy_path_list_modules_identical_across_transports(transports):
    lib, _mcp, _http = transports
    envelope = lib.list_modules()
    assert envelope.ok

    _assert_all_equal(
        transports, envelope,
        "list_modules", {},
        "get", "/list_modules", {},
    )


def test_happy_path_describe_module_identical_across_transports(transports):
    lib, _mcp, _http = transports
    module_id = "com.accelsolutions.fixture.pneumatic-nest"
    envelope = lib.describe_module(module_id)
    assert envelope.ok

    _assert_all_equal(
        transports, envelope,
        "describe_module", {"id": module_id},
        "get", "/describe_module", {"params": {"id": module_id}},
    )


def test_refusal_not_found_identical_across_transports(transports):
    lib, _mcp, _http = transports
    envelope = lib.describe_module("com.does.not.exist")
    assert not envelope.ok

    _assert_all_equal(
        transports, envelope,
        "describe_module", {"id": "com.does.not.exist"},
        "get", "/describe_module", {"params": {"id": "com.does.not.exist"}},
    )


def test_refusal_param_out_of_bounds_identical_across_transports(transports):
    lib, _mcp, _http = transports
    lib.create_cell("txp-cell", "com.accelsolutions.base.frame1200@2.0.0")
    lib.place_instance(
        "txp-cell", "sd1", "com.accelsolutions.screwdriver.sd50@1.2.0",
        {"pose": {"xyz_mm": [400, 300, 0], "rpy_deg": [0, 0, 0]}},
    )
    plan = [{"step": "fasten", "module": "sd1", "op": "drive_screw", "params": {"torque_nm": 999.0, "depth_mm": 8.0}}]

    envelope = lib.set_plan("txp-cell", plan)
    assert not envelope.ok

    _assert_all_equal(
        transports, envelope,
        "set_plan", {"cell": "txp-cell", "plan": plan},
        "post", "/set_plan", {"json": {"cell": "txp-cell", "plan": plan}},
    )


def test_refusal_verified_by_stripped_identical_across_transports(transports):
    lib, _mcp, _http = transports
    lib.create_module_draft("com.example.txp.stamp", "end_effector")
    base_manifest = lib.describe_module("com.example.txp.stamp").data["manifest"]
    base_manifest["safety"] = {"verified_by": "Jane Doe", "verified_on": "2026-01-01"}

    # update_module's verified_by-stripping mutates the nested `safety`
    # dict in place, so each transport gets its own deep copy -- otherwise
    # the first (library) call would strip the field before the MCP/HTTP
    # calls ever see it.
    envelope = lib.update_module("com.example.txp.stamp", manifest=copy.deepcopy(base_manifest))
    assert not envelope.ok

    _assert_all_equal(
        transports, envelope,
        "update_module", {"id": "com.example.txp.stamp", "manifest": copy.deepcopy(base_manifest)},
        "post", "/update_module", {"json": {"id": "com.example.txp.stamp", "manifest": copy.deepcopy(base_manifest)}},
    )
