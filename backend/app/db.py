from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

# Pool tuned for a remote database (Neon, ap-southeast-1), where one round trip
# costs ~100 ms from the demo machine. Measured 2026-09-17, two queries per
# session: ~712 ms with pool_pre_ping, ~399 ms without -- the per-checkout
# ping alone was a third of every request's database time, and the console
# makes several authenticated requests a second.
#
# - pool_pre_ping off: the backend's own 10 s analytics supervisor tick keeps
#   pooled connections in use, so they don't go stale between requests. A
#   connection that does drop is invalidated by SQLAlchemy on the failed
#   statement and replaced on the next checkout.
# - pool_recycle bounds a connection's age instead, without a per-request cost.
# - pool_size 10: a request plus its audit write can hold two connections, and
#   an overflow connection (closed after use) costs a ~2.5 s TLS handshake to
#   this database every time a burst exceeds the pool.
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=False,
    pool_recycle=1800,
    pool_size=10,
    max_overflow=10,
)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
