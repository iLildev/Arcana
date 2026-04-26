"""Wallet read / write helpers — the only place that mutates crystal balances."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zerobot.config import settings
from zerobot.database.models import Wallet


class WalletService:
    """Thin wrapper around the ``Wallet`` ORM model.

    Wallets are auto-created with ``settings.INITIAL_CRYSTALS`` the first
    time a balance is requested for a user, so callers never have to handle
    the "no wallet yet" case explicitly.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_wallet(self, user_id: str) -> Wallet:
        """Return the wallet for *user_id*, creating it on first access."""
        result = await self.session.execute(select(Wallet).where(Wallet.user_id == user_id))
        wallet = result.scalar_one_or_none()

        if not wallet:
            wallet = await self.create_wallet(user_id)

        return wallet

    async def create_wallet(self, user_id: str) -> Wallet:
        """Insert a new wallet seeded with the configured initial balance."""
        wallet = Wallet(
            user_id=user_id,
            balance=settings.INITIAL_CRYSTALS,
        )
        self.session.add(wallet)
        await self.session.commit()
        return wallet

    async def charge(self, user_id: str, amount: int) -> None:
        """Deduct *amount* crystals; raise ``RuntimeError`` if insufficient."""
        wallet = await self.get_wallet(user_id)

        if wallet.balance < amount:
            raise RuntimeError("Insufficient crystals")

        wallet.balance -= amount
        await self.session.commit()

    async def add(self, user_id: str, amount: int) -> None:
        """Top *user_id*'s wallet up by *amount* crystals."""
        wallet = await self.get_wallet(user_id)
        wallet.balance += amount
        await self.session.commit()
