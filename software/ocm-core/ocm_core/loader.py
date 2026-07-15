# SPDX-License-Identifier: AGPL-3.0-or-later
"""File I/O: read manifest/cell YAML off disk, validate, and build typed objects."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .cell import Cell, validate_cell_dict
from .errors import CellLoadError, ManifestValidationError
from .module import Module

# software/ocm-core/ocm_core/loader.py -> repo root
DEFAULT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "spec" / "schema" / "ocm-module-1.0.schema.json"
)


class _Loader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2 boolean resolution instead of PyYAML's YAML 1.1 default.

    PyYAML's SafeLoader resolves bare `on`/`off`/`yes`/`no` (as scalars OR as
    mapping keys) to booleans. That silently turns a mount key like
    `on: robot1.flange` into `{True: "robot1.flange"}`. The schema and every
    manifest in this repo assume JSON-compatible (YAML 1.2) bool semantics
    (`true`/`false` only), so narrow the resolver to match.
    """


_Loader.yaml_implicit_resolvers = {
    key: [r for r in resolvers if r[0] != "tag:yaml.org,2002:bool"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


def _read_yaml(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.load(f, Loader=_Loader)


def load_schema(schema_path: Path | str = DEFAULT_SCHEMA_PATH) -> dict[str, Any]:
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_module_dict(data: Any, schema: dict[str, Any]) -> list[str]:
    """Return every schema violation as a readable string (empty list if valid)."""
    validator = Draft202012Validator(schema)
    violations = sorted(validator.iter_errors(data), key=lambda e: list(map(str, e.path)))
    return [f"{'/'.join(str(p) for p in v.path) or '<root>'}: {v.message}" for v in violations]


def load_module(path: Path | str, schema_path: Path | str = DEFAULT_SCHEMA_PATH) -> Module:
    """Load a module manifest YAML file, validate it against the OCM module
    schema, and return a typed Module.

    Raises ManifestValidationError (carrying every violation, not just the
    first) if the manifest doesn't conform.
    """
    path = Path(path)
    data = _read_yaml(path)
    schema = load_schema(schema_path)
    errors = validate_module_dict(data, schema)
    if errors:
        raise ManifestValidationError(path, errors)
    return Module.from_dict(data)


def load_cell(path: Path | str) -> Cell:
    """Load a cell composition YAML file into a typed Cell.

    No JSON Schema exists yet for the cell-composition shape, so this
    performs structural checks (see cell.validate_cell_dict) rather than
    full schema validation.
    """
    path = Path(path)
    data = _read_yaml(path)
    errors = validate_cell_dict(data)
    if errors:
        raise CellLoadError(path, errors)
    return Cell.from_dict(data)
