# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one response shape every ocm-api verb returns -- spec/09-ocm-api.md's
design principle #1: "Refusals are results, not errors." An agent or a GUI
renders `Envelope.to_dict()`; neither ever catches an exception from this
package's own verbs (`OcmApi`'s methods don't raise for ordinary refusals --
only for genuinely unexpected failures, e.g. a missing repo path).

`Envelope.to_dict()` is the ONE canonical JSON-shape function. The MCP
server and the HTTP wrapper both call it and pass the result straight
through their own transport's serialization with no reshaping -- that's
what makes their responses byte-identical to the library call and to each
other for the same verb call (see tests/test_envelope_consistency.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class Codes:
    """Every refusal code this package emits. Two are named directly in
    spec/09-ocm-api.md (`PARAM_OUT_OF_BOUNDS`, `HUMAN_SIGNATURE_REQUIRED`);
    the rest name scenarios the spec describes narratively (unknown
    module, dangling mount.on, workspace overhang, ...) without pinning a
    literal code string -- these are this library's own, chosen once here
    so every verb that can hit the same scenario uses the same code.
    """

    SCHEMA_INVALID = "SCHEMA_INVALID"
    CELL_INVALID = "CELL_INVALID"
    NOT_FOUND = "NOT_FOUND"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    HUMAN_SIGNATURE_REQUIRED = "HUMAN_SIGNATURE_REQUIRED"
    DRAFT_NOT_PUBLISHABLE = "DRAFT_NOT_PUBLISHABLE"
    UNKNOWN_MODULE = "UNKNOWN_MODULE"
    REVISION_MISMATCH = "REVISION_MISMATCH"
    DANGLING_MOUNT = "DANGLING_MOUNT"
    DRAFT_MODULE_REFERENCED = "DRAFT_MODULE_REFERENCED"
    WORKSPACE_OVERHANG = "WORKSPACE_OVERHANG"
    UNKNOWN_OP = "UNKNOWN_OP"
    UNKNOWN_PARAM = "UNKNOWN_PARAM"
    PARAM_OUT_OF_BOUNDS = "PARAM_OUT_OF_BOUNDS"
    NO_FASTENING_STEP = "NO_FASTENING_STEP"
    POSE_UNREACHABLE = "POSE_UNREACHABLE"
    PATH_COLLISION = "PATH_COLLISION"
    COLLISION_DETECTED = "COLLISION_DETECTED"
    UNAVAILABLE = "UNAVAILABLE"  # a needed optional extra (e.g. tesseract) isn't installed
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    UNKNOWN_COMPONENT = "UNKNOWN_COMPONENT"  # ADR-0014: a components: entry's ref doesn't resolve
    DUPLICATE_REFDES = "DUPLICATE_REFDES"  # ADR-0014: two components: entries share a refdes
    INVALID_SOURCE = "INVALID_SOURCE"  # ADR-0014: a signal's source: provenance doesn't check out
    TOOL_SLOT_OCCUPIED = "TOOL_SLOT_OCCUPIED"  # place_instance onto a mount.on flange that's already carrying an instance


@dataclass(frozen=True)
class Refusal:
    code: str
    path: str
    message: str
    allowed: dict[str, Any] | None = None
    hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "path": self.path, "message": self.message}
        d["allowed"] = self.allowed
        d["hint"] = self.hint
        return d


@dataclass(frozen=True)
class Envelope:
    ok: bool
    refusals: tuple[Refusal, ...] = ()
    warnings: tuple[str, ...] = ()
    data: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "refusals": [r.to_dict() for r in self.refusals],
            "warnings": list(self.warnings),
            "data": self.data,
        }

    @classmethod
    def refuse(cls, refusals: list[Refusal], warnings: list[str] | None = None) -> "Envelope":
        return cls(ok=False, refusals=tuple(refusals), warnings=tuple(warnings or ()))

    @classmethod
    def succeed(cls, data: Any = None, warnings: list[str] | None = None) -> "Envelope":
        return cls(ok=True, data=data, warnings=tuple(warnings or ()))


def single_refusal(code: str, path: str, message: str, allowed: dict[str, Any] | None = None, hint: str | None = None) -> Envelope:
    return Envelope.refuse([Refusal(code=code, path=path, message=message, allowed=allowed, hint=hint)])
