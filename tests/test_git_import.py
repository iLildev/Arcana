"""Tests for the GitHub / GitLab repo-import feature.

Covers two layers:

* Pure URL validation (:func:`arcana.agents.tools.parse_git_url`) — runs in
  isolation, no I/O.
* The ``git_clone`` tool dispatcher in :func:`arcana.agents.tools.execute_tool`,
  exercised against a real :class:`SandboxManager` but with the ``git``
  subprocess monkey-patched to a stub so the test stays hermetic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arcana.agents import tools
from arcana.agents.sandbox import BashResult, SandboxManager
from arcana.agents.tools import (
    GitImportError,
    execute_tool,
    parse_git_url,
)

# ─────────────── parse_git_url ───────────────


@pytest.mark.parametrize(
    "url,expected_normalized,expected_dir",
    [
        (
            "https://github.com/owner/repo",
            "https://github.com/owner/repo.git",
            "repo",
        ),
        (
            "https://github.com/owner/repo.git",
            "https://github.com/owner/repo.git",
            "repo",
        ),
        (
            "  https://gitlab.com/group/sub/proj  ",  # whitespace tolerated
            "https://gitlab.com/group/sub/proj.git",
            "proj",
        ),
        (
            "https://gitlab.com/group/sub/proj.git",
            "https://gitlab.com/group/sub/proj.git",
            "proj",
        ),
    ],
)
def test_parse_git_url_accepts_valid_https_urls(
    url: str, expected_normalized: str, expected_dir: str
) -> None:
    normalized, default_dir = parse_git_url(url)
    assert normalized == expected_normalized
    assert default_dir == expected_dir


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "http://github.com/owner/repo",       # http, not https
        "ftp://github.com/owner/repo",        # wrong scheme
        "https://bitbucket.org/owner/repo",   # disallowed host
        "https://github.com/",                 # no path
        "https://github.com/owner",            # missing repo segment
        "https://github.com/owner/repo?token=abc",  # query disallowed
        "https://github.com/owner/repo#frag",  # fragment disallowed
        "https://user:pwd@github.com/owner/repo",  # credentials disallowed
        "https://github.com/owner/repo with spaces",  # invalid segment
        "https://github.com/owner/../etc",     # path traversal in segment
    ],
)
def test_parse_git_url_rejects_bad_urls(url: str) -> None:
    with pytest.raises(GitImportError):
        parse_git_url(url)


def test_parse_git_url_rejects_non_string() -> None:
    with pytest.raises(GitImportError):
        parse_git_url(None)  # type: ignore[arg-type]


# ─────────────── git_clone tool dispatch ───────────────


@pytest.fixture
def sandbox(tmp_path: Path) -> SandboxManager:
    return SandboxManager(base_dir=tmp_path)


async def test_git_clone_rejects_invalid_url(sandbox: SandboxManager) -> None:
    """A bad URL never reaches the bash subprocess."""
    out = await execute_tool(
        "user-1",
        "git_clone",
        {"url": "https://example.com/some/repo"},
        sandbox,
    )
    assert out.startswith("error: only ")
    assert "github.com" in out and "gitlab.com" in out


async def test_git_clone_invokes_bash_with_safe_command(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxManager
) -> None:
    """The dispatcher builds a depth=1 clone command and surfaces success."""
    captured: dict[str, object] = {}

    async def fake_run_bash(self: SandboxManager, user_id: str, command: str, timeout: int = 30):
        captured["user_id"] = user_id
        captured["command"] = command
        captured["timeout"] = timeout
        return BashResult(stdout="Cloning into 'repo'...\n", stderr="", returncode=0)

    monkeypatch.setattr(SandboxManager, "run_bash", fake_run_bash)

    out = await execute_tool(
        "user-2",
        "git_clone",
        {"url": "https://github.com/owner/repo"},
        sandbox,
    )

    assert out.startswith("✅ cloned https://github.com/owner/repo.git into repo/")
    assert captured["user_id"] == "user-2"
    cmd = str(captured["command"])
    assert cmd.startswith("git clone --depth=1 ")
    assert "https://github.com/owner/repo.git" in cmd
    # No --branch when no ref is given.
    assert "--branch" not in cmd
    # And no shell metacharacters slipped through.
    assert "&&" not in cmd and "|" not in cmd and ";" not in cmd
    assert captured["timeout"] == tools.GIT_CLONE_TIMEOUT


async def test_git_clone_passes_validated_ref(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxManager
) -> None:
    captured: dict[str, str] = {}

    async def fake_run_bash(self, user_id, command, timeout=30):
        captured["command"] = command
        return BashResult(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(SandboxManager, "run_bash", fake_run_bash)

    out = await execute_tool(
        "user-3",
        "git_clone",
        {"url": "https://github.com/owner/repo", "ref": "main"},
        sandbox,
    )
    assert out.startswith("✅")
    assert "--branch main --single-branch" in captured["command"]


async def test_git_clone_rejects_ref_with_shell_meta(sandbox: SandboxManager) -> None:
    out = await execute_tool(
        "user-4",
        "git_clone",
        {"url": "https://github.com/owner/repo", "ref": "main; rm -rf /"},
        sandbox,
    )
    assert out.startswith("error: invalid ref name")


async def test_git_clone_refuses_existing_destination(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxManager
) -> None:
    """If the dest folder already exists we refuse instead of merging."""
    sandbox.write_file("user-5", "existing/keep.txt", "hi")

    async def boom(self, user_id, command, timeout=30):  # pragma: no cover - must not be called
        raise AssertionError("run_bash should not be invoked when dest exists")

    monkeypatch.setattr(SandboxManager, "run_bash", boom)

    out = await execute_tool(
        "user-5",
        "git_clone",
        {"url": "https://github.com/owner/repo", "dest": "existing"},
        sandbox,
    )
    assert "already exists" in out


async def test_git_clone_surfaces_failure(
    monkeypatch: pytest.MonkeyPatch, sandbox: SandboxManager
) -> None:
    async def fake_run_bash(self, user_id, command, timeout=30):
        return BashResult(stdout="", stderr="fatal: repository not found", returncode=128)

    monkeypatch.setattr(SandboxManager, "run_bash", fake_run_bash)

    out = await execute_tool(
        "user-6",
        "git_clone",
        {"url": "https://github.com/owner/repo"},
        sandbox,
    )
    assert out.startswith("❌ clone failed")
    assert "repository not found" in out
