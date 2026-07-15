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
from typing import Any

from ocm_core import Capability, Cell, Module, ModuleInstance, Parameter

from .errors import CellResolutionError
from .plan_walk import iter_op_steps
from .search import SearchPath, find_module


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


def _check_param(
    location: str,
    op_name: str,
    param_name: str,
    value: Any,
    param: Parameter,
    errors: list[str],
) -> None:
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


def resolve_cell(cell: Cell, search_path: SearchPath) -> ResolvedCell:
    """Load every module a cell references, and cross-check its plan and
    mount chain against those manifests.

    Raises CellResolutionError (carrying every violation found) if any
    referenced module can't be found, any plan step names an unknown op or
    an out-of-bounds/undeclared param, or any mount.on chain is dangling.
    """
    errors: list[str] = []

    base_module, base_errors = find_module(cell.base.module, search_path)
    errors.extend(base_errors)

    loaded: dict[str, ResolvedModuleInstance] = {}
    for mi in cell.modules:
        module, mod_errors = find_module(mi.module, search_path)
        errors.extend(mod_errors)
        if module is not None:
            loaded[mi.instance] = ResolvedModuleInstance(instance=mi, module=module)

    resolved = _resolve_mounts(loaded, errors)

    for location, step in iter_op_steps(cell.plan):
        _check_op_step(location, step, resolved, errors)

    if errors:
        raise CellResolutionError(cell.id, errors)

    assert base_module is not None  # no base errors above => it resolved
    return ResolvedCell(cell=cell, base=base_module, instances=resolved)
