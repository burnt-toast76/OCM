# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0027: collision geometry -- derived from posed components, or authored
and checked against them.

Two jobs live here, both pure Python (no tesseract, no numpy -- deliberately,
so they run in the same minimal environment as the rest of scene assembly):

1. **Checks** (`check_module_collision_geometry`): the file-dependent half of
   ADR-0027's refusal table, complementing ocm-resolve's manifest-only half
   (pose/envelope/unit completeness). Needs the module's directory, its
   urdf_fragment, and -- in authored mode -- its collision mesh:

   - OCM_AUTHORED_COLLISION_MISSING: `authored` with no `collision` path, or a
     path that is not a file.
   - OCM_LINK_UNKNOWN: a component instance or structure primitive naming a
     `link` absent from the fragment (D4 -- a check, not a mechanism).
   - OCM_COMPONENT_OUTSIDE_COLLISION: in authored mode, a component envelope
     at its pose protrudes outside the authored collision geometry (D2).
   - OCM_ENVELOPE_OVERLAP: in derived mode, overlapping component envelopes --
     `advise`, never `refuse` (D5: real assemblies interpenetrate; overlap is
     weak evidence of a pose error and strong evidence of nothing). Returned
     separately so the caller surfaces it as a warning, not a refusal.

2. **The derived proxy** (`derived_collision_elements`): per-link URDF
   <collision> elements built from posed component envelopes plus structure
   primitives -- what `scene/build.py` splices into a `derived` module's links
   so the planner collides against what the manifest states (one source, no
   second artifact).

Units: manifests carry mm (poses) and verbatim envelope units resolved through
ocm_core.units (the shared deterministic converter -- ADR-0027's consequence
note); URDF and STL are metres. All internal math is mm; emission converts.

Containment semantics (a recorded judgement call): the check runs against the
authored mesh's CONVEX HULL, realised as the intersection of its faces'
outward half-spaces. The repo's own convention is `_convex.stl` meshes, where
hull == mesh exactly; on a concave authored mesh this can only under-refuse
(the hull is larger), which is the direction ADR-0027 already accepts --
oversized geometry is merely conservative. Exact point-in-mesh would need a
real geometry dependency and can refuse on legitimately conservative meshes.

Envelope placement convention (v0): a component's envelope box is CENTRED at
the instance's pose. The datasheet states overall dims but not a datum; until
a datum field is transcribed, centred is the stated, deterministic choice --
not a guess buried in math.
"""

from __future__ import annotations

import math
import struct as _struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from ocm_core import Module
from ocm_core.component import Component
from ocm_core.units import UnknownUnitError, length_to_mm

# Half-space containment tolerance, in mm. Covers float noise, not real
# protrusion -- a tenth of a millimetre is far below any fabrication concern.
_TOLERANCE_MM = 0.1


# ---------------------------------------------------------------------------
# Small pure-python vector helpers (no numpy in the base install).
# ---------------------------------------------------------------------------


def _rpy_deg_to_matrix(rpy: tuple[float, float, float]) -> list[list[float]]:
    r, p, y = (math.radians(a) for a in rpy)
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    # URDF fixed-axis RPY: R = Rz(y) @ Ry(p) @ Rx(r)
    return [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ]


def _apply(m: list[list[float]], v: tuple[float, float, float]) -> tuple[float, float, float]:
    return (
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    )


def _envelope_corners_mm(
    envelope_mm: tuple[float, float, float],
    pose_xyz_mm: tuple[float, float, float],
    pose_rpy_deg: tuple[float, float, float],
) -> list[tuple[float, float, float]]:
    """The 8 world-frame corners of an envelope box CENTRED at its pose."""
    hx, hy, hz = envelope_mm[0] / 2.0, envelope_mm[1] / 2.0, envelope_mm[2] / 2.0
    rot = _rpy_deg_to_matrix(pose_rpy_deg)
    corners = []
    for sx in (-hx, hx):
        for sy in (-hy, hy):
            for sz in (-hz, hz):
                rx, ry, rz = _apply(rot, (sx, sy, sz))
                corners.append((pose_xyz_mm[0] + rx, pose_xyz_mm[1] + ry, pose_xyz_mm[2] + rz))
    return corners


def _aabb(corners: list[tuple[float, float, float]]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    xs, ys, zs = zip(*corners)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


# ---------------------------------------------------------------------------
# STL loading (binary or ASCII) -> outward half-spaces, in mm.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _HalfSpaces:
    """The mesh's faces as (normal, offset) with `dot(n, p) <= offset` inside.
    For a convex mesh this intersection IS the mesh; for any mesh it is the
    convex-hull-style over-approximation documented in the module docstring.
    """

    planes: tuple[tuple[tuple[float, float, float], float], ...]


def load_stl_half_spaces_mm(path: Path) -> _HalfSpaces:
    """Parse an STL (STL units are metres, per URDF convention) into outward
    face half-spaces in mm. Degenerate faces (zero-area) are skipped; face
    normals are recomputed from vertex winding rather than trusted from the
    file (exporters routinely write junk normals).
    """
    raw = path.read_bytes()
    tris: list[tuple[tuple[float, float, float], ...]] = []
    try:
        if raw[:5].lower() == b"solid" and b"facet" in raw[:200]:
            # ASCII STL
            floats: list[float] = []
            for line in raw.decode("ascii", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("vertex"):
                    parts = line.split()
                    floats.extend(float(x) for x in parts[1:4])
            verts = [tuple(floats[i : i + 3]) for i in range(0, len(floats), 3)]
            tris = [tuple(verts[i : i + 3]) for i in range(0, len(verts) - 2, 3)]
        else:
            (n,) = _struct.unpack_from("<I", raw, 80)
            off = 84
            for _ in range(n):
                vals = _struct.unpack_from("<12f", raw, off)
                tris.append((tuple(vals[3:6]), tuple(vals[6:9]), tuple(vals[9:12])))
                off += 50
    except (ValueError, _struct.error):
        # Not parseable as STL (e.g. a stub whose `collision` points at a URDF
        # fragment, or a truncated file). No planes -> the containment check
        # skips rather than crashing; whether the file SHOULD be a real mesh is
        # a separate (authored-path) refusal, not this parser's call.
        return _HalfSpaces(planes=())

    centroid = [0.0, 0.0, 0.0]
    count = 0
    for tri in tris:
        for v in tri:
            centroid[0] += v[0]
            centroid[1] += v[1]
            centroid[2] += v[2]
            count += 1
    if count == 0:
        return _HalfSpaces(planes=())
    c = (centroid[0] / count, centroid[1] / count, centroid[2] / count)

    planes = []
    for a, b, d in tris:
        u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        w = (d[0] - a[0], d[1] - a[1], d[2] - a[2])
        n = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
        norm = math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2)
        if norm < 1e-12:
            continue
        n = (n[0] / norm, n[1] / norm, n[2] / norm)
        # orient outward: the mesh centroid must be on the inside
        if n[0] * (c[0] - a[0]) + n[1] * (c[1] - a[1]) + n[2] * (c[2] - a[2]) > 0:
            n = (-n[0], -n[1], -n[2])
        offset = n[0] * a[0] + n[1] * a[1] + n[2] * a[2]
        # metres -> mm
        planes.append(((n[0], n[1], n[2]), offset * 1000.0))
    return _HalfSpaces(planes=tuple(planes))


def _point_inside(hs: _HalfSpaces, p_mm: tuple[float, float, float], tol_mm: float = _TOLERANCE_MM) -> bool:
    return all(n[0] * p_mm[0] + n[1] * p_mm[1] + n[2] * p_mm[2] <= off + tol_mm for n, off in hs.planes)


# ---------------------------------------------------------------------------
# Fragment link inventory
# ---------------------------------------------------------------------------


def fragment_link_names(fragment_path: Path) -> tuple[set[str], str | None]:
    """All link names in the fragment, plus the root link (a link that is no
    joint's child). Returns (set(), None) on a parse failure -- the fragment's
    own load path reports that separately.
    """
    try:
        root = ET.parse(fragment_path).getroot()
    except (ET.ParseError, OSError):
        return set(), None
    links = {el.get("name") for el in root.iter("link") if el.get("name")}
    children = {j.find("child").get("link") for j in root.iter("joint") if j.find("child") is not None}
    roots = [name for name in links if name not in children]
    return links, (roots[0] if roots else None)


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


def _envelope_mm(component: Component) -> tuple[float, float, float] | None:
    env = component.geometry.envelope if component.geometry else None
    if env is None or None in (env.length, env.width, env.height, env.units):
        return None
    try:
        return (
            length_to_mm(env.length, env.units),
            length_to_mm(env.width, env.units),
            length_to_mm(env.height, env.units),
        )
    except UnknownUnitError:
        return None  # already refused at resolve (OCM_UNIT_UNRECOGNISED)


def check_module_collision_geometry(
    module: Module,
    module_dir: Path,
    components_by_refdes: dict[str, Component],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """The file-dependent ADR-0027 checks for one module.

    Returns (refusals, advisories):
    - refusals: (code, path, message) tuples the caller turns into Refusals.
    - advisories: OCM_ENVELOPE_OVERLAP strings, surfaced as warnings -- advise,
      never gate (ADR-0025 D3 / ADR-0027 D5). Each records the overlapping
      pair so a later reader can identify every flagged placement.
    """
    refusals: list[tuple[str, str, str]] = []
    advisories: list[str] = []
    geo = module.mechanical.geometry
    source = geo.collision_source

    # Link inventory, for D4's link check (both modes).
    links: set[str] = set()
    if geo.urdf_fragment:
        links, _root = fragment_link_names(module_dir / geo.urdf_fragment)
    if links:
        for mc in module.components:
            if mc.link is not None and mc.link not in links:
                refusals.append((
                    "OCM_LINK_UNKNOWN",
                    f"components['{mc.refdes}'].link",
                    f"{module.id}: component {mc.refdes} names link {mc.link!r}, absent from the "
                    f"urdf_fragment (has: {sorted(links)})",
                ))
        for sp in module.mechanical.structure:
            if sp.link is not None and sp.link not in links:
                refusals.append((
                    "OCM_LINK_UNKNOWN",
                    f"mechanical.structure['{sp.id}'].link",
                    f"{module.id}: structure {sp.id} names link {sp.link!r}, absent from the "
                    f"urdf_fragment (has: {sorted(links)})",
                ))

    if source == "authored":
        collision = geo.collision
        if not collision or not (module_dir / collision).is_file():
            refusals.append((
                "OCM_AUTHORED_COLLISION_MISSING",
                "mechanical.geometry.collision",
                f"{module.id}: collision_source 'authored' but "
                + (f"{collision!r} is not a file under {module_dir}" if collision else "no collision path is declared"),
            ))
        else:
            hs = load_stl_half_spaces_mm(module_dir / collision)
            if hs.planes:
                for mc in module.components:
                    comp = components_by_refdes.get(mc.refdes)
                    if comp is None or mc.pose is None:
                        continue  # resolve-side refusals own incompleteness
                    env_mm = _envelope_mm(comp)
                    if env_mm is None:
                        continue
                    corners = _envelope_corners_mm(env_mm, mc.pose.xyz_mm, mc.pose.rpy_deg)
                    outside = [p for p in corners if not _point_inside(hs, p)]
                    if outside:
                        refusals.append((
                            "OCM_COMPONENT_OUTSIDE_COLLISION",
                            f"components['{mc.refdes}'].pose",
                            f"{module.id}: component {mc.refdes} envelope at its pose protrudes outside "
                            f"the authored collision geometry ({len(outside)}/8 corners outside) -- "
                            "the planner would not know it is there (ADR-0027 D2)",
                        ))

    if source == "derived":
        # Overlap advisory: world AABBs of posed envelopes, pairwise.
        boxes: list[tuple[str, tuple, tuple]] = []
        for mc in module.components:
            comp = components_by_refdes.get(mc.refdes)
            if comp is None or mc.pose is None:
                continue
            env_mm = _envelope_mm(comp)
            if env_mm is None:
                continue
            lo, hi = _aabb(_envelope_corners_mm(env_mm, mc.pose.xyz_mm, mc.pose.rpy_deg))
            boxes.append((mc.refdes, lo, hi))
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                (ra, lo_a, hi_a), (rb, lo_b, hi_b) = boxes[i], boxes[j]
                if all(lo_a[k] < hi_b[k] and lo_b[k] < hi_a[k] for k in range(3)):
                    advisories.append(
                        f"OCM_ENVELOPE_OVERLAP: {module.id}: envelopes of {ra} and {rb} overlap at their "
                        "declared poses -- weak evidence of a pose error, strong evidence of nothing; "
                        "surfaced, not gated (ADR-0027 D5)"
                    )
    return refusals, advisories


# ---------------------------------------------------------------------------
# The derived proxy (build.py splices these into the composed URDF)
# ---------------------------------------------------------------------------


def _collision_element(shape_xml: ET.Element, xyz_m: tuple[float, float, float], rpy_rad: tuple[float, float, float]) -> ET.Element:
    col = ET.Element("collision")
    ET.SubElement(col, "origin", {
        "xyz": f"{xyz_m[0]:.9g} {xyz_m[1]:.9g} {xyz_m[2]:.9g}",
        "rpy": f"{rpy_rad[0]:.9g} {rpy_rad[1]:.9g} {rpy_rad[2]:.9g}",
    })
    geom = ET.SubElement(col, "geometry")
    geom.append(shape_xml)
    return col


def derived_collision_elements(
    module: Module,
    components_by_refdes: dict[str, Component],
) -> dict[str | None, list[ET.Element]]:
    """Per-link URDF <collision> elements for a `derived` module: one box per
    posed component envelope (centred at its pose -- the documented v0
    convention), plus each structure primitive. Keyed by the manifest's own
    (un-namespaced) link name; None = the fragment root. Completeness is NOT
    re-checked here -- resolve refused an incomplete derived module before a
    scene build ever starts; instances this cannot realise are skipped.
    """
    out: dict[str | None, list[ET.Element]] = {}

    for mc in module.components:
        comp = components_by_refdes.get(mc.refdes)
        if comp is None or mc.pose is None:
            continue
        env_mm = _envelope_mm(comp)
        if env_mm is None:
            continue
        box = ET.Element("box", {"size": f"{env_mm[0] / 1000:.9g} {env_mm[1] / 1000:.9g} {env_mm[2] / 1000:.9g}"})
        xyz_m = tuple(v / 1000.0 for v in mc.pose.xyz_mm)
        rpy_rad = tuple(math.radians(a) for a in mc.pose.rpy_deg)
        out.setdefault(mc.link, []).append(_collision_element(box, xyz_m, rpy_rad))

    for sp in module.mechanical.structure:
        if sp.units is None and sp.shape in ("box", "cylinder"):
            continue  # refused at resolve; nothing sane to emit
        try:
            if sp.shape == "box" and sp.size is not None:
                dims_m = tuple(length_to_mm(v, sp.units) / 1000.0 for v in sp.size)
                shape = ET.Element("box", {"size": f"{dims_m[0]:.9g} {dims_m[1]:.9g} {dims_m[2]:.9g}"})
            elif sp.shape == "cylinder" and sp.radius is not None and sp.length is not None:
                shape = ET.Element("cylinder", {
                    "radius": f"{length_to_mm(sp.radius, sp.units) / 1000.0:.9g}",
                    "length": f"{length_to_mm(sp.length, sp.units) / 1000.0:.9g}",
                })
            elif sp.shape == "mesh" and sp.path is not None:
                shape = ET.Element("mesh", {"filename": sp.path})
            else:
                continue
            xyz_m = tuple(length_to_mm(v, sp.units) / 1000.0 for v in sp.pose.xyz) if sp.units else tuple(sp.pose.xyz)
            rpy_rad = tuple(math.radians(a) for a in sp.pose.rpy)
            out.setdefault(sp.link, []).append(_collision_element(shape, xyz_m, rpy_rad))
        except UnknownUnitError:
            continue  # refused at resolve (OCM_UNIT_UNRECOGNISED)

    return out
