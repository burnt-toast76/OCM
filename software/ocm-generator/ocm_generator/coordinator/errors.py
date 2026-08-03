# SPDX-License-Identifier: AGPL-3.0-or-later
"""Errors raised by ocm_generator.coordinator."""

from __future__ import annotations

from ocm_generator.errors import OcmGeneratorError


class CoordinatorError(OcmGeneratorError):
    """Base class for every error ocm_generator.coordinator can raise."""


class HandshakeBindingError(CoordinatorError):
    """A robot module's manifest doesn't declare the signals spec/08's
    handshake needs -- e.g. no `comms.signals` block, or no signal (or more
    than one) with a given `handshake_*` role. Raised at bind time, not
    lazily on first use, so a missing binding is a startup-time refusal,
    not a hang mid-cycle.
    """


class PreconditionError(CoordinatorError):
    """A capability declares a precondition this coordinator doesn't know
    how to evaluate (spec/00's control vocabulary is fixed and small, but
    v0's expression grammar is smaller still: `signal == literal`).

    ADR-0023 Decision 5: this is now a *backstop*. The same defect --
    a condition naming a signal the module doesn't declare -- is refused at
    resolve time (CONDITION_UNKNOWN_SIGNAL), so a validated manifest should
    never reach this raise. It stays as a guard against an unvalidated
    manifest driven straight into the coordinator.
    """


class PostconditionError(CoordinatorError):
    """ADR-0023 Decision 2: a module reported PackML Complete while one of
    its own declared postconditions reads false against the live bus. The
    coordinator does not believe Complete on its own -- the step is faulted,
    naming the capability and the condition that read false.
    """


class OpTimeoutError(CoordinatorError):
    """ADR-0023 Decision 6: a capability's `timeout_s` elapsed while the
    coordinator was still waiting -- for its preconditions to hold, or for it
    to report Complete. Carries `on_timeout` (`hold` | `abort`) so the caller
    can dispose the part per the module's own declaration.
    """

    def __init__(self, capability_name: str, phase: str, on_timeout: str | None, timeout_s: float | None):
        self.capability_name = capability_name
        self.phase = phase  # "preconditions" | "completion"
        self.on_timeout = on_timeout
        self.timeout_s = timeout_s
        super().__init__(
            f"{capability_name} timed out after {timeout_s}s waiting for {phase} (on_timeout: {on_timeout})"
        )


class HeartbeatStaleError(CoordinatorError):
    """hs_heartbeat hasn't advanced for longer than the fault threshold
    while the program should still be running -- spec/08: "robot program
    dead or connection lost -> coordinator faults the cell."
    """


class DriverNotRegisteredError(CoordinatorError):
    """One or more resolved instances declare a `comms.protocol` this
    coordinator build has no registered transport driver for -- checked at
    go-live (`.drivers.check_drivers_registered`), before any motion
    starts. Per ADR-0012: authoring, resolve, scene, and plan all work
    with ANY protocol (including `x-<name>` custom ones) since they never
    touch transports; the coordinator is the one stage that actually has
    to talk to hardware, so it's the one stage that has to know what it
    can and can't drive.
    """

    def __init__(self, missing: list[tuple[str, str]]):
        self.missing = tuple(missing)
        detail = "; ".join(f"{instance} (protocol {protocol!r})" for protocol, instance in missing)
        super().__init__(f"no registered driver for: {detail}")
