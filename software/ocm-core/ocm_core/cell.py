# SPDX-License-Identifier: AGPL-3.0-or-later
"""Typed object model for a cell composition file (cells/<id>/cell.yaml).

There is no published JSON Schema for this shape yet (ADR-0011's mount grid
is still open, and everything hangs off it), so `validate_cell_dict` does
structural checks rather than schema validation. `Cell.part` and `Cell.plan`
are deliberately kept as raw dicts/lists: that's the assembly-sequence DSL
the generator's planner interprets — typing it here would be reaching into
the planner, which this task explicitly leaves alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .module import ID_PATTERN, REVISION_PATTERN


@dataclass(frozen=True)
class ModuleRef:
    """A reference to a module manifest by id and revision: 'id@x.y.z'."""

    id: str
    revision: str

    @classmethod
    def parse(cls, ref: str) -> "ModuleRef":
        if "@" not in ref:
            raise ValueError(f"module ref {ref!r} is missing '@revision'")
        module_id, _, revision = ref.partition("@")
        if not ID_PATTERN.match(module_id):
            raise ValueError(f"module ref {ref!r} has an invalid id {module_id!r}")
        if not REVISION_PATTERN.match(revision):
            raise ValueError(f"module ref {ref!r} has an invalid revision {revision!r}")
        return cls(id=module_id, revision=revision)

    def __str__(self) -> str:
        return f"{self.id}@{self.revision}"


@dataclass(frozen=True)
class Pose:
    xyz_mm: tuple[float, float, float]
    rpy_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Pose":
        return cls(
            xyz_mm=tuple(data["xyz_mm"]),
            rpy_deg=tuple(data.get("rpy_deg", (0.0, 0.0, 0.0))),
        )


@dataclass(frozen=True)
class InstanceMount:
    """Where a module instance sits: a grid station + pose, or 'on' another instance."""

    station: tuple[float, float] | None = None
    pose: Pose | None = None
    on: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InstanceMount":
        station = data.get("station")
        pose = data.get("pose")
        return cls(
            station=tuple(station) if station else None,
            pose=Pose.from_dict(pose) if pose else None,
            on=data.get("on"),
        )


@dataclass(frozen=True)
class InstanceAddress:
    """Fieldbus/network address of a module instance. Shape varies by protocol,
    so known fields are lifted out and the rest is kept in `raw`.
    """

    ip: str | None = None
    ethercat_position: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InstanceAddress":
        return cls(ip=data.get("ip"), ethercat_position=data.get("ethercat_position"), raw=dict(data))


@dataclass(frozen=True)
class Consumable:
    part: str
    source: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Consumable":
        return cls(part=data["part"], source=data.get("source"))


@dataclass(frozen=True)
class ModuleInstance:
    instance: str
    module: ModuleRef
    mount: InstanceMount | None = None
    address: InstanceAddress | None = None
    tool: str | None = None
    consumables: dict[str, Consumable] = field(default_factory=dict)
    calibration: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModuleInstance":
        mount = data.get("mount")
        address = data.get("address")
        return cls(
            instance=data["instance"],
            module=ModuleRef.parse(data["module"]),
            mount=InstanceMount.from_dict(mount) if mount else None,
            address=InstanceAddress.from_dict(address) if address else None,
            tool=data.get("tool"),
            consumables={
                k: Consumable.from_dict(v) for k, v in data.get("consumables", {}).items()
            },
            calibration=data.get("calibration"),
        )


@dataclass(frozen=True)
class Base:
    module: ModuleRef
    datum: str
    grid: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Base":
        return cls(module=ModuleRef.parse(data["module"]), datum=data["datum"], grid=data["grid"])


@dataclass(frozen=True)
class Controller:
    runtime: str | None = None
    target: str | None = None
    fieldbus: str | None = None
    tags: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Controller":
        return cls(
            runtime=data.get("runtime"),
            target=data.get("target"),
            fieldbus=data.get("fieldbus"),
            tags=data.get("tags"),
        )


@dataclass(frozen=True)
class CellSafety:
    """NOT a risk assessment. Hardwired and separately certified — the generator's
    only job is to refuse a build whose declared safety hardware doesn't meet it.
    """

    circuit: str | None = None
    relay: str | None = None
    performance_level: str | None = None
    verified_by: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CellSafety":
        return cls(
            circuit=data.get("circuit"),
            relay=data.get("relay"),
            performance_level=data.get("performance_level"),
            verified_by=data.get("verified_by"),
        )


@dataclass(frozen=True)
class Cell:
    """The instance layer: which modules, where, wired how."""

    ocm_version: str
    id: str
    license: str
    base: Base
    modules: tuple[ModuleInstance, ...]
    name: str | None = None
    controller: Controller | None = None
    safety: CellSafety | None = None
    part: dict[str, Any] | None = None
    plan: list[Any] = field(default_factory=list)

    def module(self, instance: str) -> ModuleInstance:
        for m in self.modules:
            if m.instance == instance:
                return m
        raise KeyError(f"cell {self.id} has no module instance {instance!r}")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Cell":
        controller = data.get("controller")
        safety = data.get("safety")
        return cls(
            ocm_version=data["ocm_version"],
            id=data["id"],
            license=data["license"],
            name=data.get("name"),
            base=Base.from_dict(data["base"]),
            modules=tuple(ModuleInstance.from_dict(m) for m in data.get("modules", [])),
            controller=Controller.from_dict(controller) if controller else None,
            safety=CellSafety.from_dict(safety) if safety else None,
            part=data.get("part"),
            plan=data.get("plan", []),
        )


def validate_cell_dict(data: Any) -> list[str]:
    """Structural checks for the cell-composition shape.

    Returns a list of human-readable problems (empty if none). This is not
    JSON Schema validation — no schema for this shape has been published yet.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["<root>: expected a mapping"]

    for key in ("ocm_version", "id", "license", "base", "modules"):
        if key not in data:
            errors.append(f"<root>: missing required key {key!r}")
    if errors:
        return errors  # can't safely check further without the basics

    if data.get("ocm_version") != "1.0":
        errors.append(f"ocm_version: expected '1.0', got {data.get('ocm_version')!r}")

    if data.get("kind") != "cell":
        errors.append(f"kind: expected 'cell', got {data.get('kind')!r}")

    base = data.get("base")
    if not isinstance(base, dict) or "module" not in base:
        errors.append("base: missing required key 'module'")
    elif isinstance(base.get("module"), str):
        try:
            ModuleRef.parse(base["module"])
        except ValueError as e:
            errors.append(f"base.module: {e}")

    modules = data.get("modules")
    if not isinstance(modules, list) or not modules:
        errors.append("modules: expected a non-empty list")
    else:
        seen_instances: set[str] = set()
        for i, m in enumerate(modules):
            if not isinstance(m, dict) or "instance" not in m or "module" not in m:
                errors.append(f"modules[{i}]: missing required key 'instance' or 'module'")
                continue
            if m["instance"] in seen_instances:
                errors.append(f"modules[{i}]: duplicate instance name {m['instance']!r}")
            seen_instances.add(m["instance"])
            if isinstance(m.get("module"), str):
                try:
                    ModuleRef.parse(m["module"])
                except ValueError as e:
                    errors.append(f"modules[{i}].module: {e}")

    return errors
