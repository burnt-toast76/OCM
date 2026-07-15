# SPDX-License-Identifier: AGPL-3.0-or-later
from ocm_core.cell import Cell
from ocm_resolve import ResolvedCell, resolve_cell

from .conftest import build_cell_dict


def test_resolves_a_consistent_cell(search_root, tiny_cell):
    resolved = resolve_cell(tiny_cell, search_root)

    assert isinstance(resolved, ResolvedCell)
    assert resolved.cell is tiny_cell
    assert resolved.base.id == "com.example.base.tiny"
    assert set(resolved.instances) == {"robot1", "tool1"}


def test_resolved_instance_carries_the_loaded_module(search_root, tiny_cell):
    resolved = resolve_cell(tiny_cell, search_root)

    tool1 = resolved.instance("tool1")
    assert tool1.name == "tool1"
    assert tool1.module.id == "com.example.tool.tiny"
    assert tool1.module.revision == "1.0.0"
    assert tool1.module.capability("drive_screw").parameters["torque_nm"].max == 5.0


def test_mount_on_chain_is_resolved_to_the_target_instance(search_root, tiny_cell):
    resolved = resolve_cell(tiny_cell, search_root)

    robot1 = resolved.instance("robot1")
    tool1 = resolved.instance("tool1")
    assert tool1.mounted_on is robot1
    assert robot1.mounted_on is None  # robot1 mounts by station/pose, not 'on'


def test_mount_on_chain_two_levels_deep_shares_the_same_resolved_object(search_root):
    # tool2 is mounted on tool1, which is mounted on robot1. tool2.mounted_on
    # must be the exact same object as resolved.instance("tool1") -- which
    # in turn must be the same object as tool1.mounted_on's owner chain.
    data = build_cell_dict(
        modules=[
            {
                "instance": "robot1",
                "module": "com.example.robot.tiny@1.0.0",
                "mount": {"station": [100, 100]},
            },
            {
                "instance": "tool1",
                "module": "com.example.tool.tiny@1.0.0",
                "mount": {"on": "robot1.flange"},
            },
            {
                "instance": "tool2",
                "module": "com.example.tool.tiny@1.0.0",
                "mount": {"on": "tool1.aux_port"},
            },
        ],
        plan=[],
    )
    cell = Cell.from_dict(data)

    resolved = resolve_cell(cell, search_root)

    tool1 = resolved.instance("tool1")
    tool2 = resolved.instance("tool2")
    assert tool2.mounted_on is tool1
    assert tool1.mounted_on is resolved.instance("robot1")
