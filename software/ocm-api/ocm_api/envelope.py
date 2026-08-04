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
    spec/09-ocm-api.md (`OCM_PARAM_OUT_OF_BOUNDS`, `OCM_HUMAN_SIGNATURE_REQUIRED`);
    the rest name scenarios the spec describes narratively (unknown
    module, dangling mount.on, workspace overhang, ...) without pinning a
    literal code string -- these are this library's own, chosen once here
    so every verb that can hit the same scenario uses the same code.
    """

    OCM_SCHEMA_INVALID = "OCM_SCHEMA_INVALID"
    OCM_CELL_INVALID = "OCM_CELL_INVALID"
    OCM_NOT_FOUND = "OCM_NOT_FOUND"
    OCM_ALREADY_EXISTS = "OCM_ALREADY_EXISTS"
    OCM_HUMAN_SIGNATURE_REQUIRED = "OCM_HUMAN_SIGNATURE_REQUIRED"
    OCM_DRAFT_NOT_PUBLISHABLE = "OCM_DRAFT_NOT_PUBLISHABLE"
    OCM_UNKNOWN_MODULE = "OCM_UNKNOWN_MODULE"
    OCM_REVISION_MISMATCH = "OCM_REVISION_MISMATCH"
    OCM_DANGLING_MOUNT = "OCM_DANGLING_MOUNT"
    OCM_DRAFT_MODULE_REFERENCED = "OCM_DRAFT_MODULE_REFERENCED"
    OCM_WORKSPACE_OVERHANG = "OCM_WORKSPACE_OVERHANG"
    OCM_UNKNOWN_OP = "OCM_UNKNOWN_OP"
    OCM_UNKNOWN_PARAM = "OCM_UNKNOWN_PARAM"
    OCM_PARAM_OUT_OF_BOUNDS = "OCM_PARAM_OUT_OF_BOUNDS"
    OCM_NO_FASTENING_STEP = "OCM_NO_FASTENING_STEP"
    OCM_POSE_UNREACHABLE = "OCM_POSE_UNREACHABLE"
    OCM_PATH_COLLISION = "OCM_PATH_COLLISION"
    OCM_COLLISION_DETECTED = "OCM_COLLISION_DETECTED"
    OCM_UNAVAILABLE = "OCM_UNAVAILABLE"  # a needed optional extra (e.g. tesseract) isn't installed
    OCM_INVALID_ARGUMENT = "OCM_INVALID_ARGUMENT"
    OCM_UNKNOWN_COMPONENT = "OCM_UNKNOWN_COMPONENT"  # ADR-0014: a components: entry's ref doesn't resolve
    OCM_DUPLICATE_REFDES = "OCM_DUPLICATE_REFDES"  # ADR-0014: two components: entries share a refdes
    OCM_INVALID_SOURCE = "OCM_INVALID_SOURCE"  # ADR-0014: a signal's source: provenance doesn't check out
    OCM_TOOL_SLOT_OCCUPIED = "OCM_TOOL_SLOT_OCCUPIED"  # place_instance onto a mount.on flange that's already carrying an instance
    OCM_AGENT_UNAVAILABLE = "OCM_AGENT_UNAVAILABLE"  # /agent/chat with no ANTHROPIC_API_KEY configured
    # ADR-0015: a module's nets/links/ports connectivity, one stable code per
    # refusal in the ADR's "implementable against the current schema" table.
    OCM_NET_TOO_FEW_ENDPOINTS = "OCM_NET_TOO_FEW_ENDPOINTS"  # a net with fewer than 2 endpoints
    OCM_PIN_ON_MULTIPLE_NETS = "OCM_PIN_ON_MULTIPLE_NETS"  # one pin claimed by more than one net
    OCM_UNRESOLVED_ENDPOINT = "OCM_UNRESOLVED_ENDPOINT"  # endpoint names an unknown refdes/ref/pin/port
    OCM_COMPONENT_HAS_NO_CONNECTORS = "OCM_COMPONENT_HAS_NO_CONNECTORS"  # wired instance whose component declares none
    OCM_PORT_UNCONNECTED = "OCM_PORT_UNCONNECTED"  # module port declared but on no net or link
    OCM_LINK_NON_COMMUNICATION_PORT = "OCM_LINK_NON_COMMUNICATION_PORT"  # link endpoint on an electrical/pneumatic port
    OCM_LINK_PROTOCOL_MISMATCH = "OCM_LINK_PROTOCOL_MISMATCH"  # a link's two ends speak different protocols
    OCM_ETHERCAT_CHAIN_BROKEN = "OCM_ETHERCAT_CHAIN_BROKEN"  # chain reaches no master, loops, or leaves slaves unreached
    # ADR-0027: collision geometry is derived from posed components, or
    # authored and checked against them.
    OCM_COLLISION_SOURCE_MISSING = "OCM_COLLISION_SOURCE_MISSING"  # publish requires collision_source (D6)
    OCM_AUTHORED_COLLISION_MISSING = "OCM_AUTHORED_COLLISION_MISSING"  # authored with no collision path, or not a file
    OCM_COMPONENT_OUTSIDE_COLLISION = "OCM_COMPONENT_OUTSIDE_COLLISION"  # envelope protrudes outside authored mesh (D2)
    OCM_DERIVED_POSE_MISSING = "OCM_DERIVED_POSE_MISSING"  # derived + a component instance with no pose (D5)
    OCM_DERIVED_ENVELOPE_MISSING = "OCM_DERIVED_ENVELOPE_MISSING"  # derived + referenced component lacks geometry.envelope (D5)
    OCM_UNIT_UNRECOGNISED = "OCM_UNIT_UNRECOGNISED"  # a unit string outside ocm_core.units' explicit table
    OCM_LINK_UNKNOWN = "OCM_LINK_UNKNOWN"  # component/structure names a link absent from the fragment (D4)
    OCM_ENVELOPE_OVERLAP = "OCM_ENVELOPE_OVERLAP"  # advise, not refuse (D5): overlapping envelopes surfaced
    # ADR-0028: a capability declares the joints it actuates.
    OCM_ACTUATION_JOINT_UNKNOWN = "OCM_ACTUATION_JOINT_UNKNOWN"  # actuates a joint absent from the fragment
    OCM_ACTUATION_JOINT_FIXED = "OCM_ACTUATION_JOINT_FIXED"  # actuates a fixed joint -- no configurable position
    OCM_ACTUATION_UNIT_MISMATCH = "OCM_ACTUATION_UNIT_MISMATCH"  # length unit on a revolute joint, or angular on prismatic (D2)
    OCM_ACTUATION_OUT_OF_LIMIT = "OCM_ACTUATION_OUT_OF_LIMIT"  # target outside the joint's own <limit> (D3)
    OCM_ACTUATION_CONFLICT = "OCM_ACTUATION_CONFLICT"  # one capability actuates the same joint twice
    OCM_JOINT_STATE_OUT_OF_LIMIT = "OCM_JOINT_STATE_OUT_OF_LIMIT"  # cell joint_state beyond the joint's <limit> (D3 retrofit)
    OCM_JOINT_UNACTUATED = "OCM_JOINT_UNACTUATED"  # advise: a movable joint no capability actuates (D4)
    OCM_FRAGMENT_MALFORMED = "OCM_FRAGMENT_MALFORMED"  # urdf_fragment exists but is not well-formed XML (Erratum 1; underlying principle ADR-0007)
    # ADR-0029 (the plan is the timeline) -- the in-order walk's refusals.
    OCM_PLAN_STEP_UNPLANNABLE = "OCM_PLAN_STEP_UNPLANNABLE"  # no at:, no actuates, no nominal_duration_s -- nothing to place on a timeline
    OCM_ACTUATION_DURATION_MISSING = "OCM_ACTUATION_DURATION_MISSING"  # actuates with no nominal_duration_s -- a stated endpoint with no stated time
    # ADR-0031 part 1 (D1 + D3) -- the carrier type and the located datum.
    OCM_CARRIER_TYPE_HAS_CONTROL = "OCM_CARRIER_TYPE_HAS_CONTROL"  # a carrier has no controller, no states, and no capabilities
    OCM_LOCATED_FRAME_UNKNOWN = "OCM_LOCATED_FRAME_UNKNOWN"  # located.frame names no mechanical.frames entry
    OCM_LOCATED_DOF_UNGOVERNED = "OCM_LOCATED_DOF_UNGOVERNED"  # a DOF no constraint feature governs -- the scheme does not close
    OCM_LOCATED_DOF_OVERCONSTRAINED = "OCM_LOCATED_DOF_OVERCONSTRAINED"  # a DOF governed twice -- the same failure, from the other side
    OCM_LOCATED_TOLERANCE_MISSING = "OCM_LOCATED_TOLERANCE_MISSING"  # a governed DOF with no tolerance -- a claim of infinite precision
    OCM_LOCATED_UNIT_MISMATCH = "OCM_LOCATED_UNIT_MISMATCH"  # length unit on a rotational DOF or vice versa (ADR-0028 D2's rule, second site)
    # ADR-0031 part 2 (D4) -- the part datum is declared, never scraped from a clamp verb.
    OCM_PART_DATUM_UNDECLARED = "OCM_PART_DATUM_UNDECLARED"  # plan operates on part; no carrier or fixture declares frames.part_datum
    # ADR-0023: the plan is verbs; conditions belong to modules.
    OCM_CONDITION_UNKNOWN_SIGNAL = "OCM_CONDITION_UNKNOWN_SIGNAL"  # a pre/postcondition names no known signal or requires key
    OCM_REQUIREMENT_UNBOUND = "OCM_REQUIREMENT_UNBOUND"  # a capability's requires key is unbound by the cell
    OCM_REQUIREMENT_UNKNOWN_TARGET = "OCM_REQUIREMENT_UNKNOWN_TARGET"  # a binding names an unknown instance/signal
    OCM_TIMEOUT_DISPOSITION_CONFLICT = "OCM_TIMEOUT_DISPOSITION_CONFLICT"  # on_timeout: hold on a not-abort-safe capability


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
