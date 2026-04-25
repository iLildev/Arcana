import json
import shutil
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Bot
from database.wallet import WalletService
from database.port_registry import PortManager
from isolation.venv_manager import VenvManager
from core.runtime_manager import RuntimeManager


TEMPLATE_PATH = Path("templates/base_template")


class Orchestrator:
    def __init__(self, session: AsyncSession):
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
    ):
        # 1. خصم الكرستالات
        await self.wallet.charge(user_id, 1)

        # 2. حجز بورت
        port = await self.ports.reserve_port(bot_id)

        # 3. إنشاء venv
        await self.venv.create_venv(bot_id)

        # 4. نسخ template إلى مجلد البوت
        bot_path = self.venv.get_bot_path(bot_id)
        if not (bot_path / "main.py").exists():
            shutil.copytree(TEMPLATE_PATH, bot_path, dirs_exist_ok=True)

        # 5. تثبيت dependencies من manifest.json
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

        # 6. إنشاء bot record
        bot = Bot(
            id=bot_id,
            user_id=user_id,
            token=token,
            is_active=True,
            port=port,
        )

        self.session.add(bot)
        await self.session.commit()

        # 7. تشغيل البوت
        await self.runtime.start_bot(
            bot_id=bot_id,
            bot_path=bot_path,
            token=token,
            port=port,
        )

    async def reap_bot(self, bot_id: str):
        await self.runtime.stop_bot(bot_id)
        await self.ports.release_port(bot_id)

    async def wake_bot(self, bot):
        if bot.is_active:
            return

        port = await self.ports.reserve_port(bot.id)

        bot.is_active = True
        bot.port = port

        await self.session.commit()

        bot_path = self.venv.get_bot_path(bot.id)

        await self.runtime.start_bot(
            bot_id=bot.id,
            bot_path=bot_path,
            token=bot.token,
            port=port,
        )
