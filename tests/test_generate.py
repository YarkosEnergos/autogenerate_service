import asyncio

from app.domain.enums import ErrorType
from tests.helpers import balance, create_task, generate, get_task, ledger_reasons, pay


async def test_generate_charges_price_and_sends_to_first_leg(client, gateway):
    await pay(client, user_id=1, tokens=10)

    task_id = await create_task(client, user_id=1)

    task = await get_task(client, task_id)
    assert task["status"] == "processing"
    assert task["current_leg"]["provider"] == "alpha"
    assert [(a["provider"], a["status"]) for a in task["attempts"]] == [("alpha", "sent")]
    assert task["attempts"][0]["external_id"] is not None
    assert [s.provider for s in gateway.submissions] == ["alpha"]
    state = await balance(client, 1)
    assert state["balance"] == 8
    assert ledger_reasons(state) == [("topup", 10), ("charge", -2)]


async def test_first_suitable_leg_is_chosen_by_reference_count(client, gateway):
    await pay(client, user_id=1, tokens=10)

    task_id = await create_task(client, user_id=1, ref_images=5)

    task = await get_task(client, task_id)
    assert [a["provider"] for a in task["attempts"]] == ["beta"]


async def test_no_suitable_leg_is_rejected_before_charging(client):
    await pay(client, user_id=1, tokens=100)

    response = await generate(client, user_id=1, model_slug="video-long", ref_images=3)

    assert response.status_code == 400
    state = await balance(client, 1)
    assert state["balance"] == 100
    assert ledger_reasons(state) == [("topup", 100)]


async def test_insufficient_tokens_returns_402(client):
    await pay(client, user_id=1, tokens=24)

    response = await generate(client, user_id=1, model_slug="video-long")

    assert response.status_code == 402
    assert (await balance(client, 1))["balance"] == 24


async def test_fourth_active_task_returns_429(client):
    await pay(client, user_id=1, tokens=100)
    for _ in range(3):
        await create_task(client, user_id=1)

    response = await generate(client, user_id=1)

    assert response.status_code == 429
    assert (await balance(client, 1))["balance"] == 94


async def test_concurrent_generates_respect_active_limit(client):
    await pay(client, user_id=1, tokens=100)

    responses = await asyncio.gather(*(generate(client, user_id=1) for _ in range(8)))

    codes = sorted(r.status_code for r in responses)
    assert codes == [202] * 3 + [429] * 5
    assert (await balance(client, 1))["balance"] == 94


async def test_unknown_user_and_model_return_404(client):
    await pay(client, user_id=1, tokens=10)

    assert (await generate(client, user_id=2)).status_code == 404
    assert (await generate(client, user_id=1, model_slug="nope")).status_code == 404


async def test_sync_rejection_moves_task_to_next_leg(client, gateway):
    gateway.reject("alpha", detail="HTTP 503")
    await pay(client, user_id=1, tokens=10)

    task_id = await create_task(client, user_id=1)

    task = await get_task(client, task_id)
    assert task["status"] == "processing"
    assert task["current_leg"]["provider"] == "beta"
    assert [(a["provider"], a["status"], a["error_type"]) for a in task["attempts"]] == [
        ("alpha", "failed", "technical"),
        ("beta", "sent", None),
    ]


async def test_sync_rejection_on_every_leg_fails_task_and_refunds_once(client, gateway):
    gateway.reject("alpha")
    gateway.reject("beta", detail="timeout on POST /tasks")
    await pay(client, user_id=1, tokens=10)

    task_id = await create_task(client, user_id=1)

    task = await get_task(client, task_id)
    assert task["status"] == "failed"
    assert len(task["attempts"]) == 2
    state = await balance(client, 1)
    assert state["balance"] == 10
    assert ledger_reasons(state) == [("topup", 10), ("charge", -2), ("refund", 2)]


async def test_sync_payload_rejection_fails_task_without_trying_next_leg(client, gateway):
    gateway.reject("alpha", ErrorType.PAYLOAD, "HTTP 422")
    await pay(client, user_id=1, tokens=10)

    task_id = await create_task(client, user_id=1)

    task = await get_task(client, task_id)
    assert task["status"] == "failed"
    assert [a["provider"] for a in task["attempts"]] == ["alpha"]
    assert (await balance(client, 1))["balance"] == 10
