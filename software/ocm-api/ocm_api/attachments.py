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

Conversion runs in a BACKGROUND THREAD, not inline in the upload request --
confirmed against a real manufacturer STEP file that this can take minutes,
not the near-instant conversion small test fixtures suggested. Blocking the
whole HTTP request (and, worse, being silently killed mid-conversion by an
unrelated backend restart, leaving no .glb and no record anything was even
attempted) is exactly the failure this session's own live testing hit.
`glb_status` (pending/ready/failed) on every STEP row is how a caller tells
those apart instead of staring at an indefinitely blank viewer.
`resume_pending_step_conversions` is the other half: called once at server
startup, it re-attempts any STEP file still missing a .glb -- the case a
restart mid-conversion leaves behind, since a killed thread never gets to
clean up after itself.
"""

from __future__ import annotations

import base64
import logging
import threading
from pathlib import Path
from typing import Any, Callable

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

# STEP files currently being converted IN THIS PROCESS (absolute path
# strings) -- deliberately in-memory, not a file on disk: a process
# restart should make every in-flight conversion look like what it now
# is (not running), which in-memory state does for free, where a
# persistent "pending" marker file would need its own stale-on-restart
# handling to avoid lying forever about a conversion nothing is actually
# doing anymore.
_CONVERTING: set[str] = set()

RunConversion = Callable[[Callable[[], None]], None]


def _run_in_background_thread(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, daemon=True).start()


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
        if not path.is_file() or path.suffix.lower() in (".glb", ".failed"):
            continue
        ext = path.suffix.lower()
        kind = "pdf" if ext == ".pdf" else "text" if ext in _TEXT_EXTENSIONS else "step" if ext in _STEP_EXTENSIONS else "other"
        row: dict[str, Any] = {"filename": path.name, "kind": kind, "glb": None, "glb_status": None, "measured_envelope_mm": None}
        if kind == "step":
            glb_path = path.with_suffix(".glb")
            if glb_path.is_file():
                row["glb"] = glb_path.name
                row["glb_status"] = "ready"
                row["measured_envelope_mm"] = _measure_glb(glb_path)
            elif _is_converting(path):
                row["glb_status"] = "pending"
            elif _failed_marker(path).is_file():
                row["glb_status"] = "failed"
            else:
                row["glb_status"] = "pending"  # not yet picked up by this process; startup catch-up handles it
        rows.append(row)
    return rows


def save_attachment(
    ws: Workspace, component_id: str, filename: str, content: bytes, *, run_conversion: RunConversion | None = None
) -> dict[str, Any]:
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
    result: dict[str, Any] = {"filename": safe_name, "kind": "other", "measured_envelope_mm": None, "glb": None, "glb_status": None}

    if ext == ".pdf":
        result["kind"] = "pdf"
    elif ext in _TEXT_EXTENSIONS:
        result["kind"] = "text"
    elif ext in _STEP_EXTENSIONS:
        result["kind"] = "step"
        result["glb_status"] = "pending"
        _start_step_conversion(dest, run_conversion=run_conversion)

    return result


def resume_pending_step_conversions(ws: Workspace, *, run_conversion: RunConversion | None = None) -> None:
    """Called once at server startup (http_app.py). Any STEP file still
    missing its .glb -- never attempted, or interrupted by a previous
    process's restart mid-conversion -- gets a fresh attempt. Cheap and
    self-healing: a component with nothing to do costs one directory
    listing per component.
    """
    for component_id in ws.list_component_ids():
        directory = ws.attachments_dir(component_id)
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if not path.is_file() or path.suffix.lower() not in _STEP_EXTENSIONS:
                continue
            if path.with_suffix(".glb").is_file() or _is_converting(path):
                continue
            _start_step_conversion(path, run_conversion=run_conversion)


def _is_converting(step_path: Path) -> bool:
    return str(step_path.resolve()) in _CONVERTING


def _failed_marker(step_path: Path) -> Path:
    return step_path.with_suffix(".glb.failed")


def _start_step_conversion(step_path: Path, *, run_conversion: RunConversion | None) -> None:
    # Looked up as a plain module-global NAME at call time, deliberately
    # not bound as a parameter default -- a default is bound once, at
    # import time, so monkeypatching `_run_in_background_thread` (the
    # normal way tests and any future caller override behavior, same
    # pattern as this module's own `cascadio`/`trimesh` swaps) would
    # silently have no effect on a caller that never passes its own
    # run_conversion explicitly.
    run = run_conversion or _run_in_background_thread
    key = str(step_path.resolve())
    failed_marker = _failed_marker(step_path)
    if failed_marker.is_file():
        # A fresh attempt (re-upload, or a startup catch-up retry) --
        # don't leave a stale "failed" status up if this one succeeds.
        failed_marker.unlink(missing_ok=True)
    _CONVERTING.add(key)

    def worker() -> None:
        try:
            envelope = _convert_step_to_glb(step_path)
            if envelope is None:
                failed_marker.touch()
        finally:
            _CONVERTING.discard(key)

    run(worker)


def _convert_step_to_glb(step_path: Path) -> list[float] | None:
    if cascadio is None or trimesh is None:
        logger.info("STEP->GLB conversion skipped for %s: cascadio/trimesh not installed", step_path.name)
        return None

    glb_path = step_path.with_suffix(".glb")
    try:
        cascadio.step_to_glb(str(step_path), str(glb_path))
        return _measure_glb(glb_path)
    except Exception:
        # Deliberately broad: a CAD kernel's failure modes on a real-world
        # file aren't enumerable in advance, and this is a best-effort
        # nicety, not a load-bearing step of the upload itself (spec/09:
        # "on any failure, store the file and proceed without geometry").
        logger.exception("STEP->GLB conversion failed for %s", step_path.name)
        _remove_partial_glb(glb_path)
        return None


def _measure_glb(glb_path: Path) -> list[float] | None:
    if trimesh is None or not glb_path.is_file():
        return None
    try:
        mesh = trimesh.load(str(glb_path))
        bounds = mesh.bounds  # (2, 3): [min_xyz, max_xyz], cascadio emits mm-scale GLBs
        extents = (bounds[1] - bounds[0]).tolist()
        return [round(v, 2) for v in extents]
    except Exception:
        logger.exception("Could not measure the envelope for %s", glb_path.name)
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
    if _is_converting(step_path):
        return f"{step_path.name}: a STEP file was uploaded and its geometry conversion is still running -- no measured envelope yet, try again shortly."
    glb_path = step_path.with_suffix(".glb")
    if not glb_path.is_file():
        return f"{step_path.name}: a STEP file was uploaded but geometry conversion was unavailable -- no measured envelope."
    extents = _measure_glb(glb_path)
    if extents is None:
        reason = "trimesh unavailable" if trimesh is None else "re-derivation failed"
        return f"{step_path.name}: a STEP file was uploaded and converted, but its measured envelope could not be re-derived ({reason})."
    return f"Measured envelope for {step_path.name} (from its STEP geometry, in mm, x/y/z): {extents}"
