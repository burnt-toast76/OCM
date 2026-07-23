# SPDX-License-Identifier: AGPL-3.0-or-later
"""The /agent/chat orchestrator (spec/09 "Agent orchestrator"): an
Anthropic Messages API tool-use loop, tools bound IN-PROCESS to the
`OcmApi` facade -- a tool call never leaves this process, it's a plain
Python method call, same as any other verb's caller (ADR-0012: "the GUI
and the AI agent are clients of one API"; this is the one place that's
also literally true at the function-call level, not just the transport
level).

Toolset scoping is deliberate and load-bearing, not an oversight:
COMPONENT authoring + DISCOVERY verbs only. No cell verbs (this agent
never places or moves anything in a cell -- ADR-0012's GUI/agent split
for cell composition is a separate, later surface). No module-authoring
verbs (ADR-0014: a datasheet is never enough to author a MODULE, so the
component-transcription assistant has no way to even try). No
publish_component either, despite being a component verb: publishing is
the one deliberate, human-gated action in this workflow (spec/10: "the
human handoff") -- the Components page's checklist panel has its own
Publish button for exactly that reason, and this agent completing a
draft and then quietly publishing it on its own would erase the human
checkpoint spec/10 exists to create.

Streaming is its own small seam (`_stream_turn`) specifically so tests
can replace "call the real Anthropic API" with a fake generator that
yields the same two-tuple shape, without needing to replicate the SDK's
real streaming event objects.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Generator, Iterable
from typing import Any

from .api import OcmApi
from .envelope import Codes
from .prompts import DATASHEET_EXTRACTION_PROMPT, ZERO_ASSUMPTION_DOCTRINE

DEFAULT_MODEL = "claude-sonnet-5"
MAX_TOOL_TURNS = 8  # a hard ceiling -- a misbehaving loop reports itself instead of running forever

# The model choices this agent offers, restricted to the current, tool-
# capable Claude models -- deliberately excludes Fable 5, which targets
# creative writing, not schema-constrained JSON tool calls. Label text is
# for the Components page's own picker; id is the literal string sent to
# the Anthropic API, validated against this same dict before every call
# (Codes.INVALID_ARGUMENT, not a raw 400 from the API, for a typo'd or
# retired model id -- the same "surface it, don't swallow it" lesson the
# earlier stream_turn/parsed_output fixes exist for).
ALLOWED_MODELS: dict[str, str] = {
    "claude-sonnet-5": "Sonnet 5 (balanced, default)",
    "claude-opus-4-8": "Opus 4.8 (most capable, slower)",
    "claude-haiku-4-5-20251001": "Haiku 4.5 (fastest, lighter)",
}

# -- Tool schemas -------------------------------------------------------
# The FUNCTION signature Anthropic calls (arguments in, envelope out), not
# the component's own domain schema -- an agent discovers THAT at runtime
# by calling describe_schema, same as spec/09 tells any other agent.
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "describe_schema",
        "description": "The component JSON Schema (target='component', the default here -- this agent authors components, not modules), or one named section of it (e.g. 'electrical', 'pneumatic', 'comms'). Call this before guessing a field name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {"type": "string"},
                "target": {"type": "string", "enum": ["component", "module"], "description": "Defaults to 'component' -- only pass 'module' if get_example's own module manifest needs a schema section to interpret."},
            },
        },
    },
    {
        "name": "get_example",
        "description": "The best-matching real, committed module manifest for a kind (e.g. sensor, end_effector) -- worked examples ARE the documentation.",
        "input_schema": {"type": "object", "properties": {"kind": {"type": "string"}}, "required": ["kind"]},
    },
    {
        "name": "list_modules",
        "description": "Every module in the registry: id, revision, kind, name, draft status.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "describe_module",
        "description": "The full parsed manifest for one module id, including any derived component aggregates (BOM, power budget).",
        "input_schema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    },
    {
        "name": "list_cells",
        "description": "Every cell in the registry (read-only -- this agent never edits a cell).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "describe_cell",
        "description": "A resolved cell's composition (read-only).",
        "input_schema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    },
    {
        "name": "list_frames",
        "description": "Every referenceable frame in a resolved cell (read-only).",
        "input_schema": {"type": "object", "properties": {"cell_id": {"type": "string"}}, "required": ["cell_id"]},
    },
    {
        "name": "create_component_draft",
        "description": "THE entry point for transcribing a new datasheet -- scaffolds components/<id>/component.yaml with only ocm_version/id/revision/kind. Never invent vendor/source here; those get filled by update_component once you actually know them.",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "kind": {"type": "string"}},
            "required": ["id", "kind"],
        },
    },
    {
        "name": "update_component",
        "description": "Write a component definition -- a full replacement document (manifest) OR an RFC-6902 patch (patch), exactly one of the two. Always writes, even if invalid; validation gates publishing, not this call, so iterate freely.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "manifest": {"type": "object", "description": "A full replacement document."},
                "patch": {"type": "array", "items": {"type": "object"}, "description": "An RFC-6902 patch, instead of manifest."},
            },
            "required": ["id"],
        },
    },
    {
        "name": "validate_component",
        "description": "Full schema validation. The refusal list IS the human's completion list -- report it, don't try to silently satisfy it by guessing.",
        "input_schema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    },
    {
        "name": "list_components",
        "description": "Every component in the registry: id, revision, kind, vendor, draft status.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "describe_component",
        "description": "The full parsed component definition for one id.",
        "input_schema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    },
]

TOOL_NAMES: frozenset[str] = frozenset(t["name"] for t in TOOL_DEFINITIONS)


def build_system_prompt(component_id: str | None) -> str:
    subject = f"the component `{component_id}`" if component_id else "a component"
    draft_note = (
        f"\n\nA draft for `{component_id}` already exists -- the Components page always creates it "
        "(via its own \"New draft\" action) before you are ever asked to transcribe into it. Use "
        "update_component to write into it. Do NOT call create_component_draft for this id: it "
        "already exists, so that call will only be refused as ALREADY_EXISTS."
        if component_id
        else ""
    )
    action_note = (
        "\n\nGathering context first (describe_schema, get_example, describe_component) is fine and "
        "expected, but it is not the deliverable -- you MUST end by actually calling update_component "
        "with whatever you were able to transcribe, even if that's only one or two fields. A partial, "
        "honest write beats a well-informed silence: the doctrine above already tells you omission is "
        "the correct move for anything the source doesn't state, so schema strictness or an incomplete "
        "picture is never a reason to end the conversation without writing anything at all. If you "
        "truly cannot transcribe a single fact (e.g. no datasheet was actually attached), say so in "
        "words -- never just stop."
    )
    return (
        f"You are the OCM component-authoring assistant, embedded in the Components page, helping "
        f"transcribe a datasheet, manual, or catalog page into {subject}. You can only see and touch "
        "components and read-only discovery data through your tools -- you have no way to create or "
        "edit a cell or a module, and no way to publish a component yourself; that boundary is "
        "intentional (ADR-0012, ADR-0014), not a bug to route around."
        + draft_note
        + "\n\n"
        + ZERO_ASSUMPTION_DOCTRINE
        + action_note
        + "\n\n"
        + DATASHEET_EXTRACTION_PROMPT
    )


def _call_tool(api: OcmApi, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in TOOL_NAMES:
        # Unreachable in practice -- Anthropic can only return a tool_use
        # for a name from TOOL_DEFINITIONS -- kept as a defensive boundary
        # check, not a real branch this code expects to take.
        return {
            "ok": False,
            "refusals": [{"code": Codes.INVALID_ARGUMENT, "path": "$", "message": f"unknown tool {name!r}", "allowed": None, "hint": None}],
            "warnings": [],
            "data": None,
        }
    if name == "describe_schema":
        # describe_schema's OWN default (OcmApi.describe_schema) is
        # target="module", for backward compatibility with callers that
        # predate ADR-0014's component schema. This agent's entire domain
        # is components, so default to that HERE rather than trust every
        # model turn to remember to pass target explicitly -- a model that
        # omits it should still get the schema it's actually working
        # against, not silently fall back to the wrong artifact type.
        arguments = {"target": "component", **arguments}
    method = getattr(api, name)
    return method(**arguments).to_dict()


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _envelope_event(event: str, code: str, message: str, hint: str | None = None, allowed: Any = None) -> str:
    return _sse(
        event,
        {"envelope": {"ok": False, "refusals": [{"code": code, "path": "$", "message": message, "allowed": allowed, "hint": hint}], "warnings": [], "data": None}},
    )


def agent_unavailable_stream(reason: str) -> Iterable[str]:
    yield _envelope_event(
        "error", Codes.AGENT_UNAVAILABLE, reason, hint="Set ANTHROPIC_API_KEY in the ocm-api server's environment and restart it."
    )


def invalid_model_stream(model: str) -> Iterable[str]:
    yield _envelope_event(
        "error",
        Codes.INVALID_ARGUMENT,
        f"{model!r} is not one of this agent's allowed models",
        hint="Choose one of the models GET /agent/models returns.",
        allowed={"values": list(ALLOWED_MODELS)},
    )


def _to_input_content_block(block: Any) -> dict[str, Any]:
    """Re-serialize a RESPONSE content block into the shape the API's
    REQUEST-side schema actually accepts, rather than a raw `model_dump()`
    of whatever fields happened to be present. Confirmed live: a `text`
    block's response can carry a `parsed_output` field this SDK version
    doesn't declare (the SDK's base model allows unknown fields, for
    forward compatibility) -- `model_dump()` faithfully includes it, and
    the instant that gets round-tripped back as the next turn's own
    conversation history, the API rejects it outright: "Extra inputs are
    not permitted". Response-only fields (citations, parsed_output,
    whatever comes next) are exactly the kind of thing that keeps
    accumulating across a real multi-turn tool-use loop -- allowlisting
    the known-safe input fields per type is what makes this immune to the
    next one of these, not just this one.
    """
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    return block.model_dump()  # unreachable with this agent's own tool/thinking config, kept as a defensive fallback


def _stream_turn(
    client: Any, *, model: str, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
) -> Generator[tuple[str, Any], None, None]:
    """One model turn against the real Anthropic API. Yields ('text', str)
    for each text delta as it streams, then exactly one
    ('stop', {'tool_uses', 'stop_reason', 'assistant_content'}) once the
    turn completes. This is the ONLY function in this module that touches
    the Anthropic SDK's actual streaming object model -- run_agent_chat
    itself only depends on this two-tuple shape, which is what lets tests
    substitute a trivial fake generator instead (see tests/test_agent.py).
    """
    with client.messages.stream(model=model, max_tokens=4096, system=system, messages=messages, tools=tools) as stream:
        for event in stream:
            if event.type == "content_block_delta" and event.delta.type == "text_delta":
                yield ("text", event.delta.text)
        final = stream.get_final_message()

    tool_uses = [{"id": block.id, "name": block.name, "input": block.input} for block in final.content if block.type == "tool_use"]
    assistant_content = [_to_input_content_block(block) for block in final.content]
    yield ("stop", {"tool_uses": tool_uses, "stop_reason": final.stop_reason, "assistant_content": assistant_content})


StreamTurnFn = Callable[..., Iterable[tuple[str, Any]]]


def run_agent_chat(
    client: Any,
    api: OcmApi,
    messages: list[dict[str, Any]],
    *,
    component_id: str | None = None,
    model: str = DEFAULT_MODEL,
    stream_turn: StreamTurnFn = _stream_turn,
) -> Generator[str, None, None]:
    """The tool-use loop: stream text, and when the model asks for a tool,
    call it against `api` IN-PROCESS, emit a compact tool_call SSE event
    (name/ok/refusal_count -- spec/09: "so the UI can render chips") plus
    the full envelope for the UI's own expand-to-see-detail affordance,
    append the tool_result, and loop -- until the model stops asking for
    tools or MAX_TOOL_TURNS is hit.

    `stream_turn` itself is the one call that leaves this process (the real
    Anthropic API) -- a bad model id, a rate limit, a dropped connection,
    anything the SDK can raise, must not be allowed to kill this generator
    silently. Before this try/except existed, that kind of failure just
    ended the SSE stream mid-flight with no terminal event at all: the
    frontend's reader loop sees a plain end-of-stream (not an error), so it
    never fires onDone or onError -- the UI is left showing whatever text
    had already streamed (often just "I'll transcribe this now...") with
    chatStreaming stuck true forever. Turning it into a real `error` event
    is what lets the UI actually tell the user something went wrong instead
    of quietly doing nothing.

    Two more silent-completion traps, found by actually running this
    against a real multi-page datasheet: (1) `stop_reason` can legitimately
    come back as "refusal" (a real, documented value -- the model declining
    to continue, distinct from an exception), which used to be treated
    exactly like an ordinary "I'm done" and silently closed the stream. (2)
    A turn can end with `stop_reason: end_turn` and NO tool_use AND no text
    at all -- after several real, successful discovery tool calls
    (describe_schema, describe_component, get_example, list_components),
    the model can still simply stop without ever calling update_component
    or saying a word, which used to look identical to a clean, satisfied
    "done". Both cases now surface something a human can actually read,
    instead of an empty transcript that looks hung.
    """
    system = build_system_prompt(component_id)
    conversation = list(messages)
    any_text_emitted = False

    for _turn in range(MAX_TOOL_TURNS):
        tool_uses: list[dict[str, Any]] = []
        stop_reason = "end_turn"
        assistant_content: list[dict[str, Any]] = []

        try:
            for kind, payload in stream_turn(client, model=model, system=system, messages=conversation, tools=TOOL_DEFINITIONS):
                if kind == "text":
                    any_text_emitted = True
                    yield _sse("text", {"delta": payload})
                elif kind == "stop":
                    tool_uses = payload["tool_uses"]
                    stop_reason = payload["stop_reason"]
                    assistant_content = payload["assistant_content"]
        except Exception as e:  # noqa: BLE001 -- deliberately broad, see docstring
            yield _envelope_event(
                "error",
                Codes.INVALID_ARGUMENT,
                f"the agent's call to the model failed: {e}",
                hint="Try again, or check the ocm-api server's own logs for the underlying error.",
            )
            return

        conversation.append({"role": "assistant", "content": assistant_content})

        if stop_reason == "refusal":
            yield _envelope_event(
                "error",
                Codes.INVALID_ARGUMENT,
                "the model declined to continue this turn (Anthropic reported stop_reason: refusal)",
                hint="Try rephrasing the request, narrowing it, or filling in the remaining fields yourself.",
            )
            return

        if stop_reason != "tool_use" or not tool_uses:
            if not any_text_emitted:
                yield _sse(
                    "text",
                    {
                        "delta": "(The agent stopped without writing anything or explaining why. "
                        "Try again, or fill in the remaining fields yourself.)"
                    },
                )
            yield _sse("done", {})
            return

        tool_results = []
        for call in tool_uses:
            envelope = _call_tool(api, call["name"], call["input"])
            yield _sse(
                "tool_call",
                {"name": call["name"], "ok": envelope["ok"], "refusal_count": len(envelope["refusals"]), "envelope": envelope},
            )
            tool_results.append({"type": "tool_result", "tool_use_id": call["id"], "content": json.dumps(envelope)})
        conversation.append({"role": "user", "content": tool_results})

    yield _envelope_event(
        "error",
        Codes.INVALID_ARGUMENT,
        f"the agent used {MAX_TOOL_TURNS} tool-call turns without finishing",
        hint="Ask a narrower question, or continue in a new message.",
    )
