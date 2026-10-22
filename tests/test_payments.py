import asyncio
import json

from app.core.security import SIGNATURE_HEADER
from tests.helpers import balance, pay, post_signed


async def test_twenty_concurrent_identical_payments_credit_once(client):
    responses = await asyncio.gather(*(pay(client, user_id=1, tokens=100, payment_id="pay-1") for _ in range(20)))

    assert [r.status_code for r in responses] == [200] * 20
    state = await balance(client, 1)
    assert state["balance"] == 100
    assert [(e["reason"], e["amount"], e["payment_id"]) for e in state["ledger"]] == [("topup", 100, "pay-1")]


async def test_different_payments_are_credited_separately(client):
    await pay(client, user_id=1, tokens=10, payment_id="pay-a")
    await pay(client, user_id=1, tokens=5, payment_id="pay-b")

    assert (await balance(client, 1))["balance"] == 15


async def test_not_succeeded_payment_is_not_credited(client):
    response = await post_signed(
        client,
        "/webhooks/payments",
        {"payment_id": "pay-x", "user_id": 1, "tokens": 10, "status": "failed"},
    )

    assert response.status_code == 200
    assert (await client.get("/users/1/balance")).status_code == 404


async def test_payment_with_invalid_signature_is_rejected(client):
    body = json.dumps({"payment_id": "pay-x", "user_id": 1, "tokens": 10, "status": "succeeded"}).encode()

    response = await client.post("/webhooks/payments", content=body, headers={SIGNATURE_HEADER: "deadbeef"})

    assert response.status_code == 401
    assert (await client.get("/users/1/balance")).status_code == 404
