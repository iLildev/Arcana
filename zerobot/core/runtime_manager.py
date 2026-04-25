import asyncio
from pathlib import Path


class RuntimeManager:
    def __init__(self):
        self.processes: dict[str, asyncio.subprocess.Process] = {}

    async def start_bot(
        self,
        bot_id: str,
        bot_path: Path,
        token: str,
        port: int,
    ):
        main_file = bot_path / "main.py"
        venv_python = bot_path / "venv" / "bin" / "python"

        if not venv_python.exists():
            raise RuntimeError(f"Venv python not found for bot {bot_id}")

        process = await asyncio.create_subprocess_exec(
            str(venv_python),
            str(main_file),
            env={
                "BOT_TOKEN": token,
                "BOT_PORT": str(port),
            },
        )

        self.processes[bot_id] = process

    async def stop_bot(self, bot_id: str):
        process = self.processes.get(bot_id)

        if not process:
            return

        process.terminate()
        await process.wait()

        del self.processes[bot_id]
