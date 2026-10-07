from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from core.config import DATABASE_URL

# Convert postgres URL for async if needed
url = DATABASE_URL
if url.startswith("postgres://"):
    url = url.replace("postgres://", "postgresql+asyncpg://", 1)
elif url.startswith("postgresql://") and "+asyncpg" not in url:
    url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# Columns added after the first release. create_all() never alters existing
# tables, so these are added automatically at startup when missing.
_NEW_COLUMNS = {
    "users": [
        ("auth_provider", "VARCHAR(20) DEFAULT 'password'"),
        ("google_id", "VARCHAR(64)"),
        ("telegram_id", "VARCHAR(32)"),
        ("avatar_url", "VARCHAR(500)"),
    ],
    "orders": [
        ("months", "INTEGER DEFAULT 1"),
        ("payment_id", "VARCHAR(100)"),
        ("pay_data", "TEXT"),
    ],
    "projects": [
        ("folder", "VARCHAR(40)"),
    ],
    "login_history": [
        ("method", "VARCHAR(20) DEFAULT 'password'"),
    ],
    "support_tickets": [
        ("priority", "VARCHAR(20) DEFAULT 'normal'"),
        ("assigned_to", "INTEGER"),
    ],
}
_NEW_INDEXES = [
    ("ix_users_google_id", "users", "google_id"),
    ("ix_users_telegram_id", "users", "telegram_id"),
]


def _migrate(sync_conn):
    from sqlalchemy import inspect, text
    insp = inspect(sync_conn)
    for table, cols in _NEW_COLUMNS.items():
        if not insp.has_table(table):
            continue
        have = {c["name"] for c in insp.get_columns(table)}
        for name, ddl in cols:
            if name not in have:
                sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
    for ix, table, col in _NEW_INDEXES:
        sync_conn.execute(text(f"CREATE INDEX IF NOT EXISTS {ix} ON {table} ({col})"))


async def init_db():
    from core import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate)
