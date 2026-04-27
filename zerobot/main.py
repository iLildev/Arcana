"""Database bootstrap entry-point.

Run once before starting the rest of the platform; it is safe to run on
every boot. Responsibilities:

1. Create any missing tables registered on ``Base.metadata``.
2. Apply a small set of additive ``ALTER TABLE … ADD COLUMN IF NOT EXISTS``
   migrations so that older deployments pick up new optional columns.
3. Seed the port registry with the configured port range.
4. Bootstrap the admin user when ``ADMIN_USER_ID`` is set.

Usage::

    python -m zerobot.main
"""

import asyncio

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from zerobot import database  # noqa: F401  - register all ORM tables
from zerobot.config import settings
from zerobot.database.engine import AsyncSessionLocal, Base, engine
from zerobot.database.models import User
from zerobot.database.port_registry import Port

# Idempotent additive column migrations. Safe to run on every boot:
# PostgreSQL's `ADD COLUMN IF NOT EXISTS` is non-destructive and skips
# columns that already exist. Primary keys are never touched.
ADDITIVE_MIGRATIONS = [
    "ALTER TABLE bots  ADD COLUMN IF NOT EXISTS is_official       BOOLEAN DEFAULT FALSE",
    "ALTER TABLE bots  ADD COLUMN IF NOT EXISTS name              VARCHAR",
    "ALTER TABLE bots  ADD COLUMN IF NOT EXISTS description       VARCHAR",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin          BOOLEAN DEFAULT FALSE",
    # ── Phase 0 (identity) ───────────────────────────────────────────────
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_encrypted   BYTEA",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_hash        VARCHAR(64)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_verified_at TIMESTAMP",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS bot_quota         INTEGER",
    # Unique index on phone_hash (skipped if already present). The
    # WHERE-clause makes it a "partial unique" so multiple unverified
    # users (NULL hash) coexist without colliding.
    (
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_users_phone_hash "
        "ON users (phone_hash) WHERE phone_hash IS NOT NULL"
    ),
]


async def init_db() -> None:
    """Create any missing tables defined on ``Base.metadata``."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def apply_additive_migrations() -> None:
    """Run the additive ALTER TABLE statements declared above."""
    async with engine.begin() as conn:
        for stmt in ADDITIVE_MIGRATIONS:
            await conn.execute(text(stmt))


async def seed_ports() -> None:
    """Seed the ports table from PORT_RANGE_START..PORT_RANGE_END (idempotent)."""
    rows = [
        {"port_number": p, "bot_id": None, "status": "free", "last_used": None}
        for p in range(settings.PORT_RANGE_START, settings.PORT_RANGE_END + 1)
    ]

    async with AsyncSessionLocal() as session:
        stmt = pg_insert(Port).values(rows).on_conflict_do_nothing(index_elements=["port_number"])
        await session.execute(stmt)
        await session.commit()

        result = await session.execute(select(Port))
        total = len(result.scalars().all())

    print(f"✅ Seeded ports: {total} total in registry")


async def bootstrap_admin() -> None:
    """If ADMIN_USER_ID is set, ensure that user exists and is flagged admin."""
    if not settings.ADMIN_USER_ID:
        print("ℹ️  ADMIN_USER_ID not set — skipping admin bootstrap")
        return

    async with AsyncSessionLocal() as session:
        user = await session.get(User, settings.ADMIN_USER_ID)
        if not user:
            session.add(User(id=settings.ADMIN_USER_ID, is_admin=True))
            await session.commit()
            print(f"✅ Admin user created: {settings.ADMIN_USER_ID}")
        elif not user.is_admin:
            user.is_admin = True
            await session.commit()
            print(f"✅ Admin flag promoted on existing user: {settings.ADMIN_USER_ID}")
        else:
            print(f"✅ Admin user already configured: {settings.ADMIN_USER_ID}")


async def main() -> None:
    """Run every bootstrap step in order."""
    await init_db()
    print("✅ Database initialized")
    await apply_additive_migrations()
    print("✅ Additive column migrations applied")
    await seed_ports()
    await bootstrap_admin()


if __name__ == "__main__":
    asyncio.run(main())
