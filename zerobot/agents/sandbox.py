"""Per-user sandboxed workspace for the Builder Agent.

Each user gets an isolated directory under
``runtime_envs/builder_sessions/{user_id}/workspace`` where the agent can
read, write, and execute commands. All file operations validate that the
requested path stays inside the workspace; the bash tool runs with ``cwd``
pinned to the workspace and a minimal environment.

This is filesystem-level isolation, not VM-grade. It is sufficient for
trusted users (the platform owner + invited collaborators). For untrusted
multi-tenant use, layer namespaces / nsjail / containers in a later phase.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE_DIR = Path("runtime_envs/builder_sessions")
MAX_OUTPUT_BYTES = 8_192  # truncate stdout / stderr to this many bytes
MAX_FILE_READ_BYTES = 64_000  # refuse to read files larger than this
DEFAULT_BASH_TIMEOUT = 30  # seconds
HARD_BASH_TIMEOUT = 120  # absolute upper bound

# Only forward these env vars from the host to bash subprocesses, so the
# agent cannot trivially read API keys or other secrets out of os.environ.
SAFE_ENV_KEYS = {"LANG", "LC_ALL", "TERM"}


@dataclass
class BashResult:
    """Captured output of a single bash invocation."""

    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False
    truncated: bool = False

    def as_text(self) -> str:
        """Render the result as a single string suitable for the LLM."""
        parts = [f"exit={self.returncode}"]
        if self.timed_out:
            parts.append("(timed out)")
        if self.truncated:
            parts.append("(output truncated)")
        head = " ".join(parts)
        body = []
        if self.stdout:
            body.append(f"--- stdout ---\n{self.stdout}")
        if self.stderr:
            body.append(f"--- stderr ---\n{self.stderr}")
        return head + ("\n" + "\n".join(body) if body else "")


class SandboxError(Exception):
    """Raised on any policy violation (path escape, oversize file, …)."""


class SandboxManager:
    """Coordinator for per-user workspaces and the operations on them."""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else DEFAULT_BASE_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # ── workspace lifecycle ─────────────────────────────────────────────────

    def workspace(self, user_id: str) -> Path:
        """Return (creating if needed) the absolute workspace path for a user."""
        if not user_id or "/" in user_id or user_id.startswith("."):
            raise SandboxError(f"invalid user_id: {user_id!r}")
        ws = (self.base_dir / user_id / "workspace").resolve()
        ws.mkdir(parents=True, exist_ok=True)
        return ws

    def reset_workspace(self, user_id: str) -> None:
        """Wipe and recreate a user's workspace (used by the ``/reset`` command)."""
        ws = self.workspace(user_id)
        for entry in ws.iterdir():
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                with contextlib.suppress(OSError):
                    entry.unlink()

    # ── path safety ─────────────────────────────────────────────────────────

    def resolve(self, user_id: str, requested: str) -> Path:
        """Resolve *requested* relative to the user's workspace.

        Rejects absolute paths, parent escapes, and symlinks that would
        leave the workspace.
        """
        ws = self.workspace(user_id)
        if not requested or requested.strip() == "":
            raise SandboxError("empty path")
        if requested.startswith("/") or requested.startswith("~"):
            raise SandboxError(
                f"absolute paths are not allowed; use a workspace-relative path: {requested!r}"
            )
        candidate = (ws / requested).resolve()
        try:
            candidate.relative_to(ws)
        except ValueError as exc:
            raise SandboxError(f"path escapes workspace: {requested!r}") from exc
        return candidate

    # ── file operations ─────────────────────────────────────────────────────

    def read_file(self, user_id: str, path: str) -> str:
        """Read a UTF-8 text file from the user's workspace."""
        target = self.resolve(user_id, path)
        if not target.exists():
            raise SandboxError(f"not found: {path}")
        if target.is_dir():
            raise SandboxError(f"is a directory: {path}")
        size = target.stat().st_size
        if size > MAX_FILE_READ_BYTES:
            raise SandboxError(f"file too large ({size} bytes > {MAX_FILE_READ_BYTES})")
        try:
            return target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise SandboxError(f"binary file (not UTF-8): {path}") from exc

    def write_file(self, user_id: str, path: str, content: str) -> int:
        """Write *content* (UTF-8) to *path* and return the byte count."""
        target = self.resolve(user_id, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8")
        target.write_bytes(data)
        return len(data)

    def list_dir(self, user_id: str, path: str = ".") -> list[dict]:
        """Return a sorted listing of *path* inside the user's workspace."""
        target = self.resolve(user_id, path)
        if not target.exists():
            raise SandboxError(f"not found: {path}")
        if not target.is_dir():
            raise SandboxError(f"not a directory: {path}")
        entries = []
        for child in sorted(target.iterdir()):
            try:
                stat = child.stat()
                entries.append(
                    {
                        "name": child.name,
                        "kind": "dir" if child.is_dir() else "file",
                        "size": stat.st_size if child.is_file() else None,
                    }
                )
            except OSError:
                continue
        return entries

    # ── bash ────────────────────────────────────────────────────────────────

    async def run_bash(
        self,
        user_id: str,
        command: str,
        timeout: int = DEFAULT_BASH_TIMEOUT,
    ) -> BashResult:
        """Execute *command* inside the user's workspace.

        ``cwd`` is pinned to the workspace and the environment is whittled
        down to a minimal set so the agent can't trivially read host secrets.
        """
        if not command or not command.strip():
            raise SandboxError("empty command")
        timeout = min(max(1, int(timeout)), HARD_BASH_TIMEOUT)
        ws = self.workspace(user_id)

        env = {k: v for k, v in os.environ.items() if k in SAFE_ENV_KEYS}
        env.update(
            {
                "HOME": str(ws),
                "PWD": str(ws),
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "USER": f"builder-{user_id}",
                "SHELL": "/bin/bash",
            }
        )

        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(ws),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        timed_out = False
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            timed_out = True
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            stdout_b, stderr_b = await proc.communicate()

        truncated = False
        if len(stdout_b) > MAX_OUTPUT_BYTES:
            stdout_b = stdout_b[:MAX_OUTPUT_BYTES]
            truncated = True
        if len(stderr_b) > MAX_OUTPUT_BYTES:
            stderr_b = stderr_b[:MAX_OUTPUT_BYTES]
            truncated = True

        return BashResult(
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
            returncode=proc.returncode if proc.returncode is not None else -1,
            timed_out=timed_out,
            truncated=truncated,
        )
