# SPDX-License-Identifier: AGPL-3.0-or-later
"""Comment-preserving writes (see ocm_api.workspace's own module docstring
for the mechanism). This repo's YAML comments carry design intent -- a
plain yaml.safe_dump round-trip used to destroy every one of them on the
first agent-driven write.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from ocm_api import OcmApi


def test_patch_preserves_comments_and_key_order_on_a_real_heavily_commented_module(api: OcmApi, workspace_root: Path):
    module_id = "com.accelsolutions.base.frame1200"
    path = workspace_root / "modules" / module_id / "module.yaml"
    original = path.read_text(encoding="utf-8")
    # The COMMENT TEXT itself (from `#` onward), not the whole line -- a
    # couple of this file's lines pad extra spaces before the value to
    # visually align colons, and that padding isn't preservable YAML state
    # (see test_targeted_patch_produces_a_minimal_diff's own docstring
    # note); the comment content that actually carries design intent is.
    original_comments = [line[line.index("#") :] for line in original.splitlines() if "#" in line]
    assert len(original_comments) >= 6  # the header block (5 lines) + several inline notes

    e = api.update_module(module_id, patch=[{"op": "replace", "path": "/mechanical/mass_kg", "value": 90.0}])
    assert e.ok, e.refusals

    updated = path.read_text(encoding="utf-8")

    # Every comment (the header block AND every inline trailing comment)
    # survives verbatim -- ADR references, "placeholder -- not authored
    # yet" caveats, unit notes, all of it.
    for comment_text in original_comments:
        assert comment_text in updated, comment_text

    def top_level_keys(text: str) -> list[str]:
        return [m.group(1) for m in re.finditer(r"^([a-z_]+):", text, re.MULTILINE)]

    assert top_level_keys(updated) == top_level_keys(original)
    assert "mass_kg: 90.0" in updated


def test_targeted_patch_produces_a_minimal_diff(api: OcmApi, workspace_root: Path):
    # A synthetic-but-realistic fixture in this repo's OWN default
    # (single-space, no manual column alignment) style -- unlike a couple
    # of this repo's earliest hand-typed files (frame1200 among them),
    # which pad extra spaces before `:` to visually align keys. That
    # padding isn't meaningful YAML syntax any round-trip library models
    # as preservable state, so re-serializing such a file re-flows every
    # padded line even when untouched (see workspace.py's own docstring).
    # Every file this package itself ever writes uses plain formatting,
    # so that caveat doesn't apply to the write path being tested here.
    api.create_module_draft("com.example.pickhead.yamldiff", "end_effector")
    path = workspace_root / "modules" / "com.example.pickhead.yamldiff" / "module.yaml"

    original = path.read_text(encoding="utf-8")
    annotated = original.replace(
        "name: yamldiff\n",
        "# TODO: get NDA'd docs from Acme before publishing this draft\nname: yamldiff  # working title only\n",
    )
    assert annotated != original  # the replace actually matched
    path.write_text(annotated, encoding="utf-8")

    manifest = api.describe_module("com.example.pickhead.yamldiff").data["manifest"]
    manifest["mechanical"]["mass_kg"] = 0.75  # the one real change

    e = api.update_module("com.example.pickhead.yamldiff", manifest=manifest)
    assert e.ok, e.refusals

    updated = path.read_text(encoding="utf-8")
    assert "# TODO: get NDA'd docs from Acme before publishing this draft" in updated
    assert "# working title only" in updated

    diff = [
        line
        for line in difflib.unified_diff(annotated.splitlines(), updated.splitlines(), lineterm="")
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    ]
    assert diff, "expected the patch to change something"
    assert all("mass_kg" in line for line in diff), diff


def test_adr0015_connectivity_patch_preserves_comments_and_round_trips(api: OcmApi, workspace_root: Path):
    # ADR-0015's ports/nets/links go through this exact same write path as
    # every other field -- a golden-file round trip proving that a
    # comment-annotated draft survives a patch adding them, same as
    # test_targeted_patch_produces_a_minimal_diff already proves for an
    # ordinary scalar. Uses the ADR's own worked example (ref, not
    # "connector" -- see ocm-core's test_module_loading.py for why).
    api.create_module_draft("com.example.fixture.connectivity", "fixture")
    path = workspace_root / "modules" / "com.example.fixture.connectivity" / "module.yaml"

    original = path.read_text(encoding="utf-8")
    annotated = original.replace(
        "name: connectivity\n",
        "# ADR-0015: one 24V feed, one EtherCAT chain -- this module's own external interface\nname: connectivity  # working title only\n",
    )
    assert annotated != original
    path.write_text(annotated, encoding="utf-8")

    e = api.update_module(
        "com.example.fixture.connectivity",
        patch=[
            {
                "op": "add",
                "path": "/components",
                "value": [{"refdes": "DP1", "ref": "com.nordson-kline.dispenser.dp8@1.0.0"}],
            },
            {
                "op": "add",
                "path": "/ports",
                "value": [
                    {"id": "PWR_IN", "domain": "electrical", "type": "M12-A-4P"},
                    {"id": "NET_IN", "domain": "communication", "protocol": "ethercat", "role": "slave_in"},
                ],
            },
            {
                "op": "add",
                "path": "/nets",
                "value": {
                    "electrical": [
                        {
                            "id": "N_24V",
                            "endpoints": [
                                {"port": "PWR_IN", "pin": "1"},
                                {"refdes": "DP1", "ref": "electrical", "pin": "1"},
                            ],
                        }
                    ]
                },
            },
            {
                "op": "add",
                "path": "/links",
                "value": [{"id": "L_EC_1", "protocol": "ethercat", "a": {"port": "NET_IN"}, "b": {"refdes": "DP1", "ref": "X1"}}],
            },
        ],
    )
    assert e.ok, e.refusals

    updated = path.read_text(encoding="utf-8")
    assert "# ADR-0015: one 24V feed, one EtherCAT chain -- this module's own external interface" in updated
    assert "# working title only" in updated

    manifest = api.describe_module("com.example.fixture.connectivity").data["manifest"]
    assert manifest["ports"][0]["id"] == "PWR_IN"
    assert manifest["nets"]["electrical"][0]["id"] == "N_24V"
    assert manifest["links"][0]["id"] == "L_EC_1"

    # A second, genuine no-op write (same data back) doesn't reformat or
    # drop anything either -- the same canonicalize-not-preserve-harder
    # guarantee `ocm fmt` relies on, exercised here through the connectivity
    # fields specifically.
    after_first_write = path.read_text(encoding="utf-8")
    e2 = api.update_module("com.example.fixture.connectivity", manifest=manifest)
    assert e2.ok, e2.refusals
    assert path.read_text(encoding="utf-8") == after_first_write


def test_ocm_fmt_output_is_byte_identical_to_the_gui_write_paths(tmp_path: Path, workspace_root: Path, api: OcmApi):
    # ocm_generator.cli.cmd_fmt and ocm_api.workspace.write_yaml both call
    # ocm_core.new_yaml_rt directly now (a shared ocm-core function, not a
    # private copy each) specifically so they can't quietly drift apart --
    # this is the test that actually pins that down: canonicalizing the
    # SAME non-canonical bytes through `ocm fmt`'s own code (no API, no
    # Workspace) and through a real update_module write (the GUI/agent
    # path) must produce byte-identical output.
    import yaml

    from ocm_core import new_yaml_rt
    from ocm_generator.cli import _canonicalize

    non_canonical = (
        "ocm_version: '1.1'\n"
        "id: com.example.fixture.byteidentical\n"
        "revision: 0.1.0\n"
        "kind: fixture\n"
        "electrical:\n"
        "  supplies:\n"
        "    - rail: 24VDC\n"  # sequence=4/offset=2 -- this repo's own non-canonical style
        "      current_nominal_a: 2.0\n"
    )

    # Path 1: `ocm fmt` -- a bare file, no OcmApi/Workspace involved at all.
    fmt_copy = tmp_path / "module.yaml"
    fmt_copy.write_text(non_canonical, encoding="utf-8")
    fmt_output = _canonicalize(new_yaml_rt(), fmt_copy)

    # Path 2: the real GUI/agent write path -- inject the SAME non-canonical
    # bytes directly (same technique test_targeted_patch_produces_a_minimal_diff
    # uses), then a genuine no-op update_module (identical data back)
    # triggers write_yaml's own reformat.
    api.create_module_draft("com.example.fixture.byteidentical", "fixture")
    api_path = workspace_root / "modules" / "com.example.fixture.byteidentical" / "module.yaml"
    api_path.write_text(non_canonical, encoding="utf-8")
    manifest = yaml.safe_load(non_canonical)
    # update_module always writes, even when the manifest is schema-invalid
    # (validation gates publishing, not saving) -- `non_canonical` above is
    # deliberately minimal/incomplete, so this write IS refused, but the
    # reformat this test cares about happens regardless.
    api.update_module("com.example.fixture.byteidentical", manifest=manifest)
    write_path_output = api_path.read_text(encoding="utf-8")

    assert fmt_output == write_path_output
    assert "    - rail: 24VDC" not in fmt_output  # sanity: a real reformat actually happened, not a no-op comparison
