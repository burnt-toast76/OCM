# SPDX-License-Identifier: AGPL-3.0-or-later
"""PackML command/state codes, and a small evaluator for a capability's
declared `preconditions`/`postconditions` (ocm_core.Capability -- plain
`"signal == literal"` strings) against live SignalBus values.

## Where a condition's signal actually lives (ADR-0023)

A condition's left-hand name is either one of the capability's own comms
signals (read on the instance that declares the capability) or one of its
`requires` keys -- a requirement the *cell* binds to some peer instance's
signal (`sd1.requires.workpiece_secured: nest1.clamped`). Resolving which
is which is not this evaluator's job: the caller passes a `bindings` map
(requires key -> `(instance, signal)`), already resolved from the cell.
`_condition_targets` turns a capability's condition list into concrete
`(instance, signal)` reads using that map; anything not in it is a local
signal on the declaring instance. `_check_condition`'s grammar stays
exactly `signal == literal`, keyed by the LOCAL name -- it never sees, and
never needs to see, which instance a value came from.

## The numeric encoding below is THIS PROJECT's, not a vendor's

spec/05-state-machine.md mandates the PackML (ISA-TR88.00.02) *model* --
which states exist and what they mean -- but doesn't pin down a wire
encoding, and no module manifest in this repo declares one either (a
module's `signals:` block just says `packml_cmd`/`packml_state` are
`uint16`). Real integration (a real PLC runtime, ADR's own
`emitters/plcopen.py`, still future work) will need a REAL, agreed
encoding -- likely the runtime's own. Until then, `SimulatedPackMLModule`
(the only thing that reads or writes these values before that layer
exists) and this file agree on values with each other, which is all a
loopback proof needs. Treat these as a placeholder, not a spec.
"""

from __future__ import annotations

import enum
from typing import Any

from ocm_core import Capability

from .errors import PreconditionError
from .signals import SignalBus


class PackMLCommand(enum.IntEnum):
    IDLE = 0
    START = 1
    STOP = 2
    ABORT = 3
    CLEAR = 4
    RESET = 5
    HOLD = 6


class PackMLState(enum.IntEnum):
    IDLE = 0
    STARTING = 1
    EXECUTE = 2
    COMPLETING = 3
    COMPLETE = 4
    ABORTING = 5
    ABORTED = 6
    STOPPING = 7
    STOPPED = 8
    RESETTING = 9
    CLEARING = 10
    HELD = 11


def _parse_literal(text: str) -> Any:
    text = text.strip()
    if text == "true":
        return True
    if text == "false":
        return False
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _check_condition(expr: str, values: dict[str, Any]) -> bool:
    """v0's expression grammar: `signal == literal`. That's every
    precondition/postcondition string in this repo's own committed
    modules (see sd50/pneumatic-nest's manifests) -- not a claim that
    it's all the grammar will ever need. Keyed by LOCAL name: binding
    resolution (which instance each name reads from) happens before this,
    in `_condition_targets`, so this stays a pure local-name lookup.
    """
    if "==" not in expr:
        raise PreconditionError(f"unsupported condition (expected 'signal == value'): {expr!r}")
    name, _, literal = expr.partition("==")
    name = name.strip()
    if name not in values:
        raise PreconditionError(f"condition {expr!r} references unknown signal {name!r}")
    return values[name] == _parse_literal(literal)


def _condition_names(conditions: tuple[str, ...]) -> set[str]:
    return {expr.partition("==")[0].strip() for expr in conditions}


def _condition_targets(
    instance: str,
    conditions: tuple[str, ...],
    bindings: dict[str, tuple[str, str]],
) -> dict[str, tuple[str, str]]:
    """Local condition name -> the concrete `(instance, signal)` it reads.

    A name the cell bound (a `requires` key) reads its peer's signal; any
    other name is a local signal on the capability's own instance. The
    result is keyed by the LOCAL name so `_check_condition` -- which only
    knows local names -- can look values up unchanged.
    """
    return {name: bindings.get(name, (instance, name)) for name in _condition_names(conditions)}


async def read_signals(bus: SignalBus, targets: dict[str, tuple[str, str]]) -> dict[str, Any]:
    """Read every `(instance, signal)` in `targets`, returning a map keyed
    by the LOCAL name each was requested under. Instance-qualified: a
    single call can span more than one instance (a capability that gates
    on a peer's signal via a `requires` binding).
    """
    return {name: await bus.read(inst, sig) for name, (inst, sig) in targets.items()}


async def _conditions_met(
    bus: SignalBus,
    instance: str,
    conditions: tuple[str, ...],
    bindings: dict[str, tuple[str, str]],
) -> bool:
    if not conditions:
        return True
    values = await read_signals(bus, _condition_targets(instance, conditions, bindings))
    return all(_check_condition(expr, values) for expr in conditions)


async def preconditions_met(
    bus: SignalBus,
    instance: str,
    capability: Capability,
    bindings: dict[str, tuple[str, str]],
) -> bool:
    """True if every one of `capability.preconditions` currently holds --
    each read from wherever `bindings` says it lives (a local signal on
    `instance`, or a peer's signal via a `requires` binding). Evaluated
    fresh on every call -- the caller (the coordinator) decides whether to
    poll.
    """
    return await _conditions_met(bus, instance, capability.preconditions, bindings)


async def postconditions_met(
    bus: SignalBus,
    instance: str,
    capability: Capability,
    bindings: dict[str, tuple[str, str]],
) -> bool:
    """Mirror of `preconditions_met` for `capability.postconditions`
    (ADR-0023 Decision 2): a capability reporting PackML Complete is not
    believed until these read true against the live bus.
    """
    return await _conditions_met(bus, instance, capability.postconditions, bindings)


async def failing_postconditions(
    bus: SignalBus,
    instance: str,
    capability: Capability,
    bindings: dict[str, tuple[str, str]],
) -> list[str]:
    """The subset of `capability.postconditions` that read false right now
    -- so the coordinator can fault a step naming the exact condition that
    Complete lied about, not just "a postcondition".
    """
    if not capability.postconditions:
        return []
    values = await read_signals(bus, _condition_targets(instance, capability.postconditions, bindings))
    return [expr for expr in capability.postconditions if not _check_condition(expr, values)]
