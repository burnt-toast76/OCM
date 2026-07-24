# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0015: a module's connectivity -- its `nets:` (electrical/pneumatic),
`links:` (communication) and `ports:` (external interface) -- cross-checked
against the transcribed connector/pin lists of the components it places.

This is the same kind of cross-file resolution `_check_module_components`
already does for a module's `components:` list (ADR-0014), one concern over:
that pass answers "does this refdes name a real component?"; this one answers
"does this endpoint name a real *connector/pin* on that component, and does
the wiring hang together as a whole?".

Only the refusals ADR-0015 lists as "implementable against the current
schema -- structural only" live here. Everything the ADR defers (driver
contention, signal-class, required-pin, pneumatic function/size, pressure
rating) waits on a component field that isn't transcribed yet; inferring it
from free text would be the exact ADR-0014 violation ADR-0015 was written to
avoid, so it is deliberately absent, not merely unfinished.

Chain order (which EtherCAT slave is second) is DERIVED here by walking the
links' `a`/`b` at resolve time -- never read from a stored index, because no
`position`/`index` field exists anywhere in the schema (ADR-0015 Decision 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ocm_core import Component, Endpoint, Link, Module, Net, Port

# EtherCAT-style chain roles, as a datasheet/design labels them (schema
# `role` enum, minus the generic "port"). A terminal carrying one of these
# participates in the derived-chain walk; anything else does not.
_CHAIN_ROLES = ("master", "slave_in", "slave_out")


@dataclass(frozen=True)
class _Terminal:
    """What one net/link `Endpoint` resolved to. `None` fields are simply
    "not that kind of terminal": a module-port endpoint has `port`/`domain`
    set and `refdes` empty; a component endpoint is the reverse.
    """

    port_id: str | None
    domain: str | None  # port terminal only -- the port's declared domain
    refdes: str | None
    ref: str | None
    pin: str | None
    role: str | None
    protocol: str | None
    is_comms: bool  # ref matched a comms connector (vs an electrical one)

    @property
    def key(self) -> tuple:
        """Identity for the chain graph -- a module port is one node; a
        component connector is (refdes, ref), so a device's IN and OUT are
        two distinct nodes on the same refdes."""
        if self.port_id is not None:
            return ("port", self.port_id)
        return ("comp", self.refdes, self.ref)

    @property
    def pin_key(self) -> tuple | None:
        """Identity for the "pin on more than one net" check -- only
        meaningful for an endpoint that actually names a pin."""
        if self.pin is None:
            return None
        if self.port_id is not None:
            return ("port", self.port_id, self.pin)
        return ("comp", self.refdes, self.ref, self.pin)


def _connectors_of(component: "Component") -> tuple[dict[str, set[str]], dict[str, object], bool]:
    """A component's endpoint-referenceable connectors, keyed by `ref`.

    Returns (electrical, comms, declares_any):
    - electrical: connector ref -> the pins it declares (schema endpoint
      doc: a net/link `ref` names an `electrical.connectors[].ref` ...).
    - comms: connector ref -> the ComponentCommsConnector (... or a
      `comms.connectors[].ref`); these carry no pins.
    - declares_any: whether the component declares ANY connector at all --
      the basis for ADR-0015's "instance whose component declares no
      connectors" refusal. A connector with no `ref` can't be endpoint-named
      but still counts as "declares a connector" here.
    """
    electrical: dict[str, set[str]] = {}
    comms: dict[str, object] = {}
    declares_any = False
    if component.electrical and component.electrical.connectors:
        declares_any = True
        for c in component.electrical.connectors:
            if c.ref is not None:
                electrical[c.ref] = {p.pin for p in c.pins}
    if component.comms and component.comms.connectors:
        declares_any = True
        for c in component.comms.connectors:
            if c.ref is not None:
                comms[c.ref] = c
    return electrical, comms, declares_any


def _resolve_endpoint(
    location: str,
    module: "Module",
    where: str,
    endpoint: "Endpoint",
    ports_by_id: dict[str, "Port"],
    declared_refdes: list[str],
    resolved_by_refdes: "dict[str, Component]",
    errors: list[str],
) -> _Terminal | None:
    """Resolve one endpoint to a `_Terminal`, appending a refusal (and
    returning None) if it doesn't resolve. `where` names the endpoint's
    home ("electrical net 'N_24V'", "link 'L1' endpoint a") so every
    message names the exact place the bad reference lives.
    """
    prefix = f"module {location} ({module.id}): {where}"

    if endpoint.port is not None:
        port = ports_by_id.get(endpoint.port)
        if port is None:
            known = sorted(ports_by_id)
            errors.append(f"{prefix} references unknown port {endpoint.port!r} (declared ports: {known})")
            return None
        return _Terminal(
            port_id=port.id,
            domain=port.domain,
            refdes=None,
            ref=None,
            pin=endpoint.pin,
            role=port.role,
            protocol=port.protocol,
            is_comms=False,
        )

    if endpoint.refdes is not None:
        if endpoint.refdes not in declared_refdes:
            errors.append(
                f"{prefix} references unknown refdes {endpoint.refdes!r} "
                f"(declared components: {sorted(declared_refdes)})"
            )
            return None
        component = resolved_by_refdes.get(endpoint.refdes)
        if component is None:
            # The component itself already failed to resolve in
            # _check_module_components -- don't pile a second refusal on it.
            return None

        electrical, comms, declares_any = _connectors_of(component)
        if not declares_any:
            errors.append(
                f"{prefix} references refdes {endpoint.refdes!r} ({component.id}), "
                "which declares no connectors -- its pinout is missing (ADR-0015)"
            )
            return None

        if endpoint.ref is None:
            errors.append(
                f"{prefix} references refdes {endpoint.refdes!r} ({component.id}) "
                "without naming a connector `ref`"
            )
            return None

        if endpoint.ref in electrical:
            pins = electrical[endpoint.ref]
            if endpoint.pin is not None and endpoint.pin not in pins:
                errors.append(
                    f"{prefix} references pin {endpoint.pin!r} not on connector {endpoint.ref!r} "
                    f"of refdes {endpoint.refdes!r} ({component.id}) (declared pins: {sorted(pins)})"
                )
                return None
            return _Terminal(
                port_id=None,
                domain=None,
                refdes=endpoint.refdes,
                ref=endpoint.ref,
                pin=endpoint.pin,
                role=None,
                protocol=None,
                is_comms=False,
            )

        if endpoint.ref in comms:
            cc = comms[endpoint.ref]
            if endpoint.pin is not None:
                errors.append(
                    f"{prefix} references pin {endpoint.pin!r} on comms connector {endpoint.ref!r} "
                    f"of refdes {endpoint.refdes!r} ({component.id}), which declares no pins"
                )
                return None
            protocol = cc.protocol or (component.comms.protocol if component.comms else None)
            return _Terminal(
                port_id=None,
                domain=None,
                refdes=endpoint.refdes,
                ref=endpoint.ref,
                pin=None,
                role=cc.role,
                protocol=protocol,
                is_comms=True,
            )

        known = sorted([*electrical, *comms])
        errors.append(
            f"{prefix} references unknown connector {endpoint.ref!r} on refdes {endpoint.refdes!r} "
            f"({component.id}) (declared connectors: {known})"
        )
        return None

    errors.append(f"{prefix} references neither a port nor a component refdes")
    return None


def _check_ethercat_chain(
    location: str,
    module: "Module",
    link_terminals: list[tuple[str, _Terminal, _Terminal]],
    errors: list[str],
) -> None:
    """ADR-0015 Decision 2: derive the chain by walking the links and refuse
    a chain that (a) reaches no master, (b) loops, or (c) leaves a slave_out
    dangling with devices beyond it (a slave the walk never reaches).

    The order is derived here, walking each link's two terminals -- nothing
    is read from a stored index, because none exists.
    """
    # Chain-participating terminals only (roles master/slave_in/slave_out),
    # and only those actually referenced by a link -- an unwired component is
    # not a broken chain.
    nodes: dict[tuple, _Terminal] = {}
    edges: list[tuple[tuple, tuple]] = []
    for _link_id, ta, tb in link_terminals:
        if ta.role in _CHAIN_ROLES and tb.role in _CHAIN_ROLES:
            nodes[ta.key] = ta
            nodes[tb.key] = tb
            edges.append((ta.key, tb.key))

    if not nodes:
        return

    # Internal pass-through: a device forwards the chain from its IN to its
    # OUT, so a refdes carrying both a slave_in and a slave_out node is one
    # edge between them (this is what lets the walk continue downstream).
    by_refdes: dict[str, dict[str, tuple]] = {}
    for key, term in nodes.items():
        if term.refdes is not None and term.role in ("slave_in", "slave_out"):
            by_refdes.setdefault(term.refdes, {})[term.role] = key
    for roles in by_refdes.values():
        if "slave_in" in roles and "slave_out" in roles:
            edges.append((roles["slave_in"], roles["slave_out"]))

    # Anchors -- where the chain is allowed to reach "the master side": a
    # real master terminal, or one of the module's own slave_in PORTS (its
    # uplink to an upstream master that lives one layer up, in the cell).
    anchors = {
        key
        for key, term in nodes.items()
        if term.role == "master" or (term.port_id is not None and term.role == "slave_in")
    }
    slave_devices = {term.refdes for term in nodes.values() if term.refdes is not None}

    if not anchors:
        some_slave = sorted(slave_devices)
        errors.append(
            f"module {location} ({module.id}): EtherCAT chain reaches no master "
            f"(no master terminal and no slave_in port anchors slaves {some_slave})"
        )
        return

    # Loop detection over the full edge set (internal + external) via
    # union-find: an edge joining two already-connected nodes closes a loop.
    parent: dict[tuple, tuple] = {key: key for key in nodes}

    def find(x: tuple) -> tuple:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra == rb:
            errors.append(
                f"module {location} ({module.id}): EtherCAT chain loops back on itself "
                f"(closing edge {a} -- {b})"
            )
            return
        parent[ra] = rb

    # Reachability: walk out from every anchor; any slave device not reached
    # sits beyond a break (a dangling slave_out, or a chain that never left
    # the master).
    adj: dict[tuple, list[tuple]] = {key: [] for key in nodes}
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
    reached: set[tuple] = set()
    stack = [a for a in anchors]
    while stack:
        cur = stack.pop()
        if cur in reached:
            continue
        reached.add(cur)
        stack.extend(adj[cur])

    unreached = sorted(
        {term.refdes for key, term in nodes.items() if key not in reached and term.refdes is not None}
    )
    if unreached:
        errors.append(
            f"module {location} ({module.id}): EtherCAT chain leaves slave(s) {unreached} unreached "
            "(a slave_out is left dangling with devices beyond it)"
        )


def check_module_connectivity(
    location: str,
    module: "Module",
    resolved_by_refdes: "dict[str, Component]",
    errors: list[str],
) -> None:
    """ADR-0015 structural refusals for a module's nets/links/ports.

    `resolved_by_refdes` is the very map `_check_module_components` already
    built while checking the module's `components:` list -- reused here so a
    component is resolved once, off the same components search path, never
    twice. A refdes that is declared but failed to resolve is absent from
    the map; endpoints naming it are skipped (its own refusal is already
    recorded), never double-reported.
    """
    nets = module.nets
    if nets is None and not module.links and not module.ports:
        return

    ports_by_id = {p.id: p for p in module.ports}
    declared_refdes = [mc.refdes for mc in module.components]

    used_ports: set[str] = set()
    # (pin_key) -> set of net ids it appears on, for the "pin on more than
    # one net" membership refusal.
    pin_nets: dict[tuple, set[str]] = {}
    pin_desc: dict[tuple, str] = {}

    def note_usage(term: _Terminal | None) -> None:
        if term is not None and term.port_id is not None:
            used_ports.add(term.port_id)

    # --- nets: electrical + pneumatic ---
    net_domains: list[tuple[str, tuple["Net", ...]]] = []
    if nets is not None:
        net_domains = [("electrical", nets.electrical), ("pneumatic", nets.pneumatic)]

    for domain, net_list in net_domains:
        for net in net_list:
            if len(net.endpoints) < 2:
                errors.append(
                    f"module {location} ({module.id}): {domain} net {net.id!r} has "
                    f"{len(net.endpoints)} endpoint(s); a net needs at least 2"
                )
            for endpoint in net.endpoints:
                where = f"{domain} net {net.id!r}"
                term = _resolve_endpoint(
                    location, module, where, endpoint, ports_by_id, declared_refdes, resolved_by_refdes, errors
                )
                note_usage(term)
                if term is not None and term.pin_key is not None:
                    pin_nets.setdefault(term.pin_key, set()).add(net.id)
                    pin_desc.setdefault(term.pin_key, _describe_pin(term))

    # --- pin on more than one net ---
    for pin_key, net_ids in pin_nets.items():
        if len(net_ids) > 1:
            errors.append(
                f"module {location} ({module.id}): pin {pin_desc[pin_key]} appears on more than "
                f"one net ({', '.join(sorted(net_ids))})"
            )

    # --- links: communication ---
    link_terminals: list[tuple[str, _Terminal, _Terminal]] = []
    for link in module.links:
        ta = _resolve_endpoint(
            location, module, f"link {link.id!r} endpoint a", link.a, ports_by_id, declared_refdes, resolved_by_refdes, errors
        )
        tb = _resolve_endpoint(
            location, module, f"link {link.id!r} endpoint b", link.b, ports_by_id, declared_refdes, resolved_by_refdes, errors
        )
        note_usage(ta)
        note_usage(tb)

        # A link is communication: an endpoint on a module port must be on a
        # communication port, never an electrical/pneumatic one.
        for label, term in (("a", ta), ("b", tb)):
            if term is not None and term.port_id is not None and term.domain != "communication":
                errors.append(
                    f"module {location} ({module.id}): link {link.id!r} endpoint {label} references "
                    f"port {term.port_id!r} (domain {term.domain!r}), which is not a communication port"
                )

        _check_link_protocol(location, module, link, ta, tb, errors)

        if ta is not None and tb is not None:
            link_terminals.append((link.id, ta, tb))

    _check_ethercat_chain(location, module, link_terminals, errors)

    # --- module port declared but connected to nothing ---
    for port in module.ports:
        if port.id not in used_ports:
            errors.append(
                f"module {location} ({module.id}): port {port.id!r} is declared but connected to no net or link"
            )


def _describe_pin(term: _Terminal) -> str:
    if term.port_id is not None:
        return f"{term.pin!r} of port {term.port_id!r}"
    return f"{term.pin!r} of connector {term.ref!r} on refdes {term.refdes!r}"


def _check_link_protocol(
    location: str,
    module: "Module",
    link: "Link",
    ta: _Terminal | None,
    tb: _Terminal | None,
    errors: list[str],
) -> None:
    """Refuse a link whose two ends -- and its own declared `protocol` --
    don't agree. Only KNOWN protocols count: an endpoint whose component
    connector states no per-connector protocol contributes nothing, rather
    than a false mismatch (ADR-0014: absence is not a value)."""
    seen: dict[str, str] = {}
    candidates = [("link", link.protocol)]
    if ta is not None:
        candidates.append(("endpoint a", ta.protocol))
    if tb is not None:
        candidates.append(("endpoint b", tb.protocol))
    for source, protocol in candidates:
        if protocol is not None:
            seen[source] = protocol
    distinct = set(seen.values())
    if len(distinct) > 1:
        detail = ", ".join(f"{src}={proto!r}" for src, proto in seen.items())
        errors.append(
            f"module {location} ({module.id}): link {link.id!r} connects mismatched protocols ({detail})"
        )
