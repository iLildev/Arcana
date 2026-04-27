"""Tool schemas exposed to Claude + dispatcher that runs them in a sandbox.

Each tool's input schema follows the Anthropic tool-use spec. The dispatcher
returns a string that becomes the ``tool_result`` content block.
"""

from __future__ import annotations

import json
import re
import shlex
from typing import Any
from urllib.parse import urlparse

import httpx

from arcana.agents.sandbox import SandboxError, SandboxManager

WEB_FETCH_TIMEOUT = 15
WEB_FETCH_MAX_BYTES = 64_000

# ── git_clone tool config ─────────────────────────────────────────────────
# We only allow shallow clones from these hosts. Self-hosted Git instances are
# refused on purpose: validating their reachability + safety is out of scope
# for the sandbox, and these two cover the overwhelming majority of imports.
ALLOWED_GIT_HOSTS: frozenset[str] = frozenset({"github.com", "gitlab.com"})

# Conservative cap on clone duration; the per-repo on-disk size is already
# capped via the sandbox's RLIMIT_FSIZE.
GIT_CLONE_TIMEOUT = 90

# Ref names accepted by the optional ``ref`` parameter. Keeps shell-meta out
# of the command line we hand to git.
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9._/\-]{1,200}$")

# Folder name accepted as a clone destination — must be a single path segment
# so we can't escape the workspace via "../".
_SAFE_DIR_RE = re.compile(r"^[A-Za-z0-9._\-]{1,80}$")


class GitImportError(ValueError):
    """Raised when a /import URL fails validation before we touch the sandbox."""


def parse_git_url(url: str) -> tuple[str, str]:
    """Validate *url* and return ``(normalized_https_url, default_dirname)``.

    Accepts ``https://github.com/<owner>/<repo>(.git)?`` and the GitLab
    equivalent (with optional sub-groups). Anything else raises
    :class:`GitImportError`. The returned ``default_dirname`` strips the
    trailing ``.git`` and is safe to use as a workspace folder name.
    """
    if not url or not isinstance(url, str):
        raise GitImportError("URL is required")
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise GitImportError("URL must use the https:// scheme")
    if parsed.hostname not in ALLOWED_GIT_HOSTS:
        raise GitImportError(
            f"only {', '.join(sorted(ALLOWED_GIT_HOSTS))} are allowed"
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise GitImportError("URL must not contain credentials, query, or fragment")
    path = parsed.path.strip("/")
    if not path:
        raise GitImportError("URL is missing the repository path")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    segments = path.split("/")
    if len(segments) < 2 or any(not s for s in segments):
        raise GitImportError("URL must point to <owner>/<repo>")
    for seg in segments:
        # Reject dot-only segments (".", "..") even though the regex would
        # allow them — they're path-traversal bait.
        if seg in {".", ".."} or set(seg) == {"."}:
            raise GitImportError(f"invalid path segment: {seg!r}")
        if not _SAFE_DIR_RE.match(seg):
            raise GitImportError(f"invalid path segment: {seg!r}")
    normalized = f"https://{parsed.hostname}/{path}.git"
    default_dir = segments[-1]
    return normalized, default_dir


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "bash",
        "description": (
            "Execute a bash command inside the user's sandboxed workspace. "
            "cwd is the workspace root. Returns exit code, stdout, and stderr. "
            "Use this for installing packages, running tests, scaffolding "
            "projects, git operations, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 30, max 120).",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read a UTF-8 text file from the workspace. Paths are relative "
            "to the workspace root. Files larger than 64KB are rejected."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Create or overwrite a UTF-8 text file in the workspace. "
            "Parent directories are created automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path."},
                "content": {"type": "string", "description": "Full file contents."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_dir",
        "description": "List entries in a workspace directory (default: workspace root).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative dir path."},
            },
        },
    },
    {
        "name": "web_fetch",
        "description": (
            "HTTP GET a URL and return up to 64KB of the response body as text. "
            "Use this to fetch documentation, raw GitHub files, public APIs, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Absolute http(s) URL."},
            },
            "required": ["url"],
        },
    },
    {
        "name": "git_clone",
        "description": (
            "Shallow-clone a public GitHub or GitLab repository into the user's "
            "workspace. Only https://github.com/ and https://gitlab.com/ URLs "
            "are accepted. Use this when the user wants to import an existing "
            "project to inspect, refactor, or extend."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": (
                        "Full https URL of the repo, e.g. "
                        "https://github.com/owner/repo"
                    ),
                },
                "dest": {
                    "type": "string",
                    "description": (
                        "Optional destination folder name inside the workspace. "
                        "Defaults to the repository name."
                    ),
                },
                "ref": {
                    "type": "string",
                    "description": (
                        "Optional branch or tag to check out. Defaults to the "
                        "remote's default branch."
                    ),
                },
            },
            "required": ["url"],
        },
    },
]


async def execute_tool(
    user_id: str,
    name: str,
    params: dict[str, Any],
    sandbox: SandboxManager,
) -> str:
    """Dispatch a tool call and return its result as a string."""
    try:
        if name == "bash":
            cmd = params.get("command", "")
            timeout = int(params.get("timeout") or 30)
            result = await sandbox.run_bash(user_id, cmd, timeout=timeout)
            return result.as_text()

        if name == "read_file":
            content = sandbox.read_file(user_id, params["path"])
            return content if content else "(empty file)"

        if name == "write_file":
            n = sandbox.write_file(user_id, params["path"], params.get("content", ""))
            return f"wrote {n} bytes to {params['path']}"

        if name == "list_dir":
            entries = sandbox.list_dir(user_id, params.get("path") or ".")
            if not entries:
                return "(empty directory)"
            return json.dumps(entries, ensure_ascii=False, indent=2)

        if name == "web_fetch":
            return await _web_fetch(params["url"])

        if name == "git_clone":
            return await _git_clone(
                user_id,
                sandbox,
                url=params["url"],
                dest=params.get("dest"),
                ref=params.get("ref"),
            )

        return f"error: unknown tool {name!r}"

    except SandboxError as exc:
        return f"error: {exc}"
    except KeyError as exc:
        return f"error: missing required parameter {exc}"
    except Exception as exc:  # noqa: BLE001 — surface to the model as a tool error
        return f"error: {type(exc).__name__}: {exc}"


async def _web_fetch(url: str) -> str:
    """HTTP GET *url* and return up to ``WEB_FETCH_MAX_BYTES`` of its body."""
    if not url.startswith(("http://", "https://")):
        return "error: url must start with http:// or https://"
    async with httpx.AsyncClient(timeout=WEB_FETCH_TIMEOUT, follow_redirects=True) as client:
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            return f"error: fetch failed: {exc}"
    body = resp.text
    truncated = False
    if len(body) > WEB_FETCH_MAX_BYTES:
        body = body[:WEB_FETCH_MAX_BYTES]
        truncated = True
    head = f"HTTP {resp.status_code} ({len(body)} bytes"
    if truncated:
        head += ", truncated"
    head += ")\n"
    return head + body


async def _git_clone(
    user_id: str,
    sandbox: SandboxManager,
    *,
    url: str,
    dest: str | None,
    ref: str | None,
) -> str:
    """Shallow-clone *url* into the user's workspace and report the result.

    The URL is validated before any subprocess runs. The clone is depth=1
    (no full history), runs through the sandbox's bash with its rlimits,
    and writes into a single workspace-relative folder we control.
    """
    try:
        normalized_url, default_dir = parse_git_url(url)
    except GitImportError as exc:
        return f"error: {exc}"

    target_dir = dest or default_dir
    if not _SAFE_DIR_RE.match(target_dir):
        return f"error: invalid dest folder name: {target_dir!r}"

    # Make sure the destination doesn't already exist — refuse instead of
    # silently merging into a half-cloned tree.
    try:
        existing = sandbox.list_dir(user_id, target_dir)
    except SandboxError:
        existing = None
    if existing is not None:
        return (
            f"error: destination {target_dir!r} already exists in the workspace; "
            "remove it first or pass a different `dest`."
        )

    parts = ["git", "clone", "--depth=1"]
    if ref:
        if not _SAFE_REF_RE.match(ref):
            return f"error: invalid ref name: {ref!r}"
        parts += ["--branch", ref, "--single-branch"]
    parts += [normalized_url, target_dir]
    command = " ".join(shlex.quote(p) for p in parts)

    result = await sandbox.run_bash(user_id, command, timeout=GIT_CLONE_TIMEOUT)
    if result.returncode == 0:
        head = (
            f"✅ cloned {normalized_url} into {target_dir}/ "
            f"(depth=1{f', ref={ref}' if ref else ''})\n"
        )
        return head + result.as_text()
    return "❌ clone failed\n" + result.as_text()
