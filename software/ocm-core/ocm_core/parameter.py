# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared value types from the schema's $defs: parameter and frame."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Parameter:
    """A typed, bounded, unit-carrying value ($defs/parameter).

    Bounds (min/max) are hard limits: the generator must reject a plan that
    exceeds them, and the agent must never propose one. ocm-core only carries
    the declaration — enforcing it against an actual plan is validate/'s job.
    """

    type: str
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    default: Any = None
    values: tuple[Any, ...] | None = None
    required: bool = True
    summary: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Parameter":
        values = data.get("values")
        return cls(
            type=data["type"],
            unit=data.get("unit"),
            min=data.get("min"),
            max=data.get("max"),
            default=data.get("default"),
            values=tuple(values) if values is not None else None,
            required=data.get("required", True),
            summary=data.get("summary"),
        )


@dataclass(frozen=True)
class Frame:
    """A named coordinate frame ($defs/frame), relative to `parent` (default origin)."""

    xyz_mm: tuple[float, float, float]
    rpy_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    parent: str = "origin"
    note: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Frame":
        return cls(
            xyz_mm=tuple(data["xyz_mm"]),
            rpy_deg=tuple(data.get("rpy_deg", (0.0, 0.0, 0.0))),
            parent=data.get("parent", "origin"),
            note=data.get("note"),
        )
