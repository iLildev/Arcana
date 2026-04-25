import asyncio
import socket
from pathlib import Path


async def wait_for_port(port: int, timeout: float = 5.0):
    start = asyncio.get_event_loop().time()

    while True:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            await asyncio.sleep(0.2)

        if asyncio.get_event_loop().time() - start > timeout:
            raise TimeoutError(f"Bot on port {port} did not start in time")


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

        await wait_for_port(port)

    async def stop_bot(self, bot_id: str):
        process = self.processes.get(bot_id)

        if not process:
            return

        process.terminate()
        await process.wait()

        del self.processes[bot_id]
