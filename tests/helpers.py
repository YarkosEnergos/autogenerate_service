import json
from typing import Any

import httpx

from app.core.security import SIGNATURE_HEADER, sign

WEBHOOK_SECRET = "test-secret"


async def post_signed(client: httpx.AsyncClient, url: str, payload: dict[str, Any]) -> httpx.Response:
    body = json.dumps(payload).encode()
    headers = {SIGNATURE_HEADER: sign(body, WEBHOOK_SECRET), "Content-Type": "application/json"}
    return await client.post(url, content=body, headers=headers)


async def pay(client: httpx.AsyncClient, user_id: int, tokens: int, payment_id: str | None = None) -> httpx.Response:
    payload = {
        "payment_id": payment_id or f"pay-{user_id}-{tokens}",
        "user_id": user_id,
        "tokens": tokens,
        "status": "succeeded",
    }
    return await post_signed(client, "/webhooks/payments", payload)


async def balance(client: httpx.AsyncClient, user_id: int) -> dict[str, Any]:
    response = await client.get(f"/users/{user_id}/balance")
    response.raise_for_status()
    return response.json()


async def generate(
    client: httpx.AsyncClient, user_id: int, model_slug: str = "image-fast", ref_images: int = 0
) -> httpx.Response:
    payload = {
        "user_id": user_id,
        "model_slug": model_slug,
        "prompt": "a cat in a hat",
        "ref_images": [f"https://refs.example/{i}.png" for i in range(ref_images)],
    }
    return await client.post("/generate", json=payload)


async def create_task(
    client: httpx.AsyncClient, user_id: int, model_slug: str = "image-fast", ref_images: int = 0
) -> str:
    response = await generate(client, user_id, model_slug, ref_images)
    assert response.status_code == 202, response.text
    return response.json()["task_id"]


async def get_task(client: httpx.AsyncClient, task_id: str) -> dict[str, Any]:
    response = await client.get(f"/tasks/{task_id}")
    response.raise_for_status()
    return response.json()


def ledger_reasons(state: dict[str, Any]) -> list[tuple[str, int]]:
    return [(entry["reason"], entry["amount"]) for entry in reversed(state["ledger"])]


async def provider_webhook(
    client: httpx.AsyncClient,
    provider: str,
    attempt_id: str,
    status: str,
    *,
    result_url: str | None = None,
    error_type: str | None = None,
) -> httpx.Response:
    payload: dict[str, Any] = {"client_ref": attempt_id, "external_id": f"{provider}-ext", "status": status}
    if status == "completed":
        payload["result_url"] = result_url or f"https://cdn.{provider}.example/{attempt_id}.png"
    else:
        payload["error_type"] = error_type or "technical"
    return await post_signed(client, f"/webhooks/providers/{provider}", payload)


async def fail_current(client: httpx.AsyncClient, task_id: str, error_type: str = "technical") -> dict[str, Any]:
    leg = (await get_task(client, task_id))["current_leg"]
    response = await provider_webhook(client, leg["provider"], leg["attempt_id"], "failed", error_type=error_type)
    assert response.status_code == 200, response.text
    return await get_task(client, task_id)
