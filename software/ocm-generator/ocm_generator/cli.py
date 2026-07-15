# SPDX-License-Identifier: AGPL-3.0-or-later
"""ocm -- a small CLI to run and trial the pipeline built so far.

    ocm validate <module.yaml>
    ocm resolve  <cell.yaml> [--modules DIR]
    ocm scene    <cell.yaml> [--modules DIR] [--dump-urdf FILE.urdf] [--view FILE.html]

Each stage's collected-violations error (ManifestValidationError,
CellResolutionError, SceneBuildError) is printed in full, not just the
first problem -- same as the underlying libraries. Exit code is 0 on
success, 1 if that stage reported errors.

This is a developer/trial tool, not the agent layer (see ROADMAP Step 6 --
"the agent is a thin tool-calling wrapper over a generator that already
works," and this is how you check it already works).
"""

from __future__ import annotations

import argparse
import sys
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

    sg = scene.environment.getSceneGraph()
    links = sg.getLinks()
    joints = sg.getJoints()
    print(f"OK: {resolved.cell.id}")
    print(f"  {len(links)} links, {len(joints)} joints")
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

    p_scene = subparsers.add_parser("scene", help="Resolve a cell and build its Tesseract scene.")
    p_scene.add_argument("cell", type=Path, help="Path to a cell.yaml")
    p_scene.add_argument("--modules", type=Path, default=Path("modules"), help="Module search path (default: ./modules)")
    p_scene.add_argument("--dump-urdf", type=Path, default=None, help="Write the composed URDF to this file (a plain cross-check, e.g. to open in another URDF tool)")
    p_scene.add_argument("--view", type=Path, default=None, help="Write a self-contained three.js HTML viewer to this file (open by double-clicking)")
    p_scene.set_defaults(func=cmd_scene)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
