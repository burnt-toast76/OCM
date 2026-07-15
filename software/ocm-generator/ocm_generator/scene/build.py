# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build a Tesseract Environment from a ResolvedCell.

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

from tesseract_robotics.tesseract_common import GeneralResourceLocator
from tesseract_robotics.tesseract_environment import Environment

from .errors import FragmentError, SceneBuildError
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


@dataclass(frozen=True)
class Scene:
    environment: Environment
    urdf_xml: str
    base: SceneInstance
    instances: dict[str, SceneInstance] = field(default_factory=dict)

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


def build_scene(resolved: ResolvedCell, modules_root: Path | str) -> Scene:
    """Compile a resolved cell into a real tesseract_robotics Environment.

    Raises SceneBuildError (carrying every violation found) if any
    instance's urdf_fragment is missing/malformed, any instance has neither
    a mount.pose nor a mount.on, or any mount.on names an attachment link
    that doesn't exist on its target.
    """
    modules_root = Path(modules_root)
    errors: list[str] = []

    loaded: dict[str, _LoadedFragment] = {}

    try:
        loaded[_BASE_KEY] = _load_and_namespace(resolved.base, _BASE_KEY, modules_root)
    except FragmentError as e:
        errors.append(f"base ({resolved.base.id}): {e}")

    for name, ri in resolved.instances.items():
        try:
            loaded[name] = _load_and_namespace(ri.module, name, modules_root)
        except FragmentError as e:
            errors.append(f"module {name} ({ri.module.id}): {e}")

    all_links: list[ET.Element] = []
    all_joints: list[ET.Element] = []
    instances: dict[str, SceneInstance] = {}
    base_instance: Optional[SceneInstance] = None

    if _BASE_KEY in loaded:
        frag = loaded[_BASE_KEY]
        joint = _fixed_joint(f"{_BASE_KEY}__mount", WORLD_LINK, frag.root_link, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        all_links.extend(frag.links)
        all_joints.append(joint)
        all_joints.extend(frag.joints)
        base_instance = SceneInstance(
            name="base", root_link=frag.root_link, parent_link=WORLD_LINK, joint_name=joint.get("name")
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
            name=name, root_link=frag.root_link, parent_link=parent_link, joint_name=joint.get("name")
        )

    if errors:
        raise SceneBuildError(resolved.cell.id, errors)

    urdf_xml = _render_urdf(resolved.cell.id, all_links, all_joints)

    locator = GeneralResourceLocator()
    env = Environment()
    if not env.init(urdf_xml, locator):
        raise SceneBuildError(
            resolved.cell.id,
            ["tesseract Environment.init() rejected the composed URDF (see stderr for the parser error)"],
        )

    assert base_instance is not None  # no base errors above => it loaded
    return Scene(environment=env, urdf_xml=urdf_xml, base=base_instance, instances=instances)
