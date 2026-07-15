# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

from pathlib import Path

from ocm_generator.cli import main


def test_validate_succeeds_on_a_valid_manifest(capsys, sd50_manifest_path):
    exit_code = main(["validate", str(sd50_manifest_path)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "OK: com.accelsolutions.screwdriver.sd50@1.2.0" in out
    assert "drive_screw" in out


def test_validate_reports_missing_file_cleanly(capsys, tmp_path: Path):
    exit_code = main(["validate", str(tmp_path / "nope.yaml")])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "FAILED" in err
    assert "nope.yaml" in err


def test_validate_reports_schema_violations(capsys, tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("ocm_version: '1.0'\nid: com.example.bad\n", encoding="utf-8")

    exit_code = main(["validate", str(bad)])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "FAILED" in err
    assert "mechanical" in err  # a required top-level field, reported as missing


def test_resolve_succeeds_on_the_real_bracket_cell(capsys, repo_root: Path):
    exit_code = main(
        ["resolve", str(repo_root / "cells" / "bracket-asm-01" / "cell.yaml"), "--modules", str(repo_root / "modules")]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "OK: com.accelsolutions.cell.bracket-asm-01" in out
    assert "sd1: com.accelsolutions.screwdriver.sd50@1.2.0 (on robot1)" in out


def test_resolve_reports_missing_cell_file_cleanly(capsys, tmp_path: Path):
    exit_code = main(["resolve", str(tmp_path / "nope.yaml")])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "FAILED" in err
    assert "nope.yaml" in err


def test_resolve_reports_every_violation(capsys, repo_root: Path, tmp_path: Path):
    empty_modules = tmp_path / "empty"
    empty_modules.mkdir()

    exit_code = main(
        ["resolve", str(repo_root / "cells" / "bracket-asm-01" / "cell.yaml"), "--modules", str(empty_modules)]
    )

    assert exit_code == 1
    err = capsys.readouterr().err
    assert err.count("module not found") >= 6


def test_scene_succeeds_on_the_real_bracket_cell(capsys, repo_root: Path, tmp_path: Path):
    out_path = tmp_path / "bracket.urdf"

    exit_code = main(
        [
            "scene",
            str(repo_root / "cells" / "bracket-asm-01" / "cell.yaml"),
            "--modules",
            str(repo_root / "modules"),
            "--out",
            str(out_path),
        ]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "18 links, 17 joints" in out
    assert "sd1: sd1__origin -> parent robot1__flange" in out
    assert out_path.is_file()
    assert "<robot" in out_path.read_text(encoding="utf-8")


def test_scene_fails_cleanly_when_resolve_fails(capsys, repo_root: Path, tmp_path: Path):
    empty_modules = tmp_path / "empty"
    empty_modules.mkdir()

    exit_code = main(
        ["scene", str(repo_root / "cells" / "bracket-asm-01" / "cell.yaml"), "--modules", str(empty_modules)]
    )

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "did not resolve" in err
