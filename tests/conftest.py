import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import make_url, text

from app.core.config import Settings
from app.main import create_app
from tests.helpers import WEBHOOK_SECRET

ROOT = Path(__file__).resolve().parent.parent
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/generation_test"
)


async def recreate_database(url: str) -> None:
    parsed = make_url(url)
    admin_dsn = parsed.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
    connection = await asyncpg.connect(admin_dsn)
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{parsed.database}" WITH (FORCE)')
        await connection.execute(f'CREATE DATABASE "{parsed.database}"')
    finally:
        await connection.close()


@pytest.fixture(scope="session")
def database_url() -> str:
    asyncio.run(recreate_database(TEST_DATABASE_URL))
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
    return TEST_DATABASE_URL


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        webhook_secret=WEBHOOK_SECRET,
        watchdog_enabled=False,
        provider_timeout=60,
        _env_file=None,
    )


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        session_factory = application.state.container.session_factory
        async with session_factory() as session, session.begin():
            await session.execute(text("TRUNCATE ledger, attempts, tasks, users RESTART IDENTITY CASCADE"))
        yield application
        async with session_factory() as session:
            mismatched = await session.execute(
                text(
                    "SELECT u.id, u.balance, COALESCE(SUM(l.amount), 0) AS journal "
                    "FROM users u LEFT JOIN ledger l ON l.user_id = u.id "
                    "GROUP BY u.id HAVING u.balance <> COALESCE(SUM(l.amount), 0)"
                )
            )
            assert mismatched.all() == [], "balance must equal the sum of the ledger"


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        yield http
