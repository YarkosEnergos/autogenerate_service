import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_error_handlers
from app.api.routes import generate, tasks, users, webhooks
from app.clients.providers import HttpProviderGateway, ProviderGateway
from app.container import Container
from app.core.config import Settings, get_settings
from app.db.session import create_engine, create_session_factory


def create_app(settings: Settings | None = None, gateway: ProviderGateway | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(process)d %(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url)
        provider_gateway = gateway or HttpProviderGateway(
            settings.provider_urls, settings.public_base_url, settings.provider_http_timeout
        )
        container = Container(settings, create_session_factory(engine), provider_gateway)
        app.state.container = container
        watchdog_task = asyncio.create_task(container.watchdog.run_forever()) if settings.watchdog_enabled else None
        try:
            yield
        finally:
            if watchdog_task is not None:
                watchdog_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watchdog_task
            await provider_gateway.aclose()
            await engine.dispose()

    app = FastAPI(title="Generation service", lifespan=lifespan)
    register_error_handlers(app)
    app.include_router(generate.router)
    app.include_router(tasks.router)
    app.include_router(users.router)
    app.include_router(webhooks.router)

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
