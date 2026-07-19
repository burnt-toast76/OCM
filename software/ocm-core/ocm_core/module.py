# SPDX-License-Identifier: AGPL-3.0-or-later
"""Typed object model for an OCM module manifest (ocm-module-1.0.schema.json)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .parameter import Frame, Parameter

# Mirrors the schema's id/revision patterns. Re-used by ocm_core.cell to
# validate the "id@revision" refs a cell.yaml uses to point at a module —
# refs the module schema itself has no opinion about.
ID_PATTERN = re.compile(r"^[a-z0-9]+(\.[a-z0-9_-]+)+$")
REVISION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass(frozen=True)
class Mount:
    interface: str
    footprint_mm: tuple[float, float] | None = None
    keepout_mm: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Mount":
        footprint = data.get("footprint_mm")
        return cls(
            interface=data["interface"],
            footprint_mm=tuple(footprint) if footprint else None,
            keepout_mm=data.get("keepout_mm", 0.0),
        )


@dataclass(frozen=True)
class Geometry:
    visual: str | None = None
    collision: str | None = None
    urdf_fragment: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Geometry":
        return cls(
            visual=data.get("visual"),
            collision=data.get("collision"),
            urdf_fragment=data.get("urdf_fragment"),
        )


@dataclass(frozen=True)
class Mechanical:
    mount: Mount
    frames: dict[str, Frame]
    geometry: Geometry
    mass_kg: float
    com_mm: tuple[float, float, float] | None = None
    inertia_kgm2: tuple[float, float, float, float, float, float] | None = None

    @property
    def origin(self) -> Frame:
        return self.frames["origin"]

    @property
    def tcp(self) -> Frame | None:
        return self.frames.get("tcp")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Mechanical":
        com = data.get("com_mm")
        inertia = data.get("inertia_kgm2")
        return cls(
            mount=Mount.from_dict(data["mount"]),
            frames={name: Frame.from_dict(f) for name, f in data["frames"].items()},
            geometry=Geometry.from_dict(data["geometry"]),
            mass_kg=data["mass_kg"],
            com_mm=tuple(com) if com else None,
            inertia_kgm2=tuple(inertia) if inertia else None,
        )


@dataclass(frozen=True)
class Supply:
    rail: str
    current_nominal_a: float
    current_peak_a: float | None = None
    inrush_a: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Supply":
        return cls(
            rail=data["rail"],
            current_nominal_a=data["current_nominal_a"],
            current_peak_a=data.get("current_peak_a"),
            inrush_a=data.get("inrush_a"),
        )


@dataclass(frozen=True)
class Pneumatic:
    pressure_bar: float | None = None
    flow_nl_min: float | None = None
    port: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Pneumatic":
        return cls(
            pressure_bar=data.get("pressure_bar"),
            flow_nl_min=data.get("flow_nl_min"),
            port=data.get("port"),
        )


@dataclass(frozen=True)
class Connector:
    ref: str | None = None
    type: str | None = None
    carries: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Connector":
        return cls(ref=data.get("ref"), type=data.get("type"), carries=data.get("carries"))


@dataclass(frozen=True)
class Electrical:
    supplies: tuple[Supply, ...] = ()
    pneumatic: Pneumatic | None = None
    connectors: tuple[Connector, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Electrical":
        pneumatic = data.get("pneumatic")
        return cls(
            supplies=tuple(Supply.from_dict(s) for s in data.get("supplies", [])),
            pneumatic=Pneumatic.from_dict(pneumatic) if pneumatic else None,
            connectors=tuple(Connector.from_dict(c) for c in data.get("connectors", [])),
        )


@dataclass(frozen=True)
class Signal:
    """One entry in the semantic I/O map. `name` becomes the generated PLC tag.

    v1.1 adds composite types (`pose6d`, `vec3`, `struct` — spec/CHANGELOG.md).
    `frame` (pose6d's required reference frame) and `fields` (struct's
    ordered field name -> scalar type map, wire layout in declaration
    order) carry those declarations; both are None for every scalar type.

    ADR-0014 additive field: `source` is this signal's provenance into a
    referenced component's own signal list ('REFDES.signal_name') -- None
    for a signal with no such backing part.
    """

    name: str
    direction: str
    type: str
    unit: str | None = None
    offset: int | None = None
    bit: int | None = None
    role: str | None = None
    frame: str | None = None
    fields: dict[str, str] | None = None
    source: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Signal":
        fields = data.get("fields")
        return cls(
            name=data["name"],
            direction=data["direction"],
            type=data["type"],
            unit=data.get("unit"),
            offset=data.get("offset"),
            bit=data.get("bit"),
            role=data.get("role"),
            frame=data.get("frame"),
            fields=dict(fields) if fields is not None else None,
            source=data.get("source"),
        )


@dataclass(frozen=True)
class Comms:
    protocol: str
    signals: tuple[Signal, ...] = ()
    esi: str | None = None

    def signals_with_role(self, role: str) -> tuple[Signal, ...]:
        return tuple(s for s in self.signals if s.role == role)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Comms":
        return cls(
            protocol=data["protocol"],
            signals=tuple(Signal.from_dict(s) for s in data.get("signals", [])),
            esi=data.get("esi"),
        )


@dataclass(frozen=True)
class PathSpec:
    """For hold_still=false ops: what the process needs of the path itself."""

    speed_mm_s: Parameter | None = None
    max_accel_mm_s2: float | None = None
    corner_radius_mm: float | None = None
    orientation: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PathSpec":
        speed = data.get("speed_mm_s")
        return cls(
            speed_mm_s=Parameter.from_dict(speed) if speed else None,
            max_accel_mm_s2=data.get("max_accel_mm_s2"),
            corner_radius_mm=data.get("corner_radius_mm"),
            orientation=data.get("orientation"),
        )


@dataclass(frozen=True)
class Motion:
    """How the robot (or the module's own axes) must move to execute an op."""

    frame: str = "tcp"
    approach_vec: tuple[float, float, float] | None = None
    approach_mm: float | None = None
    approach_speed_mm_s: float | None = None
    retract_vec: tuple[float, float, float] | None = None
    retract_mm: float | None = None
    clearance_mm: float | None = None
    hold_still: bool = True
    path: PathSpec | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Motion":
        approach_vec = data.get("approach_vec")
        retract_vec = data.get("retract_vec")
        path = data.get("path")
        return cls(
            frame=data.get("frame", "tcp"),
            approach_vec=tuple(approach_vec) if approach_vec else None,
            approach_mm=data.get("approach_mm"),
            approach_speed_mm_s=data.get("approach_speed_mm_s"),
            retract_vec=tuple(retract_vec) if retract_vec else None,
            retract_mm=data.get("retract_mm"),
            clearance_mm=data.get("clearance_mm"),
            hold_still=data.get("hold_still", True),
            path=PathSpec.from_dict(path) if path else None,
        )


@dataclass(frozen=True)
class Capability:
    """A verb this module offers. The agent-facing surface."""

    name: str
    summary: str
    parameters: dict[str, Parameter] = field(default_factory=dict)
    motion: Motion | None = None
    preconditions: tuple[str, ...] = ()
    postconditions: tuple[str, ...] = ()
    results: dict[str, Parameter] = field(default_factory=dict)
    nominal_duration_s: float | None = None
    consumes: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Capability":
        motion = data.get("motion")
        return cls(
            name=data["name"],
            summary=data["summary"],
            parameters={
                k: Parameter.from_dict(v) for k, v in data.get("parameters", {}).items()
            },
            motion=Motion.from_dict(motion) if motion else None,
            preconditions=tuple(data.get("preconditions", [])),
            postconditions=tuple(data.get("postconditions", [])),
            results={k: Parameter.from_dict(v) for k, v in data.get("results", {}).items()},
            nominal_duration_s=data.get("nominal_duration_s"),
            consumes=tuple(data.get("consumes", [])),
        )


@dataclass(frozen=True)
class Process:
    """Recipe-level parameters, set once per PART rather than per operation."""

    recipe_parameters: dict[str, Parameter] = field(default_factory=dict)
    warmup_s: float | None = None
    purge_required: bool | None = None
    idle_timeout_s: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Process":
        return cls(
            recipe_parameters={
                k: Parameter.from_dict(v) for k, v in data.get("recipe_parameters", {}).items()
            },
            warmup_s=data.get("warmup_s"),
            purge_required=data.get("purge_required"),
            idle_timeout_s=data.get("idle_timeout_s"),
        )


@dataclass(frozen=True)
class StateMachine:
    model: str
    modes: tuple[str, ...] = ("production",)
    implements: tuple[str, ...] = ()
    abort_safe: bool | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StateMachine":
        return cls(
            model=data["model"],
            modes=tuple(data.get("modes", ["production"])),
            implements=tuple(data.get("implements", [])),
            abort_safe=data.get("abort_safe"),
        )


@dataclass(frozen=True)
class Safety:
    """Declares hazards. NOT a risk assessment."""

    hazards: tuple[str, ...] = ()
    required_performance_level: str | None = None
    sto_required: bool | None = None
    guarding: str | None = None
    safe_state: str | None = None
    notes: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Safety":
        return cls(
            hazards=tuple(data.get("hazards", [])),
            required_performance_level=data.get("required_performance_level"),
            sto_required=data.get("sto_required"),
            guarding=data.get("guarding"),
            safe_state=data.get("safe_state"),
            notes=data.get("notes"),
        )


@dataclass(frozen=True)
class WearItem:
    name: str | None = None
    part_number: str | None = None
    interval_cycles: int | None = None
    interval_hours: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WearItem":
        return cls(
            name=data.get("name"),
            part_number=data.get("part_number"),
            interval_cycles=data.get("interval_cycles"),
            interval_hours=data.get("interval_hours"),
        )


@dataclass(frozen=True)
class Maintenance:
    wear_items: tuple[WearItem, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Maintenance":
        return cls(wear_items=tuple(WearItem.from_dict(w) for w in data.get("wear_items", [])))


@dataclass(frozen=True)
class ComponentRef:
    """A reference to a components/ entry from a module's own `components:`
    list: 'id@x.y.z' -- one layer up from ocm_core.cell.ModuleRef (ADR-0014:
    modules reference components the same way cells reference modules).
    Not imported from .cell to avoid a circular import (cell.py already
    depends on this module for ID_PATTERN/REVISION_PATTERN).
    """

    id: str
    revision: str

    @classmethod
    def parse(cls, ref: str) -> "ComponentRef":
        if "@" not in ref:
            raise ValueError(f"component ref {ref!r} is missing '@revision'")
        component_id, _, revision = ref.partition("@")
        if not ID_PATTERN.match(component_id):
            raise ValueError(f"component ref {ref!r} has an invalid id {component_id!r}")
        if not REVISION_PATTERN.match(revision):
            raise ValueError(f"component ref {ref!r} has an invalid revision {revision!r}")
        return cls(id=component_id, revision=revision)

    def __str__(self) -> str:
        return f"{self.id}@{self.revision}"


@dataclass(frozen=True)
class ModuleComponent:
    """One entry in a module's `components:` list -- a purchased part this
    module is assembled from, by its own reference designator (ADR-0014).
    """

    refdes: str
    ref: ComponentRef

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModuleComponent":
        return cls(refdes=data["refdes"], ref=ComponentRef.parse(data["ref"]))


@dataclass(frozen=True)
class Module:
    """A validated OCM module manifest. Construct via ocm_core.load_module, not directly."""

    ocm_version: str
    id: str
    revision: str
    kind: str
    license: str
    mechanical: Mechanical
    state_machine: StateMachine
    name: str | None = None
    vendor: str | None = None
    description: str | None = None
    datasheet: str | None = None
    electrical: Electrical | None = None
    comms: Comms | None = None
    capabilities: tuple[Capability, ...] = ()
    process: Process | None = None
    safety: Safety | None = None
    maintenance: Maintenance | None = None
    components: tuple[ModuleComponent, ...] = ()

    @property
    def is_abort_safe(self) -> bool:
        return bool(self.state_machine.abort_safe)

    def capability(self, name: str) -> Capability:
        for cap in self.capabilities:
            if cap.name == name:
                return cap
        raise KeyError(f"{self.id} has no capability {name!r}")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Module":
        electrical = data.get("electrical")
        comms = data.get("comms")
        process = data.get("process")
        safety = data.get("safety")
        maintenance = data.get("maintenance")
        return cls(
            ocm_version=data["ocm_version"],
            id=data["id"],
            revision=data["revision"],
            kind=data["kind"],
            license=data["license"],
            name=data.get("name"),
            vendor=data.get("vendor"),
            description=data.get("description"),
            datasheet=data.get("datasheet"),
            mechanical=Mechanical.from_dict(data["mechanical"]),
            electrical=Electrical.from_dict(electrical) if electrical else None,
            comms=Comms.from_dict(comms) if comms else None,
            capabilities=tuple(Capability.from_dict(c) for c in data.get("capabilities", [])),
            process=Process.from_dict(process) if process else None,
            state_machine=StateMachine.from_dict(data["state_machine"]),
            safety=Safety.from_dict(safety) if safety else None,
            maintenance=Maintenance.from_dict(maintenance) if maintenance else None,
            components=tuple(ModuleComponent.from_dict(c) for c in data.get("components", [])),
        )
