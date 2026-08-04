# SPDX-License-Identifier: AGPL-3.0-or-later
"""Typed object model for an OCM carrier type manifest
(ocm-carrier-1.0.schema.json, ADR-0031 D1).

A carrier is transcribed hardware -- frames, geometry, joints, meshes --
and DELIBERATELY has no `state_machine`, `comms`, or `capabilities`: a
pallet has no controller, no PackML states, and nothing to command it
with. Per ADR-0014 the absent fields stay absent rather than acquiring
placeholders; `CARRIER_CONTROL_FIELDS` names them so `validate_carrier`
can refuse a manifest carrying one (OCM_CARRIER_TYPE_HAS_CONTROL) with a
message that says why, instead of a bare "additional property not
allowed". Identity and wear stay ADR-0020's `carriers` block -- a
different question about the same object.

`Geometry` and `Frame` are the module model's own -- one definition, no
drifting copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .module import Geometry
from .parameter import Frame

# The module-schema sections a carrier must never carry (ADR-0031 D1).
CARRIER_CONTROL_FIELDS = ("state_machine", "comms", "capabilities")


@dataclass(frozen=True)
class CarrierMount:
    """The carrier's footprint on whatever locates it -- no interface: a
    carrier is placed by being LOCATED (ADR-0031 D2), not bolted."""

    footprint_mm: tuple[float, float] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CarrierMount":
        footprint = data.get("footprint_mm")
        return cls(footprint_mm=tuple(footprint) if footprint else None)


@dataclass(frozen=True)
class CarrierMechanical:
    frames: dict[str, Frame]
    geometry: Geometry
    mass_kg: float
    mount: CarrierMount | None = None
    com_mm: tuple[float, float, float] | None = None

    @property
    def origin(self) -> Frame:
        return self.frames["origin"]

    @property
    def part_datum(self) -> Frame | None:
        """Where a correctly seated part's own origin lands -- load-bearing
        with ADR-0031 D4 (part 2); a plain frame until then."""
        return self.frames.get("part_datum")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CarrierMechanical":
        com = data.get("com_mm")
        mount = data.get("mount")
        return cls(
            frames={name: Frame.from_dict(f) for name, f in data["frames"].items()},
            geometry=Geometry.from_dict(data["geometry"]),
            mass_kg=data["mass_kg"],
            mount=CarrierMount.from_dict(mount) if mount else None,
            com_mm=tuple(com) if com else None,
        )


@dataclass(frozen=True)
class Carrier:
    ocm_version: str
    id: str
    revision: str
    license: str
    mechanical: CarrierMechanical
    name: str | None = None
    vendor: str | None = None
    description: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Carrier":
        return cls(
            ocm_version=data["ocm_version"],
            id=data["id"],
            revision=data["revision"],
            license=data["license"],
            mechanical=CarrierMechanical.from_dict(data["mechanical"]),
            name=data.get("name"),
            vendor=data.get("vendor"),
            description=data.get("description"),
        )
