# SPDX-License-Identifier: AGPL-3.0-or-later
"""`ocm fmt` -- see cmd_fmt in ocm_generator/cli.py. Needs nothing beyond
ocm-core (it calls ocm_core.new_yaml_rt, the same function
ocm_api.workspace.write_yaml -- the GUI/agent write path -- calls, so the
CLI canonicalizes to EXACTLY what that write path would have produced)
-- no importorskip needed here: ocm-core is already a structural
dependency of this whole test module (test_cli.py's own validate/resolve/
scene/plan coverage needs it too), never something that might be absent.
"""

from __future__ import annotations

from pathlib import Path

from ocm_generator.cli import main


NON_CANONICAL = (
    "# ADR-0001: important context, must survive a reformat\n"
    "ocm_version: '1.0'  # pinned\n"
    "id:       com.example.tiny\n"
    "electrical:\n"
    "  supplies:\n"
    "    - rail: 24VDC\n"
    "      current_nominal_a: 2.0\n"
)


def test_check_reports_a_non_canonical_file_and_never_writes(capsys, tmp_path: Path):
    manifest = tmp_path / "module.yaml"
    manifest.write_text(NON_CANONICAL, encoding="utf-8")

    exit_code = main(["fmt", str(manifest), "--check"])

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "1 of 1 manifest(s) not canonically formatted" in err
    assert str(manifest) in err
    assert "Run `ocm fmt` to fix" in err
    assert manifest.read_text(encoding="utf-8") == NON_CANONICAL


def test_fmt_rewrites_sequence_indent_to_this_repos_convention(tmp_path: Path):
    manifest = tmp_path / "module.yaml"
    manifest.write_text(NON_CANONICAL, encoding="utf-8")

    exit_code = main(["fmt", str(manifest)])

    assert exit_code == 0
    text = manifest.read_text(encoding="utf-8")
    # sequence=2/offset=0 -- flush with the parent key, not indented past it.
    assert "  - rail: 24VDC" in text
    assert "    - rail: 24VDC" not in text


def test_fmt_preserves_comments_and_semantic_content(tmp_path: Path):
    import yaml

    manifest = tmp_path / "module.yaml"
    manifest.write_text(NON_CANONICAL, encoding="utf-8")

    main(["fmt", str(manifest)])

    text = manifest.read_text(encoding="utf-8")
    assert "# ADR-0001: important context, must survive a reformat" in text
    assert "# pinned" in text
    assert yaml.safe_load(text) == yaml.safe_load(NON_CANONICAL)


def test_fmt_collapses_manual_column_alignment_padding(tmp_path: Path):
    # The one documented, honest limitation of this round-trip (see
    # ocm_api/workspace.py's own module docstring): hand-typed
    # inter-column alignment isn't meaningful YAML syntax, so it doesn't
    # survive a canonicalizing round-trip either -- confirm `fmt` actually
    # exercises that path rather than leaving it untouched by accident.
    manifest = tmp_path / "module.yaml"
    manifest.write_text(NON_CANONICAL, encoding="utf-8")

    main(["fmt", str(manifest)])

    text = manifest.read_text(encoding="utf-8")
    assert "id: com.example.tiny" in text
    assert "id:       com.example.tiny" not in text


def test_check_passes_once_a_file_is_already_canonical(capsys, tmp_path: Path):
    manifest = tmp_path / "module.yaml"
    manifest.write_text(NON_CANONICAL, encoding="utf-8")
    assert main(["fmt", str(manifest)]) == 0

    exit_code = main(["fmt", str(manifest), "--check"])

    assert exit_code == 0
    assert "OK: 1 manifest(s) already canonical" in capsys.readouterr().out


def test_fmt_is_idempotent_a_second_run_changes_nothing(tmp_path: Path):
    manifest = tmp_path / "module.yaml"
    manifest.write_text(NON_CANONICAL, encoding="utf-8")
    main(["fmt", str(manifest)])
    once = manifest.read_text(encoding="utf-8")

    main(["fmt", str(manifest)])

    assert manifest.read_text(encoding="utf-8") == once


def test_fmt_discovers_manifests_recursively_and_ignores_non_manifest_yaml(capsys, tmp_path: Path):
    (tmp_path / "modules" / "a").mkdir(parents=True)
    (tmp_path / "modules" / "a" / "module.yaml").write_text("ocm_version: '1.0'\n", encoding="utf-8")
    (tmp_path / "components" / "b").mkdir(parents=True)
    (tmp_path / "components" / "b" / "component.yaml").write_text("ocm_version: '1.1'\n", encoding="utf-8")
    # Not a manifest by filename -- must never be counted or touched.
    (tmp_path / "modules" / "a" / "attachments").mkdir()
    (tmp_path / "modules" / "a" / "attachments" / "notes.yaml").write_text("x:    1\n", encoding="utf-8")

    exit_code = main(["fmt", str(tmp_path / "modules"), str(tmp_path / "components"), "--check"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "OK: 2 manifest(s) already canonical" in out
    assert (tmp_path / "modules" / "a" / "attachments" / "notes.yaml").read_text(encoding="utf-8") == "x:    1\n"


def test_fmt_with_no_paths_and_nothing_found_is_not_an_error(capsys, tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no ./modules, ./components, ./cells here

    exit_code = main(["fmt"])

    assert exit_code == 0
    assert "No manifests found" in capsys.readouterr().err


def test_fmt_defaults_to_modules_components_cells_under_the_cwd(monkeypatch, tmp_path: Path):
    (tmp_path / "modules" / "a").mkdir(parents=True)
    (tmp_path / "modules" / "a" / "module.yaml").write_text(NON_CANONICAL, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = main(["fmt"])

    assert exit_code == 0
    text = (tmp_path / "modules" / "a" / "module.yaml").read_text(encoding="utf-8")
    assert "id: com.example.tiny" in text


def test_fmt_on_the_real_repo_manifests_only_reflows_formatting(repo_root: Path, tmp_path: Path):
    # The actual regression this command exists to fix: dh200/sd50 (and
    # most of the rest) were hand-authored at sequence=4/offset=2, which
    # new_yaml_rt's global sequence=2/offset=0 config silently reformats
    # on ANY write. A round trip through `fmt` must be a no-op the SECOND
    # time (idempotent) and must never change parsed content, on the real
    # files this was found on -- not just a synthetic fixture.
    import shutil

    import yaml

    src = repo_root / "modules" / "com.accelsolutions.dispense.dh200" / "module.yaml"
    copy = tmp_path / "module.yaml"
    shutil.copy(src, copy)

    exit_code = main(["fmt", str(copy)])
    assert exit_code == 0
    assert yaml.safe_load(copy.read_text(encoding="utf-8")) == yaml.safe_load(src.read_text(encoding="utf-8"))

    before_second_pass = copy.read_text(encoding="utf-8")
    assert main(["fmt", str(copy), "--check"]) == 0  # already canonical after one pass
    assert copy.read_text(encoding="utf-8") == before_second_pass
