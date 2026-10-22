import json

import httpx
import pytest

from app.core.security import SIGNATURE_HEADER, is_valid_signature
from fake_providers.main import Behavior, FakeProviderSettings, create_app

SECRET = "fake-secret"


@pytest.fixture
def received() -> list[httpx.Request]:
    return []


@pytest.fixture
async def provider(received):
    async def record(request: httpx.Request) -> httpx.Response:
        received.append(request)
        return httpx.Response(200, json={"status": "ok"})

    settings = FakeProviderSettings(
        provider_name="alpha",
        webhook_secret=SECRET,
        behavior=Behavior(min_delay=0, max_delay=0),
        _env_file=None,
    )
    app = create_app(settings, http=httpx.AsyncClient(transport=httpx.MockTransport(record)))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://alpha") as client:
            yield app, client


def task_request(client_ref: str = "ref-1") -> dict[str, object]:
    return {
        "prompt": "cat",
        "ref_images": [],
        "client_ref": client_ref,
        "callback_url": "http://svc/webhooks/providers/alpha",
    }


async def test_accepts_task_and_sends_signed_completed_webhook(provider, received):
    app, client = provider

    response = await client.post("/tasks", json=task_request())
    await app.state.provider.drain()

    assert response.status_code == 202
    external_id = response.json()["external_id"]
    assert len(received) == 1
    body = received[0].content
    assert is_valid_signature(body, received[0].headers[SIGNATURE_HEADER], SECRET)
    assert json.loads(body) == {
        "external_id": external_id,
        "client_ref": "ref-1",
        "status": "completed",
        "result_url": f"https://cdn.alpha.example/{external_id}.png",
    }


async def test_failure_duplicate_and_drop_are_configurable(provider, received):
    app, client = provider

    await client.patch("/behavior", json={"failure_rate": 1, "failure_type": "moderation", "duplicate_rate": 1})
    await client.post("/tasks", json=task_request("dup"))
    await app.state.provider.drain()
    await client.patch("/behavior", json={"drop_rate": 1})
    await client.post("/tasks", json=task_request("dropped"))
    await app.state.provider.drain()

    payloads = [json.loads(r.content) for r in received]
    assert [(p["client_ref"], p["status"], p.get("error_type")) for p in payloads] == [
        ("dup", "failed", "moderation"),
        ("dup", "failed", "moderation"),
    ]


async def test_sync_error_returns_503(provider):
    _, client = provider

    await client.patch("/behavior", json={"sync_error_rate": 1})

    assert (await client.post("/tasks", json=task_request())).status_code == 503


async def test_late_webhook_is_always_completed(provider, received):
    app, client = provider

    await client.patch("/behavior", json={"late_rate": 1, "late_delay": 0, "failure_rate": 1})
    await client.post("/tasks", json=task_request())
    await app.state.provider.drain()

    assert json.loads(received[0].content)["status"] == "completed"


async def test_reset_restores_configured_behavior(provider):
    _, client = provider

    await client.patch("/behavior", json={"failure_rate": 0.5})
    response = await client.post("/behavior/reset")

    assert response.json()["failure_rate"] == 0
