import asyncio
import sys
from pathlib import Path


class VenvManager:
    def __init__(self, base_path: str = "runtime_envs"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(exist_ok=True)

    def get_bot_path(self, bot_id: str) -> Path:
        return self.base_path / bot_id

    def get_venv_path(self, bot_id: str) -> Path:
        return self.get_bot_path(bot_id) / "venv"

    async def create_venv(self, bot_id: str) -> None:
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

    async def install_requirements(self, bot_id: str, requirements: list[str]):
        pip_path = self.get_venv_path(bot_id) / "bin" / "pip"

        process = await asyncio.create_subprocess_exec(
            str(pip_path),
            "install",
            *requirements,
        )

        await process.wait()
