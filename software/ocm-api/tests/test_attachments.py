# SPDX-License-Identifier: AGPL-3.0-or-later
"""spec/09 "Agent orchestrator": shared component/module attachment
storage, and the STEP->GLB conversion's graceful degradation -- an upload
NEVER fails because geometry conversion did (cascadio simply absent, or a
real conversion failure), it just proceeds without a measured envelope.

Every public function in attachments.py takes a bare directory (Path), not
a component/module id -- component and module attachments share the exact
same storage/conversion machinery (attachments.py itself has no
entity-specific logic at all). Most tests below exercise it against a
component's own attachments_dir, since that's the original/more heavily
used call site; a dedicated section near the bottom proves the identical
machinery works against a module's own attachments dir too, including
resume_pending_step_conversions handling BOTH kinds of directory together.

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
_FAKE_STEP_BYTES = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "repo")


@pytest.fixture
def directory(ws: Workspace) -> Path:
    # The overwhelming majority of these tests only care about "some
    # attachments directory" -- a component's own is the original/more
    # heavily exercised call site. Module-directory coverage lives in its
    # own section near the bottom.
    return ws.attachments_dir("com.example.demo")


def _write_component_stub(ws: Workspace, component_id: str) -> None:
    # resume_pending_step_conversions' caller (http_app.py's lifespan)
    # enumerates via Workspace.list_component_ids/list_module_ids, which
    # (correctly, for real usage: a component.yaml/module.yaml always
    # exists before any attachment can be uploaded through the real API)
    # requires that manifest file -- tests that call save_attachment
    # directly, without going through create_component_draft first, need
    # to write it themselves.
    write_yaml(ws.component_path(component_id), {"ocm_version": "1.1", "id": component_id, "revision": "0.1.0", "kind": "sensor"})


def _write_module_stub(ws: Workspace, module_id: str) -> None:
    write_yaml(ws.module_path(module_id), {"ocm_version": "1.1", "id": module_id, "revision": "0.1.0", "kind": "fixture"})


# ---------------------------------------------------------------------------
# Plain storage (PDF/text) -- always unconditional, never touches cascadio.
# ---------------------------------------------------------------------------


def test_pdf_upload_is_stored_and_classified(directory: Path):
    result = attachments_module.save_attachment(directory, "datasheet.pdf", b"%PDF-1.4 fake pdf bytes")
    assert result == {"filename": "datasheet.pdf", "kind": "pdf", "measured_envelope_mm": None, "glb": None, "glb_status": None}
    assert (directory / "datasheet.pdf").read_bytes() == b"%PDF-1.4 fake pdf bytes"


def test_text_upload_is_stored_and_classified(directory: Path):
    result = attachments_module.save_attachment(directory, "notes.txt", b"stated: 4-6 bar")
    assert result["kind"] == "text"


def test_upload_filename_is_sanitized_against_path_traversal(ws: Workspace, directory: Path):
    result = attachments_module.save_attachment(directory, "../../evil.txt", b"x")
    assert result["filename"] == "evil.txt"
    assert (directory / "evil.txt").is_file()
    # Never escaped this entity's own attachments directory.
    assert not (ws.root / "evil.txt").exists()


# ---------------------------------------------------------------------------
# STEP -> GLB: runs in the background; the upload response only ever
# reports glb_status: "pending" for a STEP file (this turn's explicit test
# requirement -- the actual outcome is discovered later, via
# list_attachments).
# ---------------------------------------------------------------------------


def test_step_upload_returns_pending_immediately_and_stores_the_raw_file(directory: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(attachments_module, "cascadio", None)
    monkeypatch.setattr(attachments_module, "trimesh", None)

    result = attachments_module.save_attachment(directory, "part.step", _FAKE_STEP_BYTES, run_conversion=_INLINE)

    assert result == {"filename": "part.step", "kind": "step", "measured_envelope_mm": None, "glb": None, "glb_status": "pending"}
    # The upload itself never fails -- the raw file is on disk regardless.
    assert (directory / "part.step").read_bytes() == _FAKE_STEP_BYTES


def test_step_upload_returns_before_a_slow_conversion_finishes(directory: Path, monkeypatch: pytest.MonkeyPatch):
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
    # _convert_step_to_glb short-circuits before ever calling cascadio if
    # EITHER dependency is None -- on a machine without trimesh installed,
    # leaving the real (None) value in place would skip the conversion
    # entirely and `started` would never fire. This test is about the
    # threading, not about trimesh, so it only needs to stay non-None;
    # nothing here asserts on the measured envelope.
    monkeypatch.setattr(attachments_module, "trimesh", object())

    result = attachments_module.save_attachment(directory, "part.step", _FAKE_STEP_BYTES)

    assert result["glb_status"] == "pending"
    assert started.wait(timeout=5), "conversion never started in the background"
    # The upload call already returned above -- prove the glb genuinely
    # isn't there yet (conversion is still blocked on `release`).
    assert not (directory / "part.glb").exists()
    release.set()  # let the background thread finish so it doesn't leak into the next test


def test_step_upload_stores_the_file_even_when_conversion_raises(directory: Path, monkeypatch: pytest.MonkeyPatch):
    class _ExplodingCascadio:
        def step_to_glb(self, step_path: str, glb_path: str) -> None:
            # Simulate a CAD kernel choking on a real-world file, and (as a
            # real failure plausibly would) leaving a partial file behind
            # before raising.
            Path(glb_path).write_bytes(b"not a real glb")
            raise RuntimeError("kernel exploded on this geometry")

    monkeypatch.setattr(attachments_module, "cascadio", _ExplodingCascadio())

    attachments_module.save_attachment(directory, "part.stp", _FAKE_STEP_BYTES, run_conversion=_INLINE)

    assert (directory / "part.stp").is_file()
    # The partial GLB a failed conversion left behind must not linger --
    # a later chat turn could otherwise try to load it as if it were real.
    assert not (directory / "part.glb").exists()
    rows = attachments_module.list_attachments(directory)
    assert rows[0]["glb_status"] == "failed"


def test_step_upload_measures_the_envelope_on_success(directory: Path, monkeypatch: pytest.MonkeyPatch):
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

    attachments_module.save_attachment(directory, "part.step", _FAKE_STEP_BYTES, run_conversion=_INLINE)

    assert (directory / "part.glb").is_file()
    rows = attachments_module.list_attachments(directory)
    assert rows[0]["glb"] == "part.glb"
    assert rows[0]["glb_status"] == "ready"
    assert rows[0]["measured_envelope_mm"] == [120.0, 80.5, 45.0]


def test_a_re_upload_clears_a_stale_failed_marker_before_retrying(directory: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(attachments_module, "cascadio", None)
    attachments_module.save_attachment(directory, "part.step", _FAKE_STEP_BYTES, run_conversion=_INLINE)
    assert attachments_module.list_attachments(directory)[0]["glb_status"] == "failed"

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

    attachments_module.save_attachment(directory, "part.step", _FAKE_STEP_BYTES, run_conversion=_INLINE)

    assert attachments_module.list_attachments(directory)[0]["glb_status"] == "ready"


# ---------------------------------------------------------------------------
# resume_pending_step_conversions: startup catch-up for a conversion a
# previous process's restart interrupted.
# ---------------------------------------------------------------------------


def test_resume_converts_a_step_file_left_without_a_glb(directory: Path, monkeypatch: pytest.MonkeyPatch):
    # No conversion attempted at all yet (as if this process just started
    # and a previous one died mid-conversion, or never got to it).
    attachments_module.save_attachment(directory, "part.step", _FAKE_STEP_BYTES, run_conversion=lambda fn: None)
    assert attachments_module.list_attachments(directory)[0]["glb_status"] == "pending"

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

    attachments_module.resume_pending_step_conversions([directory], run_conversion=_INLINE)

    assert attachments_module.list_attachments(directory)[0]["glb_status"] == "ready"


def test_resume_does_not_touch_a_step_file_that_already_converted(directory: Path, monkeypatch: pytest.MonkeyPatch):
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
    attachments_module.save_attachment(directory, "part.step", _FAKE_STEP_BYTES, run_conversion=_INLINE)
    original_bytes = (directory / "part.glb").read_bytes()

    calls = []
    attachments_module.resume_pending_step_conversions([directory], run_conversion=lambda fn: calls.append(fn))

    assert calls == []
    assert (directory / "part.glb").read_bytes() == original_bytes


def test_resume_handles_a_component_and_a_module_directory_together(ws: Workspace, monkeypatch: pytest.MonkeyPatch):
    # The actual shape resume_pending_step_conversions is called in
    # (http_app.py's lifespan): a mixed list of every component's AND
    # every module's own attachments directory, in one pass.
    component_dir = ws.attachments_dir("com.example.demo")
    module_dir = ws.module_attachments_dir("com.example.fixture.nest1")
    attachments_module.save_attachment(component_dir, "part.step", _FAKE_STEP_BYTES, run_conversion=lambda fn: None)
    attachments_module.save_attachment(module_dir, "assembly.step", _FAKE_STEP_BYTES, run_conversion=lambda fn: None)
    attachments_module._CONVERTING.clear()

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

    attachments_module.resume_pending_step_conversions([component_dir, module_dir], run_conversion=_INLINE)

    assert attachments_module.list_attachments(component_dir)[0]["glb_status"] == "ready"
    assert attachments_module.list_attachments(module_dir)[0]["glb_status"] == "ready"


# ---------------------------------------------------------------------------
# attachment_content_blocks: what gets injected into a chat turn.
# ---------------------------------------------------------------------------


def test_pdf_becomes_a_document_block(directory: Path):
    attachments_module.save_attachment(directory, "sheet.pdf", b"%PDF-1.4 x")
    blocks = attachments_module.attachment_content_blocks(directory, ["sheet.pdf"])
    assert len(blocks) == 1
    assert blocks[0]["type"] == "document"
    assert blocks[0]["source"]["media_type"] == "application/pdf"


def test_text_becomes_a_text_block_with_its_content(directory: Path):
    attachments_module.save_attachment(directory, "notes.txt", b"stated: 4-6 bar")
    blocks = attachments_module.attachment_content_blocks(directory, ["notes.txt"])
    assert blocks[0]["type"] == "text"
    assert "4-6 bar" in blocks[0]["text"]


def test_step_with_no_successful_conversion_becomes_a_note_saying_so(directory: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(attachments_module, "cascadio", None)
    attachments_module.save_attachment(directory, "part.step", _FAKE_STEP_BYTES, run_conversion=_INLINE)

    blocks = attachments_module.attachment_content_blocks(directory, ["part.step"])

    assert blocks[0]["type"] == "text"
    assert "unavailable" in blocks[0]["text"]
    assert "no measured envelope" in blocks[0]["text"]


def test_step_still_converting_becomes_a_note_saying_so_not_a_silent_gap(directory: Path):
    # A chat turn that fires while conversion is still running (a real
    # possibility now that it's backgrounded) must say so, not read
    # identically to "conversion was never attempted."
    attachments_module.save_attachment(directory, "part.step", _FAKE_STEP_BYTES, run_conversion=lambda fn: None)

    blocks = attachments_module.attachment_content_blocks(directory, ["part.step"])

    assert blocks[0]["type"] == "text"
    assert "still running" in blocks[0]["text"]
    attachments_module._CONVERTING.clear()  # the abandoned "pending" from the never-run thread above


def test_a_filename_that_does_not_exist_is_silently_skipped(directory: Path):
    assert attachments_module.attachment_content_blocks(directory, ["never-uploaded.pdf"]) == []


def test_list_attachments_reports_a_step_files_glb_sibling_and_excludes_the_glb_itself(directory: Path, monkeypatch: pytest.MonkeyPatch):
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

    attachments_module.save_attachment(directory, "part.step", _FAKE_STEP_BYTES, run_conversion=_INLINE)
    attachments_module.save_attachment(directory, "sheet.pdf", b"%PDF-1.4 x")

    rows = attachments_module.list_attachments(directory)
    by_name = {r["filename"]: r for r in rows}

    assert set(by_name) == {"part.step", "sheet.pdf"}  # the .glb itself is not a separate row
    assert by_name["part.step"]["glb"] == "part.glb"
    assert by_name["sheet.pdf"]["glb"] is None


# ---------------------------------------------------------------------------
# HTTP transport: upload, list, and download -- components.
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
    # up on its own, with no new upload needed. Covers BOTH a component's
    # and a module's own attachments directory in one pass, proving the
    # generalized lifespan call in http_app.py actually chains both.
    repo_root = tmp_path / "repo"
    ws = Workspace(repo_root)
    _write_component_stub(ws, "com.example.http-demo")
    _write_module_stub(ws, "com.example.fixture.http-demo")
    attachments_module.save_attachment(ws.attachments_dir("com.example.http-demo"), "part.step", _FAKE_STEP_BYTES, run_conversion=lambda fn: None)
    attachments_module.save_attachment(
        ws.module_attachments_dir("com.example.fixture.http-demo"), "assembly.step", _FAKE_STEP_BYTES, run_conversion=lambda fn: None
    )
    attachments_module._CONVERTING.clear()  # simulate the process that would have run these having died

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

    assert attachments_module.list_attachments(ws.attachments_dir("com.example.http-demo"))[0]["glb_status"] == "ready"
    assert attachments_module.list_attachments(ws.module_attachments_dir("com.example.fixture.http-demo"))[0]["glb_status"] == "ready"


# ---------------------------------------------------------------------------
# HTTP transport: upload, list, and download -- modules. Same routes,
# same shape, proving the module side of http_app.py's new routes works
# identically to the (much more heavily exercised) component ones above.
# ---------------------------------------------------------------------------


def test_http_module_upload_then_list_then_download_round_trip(tmp_path: Path):
    client = TestClient(build_app(str(tmp_path / "repo")))

    upload = client.post(
        "/modules/com.example.fixture.http-demo/attachments",
        files={"file": ("reference.txt", b"assembly reference note", "text/plain")},
    )
    assert upload.status_code == 200
    assert upload.json()["kind"] == "text"

    listing = client.get("/modules/com.example.fixture.http-demo/attachments")
    assert listing.status_code == 200
    assert listing.json()["files"] == [
        {"filename": "reference.txt", "kind": "text", "glb": None, "glb_status": None, "measured_envelope_mm": None}
    ]

    download = client.get("/modules/com.example.fixture.http-demo/attachments/reference.txt")
    assert download.status_code == 200
    assert download.content == b"assembly reference note"


def test_http_download_of_an_unknown_module_attachment_is_a_404(tmp_path: Path):
    client = TestClient(build_app(str(tmp_path / "repo")))
    response = client.get("/modules/com.example.fixture.http-demo/attachments/never-uploaded.pdf")
    assert response.status_code == 404
