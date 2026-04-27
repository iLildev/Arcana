"""Per-user bot quota — anti-abuse cap on simultaneous bots.

The free tier ships a small quota (``settings.FREE_BOT_QUOTA``) that
covers the experimentation use-case. Admins can raise the cap per-user
via :func:`set_bot_quota` (exposed as ``/setquota`` on the Manager Bot).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from zerobot.config import settings
from zerobot.database.models import Bot, User


class QuotaError(Exception):
    """Raised when an action would push the user above their bot quota."""


@dataclass(frozen=True)
class QuotaStatus:
    """Snapshot of a user's bot-quota situation."""

    allowed: bool
    current: int
    quota: int

    @property
    def remaining(self) -> int:
        """Slots still available (clamped to zero)."""
        return max(0, self.quota - self.current)


async def _resolve_quota(session: AsyncSession, user_id: str) -> int:
    """Resolve the effective quota: per-user override or platform default."""
    user = await session.get(User, user_id)
    if user is not None and user.bot_quota is not None:
        return int(user.bot_quota)
    return int(settings.FREE_BOT_QUOTA)


async def _count_user_bots(session: AsyncSession, user_id: str) -> int:
    """Return the current count of bots owned by *user_id*."""
    return int(
        await session.scalar(
            select(func.count()).select_from(Bot).where(Bot.user_id == user_id)
        )
        or 0
    )


async def check_bot_quota(session: AsyncSession, user_id: str) -> QuotaStatus:
    """Return whether *user_id* may create one more bot, and the raw counts."""
    quota = await _resolve_quota(session, user_id)
    current = await _count_user_bots(session, user_id)
    return QuotaStatus(allowed=current < quota, current=current, quota=quota)


async def set_bot_quota(session: AsyncSession, user_id: str, quota: int) -> int:
    """Override *user_id*'s bot quota. ``quota=None`` resets to the default."""
    if quota < 0:
        raise QuotaError(f"quota must be non-negative, got {quota}")
    user = await session.get(User, user_id)
    if user is None:
        user = User(id=user_id)
        session.add(user)
    user.bot_quota = int(quota)
    await session.commit()
    return user.bot_quota
