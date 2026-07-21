# SPDX-License-Identifier: AGPL-3.0-or-later
"""ADR-0014 / spec/10: the component registry. Full lifecycle
(create_component_draft -> update_component -> validate_component ->
publish_component -> list/describe_component), the zero-assumption
transcription workflow (an honestly incomplete draft's refusal list reads
as the human's completion list), a module referencing published
components resolving and aggregating (describe_module's derived BOM/power/
air budget), and every ADR-0014 refusal path resolve_cell can raise,
surfaced through the same envelope every other refusal uses.
"""

from __future__ import annotations

from ocm_api import Codes, OcmApi


def _ejector_manifest(component_id: str = "com.example.ejector.demo1") -> dict:
    return {
        "ocm_version": "1.1",
        "id": component_id,
        "revision": "0.1.0",
        "kind": "vacuum_ejector",
        "vendor": "Example Co",
        "part_number": "EJ-100",
        "source": {"kind": "datasheet", "ref": "fictional demo datasheet, worked-example only"},
        "electrical": {"supplies": [{"rail": "24VDC", "current_nominal_a": 0.3}]},
        "pneumatic": {"pressure_bar_min": 4.0, "pressure_bar_max": 6.0, "flow_nl_min": 12.0},
        "comms": {
            "protocol": "discrete-io",
            "signals": [{"name": "vacuum_switch", "direction_device": "output", "type": "bool"}],
        },
    }


def _tool_module_manifest(module_id: str, components: list[dict], signal_source: str | None) -> dict:
    signal: dict = {"name": "part_present", "direction": "input", "type": "bool"}
    if signal_source is not None:
        signal["source"] = signal_source
    return {
        "ocm_version": "1.1",
        "id": module_id,
        "revision": "0.1.0",
        "kind": "end_effector",
        "license": "CERN-OHL-S-2.0",
        "name": "Tiny Test Tool",
        "mechanical": {
            "mount": {"interface": "iso-9409-1-a50", "footprint_mm": [70.0, 70.0]},
            "frames": {"origin": {"xyz_mm": [0.0, 0.0, 0.0]}, "tcp": {"xyz_mm": [0.0, 0.0, 100.0]}},
            "geometry": {"collision": "meshes/tool_convex.stl", "urdf_fragment": "urdf/generated_box.urdf.xacro"},
            "mass_kg": 1.0,
            "com_mm": [0.0, 0.0, 50.0],
        },
        "state_machine": {"model": "packml", "implements": ["idle", "execute"], "abort_safe": False},
        "capabilities": [{"name": "pick", "summary": "Pick a part."}],
        "comms": {"protocol": "ethercat", "signals": [signal]},
        "components": components,
    }


# ---------------------------------------------------------------------------
# Full lifecycle
# ---------------------------------------------------------------------------


def test_component_full_lifecycle(api: OcmApi):
    draft = api.create_component_draft("com.example.ejector.demo1", "vacuum_ejector")
    assert draft.ok, draft.refusals
    assert draft.data["draft"] is True
    assert draft.data["revision"] == "0.1.0"

    updated = api.update_component("com.example.ejector.demo1", manifest=_ejector_manifest())
    assert updated.ok, updated.refusals

    validated = api.validate_component("com.example.ejector.demo1")
    assert validated.ok, validated.refusals
    assert validated.data["valid"] is True

    published = api.publish_component("com.example.ejector.demo1", "1.0.0")
    assert published.ok, published.refusals
    assert published.data == {"id": "com.example.ejector.demo1", "revision": "1.0.0", "draft": False, "published": True}

    listed = api.list_components()
    assert listed.ok
    row = next(r for r in listed.data if r["id"] == "com.example.ejector.demo1")
    assert row["draft"] is False
    assert row["vendor"] == "Example Co"

    described = api.describe_component("com.example.ejector.demo1")
    assert described.ok
    assert described.data["component"]["part_number"] == "EJ-100"


def test_describe_component_succeeds_with_warnings_on_an_incomplete_draft(api: OcmApi):
    # A fresh draft is EXPECTED to be schema-invalid (ADR-0014: vendor/
    # source are transcribed facts, never pre-filled) -- describing it
    # must still return the document (Part B's Components page form needs
    # to render and keep editing an in-progress draft), not refuse and
    # withhold `data` the way it did before this behavior matched
    # describe_cell's own "succeed with warnings" pattern for an
    # unresolvable cell.
    api.create_component_draft("com.example.ejector.incomplete1", "vacuum_ejector")

    e = api.describe_component("com.example.ejector.incomplete1")

    assert e.ok
    assert e.data["component"]["kind"] == "vacuum_ejector"
    assert e.data["draft"] is True
    assert any("vendor" in w for w in e.warnings)
    assert any("source" in w for w in e.warnings)


def test_describe_component_has_no_warnings_once_valid(api: OcmApi):
    api.create_component_draft("com.example.ejector.complete1", "vacuum_ejector")
    api.update_component("com.example.ejector.complete1", manifest=_ejector_manifest("com.example.ejector.complete1"))

    e = api.describe_component("com.example.ejector.complete1")

    assert e.ok
    assert e.warnings == ()


def test_publish_component_gates_on_validity_same_as_modules(api: OcmApi):
    api.create_component_draft("com.example.ejector.demo2", "vacuum_ejector")
    e = api.publish_component("com.example.ejector.demo2", "1.0.0")
    assert not e.ok
    assert any(r.code == Codes.SCHEMA_INVALID for r in e.refusals)


def test_draft_component_cannot_publish_at_a_0x_revision(api: OcmApi):
    api.create_component_draft("com.example.ejector.demo3", "vacuum_ejector")
    api.update_component("com.example.ejector.demo3", manifest=_ejector_manifest("com.example.ejector.demo3"))
    e = api.publish_component("com.example.ejector.demo3", "0.2.0")
    assert not e.ok
    assert e.refusals[0].code == Codes.DRAFT_NOT_PUBLISHABLE


# ---------------------------------------------------------------------------
# Zero-assumption transcription: refusals as a completion list; a
# deliberately gap-filled transcription stays a draft.
# ---------------------------------------------------------------------------


def test_fresh_draft_refusal_list_is_the_completion_list(api: OcmApi):
    # create_component_draft deliberately does NOT pre-fill vendor/source
    # with a TODO placeholder the way create_module_draft fills design
    # fields -- those are datasheet FACTS, not design sketches, so an
    # untouched draft is genuinely incomplete and validate_component's own
    # refusal list names exactly what's missing: the human's/agent's
    # next-read-the-datasheet-and-supply-this list.
    api.create_component_draft("com.example.ejector.demo4", "vacuum_ejector")

    e = api.validate_component("com.example.ejector.demo4")
    assert not e.ok
    # jsonschema reports a missing required property against the PARENT
    # object (path "$"), not a path into the (nonexistent) property --
    # the completion list lives in each refusal's message instead.
    messages = " | ".join(r.message for r in e.refusals)
    assert "'vendor' is a required property" in messages
    assert "'source' is a required property" in messages


def test_deliberately_gap_filled_transcription_stays_a_draft(api: OcmApi):
    # A real datasheet often doesn't state mass or current draw. ADR-0014:
    # omit, don't estimate -- this update still validates cleanly (mass_kg/
    # current_nominal_a are genuinely optional fields, not required ones),
    # but the component correctly stays at its draft revision because
    # nothing here calls publish_component -- that's the human's decision
    # once they've confirmed the transcription is as complete as the
    # source allows, not something validation forces on incomplete-but-
    # honest data.
    api.create_component_draft("com.example.ejector.demo5", "vacuum_ejector")
    gap_filled = {
        "ocm_version": "1.1",
        "id": "com.example.ejector.demo5",
        "revision": "0.1.0",
        "kind": "vacuum_ejector",
        "vendor": "Example Co",
        "source": {"kind": "datasheet", "ref": "fictional demo datasheet, worked-example only"},
        "electrical": {"supplies": [{"rail": "24VDC"}]},  # no current_nominal_a -- not stated
        # no `geometry` block at all -- mass not stated
    }

    e = api.update_component("com.example.ejector.demo5", manifest=gap_filled)
    assert e.ok, e.refusals
    assert e.data["draft"] is True

    validated = api.validate_component("com.example.ejector.demo5")
    assert validated.ok, validated.refusals

    written = api.describe_component("com.example.ejector.demo5").data["component"]
    assert "current_nominal_a" not in written["electrical"]["supplies"][0]
    assert "geometry" not in written  # never estimated, never copied from another definition


# ---------------------------------------------------------------------------
# A module referencing published components resolves and aggregates.
# ---------------------------------------------------------------------------


def _publish_ejector(api: OcmApi, component_id: str) -> None:
    api.create_component_draft(component_id, "vacuum_ejector")
    api.update_component(component_id, manifest=_ejector_manifest(component_id))
    e = api.publish_component(component_id, "1.0.0")
    assert e.ok, e.refusals


def _publish_io_master(api: OcmApi, component_id: str) -> None:
    api.create_component_draft(component_id, "io_link_master")
    manifest = {
        "ocm_version": "1.1",
        "id": component_id,
        "revision": "0.1.0",
        "kind": "io_link_master",
        "vendor": "Example Co",
        "source": {"kind": "datasheet", "ref": "fictional demo datasheet, worked-example only"},
        "electrical": {"supplies": [{"rail": "24VDC", "current_nominal_a": 0.1}]},
    }
    api.update_component(component_id, manifest=manifest)
    e = api.publish_component(component_id, "1.0.0")
    assert e.ok, e.refusals


def test_module_referencing_two_components_resolves_and_aggregates(api: OcmApi):
    _publish_ejector(api, "com.example.ejector.vg1")
    _publish_io_master(api, "com.example.io.io1")

    api.create_module_draft("com.example.pickhead.pk200", "end_effector")
    manifest = _tool_module_manifest(
        "com.example.pickhead.pk200",
        components=[
            {"refdes": "VG1", "ref": "com.example.ejector.vg1@1.0.0"},
            {"refdes": "IO1", "ref": "com.example.io.io1@1.0.0"},
        ],
        signal_source="VG1.vacuum_switch",
    )
    e = api.update_module("com.example.pickhead.pk200", manifest=manifest)
    assert e.ok, e.refusals
    geom = api.generate_geometry_stub("com.example.pickhead.pk200", (70.0, 70.0), 100.0)
    assert geom.ok, geom.refusals

    published = api.publish_module("com.example.pickhead.pk200", "1.0.0")
    assert published.ok, published.refusals

    described = api.describe_module("com.example.pickhead.pk200")
    assert described.ok, described.refusals
    aggregates = described.data["aggregates"]
    assert {row["refdes"] for row in aggregates["bom"]} == {"VG1", "IO1"}
    assert aggregates["power_budget"]["24VDC"]["current_nominal_a"] == 0.4
    assert aggregates["air_consumption_nl_min"] == 12.0

    # And the module genuinely resolves into a cell -- ADR-0014's whole
    # point (a module referencing components is still just a module).
    api.create_cell("c-agg", "com.accelsolutions.base.frame1200@2.0.0")
    placed = api.place_instance(
        "c-agg", "pk1", "com.example.pickhead.pk200@1.0.0",
        {"pose": {"xyz_mm": [400, 300, 0], "rpy_deg": [0, 0, 0]}},
    )
    assert placed.ok, placed.refusals


def test_describe_module_with_no_components_list_has_no_aggregates(api: OcmApi):
    e = api.describe_module("com.accelsolutions.fixture.pneumatic-nest")
    assert e.ok
    assert "aggregates" not in e.data


# ---------------------------------------------------------------------------
# Every ADR-0014 refusal path resolve_cell can raise, surfaced through the
# ocm-api envelope (place_instance re-resolves, same as any other verb).
# ---------------------------------------------------------------------------


def _place_tool(api: OcmApi, cell_id: str, module_id: str, components: list[dict], signal_source: str | None = None):
    api.create_module_draft(module_id, "end_effector")
    manifest = _tool_module_manifest(module_id, components, signal_source)
    e = api.update_module(module_id, manifest=manifest)
    assert e.ok, e.refusals
    geom = api.generate_geometry_stub(module_id, (70.0, 70.0), 100.0)
    assert geom.ok, geom.refusals
    published = api.publish_module(module_id, "1.0.0")
    assert published.ok, published.refusals
    api.create_cell(cell_id, "com.accelsolutions.base.frame1200@2.0.0")
    return api.place_instance(cell_id, "tool1", f"{module_id}@1.0.0", {"pose": {"xyz_mm": [400, 300, 0], "rpy_deg": [0, 0, 0]}})


def test_unknown_component_is_refused(api: OcmApi):
    e = _place_tool(api, "c-unknown", "com.example.pickhead.unknown1", [{"refdes": "VG1", "ref": "com.example.ejector.doesnotexist@1.0.0"}])
    assert not e.ok
    assert e.refusals[0].code == Codes.UNKNOWN_COMPONENT


def test_duplicate_refdes_is_refused(api: OcmApi):
    _publish_ejector(api, "com.example.ejector.dup1")
    e = _place_tool(
        api, "c-dup", "com.example.pickhead.dup1",
        [
            {"refdes": "VG1", "ref": "com.example.ejector.dup1@1.0.0"},
            {"refdes": "VG1", "ref": "com.example.ejector.dup1@1.0.0"},
        ],
    )
    assert not e.ok
    assert e.refusals[0].code == Codes.DUPLICATE_REFDES


def test_source_unknown_refdes_is_refused(api: OcmApi):
    _publish_ejector(api, "com.example.ejector.src1")
    e = _place_tool(
        api, "c-src1", "com.example.pickhead.src1",
        [{"refdes": "VG1", "ref": "com.example.ejector.src1@1.0.0"}],
        signal_source="VG9.vacuum_switch",
    )
    assert not e.ok
    assert e.refusals[0].code == Codes.INVALID_SOURCE
    assert "VG9" in e.refusals[0].message


def test_source_unknown_signal_on_component_is_refused(api: OcmApi):
    _publish_ejector(api, "com.example.ejector.src2")
    e = _place_tool(
        api, "c-src2", "com.example.pickhead.src2",
        [{"refdes": "VG1", "ref": "com.example.ejector.src2@1.0.0"}],
        signal_source="VG1.not_a_real_signal",
    )
    assert not e.ok
    assert e.refusals[0].code == Codes.INVALID_SOURCE
    assert "not_a_real_signal" in e.refusals[0].message


def test_draft_component_referenced_by_a_published_module_blocks_resolution(api: OcmApi):
    api.create_component_draft("com.example.ejector.draft1", "vacuum_ejector")
    api.update_component("com.example.ejector.draft1", manifest=_ejector_manifest("com.example.ejector.draft1"))
    # never published -- still revision 0.1.0

    e = _place_tool(api, "c-draftcomp", "com.example.pickhead.draftcomp1", [{"refdes": "VG1", "ref": "com.example.ejector.draft1@0.1.0"}])
    assert not e.ok
    assert e.refusals[0].code == Codes.DRAFT_MODULE_REFERENCED
