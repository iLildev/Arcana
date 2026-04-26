"""Tool schemas exposed to Claude + dispatcher that runs them in a sandbox.

Each tool's input schema follows the Anthropic tool-use spec. The dispatcher
returns a string that becomes the ``tool_result`` content block.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from zerobot.agents.sandbox import SandboxError, SandboxManager

WEB_FETCH_TIMEOUT = 15
WEB_FETCH_MAX_BYTES = 64_000


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
