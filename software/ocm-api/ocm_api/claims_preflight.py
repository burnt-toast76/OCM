# SPDX-License-Identifier: AGPL-3.0-or-later
"""Extraction preflight for datasheet/catalog pages (ADR-0035 D6).

Transcription against a lossy text extraction fails in known ways, and
every detector here corresponds to a real incident from this repo's own
ingestion history:

- interleaved glyph runs: column collisions in the text layer turn
  "Approx. 20g" into "Ap 2 p 0 r g ox." (FS-N40 catalog p19);
- merge-suspect cells: a value printed once across two table rows comes
  back as an empty grid cell (FU-67TG's minimum bend radius);
- lookalike glyphs: the text layer substituted "ø" for the printed "±",
  and the same document mixes ° (U+00B0) with ˚ (U+02DA) and µ (U+00B5)
  with μ (U+03BC);
- cross-extraction disagreement: the table grid dropped an entire model
  column the text layer still carried.

The preflight REPORTS hazards; it never fixes them. Resolution is
against the rendered page image (see render_page) or the cell is
skipped and the skip named -- the tool makes "didn't notice" impossible,
not judgment unnecessary. The interleave detector may PROPOSE a
de-interleaved reading (unzipping alternate tokens), same
propose-don't-write posture as claims_split.

The detectors are pure functions over extracted text and grids so they
test without PDFs. preflight_page/render_page need the `ingest` extra
(pdfplumber, pypdfium2) and say so when it is absent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Confusable glyphs the text layer has actually substituted or mixed.
SUSPECT_GLYPHS: dict[str, str] = {
    "ø": "U+00F8 (o-slash; has stood in for a printed ±)",
    "Ø": "U+00D8 (O-slash)",
    "±": "U+00B1 (plus-minus)",
    "µ": "U+00B5 (micro sign)",
    "μ": "U+03BC (Greek mu; documents mix this with U+00B5)",
    "°": "U+00B0 (degree sign)",
    "˚": "U+02DA (ring above; documents mix this with U+00B0)",
    "′": "U+2032 (prime)",
    "″": "U+2033 (double prime)",
}

_MODEL_TOKEN = re.compile(r"\b[A-Z]{2}-[0-9A-Z]+\b")


@dataclass
class Hazard:
    kind: str  # interleave | glyph | merge_suspect | cross_missing
    where: str
    detail: str
    proposal: str | None = None


@dataclass
class PreflightReport:
    page: int | None
    hazards: list[Hazard] = field(default_factory=list)

    def by_kind(self, kind: str) -> list[Hazard]:
        return [h for h in self.hazards if h.kind == kind]


def find_interleaved_runs(text: str) -> list[Hazard]:
    """A run of five or more short tokens (each <= 3 chars) containing at
    least four single-character tokens and both letters and digits is
    almost never prose -- it is two print columns shuffled together.
    (Three singletons is still prose: "500 m / s2; 3 times each".)
    The proposal unzips alternate tokens into the two likely streams.
    """
    hazards: list[Hazard] = []
    for line in text.splitlines():
        tokens = line.split()
        run: list[str] = []
        for token in tokens + [""]:
            if token and len(token) <= 3:
                run.append(token)
                continue
            if len(run) >= 5:
                singles = sum(1 for t in run if len(t) == 1)
                has_alpha = any(any(c.isalpha() for c in t) for t in run)
                has_digit = any(any(c.isdigit() for c in t) for t in run)
                if singles >= 4 and has_alpha and has_digit:
                    evens = "".join(run[0::2])
                    odds = "".join(run[1::2])
                    hazards.append(
                        Hazard(
                            kind="interleave",
                            where=line.strip()[:80],
                            detail=f"{len(run)} short tokens with {singles} singletons -- likely two print columns shuffled together",
                            proposal=f"unzipped streams: {evens!r} / {odds!r} -- verify against the page image",
                        )
                    )
            run = []
    return hazards


def find_suspect_glyphs(text: str) -> list[Hazard]:
    hazards: list[Hazard] = []
    for glyph, description in SUSPECT_GLYPHS.items():
        count = text.count(glyph)
        if count:
            hazards.append(
                Hazard(
                    kind="glyph",
                    where=f"{count} occurrence(s) of {glyph!r}",
                    detail=f"{description}; confirm against the page image before transcribing verbatim",
                )
            )
    return hazards


def find_merge_suspects(table: list[list[Any]]) -> list[Hazard]:
    """An empty cell in a mostly-populated data row, with a populated
    neighbour in the same column, is usually a merged cell whose value
    prints once for several rows. Never fill it from a guess: resolve
    against the page image or skip-and-name.
    """
    hazards: list[Hazard] = []
    for r, row in enumerate(table):
        populated = [c for c in row if c not in (None, "")]
        if len(populated) < max(2, len(row) // 2):
            continue  # header/spacer rows are mostly empty; not data
        for col, cell in enumerate(row):
            if cell not in (None, ""):
                continue
            above = table[r - 1][col] if r > 0 and col < len(table[r - 1]) else None
            below = table[r + 1][col] if r + 1 < len(table) and col < len(table[r + 1]) else None
            if above not in (None, "") or below not in (None, ""):
                hazards.append(
                    Hazard(
                        kind="merge_suspect",
                        where=f"row {r}, column {col}",
                        detail="empty cell in a populated data row with a populated column neighbour -- possibly a value shared across merged rows",
                    )
                )
    return hazards


def cross_check_models(text: str, tables: list[list[list[Any]]]) -> list[Hazard]:
    """Part-number-shaped tokens present in one extraction and missing
    from the other. The table grid has silently dropped whole model
    columns; the text layer has garbled tokens the grid kept.
    """
    text_models = set(_MODEL_TOKEN.findall(text))
    grid_text = " ".join(str(cell) for table in tables for row in table for cell in row if cell)
    grid_models = set(_MODEL_TOKEN.findall(grid_text))
    hazards: list[Hazard] = []
    for model in sorted(text_models - grid_models):
        hazards.append(
            Hazard(kind="cross_missing", where=model, detail="in the text layer but missing from every table grid -- the grid may have dropped its column; map rows to models by hand")
        )
    for model in sorted(grid_models - text_models):
        hazards.append(
            Hazard(kind="cross_missing", where=model, detail="in a table grid but missing from the text layer -- the text layer may have garbled it")
        )
    return hazards


def preflight_text_and_tables(text: str, tables: list[list[list[Any]]], page: int | None = None) -> PreflightReport:
    report = PreflightReport(page=page)
    report.hazards.extend(find_interleaved_runs(text))
    report.hazards.extend(find_suspect_glyphs(text))
    for table in tables:
        report.hazards.extend(find_merge_suspects(table))
    report.hazards.extend(cross_check_models(text, tables))
    return report


def preflight_page(pdf_path: str | Path, page_index: int) -> PreflightReport:
    """Run every detector over one PDF page (0-based index). Needs the
    `ingest` extra."""
    try:
        import pdfplumber
    except ImportError as e:  # pragma: no cover -- environment-dependent
        raise RuntimeError("preflight_page needs pdfplumber: pip install 'ocm-api[ingest]'") from e

    with pdfplumber.open(str(pdf_path)) as pdf:
        page = pdf.pages[page_index]
        text = page.extract_text() or ""
        tables = page.extract_tables() or []
    return preflight_text_and_tables(text, tables, page=page_index + 1)


def render_page(pdf_path: str | Path, page_index: int, out_path: str | Path, scale: float = 3.0) -> Path:
    """Render one PDF page (0-based index) to a PNG -- the arbiter every
    hazard is resolved against. Needs the `ingest` extra."""
    try:
        import pypdfium2
    except ImportError as e:  # pragma: no cover -- environment-dependent
        raise RuntimeError("render_page needs pypdfium2: pip install 'ocm-api[ingest]'") from e

    pdf = pypdfium2.PdfDocument(str(pdf_path))
    try:
        bitmap = pdf[page_index].render(scale=scale)
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        bitmap.to_pil().save(str(out))
    finally:
        pdf.close()
    return out
