"""Queue waiting counts toward reading delay without bypassing typing or safety."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.test_workflow_regressions import make_stack


def configure_timing(tmp_path, clock, monkeypatch, global_wait):
    s = make_stack(tmp_path, min_delay_seconds=1, max_delay_seconds=60)
    monkeypatch.setattr("app.reply_manager.time", SimpleNamespace(time=lambda: clock.now, monotonic=lambda: clock.now))

    def uniform(low, high):
        if (low, high) == (5.0, 6.5):
            return 5.0
        if (low, high) == (0.8, 1.4):
            return 1.0
        return low

    monkeypatch.setattr("app.reply_manager.random.uniform", uniform)
    s.db.set_state("min_global_cooldown_seconds", str(global_wait))
    s.db.set_state("max_global_cooldown_seconds", str(global_wait))
    s.safety.set_chat_cooldown(123, 15, 15)
    s.safety.mark_reply_sent(-100111)
    s.manager.calculate_adaptive_delay = MagicMock(return_value=35)
    s.manager.refresh_single_chat_summary = AsyncMock()
    return s


# Sent at max(35 s human delay, global cooldown); the 5 s typing window ends the wait instead of extending it.
@pytest.mark.parametrize("global_wait,expected", [(0, 35), (10, 35), (40, 40)])
def test_queue_wait_overlaps_reading_but_preserves_final_typing(tmp_path, clock, monkeypatch, global_wait, expected):
    s = configure_timing(tmp_path, clock, monkeypatch, global_wait)
    events = []

    class Typing:
        async def __aenter__(self):
            events.append(("typing", clock.now))

        async def __aexit__(self, *_args):
            events.append(("typing_end", clock.now))

    async def send(*_args, **_kwargs):
        events.append(("sent", clock.now))
        return SimpleNamespace(id=777)

    s.client.action = MagicMock(return_value=Typing())
    s.client.send_message.side_effect = send
    start = clock.now
    asyncio.run(s.manager._schedule_deferred_reply(123, 1, "Ready for launch"))
    s.client.send_message.assert_awaited_once()
    assert events[-1][1] - start == expected
    assert events[-1][1] - start >= global_wait
    # Typing occupies exactly the last 5 s of the wait, with the pause between bursts inside it.
    assert events[-1][1] - events[0][1] == 5
    assert [event for event, _ in events] == ["typing", "typing_end", "typing", "typing_end", "sent"]
    assert events[-1][1] == events[-2][1]


def test_stop_during_credited_queue_wait_prevents_send(tmp_path, clock, monkeypatch):
    s = configure_timing(tmp_path, clock, monkeypatch, 40)
    clock.on_sleep = lambda _seconds: s.safety.set_emergency_stop(True)
    asyncio.run(s.manager._schedule_deferred_reply(123, 1, "Ready for launch"))
    s.client.send_message.assert_not_awaited()


def test_waiting_for_chat_lock_also_counts_toward_reading(tmp_path, clock, monkeypatch):
    s = configure_timing(tmp_path, clock, monkeypatch, 0)
    sent_at = []

    async def send(*_args, **_kwargs):
        sent_at.append(clock.now)
        return SimpleNamespace(id=777)

    s.client.send_message.side_effect = send

    async def run():
        lock = s.manager._get_chat_send_lock(123)
        await lock.acquire()
        start = clock.now
        task = asyncio.create_task(s.manager._send_reply(123, 1, "Ready for launch"))
        await asyncio.sleep(0)
        clock.now += 10
        lock.release()
        assert await asyncio.wait_for(task, timeout=3)
        assert sent_at[0] - start == 35

    asyncio.run(run())
