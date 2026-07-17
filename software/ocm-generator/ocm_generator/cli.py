# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm -- a small CLI to run and trial the pipeline built so far.

    ocm validate <module.yaml>
    ocm resolve  <cell.yaml> [--modules DIR]
    ocm scene    <cell.yaml> [--modules DIR] [--dump-urdf FILE.urdf] [--view FILE.html]
                             [--collision [--collision-margin-mm MM]]
    ocm plan     <cell.yaml> [--modules DIR] --emit-urscript FILE.script
                             [--collision-margin-mm MM] [--path-samples N]

Each stage's collected-violations error (ManifestValidationError,
CellResolutionError, SceneBuildError) is printed in full, not just the
first problem -- same as the underlying libraries. Exit code is 0 on
success, 1 if that stage reported errors.

`--collision` and `plan` need the `tesseract` extra (pip install
ocm-generator[tesseract]); nothing else here does -- see
ocm_generator/scene/collision.py and ocm_generator/planner/ik.py.

This is a developer/trial tool, not the agent layer (see ROADMAP Step 6 --
"the agent is a thin tool-calling wrapper over a generator that already
works," and this is how you check it already works).
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _print_errors(heading: str, errors: list[str]) -> None:
    print(heading, file=sys.stderr)
    for err in errors:
        print(f"  - {err}", file=sys.stderr)


def cmd_validate(args: argparse.Namespace) -> int:
    from ocm_core import ManifestValidationError, load_module

    try:
        module = load_module(args.manifest)
    except OSError as e:
        print(f"FAILED: {args.manifest}: {e.strerror or e}", file=sys.stderr)
        return 1
    except ManifestValidationError as e:
        _print_errors(f"FAILED: {args.manifest}", e.errors)
        return 1

    print(f"OK: {module.id}@{module.revision} ({module.kind})")
    if module.name:
        print(f"  name: {module.name}")
    if module.capabilities:
        print("  capabilities:")
        for cap in module.capabilities:
            print(f"    - {cap.name}: {cap.summary}")
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    from ocm_core import load_cell
    from ocm_resolve import CellResolutionError, resolve_cell

    try:
        cell = load_cell(args.cell)
    except OSError as e:
        print(f"FAILED: {args.cell}: {e.strerror or e}", file=sys.stderr)
        return 1

    try:
        resolved = resolve_cell(cell, args.modules)
    except CellResolutionError as e:
        _print_errors(f"FAILED: {args.cell} did not resolve against {args.modules}", e.errors)
        return 1

    print(f"OK: {resolved.cell.id}")
    print(f"  base: {resolved.base.id}@{resolved.base.revision}")
    for name in sorted(resolved.instances):
        inst = resolved.instances[name]
        where = f"on {inst.mounted_on.name}" if inst.mounted_on is not None else "on base grid"
        print(f"  {name}: {inst.module.id}@{inst.module.revision} ({where})")
    return 0


def cmd_scene(args: argparse.Namespace) -> int:
    from ocm_core import load_cell
    from ocm_generator.scene import SceneBuildError, build_scene
    from ocm_resolve import CellResolutionError, resolve_cell

    try:
        cell = load_cell(args.cell)
    except OSError as e:
        print(f"FAILED: {args.cell}: {e.strerror or e}", file=sys.stderr)
        return 1

    try:
        resolved = resolve_cell(cell, args.modules)
    except CellResolutionError as e:
        _print_errors(f"FAILED: {args.cell} did not resolve against {args.modules}", e.errors)
        return 1

    try:
        scene = build_scene(resolved, args.modules)
    except SceneBuildError as e:
        _print_errors(f"FAILED: {args.cell} scene did not build", e.errors)
        return 1

    root = ET.fromstring(scene.urdf_xml)
    n_links = len(root.findall("link"))
    n_joints = len(root.findall("joint"))
    print(f"OK: {resolved.cell.id}")
    print(f"  {n_links} links, {n_joints} joints")
    print(f"  base: {scene.base.root_link} -> parent {scene.base.parent_link}")
    for name in sorted(scene.instances):
        inst = scene.instances[name]
        print(f"  {name}: {inst.root_link} -> parent {inst.parent_link}")

    if args.dump_urdf:
        Path(args.dump_urdf).write_text(scene.urdf_xml, encoding="utf-8")
        print(f"  wrote combined URDF to {args.dump_urdf}")

    if args.view:
        from ocm_generator.scene import render_html

        Path(args.view).write_text(render_html(scene, resolved), encoding="utf-8")
        print(f"  wrote HTML viewer to {args.view}")

    if args.collision:
        return cmd_scene_collision(scene, args)

    return 0


def cmd_scene_collision(scene, args: argparse.Namespace) -> int:
    from ocm_generator.scene import CollisionCheckError, CollisionCheckUnavailable, check_collisions

    try:
        result = check_collisions(scene, contact_distance_mm=args.collision_margin_mm)
    except CollisionCheckUnavailable as e:
        print(f"FAILED: collision check unavailable: {e}", file=sys.stderr)
        return 1
    except CollisionCheckError as e:
        print(f"FAILED: collision check did not complete: {e}", file=sys.stderr)
        return 1

    print(f"  collision check (margin {result.margin_mm:g} mm):")
    if not result.contacts:
        print("    no contacts within the margin")
    for c in sorted(result.contacts, key=lambda c: c.distance_mm):
        tag = "COLLISION" if c.is_violation else "resting contact (ok)"
        print(f"    {c.instance_a} <-> {c.instance_b}  ({c.link_a} / {c.link_b})  {c.distance_mm:+.2f} mm  {tag}")

    if result.violations:
        print(f"  FAILED: {len(result.violations)} real contact(s) (penetration beyond the margin)", file=sys.stderr)
        return 1

    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    from ocm_core import load_cell
    from ocm_generator.emitters import emit_urscript, render_cycle_time_table
    from ocm_generator.planner import PlanningError, PlanningUnavailable, plan_fastening_sequence
    from ocm_generator.scene import SceneBuildError, build_scene
    from ocm_resolve import CellResolutionError, resolve_cell

    try:
        cell = load_cell(args.cell)
    except OSError as e:
        print(f"FAILED: {args.cell}: {e.strerror or e}", file=sys.stderr)
        return 1

    try:
        resolved = resolve_cell(cell, args.modules)
    except CellResolutionError as e:
        _print_errors(f"FAILED: {args.cell} did not resolve against {args.modules}", e.errors)
        return 1

    try:
        scene = build_scene(resolved, args.modules)
    except SceneBuildError as e:
        _print_errors(f"FAILED: {args.cell} scene did not build", e.errors)
        return 1

    try:
        plan = plan_fastening_sequence(
            resolved,
            scene,
            collision_margin_mm=args.collision_margin_mm,
            path_samples=args.path_samples,
        )
    except PlanningUnavailable as e:
        print(f"FAILED: planning unavailable: {e}", file=sys.stderr)
        return 1
    except PlanningError as e:
        print(f"FAILED: {args.cell}: {e}", file=sys.stderr)
        return 1

    script = emit_urscript(plan)
    args.emit_urscript.write_text(script, encoding="utf-8")
    print(f"OK: {plan.tool_instance} fastening sequence ({len(plan.holes)} hole(s)): "
          f"{', '.join(h.hole_id for h in plan.holes)}")
    print(f"  wrote URScript to {args.emit_urscript}")
    print()
    print(render_cycle_time_table(plan))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ocm", description="Run and trial the OCM generator pipeline.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_validate = subparsers.add_parser("validate", help="Load + schema-validate a module manifest.")
    p_validate.add_argument("manifest", type=Path, help="Path to a module.yaml")
    p_validate.set_defaults(func=cmd_validate)

    p_resolve = subparsers.add_parser("resolve", help="Load a cell and resolve it against a module search path.")
    p_resolve.add_argument("cell", type=Path, help="Path to a cell.yaml")
    p_resolve.add_argument("--modules", type=Path, default=Path("modules"), help="Module search path (default: ./modules)")
    p_resolve.set_defaults(func=cmd_resolve)

    p_scene = subparsers.add_parser("scene", help="Resolve a cell and compose its scene.")
    p_scene.add_argument("cell", type=Path, help="Path to a cell.yaml")
    p_scene.add_argument("--modules", type=Path, default=Path("modules"), help="Module search path (default: ./modules)")
    p_scene.add_argument("--dump-urdf", type=Path, default=None, help="Write the composed URDF to this file (a plain cross-check, e.g. to open in another URDF tool)")
    p_scene.add_argument("--view", type=Path, default=None, help="Write a self-contained three.js HTML viewer to this file (open by double-clicking)")
    p_scene.add_argument(
        "--collision",
        action="store_true",
        help="Run a discrete Tesseract collision check on the composed scene at its joint_state "
        "(needs the 'tesseract' extra: pip install ocm-generator[tesseract]). Exits nonzero on any "
        "real contact (penetration). Touching/near contact within --collision-margin-mm is reported "
        "but does not fail the check -- e.g. a module resting flush on the base deck.",
    )
    p_scene.add_argument(
        "--collision-margin-mm",
        type=float,
        default=1.0,
        metavar="MM",
        help="Contact distance margin in mm (default: 1.0). Two shapes closer than this are reported; "
        "only ones that actually interpenetrate (not just touch) count as a real contact. Raise this "
        "to tolerate looser resting fits; lower it to catch closer near-misses too.",
    )
    p_scene.set_defaults(func=cmd_scene)

    p_plan = subparsers.add_parser(
        "plan", help="Plan the plan's fastening for_each sequence and emit URScript (needs the 'tesseract' extra)."
    )
    p_plan.add_argument("cell", type=Path, help="Path to a cell.yaml")
    p_plan.add_argument("--modules", type=Path, default=Path("modules"), help="Module search path (default: ./modules)")
    p_plan.add_argument(
        "--emit-urscript",
        type=Path,
        required=True,
        metavar="FILE.script",
        help="Write the planned standoff/contact/retract/home motion as URScript to this file.",
    )
    p_plan.add_argument(
        "--collision-margin-mm",
        type=float,
        default=1.0,
        metavar="MM",
        help="Contact distance margin for the home->standoff path check (default: 1.0).",
    )
    p_plan.add_argument(
        "--path-samples",
        type=int,
        default=50,
        metavar="N",
        help="Number of joint-space states to collision-check along home->standoff (default: 50).",
    )
    p_plan.set_defaults(func=cmd_plan)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
