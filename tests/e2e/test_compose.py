import asyncio
import json
import os
import random
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx
import pytest

from app.core.security import SIGNATURE_HEADER, sign

pytestmark = pytest.mark.e2e

API_URL = os.environ.get("E2E_API_URL", "http://localhost:8000")
PROVIDER_URLS = {
    "alpha": os.environ.get("E2E_ALPHA_URL", "http://localhost:9001"),
    "beta": os.environ.get("E2E_BETA_URL", "http://localhost:9002"),
}
SECRET = os.environ.get("E2E_WEBHOOK_SECRET", "dev-secret")
FAST = {"min_delay": 0.3, "max_delay": 1.0}


@pytest.fixture
async def api() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=API_URL, timeout=30) as client:
        try:
            await client.get("/health")
        except httpx.HTTPError:
            pytest.skip(f"service is not running at {API_URL}, start it with docker compose up")
        yield client


@pytest.fixture
async def providers(api) -> AsyncIterator[dict[str, httpx.AsyncClient]]:
    clients = {name: httpx.AsyncClient(base_url=url, timeout=10) for name, url in PROVIDER_URLS.items()}
    try:
        for client in clients.values():
            await client.patch("/behavior", json=FAST)
        yield clients
    finally:
        for client in clients.values():
            await client.post("/behavior/reset")
            await client.aclose()


async def pay(api: httpx.AsyncClient, user_id: int, tokens: int, payment_id: str) -> httpx.Response:
    body = json.dumps({"payment_id": payment_id, "user_id": user_id, "tokens": tokens, "status": "succeeded"}).encode()
    return await api.post(
        "/webhooks/payments",
        content=body,
        headers={SIGNATURE_HEADER: sign(body, SECRET), "Content-Type": "application/json"},
    )


async def funded_user(api: httpx.AsyncClient, tokens: int = 100) -> int:
    user_id = random.randint(10**9, 2 * 10**9)
    assert (await pay(api, user_id, tokens, f"e2e-{uuid.uuid4()}")).status_code == 200
    return user_id


async def start_task(api: httpx.AsyncClient, user_id: int, model_slug: str = "image-fast") -> str:
    response = await api.post(
        "/generate", json={"user_id": user_id, "model_slug": model_slug, "prompt": "e2e", "ref_images": []}
    )
    assert response.status_code == 202, response.text
    return response.json()["task_id"]


async def wait_finished(api: httpx.AsyncClient, task_id: str, within: float = 30) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + within
    while True:
        task = (await api.get(f"/tasks/{task_id}")).json()
        if task["status"] != "processing":
            return task
        assert asyncio.get_running_loop().time() < deadline, f"task is still processing: {task}"
        await asyncio.sleep(0.3)


async def ledger(api: httpx.AsyncClient, user_id: int) -> dict[str, Any]:
    return (await api.get(f"/users/{user_id}/balance")).json()


async def test_twenty_concurrent_payments_across_workers_credit_once(api):
    user_id = random.randint(10**9, 2 * 10**9)
    payment_id = f"e2e-{uuid.uuid4()}"

    responses = await asyncio.gather(*(pay(api, user_id, 40, payment_id) for _ in range(20)))

    assert [r.status_code for r in responses] == [200] * 20
    state = await ledger(api, user_id)
    assert state["balance"] == 40
    assert len(state["ledger"]) == 1


async def test_failed_first_leg_finishes_on_second_with_duplicated_webhooks(api, providers):
    await providers["alpha"].patch("/behavior", json={"failure_rate": 1, "duplicate_rate": 1})
    user_id = await funded_user(api)

    task = await wait_finished(api, await start_task(api, user_id))

    assert task["status"] == "completed"
    assert [(a["provider"], a["status"]) for a in task["attempts"]] == [("alpha", "failed"), ("beta", "completed")]
    assert (await ledger(api, user_id))["balance"] == 98


async def test_all_legs_failing_with_duplicates_refund_once(api, providers):
    for client in providers.values():
        await client.patch("/behavior", json={"failure_rate": 1, "duplicate_rate": 1})
    user_id = await funded_user(api)

    task = await wait_finished(api, await start_task(api, user_id))

    assert task["status"] == "failed"
    state = await ledger(api, user_id)
    assert state["balance"] == 100
    assert sorted(e["reason"] for e in state["ledger"]) == ["charge", "refund", "topup"]


async def test_sync_503_moves_to_next_leg(api, providers):
    await providers["alpha"].patch("/behavior", json={"sync_error_rate": 1})
    user_id = await funded_user(api)

    task = await wait_finished(api, await start_task(api, user_id))

    assert task["status"] == "completed"
    assert [(a["provider"], a["error_type"]) for a in task["attempts"]] == [("alpha", "technical"), ("beta", None)]


async def test_late_completed_after_watchdog_is_accepted(api, providers):
    user_id = await funded_user(api)
    probe = await wait_finished(api, await start_task(api, user_id))
    first = probe["attempts"][0]
    timeout = (datetime.fromisoformat(first["deadline_at"]) - datetime.fromisoformat(first["started_at"])).seconds
    if timeout > 10:
        pytest.skip("needs a short watchdog timeout: PROVIDER_TIMEOUT=5 docker compose up -d")
    await providers["alpha"].patch("/behavior", json={"late_rate": 1, "late_delay": timeout + 2})
    await providers["beta"].patch("/behavior", json={"min_delay": timeout + 10, "max_delay": timeout + 10})

    task = await wait_finished(api, await start_task(api, user_id), within=timeout + 15)

    assert task["status"] == "completed"
    assert task["result_url"].startswith("https://cdn.alpha.example/")
    assert [(a["provider"], a["status"], a["late_result"]) for a in task["attempts"]] == [
        ("alpha", "completed", "accepted"),
        ("beta", "cancelled", None),
    ]
    assert (await ledger(api, user_id))["balance"] == 96
