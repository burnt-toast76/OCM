# SPDX-License-Identifier: AGPL-3.0-or-later
"""PackML command/state codes, and a small evaluator for a capability's
declared `preconditions`/`postconditions` (ocm_core.Capability -- plain
`"signal == literal"` strings) against live SignalBus values.

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
    it's all the grammar will ever need.
    """
    if "==" not in expr:
        raise PreconditionError(f"unsupported condition (expected 'signal == value'): {expr!r}")
    name, _, literal = expr.partition("==")
    name = name.strip()
    if name not in values:
        raise PreconditionError(f"condition {expr!r} references unknown signal {name!r}")
    return values[name] == _parse_literal(literal)


async def read_signals(bus: SignalBus, instance: str, names: set[str]) -> dict[str, Any]:
    return {name: await bus.read(instance, name) for name in names}


def _condition_signal_names(conditions: tuple[str, ...]) -> set[str]:
    return {expr.partition("==")[0].strip() for expr in conditions}


async def preconditions_met(bus: SignalBus, instance: str, capability: Capability) -> bool:
    """True if every one of `capability.preconditions` currently holds
    against `instance`'s live signals. Evaluated fresh on every call --
    the caller (the coordinator) is the one that decides whether to poll.
    """
    if not capability.preconditions:
        return True
    values = await read_signals(bus, instance, _condition_signal_names(capability.preconditions))
    return all(_check_condition(expr, values) for expr in capability.preconditions)
