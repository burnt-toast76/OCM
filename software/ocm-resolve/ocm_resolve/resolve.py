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

    loaded: dict[str, ResolvedModuleInstance] = {}
    for mi in cell.modules:
        module, mod_errors = find_module(mi.module, search_path)
        errors.extend(mod_errors)
        if module is not None:
            loaded[mi.instance] = ResolvedModuleInstance(instance=mi, module=module)
            resolved_components = _check_module_components(mi.instance, module, components_search_path, errors)
            check_module_connectivity(mi.instance, module, resolved_components, errors)

    resolved = _resolve_mounts(loaded, errors)

    for location, step in iter_op_steps(cell.plan):
        _check_op_step(location, step, resolved, errors)

    if errors:
        raise CellResolutionError(cell.id, errors)

    assert base_module is not None  # no base errors above => it resolved
    return ResolvedCell(cell=cell, base=base_module, instances=resolved)
