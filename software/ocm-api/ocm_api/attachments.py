# SPDX-License-Identifier: AGPL-3.0-or-later
"""Component attachment storage (spec/09 "Agent orchestrator"): datasheet
uploads live at `components/<id>/attachments/`, next to the component
they document. Two things happen to an upload:

1. It's stored, unconditionally -- an upload never fails because of what
   comes next.
2. If it's a .step/.stp file, this module makes a BEST-EFFORT attempt to
   convert it to GLB (via cascadio) and measure its bounding-box envelope
   (via trimesh), so a "measured envelope" fact can be injected into a
   chat turn without asking the model to interpret CAD data itself. Any
   failure here -- cascadio simply not installed (its Windows wheel
   availability was uncertain at the time this was written), or a CAD
   kernel choking on a real-world file -- degrades to "no geometry", never
   a crash and never a rejected upload. Logged, not raised.

`attachment_content_blocks` is the other direction: turning previously-
stored attachments into Anthropic Messages API content blocks for a chat
turn. PDFs and text files are passed through close to verbatim (spec/09:
"PDFs/text are passed to the chat as document/text blocks"); a STEP file
has no Anthropic block type of its own, so it becomes a synthesized text
note naming whatever measured envelope conversion produced (spec/09:
"inject a 'measured envelope' note into the conversation").
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

from .workspace import Workspace

logger = logging.getLogger(__name__)

try:
    import cascadio
    import trimesh
except ImportError:  # pragma: no cover -- exercised via monkeypatched None in tests
    cascadio = None  # type: ignore[assignment]
    trimesh = None  # type: ignore[assignment]

_PDF_MEDIA_TYPE = "application/pdf"
_STEP_EXTENSIONS = {".step", ".stp"}
_TEXT_EXTENSIONS = {".txt", ".md", ".csv"}


def list_attachments(ws: Workspace, component_id: str) -> list[dict[str, Any]]:
    """Everything previously uploaded for this component -- lets a
    freshly (re)loaded Components detail page discover a GLB that was
    converted in an earlier session, not just ones staged in this one.
    """
    directory = ws.attachments_dir(component_id)
    if not directory.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.lower() == ".glb":
            continue  # a GLB is reported as its STEP sibling's own `glb` field, not a separate row
        ext = path.suffix.lower()
        kind = "pdf" if ext == ".pdf" else "text" if ext in _TEXT_EXTENSIONS else "step" if ext in _STEP_EXTENSIONS else "other"
        glb_sibling = path.with_suffix(".glb")
        rows.append({"filename": path.name, "kind": kind, "glb": glb_sibling.name if kind == "step" and glb_sibling.is_file() else None})
    return rows


def save_attachment(ws: Workspace, component_id: str, filename: str, content: bytes) -> dict[str, Any]:
    # Path(filename).name strips any directory components a client could
    # smuggle in (e.g. "../../module.yaml") -- an upload only ever lands
    # inside this component's own attachments/ directory, never anywhere
    # else in the workspace.
    safe_name = Path(filename).name
    directory = ws.attachments_dir(component_id)
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / safe_name
    dest.write_bytes(content)

    ext = dest.suffix.lower()
    result: dict[str, Any] = {"filename": safe_name, "kind": "other", "measured_envelope_mm": None, "glb": None}

    if ext == ".pdf":
        result["kind"] = "pdf"
    elif ext in _TEXT_EXTENSIONS:
        result["kind"] = "text"
    elif ext in _STEP_EXTENSIONS:
        result["kind"] = "step"
        envelope = _convert_step_to_glb(dest)
        if envelope is not None:
            result["measured_envelope_mm"] = envelope
            result["glb"] = dest.with_suffix(".glb").name

    return result


def _convert_step_to_glb(step_path: Path) -> list[float] | None:
    if cascadio is None or trimesh is None:
        logger.info("STEP->GLB conversion skipped for %s: cascadio/trimesh not installed", step_path.name)
        return None

    glb_path = step_path.with_suffix(".glb")
    try:
        cascadio.step_to_glb(str(step_path), str(glb_path))
        mesh = trimesh.load(str(glb_path))
        bounds = mesh.bounds  # (2, 3): [min_xyz, max_xyz], cascadio emits mm-scale GLBs
        extents = (bounds[1] - bounds[0]).tolist()
        return [round(v, 2) for v in extents]
    except Exception:
        # Deliberately broad: a CAD kernel's failure modes on a real-world
        # file aren't enumerable in advance, and this is a best-effort
        # nicety, not a load-bearing step of the upload itself (spec/09:
        # "on any failure, store the file and proceed without geometry").
        logger.exception("STEP->GLB conversion failed for %s", step_path)
        _remove_partial_glb(glb_path)
        return None


def _remove_partial_glb(glb_path: Path) -> None:
    # cascadio may have written a partial/corrupt GLB before a later step
    # (e.g. trimesh.load) failed -- don't leave a broken file behind for a
    # later chat turn to try to render.
    if glb_path.is_file():
        try:
            glb_path.unlink()
        except OSError:
            pass


def attachment_content_blocks(ws: Workspace, component_id: str, filenames: list[str]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    directory = ws.attachments_dir(component_id)
    for filename in filenames:
        path = directory / Path(filename).name
        if not path.is_file():
            continue
        ext = path.suffix.lower()

        if ext == ".pdf":
            blocks.append(
                {
                    "type": "document",
                    "source": {"type": "base64", "media_type": _PDF_MEDIA_TYPE, "data": base64.b64encode(path.read_bytes()).decode("ascii")},
                    "title": path.name,
                }
            )
        elif ext in _TEXT_EXTENSIONS:
            blocks.append({"type": "text", "text": f"--- {path.name} ---\n{path.read_text(encoding='utf-8', errors='replace')}"})
        elif ext in _STEP_EXTENSIONS:
            blocks.append({"type": "text", "text": _step_note(path)})
        # Anything else (e.g. an image) isn't a format spec/09 asked this
        # endpoint to understand -- silently not included, same as a
        # filename that doesn't resolve to a real file.
    return blocks


def _step_note(step_path: Path) -> str:
    glb_path = step_path.with_suffix(".glb")
    if not glb_path.is_file():
        return f"{step_path.name}: a STEP file was uploaded but geometry conversion was unavailable -- no measured envelope."
    if trimesh is None:
        return f"{step_path.name}: a STEP file was uploaded and converted, but its measured envelope could not be re-derived (trimesh unavailable)."
    try:
        mesh = trimesh.load(str(glb_path))
        extents = [round(v, 2) for v in (mesh.bounds[1] - mesh.bounds[0]).tolist()]
        return f"Measured envelope for {step_path.name} (from its STEP geometry, in mm, x/y/z): {extents}"
    except Exception:
        logger.exception("Could not re-derive the measured envelope for %s", step_path)
        return f"{step_path.name}: a STEP file was uploaded but its measured envelope could not be re-derived."
