"""High-level lifecycle for bots: plant, wake, and reap.

The orchestrator is the only component that touches the database, the venv
manager, the port registry, and the runtime manager together. Every consumer
(the FastAPI consoles, the gateway, the manager bot) goes through it instead
of orchestrating those services directly.
"""

import json
import shutil
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from zerobot.core.runtime_manager import RuntimeManager
from zerobot.database.models import Bot
from zerobot.database.port_registry import PortManager
from zerobot.database.wallet import WalletService
from zerobot.isolation.venv_manager import VenvManager

# Default starter template copied into a freshly planted bot's directory.
TEMPLATE_PATH = Path("zerobot/templates/base_template")


class Orchestrator:
    """Coordinator for the platform's bot lifecycle."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.wallet = WalletService(session)
        self.ports = PortManager(session)
        self.venv = VenvManager()
        self.runtime = RuntimeManager()

    async def plant_bot(
        self,
        bot_id: str,
        user_id: str,
        token: str,
    ) -> None:
        """Create a brand-new bot end-to-end: charge → reserve → install → run."""
        # 1. Charge the user's wallet for the planting fee.
        await self.wallet.charge(user_id, 1)

        # 2. Reserve a free port from the registry.
        port = await self.ports.reserve_port(bot_id)

        # 3. Create an isolated virtualenv for the bot.
        await self.venv.create_venv(bot_id)

        # 4. Copy the starter template into the bot's directory.
        bot_path = self.venv.get_bot_path(bot_id)
        if not (bot_path / "main.py").exists():
            shutil.copytree(TEMPLATE_PATH, bot_path, dirs_exist_ok=True)

        # 5. Install dependencies declared in the template's manifest.json.
        manifest_path = bot_path / "manifest.json"

        with open(manifest_path) as f:
            manifest = json.load(f)

        dependencies = manifest.get("dependencies", [])

        if not dependencies:
            raise RuntimeError(f"No dependencies found in manifest for {bot_id}")

        await self.venv.install_requirements(
            bot_id,
            dependencies,
        )

        # 6. Persist the bot record before launching anything.
        bot = Bot(
            id=bot_id,
            user_id=user_id,
            token=token,
            is_active=True,
            port=port,
        )

        self.session.add(bot)
        await self.session.commit()

        # 7. Launch the bot subprocess.
        await self.runtime.start_bot(
            bot_id=bot_id,
            bot_path=bot_path,
            token=token,
            port=port,
        )

    async def reap_bot(self, bot_id: str) -> None:
        """Stop *bot_id*'s process and release its port back to the registry."""
        await self.runtime.stop_bot(bot_id)
        await self.ports.release_port(bot_id)

    async def wake_bot(self, bot: Bot) -> None:
        """Re-launch a hibernating bot on a freshly reserved port."""
        if bot.is_active:
            return

        port = await self.ports.reserve_port(bot.id)

        bot.is_active = True
        bot.port = port
        bot.is_hibernated = False

        await self.session.commit()

        bot_path = self.venv.get_bot_path(bot.id)

        await self.runtime.start_bot(
            bot_id=bot.id,
            bot_path=bot_path,
            token=bot.token,
            port=port,
        )
