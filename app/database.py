from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models import Base


def create_engine_and_session(
    database_url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine_kwargs: dict[str, object] = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"timeout": 30}

    engine = create_async_engine(database_url, **engine_kwargs)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_maker


async def create_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def session_scope(
    session_maker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_maker() as session:
        yield session
