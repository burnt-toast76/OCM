# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every YAML this project writes is LF, on every platform.

The store is content-addressed and lives in git under `claims/** -text`, so
git stores exactly the bytes the writer produced. Text mode translates "\\n"
to os.linesep, which made the same append emit different bytes on Windows and
on Linux: a one-line append to a 492-line claims entry came back as 492
changed lines, and two machines disagreed byte-for-byte about a file neither
had changed.

Claim ids hash record content, never file bytes, so no id ever moved -- which
is precisely why this went unnoticed. Nothing but a test on the bytes catches
it, and on Linux the bug is invisible, so the assertion has to be about the
bytes rather than about the platform.
"""

from __future__ import annotations

from pathlib import Path

from ocm_api import OcmApi
from ocm_api.workspace import write_yaml


def test_write_yaml_emits_lf_on_every_platform(tmp_path: Path):
    path = tmp_path / "thing.yaml"
    write_yaml(path, {"ocm_version": "1.0", "notes": ["one", "two"], "nested": {"a": 1}})

    raw = path.read_bytes()
    assert b"\r\n" not in raw, "write_yaml emitted CRLF -- text mode translated the newlines"
    assert raw.count(b"\n") >= 4  # the write really did produce multiple lines


def test_rewriting_an_existing_file_does_not_change_its_line_endings(tmp_path: Path):
    """The merge path (existing file -> jsonpatch -> dump) is a second writer
    and regressed independently of the first."""
    path = tmp_path / "thing.yaml"
    write_yaml(path, {"ocm_version": "1.0", "value": 1})
    write_yaml(path, {"ocm_version": "1.0", "value": 2})

    assert b"\r\n" not in path.read_bytes()


def test_an_api_write_emits_lf_even_over_a_file_that_arrived_with_crlf(api: OcmApi, workspace_root: Path):
    """End to end, through a real verb.

    The file this writes over may well arrive as CRLF: git converts on
    checkout for everything except the paths `.gitattributes` marks `-text`,
    and `claims/**` is marked precisely so the store escapes that. So the
    invariant is about what the writer PRODUCES, not what it found -- writing
    LF is right in both cases, since git normalizes on commit for the paths it
    manages and the store needs LF for the ones it does not.
    """
    module_id = "com.accelsolutions.base.frame1200"
    path = workspace_root / "modules" / module_id / "module.yaml"

    e = api.update_module(module_id, patch=[{"op": "replace", "path": "/mechanical/mass_kg", "value": 91.0}])
    assert e.ok, e.refusals

    assert b"\r\n" not in path.read_bytes(), "an API write emitted CRLF"
