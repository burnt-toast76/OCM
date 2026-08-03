# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0028: a capability declares the joints it actuates -- the
fragment-dependent half of the checks, complementing ocm-resolve's
manifest-only half (duplicate joint, unit outside every table).

Modelled on scene/collision_geometry.py's check_module_collision_geometry:
same signature shape, same return convention (refusal tuples + advisory
strings), pure Python. Needs the module's own urdf_fragment, which is why it
lives here and is reached through validate_module (ADR-0016's one surface) --
this is module-scoped, BEFORE any cell places it, so joint names are the
fragment's own, unnamespaced.

Per actuates entry:
- OCM_ACTUATION_JOINT_UNKNOWN: the joint is not in the fragment.
- OCM_ACTUATION_JOINT_FIXED: the joint is fixed (or has no type, which URDF
  defaults to fixed) -- no configurable position to drive.
- OCM_ACTUATION_UNIT_MISMATCH: a length unit on a revolute/continuous joint,
  or an angular unit on a prismatic one (ADR-0028 D2 -- the unit is
  type-checked against the joint, never inferred from it).
- OCM_ACTUATION_OUT_OF_LIMIT: the target, converted to URDF-native units
  (metres for prismatic, radians for revolute), is outside the joint's own
  <limit lower= upper=> (D3). `continuous` has no limits and is exempt; a
  revolute joint with NO <limit> is malformed URDF and refuses here too --
  saying the limit is missing -- rather than silently passing.

Across the whole module:
- OCM_JOINT_UNACTUATED (ADVISORY, never a refusal -- D4): a movable joint no
  capability actuates. Almost certainly incomplete authoring, but the engine
  cannot tell a genuinely passive joint from an unfinished one, so it says so
  on the completion list instead of deciding.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ocm_core import Module
from ocm_core.units import (
    UnknownUnitError,
    angle_to_rad,
    known_angle_units,
    known_length_units,
    length_to_mm,
)

from .errors import FragmentError
from .urdf import load_fragment

_MOVABLE_JOINT_TYPES = ("revolute", "continuous", "prismatic")


def _joints_by_name(root: ET.Element) -> dict[str, ET.Element]:
    return {j.get("name"): j for j in root.iter("joint") if j.get("name")}


def _limits_of(joint: ET.Element) -> tuple[float, float] | None:
    limit = joint.find("limit")
    if limit is None or limit.get("lower") is None or limit.get("upper") is None:
        return None
    return float(limit.get("lower")), float(limit.get("upper"))


def check_module_actuation(
    module: Module,
    module_dir: Path,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """The fragment-dependent ADR-0028 checks for one module.

    Returns (refusals, advisories):
    - refusals: (code, path, message) tuples the caller turns into Refusals.
    - advisories: OCM_JOINT_UNACTUATED strings, surfaced as warnings --
      advise, never gate (ADR-0028 D4 / ADR-0025 D3).
    """
    refusals: list[tuple[str, str, str]] = []
    advisories: list[str] = []

    fragment_field = module.mechanical.geometry.urdf_fragment
    if not fragment_field:
        # No fragment: nothing to check joints against. A capability that
        # actuates with no fragment at all will refuse the moment the
        # fragment claim lands; the fragment's own absence is validate's
        # existing artifact concern, not this pass's.
        return refusals, advisories
    try:
        root = load_fragment(module_dir / fragment_field)
    except FragmentError:
        return refusals, advisories  # the fragment's own load path reports this

    joints = _joints_by_name(root)
    known = sorted(joints)
    actuated: set[str] = set()

    for cap in module.capabilities:
        for act in cap.actuates:
            actuated.add(act.joint)
            path = f"capabilities['{cap.name}'].actuates['{act.joint}']"

            joint = joints.get(act.joint)
            if joint is None:
                refusals.append((
                    "OCM_ACTUATION_JOINT_UNKNOWN",
                    path,
                    f"{module.id}: capability {cap.name!r} actuates joint {act.joint!r}, "
                    f"absent from this module's urdf_fragment (has: {known})",
                ))
                continue

            joint_type = joint.get("type", "fixed")
            if joint_type not in _MOVABLE_JOINT_TYPES:
                refusals.append((
                    "OCM_ACTUATION_JOINT_FIXED",
                    path,
                    f"{module.id}: capability {cap.name!r} actuates {act.joint!r}, a fixed "
                    "joint -- no configurable position",
                ))
                continue

            # D2: the unit must match the joint's kind -- prismatic takes a
            # length, revolute/continuous an angle. A unit in NEITHER table
            # was already refused at resolve (manifest-only pass).
            is_length = act.units in known_length_units()
            is_angle = act.units in known_angle_units()
            if joint_type == "prismatic" and is_angle:
                refusals.append((
                    "OCM_ACTUATION_UNIT_MISMATCH",
                    path,
                    f"{module.id}: capability {cap.name!r} gives {act.joint!r} an angular "
                    f"unit {act.units!r}; a prismatic joint takes a length "
                    f"({list(known_length_units())})",
                ))
                continue
            if joint_type in ("revolute", "continuous") and is_length:
                refusals.append((
                    "OCM_ACTUATION_UNIT_MISMATCH",
                    path,
                    f"{module.id}: capability {cap.name!r} gives {act.joint!r} a length "
                    f"unit {act.units!r}; a {joint_type} joint takes an angle "
                    f"({list(known_angle_units())})",
                ))
                continue
            if not (is_length or is_angle):
                continue  # refused at resolve (OCM_UNIT_UNRECOGNISED); nothing sane to convert

            # D3: limit check, in URDF-native units (metres / radians).
            if joint_type == "continuous":
                continue  # no limits to check, by definition
            try:
                if joint_type == "prismatic":
                    value_native = length_to_mm(act.to, act.units) / 1000.0
                else:
                    value_native = angle_to_rad(act.to, act.units)
            except UnknownUnitError:
                continue  # unreachable given the table checks above; belt only

            limits = _limits_of(joint)
            if limits is None:
                refusals.append((
                    "OCM_ACTUATION_OUT_OF_LIMIT",
                    path,
                    f"{module.id}: capability {cap.name!r} drives {act.joint!r} but the "
                    f"{joint_type} joint declares no <limit> -- malformed URDF; a target "
                    "cannot be checked against a limit that is missing",
                ))
                continue
            lower, upper = limits
            if not (lower <= value_native <= upper):
                refusals.append((
                    "OCM_ACTUATION_OUT_OF_LIMIT",
                    path,
                    f"{module.id}: capability {cap.name!r} drives {act.joint!r} to "
                    f"{act.to} {act.units}, outside its declared limit [{lower}, {upper}] "
                    "(URDF-native units)",
                ))

    # D4: a movable joint no capability actuates -- advisory, on the human's
    # completion list, never blocking a resolve.
    for name in known:
        if joints[name].get("type", "fixed") in _MOVABLE_JOINT_TYPES and name not in actuated:
            advisories.append(
                f"OCM_JOINT_UNACTUATED: {module.id}: movable joint {name!r} is actuated by "
                "no capability -- a genuinely passive joint is legitimate, an unfinished "
                "manifest looks identical; the engine cannot tell, so it says so (ADR-0028 D4)"
            )

    return refusals, advisories
