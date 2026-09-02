# SPDX-License-Identifier: AGPL-3.0-or-later
"""Extraction preflight detectors (ADR-0035 D6). Every fixture is a real
incident from this repo's ingestion of the FS-N41N datasheet and FS-N40
catalog -- the detectors are graded against exactly the failures that
happened, not invented ones."""

from __future__ import annotations

from ocm_api.claims_preflight import (
    cross_check_models,
    find_interleaved_runs,
    find_merge_suspects,
    find_suspect_glyphs,
    preflight_text_and_tables,
)

# Verbatim from the FS-N40 catalog page 19 text layer: "Approx. 20g"
# with the model-column glyphs shuffled in.
INTERLEAVED_LINE = 'M3 (- − 4 4 0 0 t t o o + + 1 5 2 0 2 ° ° C F) R0.39" 130 5.12" Ap 2 p 0 r g ox.'


def test_interleaved_run_is_flagged_with_an_unzip_proposal():
    hazards = find_interleaved_runs("Ap 2 p 0 r g ox.")
    assert len(hazards) == 1
    assert hazards[0].kind == "interleave"
    # The unzip recovers both print streams.
    assert "Approx." in hazards[0].proposal
    assert "20g" in hazards[0].proposal


def test_the_real_catalog_line_is_flagged():
    assert find_interleaved_runs(INTERLEAVED_LINE)


def test_ordinary_spec_prose_is_not_flagged():
    for line in (
        "1 m 3.3' Cut not allowed",
        '590 23.23" 540 21.26" 190 7.48" FU-2303',
        "500 m / s2; 3 times each for X, Y, and Z axes",
    ):
        assert find_interleaved_runs(line) == [], line


def test_suspect_glyphs_are_inventoried():
    # The catalog printed ± as ø in the text layer, and mixes mu and
    # degree codepoints.
    hazards = find_suspect_glyphs('Free-cut (ø1.3 ø0.05" × 2)  23 μs  +50˚C')
    kinds = {h.where.split(" of ")[1] for h in hazards}
    assert "'ø'" in kinds and "'μ'" in kinds and "'˚'" in kinds


def test_plain_text_has_no_glyph_hazards():
    assert find_suspect_glyphs("10 to 30 VDC, class 2 or LPS") == []


def test_merge_suspect_is_the_fu67tg_bend_radius_shape():
    # Modeled on catalog p19: FU-67TG's row is populated except the bend
    # radius cell, which the print merges with FU-67MTG's row below.
    table = [
        ["Type", "Appearance", "Bend radius", "Distance"],
        ["Hex", "17 0.67", 'R10 R0.39"', "900"],
        ["Hex", "20.5 0.81", "", "900"],
        ["Hex", "22.5 0.89", 'R25 R0.98"', "580"],
    ]
    hazards = find_merge_suspects(table)
    assert [h.where for h in hazards] == ["row 2, column 2"]


def test_mostly_empty_header_rows_are_not_merge_suspects():
    table = [
        ["Type", "", "", ""],
        ["", "TERA", "", ""],
        ["Hex", "17", "R10", "900"],
    ]
    assert find_merge_suspects(table) == []


def test_cross_check_catches_the_dropped_model_column():
    # p19's table grid came back with the model/weight column empty while
    # the text layer still carried every model name.
    text = "590 FU-2303 ... 590 FU-35FG ... 900 FU-67TG"
    tables = [[["590", ""], ["590", ""], ["900", ""]]]
    hazards = cross_check_models(text, tables)
    assert {h.where for h in hazards} == {"FU-2303", "FU-35FG", "FU-67TG"}
    assert all("missing from every table grid" in h.detail for h in hazards)


def test_cross_check_is_quiet_when_both_extractions_agree():
    text = "590 FU-2303"
    tables = [[["590", "FU-2303"]]]
    assert cross_check_models(text, tables) == []


def test_the_report_aggregates_all_detectors():
    report = preflight_text_and_tables(
        INTERLEAVED_LINE + "\nFU-2303 is only here",
        [[["a", "b", "c", "d"], ["a", "", "c", "d"], ["a", "b", "c", "d"]]],
        page=19,
    )
    assert report.page == 19
    assert report.by_kind("interleave")
    assert report.by_kind("glyph")  # the ° in the interleaved line
    assert report.by_kind("merge_suspect")
    assert report.by_kind("cross_missing")
