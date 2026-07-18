# SPDX-License-Identifier: AGPL-3.0-or-later
"""Translate the plain-string violations ocm-core/ocm-resolve/ocm-generator
already collect (ManifestValidationError.errors, CellResolutionError.errors,
SceneBuildError.errors, ...) into structured `Refusal`s -- spec/09's
envelope wants `path`/`code`/`allowed`, not a paragraph.

This is deliberately a set of regexes over ALREADY-STABLE message text, not
a second implementation of the underlying checks -- the checks themselves
(bounds, known-ops, mount chains, workspace footprint, ...) still live
exactly once, in the packages that already implement them. Nothing here
re-derives a violation; it only re-shapes one that's already been found.
Every existing check's own test suite already pins its message text down
(e.g. `ocm_generator`'s `test_scene_build_real_bracket_cell.py` asserts
"+X" appears in its own overhang string) -- these patterns lean on that
same stability.

A pattern that doesn't match anything falls through to `CELL_INVALID` /
`SCHEMA_INVALID` with the raw text preserved in `message` -- no information
is ever dropped just because a message doesn't fit a known shape yet.
"""

from __future__ import annotations

import re
from typing import Any

from .envelope import Codes, Refusal

# ---------------------------------------------------------------------------
# ocm-core: ManifestValidationError.errors (from validate_module_dict) --
# "path/to/field: message", path already a schema JSON-Pointer-ish string.
# ---------------------------------------------------------------------------


def _schema_path_to_json_path(schema_path: str) -> str:
    if schema_path in ("", "<root>"):
        return "$"
    out: list[str] = []
    for part in schema_path.split("/"):
        if part.isdigit():
            out.append(f"[{part}]")
        else:
            out.append(f".{part}" if out else part)
    return "".join(out)


def schema_violation_to_refusal(violation: str) -> Refusal:
    schema_path, _, message = violation.partition(": ")
    return Refusal(
        code=Codes.SCHEMA_INVALID,
        path=_schema_path_to_json_path(schema_path),
        message=message or violation,
        hint="Fix the field named in `path` and resubmit -- validation gates publishing, not saving.",
    )


# ---------------------------------------------------------------------------
# ocm-resolve: CellResolutionError.errors
# ---------------------------------------------------------------------------

_RE_NOT_FOUND = re.compile(r"^(?P<ref>\S+): module not found \(looked in: (?P<tried>.*)\)$")
_RE_INVALID_MANIFEST = re.compile(r"^(?P<ref>\S+): found (?P<candidate>.+) but it failed manifest validation: (?P<detail>.*)$", re.S)
_RE_REVISION_MISMATCH = re.compile(r"^(?P<ref>\S+): found (?P<candidate>.+) but it declares (?P<got>\S+), not \S+$")
_RE_MALFORMED_MOUNT = re.compile(r"^module (?P<name>\S+): malformed mount\.on ")
_RE_UNKNOWN_MOUNT_TARGET = re.compile(r"^module (?P<name>\S+): mounts on unknown module instance ")
_RE_MOUNT_CYCLE = re.compile(r"^module (?P<name>\S+): mount\.on chain cycles back")
_RE_UNKNOWN_INSTANCE_IN_PLAN = re.compile(r"^(?P<loc>[\w.\[\]]+): references unknown module instance '(?P<name>[^']+)'$")
_RE_UNKNOWN_OP = re.compile(
    r"^(?P<loc>[\w.\[\]]+): (?P<inst>\S+) \((?P<mod>\S+)\) has no op '(?P<op>[^']+)' \(known ops: (?P<known>\[.*\])\)$"
)
_RE_UNKNOWN_PARAM = re.compile(
    r"^(?P<loc>[\w.\[\]]+): op '(?P<op>[^']+)' has no parameter '(?P<param>[^']+)' \(known parameters: (?P<known>\[.*\])\)$"
)
_RE_PARAM_NOT_NUMERIC = re.compile(r"^(?P<loc>[\w.\[\]]+): op '(?P<op>[^']+)' param '(?P<param>[^']+)' = (?P<val>.+) is not numeric$")
_RE_PARAM_BELOW_MIN = re.compile(
    r"^(?P<loc>[\w.\[\]]+): op '(?P<op>[^']+)' param '(?P<param>[^']+)' = (?P<val>[-\d.eE]+) is below the declared minimum (?P<min>[-\d.eE]+)$"
)
_RE_PARAM_ABOVE_MAX = re.compile(
    r"^(?P<loc>[\w.\[\]]+): op '(?P<op>[^']+)' param '(?P<param>[^']+)' = (?P<val>[-\d.eE]+) exceeds the declared maximum (?P<max>[-\d.eE]+)$"
)
_RE_PARAM_NOT_ENUM = re.compile(
    r"^(?P<loc>[\w.\[\]]+): op '(?P<op>[^']+)' param '(?P<param>[^']+)' = (?P<val>.+) is not one of (?P<known>\[.*\])$"
)


def _parse_pylist(text: str) -> list[str]:
    # `known ops: ['a', 'b']`-style Python repr of a list of strings --
    # not JSON (single quotes). Safe to eval-free parse: strip brackets,
    # split on ", ", strip quotes.
    inner = text.strip("[]")
    if not inner:
        return []
    return [item.strip().strip("'\"") for item in inner.split(", ")]


def resolve_error_to_refusal(error: str) -> Refusal:
    if m := _RE_PARAM_BELOW_MIN.match(error):
        return Refusal(
            code=Codes.PARAM_OUT_OF_BOUNDS,
            path=f"{m['loc']}.params.{m['param']}",
            message=error,
            allowed={"min": float(m["min"])},
            hint=f"Raise {m['param']} to at least {m['min']}.",
        )
    if m := _RE_PARAM_ABOVE_MAX.match(error):
        return Refusal(
            code=Codes.PARAM_OUT_OF_BOUNDS,
            path=f"{m['loc']}.params.{m['param']}",
            message=error,
            allowed={"max": float(m["max"])},
            hint=f"Lower {m['param']} to at most {m['max']}, or select a module whose capability covers {m['val']}.",
        )
    if m := _RE_PARAM_NOT_ENUM.match(error):
        return Refusal(
            code=Codes.PARAM_OUT_OF_BOUNDS,
            path=f"{m['loc']}.params.{m['param']}",
            message=error,
            allowed={"values": _parse_pylist(m["known"])},
            hint=f"Use one of the declared values for {m['param']}.",
        )
    if m := _RE_PARAM_NOT_NUMERIC.match(error):
        return Refusal(code=Codes.PARAM_OUT_OF_BOUNDS, path=f"{m['loc']}.params.{m['param']}", message=error)
    if m := _RE_UNKNOWN_PARAM.match(error):
        return Refusal(
            code=Codes.UNKNOWN_PARAM,
            path=f"{m['loc']}.params.{m['param']}",
            message=error,
            allowed={"values": _parse_pylist(m["known"])},
            hint="Use one of the capability's declared parameter names.",
        )
    if m := _RE_UNKNOWN_OP.match(error):
        return Refusal(
            code=Codes.UNKNOWN_OP,
            path=f"{m['loc']}.op",
            message=error,
            allowed={"values": _parse_pylist(m["known"])},
            hint=f"Use one of {m['inst']}'s declared capabilities.",
        )
    if m := _RE_UNKNOWN_INSTANCE_IN_PLAN.match(error):
        return Refusal(code=Codes.UNKNOWN_MODULE, path=f"{m['loc']}.module", message=error, hint="Place this instance first, or fix the typo.")
    if m := _RE_MOUNT_CYCLE.match(error) or _RE_UNKNOWN_MOUNT_TARGET.match(error) or _RE_MALFORMED_MOUNT.match(error):
        return Refusal(code=Codes.DANGLING_MOUNT, path=f"modules.{m['name']}.mount.on", message=error)
    if m := _RE_REVISION_MISMATCH.match(error):
        return Refusal(code=Codes.REVISION_MISMATCH, path="module", message=error, allowed={"declared": m["got"]})
    if m := _RE_INVALID_MANIFEST.match(error):
        return Refusal(code=Codes.SCHEMA_INVALID, path="module", message=error)
    if m := _RE_NOT_FOUND.match(error):
        return Refusal(code=Codes.UNKNOWN_MODULE, path="module", message=error, hint="Check the id@revision, or publish_module it first.")
    return Refusal(code=Codes.CELL_INVALID, path="$", message=error)


# ---------------------------------------------------------------------------
# ocm-generator: SceneBuildError.errors (containment: workspace overhang)
# ---------------------------------------------------------------------------

_RE_OVERHANG = re.compile(
    r"^module (?P<name>\S+): extends beyond the workspace footprint \((?P<footprint>[^)]+)\): (?P<overhangs>.+)$"
)


def scene_error_to_refusal(error: str) -> Refusal:
    if m := _RE_OVERHANG.match(error):
        directions = [d.strip() for d in m["overhangs"].split(",")]
        return Refusal(
            code=Codes.WORKSPACE_OVERHANG,
            path=f"modules.{m['name']}.mount",
            message=error,
            allowed={"footprint": m["footprint"], "overhangs": directions},
            hint=f"Move {m['name']} inside the base footprint ({m['footprint']}).",
        )
    return Refusal(code=Codes.CELL_INVALID, path="$", message=error)


# ---------------------------------------------------------------------------
# ocm-generator.planner: PoseUnreachableError / PathCollisionError /
# NoDriveScrewStepError / PlanningUnavailable -- already-structured
# exceptions (attributes, not strings to parse), so these translate
# directly rather than through a regex.
# ---------------------------------------------------------------------------


def pose_unreachable_to_refusal(pose_name: str, message: str) -> Refusal:
    return Refusal(
        code=Codes.POSE_UNREACHABLE,
        path=f"plan.poses.{pose_name}",
        message=message,
        hint="Move the target feature/fixture closer to the robot, or re-check the mount pose.",
    )


def path_collision_to_refusal(segment: str, instance_a: str, instance_b: str, link_a: str, link_b: str, fraction: float, message: str) -> Refusal:
    return Refusal(
        code=Codes.PATH_COLLISION,
        path=f"plan.segments['{segment}']",
        message=message,
        allowed={"instance_a": instance_a, "instance_b": instance_b, "link_a": link_a, "link_b": link_b, "t": fraction},
        hint="This is a straight joint-space line, not a planned path -- reposition the colliding module or the target.",
    )


def contacts_to_refusals(contacts: list[dict[str, Any]]) -> list[Refusal]:
    return [
        Refusal(
            code=Codes.COLLISION_DETECTED,
            path=f"scene.instances['{c['instance_a']}']",
            message=f"{c['instance_a']} <-> {c['instance_b']} penetrate by {-c['distance_mm']:.2f} mm ({c['link_a']} / {c['link_b']})",
            allowed={"instance_b": c["instance_b"], "distance_mm": c["distance_mm"]},
        )
        for c in contacts
        if c["is_violation"]
    ]
