import asyncio
from types import SimpleNamespace

import pytest


@pytest.fixture
def clock(monkeypatch):
    original_sleep = asyncio.sleep
    value = SimpleNamespace(now=1000.0, on_sleep=lambda seconds: None)
    async def sleep(seconds):
        value.on_sleep(seconds)
        value.now += seconds
        await original_sleep(0)
    value.sleep = sleep
    monkeypatch.setattr("app.reply_manager.time.time", lambda: value.now)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    return value
