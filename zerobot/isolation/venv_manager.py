"""Create per-bot virtual environments and install their dependencies."""

import asyncio
import sys
from pathlib import Path


class VenvManager:
    """Manage the directory layout under ``base_path`` and venv operations.

    Each bot gets its own subdirectory ``{base_path}/{bot_id}`` containing a
    standalone ``venv/`` directory plus the bot's source files. Keeping each
    bot in its own venv guarantees that one bot's dependencies cannot conflict
    with another's.
    """

    def __init__(self, base_path: str = "runtime_envs") -> None:
        self.base_path = Path(base_path)
        self.base_path.mkdir(exist_ok=True)

    def get_bot_path(self, bot_id: str) -> Path:
        """Return the per-bot working directory."""
        return self.base_path / bot_id

    def get_venv_path(self, bot_id: str) -> Path:
        """Return the per-bot venv directory."""
        return self.get_bot_path(bot_id) / "venv"

    async def create_venv(self, bot_id: str) -> None:
        """Create the venv if it does not already exist (idempotent)."""
        venv_path = self.get_venv_path(bot_id)

        if venv_path.exists():
            return

        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "venv",
            str(venv_path),
        )

        await process.wait()

    async def install_requirements(self, bot_id: str, requirements: list[str]) -> None:
        """Install *requirements* into *bot_id*'s venv with its own ``pip``."""
        pip_path = self.get_venv_path(bot_id) / "bin" / "pip"

        process = await asyncio.create_subprocess_exec(
            str(pip_path),
            "install",
            *requirements,
        )

        await process.wait()
