"""Port allocation table and helpers used by the orchestrator.

Each row represents a TCP port that bot processes can bind to. Ports cycle
through three statuses: ``free`` → ``used`` (while a bot owns it) →
``cooldown`` (briefly held after release so a restarting bot doesn't
immediately reuse the same socket) → ``free`` again.
"""

from datetime import datetime, timedelta

from sqlalchemy import DateTime, Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from zerobot.database.engine import Base


class Port(Base):
    """One row per port that the platform may hand out to a bot."""

    __tablename__ = "ports"

    port_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="free")
    last_used: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PortManager:
    """Reserve, release, and recycle ports for bot processes."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def reserve_port(self, bot_id: str) -> int:
        """Mark the first ``free`` port as ``used`` by *bot_id* and return it."""
        result = await self.session.execute(select(Port).where(Port.status == "free"))
        port = result.scalar_one_or_none()

        if not port:
            raise RuntimeError("No free ports available")

        port.status = "used"
        port.bot_id = bot_id
        port.last_used = datetime.utcnow()

        await self.session.commit()
        return port.port_number

    async def release_port(self, bot_id: str) -> None:
        """Move *bot_id*'s port into ``cooldown`` so it can be recycled later."""
        result = await self.session.execute(select(Port).where(Port.bot_id == bot_id))
        port = result.scalar_one_or_none()

        if not port:
            return

        port.status = "cooldown"
        port.bot_id = None
        port.last_used = datetime.utcnow()

        await self.session.commit()

    async def cleanup(self) -> None:
        """Promote any cooldown ports older than 60s back to ``free``."""
        threshold = datetime.utcnow() - timedelta(seconds=60)

        result = await self.session.execute(
            select(Port).where(
                Port.status == "cooldown",
                Port.last_used < threshold,
            )
        )

        ports = result.scalars().all()

        for port in ports:
            port.status = "free"

        await self.session.commit()
