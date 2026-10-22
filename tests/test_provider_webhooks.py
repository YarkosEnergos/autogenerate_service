import asyncio

from tests.helpers import (
    balance,
    create_task,
    fail_current,
    get_task,
    ledger_reasons,
    pay,
    provider_webhook,
)


async def test_completed_webhook_completes_task(client):
    await pay(client, user_id=1, tokens=10)
    task_id = await create_task(client, user_id=1)
    attempt_id = (await get_task(client, task_id))["current_leg"]["attempt_id"]

    response = await provider_webhook(client, "alpha", attempt_id, "completed", result_url="https://cdn/a.png")

    assert response.status_code == 200
    task = await get_task(client, task_id)
    assert task["status"] == "completed"
    assert task["result_url"] == "https://cdn/a.png"
    assert (await balance(client, 1))["balance"] == 8


async def test_first_leg_failure_completes_on_second_leg_with_two_attempts(client, gateway):
    await pay(client, user_id=1, tokens=10)
    task_id = await create_task(client, user_id=1)

    task = await fail_current(client, task_id, "technical")
    assert task["current_leg"]["provider"] == "beta"
    assert [s.provider for s in gateway.submissions] == ["alpha", "beta"]
    response = await provider_webhook(
        client, "beta", task["current_leg"]["attempt_id"], "completed", result_url="https://cdn/b.png"
    )

    assert response.status_code == 200
    task = await get_task(client, task_id)
    assert task["status"] == "completed"
    assert task["result_url"] == "https://cdn/b.png"
    assert [(a["provider"], a["status"], a["error_type"]) for a in task["attempts"]] == [
        ("alpha", "failed", "technical"),
        ("beta", "completed", None),
    ]
    assert all(a["started_at"] for a in task["attempts"])
    assert ledger_reasons(await balance(client, 1)) == [("topup", 10), ("charge", -2)]


async def test_ten_concurrent_failures_on_last_leg_refund_once(client):
    await pay(client, user_id=1, tokens=10)
    task_id = await create_task(client, user_id=1)
    task = await fail_current(client, task_id)
    last_attempt = task["current_leg"]["attempt_id"]

    responses = await asyncio.gather(
        *(provider_webhook(client, "beta", last_attempt, "failed", error_type="technical") for _ in range(10))
    )

    assert [r.status_code for r in responses] == [200] * 10
    task = await get_task(client, task_id)
    assert task["status"] == "failed"
    assert len(task["attempts"]) == 2
    state = await balance(client, 1)
    assert state["balance"] == 10
    assert ledger_reasons(state) == [("topup", 10), ("charge", -2), ("refund", 2)]


async def test_duplicate_completed_webhooks_are_idempotent(client):
    await pay(client, user_id=1, tokens=10)
    task_id = await create_task(client, user_id=1)
    attempt_id = (await get_task(client, task_id))["current_leg"]["attempt_id"]

    responses = await asyncio.gather(*(provider_webhook(client, "alpha", attempt_id, "completed") for _ in range(5)))

    assert [r.status_code for r in responses] == [200] * 5
    task = await get_task(client, task_id)
    assert task["status"] == "completed"
    assert [a["status"] for a in task["attempts"]] == ["completed"]


async def test_moderation_failure_skips_leg_with_skip_on_moderation(client):
    await pay(client, user_id=1, tokens=30)
    task_id = await create_task(client, user_id=1, model_slug="video-long")

    task = await fail_current(client, task_id, "moderation")

    assert task["status"] == "failed"
    assert [(a["provider"], a["error_type"]) for a in task["attempts"]] == [("beta", "moderation")]
    assert (await balance(client, 1))["balance"] == 30


async def test_technical_failure_does_not_skip_leg_with_skip_on_moderation(client):
    await pay(client, user_id=1, tokens=30)
    task_id = await create_task(client, user_id=1, model_slug="video-long")

    task = await fail_current(client, task_id, "technical")

    assert task["status"] == "processing"
    assert task["current_leg"]["provider"] == "alpha"


async def test_payload_failure_fails_task_immediately(client):
    await pay(client, user_id=1, tokens=10)
    task_id = await create_task(client, user_id=1)

    task = await fail_current(client, task_id, "payload")

    assert task["status"] == "failed"
    assert [a["provider"] for a in task["attempts"]] == ["alpha"]
    assert (await balance(client, 1))["balance"] == 10


async def test_webhook_for_unknown_attempt_or_wrong_provider_returns_404(client):
    await pay(client, user_id=1, tokens=10)
    task_id = await create_task(client, user_id=1)
    attempt_id = (await get_task(client, task_id))["current_leg"]["attempt_id"]

    wrong_provider = await provider_webhook(client, "beta", attempt_id, "completed")
    unknown = await provider_webhook(client, "alpha", "00000000-0000-0000-0000-000000000000", "completed")

    assert wrong_provider.status_code == 404
    assert unknown.status_code == 404
    assert (await get_task(client, task_id))["status"] == "processing"


async def test_webhook_with_bad_signature_is_rejected(client):
    response = await client.post(
        "/webhooks/providers/alpha",
        json={"client_ref": "00000000-0000-0000-0000-000000000000", "status": "completed", "result_url": "x"},
        headers={"X-Signature": "bad"},
    )

    assert response.status_code == 401
