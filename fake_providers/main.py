import asyncio
import json
import logging
import random
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.security import SIGNATURE_HEADER, sign

logger = logging.getLogger("fake_provider")


class Behavior(BaseModel):
    min_delay: float = Field(default=2.0, ge=0)
    max_delay: float = Field(default=20.0, ge=0)
    failure_rate: float = Field(default=0.0, ge=0, le=1)
    failure_type: Literal["technical", "moderation", "payload"] = "technical"
    sync_error_rate: float = Field(default=0.0, ge=0, le=1)
    sync_error: Literal["503", "timeout"] = "503"
    sync_timeout: float = Field(default=30.0, ge=0)
    duplicate_rate: float = Field(default=0.0, ge=0, le=1)
    drop_rate: float = Field(default=0.0, ge=0, le=1)
    late_rate: float = Field(default=0.0, ge=0, le=1)
    late_delay: float = Field(default=75.0, ge=0)


class FakeProviderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FAKE_", env_nested_delimiter="__", extra="ignore")

    provider_name: str = "alpha"
    webhook_secret: str = "dev-secret"
    behavior: Behavior = Behavior()


class TaskRequest(BaseModel):
    prompt: str
    ref_images: list[str] = Field(default_factory=list)
    client_ref: str
    callback_url: str


class FakeProvider:
    def __init__(self, settings: FakeProviderSettings, http: httpx.AsyncClient) -> None:
        self.settings = settings
        self.behavior = settings.behavior.model_copy()
        self._http = http
        self._deliveries: set[asyncio.Task[None]] = set()

    @property
    def name(self) -> str:
        return self.settings.provider_name

    def schedule(self, request: TaskRequest, external_id: str) -> None:
        delivery = asyncio.create_task(self._deliver(request, external_id, self.behavior.model_copy()))
        self._deliveries.add(delivery)
        delivery.add_done_callback(self._deliveries.discard)

    async def _deliver(self, request: TaskRequest, external_id: str, behavior: Behavior) -> None:
        if random.random() < behavior.drop_rate:
            logger.info("%s: webhook for %s dropped", self.name, external_id)
            return
        late = random.random() < behavior.late_rate
        await asyncio.sleep(behavior.late_delay if late else random.uniform(behavior.min_delay, behavior.max_delay))
        payload: dict[str, Any] = {"external_id": external_id, "client_ref": request.client_ref}
        if not late and random.random() < behavior.failure_rate:
            payload |= {"status": "failed", "error_type": behavior.failure_type}
        else:
            payload |= {"status": "completed", "result_url": f"https://cdn.{self.name}.example/{external_id}.png"}
        body = json.dumps(payload).encode()
        copies = 2 if random.random() < behavior.duplicate_rate else 1
        await asyncio.gather(*(self._post(request.callback_url, body) for _ in range(copies)))

    async def _post(self, url: str, body: bytes) -> None:
        headers = {SIGNATURE_HEADER: sign(body, self.settings.webhook_secret), "Content-Type": "application/json"}
        try:
            response = await self._http.post(url, content=body, headers=headers)
            logger.info("%s: webhook %s -> %s", self.name, body.decode(), response.status_code)
        except httpx.HTTPError as exc:
            logger.warning("%s: webhook delivery failed: %r", self.name, exc)

    async def drain(self) -> None:
        await asyncio.gather(*self._deliveries, return_exceptions=True)

    async def close(self) -> None:
        for delivery in self._deliveries:
            delivery.cancel()
        await self._http.aclose()


def create_app(settings: FakeProviderSettings | None = None, http: httpx.AsyncClient | None = None) -> FastAPI:
    settings = settings or FakeProviderSettings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        provider = FakeProvider(settings, http or httpx.AsyncClient(timeout=10))
        app.state.provider = provider
        try:
            yield
        finally:
            await provider.close()

    app = FastAPI(title=f"Fake provider {settings.provider_name}", lifespan=lifespan)

    def provider_of(request: Request) -> FakeProvider:
        return request.app.state.provider

    @app.post("/tasks", status_code=status.HTTP_202_ACCEPTED)
    async def create_task(task: TaskRequest, request: Request) -> dict[str, str]:
        provider = provider_of(request)
        behavior = provider.behavior
        if random.random() < behavior.sync_error_rate:
            if behavior.sync_error == "timeout":
                await asyncio.sleep(behavior.sync_timeout)
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "provider is unavailable")
        external_id = f"{provider.name}-{uuid.uuid4().hex}"
        provider.schedule(task, external_id)
        return {"external_id": external_id}

    @app.get("/behavior")
    async def get_behavior(request: Request) -> Behavior:
        return provider_of(request).behavior

    @app.patch("/behavior")
    async def update_behavior(changes: dict[str, Any], request: Request) -> Behavior:
        provider = provider_of(request)
        provider.behavior = Behavior.model_validate(provider.behavior.model_dump() | changes)
        return provider.behavior

    @app.post("/behavior/reset")
    async def reset_behavior(request: Request) -> Behavior:
        provider = provider_of(request)
        provider.behavior = provider.settings.behavior.model_copy()
        return provider.behavior

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
