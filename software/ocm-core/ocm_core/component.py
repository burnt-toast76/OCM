# SPDX-License-Identifier: AGPL-3.0-or-later
"""Typed object model for an OCM component definition
(ocm-component-1.0.schema.json). ADR-0014: a component is a purchasable
part described by transcribed catalog facts, mirroring `module.py`'s own
shape one level down -- typed, frozen, `from_dict`-constructed, nothing
more. Unlike a `Module`, a `Component` carries no capabilities, no
mount/frames, no PackML, no safety assessment: those are assembly-level
judgment (spec/10 -- "what a component definition must NOT contain").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ComponentSource:
    """Provenance is mandatory -- every component names where its facts
    came from (spec/10, ADR-0014's zero-assumption rule)."""

    kind: str
    ref: str
    date: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ComponentSource":
        return cls(kind=data["kind"], ref=data["ref"], date=data.get("date"))


@dataclass(frozen=True)
class ComponentSupply:
    rail: str
    current_nominal_a: float | None = None
    current_peak_a: float | None = None
    note: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ComponentSupply":
        return cls(
            rail=data["rail"],
            current_nominal_a=data.get("current_nominal_a"),
            current_peak_a=data.get("current_peak_a"),
            note=data.get("note"),
        )


@dataclass(frozen=True)
class ComponentConnector:
    ref: str | None = None
    type: str | None = None
    carries: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ComponentConnector":
        return cls(ref=data.get("ref"), type=data.get("type"), carries=data.get("carries"))


@dataclass(frozen=True)
class ComponentElectrical:
    supplies: tuple[ComponentSupply, ...] = ()
    connectors: tuple[ComponentConnector, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ComponentElectrical":
        return cls(
            supplies=tuple(ComponentSupply.from_dict(s) for s in data.get("supplies", [])),
            connectors=tuple(ComponentConnector.from_dict(c) for c in data.get("connectors", [])),
        )


@dataclass(frozen=True)
class ComponentPneumatic:
    """Pressure as a RANGE if the source gives one -- choosing a single
    operating point is a module-layer decision (ADR-0014), never made here.
    """

    pressure_min: float | None = None
    pressure_max: float | None = None
    pressure_units: str | None = None  # verbatim as printed (e.g. "bar", "psi") -- never converted
    flow: float | None = None
    flow_units: str | None = None  # verbatim as printed (e.g. "Nl/min", "SCFM") -- never converted
    port: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ComponentPneumatic":
        return cls(
            pressure_min=data.get("pressure_min"),
            pressure_max=data.get("pressure_max"),
            pressure_units=data.get("pressure_units"),
            flow=data.get("flow"),
            flow_units=data.get("flow_units"),
            port=data.get("port"),
        )


@dataclass(frozen=True)
class ComponentSignal:
    """The device's own I/O as documented -- device-perspective direction
    (`direction_device`), unlike a module's coordinator-perspective
    `direction`. A module's `comms.signals[].source` provenance points at
    one of these by name (spec/10).
    """

    name: str
    direction_device: str
    type: str
    unit: str | None = None
    electrical: str | None = None
    note: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ComponentSignal":
        return cls(
            name=data["name"],
            direction_device=data["direction_device"],
            type=data["type"],
            unit=data.get("unit"),
            electrical=data.get("electrical"),
            note=data.get("note"),
        )


@dataclass(frozen=True)
class ComponentComms:
    protocol: str | None = None
    device_description: str | None = None
    signals: tuple[ComponentSignal, ...] = ()

    def signal(self, name: str) -> ComponentSignal | None:
        for s in self.signals:
            if s.name == name:
                return s
        return None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ComponentComms":
        return cls(
            protocol=data.get("protocol"),
            device_description=data.get("device_description"),
            signals=tuple(ComponentSignal.from_dict(s) for s in data.get("signals", [])),
        )


@dataclass(frozen=True)
class ComponentEnvelope:
    length: float | None = None
    width: float | None = None
    height: float | None = None
    units: str | None = None  # verbatim as printed (e.g. "mm", "in") -- never converted

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ComponentEnvelope":
        return cls(length=data.get("length"), width=data.get("width"), height=data.get("height"), units=data.get("units"))


@dataclass(frozen=True)
class ComponentGeometry:
    envelope: ComponentEnvelope | None = None
    mass: float | None = None
    units: str | None = None  # mass unit, verbatim as printed (e.g. "kg", "lb") -- never converted

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ComponentGeometry":
        envelope = data.get("envelope")
        return cls(
            envelope=ComponentEnvelope.from_dict(envelope) if envelope else None,
            mass=data.get("mass"),
            units=data.get("units"),
        )


@dataclass(frozen=True)
class Component:
    """A validated OCM component definition. Construct via
    ocm_core.load_component, not directly.
    """

    ocm_version: str
    id: str
    revision: str
    kind: str
    vendor: str
    source: ComponentSource
    name: str | None = None
    part_number: str | None = None
    electrical: ComponentElectrical | None = None
    pneumatic: ComponentPneumatic | None = None
    comms: ComponentComms | None = None
    geometry: ComponentGeometry | None = None
    hazards: tuple[str, ...] = ()
    notes: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Component":
        electrical = data.get("electrical")
        pneumatic = data.get("pneumatic")
        comms = data.get("comms")
        geometry = data.get("geometry")
        return cls(
            ocm_version=data["ocm_version"],
            id=data["id"],
            revision=data["revision"],
            kind=data["kind"],
            vendor=data["vendor"],
            source=ComponentSource.from_dict(data["source"]),
            name=data.get("name"),
            part_number=data.get("part_number"),
            electrical=ComponentElectrical.from_dict(electrical) if electrical else None,
            pneumatic=ComponentPneumatic.from_dict(pneumatic) if pneumatic else None,
            comms=ComponentComms.from_dict(comms) if comms else None,
            geometry=ComponentGeometry.from_dict(geometry) if geometry else None,
            hazards=tuple(data.get("hazards", [])),
            notes=data.get("notes"),
        )
