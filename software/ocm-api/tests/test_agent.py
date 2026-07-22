# SPDX-License-Identifier: AGPL-3.0-or-later
"""spec/09 "Agent orchestrator": the tool-use loop (tool call -> the real
in-process OcmApi facade -> envelope -> a real next turn), the toolset
scoping rule (component + discovery verbs only -- no cell, module-write,
or publish verb), and the AGENT_UNAVAILABLE degraded path. STEP-upload
fallback behavior lives in test_attachments.py.

The fake Anthropic client below models only the small slice of the SDK's
streaming shape `_stream_turn` actually reads (`messages.stream(...)` as a
context manager yielding content_block_delta events, then
`get_final_message()`) -- enough to exercise the real `_stream_turn`
function, not a hand-rolled substitute for it.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ocm_api import OcmApi
from ocm_api.agent import ALLOWED_MODELS, DEFAULT_MODEL, TOOL_DEFINITIONS, TOOL_NAMES, build_system_prompt, run_agent_chat
from ocm_api.envelope import Codes
from ocm_api.http_app import build_app


def _parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for chunk in body.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        event_line, data_line = chunk.split("\n", 1)
        assert event_line.startswith("event: ")
        assert data_line.startswith("data: ")
        events.append((event_line[len("event: "):], json.loads(data_line[len("data: "):])))
    return events


# ---------------------------------------------------------------------------
# Toolset scoping (spec/09: component + discovery verbs only)
# ---------------------------------------------------------------------------


def test_toolset_is_exactly_component_and_discovery_verbs_minus_publish():
    assert TOOL_NAMES == {
        "describe_schema", "get_example", "list_modules", "describe_module",
        "list_cells", "describe_cell", "list_frames",
        "create_component_draft", "update_component", "validate_component",
        "list_components", "describe_component",
    }


def test_toolset_excludes_cell_verbs():
    assert TOOL_NAMES.isdisjoint({"create_cell", "place_instance", "move_instance", "remove_instance", "set_plan", "set_joint_state"})


def test_toolset_excludes_module_write_verbs():
    assert TOOL_NAMES.isdisjoint({"create_module_draft", "update_module", "generate_geometry_stub", "publish_module"})


def test_toolset_excludes_publish_component():
    # Publishing is the one deliberate human-gated action in this
    # workflow (spec/10) -- the chat agent completing a draft and then
    # quietly publishing it itself would erase that checkpoint.
    assert "publish_component" not in TOOL_NAMES


def test_every_tool_definition_has_a_matching_ocm_api_method():
    api = OcmApi(".")
    for tool in TOOL_DEFINITIONS:
        assert callable(getattr(api, tool["name"], None)), f"OcmApi has no method {tool['name']!r}"


# ---------------------------------------------------------------------------
# System prompt: a component_id means the Components page already created
# that draft (its own "New draft" action, a direct REST call the agent
# never sees) before any chat message reaches the model -- the model must
# not re-discover this the hard way via an ALREADY_EXISTS refusal.
# ---------------------------------------------------------------------------


def test_system_prompt_tells_the_agent_the_draft_already_exists_when_scoped_to_one():
    prompt = build_system_prompt("com.example.ejector.demo1")
    assert "com.example.ejector.demo1" in prompt
    assert "already exists" in prompt
    assert "create_component_draft" in prompt
    assert "update_component" in prompt


def test_system_prompt_says_nothing_about_an_existing_draft_when_unscoped():
    prompt = build_system_prompt(None)
    assert "already exists" not in prompt


def test_system_prompt_requires_ending_with_a_write_not_just_discovery():
    # A real, observed failure mode: the model makes several legitimate
    # discovery calls (describe_schema, describe_component, get_example,
    # list_components) and then simply stops -- no update_component call,
    # no text. The doctrine already permits an incomplete draft; this is
    # the explicit instruction that gathering context is not itself the
    # deliverable.
    prompt = build_system_prompt("com.example.ejector.demo1")
    assert "MUST end by actually calling update_component" in prompt


# ---------------------------------------------------------------------------
# The tool-use loop: fake Anthropic CLIENT (not a faked stream_turn), so
# _stream_turn's own SDK-shape parsing is exercised for real, and the tool
# call lands on the real OcmApi facade for real.
# ---------------------------------------------------------------------------


class _FakeDelta:
    def __init__(self, type_: str, text: str | None = None):
        self.type = type_
        self.text = text


class _FakeStreamEvent:
    def __init__(self, type_: str, delta: _FakeDelta | None = None):
        self.type = type_
        self.delta = delta


class _FakeContentBlock:
    def __init__(self, type_: str, **fields: Any):
        self.type = type_
        for k, v in fields.items():
            setattr(self, k, v)
        self._fields = fields

    def model_dump(self) -> dict[str, Any]:
        return {"type": self.type, **self._fields}


class _FakeFinalMessage:
    def __init__(self, content: list[_FakeContentBlock], stop_reason: str):
        self.content = content
        self.stop_reason = stop_reason


class _FakeStreamContext:
    def __init__(self, events: list[_FakeStreamEvent], final: _FakeFinalMessage):
        self._events = events
        self._final = final

    def __enter__(self) -> "_FakeStreamContext":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def __iter__(self):
        return iter(self._events)

    def get_final_message(self) -> _FakeFinalMessage:
        return self._final


class _FakeMessages:
    def __init__(self, turns: list[_FakeStreamContext]):
        self._turns = list(turns)
        self.calls: list[dict[str, Any]] = []

    def stream(self, **kwargs: Any) -> _FakeStreamContext:
        # Snapshot `messages` -- it's the SAME list object run_agent_chat
        # keeps mutating (.append) after this call returns, so capturing
        # the live reference would make every recorded call's "messages"
        # silently reflect the LOOP'S FINAL state instead of what was
        # actually sent at call time.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self._turns.pop(0)


class _FakeClient:
    def __init__(self, turns: list[_FakeStreamContext]):
        self.messages = _FakeMessages(turns)


def _text_turn(text: str, stop_reason: str = "end_turn") -> _FakeStreamContext:
    events = [_FakeStreamEvent("content_block_delta", _FakeDelta("text_delta", text))]
    final = _FakeFinalMessage([_FakeContentBlock("text", text=text)], stop_reason)
    return _FakeStreamContext(events, final)


def _tool_use_turn(text: str, tool_id: str, tool_name: str, tool_input: dict[str, Any]) -> _FakeStreamContext:
    events = [_FakeStreamEvent("content_block_delta", _FakeDelta("text_delta", text))]
    final = _FakeFinalMessage(
        [_FakeContentBlock("text", text=text), _FakeContentBlock("tool_use", id=tool_id, name=tool_name, input=tool_input)],
        "tool_use",
    )
    return _FakeStreamContext(events, final)


def test_tool_call_reaches_the_real_facade_and_a_real_next_turn_follows(api: OcmApi):
    client = _FakeClient(
        [
            _tool_use_turn("Creating the draft now.", "t1", "create_component_draft", {"id": "com.example.agent-demo", "kind": "sensor"}),
            _text_turn("Done -- the draft exists."),
        ]
    )

    events = _parse_sse("".join(run_agent_chat(client, api, [{"role": "user", "content": "Start a draft for this sensor."}])))

    kinds = [e for e, _ in events]
    assert kinds == ["text", "tool_call", "text", "done"]

    text1, tool_call, text2, _done = events
    assert text1[1]["delta"] == "Creating the draft now."
    assert tool_call[1]["name"] == "create_component_draft"
    assert tool_call[1]["ok"] is True
    assert tool_call[1]["refusal_count"] == 0
    assert tool_call[1]["envelope"]["data"]["id"] == "com.example.agent-demo"
    assert text2[1]["delta"] == "Done -- the draft exists."

    # The facade call was REAL, not mocked -- the draft genuinely exists
    # in this workspace now.
    assert api.workspace.component_exists("com.example.agent-demo")

    # And the tool RESULT (the envelope, not a summary of it) was fed back
    # as the next turn's own conversation -- proving "next turn" is real
    # continuation, not a restart.
    assert len(client.messages.calls) == 2
    second_call_messages = client.messages.calls[1]["messages"]
    tool_result_msg = second_call_messages[-1]
    assert tool_result_msg["role"] == "user"
    assert tool_result_msg["content"][0]["type"] == "tool_result"
    assert tool_result_msg["content"][0]["tool_use_id"] == "t1"
    assert json.loads(tool_result_msg["content"][0]["content"])["data"]["id"] == "com.example.agent-demo"


def test_a_refused_tool_call_still_streams_its_envelope_and_continues(api: OcmApi):
    # A patch against a component that was never create_component_draft'd
    # first -- a real NOT_FOUND refusal from the real facade (patching, as
    # opposed to a full manifest write, requires something to patch).
    client = _FakeClient(
        [
            _tool_use_turn(
                "Let me save that.", "t1", "update_component",
                {"id": "com.example.never-created", "patch": [{"op": "replace", "path": "/vendor", "value": "Acme"}]},
            ),
            _text_turn("That component doesn't have a draft yet -- want me to create one?"),
        ]
    )

    events = _parse_sse("".join(run_agent_chat(client, api, [{"role": "user", "content": "Set the vendor to Acme."}])))
    tool_call = next(data for kind, data in events if kind == "tool_call")

    assert tool_call["ok"] is False
    assert tool_call["refusal_count"] >= 1
    assert tool_call["envelope"]["refusals"][0]["code"] == Codes.NOT_FOUND


def test_a_model_call_failure_mid_stream_becomes_a_real_error_event_not_a_silent_hang(api: OcmApi):
    # Before the try/except around stream_turn existed, an exception here
    # (bad model id, dropped connection, anything the real Anthropic SDK
    # can raise) just ended the generator -- the SSE stream stopped with no
    # terminal event, so the frontend never learns anything went wrong and
    # is left showing whatever text already streamed, forever "streaming".
    def _raising_stream_turn(client: Any, *, model: str, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]):
        yield ("text", "I'll transcribe this now...")
        raise RuntimeError("model: claude-sonnet-4-6 not found")

    events = _parse_sse(
        "".join(run_agent_chat(object(), api, [{"role": "user", "content": "Transcribe this."}], stream_turn=_raising_stream_turn))
    )

    kinds = [e for e, _ in events]
    assert kinds == ["text", "error"]
    assert events[0][1]["delta"] == "I'll transcribe this now..."
    refusal = events[1][1]["envelope"]["refusals"][0]
    assert refusal["code"] == Codes.INVALID_ARGUMENT
    assert "claude-sonnet-4-6" in refusal["message"]


# ---------------------------------------------------------------------------
# Model selection
# ---------------------------------------------------------------------------


def test_default_model_is_used_when_the_caller_does_not_pick_one(api: OcmApi):
    seen: dict[str, Any] = {}

    def _capturing_stream_turn(client: Any, *, model: str, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]):
        seen["model"] = model
        return iter([("stop", {"tool_uses": [], "stop_reason": "end_turn", "assistant_content": []})])

    list(run_agent_chat(object(), api, [{"role": "user", "content": "hi"}], stream_turn=_capturing_stream_turn))

    assert seen["model"] == DEFAULT_MODEL


def test_a_requested_model_is_passed_through_to_stream_turn(api: OcmApi):
    seen: dict[str, Any] = {}

    def _capturing_stream_turn(client: Any, *, model: str, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]):
        seen["model"] = model
        return iter([("stop", {"tool_uses": [], "stop_reason": "end_turn", "assistant_content": []})])

    list(
        run_agent_chat(
            object(), api, [{"role": "user", "content": "hi"}], model="claude-opus-4-8", stream_turn=_capturing_stream_turn
        )
    )

    assert seen["model"] == "claude-opus-4-8"


def test_allowed_models_are_all_documented_with_a_label():
    assert DEFAULT_MODEL in ALLOWED_MODELS
    for model_id, label in ALLOWED_MODELS.items():
        assert isinstance(model_id, str) and model_id
        assert isinstance(label, str) and label


def test_response_only_fields_are_stripped_before_a_content_block_is_replayed_back_to_the_api(api: OcmApi):
    # Confirmed against the real Anthropic API: a response text block can
    # carry a field (here: `parsed_output`) this installed SDK version
    # doesn't declare -- the SDK's base model allows unknown fields for
    # forward compatibility, so model_dump() faithfully includes it. The
    # instant that gets replayed back as conversation history on the next
    # turn, the API's own request-side schema rejects the whole call:
    # "Extra inputs are not permitted". Only the known-safe input fields
    # per block type may survive the round trip.
    noisy_text_block = _FakeContentBlock("text", text="Noting the vendor.", parsed_output={"junk": "field"})
    tool_block = _FakeContentBlock("tool_use", id="t1", name="list_components", input={})
    turn1 = _FakeStreamContext([], _FakeFinalMessage([noisy_text_block, tool_block], "tool_use"))
    client = _FakeClient([turn1, _text_turn("Done.")])

    events = _parse_sse("".join(run_agent_chat(client, api, [{"role": "user", "content": "Transcribe this."}])))
    assert [e for e, _ in events][-1] == "done"

    second_call_messages = client.messages.calls[1]["messages"]
    assistant_msg = second_call_messages[-2]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["content"] == [
        {"type": "text", "text": "Noting the vendor."},
        {"type": "tool_use", "id": "t1", "name": "list_components", "input": {}},
    ]


def test_a_refusal_stop_reason_becomes_a_real_error_event_not_a_silent_done(api: OcmApi):
    # "refusal" is a real, documented Anthropic stop_reason (the model
    # declining to continue) -- distinct from an exception, and previously
    # treated exactly like an ordinary successful completion.
    client = _FakeClient([_FakeStreamContext([], _FakeFinalMessage([], "refusal"))])

    events = _parse_sse("".join(run_agent_chat(client, api, [{"role": "user", "content": "Transcribe this."}])))

    kinds = [e for e, _ in events]
    assert kinds == ["error"]
    refusal = events[0][1]["envelope"]["refusals"][0]
    assert refusal["code"] == Codes.INVALID_ARGUMENT
    assert "refusal" in refusal["message"]


def test_a_turn_that_ends_with_no_tool_use_and_no_text_gets_a_fallback_message(api: OcmApi):
    # Reproduces a real observed failure: several successful discovery tool
    # calls, then a final turn with stop_reason=end_turn, no tool_use, and
    # no text at all -- previously indistinguishable from a clean, quiet
    # "I'm satisfied, done" completion.
    silent_tool_use = _FakeStreamContext(
        [], _FakeFinalMessage([_FakeContentBlock("tool_use", id="t1", name="list_components", input={})], "tool_use")
    )
    client = _FakeClient([silent_tool_use, _FakeStreamContext([], _FakeFinalMessage([], "end_turn"))])

    events = _parse_sse("".join(run_agent_chat(client, api, [{"role": "user", "content": "Transcribe this."}])))

    kinds = [e for e, _ in events]
    assert kinds == ["tool_call", "text", "done"]
    assert "stopped without writing anything" in events[1][1]["delta"]


def test_loop_terminates_and_reports_itself_if_the_model_never_stops_calling_tools(api: OcmApi):
    # MAX_TOOL_TURNS+1 tool-use turns, all of the same harmless read-only
    # call, so the loop can't finish on its own -- must self-terminate.
    turns = [_tool_use_turn("checking...", f"t{i}", "list_components", {}) for i in range(20)]
    client = _FakeClient(turns)

    events = _parse_sse("".join(run_agent_chat(client, api, [{"role": "user", "content": "loop forever"}])))
    assert events[-1][0] == "error"
    assert events[-1][1]["envelope"]["refusals"][0]["code"] == Codes.INVALID_ARGUMENT
    assert "tool-call turns" in events[-1][1]["envelope"]["refusals"][0]["message"]


# ---------------------------------------------------------------------------
# AGENT_UNAVAILABLE
# ---------------------------------------------------------------------------


def test_agent_chat_returns_agent_unavailable_when_api_key_is_unset(workspace_root, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = TestClient(build_app(str(workspace_root)))

    response = client.post("/agent/chat", json={"messages": [{"role": "user", "content": "hi"}]})

    assert response.status_code == 200  # SSE itself always 200s -- the refusal is IN the stream, not the transport
    events = _parse_sse(response.text)
    assert events[0][0] == "error"
    assert events[0][1]["envelope"]["refusals"][0]["code"] == Codes.AGENT_UNAVAILABLE


def test_agent_chat_does_not_reach_anthropic_at_all_when_unavailable(workspace_root, monkeypatch: pytest.MonkeyPatch):
    # Belt-and-suspenders on the above: even if some OTHER process in this
    # environment happens to export a real key, this test's own explicit
    # deletion must be what the route sees -- assert against os.environ
    # directly so a real key elsewhere in CI can't silently mask a broken
    # AGENT_UNAVAILABLE check.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert "ANTHROPIC_API_KEY" not in os.environ
    client = TestClient(build_app(str(workspace_root)))
    response = client.post("/agent/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert "AGENT_UNAVAILABLE" in response.text


# ---------------------------------------------------------------------------
# /agent/models, and /agent/chat's own model validation (HTTP layer)
# ---------------------------------------------------------------------------


def test_agent_models_lists_every_allowed_model_and_the_default(workspace_root):
    client = TestClient(build_app(str(workspace_root)))
    response = client.get("/agent/models")

    assert response.status_code == 200
    body = response.json()
    assert body["default"] == DEFAULT_MODEL
    assert {row["id"] for row in body["models"]} == set(ALLOWED_MODELS)


def test_agent_chat_rejects_an_unknown_model_before_ever_checking_for_an_api_key(workspace_root, monkeypatch: pytest.MonkeyPatch):
    # No ANTHROPIC_API_KEY is set here either -- an invalid model is a bad
    # request regardless of whether the server could otherwise reach
    # Anthropic, so it must be caught first, not masked by AGENT_UNAVAILABLE.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = TestClient(build_app(str(workspace_root)))

    response = client.post("/agent/chat", json={"messages": [{"role": "user", "content": "hi"}], "model": "gpt-not-a-claude-model"})

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert events[0][0] == "error"
    refusal = events[0][1]["envelope"]["refusals"][0]
    assert refusal["code"] == Codes.INVALID_ARGUMENT
    assert "gpt-not-a-claude-model" in refusal["message"]
    assert set(refusal["allowed"]["values"]) == set(ALLOWED_MODELS)
