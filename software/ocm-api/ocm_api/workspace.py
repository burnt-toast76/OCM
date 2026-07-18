# SPDX-License-Identifier: AGPL-3.0-or-later
"""A repo working tree ocm-api operates against -- spec/09: "Files are the
state; git is the review layer. Every mutation lands in the working tree."
No hidden server state beyond this path (spec/09's determinism rule).

`read_yaml`/`write_yaml` reuse ocm_core's own YAML loader (`_read_yaml`,
its private-but-stable YAML-1.2-boolean-resolution `SafeLoader` subclass)
rather than re-implementing it -- a second, subtly different YAML reader
in this package would be exactly the kind of logic duplication spec/09
and this task both rule out. `on: robot1.flange` must keep parsing as a
string key, not `True`, every place this repo reads YAML.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from ocm_core.loader import DEFAULT_SCHEMA_PATH, _read_yaml  # noqa: F401 -- see module docstring


def read_yaml(path: Path) -> Any:
    return _read_yaml(path)


def write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


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
    def schema_path(self) -> Path:
        candidate = self.root / "spec" / "schema" / "ocm-module-1.0.schema.json"
        return candidate if candidate.is_file() else Path(DEFAULT_SCHEMA_PATH)

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

    def module_exists(self, module_id: str) -> bool:
        return self.module_path(module_id).is_file()

    def cell_exists(self, cell_id: str) -> bool:
        return self.cell_path(cell_id).is_file()

    def list_module_ids(self) -> list[str]:
        if not self.modules_dir.is_dir():
            return []
        return sorted(p.parent.name for p in self.modules_dir.glob("*/module.yaml"))

    def list_cell_ids(self) -> list[str]:
        if not self.cells_dir.is_dir():
            return []
        return sorted(p.parent.name for p in self.cells_dir.glob("*/cell.yaml"))
