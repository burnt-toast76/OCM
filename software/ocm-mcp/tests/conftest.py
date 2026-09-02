# SPDX-License-Identifier: AGPL-3.0-or-later
"""One index over the real committed registry, shared across the suite
-- the golden evals target the registry as committed, so the repo root
IS the fixture (same posture as ocm-api's conftest, without the copy:
nothing here writes)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ocm_mcp import build_index

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def shared_index():
    return build_index(REPO_ROOT)
