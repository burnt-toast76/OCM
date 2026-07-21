# SPDX-License-Identifier: AGPL-3.0-or-later
"""A minimal FastAPI wrapper over `OcmApi` -- the GUI's transport
(ADR-0012: "the web composer calls the exact same verbs" the MCP server
exposes to agents). One POST route per verb, named identically to the MCP
tool and the `OcmApi` method. Every handler does nothing but call the
matching `OcmApi` method and return `envelope.to_dict()` -- no reshaping,
so this transport's JSON body is exactly the library call's own envelope
(see tests/test_envelope_consistency.py). `ok=false` is still HTTP 200:
a refusal is a normal response, not a transport-level error (spec/09
design principle #1).

Also serves software/ocm-composer's production build (a pure client of
these same verbs -- ADR-0012: "the web composer calls the exact same
verbs" the MCP server exposes to agents) at `/composer`, if that build
exists. `npm run build` writes `ocm-composer/dist/`; nothing here builds
it or fails if it's absent (a fresh checkout with no `npm run build` yet
still serves the API fine, just not the GUI).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import anthropic
from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .agent import agent_unavailable_stream, run_agent_chat
from .api import OcmApi
from .attachments import attachment_content_blocks, list_attachments, save_attachment

# software/ocm-api/ocm_api/http_app.py -> software/ocm-composer/dist
_COMPOSER_DIST = Path(__file__).resolve().parents[2] / "ocm-composer" / "dist"


def build_app(repo_root: str) -> FastAPI:
    api = OcmApi(repo_root)
    app = FastAPI(title="ocm-api", description="spec/09-ocm-api.md's tool surface over HTTP.")

    def envelope_response(envelope) -> dict[str, Any]:
        return envelope.to_dict()

    # -- Discovery ---------------------------------------------------

    @app.get("/describe_schema")
    def describe_schema(section: str | None = Query(default=None), target: str = Query(default="module")) -> dict[str, Any]:
        return envelope_response(api.describe_schema(section, target=target))

    @app.get("/get_example")
    def get_example(kind: str = Query(...)) -> dict[str, Any]:
        return envelope_response(api.get_example(kind))

    @app.get("/list_modules")
    def list_modules() -> dict[str, Any]:
        return envelope_response(api.list_modules())

    @app.get("/describe_module")
    def describe_module(id: str = Query(...)) -> dict[str, Any]:
        return envelope_response(api.describe_module(id))

    @app.get("/list_cells")
    def list_cells() -> dict[str, Any]:
        return envelope_response(api.list_cells())

    @app.get("/describe_cell")
    def describe_cell(id: str = Query(...)) -> dict[str, Any]:
        return envelope_response(api.describe_cell(id))

    @app.get("/list_frames")
    def list_frames(cell_id: str = Query(...)) -> dict[str, Any]:
        return envelope_response(api.list_frames(cell_id))

    # -- Module authoring ---------------------------------------------------

    @app.post("/create_module_draft")
    def create_module_draft(id: str = Body(...), kind: str = Body(...)) -> dict[str, Any]:
        return envelope_response(api.create_module_draft(id, kind))

    @app.post("/update_module")
    def update_module(
        id: str = Body(...),
        manifest: dict[str, Any] | None = Body(default=None),
        patch: list[dict[str, Any]] | None = Body(default=None),
    ) -> dict[str, Any]:
        return envelope_response(api.update_module(id, manifest=manifest, patch=patch))

    @app.post("/generate_geometry_stub")
    def generate_geometry_stub(
        id: str = Body(...),
        footprint_mm: list[float] = Body(...),
        height_mm: float = Body(...),
        kind: str | None = Body(default=None),
    ) -> dict[str, Any]:
        return envelope_response(api.generate_geometry_stub(id, (footprint_mm[0], footprint_mm[1]), height_mm, kind=kind))

    @app.post("/validate_module")
    def validate_module(id: str = Body(..., embed=True)) -> dict[str, Any]:
        return envelope_response(api.validate_module(id))

    @app.post("/publish_module")
    def publish_module(id: str = Body(...), revision: str = Body(...)) -> dict[str, Any]:
        return envelope_response(api.publish_module(id, revision))

    # -- Component authoring (ADR-0014) ---------------------------------------------------

    @app.post("/create_component_draft")
    def create_component_draft(id: str = Body(...), kind: str = Body(...)) -> dict[str, Any]:
        return envelope_response(api.create_component_draft(id, kind))

    @app.post("/update_component")
    def update_component(
        id: str = Body(...),
        manifest: dict[str, Any] | None = Body(default=None),
        patch: list[dict[str, Any]] | None = Body(default=None),
    ) -> dict[str, Any]:
        return envelope_response(api.update_component(id, manifest=manifest, patch=patch))

    @app.post("/validate_component")
    def validate_component(id: str = Body(..., embed=True)) -> dict[str, Any]:
        return envelope_response(api.validate_component(id))

    @app.post("/publish_component")
    def publish_component(id: str = Body(...), revision: str = Body(...)) -> dict[str, Any]:
        return envelope_response(api.publish_component(id, revision))

    @app.get("/list_components")
    def list_components() -> dict[str, Any]:
        return envelope_response(api.list_components())

    @app.get("/describe_component")
    def describe_component(id: str = Query(...)) -> dict[str, Any]:
        return envelope_response(api.describe_component(id))

    # -- Cell composition ---------------------------------------------------

    @app.post("/create_cell")
    def create_cell(id: str = Body(...), base_module: str = Body(...)) -> dict[str, Any]:
        return envelope_response(api.create_cell(id, base_module))

    @app.post("/place_instance")
    def place_instance(
        cell: str = Body(...), instance: str = Body(...), module: str = Body(...), mount: dict[str, Any] = Body(...)
    ) -> dict[str, Any]:
        return envelope_response(api.place_instance(cell, instance, module, mount))

    @app.post("/move_instance")
    def move_instance(cell: str = Body(...), instance: str = Body(...), mount: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return envelope_response(api.move_instance(cell, instance, mount))

    @app.post("/remove_instance")
    def remove_instance(cell: str = Body(...), instance: str = Body(...)) -> dict[str, Any]:
        return envelope_response(api.remove_instance(cell, instance))

    @app.post("/set_plan")
    def set_plan(cell: str = Body(...), plan: list[Any] = Body(...), part: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        return envelope_response(api.set_plan(cell, plan, part=part))

    @app.post("/set_joint_state")
    def set_joint_state(cell: str = Body(...), instance: str = Body(...), joints: dict[str, float] = Body(...)) -> dict[str, Any]:
        return envelope_response(api.set_joint_state(cell, instance, joints))

    # -- Checking & generation ---------------------------------------------------

    @app.post("/build_scene")
    def build_scene(cell: str = Body(..., embed=True)) -> dict[str, Any]:
        return envelope_response(api.build_scene(cell))

    @app.post("/check_collision")
    def check_collision(cell: str = Body(...), collision_margin_mm: float = Body(default=1.0)) -> dict[str, Any]:
        return envelope_response(api.check_collision(cell, collision_margin_mm=collision_margin_mm))

    @app.post("/plan_cell")
    def plan_cell(cell: str = Body(...), collision_margin_mm: float = Body(default=1.0), path_samples: int = Body(default=50)) -> dict[str, Any]:
        return envelope_response(api.plan_cell(cell, collision_margin_mm=collision_margin_mm, path_samples=path_samples))

    @app.post("/emit")
    def emit(
        cell: str = Body(...),
        urscript: str | None = Body(default=None),
        animation: str | None = Body(default=None),
        view: str | None = Body(default=None),
        collision_margin_mm: float = Body(default=1.0),
        path_samples: int = Body(default=50),
    ) -> dict[str, Any]:
        return envelope_response(
            api.emit(cell, urscript=urscript, animation=animation, view=view, collision_margin_mm=collision_margin_mm, path_samples=path_samples)
        )

    # -- Agent orchestrator (spec/09 "Agent orchestrator") ---------------------------------------------------

    @app.post("/components/{component_id}/attachments")
    def upload_component_attachment(component_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
        return save_attachment(api.workspace, component_id, file.filename or "upload", file.file.read())

    @app.get("/components/{component_id}/attachments")
    def list_component_attachments(component_id: str) -> dict[str, Any]:
        return {"files": list_attachments(api.workspace, component_id)}

    @app.get("/components/{component_id}/attachments/{filename}")
    def download_component_attachment(component_id: str, filename: str) -> FileResponse:
        # Path(filename).name, same as save_attachment -- never trust a
        # client-supplied path component, only ever look inside this
        # component's own attachments directory.
        safe_name = Path(filename).name
        target = api.workspace.attachments_dir(component_id) / safe_name
        if not target.is_file():
            raise HTTPException(status_code=404, detail=f"no attachment {filename!r} for component {component_id!r}")
        return FileResponse(target)

    @app.post("/agent/chat")
    def agent_chat(
        component_id: str | None = Body(default=None),
        messages: list[dict[str, Any]] = Body(...),
        attachment_filenames: list[str] = Body(default=[]),
    ) -> StreamingResponse:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return StreamingResponse(
                agent_unavailable_stream("ANTHROPIC_API_KEY is not set in this server's environment"),
                media_type="text/event-stream",
            )

        # Attachments merge into the LAST user turn only -- they're what
        # this specific message is about, not resent on every later turn.
        conversation = [dict(m) for m in messages]
        if attachment_filenames and component_id and conversation and conversation[-1].get("role") == "user":
            blocks = attachment_content_blocks(api.workspace, component_id, attachment_filenames)
            if blocks:
                text = conversation[-1].get("content", "")
                conversation[-1] = {"role": "user", "content": [{"type": "text", "text": text}, *blocks]}

        client = anthropic.Anthropic(api_key=api_key)
        return StreamingResponse(run_agent_chat(client, api, conversation, component_id=component_id), media_type="text/event-stream")

    # -- Composer static build ---------------------------------------------------

    if _COMPOSER_DIST.is_dir():
        app.mount("/composer", StaticFiles(directory=_COMPOSER_DIST, html=True), name="composer")

    return app


def main() -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(prog="ocm-api-http", description="ocm-api's minimal FastAPI HTTP wrapper.")
    parser.add_argument("--repo", type=str, default=os.environ.get("OCM_API_REPO", "."))
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(build_app(args.repo), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
