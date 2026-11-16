"""Concurrency and lifecycle regressions without live Telegram or provider calls."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.telegram_client import TelegramService
from app.ai.provider import LocalRuleProvider
from app.config import AppConfig
from app.safety_manager import SafetyManager
from app.storage.database import Database
from tests.test_workflow_regressions import make_stack


@pytest.mark.parametrize("message", ["Are you available now?", "Dinner tonight?", "Are you a bot?"])
def test_offline_provider_never_invents_personal_facts(message):
    prompt = f'Latest incoming message from Contact:\n"{message}"'
    assert not LocalRuleProvider().generate_reply(prompt, "Use configured personal facts only")


def test_keyword_reply_is_rewritten_by_the_model_using_chat_profile(tmp_path):
    s = make_stack(tmp_path)
    s.db.add_keyword_rule("pricing", "Contact the account owner for pricing")
    s.db.set_state("chat_prompt_123", "Reply briefly about product support")
    s.db.set_state("chat_style_123", "concise")
    s.db.set_permanent_context(123, notes="Pricing is being updated")
    s.generator.provider = SimpleNamespace(generate_reply=MagicMock(return_value="The price list is being updated"))
    asyncio.run(s.manager._process_incoming_message(123, "Contact", 1, 222, "Contact", "Any pricing update?"))
    s.generator.provider.generate_reply.assert_called_once()
    prompt, instructions = s.generator.provider.generate_reply.call_args.args
    assert "Contact the account owner for pricing" in prompt
    assert "Pricing is being updated" in prompt and "product support" in instructions
    assert s.client.send_message.await_args.args[1] != "Contact the account owner for pricing"


def test_no_model_means_no_canned_reply_or_keyword_bypass(tmp_path):
    s = make_stack(tmp_path)
    s.db.add_keyword_rule("pricing", "Hardcoded keyword reply")
    asyncio.run(s.manager._process_incoming_message(123, "Contact", 1, 222, "Contact", "Any pricing update?"))
    s.client.send_message.assert_not_awaited()
    assert not s.db.list_pending_approvals()


def test_failed_reply_generation_is_not_retried_as_a_typing_error(tmp_path):
    s = make_stack(tmp_path)
    s.generator.generate = MagicMock(side_effect=RuntimeError("Fixture provider failure"))
    asyncio.run(s.manager._process_incoming_message(123, "Contact", 1, 222, "Contact", "Any release update?"))
    s.generator.generate.assert_called_once()
    assert all(call.args[0] == "me" for call in s.client.send_message.await_args_list)


def test_default_cooldown_ranges_and_custom_chat_isolation(tmp_path):
    cfg = AppConfig(api_id=123, api_hash="fixture-hash")
    safety = SafetyManager(cfg, Database(tmp_path / "cooldowns.db"))
    assert (safety.min_global_cooldown, safety.max_global_cooldown) == (5, 60)
    assert safety._get_chat_cooldown_range(123) == (5, 60)
    safety.set_chat_cooldown(123, 12, 19)
    assert safety._get_chat_cooldown_range(123) == (12, 19)
    assert safety._get_chat_cooldown_range(-100111) == (5, 60)
    assert (safety.min_global_cooldown, safety.max_global_cooldown) == (5, 60)


def test_typing_runs_after_cooldown_and_immediately_before_send(tmp_path, clock):
    s = make_stack(tmp_path)
    s.db.set_state("min_global_cooldown_seconds", "10")
    s.db.set_state("max_global_cooldown_seconds", "10")
    s.safety.set_chat_cooldown(123, 0, 0)
    s.safety.mark_reply_sent(-100111)
    last_send = clock.now
    moments = []

    class Typing:
        async def __aenter__(self):
            moments.append(("typing", clock.now))
        async def __aexit__(self, *_args):
            moments.append(("typing_end", clock.now))

    s.client.action = MagicMock(return_value=Typing())

    async def send(*_args, **_kwargs):
        moments.append(("sent", clock.now))
        return SimpleNamespace(id=777)

    s.client.send_message.side_effect = send
    assert asyncio.run(s.manager._deliver_message(123, "Next reply", typing_seconds=5))
    assert moments[0][0] == "typing" and moments[0][1] >= last_send + 10
    assert 5.8 <= moments[-1][1] - moments[0][1] <= 6.4
    assert moments[-1][1] == moments[-2][1]


def test_adding_private_chat_saves_model_summarized_pins(tmp_path):
    s = make_stack(tmp_path)
    s.client.get_entity.return_value = SimpleNamespace(first_name="Contact", username="contact")
    s.client.get_messages.return_value = [SimpleNamespace(id=1, text="Release scheduled Friday", message="Release scheduled Friday", sender_id=222, out=False, get_sender=AsyncMock(return_value=None))]
    s.generator.distill_group_context = MagicMock(return_value="Release: Friday")
    asyncio.run(s.manager.init_chat_context(123))
    assert s.db.get_permanent_context(123)["pinned_text"] == "Release: Friday"
    assert "Release: Friday" in s.db._get_context_file_path(123).read_text()


def test_duplicate_chat_initialization_is_coalesced(tmp_path):
    s = make_stack(tmp_path)
    s.client.get_entity.return_value = SimpleNamespace(title="Development", username="development")
    s.client.get_messages.return_value = []

    async def run():
        started, release = asyncio.Event(), asyncio.Event()

        async def pins(_chat_id):
            started.set()
            await release.wait()

        s.manager.sync_pinned_context_from_telegram = AsyncMock(side_effect=pins)
        s.manager.generate_chat_voice_profile = AsyncMock()
        s.manager.refresh_single_chat_summary = AsyncMock()
        first = s.manager.start_background(s.manager.init_chat_context(-100111))
        try:
            await started.wait()
            await s.manager.init_chat_context(-100111)
            release.set()
            await first
            s.manager.sync_pinned_context_from_telegram.assert_awaited_once()
            assert not s.manager._context_initializing
        finally:
            release.set()
            await s.manager.close()

    asyncio.run(run())


def test_sensitive_pins_never_reach_model_or_context_file(tmp_path):
    s = make_stack(tmp_path)
    s.client.get_messages.return_value = [SimpleNamespace(text="Your login code is 24680")]
    s.generator.distill_group_context = MagicMock()
    assert asyncio.run(s.manager.sync_pinned_context_from_telegram(-100111)) is None
    s.generator.distill_group_context.assert_not_called()
    assert not s.db.get_permanent_context(-100111)["pinned_text"]


def test_summary_merges_new_messages_with_prior_recap_and_keeps_notes(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_permanent_context(-100111, notes="Owner note", pinned_text="Owner pin")
    for number in range(60):
        s.db.record_chat_message(-100111, number + 1, 222, "Contact", f"Release detail {number}")
    s.generator.summarize_chat_history = MagicMock(side_effect=["Launch Friday", "Launch Friday; test the mobile release"])

    async def run():
        agent = s.manager.context_agent
        await agent.refresh(-100111, force=True)
        first = s.generator.summarize_chat_history.call_args.args[2]
        # Oldest outstanding batch first, so no message is skipped by the 50-row payload cap.
        assert "Release detail 0\n" in first and "Release detail 49" in first and "Release detail 50" not in first
        for number in range(8):
            s.db.record_chat_message(-100111, 61 + number, 222, "Contact", f"New test detail {number}")
        agent.last_attempt[-100111] = float("-inf")
        await agent.refresh(-100111)
        _title, previous, new = s.generator.summarize_chat_history.call_args.args
        assert previous == "Launch Friday" and "New test detail 7" in new
        assert "Release detail 50" in new and "Release detail 59" in new and "Release detail 49" not in new
        assert s.db.get_chat_summary(123) == ""
        context_file = s.db._get_context_file_path(-100111).read_text()
        assert "Owner note" in context_file and "Owner pin" in context_file and "test the mobile release" in context_file
        await agent.close()

    asyncio.run(run())


def test_concurrent_duplicate_replies_are_blocked_at_delivery(tmp_path):
    s = make_stack(tmp_path)

    async def run():
        results = await asyncio.gather(
            s.manager._send_reply(123, 1, "Same reply", adaptive_delay=False),
            s.manager._send_reply(123, 2, "Same reply", adaptive_delay=False),
        )
        assert sum(results) == 1
        s.client.send_message.assert_awaited_once()

    asyncio.run(run())


def test_pin_fetch_rechecks_allowlist_before_provider_call(tmp_path):
    s = make_stack(tmp_path)
    s.generator.distill_group_context = MagicMock(return_value="Old pin")

    async def fetch(*_args, **_kwargs):
        s.privacy.remove_chat(-100111)
        return [SimpleNamespace(text="Old pinned announcement")]

    s.client.get_messages.side_effect = fetch
    assert asyncio.run(s.manager.sync_pinned_context_from_telegram(-100111)) is None
    s.generator.distill_group_context.assert_not_called()
    assert not s.db.get_permanent_context(-100111)["pinned_text"]


def test_voice_profile_cannot_save_after_allowlist_revocation(tmp_path):
    s = make_stack(tmp_path)
    s.client.get_messages.return_value = [SimpleNamespace(text="Release discussion", get_sender=AsyncMock(return_value=None)) for _ in range(12)]

    def generate(*_args):
        s.privacy.remove_chat(-100111)
        return "Old voice profile"

    s.generator.generate_voice_profile = MagicMock(side_effect=generate)
    assert asyncio.run(s.manager.generate_chat_voice_profile(-100111)) is None
    assert not s.db.get_state("chat_voice_profile_-100111")


def test_service_shutdown_cancels_pending_reply_work(tmp_path):
    s = make_stack(tmp_path)
    service = TelegramService(s.config, s.db, s.safety, s.privacy, s.manager, MagicMock())

    async def run():
        tasks = [asyncio.create_task(asyncio.Event().wait()) for _ in range(2)]
        s.manager._pending_deferred_replies[123] = tasks[0]
        s.manager._debounce_tasks[123] = tasks[1]
        try:
            await service.stop()
            assert all(task.done() for task in tasks)
            assert await s.manager._deliver_message(123, "After shutdown") is None
            s.client.send_message.assert_not_awaited()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    asyncio.run(run())


def test_typo_edit_rechecks_the_approving_operator(tmp_path, clock):
    s = make_stack(tmp_path)
    s.bot._save_authorized({111, 222})
    s.db.set_state("bot_granted_cmds_222", "/approve")
    s.db.set_state("typo_correction_enabled", "1")
    clock.on_sleep = lambda seconds: s.db.set_state("bot_granted_cmds_222", "/status") if seconds >= 1 else None
    with patch.object(s.manager, "maybe_inject_typo_correction", return_value=("Ready for relase tonight", "release")):
        assert asyncio.run(s.manager._send_reply(123, 1, "Ready for release tonight", adaptive_delay=False, approved=True, operator_id=222))
    s.client.send_message.assert_awaited_once()
    s.client.edit_message.assert_not_awaited()


def test_typo_correction_updates_persisted_duplicate_memory(tmp_path, clock):
    s = make_stack(tmp_path)
    s.db.set_state("typo_correction_enabled", "1")
    with patch.object(s.manager, "maybe_inject_typo_correction", return_value=("Ready for relase tonight", "release")):
        assert asyncio.run(s.manager._send_reply(123, 1, "Ready for release tonight", adaptive_delay=False))
    s.client.edit_message.assert_awaited_once()
    assert "Ready for release tonight" in s.manager._load_recent_replies_history()[123]


def test_context_file_flush_catches_messages_arriving_during_write(tmp_path):
    s = make_stack(tmp_path)
    started, release = threading.Event(), threading.Event()
    snapshots = []

    def sync(_chat_id):
        snapshots.append([row["text"] for row in s.db.get_recent_chat_messages(123)])
        if len(snapshots) == 1:
            started.set()
            release.wait(3)
        return True

    s.db.sync_chat_context_file = sync

    async def run():
        agent = s.manager.context_agent
        s.db.record_chat_message(123, 1, 222, "Contact", "First message")
        agent.observe(123)
        try:
            assert await asyncio.to_thread(started.wait, 2)
            s.db.record_chat_message(123, 2, 222, "Contact", "Last message")
            agent.observe(123)
            release.set()
            await asyncio.wait_for(asyncio.gather(*agent.pending.values()), timeout=3)
            assert snapshots[-1] == ["First message", "Last message"]
        finally:
            release.set()
            await agent.close()

    asyncio.run(run())


def test_model_health_deduplicates_candidates(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_state("models_manually_set", "1")
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"Working"}}]}'
    with patch("urllib.request.urlopen", return_value=response) as request:
        result = s.api.handle_test_model(model="same,same,models/same", base_url="https://example.test/v1", api_key="fixture-key")
    assert result["working_models"] == ["same"]
    assert request.call_count == 1


def test_model_health_respects_total_request_budget(tmp_path):
    s = make_stack(tmp_path)
    s.db.set_state("models_manually_set", "1")
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"Working"}}]}'
    elapsed = [0.0]

    def probe(_request, timeout):
        elapsed[0] += timeout
        return response

    with patch("app.miniapp_server.time.monotonic", side_effect=lambda: elapsed[0]), patch("urllib.request.urlopen", side_effect=probe) as request:
        result = s.api.handle_test_model(model="first,second,third,fourth", base_url="https://example.test/v1", api_key="fixture-key")
    assert elapsed[0] <= 30.0
    assert request.call_count == 3
    assert "budget" in result["results"][-1]["detail"].lower()


def test_slow_model_probe_does_not_overwrite_a_newer_model_choice(tmp_path):
    s = make_stack(tmp_path)
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"Working"}}]}'

    def probe(*_args, **_kwargs):
        s.db.set_state("ai_model", "Owner-selected-model")
        return response

    original = s.generator.provider
    with patch("urllib.request.urlopen", side_effect=probe):
        result = s.api.handle_test_model(model="Old-probe-model", base_url="https://example.test/v1", api_key="fixture-key", auto_apply=True)
    assert not result["auto_applied"]
    assert s.db.get_state("ai_model") == "Owner-selected-model"
    assert s.generator.provider is original


def test_failed_model_activation_preserves_saved_settings(tmp_path):
    s = make_stack(tmp_path)
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"Working"}}]}'
    keys = ("ai_model", "ai_base_url", "ai_api_key", "ai_provider", "ai_enabled")
    before = {key: s.db.get_state(key) for key in keys}
    with patch("urllib.request.urlopen", return_value=response), patch("app.ai.reply_generator.create_ai_provider", side_effect=ValueError("Invalid provider")):
        result = s.api.handle_test_model(model="replacement", base_url="https://example.test/v1", api_key="fixture-key", auto_apply=True)
    assert not result["ok"]
    assert {key: s.db.get_state(key) for key in keys} == before


def test_failed_startup_leaves_no_signal_waiter_task(tmp_path):
    from app.main import run_app
    s = make_stack(tmp_path)
    service = SimpleNamespace(run=AsyncMock(side_effect=RuntimeError("Fixture startup failure")), stop=AsyncMock())

    async def run():
        before = asyncio.all_tasks()
        with patch("app.main.load_config", return_value=s.config), patch("app.main.TelegramService", return_value=service), \
                patch("app.miniapp_server.MiniAppServer"), patch("app.miniapp_server.resolve_miniapp_url", return_value=""), \
                patch.object(asyncio.get_running_loop(), "add_signal_handler"):
            with pytest.raises(RuntimeError, match="Fixture startup failure"):
                await run_app()
        remaining = asyncio.all_tasks() - before
        try:
            assert not remaining
        finally:
            for task in remaining:
                task.cancel()
            await asyncio.gather(*remaining, return_exceptions=True)

    asyncio.run(run())
