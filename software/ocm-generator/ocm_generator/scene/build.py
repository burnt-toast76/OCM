# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compose a ResolvedCell into a single combined URDF (Scene).

Second half of ADR-0007's thesis ("cell.yaml compiles directly into a
Tesseract scene graph"). Every resolved instance's urdf_fragment gets
namespaced (see .urdf) and spliced into one combined URDF, attached either:

- to `world`, at the xyz_mm/rpy_deg given by mount.pose (converted to the
  metres/radians URDF expects -- the schema's own Frame docstring says
  "the loader converts"; this is that loader), or
- to another instance's own named attachment link, for mount.on chains
  (e.g. sd1 on "robot1.flange"). This is a fixed joint with an IDENTITY
  local offset, not a computed world-frame pose: sd50's own manifest notes
  its `origin` frame IS the mounting interface, and more fundamentally a
  tool's world position on a moving robot depends on live joint state, so
  it has to be real kinematic parenting, not a static number.

mount.on's *target instance* existing is already guaranteed by ocm_resolve
(ResolvedModuleInstance.mounted_on) -- this module doesn't re-check that.
What it adds is the one thing ocm_resolve has no way to know: whether the
named *attachment link* actually exists in the target's own urdf_fragment.

Two more things happen here once the geometry is assembled:

- Each instance's optional `joint_state` (cell.yaml, radians, applied as-is
  -- unlike mount.pose there's no mm/deg convention to convert, matching
  how the rest of the robotics ecosystem writes joint values) is validated
  against that instance's own fragment (unknown joint name, or a joint
  that isn't revolute/continuous/prismatic, is a collected violation) and
  namespaced onto Scene.joint_state.
- Workspace containment (see .containment): does every non-base, non-robot
  instance's world AABB stay within the base module's own footprint.

Neither of those -- nor anything else in this module -- touches
tesseract_robotics. A `Scene` is plain data (a URDF string plus the
bookkeeping to make sense of it); building an actual Tesseract Environment
or running a collision check from it is .collision's job, imported lazily
and only when needed, so the base install of ocm-generator works without
Tesseract installed at all (see pyproject.toml's `tesseract` extra).

Like ocm-core and ocm-resolve, this collects every violation before
raising, rather than stopping at the first.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ocm_core import Module
from ocm_resolve import ResolvedCell

from .collision_geometry import derived_collision_elements
from .containment import check_workspace_containment
from .errors import FragmentError, SceneBuildError
from .kinematics import JointState
from .urdf import TESSERACT_NS, load_fragment, namespace_fragment

WORLD_LINK = "world"
_BASE_KEY = "__base__"


@dataclass(frozen=True)
class SceneInstance:
    """Where one resolved instance ended up in the combined scene graph."""

    name: str
    root_link: str
    parent_link: str
    joint_name: str
    # Every namespaced link this instance contributed (root_link included) --
    # lets a consumer (the debug viewer) map an arbitrary link name in the
    # composed URDF back to the instance that owns it.
    link_names: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Scene:
    urdf_xml: str
    base: SceneInstance
    instances: dict[str, SceneInstance] = field(default_factory=dict)
    # Namespaced joint name -> radians, assembled from every instance's
    # cell.yaml joint_state. Absent joints (and every fixed joint) sit at
    # zero. What the viewer renders and the containment check evaluates.
    joint_state: JointState = field(default_factory=dict)

    def instance(self, name: str) -> SceneInstance:
        try:
            return self.instances[name]
        except KeyError:
            raise KeyError(f"scene has no instance {name!r}") from None


@dataclass
class _LoadedFragment:
    links: list[ET.Element]
    joints: list[ET.Element]
    root_link: str
    link_names: set[str]


def _mm_to_m(xyz_mm: tuple[float, float, float]) -> tuple[float, float, float]:
    return (xyz_mm[0] / 1000.0, xyz_mm[1] / 1000.0, xyz_mm[2] / 1000.0)


def _deg_to_rad(rpy_deg: tuple[float, float, float]) -> tuple[float, float, float]:
    return (math.radians(rpy_deg[0]), math.radians(rpy_deg[1]), math.radians(rpy_deg[2]))


def _fixed_joint(
    name: str,
    parent_link: str,
    child_link: str,
    xyz_m: tuple[float, float, float],
    rpy_rad: tuple[float, float, float],
) -> ET.Element:
    joint = ET.Element("joint", {"name": name, "type": "fixed"})
    ET.SubElement(joint, "parent", {"link": parent_link})
    ET.SubElement(joint, "child", {"link": child_link})
    ET.SubElement(
        joint,
        "origin",
        {
            "xyz": f"{xyz_m[0]:.9g} {xyz_m[1]:.9g} {xyz_m[2]:.9g}",
            "rpy": f"{rpy_rad[0]:.9g} {rpy_rad[1]:.9g} {rpy_rad[2]:.9g}",
        },
    )
    return joint


def _render_urdf(cell_id: str, links: list[ET.Element], joints: list[ET.Element]) -> str:
    robot = ET.Element(
        "robot",
        {
            "name": cell_id,
            "xmlns:tesseract": TESSERACT_NS,
            # Every module's collision mesh is convex or a convex decomposition
            # already (schema strongly prefers it); converting again is a no-op
            # for those and a safety net for anything that isn't.
            "tesseract:make_convex": "true",
        },
    )
    ET.SubElement(robot, "link", {"name": WORLD_LINK})
    for link in links:
        robot.append(link)
    for joint in joints:
        robot.append(joint)
    return ET.tostring(robot, encoding="unicode")


def _load_and_namespace(module: Module, prefix: str, modules_root: Path) -> _LoadedFragment:
    fragment_field = module.mechanical.geometry.urdf_fragment
    if not fragment_field:
        raise FragmentError(f"{module.id} declares no mechanical.geometry.urdf_fragment")

    fragment_path = modules_root / module.id / fragment_field
    root = load_fragment(fragment_path)
    links, joints, root_link = namespace_fragment(root, prefix, fragment_path.parent, fragment_path)
    link_names = {link.get("name") for link in links}
    return _LoadedFragment(links=links, joints=joints, root_link=root_link, link_names=link_names)


def _validate_joint_state(
    name: str,
    frag: _LoadedFragment,
    raw_joint_state: dict[str, float],
    joint_state_out: JointState,
    errors: list[str],
) -> None:
    """Namespace and validate one instance's cell.yaml joint_state against
    its own (already-namespaced) fragment joints, appending to
    `joint_state_out` and collecting any violation into `errors` -- an
    unknown joint name, or one that isn't revolute/continuous/prismatic
    (a fixed joint has no configurable position to set).
    """
    if not raw_joint_state:
        return

    joints_by_name = {j.get("name"): j for j in frag.joints}
    for joint_name, value in raw_joint_state.items():
        namespaced = f"{name}__{joint_name}"
        joint_el = joints_by_name.get(namespaced)
        if joint_el is None:
            known = sorted(j.removeprefix(f"{name}__") for j in joints_by_name)
            errors.append(f"module {name}: joint_state names unknown joint {joint_name!r} (has: {known})")
            continue
        if joint_el.get("type") == "fixed":
            errors.append(
                f"module {name}: joint_state names {joint_name!r}, which is a fixed joint (no configurable position)"
            )
            continue
        # ADR-0028 D3 retrofit: a cell-supplied joint value is the same class
        # of claim as a capability's actuation target, so it gets the same
        # limit check -- a joint driven through its own stop is a fabricated
        # machine state. Continuous joints have no limits and are exempt.
        limit_el = joint_el.find("limit")
        if joint_el.get("type") != "continuous" and limit_el is not None:
            lower_attr, upper_attr = limit_el.get("lower"), limit_el.get("upper")
            if lower_attr is not None and upper_attr is not None:
                lower, upper = float(lower_attr), float(upper_attr)
                if not (lower <= float(value) <= upper):
                    errors.append(
                        f"OCM_JOINT_STATE_OUT_OF_LIMIT: instance {name!r}: joint_state drives "
                        f"{joint_name!r} to {value}, outside its declared limit [{lower}, {upper}]"
                    )
                    continue
        joint_state_out[namespaced] = float(value)


def _inject_derived_collision(
    module: Module,
    prefix: str,
    frag: _LoadedFragment,
    components_root: Path | None,
    errors: list[str],
) -> None:
    """ADR-0027: for a `collision_source: derived` module, splice per-link
    <collision> geometry (posed component envelopes + structure primitives)
    into the already-namespaced fragment links -- the planner collides against
    what the manifest states, with no second artifact to fall out of sync.
    Completeness was refused at resolve; here a missing components root is the
    one thing left to catch (a derived module cannot build its proxy blind).
    """
    if module.mechanical.geometry.collision_source != "derived":
        return
    if components_root is None:
        errors.append(
            f"module {prefix} ({module.id}): collision_source 'derived' but build_scene was "
            "given no components root -- cannot build the collision proxy"
        )
        return

    from ocm_resolve.search import find_component

    components: dict[str, "object"] = {}
    for mc in module.components:
        comp, comp_errors = find_component(mc.ref, components_root)
        if comp is not None:
            components[mc.refdes] = comp
        else:
            errors.extend(f"module {prefix} ({module.id}): {e}" for e in comp_errors)

    links_by_name = {link.get("name"): link for link in frag.links}
    for local_link, elements in derived_collision_elements(module, components).items():
        target = frag.root_link if local_link is None else f"{prefix}__{local_link}"
        link_el = links_by_name.get(target)
        if link_el is None:
            errors.append(
                f"module {prefix} ({module.id}): derived collision targets link "
                f"{local_link!r}, absent from the urdf_fragment"
            )
            continue
        for el in elements:
            link_el.append(el)


def build_scene(
    resolved: ResolvedCell,
    modules_root: Path | str,
    components_root: Path | str | None = None,
) -> Scene:
    """Compose a resolved cell into a single combined URDF (a Scene).

    Raises SceneBuildError (carrying every violation found) if any
    instance's urdf_fragment is missing/malformed, any instance has neither
    a mount.pose nor a mount.on, any mount.on names an attachment link
    that doesn't exist on its target, any joint_state entry is invalid, or
    any non-base/non-robot instance's geometry extends past the base
    module's workspace footprint (see .containment).

    `components_root` (ADR-0027): where components/ definitions live, needed
    only to build the derived collision proxy of a `collision_source: derived`
    module. Optional so existing callers keep working -- but a derived module
    with no components root is a collected violation, never a silently
    mesh-less scene.
    """
    modules_root = Path(modules_root)
    components_root = Path(components_root) if components_root is not None else None
    errors: list[str] = []

    loaded: dict[str, _LoadedFragment] = {}

    try:
        loaded[_BASE_KEY] = _load_and_namespace(resolved.base, _BASE_KEY, modules_root)
        _inject_derived_collision(resolved.base, _BASE_KEY, loaded[_BASE_KEY], components_root, errors)
    except FragmentError as e:
        errors.append(f"base ({resolved.base.id}): {e}")

    for name, ri in resolved.instances.items():
        try:
            loaded[name] = _load_and_namespace(ri.module, name, modules_root)
            _inject_derived_collision(ri.module, name, loaded[name], components_root, errors)
        except FragmentError as e:
            errors.append(f"module {name} ({ri.module.id}): {e}")

    all_links: list[ET.Element] = []
    all_joints: list[ET.Element] = []
    instances: dict[str, SceneInstance] = {}
    base_instance: Optional[SceneInstance] = None
    joint_state: JointState = {}

    if _BASE_KEY in loaded:
        frag = loaded[_BASE_KEY]
        joint = _fixed_joint(f"{_BASE_KEY}__mount", WORLD_LINK, frag.root_link, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        all_links.extend(frag.links)
        all_joints.append(joint)
        all_joints.extend(frag.joints)
        base_instance = SceneInstance(
            name="base",
            root_link=frag.root_link,
            parent_link=WORLD_LINK,
            joint_name=joint.get("name"),
            link_names=frozenset(frag.link_names),
        )

    for name, ri in resolved.instances.items():
        if name not in loaded:
            continue  # already recorded above

        frag = loaded[name]
        mount = ri.instance.mount

        if ri.mounted_on is not None:
            target_name = ri.mounted_on.name
            # mount.on is guaranteed present and well-formed here -- ocm_resolve
            # already validated the target instance exists.
            _, _, attachment = mount.on.partition(".")
            if target_name not in loaded:
                errors.append(
                    f"module {name}: cannot attach on {target_name!r}: its own "
                    "geometry failed to load (see above)"
                )
                continue
            parent_link = f"{target_name}__{attachment}"
            if parent_link not in loaded[target_name].link_names:
                errors.append(
                    f"module {name}: mount.on={mount.on!r} but {target_name}'s "
                    f"urdf_fragment has no link named {attachment!r} "
                    f"(has: {sorted(loaded[target_name].link_names)})"
                )
                continue
            xyz_m, rpy_rad = (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        elif mount is not None and mount.pose is not None:
            parent_link = WORLD_LINK
            xyz_m = _mm_to_m(mount.pose.xyz_mm)
            rpy_rad = _deg_to_rad(mount.pose.rpy_deg)
        else:
            errors.append(
                f"module {name}: has neither mount.pose nor mount.on -- "
                "nothing to place it in the scene"
            )
            continue

        joint = _fixed_joint(f"{name}__mount", parent_link, frag.root_link, xyz_m, rpy_rad)
        all_links.extend(frag.links)
        all_joints.append(joint)
        all_joints.extend(frag.joints)
        instances[name] = SceneInstance(
            name=name,
            root_link=frag.root_link,
            parent_link=parent_link,
            joint_name=joint.get("name"),
            link_names=frozenset(frag.link_names),
        )

        _validate_joint_state(name, frag, ri.instance.joint_state, joint_state, errors)

    if errors:
        raise SceneBuildError(resolved.cell.id, errors)

    urdf_xml = _render_urdf(resolved.cell.id, all_links, all_joints)

    assert base_instance is not None  # no base errors above => it loaded
    errors.extend(
        check_workspace_containment(
            cell_id=resolved.cell.id,
            urdf_xml=urdf_xml,
            joint_state=joint_state,
            base_link_names=base_instance.link_names,
            instance_link_names={name: si.link_names for name, si in instances.items()},
            instance_kinds={name: resolved.instances[name].module.kind for name in instances},
            world_link=WORLD_LINK,
        )
    )
    if errors:
        raise SceneBuildError(resolved.cell.id, errors)

    return Scene(urdf_xml=urdf_xml, base=base_instance, instances=instances, joint_state=joint_state)
