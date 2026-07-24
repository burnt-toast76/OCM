# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one canonical ruamel round-trip YAML configuration every writer of
an OCM manifest shares -- comment-preserving (`typ="rt"`), no line-wrap,
this repo's own sequence=2/offset=0 block-sequence indent.

Lives in ocm-core, not ocm-api, deliberately: ocm-core is the dependency
floor (no sibling-package imports at all), so anything that needs to
canonicalize a manifest's YAML formatting -- the GUI/agent write path
(ocm_api.workspace.write_yaml) and the standalone `ocm fmt` CLI
(ocm_generator.cli.cmd_fmt) alike -- can import this one function without
pulling in fastapi, anthropic, mcp, or ocm_generator/ocm_resolve just to
format a file. `ocm fmt` importing `ocm_api.workspace` for this used to
drag in ocm_api's own `from .api import OcmApi` -> ... ->
`ocm_generator.scene` -> `from ocm_resolve import ResolvedCell` chain,
breaking any environment that installed ocm-core/ocm-api/ocm-generator but
not ocm-resolve (exactly the shape a CI job formatting YAML has no other
reason to need). Both callers now import this module directly instead.
"""

from __future__ import annotations

from ruamel.yaml import YAML


def new_yaml_rt() -> YAML:
    # A fresh instance per call, not a module-level singleton: ruamel's
    # YAML object is stateful (its emitter/parser carry position and
    # anchor state across a load/dump), and isn't safe for concurrent use
    # -- two threads round-tripping *different* files through one shared
    # instance at the same time corrupted output with errors like
    # "EmitterError: expected NodeEvent, but got DocumentStartEvent()".
    # Every caller must construct its own; see each caller's own locking/
    # sequencing story for why reuse isn't needed to get atomicity too.
    yaml_rt = YAML(typ="rt")
    yaml_rt.preserve_quotes = True
    yaml_rt.width = 100_000  # never line-wrap -- wrapping would show up as diff noise unrelated to the actual change
    yaml_rt.indent(mapping=2, sequence=2, offset=0)  # this repo's own convention: block sequences flush with their parent key
    return yaml_rt
