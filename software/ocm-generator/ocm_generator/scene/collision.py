# SPDX-License-Identifier: AGPL-3.0-or-later
"""Discrete collision checking via a real Tesseract (Bullet) contact
manager -- the engine behind `ocm scene --collision`.

Lazily imports tesseract_robotics (see CollisionCheckUnavailable) so the
base ocm-generator install works without it -- only this module, reached
only via --collision, needs the `tesseract` extra:
`pip install ocm-generator[tesseract]`.

## A packaging workaround, documented so it isn't mistaken for an accident

On at least the Windows tesseract-robotics 0.35.0 wheel, `Environment`'s
own discrete contact manager comes back empty: no Bullet/FCL backend is
registered by default (`ContactManagersPluginFactory().hasDiscreteContact
ManagerPlugins()` is False out of the box). The backend DLLs *are*
bundled -- `tesseract_collision_bullet_factories-<hash>.dll` -- but in a
sibling `tesseract_robotics.libs/` directory (a delvewheel bundling
convention) under a content-hashed filename the default plugin search
never looks for. `_find_bullet_factories_library` locates it at runtime
(the hash changes per build, so it can't be hardcoded) and hand-builds the
tiny YAML plugin config `ContactManagersPluginFactory` needs to load it
directly. If a future/different tesseract-robotics build registers its
plugins normally, the default factory is tried first and this is skipped
entirely.

Given that manager, the actual contact test does NOT go through
`Environment.getDiscreteContactManager()` -- it doesn't need to. Link
world poses and per-link collision geometry come from this package's own
already-tested `.kinematics` (the same forward kinematics the viewer and
containment check use, joint_state included), fed directly into the
standalone manager's `addCollisionObject`. `Environment.init()` /
`.setState()` are still used -- both because the task this exists for asks
for it, and because `env.init()` is a free well-formedness check on the
composed URDF -- but nothing is read back from the Environment's own
(fragile -- see build_scene's history) state proxies.

## Margin semantics

`contact_distance_mm` is both the search radius the contact manager uses
(pairs farther apart than this never appear in results at all) and the
threshold for what counts as a *violation*: a result's `distance` is
negative when two shapes actually interpenetrate, ~0 when they're just
touching, and positive (up to the margin) when they're merely close.
Resting contact -- feed1 and nest1 sit ON the deck by design, touching at
z=0 -- reports a contact but is not a violation. Only `distance < 0`
(genuine penetration, past a small floating-point epsilon) is.

## Mount-adjacent contact is not a violation -- but only one hop of it

Two more kinds of "contact" are structurally expected, not crashes, and
aren't just a margin away from clean: a robot's real base mesh commonly
overlaps its own mounting deck by tens of mm at the foot (it bolts flush,
it doesn't float above it), and a tool bolted directly to a robot's flange
routinely overlaps the flange-side link it's mounted on -- two
independently-authored meshes rarely abut with zero overlap at a mounting
joint, coarse collision geometry least of all. `_mount_parent_map` skips
contact between any instance and whatever it's *directly* mounted on --
the mount.on target for a mount.on chain, or "base" for anything placed
by mount.pose (cell.yaml's convention makes that relative to the base's
own datum).

Deliberately NOT transitive: sd1 is mounted on robot1, and robot1 is
mounted on base, but that does not mean sd1 safely touching robot1 and
robot1 safely touching base compose into sd1 safely touching base --
sd1 punching into a guard wall (also part of "base") is exactly the crash
this whole check exists to catch. Only a direct mount relationship is
exempted; two hops of "mounted on" is not "mounted on."
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .build import WORLD_LINK, Scene
from .errors import CollisionCheckError, CollisionCheckUnavailable
from .kinematics import compute_world_poses, list_collision_primitives

DEFAULT_MARGIN_MM = 1.0
_EPSILON_M = 1e-7  # floating-point slack right at an exact touching boundary
_BULLET_MANAGER_NAME = "BulletDiscreteBVHManager"


@dataclass(frozen=True)
class Contact:
    instance_a: str
    instance_b: str
    link_a: str
    link_b: str
    distance_mm: float
    is_violation: bool  # True: real penetration. False: resting/near contact within the margin.


@dataclass(frozen=True)
class CollisionCheckResult:
    contacts: tuple[Contact, ...]
    margin_mm: float

    @property
    def violations(self) -> tuple[Contact, ...]:
        return tuple(c for c in self.contacts if c.is_violation)


def _instance_of(link_name: str, scene: Scene) -> str:
    if link_name in scene.base.link_names:
        return "base"
    for name, inst in scene.instances.items():
        if link_name in inst.link_names:
            return name
    return "?"


def _mount_parent_map(scene: Scene) -> dict[str, str]:
    """Instance name -> whatever it's *directly* mounted on: the mount.on
    target instance for a mount.on chain, or "base" for a mount.pose
    instance (bolted straight to the grid, per cell.yaml's convention that
    mount.pose is relative to the base's own datum). Deliberately one hop
    only -- see module docstring for why this must not be transitive.
    """
    parents: dict[str, str] = {}
    for name, inst in scene.instances.items():
        parents[name] = "base" if inst.parent_link == WORLD_LINK else _instance_of(inst.parent_link, scene)
    return parents


def _find_bullet_factories_library() -> Optional[str]:
    """Absolute path (no extension) to the bundled Bullet contact-manager
    factories library, or None if it can't be found this way. See the
    module docstring for why this is necessary at all.
    """
    try:
        import tesseract_robotics
    except ImportError:
        return None

    package_dir = Path(tesseract_robotics.__file__).resolve().parent
    libs_dir = package_dir.parent / f"{package_dir.name}.libs"
    if not libs_dir.is_dir():
        return None

    for pattern in ("tesseract_collision_bullet_factories*.dll", "*tesseract_collision_bullet_factories*.so*", "*tesseract_collision_bullet_factories*.dylib"):
        matches = sorted(libs_dir.glob(pattern))
        if matches:
            return str(matches[0].with_suffix(""))
    return None


def check_collisions(scene: Scene, contact_distance_mm: float = DEFAULT_MARGIN_MM) -> CollisionCheckResult:
    """Run a discrete contact check on a composed Scene.

    Raises CollisionCheckUnavailable if tesseract-robotics isn't installed
    or no discrete contact manager backend could be loaded. Raises
    CollisionCheckError if Tesseract otherwise rejects the composed URDF
    (build_scene's own validation should already rule this out in
    practice). Does not raise on contacts -- inspect the returned
    CollisionCheckResult.violations; the caller (the CLI) decides what
    exit code that becomes.
    """
    try:
        import numpy as np
        from tesseract_robotics.tesseract_collision import (
            ContactManagersPluginFactory,
            ContactRequest,
            ContactResultMap,
            ContactResultVector,
            ContactTestType_ALL,
        )
        from tesseract_robotics.tesseract_common import GeneralResourceLocator, VectorIsometry3d
        from tesseract_robotics.tesseract_environment import Environment
        from tesseract_robotics.tesseract_geometry import Box, Cylinder, GeometriesConst, Sphere
    except ImportError as e:
        raise CollisionCheckUnavailable(
            "--collision requires the 'tesseract' extra (tesseract-robotics is not installed): "
            "pip install ocm-generator[tesseract]"
        ) from e

    margin_m = contact_distance_mm / 1000.0
    locator = GeneralResourceLocator()

    # "Load the composed URDF into a Tesseract environment, apply the
    # cell's joint_state" -- see module docstring for why the actual
    # contact test below doesn't go through this environment's own
    # (unregistered-by-default) contact manager.
    env = Environment()
    if not env.init(scene.urdf_xml, locator):
        raise CollisionCheckError(
            "tesseract Environment.init() rejected the composed URDF -- this should not happen "
            "if build_scene() already succeeded; see stderr for Tesseract's own parser error"
        )
    env.setState(dict(scene.joint_state))

    factory = ContactManagersPluginFactory()
    if not factory.hasDiscreteContactManagerPlugins():
        library = _find_bullet_factories_library()
        if library is None:
            raise CollisionCheckUnavailable(
                "tesseract-robotics has no discrete contact manager plugin registered, and the "
                "bundled Bullet factories library could not be located to work around it -- "
                "see ocm_generator/scene/collision.py's module docstring"
            )
        yaml_cfg = f"""
contact_manager_plugins:
  search_libraries:
    - {library}
  discrete_plugins:
    default: {_BULLET_MANAGER_NAME}
    plugins:
      {_BULLET_MANAGER_NAME}:
        class: BulletDiscreteBVHManagerFactory
"""
        factory = ContactManagersPluginFactory(yaml_cfg, locator)

    manager = factory.createDiscreteContactManager(_BULLET_MANAGER_NAME)
    if manager is None:
        raise CollisionCheckUnavailable(f"failed to create the {_BULLET_MANAGER_NAME!r} discrete contact manager")

    def to_geometry(kind: str, dims: dict[str, float]):
        if kind == "box":
            return Box(dims["x"], dims["y"], dims["z"])
        if kind == "cylinder":
            return Cylinder(dims["radius"], dims["length"])
        return Sphere(dims["radius"])

    root = ET.fromstring(scene.urdf_xml)
    world_poses = compute_world_poses(root, scene.joint_state, WORLD_LINK)

    active_links: list[str] = []
    for link in root.findall("link"):
        name = link.get("name")
        if not name or name == WORLD_LINK or name not in world_poses:
            continue
        primitives = list_collision_primitives(link, world_poses[name])
        if not primitives:
            continue

        shapes = GeometriesConst()
        poses = VectorIsometry3d(len(primitives))
        for i, prim in enumerate(primitives):
            shapes.append(to_geometry(prim.kind, prim.dims))
            matrix = np.eye(4)
            matrix[:3, :3] = np.array(prim.world.rotation)
            matrix[0, 3], matrix[1, 3], matrix[2, 3] = prim.world.translation
            poses[i].setMatrix(matrix)

        if manager.addCollisionObject(name, 0, shapes, poses):
            active_links.append(name)

    manager.setActiveCollisionObjects(active_links)
    manager.setDefaultCollisionMargin(margin_m)

    result_map = ContactResultMap()
    manager.contactTest(result_map, ContactRequest(ContactTestType_ALL))
    flat = ContactResultVector()
    result_map.flattenCopyResults(flat)

    mount_parent = _mount_parent_map(scene)

    contacts: list[Contact] = []
    for r in flat:
        link_a, link_b = r.link_names[0], r.link_names[1]
        instance_a, instance_b = _instance_of(link_a, scene), _instance_of(link_b, scene)
        if instance_a == instance_b:
            # Adjacent links of the same instance (e.g. a robot's own arm
            # segments) are expected to touch at their shared joints --
            # not interesting for an inter-module clash check.
            continue
        if mount_parent.get(instance_a) == instance_b or mount_parent.get(instance_b) == instance_a:
            # Directly mount-adjacent (e.g. sd1 and the robot1 flange it's
            # bolted to, or robot1 and the base deck it's bolted to) --
            # expected contact, not a crash. NOT transitive -- see module
            # docstring for why sd1-vs-base must still be checked.
            continue
        distance_m = float(r.distance)
        contacts.append(
            Contact(
                instance_a=instance_a,
                instance_b=instance_b,
                link_a=link_a,
                link_b=link_b,
                distance_mm=distance_m * 1000.0,
                is_violation=distance_m < -_EPSILON_M,
            )
        )

    return CollisionCheckResult(contacts=tuple(contacts), margin_mm=contact_distance_mm)
