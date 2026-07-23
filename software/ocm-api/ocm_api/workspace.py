# SPDX-License-Identifier: AGPL-3.0-or-later
"""A repo working tree ocm-api operates against -- spec/09: "Files are the
state; git is the review layer. Every mutation lands in the working tree."
No hidden server state beyond this path (spec/09's determinism rule).

`read_yaml` reuses ocm_core's own YAML loader (`_read_yaml`, its
private-but-stable YAML-1.2-boolean-resolution `SafeLoader` subclass)
rather than re-implementing it -- a second, subtly different YAML reader
in this package would be exactly the kind of logic duplication spec/09
and this task both rule out. `on: robot1.flange` must keep parsing as a
string key, not `True`, every place this repo reads YAML. Loading for
validation goes through this one unchanged path everywhere.

`write_yaml` is comment-preserving. This repo's YAML comments carry real
design intent (ADR references, "placeholder -- not authored yet",
provisional-value caveats) -- a plain yaml.safe_dump round-trip silently
destroyed every one of them on the first agent-driven write, which makes
the resulting diff unreviewable. Ruamel's round-trip mode (`typ="rt"`)
loads the EXISTING file into a comment-carrying `CommentedMap`/
`CommentedSeq` tree; the new data is applied to that tree as an RFC-6902
patch (diffed against the old file's plain value via the same `jsonpatch`
already used for `update_module`'s explicit patch verb) rather than as a
full replacement, so untouched keys -- and their comments -- never move.
Ruamel's `CommentedMap`/`CommentedSeq` satisfy `MutableMapping`/
`MutableSequence`, so `jsonpatch.apply_patch` mutates them exactly the way
it mutates a plain dict/list; nothing here re-implements patch application.
A brand new file (nothing to preserve) is written fresh.

One honest limitation: round-trip mode preserves comments, key order,
blank-line grouping, flow-vs-block style, and quoting -- but NOT manual
inter-column alignment whitespace (`id:       foo`) some of this repo's
earliest, hand-typed files use for visual alignment. That padding isn't
meaningful YAML syntax any round-trip library models as preservable state;
re-serializing such a file re-flows it to single-space `key: value` even
on an untouched line. Files written by this package's own dumps (and
these tests' own fixtures) never used that style, so it doesn't recur.
"""

from __future__ import annotations

import io
import os
import tempfile
import threading
from collections import defaultdict
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonpatch
from ocm_core.loader import DEFAULT_COMPONENT_SCHEMA_PATH, DEFAULT_SCHEMA_PATH, _read_yaml  # noqa: F401 -- see module docstring
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

def _new_yaml_rt() -> YAML:
    # A fresh instance per call, not a module-level singleton: ruamel's
    # YAML object is stateful (its emitter/parser carry position and
    # anchor state across a load/dump), and isn't safe for concurrent use
    # -- two threads round-tripping *different* files through one shared
    # instance at the same time corrupted output with errors like
    # "EmitterError: expected NodeEvent, but got DocumentStartEvent()"
    # even though the per-path lock below fully serializes writes to any
    # single file. The per-path lock stays -- it's still needed for the
    # read-merge-write sequence to be atomic with respect to itself --
    # but the YAML instance doing the actual parsing/emitting must not be
    # shared across files.
    yaml_rt = YAML(typ="rt")
    yaml_rt.preserve_quotes = True
    yaml_rt.width = 100_000  # never line-wrap -- wrapping would show up as diff noise unrelated to the actual change
    yaml_rt.indent(mapping=2, sequence=2, offset=0)  # this repo's own convention: block sequences flush with their parent key
    return yaml_rt


# FastAPI runs sync route handlers (every verb in http_app.py) in a
# threadpool, so two HTTP requests hitting the same file -- entirely
# realistic: the composer's own debounced move_instance drag fires one
# call every ~200ms, and the pointer-up "final" call can genuinely
# overlap the last in-flight debounced one -- are truly concurrent, not
# just interleaved by an event loop. A bare path.write_text() is neither
# atomic nor mutually exclusive: two overlapping writers can each open
# the same path, and the OS is free to interleave their writes, which
# corrupts the file into neither writer's content (found empirically:
# the tail of a shorter write left dangling after a longer one). One
# lock per resolved path serializes the whole read-merge-write sequence
# for that file; the write itself lands via a temp-file-then-rename
# (os.replace, atomic on both POSIX and Windows/NTFS for a same-volume
# rename), so even a writer this process doesn't know about can never
# observe a half-written file.
#
# read_yaml takes the SAME lock, not just write_yaml: on Windows, a plain
# open(path, "r") does not request FILE_SHARE_DELETE, so a reader with the
# file open blocks a concurrent os.replace() targeting that path outright
# (found empirically: "PermissionError: [WinError 5] Access is denied"
# from a GET verb's read landing mid-rename during a drag). POSIX rename
# never had this problem -- open file handles don't block it -- but the
# lock is cheap and the read is brief, so serializing reads with writes
# here is simpler than maintaining two different concurrency stories per
# platform.
_file_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
_file_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _file_locks_guard:
        return _file_locks[key]


def read_yaml(path: Path) -> Any:
    with _lock_for(path):
        return _read_yaml(path)


def write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with _lock_for(path):
        yaml_rt = _new_yaml_rt()
        doc: Any = data
        if path.is_file():
            with path.open("r", encoding="utf-8") as f:
                existing = yaml_rt.load(f)
            if isinstance(existing, (CommentedMap, dict, list)):
                old_plain = _read_yaml(path) or {}
                ops = jsonpatch.make_patch(old_plain, data).patch
                if ops:
                    jsonpatch.apply_patch(existing, ops, in_place=True)
                doc = existing
            # else: existing content isn't a mapping/sequence (a malformed
            # or non-standard file) -- nothing structured to preserve, fall
            # through to writing `data` fresh.

        buf = io.StringIO()
        yaml_rt.dump(doc, buf)
        text = buf.getvalue()

        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp_name, path)
        except BaseException:
            with suppress(OSError):
                os.remove(tmp_name)
            raise


def is_draft_revision(revision: str) -> bool:
    """Spec/09: "Draft = revision: 0.x, excluded from cell resolution
    until published." Purely a convention on the revision string -- no
    separate draft flag anywhere.
    """
    major = revision.split(".", 1)[0]
    return major == "0"


@dataclass(frozen=True)
class Workspace:
    root: Path

    @property
    def modules_dir(self) -> Path:
        return self.root / "modules"

    @property
    def cells_dir(self) -> Path:
        return self.root / "cells"

    @property
    def components_dir(self) -> Path:
        return self.root / "components"

    @property
    def schema_path(self) -> Path:
        candidate = self.root / "spec" / "schema" / "ocm-module-1.0.schema.json"
        return candidate if candidate.is_file() else Path(DEFAULT_SCHEMA_PATH)

    @property
    def component_schema_path(self) -> Path:
        candidate = self.root / "spec" / "schema" / "ocm-component-1.0.schema.json"
        return candidate if candidate.is_file() else Path(DEFAULT_COMPONENT_SCHEMA_PATH)

    @property
    def changelog_path(self) -> Path:
        return self.root / "spec" / "CHANGELOG.md"

    def module_dir(self, module_id: str) -> Path:
        return self.modules_dir / module_id

    def module_path(self, module_id: str) -> Path:
        return self.module_dir(module_id) / "module.yaml"

    def cell_dir(self, cell_id: str) -> Path:
        return self.cells_dir / cell_id

    def cell_path(self, cell_id: str) -> Path:
        return self.cell_dir(cell_id) / "cell.yaml"

    def component_dir(self, component_id: str) -> Path:
        return self.components_dir / component_id

    def component_path(self, component_id: str) -> Path:
        return self.component_dir(component_id) / "component.yaml"

    def attachments_dir(self, component_id: str) -> Path:
        # Uploads (datasheets, STEP files, ...) live alongside the
        # component they document -- not a separate top-level tree -- so
        # `components/<id>/` stays the one place everything about that
        # component lives, same convention module geometry already follows.
        return self.component_dir(component_id) / "attachments"

    def module_attachments_dir(self, module_id: str) -> Path:
        # Same convention as attachments_dir, one level up: a module's own
        # uploaded STEP (a non-interactive visual backdrop for the Modules
        # page, never a claimed/authoritative path like mechanical.geometry.*)
        # lives under modules/<id>/attachments/, not a separate tree.
        return self.module_dir(module_id) / "attachments"

    def module_exists(self, module_id: str) -> bool:
        return self.module_path(module_id).is_file()

    def cell_exists(self, cell_id: str) -> bool:
        return self.cell_path(cell_id).is_file()

    def component_exists(self, component_id: str) -> bool:
        return self.component_path(component_id).is_file()

    def list_module_ids(self) -> list[str]:
        if not self.modules_dir.is_dir():
            return []
        return sorted(p.parent.name for p in self.modules_dir.glob("*/module.yaml"))

    def list_cell_ids(self) -> list[str]:
        if not self.cells_dir.is_dir():
            return []
        return sorted(p.parent.name for p in self.cells_dir.glob("*/cell.yaml"))

    def list_component_ids(self) -> list[str]:
        if not self.components_dir.is_dir():
            return []
        return sorted(p.parent.name for p in self.components_dir.glob("*/component.yaml"))
