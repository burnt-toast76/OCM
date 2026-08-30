# SPDX-License-Identifier: AGPL-3.0-or-later
"""Typed object model for a cell composition file (cells/<id>/cell.yaml).

Validated against `spec/schema/ocm-cell-1.0.schema.json` (ADR-0026) by
`load_cell`, the same way `load_module` validates a module. `validate_cell_dict`
is kept for the one thing JSON Schema can't express -- duplicate instance names.
The port shape and the ports-vs-subsystem-block split follow ADR-0026: a port is
what a net or link can name; `identity`, `carriers`, `record_sink`, `produces`,
and `mode_selector` are top-level subsystem blocks, not ports.

`Cell.part` and `Cell.plan` are deliberately kept as raw dict/list (the schema
leaves them open too): that's the assembly-sequence DSL the generator's planner
interprets -- typing it here would be reaching into the planner.
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
    # Named joint -> radians, applied when composing the scene (only
    # meaningful for instances whose module has movable joints of its own,
    # e.g. a robot). Unlike mount.pose's xyz_mm/rpy_deg, this is radians
    # directly -- no mm/deg convention to convert, matching how joint
    # values are written everywhere else in robotics tooling. Absent ->
    # every joint defaults to zero.
    joint_state: dict[str, float] = field(default_factory=dict)
    # ADR-0023: binds this instance's capability `requires` keys to concrete
    # signals -- requirement name -> "instance.signal". Parsed here, never
    # resolved: whether the target instance/signal exists is a resolve-time
    # concern (ocm-resolve), like every other cross-instance reference.
    requires: dict[str, str] = field(default_factory=dict)

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
            joint_state={k: float(v) for k, v in data.get("joint_state", {}).items()},
            requires={k: str(v) for k, v in data.get("requires", {}).items()},
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


# ---------------------------------------------------------------------------
# ADR-0026 connectivity: a port is what a net/link can name; the rest are
# subsystem blocks. The cell layer inherits ADR-0015's flat port shape (no
# nested signals, no direction, no behaviour) one scope up.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Endpoint:
    """One end of a net or link. Names a cell `port` (+ optional `pin`), or
    reaches into a contained module via `{instance, port, pin}` (ADR-0026 D3).
    Nothing else -- ADR-0026 Erratum 1 removed the `sink` endpoint (a link
    endpoint names a port; the record_sink is reached from the port via
    `record_sink.port`, never named by a link). Which combination is valid is a
    resolve-time concern, not enforced here.
    """

    port: str | None = None
    instance: str | None = None
    pin: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Endpoint":
        return cls(port=data.get("port"), instance=data.get("instance"), pin=data.get("pin"))


@dataclass(frozen=True)
class Net:
    """N unordered endpoints on a common node (ADR-0015). `active` (ADR-0026 D4)
    is declared here, on the net -- never on a port or a pin.
    """

    id: str
    endpoints: tuple[Endpoint, ...] = ()
    active: str | None = None
    pressure: float | None = None
    pressure_units: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Net":
        return cls(
            id=data["id"],
            endpoints=tuple(Endpoint.from_dict(e) for e in data.get("endpoints", [])),
            active=data.get("active"),
            pressure=data.get("pressure"),
            pressure_units=data.get("pressure_units"),
        )


@dataclass(frozen=True)
class Nets:
    """Electrical, pneumatic, or safety connectivity as nets (ADR-0015/0026)."""

    electrical: tuple[Net, ...] = ()
    pneumatic: tuple[Net, ...] = ()
    safety: tuple[Net, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Nets":
        return cls(
            electrical=tuple(Net.from_dict(n) for n in data.get("electrical", [])),
            pneumatic=tuple(Net.from_dict(n) for n in data.get("pneumatic", [])),
            safety=tuple(Net.from_dict(n) for n in data.get("safety", [])),
        )


@dataclass(frozen=True)
class Port:
    """ADR-0026 D1: a cell boundary endpoint a net/link can name. Flat, like a
    module port -- an identifier, a domain, the domain's descriptor. No signals,
    no direction, no `domain: identification`.
    """

    id: str
    domain: str
    type: str | None = None
    thread: str | None = None
    function: str | None = None
    protocol: str | None = None
    role: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Port":
        return cls(
            id=data["id"],
            domain=data["domain"],
            type=data.get("type"),
            thread=data.get("thread"),
            function=data.get("function"),
            protocol=data.get("protocol"),
            role=data.get("role"),
        )


@dataclass(frozen=True)
class Link:
    """Exactly two endpoints -- a cable between two ports, or a port and the
    record_sink (ADR-0015/0026).
    """

    id: str
    a: Endpoint
    b: Endpoint
    protocol: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Link":
        return cls(id=data["id"], a=Endpoint.from_dict(data["a"]), b=Endpoint.from_dict(data["b"]), protocol=data.get("protocol"))


# ---------------------------------------------------------------------------
# ADR-0026 D2 subsystem blocks: top-level siblings of `ports`, not ports.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Identity:
    """ADR-0020 + ADR-0026 D2: reader configuration for part identity at cell
    entry. Not a port -- nothing is netted to a reader.
    """

    reader: str
    protocol: str | None = None
    carrier_id_source: str | None = None
    unit_id_source: str | None = None
    read_at: str | None = None
    on_mismatch: str | None = None
    on_absent: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Identity":
        return cls(
            reader=data["reader"],
            protocol=data.get("protocol"),
            carrier_id_source=data.get("carrier_id_source"),
            unit_id_source=data.get("unit_id_source"),
            read_at=data.get("read_at"),
            on_mismatch=data.get("on_mismatch"),
            on_absent=data.get("on_absent"),
        )


@dataclass(frozen=True)
class Carriers:
    """ADR-0020: carrier fleet declaration and wear budget."""

    tag: str
    warn_at_fraction: float | None = None
    refuse_at_fraction: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Carriers":
        return cls(tag=data["tag"], warn_at_fraction=data.get("warn_at_fraction"), refuse_at_fraction=data.get("refuse_at_fraction"))


@dataclass(frozen=True)
class TransitOffsets:
    """ADR-0031 D2: offsets from the located datum, millimetres, NEGATIVE
    by construction -- both joints at zero IS the located pose, and a
    positive value would put the carrier past the hard stop the datum is
    machined at (schema-enforced: maximum 0)."""

    travel: float
    lift: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TransitOffsets":
        return cls(travel=data["travel"], lift=data["lift"])


@dataclass(frozen=True)
class CarrierInstance:
    """ADR-0031: the cell's carrier instance -- which carrier TYPE and
    where it enters. `located_on` names the module whose mechanical.located
    datum roots the chain (D2/D3); `entry_mm` (optional) is where the
    carrier enters -- a place, never a commanded travel; `transit_mm`
    (optional, requires entry_mm) is where it currently sits, absent
    meaning seated at the located datum. Identity and wear stay ADR-0020's
    `carriers` block."""

    instance: str
    type: str  # id@revision of a carriers/ entry
    located_on: str
    entry_mm: TransitOffsets | None = None
    transit_mm: TransitOffsets | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CarrierInstance":
        entry = data.get("entry_mm")
        transit = data.get("transit_mm")
        return cls(
            instance=data["instance"],
            type=data["type"],
            located_on=data["located_on"],
            entry_mm=TransitOffsets.from_dict(entry) if entry else None,
            transit_mm=TransitOffsets.from_dict(transit) if transit else None,
        )


@dataclass(frozen=True)
class Journal:
    """ADR-0021: the on-cell journal within a record_sink."""

    path: str
    fsync: str | None = None
    retention_days: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Journal":
        return cls(path=data["path"], fsync=data.get("fsync"), retention_days=data.get("retention_days"))


@dataclass(frozen=True)
class ForwardTarget:
    """ADR-0021: one downstream sink a record_sink forwards to."""

    type: str
    dsn_env: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ForwardTarget":
        return cls(type=data["type"], dsn_env=data.get("dsn_env"))


@dataclass(frozen=True)
class RecordSink:
    """ADR-0021: where the cell's records drain to. Declared, not wired.
    `port` (ADR-0026 Erratum 1) names the cell port this sink drains through --
    the subsystem block references the port; a link never names the sink.
    """

    journal: Journal
    forward: tuple[ForwardTarget, ...] = ()
    on_journal_unavailable: str | None = None
    on_forward_unavailable: str | None = None
    buffer_max_events: int | None = None
    on_buffer_full: str | None = None
    port: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecordSink":
        return cls(
            journal=Journal.from_dict(data["journal"]),
            forward=tuple(ForwardTarget.from_dict(f) for f in data.get("forward", [])),
            on_journal_unavailable=data.get("on_journal_unavailable"),
            on_forward_unavailable=data.get("on_forward_unavailable"),
            buffer_max_events=data.get("buffer_max_events"),
            on_buffer_full=data.get("on_buffer_full"),
            port=data.get("port"),
        )


@dataclass(frozen=True)
class Measurement:
    """ADR-0021: one thing the cell measures. `unit` is verbatim (ADR-0014)."""

    name: str
    source: str
    unit: str | None = None
    type: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Measurement":
        return cls(name=data["name"], source=data["source"], unit=data.get("unit"), type=data.get("type"))


@dataclass(frozen=True)
class Verdict:
    """ADR-0021: the cell's pass/fail verdict field."""

    name: str
    values: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Verdict":
        return cls(name=data["name"], values=tuple(data.get("values", [])))


@dataclass(frozen=True)
class RecordKeys:
    """ADR-0021: which identity keys every record carries."""

    primary: str | None = None
    include: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecordKeys":
        return cls(primary=data.get("primary"), include=tuple(data.get("include", [])))


@dataclass(frozen=True)
class Produces:
    """ADR-0021: what the cell measures and records. Derived from components."""

    measurements: tuple[Measurement, ...] = ()
    verdict: Verdict | None = None
    record_keys: RecordKeys | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Produces":
        verdict = data.get("verdict")
        record_keys = data.get("record_keys")
        return cls(
            measurements=tuple(Measurement.from_dict(m) for m in data.get("measurements", [])),
            verdict=Verdict.from_dict(verdict) if verdict else None,
            record_keys=RecordKeys.from_dict(record_keys) if record_keys else None,
        )


@dataclass(frozen=True)
class ModeSelector:
    """ADR-0024 + ADR-0026 D2: the AUTO/MANUAL/EDIT keyswitch. Declares intent;
    does not certify the mode (spec/06).
    """

    component: str
    positions: tuple[str, ...] = ()
    manual_mode_safety: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModeSelector":
        return cls(component=data["component"], positions=tuple(data.get("positions", [])), manual_mode_safety=data.get("manual_mode_safety"))


@dataclass(frozen=True)
class Cell:
    """The instance layer: which modules, where, wired how."""

    ocm_version: str
    id: str
    license: str
    base: Base
    modules: tuple[ModuleInstance, ...]
    kind: str = "cell"
    name: str | None = None
    controller: Controller | None = None
    safety: CellSafety | None = None
    part: dict[str, Any] | None = None
    plan: list[Any] = field(default_factory=list)
    # ADR-0026: connectivity (a port is what a net/link can name) ...
    ports: tuple[Port, ...] = ()
    nets: Nets | None = None
    links: tuple[Link, ...] = ()
    # ... and the subsystem blocks that are NOT ports.
    identity: Identity | None = None
    carriers: Carriers | None = None
    # ADR-0031: the geometric carrier instance -- a different question about
    # the same object as `carriers` (identity/wear) above.
    carrier: CarrierInstance | None = None
    record_sink: RecordSink | None = None
    produces: Produces | None = None
    mode_selector: ModeSelector | None = None

    def module(self, instance: str) -> ModuleInstance:
        for m in self.modules:
            if m.instance == instance:
                return m
        raise KeyError(f"cell {self.id} has no module instance {instance!r}")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Cell":
        controller = data.get("controller")
        safety = data.get("safety")
        nets = data.get("nets")
        identity = data.get("identity")
        carriers = data.get("carriers")
        carrier = data.get("carrier")
        record_sink = data.get("record_sink")
        produces = data.get("produces")
        mode_selector = data.get("mode_selector")
        return cls(
            ocm_version=data["ocm_version"],
            id=data["id"],
            license=data["license"],
            kind=data.get("kind", "cell"),
            name=data.get("name"),
            base=Base.from_dict(data["base"]),
            modules=tuple(ModuleInstance.from_dict(m) for m in data.get("modules", [])),
            controller=Controller.from_dict(controller) if controller else None,
            safety=CellSafety.from_dict(safety) if safety else None,
            part=data.get("part"),
            plan=data.get("plan", []),
            ports=tuple(Port.from_dict(p) for p in data.get("ports", [])),
            nets=Nets.from_dict(nets) if nets else None,
            links=tuple(Link.from_dict(link) for link in data.get("links", [])),
            identity=Identity.from_dict(identity) if identity else None,
            carriers=Carriers.from_dict(carriers) if carriers else None,
            carrier=CarrierInstance.from_dict(carrier) if carrier else None,
            record_sink=RecordSink.from_dict(record_sink) if record_sink else None,
            produces=Produces.from_dict(produces) if produces else None,
            mode_selector=ModeSelector.from_dict(mode_selector) if mode_selector else None,
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
