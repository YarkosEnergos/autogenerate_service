import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_error_handlers
from app.api.routes import users, webhooks
from app.container import Container
from app.core.config import Settings, get_settings
from app.db.session import create_engine, create_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(process)d %(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url)
        app.state.container = Container(settings, create_session_factory(engine))
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="Generation service", lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(webhooks.router)
    app.include_router(users.router)
    return app
