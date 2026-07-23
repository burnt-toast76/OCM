# SPDX-License-Identifier: AGPL-3.0-or-later
"""spec/09 "Agent orchestrator": component attachment storage, and the
STEP->GLB conversion's graceful degradation -- an upload NEVER fails
because geometry conversion did (cascadio simply absent, or a real
conversion failure), it just proceeds without a measured envelope.

Conversion runs in a background thread by default (confirmed against a
real manufacturer STEP file: minutes, not the near-instant conversion a
tiny synthetic fixture suggests) -- tests inject `run_conversion=lambda
fn: fn()` to run it inline instead, so assertions stay deterministic
without sleeping or polling for a real thread to finish. The one test that
cares about the threading itself (`test_...returns_before_a_slow_conversion_finishes`)
uses a real thread with an Event so it can prove the call didn't block.
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import ocm_api.attachments as attachments_module
from ocm_api.http_app import build_app
from ocm_api.workspace import Workspace, write_yaml

_INLINE = lambda fn: fn()  # noqa: E731 -- run "in the background" synchronously, for deterministic tests


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "repo")


def _write_component_stub(ws: Workspace, component_id: str) -> None:
    # resume_pending_step_conversions enumerates via Workspace.list_component_ids,
    # which (correctly, for real usage: a component.yaml always exists
    # before any attachment can be uploaded through the real API) requires
    # a component.yaml -- tests that call save_attachment directly, without
    # going through create_component_draft first, need to write this
    # themselves.
    write_yaml(ws.component_path(component_id), {"ocm_version": "1.1", "id": component_id, "revision": "0.1.0", "kind": "sensor"})


# ---------------------------------------------------------------------------
# Plain storage (PDF/text) -- always unconditional, never touches cascadio.
# ---------------------------------------------------------------------------


def test_pdf_upload_is_stored_and_classified(ws: Workspace):
    result = attachments_module.save_attachment(ws, "com.example.demo", "datasheet.pdf", b"%PDF-1.4 fake pdf bytes")
    assert result == {"filename": "datasheet.pdf", "kind": "pdf", "measured_envelope_mm": None, "glb": None, "glb_status": None}
    assert (ws.attachments_dir("com.example.demo") / "datasheet.pdf").read_bytes() == b"%PDF-1.4 fake pdf bytes"


def test_text_upload_is_stored_and_classified(ws: Workspace):
    result = attachments_module.save_attachment(ws, "com.example.demo", "notes.txt", b"stated: 4-6 bar")
    assert result["kind"] == "text"


def test_upload_filename_is_sanitized_against_path_traversal(ws: Workspace):
    result = attachments_module.save_attachment(ws, "com.example.demo", "../../evil.txt", b"x")
    assert result["filename"] == "evil.txt"
    assert (ws.attachments_dir("com.example.demo") / "evil.txt").is_file()
    # Never escaped this component's own attachments directory.
    assert not (ws.root / "evil.txt").exists()


# ---------------------------------------------------------------------------
# STEP -> GLB: runs in the background; the upload response only ever
# reports glb_status: "pending" for a STEP file (this turn's explicit test
# requirement -- the actual outcome is discovered later, via
# list_attachments).
# ---------------------------------------------------------------------------

_FAKE_STEP_BYTES = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"


def test_step_upload_returns_pending_immediately_and_stores_the_raw_file(ws: Workspace, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(attachments_module, "cascadio", None)
    monkeypatch.setattr(attachments_module, "trimesh", None)

    result = attachments_module.save_attachment(ws, "com.example.demo", "part.step", _FAKE_STEP_BYTES, run_conversion=_INLINE)

    assert result == {"filename": "part.step", "kind": "step", "measured_envelope_mm": None, "glb": None, "glb_status": "pending"}
    # The upload itself never fails -- the raw file is on disk regardless.
    assert (ws.attachments_dir("com.example.demo") / "part.step").read_bytes() == _FAKE_STEP_BYTES


def test_step_upload_returns_before_a_slow_conversion_finishes(ws: Workspace, monkeypatch: pytest.MonkeyPatch):
    # The whole point of running conversion in the background: a slow (or
    # hung) conversion must not block the upload call itself. Uses REAL
    # threading (not the inline injection) plus an Event so this can prove
    # save_attachment returned while the "conversion" was still blocked.
    started = threading.Event()
    release = threading.Event()

    class _SlowCascadio:
        def step_to_glb(self, step_path: str, glb_path: str) -> None:
            started.set()
            release.wait(timeout=5)
            Path(glb_path).write_bytes(b"pretend glb bytes")

    monkeypatch.setattr(attachments_module, "cascadio", _SlowCascadio())

    result = attachments_module.save_attachment(ws, "com.example.demo", "part.step", _FAKE_STEP_BYTES)

    assert result["glb_status"] == "pending"
    assert started.wait(timeout=5), "conversion never started in the background"
    # The upload call already returned above -- prove the glb genuinely
    # isn't there yet (conversion is still blocked on `release`).
    assert not (ws.attachments_dir("com.example.demo") / "part.glb").exists()
    release.set()  # let the background thread finish so it doesn't leak into the next test


def test_step_upload_stores_the_file_even_when_conversion_raises(ws: Workspace, monkeypatch: pytest.MonkeyPatch):
    class _ExplodingCascadio:
        def step_to_glb(self, step_path: str, glb_path: str) -> None:
            # Simulate a CAD kernel choking on a real-world file, and (as a
            # real failure plausibly would) leaving a partial file behind
            # before raising.
            Path(glb_path).write_bytes(b"not a real glb")
            raise RuntimeError("kernel exploded on this geometry")

    monkeypatch.setattr(attachments_module, "cascadio", _ExplodingCascadio())

    attachments_module.save_attachment(ws, "com.example.demo", "part.stp", _FAKE_STEP_BYTES, run_conversion=_INLINE)

    assert (ws.attachments_dir("com.example.demo") / "part.stp").is_file()
    # The partial GLB a failed conversion left behind must not linger --
    # a later chat turn could otherwise try to load it as if it were real.
    assert not (ws.attachments_dir("com.example.demo") / "part.glb").exists()
    rows = attachments_module.list_attachments(ws, "com.example.demo")
    assert rows[0]["glb_status"] == "failed"


def test_step_upload_measures_the_envelope_on_success(ws: Workspace, monkeypatch: pytest.MonkeyPatch):
    class _FakeMesh:
        # trimesh's own bounds shape: a (2, 3) numpy array of [min_xyz, max_xyz].
        bounds = np.array([[0.0, 0.0, 0.0], [120.0, 80.5, 45.0]])

    class _FakeCascadio:
        def step_to_glb(self, step_path: str, glb_path: str) -> None:
            Path(glb_path).write_bytes(b"pretend glb bytes")

    class _FakeTrimesh:
        def load(self, path: str) -> _FakeMesh:
            return _FakeMesh()

    monkeypatch.setattr(attachments_module, "cascadio", _FakeCascadio())
    monkeypatch.setattr(attachments_module, "trimesh", _FakeTrimesh())

    attachments_module.save_attachment(ws, "com.example.demo", "part.step", _FAKE_STEP_BYTES, run_conversion=_INLINE)

    assert (ws.attachments_dir("com.example.demo") / "part.glb").is_file()
    rows = attachments_module.list_attachments(ws, "com.example.demo")
    assert rows[0]["glb"] == "part.glb"
    assert rows[0]["glb_status"] == "ready"
    assert rows[0]["measured_envelope_mm"] == [120.0, 80.5, 45.0]


def test_a_re_upload_clears_a_stale_failed_marker_before_retrying(ws: Workspace, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(attachments_module, "cascadio", None)
    attachments_module.save_attachment(ws, "com.example.demo", "part.step", _FAKE_STEP_BYTES, run_conversion=_INLINE)
    assert attachments_module.list_attachments(ws, "com.example.demo")[0]["glb_status"] == "failed"

    class _FakeMesh:
        bounds = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]])

    class _FakeCascadio:
        def step_to_glb(self, step_path: str, glb_path: str) -> None:
            Path(glb_path).write_bytes(b"pretend glb")

    class _FakeTrimesh:
        def load(self, path: str) -> _FakeMesh:
            return _FakeMesh()

    monkeypatch.setattr(attachments_module, "cascadio", _FakeCascadio())
    monkeypatch.setattr(attachments_module, "trimesh", _FakeTrimesh())

    attachments_module.save_attachment(ws, "com.example.demo", "part.step", _FAKE_STEP_BYTES, run_conversion=_INLINE)

    assert attachments_module.list_attachments(ws, "com.example.demo")[0]["glb_status"] == "ready"


# ---------------------------------------------------------------------------
# resume_pending_step_conversions: startup catch-up for a conversion a
# previous process's restart interrupted.
# ---------------------------------------------------------------------------


def test_resume_converts_a_step_file_left_without_a_glb(ws: Workspace, monkeypatch: pytest.MonkeyPatch):
    _write_component_stub(ws, "com.example.demo")
    # No conversion attempted at all yet (as if this process just started
    # and a previous one died mid-conversion, or never got to it).
    attachments_module.save_attachment(ws, "com.example.demo", "part.step", _FAKE_STEP_BYTES, run_conversion=lambda fn: None)
    assert attachments_module.list_attachments(ws, "com.example.demo")[0]["glb_status"] == "pending"

    class _FakeMesh:
        bounds = np.array([[0.0, 0.0, 0.0], [10.0, 10.0, 10.0]])

    class _FakeCascadio:
        def step_to_glb(self, step_path: str, glb_path: str) -> None:
            Path(glb_path).write_bytes(b"pretend glb")

    class _FakeTrimesh:
        def load(self, path: str) -> _FakeMesh:
            return _FakeMesh()

    monkeypatch.setattr(attachments_module, "cascadio", _FakeCascadio())
    monkeypatch.setattr(attachments_module, "trimesh", _FakeTrimesh())
    attachments_module._CONVERTING.clear()  # the abandoned "pending" from the never-run thread above

    attachments_module.resume_pending_step_conversions(ws, run_conversion=_INLINE)

    assert attachments_module.list_attachments(ws, "com.example.demo")[0]["glb_status"] == "ready"


def test_resume_does_not_touch_a_step_file_that_already_converted(ws: Workspace, monkeypatch: pytest.MonkeyPatch):
    _write_component_stub(ws, "com.example.demo")

    class _FakeMesh:
        bounds = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]])

    class _FakeCascadio:
        def step_to_glb(self, step_path: str, glb_path: str) -> None:
            Path(glb_path).write_bytes(b"original glb bytes")

    class _FakeTrimesh:
        def load(self, path: str) -> _FakeMesh:
            return _FakeMesh()

    monkeypatch.setattr(attachments_module, "cascadio", _FakeCascadio())
    monkeypatch.setattr(attachments_module, "trimesh", _FakeTrimesh())
    attachments_module.save_attachment(ws, "com.example.demo", "part.step", _FAKE_STEP_BYTES, run_conversion=_INLINE)
    original_bytes = (ws.attachments_dir("com.example.demo") / "part.glb").read_bytes()

    calls = []
    attachments_module.resume_pending_step_conversions(ws, run_conversion=lambda fn: calls.append(fn))

    assert calls == []
    assert (ws.attachments_dir("com.example.demo") / "part.glb").read_bytes() == original_bytes


# ---------------------------------------------------------------------------
# attachment_content_blocks: what gets injected into a chat turn.
# ---------------------------------------------------------------------------


def test_pdf_becomes_a_document_block(ws: Workspace):
    attachments_module.save_attachment(ws, "com.example.demo", "sheet.pdf", b"%PDF-1.4 x")
    blocks = attachments_module.attachment_content_blocks(ws, "com.example.demo", ["sheet.pdf"])
    assert len(blocks) == 1
    assert blocks[0]["type"] == "document"
    assert blocks[0]["source"]["media_type"] == "application/pdf"


def test_text_becomes_a_text_block_with_its_content(ws: Workspace):
    attachments_module.save_attachment(ws, "com.example.demo", "notes.txt", b"stated: 4-6 bar")
    blocks = attachments_module.attachment_content_blocks(ws, "com.example.demo", ["notes.txt"])
    assert blocks[0]["type"] == "text"
    assert "4-6 bar" in blocks[0]["text"]


def test_step_with_no_successful_conversion_becomes_a_note_saying_so(ws: Workspace, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(attachments_module, "cascadio", None)
    attachments_module.save_attachment(ws, "com.example.demo", "part.step", _FAKE_STEP_BYTES, run_conversion=_INLINE)

    blocks = attachments_module.attachment_content_blocks(ws, "com.example.demo", ["part.step"])

    assert blocks[0]["type"] == "text"
    assert "unavailable" in blocks[0]["text"]
    assert "no measured envelope" in blocks[0]["text"]


def test_step_still_converting_becomes_a_note_saying_so_not_a_silent_gap(ws: Workspace):
    # A chat turn that fires while conversion is still running (a real
    # possibility now that it's backgrounded) must say so, not read
    # identically to "conversion was never attempted."
    attachments_module.save_attachment(ws, "com.example.demo", "part.step", _FAKE_STEP_BYTES, run_conversion=lambda fn: None)

    blocks = attachments_module.attachment_content_blocks(ws, "com.example.demo", ["part.step"])

    assert blocks[0]["type"] == "text"
    assert "still running" in blocks[0]["text"]
    attachments_module._CONVERTING.clear()  # the abandoned "pending" from the never-run thread above


def test_a_filename_that_does_not_exist_is_silently_skipped(ws: Workspace):
    assert attachments_module.attachment_content_blocks(ws, "com.example.demo", ["never-uploaded.pdf"]) == []


def test_list_attachments_reports_a_step_files_glb_sibling_and_excludes_the_glb_itself(ws: Workspace, monkeypatch: pytest.MonkeyPatch):
    class _FakeCascadio:
        def step_to_glb(self, step_path: str, glb_path: str) -> None:
            Path(glb_path).write_bytes(b"pretend glb")

    class _FakeMesh:
        bounds = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]])

    class _FakeTrimesh:
        def load(self, path: str) -> _FakeMesh:
            return _FakeMesh()

    monkeypatch.setattr(attachments_module, "cascadio", _FakeCascadio())
    monkeypatch.setattr(attachments_module, "trimesh", _FakeTrimesh())

    attachments_module.save_attachment(ws, "com.example.demo", "part.step", _FAKE_STEP_BYTES, run_conversion=_INLINE)
    attachments_module.save_attachment(ws, "com.example.demo", "sheet.pdf", b"%PDF-1.4 x")

    rows = attachments_module.list_attachments(ws, "com.example.demo")
    by_name = {r["filename"]: r for r in rows}

    assert set(by_name) == {"part.step", "sheet.pdf"}  # the .glb itself is not a separate row
    assert by_name["part.step"]["glb"] == "part.glb"
    assert by_name["sheet.pdf"]["glb"] is None


# ---------------------------------------------------------------------------
# HTTP transport: upload, list, and download.
# ---------------------------------------------------------------------------


def test_http_upload_then_list_then_download_round_trip(tmp_path: Path):
    client = TestClient(build_app(str(tmp_path / "repo")))

    upload = client.post(
        "/components/com.example.http-demo/attachments",
        files={"file": ("notes.txt", b"stated: 4-6 bar", "text/plain")},
    )
    assert upload.status_code == 200
    assert upload.json()["kind"] == "text"

    listing = client.get("/components/com.example.http-demo/attachments")
    assert listing.status_code == 200
    assert listing.json()["files"] == [
        {"filename": "notes.txt", "kind": "text", "glb": None, "glb_status": None, "measured_envelope_mm": None}
    ]

    download = client.get("/components/com.example.http-demo/attachments/notes.txt")
    assert download.status_code == 200
    assert download.content == b"stated: 4-6 bar"


def test_http_download_of_an_unknown_attachment_is_a_404(tmp_path: Path):
    client = TestClient(build_app(str(tmp_path / "repo")))
    response = client.get("/components/com.example.http-demo/attachments/never-uploaded.pdf")
    assert response.status_code == 404


def test_http_startup_resumes_a_step_conversion_left_pending_from_a_prior_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Simulates exactly the bug report this feature exists for: a STEP
    # file uploaded (e.g. to an earlier server process) that never got its
    # .glb, because that process restarted mid-conversion. A fresh
    # build_app() -- i.e. a fresh process starting up -- must pick it back
    # up on its own, with no new upload needed.
    repo_root = tmp_path / "repo"
    ws = Workspace(repo_root)
    _write_component_stub(ws, "com.example.http-demo")
    attachments_module.save_attachment(ws, "com.example.http-demo", "part.step", _FAKE_STEP_BYTES, run_conversion=lambda fn: None)
    attachments_module._CONVERTING.clear()  # simulate the process that would have run it having died

    class _FakeMesh:
        bounds = np.array([[0.0, 0.0, 0.0], [5.0, 5.0, 5.0]])

    class _FakeCascadio:
        def step_to_glb(self, step_path: str, glb_path: str) -> None:
            Path(glb_path).write_bytes(b"pretend glb")

    class _FakeTrimesh:
        def load(self, path: str) -> _FakeMesh:
            return _FakeMesh()

    monkeypatch.setattr(attachments_module, "cascadio", _FakeCascadio())
    monkeypatch.setattr(attachments_module, "trimesh", _FakeTrimesh())
    monkeypatch.setattr(attachments_module, "_run_in_background_thread", _INLINE)

    with TestClient(build_app(str(repo_root))):
        pass  # entering the context triggers FastAPI's startup event

    listing_rows = attachments_module.list_attachments(ws, "com.example.http-demo")
    assert listing_rows[0]["glb_status"] == "ready"
