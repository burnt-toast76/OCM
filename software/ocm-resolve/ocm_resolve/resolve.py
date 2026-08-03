# SPDX-License-Identifier: AGPL-3.0-or-later
"""Resolve a Cell against a module search path into a ResolvedCell.

Second stage of the pipeline (see ROADMAP Step 1): ocm-core loads and
validates individual manifests in isolation; ocm-resolve cross-references a
cell's module instances, its plan, and its mount chain against those
manifests. It does not touch geometry, collision, or Tesseract -- that is
ocm-generator's job, once this stage says a cell is internally consistent.

Like ocm_core's manifest validation, resolution collects every violation it
finds rather than raising on the first one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ocm_core import Capability, Cell, Module, ModuleInstance, Parameter

from .connectivity import check_module_connectivity
from .errors import CellResolutionError
from .plan_walk import iter_op_steps
from .search import SearchPath, find_component, find_module

if TYPE_CHECKING:
    from ocm_core import Component


@dataclass(frozen=True)
class ResolvedModuleInstance:
    """A cell's module instance, with its manifest loaded and its mount
    target (if any) resolved to another ResolvedModuleInstance.
    """

    instance: ModuleInstance
    module: Module
    mounted_on: ResolvedModuleInstance | None = None

    @property
    def name(self) -> str:
        return self.instance.instance


@dataclass(frozen=True)
class ResolvedCell:
    cell: Cell
    base: Module
    instances: dict[str, ResolvedModuleInstance] = field(default_factory=dict)

    def instance(self, name: str) -> ResolvedModuleInstance:
        try:
            return self.instances[name]
        except KeyError:
            raise KeyError(f"cell {self.cell.id} has no resolved instance {name!r}") from None


def _find_capability(module: Module, op_name: str) -> Capability | None:
    for cap in module.capabilities:
        if cap.name == op_name:
            return cap
    return None


# pose6d/vec3/struct (spec/CHANGELOG.md v1.1). Bounds (min/max) are a
# scalar concept -- a six-float pose or a struct blob has no ordering to
# check a number against. These are opaque to this function: known-name
# checking still applies (see _check_op_step), but never a bounds check.
_COMPOSITE_TYPES = ("pose6d", "vec3", "struct")


def _check_param(
    location: str,
    op_name: str,
    param_name: str,
    value: Any,
    param: Parameter,
    errors: list[str],
) -> None:
    if param.type in _COMPOSITE_TYPES:
        return
    if param.type in ("number", "integer"):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(
                f"{location}: op {op_name!r} param {param_name!r} = {value!r} is not numeric"
            )
            return
        if param.min is not None and value < param.min:
            errors.append(
                f"{location}: op {op_name!r} param {param_name!r} = {value} "
                f"is below the declared minimum {param.min}"
            )
        if param.max is not None and value > param.max:
            errors.append(
                f"{location}: op {op_name!r} param {param_name!r} = {value} "
                f"exceeds the declared maximum {param.max}"
            )
    elif param.type == "enum":
        if param.values is not None and value not in param.values:
            errors.append(
                f"{location}: op {op_name!r} param {param_name!r} = {value!r} "
                f"is not one of {list(param.values)}"
            )


def _check_op_step(
    location: str,
    step: dict[str, Any],
    instances: dict[str, ResolvedModuleInstance],
    errors: list[str],
) -> None:
    instance_name = step["module"]
    op_name = step["op"]

    resolved = instances.get(instance_name)
    if resolved is None:
        errors.append(f"{location}: references unknown module instance {instance_name!r}")
        return

    capability = _find_capability(resolved.module, op_name)
    if capability is None:
        known = sorted(c.name for c in resolved.module.capabilities)
        errors.append(
            f"{location}: {instance_name} ({resolved.module.id}) has no op {op_name!r} "
            f"(known ops: {known})"
        )
        return

    for param_name, value in step.get("params", {}).items():
        param = capability.parameters.get(param_name)
        if param is None:
            known = sorted(capability.parameters)
            errors.append(
                f"{location}: op {op_name!r} has no parameter {param_name!r} "
                f"(known parameters: {known})"
            )
            continue
        _check_param(location, op_name, param_name, value, param, errors)


def _resolve_mounts(
    loaded: dict[str, ResolvedModuleInstance],
    errors: list[str],
) -> dict[str, ResolvedModuleInstance]:
    # Recursive + memoized so each instance is built exactly once: a mount
    # chain (A on B on C) must have A.mounted_on be the very same object as
    # resolved["B"], not a separate pre-resolution copy of it. `building`
    # guards against a mount.on cycle recursing forever.
    resolved: dict[str, ResolvedModuleInstance] = {}
    building: set[str] = set()

    def build(name: str) -> ResolvedModuleInstance:
        if name in resolved:
            return resolved[name]

        ri = loaded[name]
        mount = ri.instance.mount
        mounted_on: ResolvedModuleInstance | None = None
        if mount is not None and mount.on is not None:
            target_name, sep, attachment = mount.on.partition(".")
            if not sep or not target_name or not attachment:
                errors.append(
                    f"module {name}: malformed mount.on {mount.on!r} "
                    "(expected 'instance.attachment')"
                )
            elif target_name not in loaded:
                errors.append(
                    f"module {name}: mounts on unknown module instance {target_name!r} "
                    f"(mount.on={mount.on!r})"
                )
            elif target_name in building:
                errors.append(f"module {name}: mount.on chain cycles back through {target_name!r}")
            else:
                building.add(name)
                mounted_on = build(target_name)
                building.discard(name)

        final = ResolvedModuleInstance(instance=ri.instance, module=ri.module, mounted_on=mounted_on)
        resolved[name] = final
        return final

    for name in loaded:
        build(name)
    return resolved


def _check_module_components(
    location: str,
    module: Module,
    components_search_path: SearchPath | None,
    errors: list[str],
) -> "dict[str, Component]":
    """ADR-0014: a module's own `components:` list, and its signals'
    `source` provenance into that list, are cross-file references exactly
    like a cell's module refs and mount chain -- checked here, once, the
    same way. Unknown component ids/revisions, duplicate refdes, and a
    `source` naming a signal the referenced component doesn't declare are
    all refused; a module with no `components:` list is untouched (ADR-0014:
    "a module with no components list stays valid").

    Returns the refdes -> resolved Component map it built along the way, so
    ADR-0015's connectivity check can reuse it (same components search path,
    each component resolved exactly once) rather than resolving a second
    time. A declared refdes that failed to resolve is simply absent.
    """
    resolved_by_refdes: dict[str, Component] = {}
    if not module.components:
        return resolved_by_refdes

    seen_refdes: set[str] = set()
    for mc in module.components:
        if mc.refdes in seen_refdes:
            errors.append(f"module {location} ({module.id}): duplicate component refdes {mc.refdes!r}")
            continue
        seen_refdes.add(mc.refdes)

        if components_search_path is None:
            errors.append(
                f"module {location} ({module.id}): declares component {mc.refdes} ({mc.ref}) "
                "but no components search path was given"
            )
            continue

        component, component_errors = find_component(mc.ref, components_search_path)
        if component_errors:
            errors.extend(f"module {location} ({module.id}): component {mc.refdes}: {e}" for e in component_errors)
        if component is not None:
            resolved_by_refdes[mc.refdes] = component

    if module.comms is None:
        return resolved_by_refdes

    for signal in module.comms.signals:
        if signal.source is None:
            continue
        refdes, sep, device_signal_name = signal.source.partition(".")
        if not sep or not refdes or not device_signal_name:
            errors.append(
                f"module {location} ({module.id}): signal {signal.name!r} has a malformed source "
                f"{signal.source!r} (expected 'REFDES.signal_name')"
            )
            continue
        if refdes not in seen_refdes:
            errors.append(
                f"module {location} ({module.id}): signal {signal.name!r} source={signal.source!r} "
                f"references unknown refdes {refdes!r} (declared components: {sorted(seen_refdes)})"
            )
            continue
        component = resolved_by_refdes.get(refdes)
        if component is None:
            continue  # the component itself already failed to resolve above -- don't pile on
        if component.comms is None or component.comms.signal(device_signal_name) is None:
            known = sorted(s.name for s in component.comms.signals) if component.comms else []
            errors.append(
                f"module {location} ({module.id}): signal {signal.name!r} source={signal.source!r} "
                f"references unknown signal {device_signal_name!r} on component {component.id} "
                f"(known signals: {known})"
            )

    return resolved_by_refdes


_LHS_IDENT = re.compile(r"^\s*([a-z][a-z0-9_]*)")


def _condition_lhs(expr: str) -> str:
    """The signal/requirement NAME a condition reads -- the leading
    identifier, whatever comparison follows it.

    The coordinator's own grammar is `name == literal` (ADR-0023 Decision 7),
    but this refusal is about whether the *name* is declared, not which
    operator compares it. Some committed manifests predate the `==`-only
    grammar and use `>` (dh200's `flow_actual > 0`); extracting the leading
    identifier means those still resolve against a real signal instead of
    being misreported as an unknown one. A grammar the coordinator can't yet
    evaluate is a separate concern (the runtime `PreconditionError` backstop),
    not a OCM_CONDITION_UNKNOWN_SIGNAL. Signal/requirement names match
    `^[a-z][a-z0-9_]*`, so the leading identifier is unambiguous.
    """
    m = _LHS_IDENT.match(expr)
    return m.group(1) if m else expr.strip()


def _check_module_capabilities(location: str, module: Module, errors: list[str]) -> None:
    """ADR-0023 module-scoped refusals, surfaced by validate_module and
    (per instance) set_plan:

    - OCM_CONDITION_UNKNOWN_SIGNAL: a pre/postcondition names something that is
      neither a `comms.signals` name nor a declared `requires` key. This is
      the resolve-time replacement for the coordinator's runtime
      `PreconditionError` (Decision 5); a manifest that would fault the
      coordinator on first contact must not validate clean.
    - OCM_TIMEOUT_DISPOSITION_CONFLICT: `on_timeout: hold` on a capability whose
      module is not abort-safe -- a held op cannot resume a compromised part
      (Decision 6).
    """
    signal_names = {s.name for s in module.comms.signals} if module.comms else set()
    abort_safe = module.state_machine.abort_safe

    for cap in module.capabilities:
        known = signal_names | set(cap.requires)
        for kind, conditions in (("precondition", cap.preconditions), ("postcondition", cap.postconditions)):
            for expr in conditions:
                name = _condition_lhs(expr)
                if name and name not in known:
                    errors.append(
                        f"module {location} ({module.id}): capability {cap.name!r} {kind} {expr!r} "
                        f"references {name!r}, which is neither a comms signal nor a declared requires key "
                        f"(known: {sorted(known)})"
                    )
        if cap.on_timeout == "hold" and abort_safe is False:
            errors.append(
                f"module {location} ({module.id}): capability {cap.name!r} declares on_timeout 'hold' "
                f"but state_machine.abort_safe is false -- a held op cannot resume a compromised part"
            )


def _input_bool_instances(loaded: dict[str, ResolvedModuleInstance]) -> list[str]:
    """Instance names whose module declares at least one input bool signal --
    the candidate targets a `requires` key can be bound to. Named in the
    OCM_REQUIREMENT_UNBOUND hint so the human's next move is obvious."""
    out = []
    for name, ri in loaded.items():
        comms = ri.module.comms
        if comms and any(s.direction == "input" and s.type == "bool" for s in comms.signals):
            out.append(name)
    return sorted(out)


def _check_requirement_bindings(
    cell: Cell, loaded: dict[str, ResolvedModuleInstance], errors: list[str]
) -> None:
    """ADR-0023 Decision 4, cell-scoped: every `requires` key a placed
    instance's capabilities declare must be bound by the cell to a real
    `instance.signal`.

    - OCM_REQUIREMENT_UNBOUND: the instance carries a capability with a requires
      key the cell binds nothing to.
    - OCM_REQUIREMENT_UNKNOWN_TARGET: a binding names an instance not in the cell,
      or a signal that instance doesn't declare.
    """
    for name, ri in loaded.items():
        bindings = cell.module(name).requires
        for cap in ri.module.capabilities:
            for req_name in cap.requires:
                target = bindings.get(req_name)
                if target is None:
                    candidates = _input_bool_instances(loaded)
                    errors.append(
                        f"cell {cell.id}: instance {name} ({ri.module.id}) capability {cap.name!r} "
                        f"requires {req_name!r}, which the cell binds to nothing "
                        f"(instances declaring an input bool: {candidates})"
                    )
                    continue
                target_instance, sep, target_signal = target.partition(".")
                if not sep or not target_instance or not target_signal:
                    errors.append(
                        f"cell {cell.id}: instance {name} binds requirement {req_name!r} to malformed "
                        f"target {target!r} (expected 'instance.signal')"
                    )
                    continue
                target_ri = loaded.get(target_instance)
                if target_ri is None:
                    errors.append(
                        f"cell {cell.id}: instance {name} binds requirement {req_name!r} to {target!r}, "
                        f"but no instance {target_instance!r} is in this cell (instances: {sorted(loaded)})"
                    )
                    continue
                target_signals = {s.name for s in target_ri.module.comms.signals} if target_ri.module.comms else set()
                if target_signal not in target_signals:
                    errors.append(
                        f"cell {cell.id}: instance {name} binds requirement {req_name!r} to {target!r}, "
                        f"but {target_instance} ({target_ri.module.id}) declares no signal {target_signal!r} "
                        f"(signals: {sorted(target_signals)})"
                    )


def _check_collision_geometry(
    location: str,
    module: Module,
    resolved_components: dict[str, "Component"],
    errors: list[str],
) -> None:
    """ADR-0027 D5 manifest-level checks, in `derived` mode only: the resolver
    builds the collision proxy from posed component envelopes plus structure
    primitives, and REFUSES instead of approximating -- a partial collision
    proxy looks like a collision model, is smaller than the machine, and
    nothing says so.

    - OCM_DERIVED_POSE_MISSING: a component instance with no `pose`.
    - OCM_DERIVED_ENVELOPE_MISSING: a referenced component with no (or an
      incomplete) `geometry.envelope` -- datasheet-answerable transcription
      work, so the refusal is the completion list (ADR-0014).
    - OCM_UNIT_UNRECOGNISED: an envelope/structure unit string outside
      ocm_core.units' explicit table -- never guessed, never normalised.

    File-dependent checks (authored mesh existence, link-in-fragment,
    containment) live in the generator's collision_geometry module, reached
    through validate_module -- they need the module's directory, which this
    manifest-only pass deliberately doesn't.
    """
    from ocm_core.units import UnknownUnitError, length_to_mm

    if module.mechanical.geometry.collision_source != "derived":
        return

    for mc in module.components:
        if mc.pose is None:
            errors.append(
                f"module {location} ({module.id}): collision_source 'derived' but component "
                f"{mc.refdes} has no pose -- the resolver refuses instead of approximating"
            )
        comp = resolved_components.get(mc.refdes)
        if comp is None:
            continue  # unresolved ref already errored in _check_module_components
        envelope = comp.geometry.envelope if comp.geometry else None
        if envelope is None or None in (envelope.length, envelope.width, envelope.height, envelope.units):
            errors.append(
                f"module {location} ({module.id}): collision_source 'derived' but component "
                f"{mc.refdes} ({comp.id}) declares no complete geometry.envelope -- "
                "datasheet-answerable transcription work, not design"
            )
        elif envelope.units is not None:
            try:
                length_to_mm(1.0, envelope.units)
            except UnknownUnitError as e:
                errors.append(
                    f"module {location} ({module.id}): component {mc.refdes} envelope unit "
                    f"{envelope.units!r} is unrecognised ({e.known and 'known: ' + str(list(e.known))})"
                )

    for sp in module.mechanical.structure:
        if sp.units is not None:
            try:
                length_to_mm(1.0, sp.units)
            except UnknownUnitError as e:
                errors.append(
                    f"module {location} ({module.id}): structure {sp.id} unit {sp.units!r} "
                    f"is unrecognised ({'known: ' + str(list(e.known))})"
                )


def resolve_module(module: Module, components_search_path: SearchPath | None = None) -> list[str]:
    """Cross-check ONE module in isolation, exactly the way resolve_cell does
    for each instance it loads: its `components:` list and signal `source`
    provenance (ADR-0014) and its own nets/links/ports connectivity
    (ADR-0015), against `components_search_path`. Returns every violation
    found -- an empty list means the module is internally consistent.

    This is the module-scoped slice of resolve_cell, for a caller (ocm-api's
    `validate_module`, ADR-0016) that must see connectivity refusals while a
    module is being authored, before any cell places it. It reuses the same
    components-search-path plumbing `_check_module_components` already threads
    -- there is no second path.
    """
    errors: list[str] = []
    resolved_components = _check_module_components(module.id, module, components_search_path, errors)
    check_module_connectivity(module.id, module, resolved_components, errors)
    _check_module_capabilities(module.id, module, errors)
    _check_collision_geometry(module.id, module, resolved_components, errors)
    return errors


def resolve_cell(cell: Cell, search_path: SearchPath, components_search_path: SearchPath | None = None) -> ResolvedCell:
    """Load every module a cell references, and cross-check its plan and
    mount chain against those manifests.

    Raises CellResolutionError (carrying every violation found) if any
    referenced module can't be found, any plan step names an unknown op or
    an out-of-bounds/undeclared param, any mount.on chain is dangling, or
    (ADR-0014) any module's own `components:` list/signal `source`
    provenance doesn't check out against `components_search_path`, or
    (ADR-0015) any module's own nets/links/ports connectivity doesn't
    resolve against those components' transcribed connectors/pins.
    """
    errors: list[str] = []

    base_module, base_errors = find_module(cell.base.module, search_path)
    errors.extend(base_errors)
    if base_module is not None:
        resolved_components = _check_module_components("base", base_module, components_search_path, errors)
        check_module_connectivity("base", base_module, resolved_components, errors)
        _check_module_capabilities("base", base_module, errors)
        _check_collision_geometry("base", base_module, resolved_components, errors)

    loaded: dict[str, ResolvedModuleInstance] = {}
    for mi in cell.modules:
        module, mod_errors = find_module(mi.module, search_path)
        errors.extend(mod_errors)
        if module is not None:
            loaded[mi.instance] = ResolvedModuleInstance(instance=mi, module=module)
            resolved_components = _check_module_components(mi.instance, module, components_search_path, errors)
            check_module_connectivity(mi.instance, module, resolved_components, errors)
            _check_collision_geometry(mi.instance, module, resolved_components, errors)
            _check_module_capabilities(mi.instance, module, errors)

    _check_requirement_bindings(cell, loaded, errors)

    resolved = _resolve_mounts(loaded, errors)

    for location, step in iter_op_steps(cell.plan):
        _check_op_step(location, step, resolved, errors)

    if errors:
        raise CellResolutionError(cell.id, errors)

    assert base_module is not None  # no base errors above => it resolved
    return ResolvedCell(cell=cell, base=base_module, instances=resolved)
