# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parse a module's urdf_fragment and namespace it for splicing into a
combined cell URDF.

A fragment is expected to be a small, valid, standalone URDF document (a
<robot> with <link>/<joint> children) -- exactly what the schema's
`mechanical.geometry.urdf_fragment` field describes: "a URDF snippet
declaring this module's links and joints... allowing cell.yaml to compile
straight into a Tesseract scene graph with zero manual CAD work"
(ocm-module-1.0.schema.json). That field is THE load-bearing decision in
ADR-0007 -- this module is where it actually gets compiled.

Every fragment gets namespaced with its instance name (`<instance>__<name>`)
so two instances of the same module (two screwdrivers, say) don't collide
on link/joint names once spliced into one document.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from .errors import FragmentError

TESSERACT_NS = "https://github.com/ros-industrial-consortium/tesseract"


def load_fragment(path: Path) -> ET.Element:
    """Read and parse a urdf_fragment file. Raises FragmentError, never a
    bare ElementTree/OS exception, so callers can collect a clear message.
    """
    if not path.is_file():
        raise FragmentError(f"urdf_fragment not found: {path}")
    try:
        return ET.parse(path).getroot()
    except ET.ParseError as e:
        raise FragmentError(f"{path}: not well-formed XML ({e})") from e


def find_root_link(root: ET.Element, source: Path) -> str:
    """The one link that is never a joint's child -- the fragment's own root."""
    link_names: set[str] = set()
    for link in root.findall("link"):
        name = link.get("name")
        if not name:
            raise FragmentError(f"{source}: has a <link> with no 'name' attribute")
        link_names.add(name)

    child_names: set[str] = set()
    for joint in root.findall("joint"):
        child = joint.find("child")
        if child is None or not child.get("link"):
            raise FragmentError(
                f"{source}: joint {joint.get('name')!r} has no valid <child link=\"...\"/>"
            )
        child_names.add(child.get("link"))

    roots = link_names - child_names
    if len(roots) != 1:
        raise FragmentError(
            f"{source}: expected exactly one root link (a <link> that is never a "
            f"joint's <child>), found {sorted(roots)} out of {sorted(link_names)}"
        )
    return roots.pop()


def namespace_fragment(
    root: ET.Element, prefix: str, fragment_dir: Path, source: Path
) -> tuple[list[ET.Element], list[ET.Element], str]:
    """Rename every link/joint in `root` to `<prefix>__<name>`, resolve
    relative <mesh filename="..."> paths against `fragment_dir`, and return
    (links, joints, namespaced_root_link_name).
    """
    root_link_name = find_root_link(root, source)

    def ns(name: str) -> str:
        return f"{prefix}__{name}"

    links = list(root.findall("link"))
    joints = list(root.findall("joint"))

    for link in links:
        link.set("name", ns(link.get("name")))
        for mesh in link.iter("mesh"):
            filename = mesh.get("filename")
            if filename and not Path(filename).is_absolute():
                mesh.set("filename", str((fragment_dir / filename).resolve()))

    for joint in joints:
        joint.set("name", ns(joint.get("name")))
        parent = joint.find("parent")
        child = joint.find("child")
        if parent is None or not parent.get("link"):
            raise FragmentError(
                f"{source}: joint {joint.get('name')!r} has no valid <parent link=\"...\"/>"
            )
        parent.set("link", ns(parent.get("link")))
        child.set("link", ns(child.get("link")))

    return links, joints, ns(root_link_name)
