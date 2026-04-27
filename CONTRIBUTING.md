# Contributing to Arcana

Thanks for your interest in improving Arcana — pull requests, bug reports,
and design discussions are all welcome.

## Ground rules

- Be kind. Reviewers and contributors are volunteers.
- Keep pull requests **focused**: one logical change per PR.
- Match the existing style. The repo enforces `ruff` for both linting and
  formatting; please run it before pushing (see below).
- Don't break public APIs (`/admin/*`, `/users/*`, `/bots/*` routes) without
  a discussion in an issue first.

## Local setup

```bash
# 1. Install dependencies (pip or uv both work).
pip install -e ".[dev]"

# 2. Copy env template and fill in real values.
cp .env.example .env

# 3. Bring up Postgres locally (any 14+ instance is fine), then bootstrap.
python -m arcana.main
```

See the **Running** section of `README.md` for how to start each individual
service (gateway, admin console, user console, Builder Bot, Manager Bot).

## Code style

We use [Ruff](https://docs.astral.sh/ruff/) for both linting and formatting.
Before opening a PR, run:

```bash
ruff check arcana
ruff format arcana
```

The configuration lives under `[tool.ruff]` in `pyproject.toml`. Highlights:

- Line length: **100**.
- Import order is auto-managed by Ruff (`I` rule).
- We use modern Python 3.11+ syntax (`list[int]`, `X | Y`, etc.).
- Public functions and classes should have a one-line docstring.
- Keep modules small and focused; prefer one responsibility per file.

## Commit messages

Use short, imperative summaries. Example:

```
Add /restart admin command to manager bot

- POST /admin/bots/{bot_id}/restart endpoint
- Wires reap → wake into a single op
```

## Adding a new tool to the Builder Agent

1. Add the schema entry in `arcana/agents/tools.py::TOOL_SCHEMAS`.
2. Implement the dispatcher branch in `execute_tool`.
3. Make sure every filesystem access goes through `SandboxManager.resolve`
   so the sandbox boundary stays intact.
4. Update the README's tool list.

## Reporting a security issue

Please **do not** open a public issue for vulnerabilities. Email the
maintainer (see `SECURITY.md` for the disclosure process) and allow time
for a fix before disclosure.
