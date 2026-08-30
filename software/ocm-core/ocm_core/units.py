# SPDX-License-Identifier: AGPL-3.0-or-later
"""The deterministic unit resolver.

ADR-0014 captures every value in the exact unit its source prints -- 'mm' and
'in' both occur, verbatim, and nothing in a manifest ever converts. The moment
an engine has to COMPUTE with those values (derive collision geometry from a
component envelope, ADR-0027; check a `produces` measurement against its
source, ADR-0021's OCM_MEASUREMENT_SOURCE_INVALID), conversion happens here --
in ONE place, outside any model, from an explicit table.

This module is deliberately the SHARED component both of those consumers use:
ADR-0027's derived-geometry path is its first caller, and ADR-0021's
measurement-source check is its declared second. Do not grow a parallel
converter next to either.

Policy, non-negotiable:
- No guessing. An unrecognised unit string raises UnknownUnitError -- it is a
  refusal (OCM_UNIT_UNRECOGNISED), never a warning and never a pass-through.
- No normalising. 'MM', 'inch', 'inches' are NOT in the table; the table keys
  are the verbatim strings ADR-0014 transcription actually produces. If a
  datasheet prints a spelling this table lacks, the fix is one reviewed line
  HERE, not a fuzzy match.
- No silent rounding. Conversions are exact multiplications by the table's
  factors (the inch is exactly 25.4 mm by definition).
"""

from __future__ import annotations

import math


class UnknownUnitError(ValueError):
    """A unit string the explicit table does not recognise. The caller turns
    this into a refusal (OCM_UNIT_UNRECOGNISED); nothing may catch it and
    guess.
    """

    def __init__(self, unit: str, kind: str, known: tuple[str, ...]):
        self.unit = unit
        self.kind = kind
        self.known = known
        super().__init__(
            f"unrecognised {kind} unit {unit!r} (known: {list(known)}) -- "
            "add it to ocm_core.units' explicit table, never guess"
        )


# Verbatim unit string -> exact factor to millimetres. The inch is exactly
# 25.4 mm (international yard and pound agreement, 1959); everything else is
# metric-exact.
_LENGTH_TO_MM: dict[str, float] = {
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "in": 25.4,
    "ft": 304.8,
}

# Verbatim unit string -> exact factor to radians (ADR-0028 D2: an actuation
# target's unit is explicit and resolved here, never inferred from the joint).
_ANGLE_TO_RAD: dict[str, float] = {
    "deg": math.pi / 180.0,
    "rad": 1.0,
}


def known_length_units() -> tuple[str, ...]:
    return tuple(_LENGTH_TO_MM)


def length_to_mm(value: float, unit: str) -> float:
    """Convert a length in the given verbatim unit to millimetres.

    Raises UnknownUnitError for any unit string not in the explicit table.
    """
    try:
        factor = _LENGTH_TO_MM[unit]
    except KeyError:
        raise UnknownUnitError(unit, "length", known_length_units()) from None
    return float(value) * factor


def known_angle_units() -> tuple[str, ...]:
    return tuple(_ANGLE_TO_RAD)


def angle_to_rad(value: float, unit: str) -> float:
    """Convert an angle in the given verbatim unit to radians.

    Raises UnknownUnitError for any unit string not in the explicit table.
    """
    try:
        factor = _ANGLE_TO_RAD[unit]
    except KeyError:
        raise UnknownUnitError(unit, "angle", known_angle_units()) from None
    return float(value) * factor
