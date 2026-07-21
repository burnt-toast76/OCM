# SPDX-License-Identifier: AGPL-3.0-or-later
"""spec/09 "Agent orchestrator": component attachment storage, and the
STEP->GLB conversion's graceful degradation -- an upload NEVER fails
because geometry conversion did (cascadio simply absent, or a real
conversion failure), it just proceeds without a measured envelope.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import ocm_api.attachments as attachments_module
from ocm_api.http_app import build_app
from ocm_api.workspace import Workspace


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "repo")


# ---------------------------------------------------------------------------
# Plain storage (PDF/text) -- always unconditional, never touches cascadio.
# ---------------------------------------------------------------------------


def test_pdf_upload_is_stored_and_classified(ws: Workspace):
    result = attachments_module.save_attachment(ws, "com.example.demo", "datasheet.pdf", b"%PDF-1.4 fake pdf bytes")
    assert result == {"filename": "datasheet.pdf", "kind": "pdf", "measured_envelope_mm": None, "glb": None}
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
# STEP -> GLB: the fallback path (this turn's explicit test requirement).
# ---------------------------------------------------------------------------

_FAKE_STEP_BYTES = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"


def test_step_upload_stores_the_file_even_when_cascadio_is_unavailable(ws: Workspace, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(attachments_module, "cascadio", None)
    monkeypatch.setattr(attachments_module, "trimesh", None)

    result = attachments_module.save_attachment(ws, "com.example.demo", "part.step", _FAKE_STEP_BYTES)

    assert result == {"filename": "part.step", "kind": "step", "measured_envelope_mm": None, "glb": None}
    # The upload itself never fails -- the raw file is on disk regardless.
    assert (ws.attachments_dir("com.example.demo") / "part.step").read_bytes() == _FAKE_STEP_BYTES


def test_step_upload_stores_the_file_even_when_conversion_raises(ws: Workspace, monkeypatch: pytest.MonkeyPatch):
    class _ExplodingCascadio:
        def step_to_glb(self, step_path: str, glb_path: str) -> None:
            # Simulate a CAD kernel choking on a real-world file, and (as a
            # real failure plausibly would) leaving a partial file behind
            # before raising.
            Path(glb_path).write_bytes(b"not a real glb")
            raise RuntimeError("kernel exploded on this geometry")

    monkeypatch.setattr(attachments_module, "cascadio", _ExplodingCascadio())

    result = attachments_module.save_attachment(ws, "com.example.demo", "part.stp", _FAKE_STEP_BYTES)

    assert result["measured_envelope_mm"] is None
    assert result["glb"] is None
    assert (ws.attachments_dir("com.example.demo") / "part.stp").is_file()
    # The partial GLB a failed conversion left behind must not linger --
    # a later chat turn could otherwise try to load it as if it were real.
    assert not (ws.attachments_dir("com.example.demo") / "part.glb").exists()


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

    result = attachments_module.save_attachment(ws, "com.example.demo", "part.step", _FAKE_STEP_BYTES)

    assert result["measured_envelope_mm"] == [120.0, 80.5, 45.0]
    assert result["glb"] == "part.glb"
    assert (ws.attachments_dir("com.example.demo") / "part.glb").is_file()


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
    attachments_module.save_attachment(ws, "com.example.demo", "part.step", _FAKE_STEP_BYTES)

    blocks = attachments_module.attachment_content_blocks(ws, "com.example.demo", ["part.step"])

    assert blocks[0]["type"] == "text"
    assert "unavailable" in blocks[0]["text"]
    assert "no measured envelope" in blocks[0]["text"]


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

    attachments_module.save_attachment(ws, "com.example.demo", "part.step", _FAKE_STEP_BYTES)
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
    assert listing.json()["files"] == [{"filename": "notes.txt", "kind": "text", "glb": None}]

    download = client.get("/components/com.example.http-demo/attachments/notes.txt")
    assert download.status_code == 200
    assert download.content == b"stated: 4-6 bar"


def test_http_download_of_an_unknown_attachment_is_a_404(tmp_path: Path):
    client = TestClient(build_app(str(tmp_path / "repo")))
    response = client.get("/components/com.example.http-demo/attachments/never-uploaded.pdf")
    assert response.status_code == 404
