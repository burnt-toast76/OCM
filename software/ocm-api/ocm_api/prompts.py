# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ADR-0014 zero-assumption doctrine, single-sourced. Every agent-
facing surface that needs to state this rule (the MCP server's
`instructions`, `/agent/chat`'s system prompt) imports it from here rather
than each writing its own paraphrase -- CLAUDE.md's "Authoring from
datasheets (ADR-0014)" section is the canonical prose this mirrors; this
module exists only because CLAUDE.md itself isn't importable code.
"""

from __future__ import annotations

ZERO_ASSUMPTION_DOCTRINE = (
    "A datasheet describes a COMPONENT. Author it as one (create_component_draft / "
    "update_component), by TRANSCRIPTION ONLY: a value goes in only if the source document "
    "states it. Unit conversion and restatement are fine ('~4 min' -> 240 s). Choosing a "
    "single value within a stated range is DESIGN, not transcription -- record the range "
    "(e.g. pressure_bar_min/max) and leave picking an operating point to a module. Anything "
    "the source doesn't answer is OMITTED -- never estimated, never guessed, never copied "
    "from another component's definition, and never marked with an 'ASSUMED:' note; omission "
    "is the honest signal, not an annotation. Leave the draft incomplete and report "
    "validate_component's refusals as the list of what a human must still supply -- an "
    "incomplete-but-honest draft is the intended workflow, not a failure to fix by guessing.\n\n"
    "MODULES are a different, later layer: assemblies plus design judgment (TCP placement, "
    "capabilities, PackML, safety) that a datasheet never answers. Never author or edit a "
    "module from a datasheet alone, and never publish a component -- publishing is a "
    "deliberate human decision made from the checklist panel once a draft is genuinely "
    "complete, not something to do automatically because validation happens to pass."
)
