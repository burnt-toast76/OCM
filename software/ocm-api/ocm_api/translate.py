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

A pattern that doesn't match anything falls through to `OCM_CELL_INVALID` /
`OCM_SCHEMA_INVALID` with the raw text preserved in `message` -- no information
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


_RE_MISSING_FRAME = re.compile(r"^'frame' is a required property$")
_RE_PATTERN_MISMATCH = re.compile(r"^'(?P<value>[^']*)' does not match '(?P<pattern>[^']*)'$")
_SNAKE_CASE_PATTERN = "^[a-z][a-z0-9_]*$"


def _snake_case_suggestion(value: str) -> str:
    out = re.sub(r"[^a-z0-9_]", "_", value.lower())
    out = re.sub(r"_+", "_", out).strip("_")
    if not out or not out[0].isalpha():
        out = f"x_{out}" if out else "x"
    return out


def _hint_for_schema_violation(message: str) -> str:
    """Code-specific hints -- generic "fix the field" advice doesn't teach
    anything the agent couldn't already see in `path`/`message`. Where the
    violation matches a known shape, spend the hint on what to do next.
    """
    if _RE_MISSING_FRAME.match(message):
        return (
            "pose6d needs `frame`: the named coordinate frame this pose is expressed in. "
            "Call list_frames(cell_id=...) to see every frame a placed instance can reference "
            "(e.g. 'tcp', 'robot1.flange', 'nest1.part_datum')."
        )
    if m := _RE_PATTERN_MISMATCH.match(message):
        if m["pattern"] == _SNAKE_CASE_PATTERN:
            return f"Use snake_case (lowercase letters, digits, underscores, starting with a letter), e.g. {_snake_case_suggestion(m['value'])!r}."
        return f"{m['value']!r} must match the pattern {m['pattern']!r}."
    return "Fix the field named in `path` and resubmit -- validation gates publishing, not saving."


def schema_violation_to_refusal(violation: str) -> Refusal:
    schema_path, _, message = violation.partition(": ")
    message = message or violation
    return Refusal(
        code=Codes.OCM_SCHEMA_INVALID,
        path=_schema_path_to_json_path(schema_path),
        message=message,
        hint=_hint_for_schema_violation(message),
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

# ADR-0014: a module's own components: list / signal source: provenance,
# checked by ocm_resolve.resolve_cell the same way it checks module refs
# and mount chains -- see resolve.py's own _check_module_components.
_RE_DUPLICATE_REFDES = re.compile(r"^module (?P<loc>\S+) \((?P<module_id>\S+)\): duplicate component refdes '(?P<refdes>[^']+)'$")
_RE_NO_COMPONENTS_SEARCH_PATH = re.compile(
    r"^module (?P<loc>\S+) \((?P<module_id>\S+)\): declares component (?P<refdes>\S+) \((?P<ref>\S+)\) but no components search path was given$"
)
_RE_COMPONENT_REF_PROBLEM = re.compile(r"^module (?P<loc>\S+) \((?P<module_id>\S+)\): component (?P<refdes>\S+): (?P<detail>.*)$", re.S)
_RE_MALFORMED_SOURCE = re.compile(
    r"^module (?P<loc>\S+) \((?P<module_id>\S+)\): signal '(?P<signal>[^']+)' has a malformed source '(?P<source>[^']*)' \(expected 'REFDES\.signal_name'\)$"
)
_RE_UNKNOWN_REFDES_SOURCE = re.compile(
    r"^module (?P<loc>\S+) \((?P<module_id>\S+)\): signal '(?P<signal>[^']+)' source='(?P<source>[^']+)' "
    r"references unknown refdes '(?P<refdes>[^']+)' \(declared components: (?P<known>\[.*\])\)$"
)
_RE_UNKNOWN_SIGNAL_SOURCE = re.compile(
    r"^module (?P<loc>\S+) \((?P<module_id>\S+)\): signal '(?P<signal>[^']+)' source='(?P<source>[^']+)' "
    r"references unknown signal '(?P<devsig>[^']+)' on component (?P<component_id>\S+) \(known signals: (?P<known>\[.*\])\)$"
)

# ADR-0015: a module's nets/links/ports connectivity, checked by
# ocm_resolve.check_module_connectivity the same way ADR-0014's components:
# list is -- one stable code per refusal in the "implementable" table. Every
# message shares the `module <loc> (<id>): ` stem the resolver stamps on all
# of its cross-file violations.
_CONN = r"^module (?P<loc>\S+) \((?P<module_id>[^)]+)\): "
_RE_NET_TOO_FEW = re.compile(_CONN + r"(?P<domain>\w+) net '(?P<net>[^']+)' has \d+ endpoint\(s\); a net needs at least 2$")
_RE_PIN_MULTI_NET = re.compile(_CONN + r"pin .+ appears on more than one net \(.+\)$")
# "declares no connectors -- its pinout is missing" (electrical/comms) or,
# per ADR-0015 Erratum 1 Correction D, "declares no pneumatic ports" on a
# pneumatic net -- both are the same OCM_COMPONENT_HAS_NO_CONNECTORS refusal.
_RE_NO_CONNECTORS = re.compile(
    _CONN + r".+ references refdes '(?P<refdes>[^']+)' \([^)]+\), which declares no (?:connectors|pneumatic ports)"
)
_RE_PORT_UNCONNECTED = re.compile(_CONN + r"port '(?P<port>[^']+)' is declared but connected to no net or link$")
_RE_LINK_NON_COMM_PORT = re.compile(
    _CONN + r"link '(?P<link>[^']+)' endpoint (?P<end>[ab]) references port '(?P<port>[^']+)' \(domain [^)]*\), which is not a communication port$"
)
_RE_LINK_PROTOCOL_MISMATCH = re.compile(_CONN + r"link '(?P<link>[^']+)' connects mismatched protocols \(.+\)$")
_RE_ETHERCAT_CHAIN = re.compile(_CONN + r"EtherCAT chain .+$")
# Broad endpoint-resolution catch-all -- must be tried AFTER the more
# specific connectivity patterns above (a "no connectors" message also
# contains "references refdes", so order matters).
_RE_UNRESOLVED_ENDPOINT = re.compile(
    _CONN + r".+ references (?:unknown refdes|unknown port|unknown connector|unknown pneumatic port|"
    r"pin '[^']*' not on connector|pin '[^']*' on comms connector|"
    r"refdes '[^']*' \([^)]*\) without naming|neither a port)"
)

# ADR-0023: plan-are-verbs conditions/requirements/timeouts. Module-scoped
# (validate_module + set_plan) share the `module <loc> (<id>): ` stem; the
# cell-scoped requirement-binding refusals use a `cell <id>: ` stem.
_RE_CONDITION_UNKNOWN_SIGNAL = re.compile(
    _CONN + r"capability '(?P<cap>[^']+)' (?:pre|post)condition .+ references '(?P<name>[^']+)', "
    r"which is neither a comms signal nor a declared requires key"
)
_RE_TIMEOUT_DISPOSITION_CONFLICT = re.compile(
    _CONN + r"capability '(?P<cap>[^']+)' declares on_timeout 'hold' but state_machine\.abort_safe is false"
)
_CELL = r"^cell (?P<cell>\S+): "
_RE_REQUIREMENT_UNBOUND = re.compile(
    _CELL + r"instance (?P<inst>\S+) \((?P<module_id>[^)]+)\) capability '(?P<cap>[^']+)' requires "
    r"'(?P<req>[^']+)', which the cell binds to nothing \(instances declaring an input bool: (?P<candidates>\[.*\])\)"
)
_RE_REQUIREMENT_UNKNOWN_TARGET = re.compile(
    _CELL + r"instance (?P<inst>\S+) binds requirement '(?P<req>[^']+)' to "
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
            code=Codes.OCM_PARAM_OUT_OF_BOUNDS,
            path=f"{m['loc']}.params.{m['param']}",
            message=error,
            allowed={"min": float(m["min"])},
            hint=f"Raise {m['param']} to at least {m['min']}.",
        )
    if m := _RE_PARAM_ABOVE_MAX.match(error):
        return Refusal(
            code=Codes.OCM_PARAM_OUT_OF_BOUNDS,
            path=f"{m['loc']}.params.{m['param']}",
            message=error,
            allowed={"max": float(m["max"])},
            hint=f"Lower {m['param']} to at most {m['max']}, or select a module whose capability covers {m['val']}.",
        )
    if m := _RE_PARAM_NOT_ENUM.match(error):
        return Refusal(
            code=Codes.OCM_PARAM_OUT_OF_BOUNDS,
            path=f"{m['loc']}.params.{m['param']}",
            message=error,
            allowed={"values": _parse_pylist(m["known"])},
            hint=f"Use one of the declared values for {m['param']}.",
        )
    if m := _RE_PARAM_NOT_NUMERIC.match(error):
        return Refusal(code=Codes.OCM_PARAM_OUT_OF_BOUNDS, path=f"{m['loc']}.params.{m['param']}", message=error)
    if m := _RE_UNKNOWN_PARAM.match(error):
        return Refusal(
            code=Codes.OCM_UNKNOWN_PARAM,
            path=f"{m['loc']}.params.{m['param']}",
            message=error,
            allowed={"values": _parse_pylist(m["known"])},
            hint="Use one of the capability's declared parameter names.",
        )
    if m := _RE_UNKNOWN_OP.match(error):
        return Refusal(
            code=Codes.OCM_UNKNOWN_OP,
            path=f"{m['loc']}.op",
            message=error,
            allowed={"values": _parse_pylist(m["known"])},
            hint=f"Use one of {m['inst']}'s declared capabilities.",
        )
    if m := _RE_UNKNOWN_INSTANCE_IN_PLAN.match(error):
        return Refusal(code=Codes.OCM_UNKNOWN_MODULE, path=f"{m['loc']}.module", message=error, hint="Place this instance first, or fix the typo.")
    if m := _RE_MOUNT_CYCLE.match(error) or _RE_UNKNOWN_MOUNT_TARGET.match(error) or _RE_MALFORMED_MOUNT.match(error):
        return Refusal(code=Codes.OCM_DANGLING_MOUNT, path=f"modules.{m['name']}.mount.on", message=error)
    if m := _RE_REVISION_MISMATCH.match(error):
        return Refusal(code=Codes.OCM_REVISION_MISMATCH, path="module", message=error, allowed={"declared": m["got"]})
    if m := _RE_INVALID_MANIFEST.match(error):
        return Refusal(code=Codes.OCM_SCHEMA_INVALID, path="module", message=error)
    if m := _RE_NOT_FOUND.match(error):
        return Refusal(code=Codes.OCM_UNKNOWN_MODULE, path="module", message=error, hint="Check the id@revision, or publish_module it first.")

    # ADR-0014: components: list / signal source: provenance.
    if m := _RE_DUPLICATE_REFDES.match(error):
        return Refusal(
            code=Codes.OCM_DUPLICATE_REFDES,
            path=f"modules['{m['loc']}'].components",
            message=error,
            hint=f"Each entry in {m['module_id']}'s components: list needs its own refdes -- rename one of the two {m['refdes']!r}s.",
        )
    if m := _RE_NO_COMPONENTS_SEARCH_PATH.match(error):
        return Refusal(
            code=Codes.OCM_UNKNOWN_COMPONENT,
            path=f"modules['{m['loc']}'].components['{m['refdes']}']",
            message=error,
            hint="This workspace has no components/ directory to resolve component refs against.",
        )
    if m := _RE_COMPONENT_REF_PROBLEM.match(error):
        return Refusal(
            code=Codes.OCM_UNKNOWN_COMPONENT,
            path=f"modules['{m['loc']}'].components['{m['refdes']}']",
            message=error,
            hint=f"Check the component id@revision, or publish_component({m['refdes']!r}'s id, <semver>) first.",
        )
    if m := _RE_MALFORMED_SOURCE.match(error):
        return Refusal(
            code=Codes.OCM_INVALID_SOURCE,
            path=f"modules['{m['loc']}'].comms.signals['{m['signal']}'].source",
            message=error,
            hint="source must be 'REFDES.signal_name', e.g. 'VG1.vacuum_switch'.",
        )
    if m := _RE_UNKNOWN_REFDES_SOURCE.match(error):
        return Refusal(
            code=Codes.OCM_INVALID_SOURCE,
            path=f"modules['{m['loc']}'].comms.signals['{m['signal']}'].source",
            message=error,
            allowed={"refdes": _parse_pylist(m["known"])},
            hint=f"Use one of {m['module_id']}'s declared component refdes.",
        )
    if m := _RE_UNKNOWN_SIGNAL_SOURCE.match(error):
        return Refusal(
            code=Codes.OCM_INVALID_SOURCE,
            path=f"modules['{m['loc']}'].comms.signals['{m['signal']}'].source",
            message=error,
            allowed={"values": _parse_pylist(m["known"])},
            hint=f"Use one of {m['component_id']}'s own declared comms.signals names.",
        )

    # ADR-0015: nets/links/ports connectivity. Specific patterns first; the
    # broad "endpoint doesn't resolve" catch-all is tried last.
    if m := _RE_NET_TOO_FEW.match(error):
        return Refusal(
            code=Codes.OCM_NET_TOO_FEW_ENDPOINTS,
            path=f"modules['{m['loc']}'].nets.{m['domain']}['{m['net']}']",
            message=error,
            hint="A net models a shared node -- give it at least two endpoints, or delete it.",
        )
    if m := _RE_PIN_MULTI_NET.match(error):
        return Refusal(
            code=Codes.OCM_PIN_ON_MULTIPLE_NETS,
            path=f"modules['{m['loc']}'].nets",
            message=error,
            hint="A pin sits on exactly one node -- move it to a single net (two nets on one pin is a short).",
        )
    if m := _RE_NO_CONNECTORS.match(error):
        return Refusal(
            code=Codes.OCM_COMPONENT_HAS_NO_CONNECTORS,
            path=f"modules['{m['loc']}'].components['{m['refdes']}']",
            message=error,
            hint=f"Transcribe {m['refdes']}'s pinout onto its component definition -- the wiring UI can't create a pin (ADR-0015 Decision 4).",
        )
    if m := _RE_PORT_UNCONNECTED.match(error):
        return Refusal(
            code=Codes.OCM_PORT_UNCONNECTED,
            path=f"modules['{m['loc']}'].ports['{m['port']}']",
            message=error,
            hint=f"Wire {m['port']} into a net or link, or remove it from ports:.",
        )
    if m := _RE_LINK_NON_COMM_PORT.match(error):
        return Refusal(
            code=Codes.OCM_LINK_NON_COMMUNICATION_PORT,
            path=f"modules['{m['loc']}'].links['{m['link']}'].{m['end']}",
            message=error,
            hint=f"A link is communication only -- point endpoint {m['end']} at a communication port, or model this as a net.",
        )
    if m := _RE_LINK_PROTOCOL_MISMATCH.match(error):
        return Refusal(
            code=Codes.OCM_LINK_PROTOCOL_MISMATCH,
            path=f"modules['{m['loc']}'].links['{m['link']}']",
            message=error,
            hint="Both ends of a link must speak the same protocol.",
        )
    if m := _RE_ETHERCAT_CHAIN.match(error):
        return Refusal(
            code=Codes.OCM_ETHERCAT_CHAIN_BROKEN,
            path=f"modules['{m['loc']}'].links",
            message=error,
            hint="Walk the IN->OUT cabling: anchor the chain to a master (or slave_in port), remove the loop, or cable the dangling slave_out onward.",
        )
    if m := _RE_UNRESOLVED_ENDPOINT.match(error):
        return Refusal(
            code=Codes.OCM_UNRESOLVED_ENDPOINT,
            path=f"modules['{m['loc']}']",
            message=error,
            hint="An endpoint may only name an existing port, or a refdes/ref/pin the placed component itself declares (ADR-0015).",
        )

    # ADR-0023: conditions / requirements / timeout disposition.
    if m := _RE_CONDITION_UNKNOWN_SIGNAL.match(error):
        return Refusal(
            code=Codes.OCM_CONDITION_UNKNOWN_SIGNAL,
            path=f"modules['{m['loc']}'].capabilities['{m['cap']}']",
            message=error,
            hint=f"Declare {m['name']!r} in comms.signals, add it to {m['cap']}'s requires, or fix the name -- conditions resolve statically (ADR-0023).",
        )
    if m := _RE_TIMEOUT_DISPOSITION_CONFLICT.match(error):
        return Refusal(
            code=Codes.OCM_TIMEOUT_DISPOSITION_CONFLICT,
            path=f"modules['{m['loc']}'].capabilities['{m['cap']}'].on_timeout",
            message=error,
            hint="Use on_timeout: abort (a compromised part routes to reject), or make the module abort_safe only if a held op can truly resume.",
        )
    if m := _RE_REQUIREMENT_UNBOUND.match(error):
        return Refusal(
            code=Codes.OCM_REQUIREMENT_UNBOUND,
            path=f"modules['{m['inst']}'].requires['{m['req']}']",
            message=error,
            allowed={"instances": _parse_pylist(m["candidates"])},
            hint=f"Bind it on the instance: requires: {{{m['req']}: <instance>.<signal>}}. Instances declaring an input bool: {m['candidates']}.",
        )
    if m := _RE_REQUIREMENT_UNKNOWN_TARGET.match(error):
        return Refusal(
            code=Codes.OCM_REQUIREMENT_UNKNOWN_TARGET,
            path=f"modules['{m['inst']}'].requires['{m['req']}']",
            message=error,
            hint="Point the binding at an 'instance.signal' that exists in this cell.",
        )

    return Refusal(code=Codes.OCM_CELL_INVALID, path="$", message=error)


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
            code=Codes.OCM_WORKSPACE_OVERHANG,
            path=f"modules.{m['name']}.mount",
            message=error,
            allowed={"footprint": m["footprint"], "overhangs": directions},
            hint=f"Move {m['name']} inside the base footprint ({m['footprint']}).",
        )
    return Refusal(code=Codes.OCM_CELL_INVALID, path="$", message=error)


# ---------------------------------------------------------------------------
# ocm-generator.planner: PoseUnreachableError / PathCollisionError /
# NoDriveScrewStepError / PlanningUnavailable -- already-structured
# exceptions (attributes, not strings to parse), so these translate
# directly rather than through a regex.
# ---------------------------------------------------------------------------


def pose_unreachable_to_refusal(pose_name: str, message: str) -> Refusal:
    return Refusal(
        code=Codes.OCM_POSE_UNREACHABLE,
        path=f"plan.poses.{pose_name}",
        message=message,
        hint="Move the target feature/fixture closer to the robot, or re-check the mount pose.",
    )


def path_collision_to_refusal(segment: str, instance_a: str, instance_b: str, link_a: str, link_b: str, fraction: float, message: str) -> Refusal:
    return Refusal(
        code=Codes.OCM_PATH_COLLISION,
        path=f"plan.segments['{segment}']",
        message=message,
        allowed={"instance_a": instance_a, "instance_b": instance_b, "link_a": link_a, "link_b": link_b, "t": fraction},
        hint="This is a straight joint-space line, not a planned path -- reposition the colliding module or the target.",
    )


def contacts_to_refusals(contacts: list[dict[str, Any]]) -> list[Refusal]:
    return [
        Refusal(
            code=Codes.OCM_COLLISION_DETECTED,
            path=f"scene.instances['{c['instance_a']}']",
            message=f"{c['instance_a']} <-> {c['instance_b']} penetrate by {-c['distance_mm']:.2f} mm ({c['link_a']} / {c['link_b']})",
            allowed={"instance_b": c["instance_b"], "distance_mm": c["distance_mm"]},
        )
        for c in contacts
        if c["is_violation"]
    ]
