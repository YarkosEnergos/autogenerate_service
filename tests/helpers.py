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
