# SPDX-License-Identifier: AGPL-3.0-or-later
"""Walk a cell's `plan` far enough to find every op-step.

`plan` is the generator's planner DSL (ocm_core.Cell keeps it as raw
data -- see cell.py's module docstring). This walk does not interpret
sequencing: `for_each`, `binds`, `at`, and `on_fail`'s recovery semantics
all stay the planner's job. It only needs to find every dict that names a
(module, op) pair, at any nesting depth under 'sequence' / 'on_fail', so
that op/param checking can see every op-step the plan actually invokes.
"""

from __future__ import annotations

from typing import Any, Iterator

_NESTED_KEYS = ("sequence", "on_fail")


def iter_op_steps(plan: list[Any], path: str = "plan") -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield (location, step) for every dict in `plan` with both 'module' and 'op'."""
    for i, item in enumerate(plan):
        item_path = f"{path}[{i}]"
        if not isinstance(item, dict):
            continue
        if "module" in item and "op" in item:
            yield item_path, item
        for key in _NESTED_KEYS:
            nested = item.get(key)
            if isinstance(nested, list):
                yield from iter_op_steps(nested, f"{item_path}.{key}")
