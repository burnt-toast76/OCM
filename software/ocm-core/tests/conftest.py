# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path

import pytest

# tests/conftest.py -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def schema_path(repo_root: Path) -> Path:
    return repo_root / "spec" / "schema" / "ocm-module-1.0.schema.json"


@pytest.fixture
def sd50_path(repo_root: Path) -> Path:
    return repo_root / "modules" / "com.accelsolutions.screwdriver.sd50" / "module.yaml"


@pytest.fixture
def dh200_path(repo_root: Path) -> Path:
    return repo_root / "modules" / "com.accelsolutions.dispense.dh200" / "module.yaml"


@pytest.fixture
def gocator_path(repo_root: Path) -> Path:
    return repo_root / "modules" / "com.lmi.gocator.2350" / "module.yaml"


@pytest.fixture
def bracket_cell_path(repo_root: Path) -> Path:
    return repo_root / "cells" / "bracket-asm-01" / "cell.yaml"
