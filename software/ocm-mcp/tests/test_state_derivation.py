# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which commit answered (ADR-0036 D8), when the root is not a checkout.

A registry root is normally a git working tree and the state is its
commit. A baked container image is the case that breaks that assumption:
the registry arrives as plain files, the history is left behind, and the
git derivation has nothing to read. Falling back to "untracked" is honest
but useless -- the envelope promises which corpus commit answered, and
"untracked" answers nothing.

So a snapshot records its commit at build time in `.ocm-state`, and this
is the file's contract: read verbatim, never trusted over git, never
served unless it is exactly one full commit hash.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ocm_mcp.index import STATE_FILE, _serving_state

COMMIT = "a417e327a220496d191cb0ccecf81e3312a7edf8"
OTHER = "b77cc8243af4fa815b796daa11d5edfbd08924e7"


def _write_state(root: Path, text: str) -> None:
    (root / STATE_FILE).write_text(text, encoding="utf-8")


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A real git working tree with one commit, so the git path is
    exercised rather than simulated."""
    root = tmp_path / "checkout"
    (root / "claims").mkdir(parents=True)
    (root / "claims" / "keep.txt").write_text("x", encoding="utf-8")
    run = lambda *args: subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    run("init", "-q")
    run("config", "user.email", "tests@example.invalid")
    run("config", "user.name", "tests")
    run("add", "-A")
    run("commit", "-qm", "one")
    return root


# -- the snapshot case, which is why the fallback exists -----------------


def test_a_state_file_answers_when_there_is_no_git(tmp_path: Path):
    _write_state(tmp_path, COMMIT)
    assert _serving_state(tmp_path) == COMMIT


def test_the_state_file_is_served_verbatim_with_no_dirty_suffix(tmp_path: Path):
    """An image is immutable, so there is nothing for `dirty` to mean.
    Appending it would invent a distinction the artifact cannot have."""
    _write_state(tmp_path, COMMIT)
    assert _serving_state(tmp_path) == COMMIT
    assert not _serving_state(tmp_path).endswith("-dirty")


def test_surrounding_whitespace_is_tolerated(tmp_path: Path):
    """`printf` and `echo` disagree about trailing newlines, and a build
    recipe should not have to care which one it used."""
    _write_state(tmp_path, f"  {COMMIT}\n")
    assert _serving_state(tmp_path) == COMMIT


# -- git always wins ----------------------------------------------------


def test_git_wins_over_a_stale_state_file(checkout: Path):
    """A checkout can move; a file recorded when it was built cannot. A
    stale `.ocm-state` in a working tree would otherwise pin the identity
    to whatever it said the day it was written -- exactly the silent
    downgrade this field exists to prevent."""
    _write_state(checkout, OTHER)
    state = _serving_state(checkout)
    assert state != OTHER
    assert state.startswith(subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip())


def test_git_still_reports_dirty_with_a_state_file_present(checkout: Path):
    """The developer's case, unchanged in every particular."""
    _write_state(checkout, OTHER)
    (checkout / "claims" / "new.txt").write_text("y", encoding="utf-8")
    assert _serving_state(checkout).endswith("-dirty")


# -- garbage is never served as a commit --------------------------------


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("", id="empty"),
        pytest.param("untracked", id="a-word"),
        pytest.param(COMMIT[:39], id="one-short"),
        pytest.param(COMMIT + "0", id="one-long"),
        pytest.param(COMMIT.upper(), id="uppercase"),
        pytest.param(f"{COMMIT}-dirty", id="with-a-dirty-suffix"),
        pytest.param(f"{COMMIT}\n{OTHER}", id="two-lines"),
        pytest.param("../../etc/passwd", id="a-path"),
    ],
)
def test_a_malformed_state_file_falls_through_to_untracked(tmp_path: Path, content: str):
    """Better to say nothing than to serve something shaped like an answer.
    `untracked` is unmistakable; a half-hash in an envelope is not."""
    _write_state(tmp_path, content)
    assert _serving_state(tmp_path) == "untracked"


def test_no_git_and_no_file_is_still_untracked(tmp_path: Path):
    assert _serving_state(tmp_path) == "untracked"


def test_a_directory_named_like_the_state_file_does_not_crash(tmp_path: Path):
    """Reading a directory raises OSError, not a missing-file error, and
    the caller gets the same honest floor either way."""
    (tmp_path / STATE_FILE).mkdir()
    assert _serving_state(tmp_path) == "untracked"
