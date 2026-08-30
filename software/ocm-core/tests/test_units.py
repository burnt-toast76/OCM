# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm_core.units -- the shared deterministic unit resolver (ADR-0027 /
ADR-0021). Verbatim table lookups, exact factors, refusal on anything else."""

import pytest

from ocm_core import UnknownUnitError, known_length_units, length_to_mm


def test_exact_conversions():
    assert length_to_mm(1, "mm") == 1.0
    assert length_to_mm(2, "cm") == 20.0
    assert length_to_mm(0.5, "m") == 500.0
    assert length_to_mm(1, "in") == 25.4  # exact by definition, not approximate
    assert length_to_mm(1, "ft") == 304.8


def test_unrecognised_unit_refuses_never_guesses():
    # 'inch'/'inches'/'MM' are deliberately NOT normalised -- ADR-0014 captures
    # verbatim strings, and the table only knows what a reviewed line added.
    for bad in ("inch", "inches", "MM", "In", "millimetre", ""):
        with pytest.raises(UnknownUnitError) as exc:
            length_to_mm(1, bad)
        assert bad in str(exc.value) or bad == ""
        assert exc.value.known == known_length_units()


def test_known_units_is_the_explicit_table():
    assert set(known_length_units()) == {"mm", "cm", "m", "in", "ft"}


def test_exact_angle_conversions():
    import math

    from ocm_core import angle_to_rad, known_angle_units

    assert angle_to_rad(180, "deg") == pytest.approx(math.pi)
    assert angle_to_rad(1.5, "rad") == 1.5
    assert set(known_angle_units()) == {"deg", "rad"}


def test_unrecognised_angle_unit_refuses_never_guesses():
    from ocm_core import angle_to_rad, known_angle_units

    # 'degree'/'degrees'/'°' are deliberately NOT normalised -- same discipline
    # as the length table (ADR-0028 D2 leans on ADR-0014's verbatim policy).
    for bad in ("degree", "degrees", "°", "grad", "turn", "rev", ""):
        with pytest.raises(UnknownUnitError) as exc:
            angle_to_rad(1, bad)
        assert exc.value.kind == "angle"
        assert exc.value.known == known_angle_units()
