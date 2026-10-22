import asyncio

import pytest
from sqlalchemy import text

from app.clients.providers import Submission
from tests.helpers import (
    balance,
    create_task,
    fail_current,
    get_task,
    ledger_reasons,
    pay,
    provider_webhook,
)


@pytest.fixture
def watchdog(app):
    return app.state.container.watchdog


@pytest.fixture
def expire(app):
    async def _expire(task_id: str) -> None:
        async with app.state.container.session_factory() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE attempts SET deadline_at = now() - interval '1 second' "
                    "WHERE task_id = :task_id AND status IN ('pending', 'sent')"
                ),
                {"task_id": task_id},
            )

    return _expire


async def test_silent_provider_is_timed_out_and_task_moves_to_next_leg(client, watchdog, expire, gateway):
    await pay(client, user_id=1, tokens=10)
    task_id = await create_task(client, user_id=1)

    assert await watchdog.run_once() == 0
    await expire(task_id)
    assert await watchdog.run_once() == 1

    task = await get_task(client, task_id)
    assert task["status"] == "processing"
    assert [(a["provider"], a["status"], a["error_type"]) for a in task["attempts"]] == [
        ("alpha", "timed_out", "timeout"),
        ("beta", "sent", None),
    ]
    assert [s.provider for s in gateway.submissions] == ["alpha", "beta"]


async def test_timeout_on_last_leg_fails_task_and_refunds(client, watchdog, expire):
    await pay(client, user_id=1, tokens=10)
    task_id = await create_task(client, user_id=1)
    await fail_current(client, task_id)
    await expire(task_id)

    await watchdog.run_once()

    task = await get_task(client, task_id)
    assert task["status"] == "failed"
    assert ledger_reasons(await balance(client, 1)) == [("topup", 10), ("charge", -2), ("refund", 2)]


async def test_concurrent_watchdogs_process_expired_attempt_once(client, watchdog, expire, gateway):
    await pay(client, user_id=1, tokens=10)
    task_ids = [await create_task(client, user_id=1) for _ in range(3)]
    for task_id in task_ids:
        await expire(task_id)

    processed = await asyncio.gather(*(watchdog.run_once() for _ in range(4)))

    assert sum(processed) == 3
    for task_id in task_ids:
        task = await get_task(client, task_id)
        assert [(a["provider"], a["status"]) for a in task["attempts"]] == [("alpha", "timed_out"), ("beta", "sent")]
    assert sorted(s.provider for s in gateway.submissions) == ["alpha"] * 3 + ["beta"] * 3


async def test_attempt_lost_before_sending_is_recovered_by_watchdog(client, watchdog, expire, gateway):
    original_submit = gateway.submit

    async def crash_on_alpha(submission: Submission) -> str:
        if submission.provider == "alpha":
            raise RuntimeError("worker died before the request left")
        return await original_submit(submission)

    gateway.submit = crash_on_alpha
    await pay(client, user_id=1, tokens=10)
    task_id = await create_task(client, user_id=1)
    assert [a["status"] for a in (await get_task(client, task_id))["attempts"]] == ["pending"]

    await expire(task_id)
    await watchdog.run_once()

    task = await get_task(client, task_id)
    assert [(a["provider"], a["status"]) for a in task["attempts"]] == [("alpha", "timed_out"), ("beta", "sent")]


async def test_late_completed_is_accepted_while_task_is_still_processing(client, watchdog, expire):
    await pay(client, user_id=1, tokens=10)
    task_id = await create_task(client, user_id=1)
    alpha_attempt = (await get_task(client, task_id))["current_leg"]["attempt_id"]
    await expire(task_id)
    await watchdog.run_once()
    beta_attempt = (await get_task(client, task_id))["current_leg"]["attempt_id"]

    late = await provider_webhook(client, "alpha", alpha_attempt, "completed", result_url="https://cdn/late.png")
    beta = await provider_webhook(client, "beta", beta_attempt, "completed", result_url="https://cdn/beta.png")

    assert late.status_code == beta.status_code == 200
    task = await get_task(client, task_id)
    assert task["status"] == "completed"
    assert task["result_url"] == "https://cdn/late.png"
    assert [(a["provider"], a["status"], a["error_type"], a["late_result"]) for a in task["attempts"]] == [
        ("alpha", "completed", "timeout", "accepted"),
        ("beta", "cancelled", None, "ignored"),
    ]
    assert ledger_reasons(await balance(client, 1)) == [("topup", 10), ("charge", -2)]


async def test_late_completed_after_refund_is_ignored(client, watchdog, expire):
    await pay(client, user_id=1, tokens=10)
    task_id = await create_task(client, user_id=1)
    await fail_current(client, task_id)
    beta_attempt = (await get_task(client, task_id))["current_leg"]["attempt_id"]
    await expire(task_id)
    await watchdog.run_once()

    responses = await asyncio.gather(
        *(
            provider_webhook(client, "beta", beta_attempt, "completed", result_url="https://cdn/late.png")
            for _ in range(3)
        )
    )

    assert [r.status_code for r in responses] == [200] * 3
    task = await get_task(client, task_id)
    assert task["status"] == "failed"
    assert task["result_url"] is None
    assert [(a["status"], a["late_result"]) for a in task["attempts"]] == [("failed", None), ("timed_out", "ignored")]
    assert ledger_reasons(await balance(client, 1)) == [("topup", 10), ("charge", -2), ("refund", 2)]


async def test_completed_racing_with_watchdog_gives_result_or_refund_never_both(client, watchdog, expire):
    await pay(client, user_id=1, tokens=100)
    for _ in range(10):
        task_id = await create_task(client, user_id=1)
        await fail_current(client, task_id)
        beta_attempt = (await get_task(client, task_id))["current_leg"]["attempt_id"]
        await expire(task_id)

        await asyncio.gather(watchdog.run_once(), provider_webhook(client, "beta", beta_attempt, "completed"))

        task = await get_task(client, task_id)
        refunds = [
            e for e in (await balance(client, 1))["ledger"] if e["reason"] == "refund" and e["task_id"] == task_id
        ]
        if task["status"] == "completed":
            assert task["result_url"] is not None and refunds == []
        else:
            assert task["status"] == "failed" and task["result_url"] is None and len(refunds) == 1
