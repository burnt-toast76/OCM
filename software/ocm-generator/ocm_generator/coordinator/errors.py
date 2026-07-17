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
    """


class HeartbeatStaleError(CoordinatorError):
    """hs_heartbeat hasn't advanced for longer than the fault threshold
    while the program should still be running -- spec/08: "robot program
    dead or connection lost -> coordinator faults the cell."
    """
