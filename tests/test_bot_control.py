"""Tests for the Telegram Bot API control channel (bot_control.py)."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.bot_control import (
    AUTHORIZED_NOTICE,
    BOT_COMMAND_HELP,
    REMOVED_NOTICE,
    SPAM_WARNING_MESSAGE,
    BotControl,
)
from app.config import AppConfig
from app.reply_manager import ReplyManager
from app.safety_manager import SafetyManager
from app.privacy_manager import PrivacyManager
from app.ai.reply_generator import ReplyGenerator
from app.storage.database import Database


def _make_config(tmp_path: Path, seed: str = "111,222") -> AppConfig:
    return AppConfig(
        api_id=123,
        api_hash="dummy_hash",
        data_dir=tmp_path,
        bot_api_key="1234567890:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        bot_authorized_users={int(x) for x in seed.split(",")},
    )


def _make_bot(tmp_path: Path, seed: str = "111,222") -> tuple[BotControl, ReplyManager, Database]:
    cfg = _make_config(tmp_path, seed)
    db = Database(tmp_path / "bot.db")
    mgr = ReplyManager(cfg, db, SafetyManager(cfg, db), PrivacyManager(cfg, database=db), ReplyGenerator(cfg, database=db))
    bot = BotControl(cfg.bot_api_key, db, mgr, seed_user_ids=cfg.bot_authorized_users)
    mgr.bot_control = bot
    return bot, mgr, db


def test_env_seed_bootstrap_and_main_owner(tmp_path: Path) -> None:
    bot, _mgr, db = _make_bot(tmp_path)

    # Env seeds the DB list once; lowest ID becomes the main owner
    assert bot._load_authorized() == {111, 222}
    assert bot.main_user_id == 111
    assert bot.is_authorized(222)
    assert not bot.is_authorized(999)


def test_env_seed_sync_when_db_already_exists(tmp_path: Path) -> None:
    import json
    cfg = _make_config(tmp_path, seed="111,222")
    db = Database(tmp_path / "bot_preexisting.db")
    # Pre-existing DB has a different user ID
    db.set_state("bot_authorized_users", json.dumps([999]))

    mgr = ReplyManager(cfg, db, SafetyManager(cfg, db), PrivacyManager(cfg, database=db), ReplyGenerator(cfg, database=db))
    bot = BotControl(cfg.bot_api_key, db, mgr, seed_user_ids=cfg.bot_authorized_users)

    # All seed users plus pre-existing DB user are authorized
    assert bot.is_authorized(111) is True
    assert bot.is_authorized(222) is True
    assert bot.is_authorized(999) is True
    assert bot._load_authorized() == {111, 222, 999}
    assert bot.main_user_id == 111



def test_authorization_applies_instantly_and_add_remove_flow(tmp_path: Path) -> None:
    bot, _mgr, _db = _make_bot(tmp_path)

    sent: list[tuple[int, str]] = []

    async def fake_call(method: str, payload: dict) -> dict:
        if method == "sendMessage":
            sent.append((payload["chat_id"], payload["text"]))
            return {"ok": True}
        return {"ok": True, "result": {}}

    with patch.object(BotControl, "_call", new=AsyncMock(side_effect=fake_call)):
        # Main owner (111) adds user 333 -> instant DB update + authorized notice sent to 333
        asyncio.run(bot._process_update({
            "update_id": 1,
            "message": {"text": "/addauth 333", "chat": {"id": 111}, "from": {"id": 111, "is_bot": False}},
        }))

    assert bot.is_authorized(333)
    assert (333, AUTHORIZED_NOTICE) in sent
    assert any(uid == 111 and "now authorized" in text for uid, text in sent)

    sent.clear()
    with patch.object(BotControl, "_call", new=AsyncMock(side_effect=fake_call)):
        # Non-main user cannot add
        asyncio.run(bot._process_update({
            "update_id": 2,
            "message": {"text": "/addauth 444", "chat": {"id": 222}, "from": {"id": 222, "is_bot": False}},
        }))
        # Main owner cannot remove the main account or empty the list
        asyncio.run(bot._process_update({
            "update_id": 3,
            "message": {"text": "/removeauth 111", "chat": {"id": 111}, "from": {"id": 111, "is_bot": False}},
        }))
        # Removing another user works + notifies the removed user
        asyncio.run(bot._process_update({
            "update_id": 4,
            "message": {"text": "/removeauth 333", "chat": {"id": 111}, "from": {"id": 111, "is_bot": False}},
        }))

    assert not bot.is_authorized(444)  # unauthorized add attempt had no effect
    assert bot.is_authorized(111)  # main owner can never be removed
    assert len(bot._load_authorized()) >= 1  # list never empty
    assert bot.is_authorized(333) is False
    assert (333, REMOVED_NOTICE) in sent
    assert any(uid == 222 and "Only the main account owner" in text for uid, text in sent)


def test_authorized_command_routes_to_reply_manager(tmp_path: Path) -> None:
    bot, _mgr, _db = _make_bot(tmp_path)

    sent: list[tuple[int, str]] = []

    async def fake_call(method: str, payload: dict) -> dict:
        if method == "sendMessage":
            sent.append((payload["chat_id"], payload["text"]))
            return {"ok": True}
        return {"ok": True, "result": {}}

    with patch.object(BotControl, "_call", new=AsyncMock(side_effect=fake_call)):
        asyncio.run(bot._process_update({
            "update_id": 1,
            "message": {"text": "/start", "chat": {"id": 111}, "from": {"id": 111, "is_bot": False}},
        }))

    # /start gets help + status reply routed through the shared command engine
    assert any(uid == 111 and BOT_COMMAND_HELP in text for uid, text in sent)
    assert any(uid == 111 and "TeleAutomator" in text for uid, text in sent)


def test_editfix_and_ownreact_toggles(tmp_path: Path) -> None:
    _bot, mgr, db = _make_bot(tmp_path)

    on_msg = asyncio.run(mgr.handle_control_command("/editfix"))
    assert "ON" in on_msg
    off_msg = asyncio.run(mgr.handle_control_command("/editfix off"))
    assert "DISABLED" in off_msg
    assert db.get_state("editfix_enabled") == "0"
    back_on = asyncio.run(mgr.handle_control_command("/editfix on"))
    assert "ENABLED" in back_on
    assert db.get_state("editfix_enabled") == "1"

    asyncio.run(mgr.handle_control_command("/ownreact off"))
    assert db.get_state("ownreact_enabled") == "0"
    asyncio.run(mgr.handle_control_command("/ownreact on"))
    assert db.get_state("ownreact_enabled") == "1"


def test_unauthorized_user_flow_strikes_then_ignored(tmp_path: Path) -> None:
    bot, _mgr, db = _make_bot(tmp_path, seed="111")

    sent: list[tuple[int, str, Optional[str]]] = []

    async def fake_call(method: str, payload: dict) -> dict:
        if method == "sendMessage":
            sent.append((payload["chat_id"], payload["text"], payload.get("parse_mode")))
            return {"ok": True}
        return {"ok": True, "result": {}}

    with patch.object(BotControl, "_call", new=AsyncMock(side_effect=fake_call)), \
         patch("app.bot_control.asyncio.sleep", new=AsyncMock(return_value=None)):
        for _ in range(4):
            asyncio.run(bot._process_update({
                "update_id": 1,
                "message": {"text": "hello who are you", "chat": {"id": 777}, "from": {"id": 777, "is_bot": False}},
            }))

    user_msgs = [(text, mode) for uid, text, mode in sent if uid == 777]
    assert len(user_msgs) == 3  # friendly notice x2 (with @mkr_infinity contact), then spam warning
    assert all("mkr_infinity" in text for text, _ in user_msgs)
    assert any(SPAM_WARNING_MESSAGE in text for text, _ in user_msgs)
    assert all(mode == "HTML" for _, mode in user_msgs)  # parse_mode HTML ensures <b> tags render properly
    assert db.get_state("bot_spam_counter_777") == "4"


def test_alerts_route_to_bot_main_user(tmp_path: Path) -> None:
    bot, mgr, _db = _make_bot(tmp_path, seed="111")
    # No Telegram client attached: only the bot control channel can deliver
    mgr._client = None
    mgr.bot_control = bot

    chat_ids: list[int] = []

    async def fake_call(method: str, payload: dict) -> dict:
        if method == "sendMessage":
            chat_ids.append(payload["chat_id"])
            return {"ok": True}
        return {"ok": True, "result": {}}

    with patch.object(BotControl, "_call", new=AsyncMock(side_effect=fake_call)):
        asyncio.run(mgr._notify_issue_to_saved_messages(
            chat_id=-42, chat_title="Devs", sender_name="Raj",
            error_msg="AI provider failed: 401", incoming_text="hey", force=True,
        ))
        assert asyncio.run(bot.send_alert("test")) is True

    assert chat_ids == [111, 111]  # both alerts routed to the main account owner


def test_bot_send_message_markdown_fallback(tmp_path: Path) -> None:
    _bot, _mgr, db = _make_bot(tmp_path, seed="111")
    bot = BotControl(_make_config(tmp_path, seed="111").bot_api_key, db, object(), seed_user_ids={111})

    calls: list[dict] = []

    async def fake_call(method: str, payload: dict) -> dict:
        calls.append({"method": method, **payload})
        if payload.get("parse_mode") == "Markdown":
            raise RuntimeError("can't parse entities")
        return {"ok": True}

    with patch.object(BotControl, "_call", new=AsyncMock(side_effect=fake_call)):
        ok = asyncio.run(bot.send_message(111, "**bold** [broken", parse_markdown=True))

    assert ok is True
    modes = [c.get("parse_mode") for c in calls if c["method"] == "sendMessage"]
    assert modes == ["Markdown", None]  # Markdown first, then safe plain-text retry


def _stub_bot_calls(bot: BotControl, sent: list[tuple[int, str]]) -> None:
    async def fake_call(method: str, payload: dict) -> dict:
        if method == "sendMessage":
            sent.append((payload["chat_id"], payload["text"]))
            return {"ok": True}
        return {"ok": True, "result": {}}
    return AsyncMock(side_effect=fake_call)


def test_pause_durations_multitoken_and_bare_minutes(tmp_path: Path) -> None:
    _bot, mgr, _db = _make_bot(tmp_path)

    assert mgr._parse_duration("30 min") == 1800.0
    assert mgr._parse_duration("2 hours") == 7200.0
    assert mgr._parse_duration("90s") == 90.0
    assert mgr._parse_duration("1d 2h") == 93600.0
    assert mgr._parse_duration("45") == 2700.0  # bare number = minutes (was hours before)
    assert mgr._parse_duration("2 xyz") is None

    safety = mgr.safety
    msg = asyncio.run(mgr.handle_control_command("/pause 30 min"))
    assert "PAUSED" in msg and 1700 < safety.get_remaining_pause_seconds() <= 1800
    asyncio.run(mgr.handle_control_command("/resume"))
    assert safety.get_remaining_pause_seconds() == 0.0

    msg = asyncio.run(mgr.handle_control_command("/pause 90s"))
    assert "PAUSED" in msg and 80 < safety.get_remaining_pause_seconds() <= 90


def test_pause_expiry_auto_resumes_and_alerts_control_channel(tmp_path: Path) -> None:
    import time as _time

    bot, mgr, db = _make_bot(tmp_path, seed="111")
    alerts: list[tuple[int, str]] = []

    async def fake_call(method: str, payload: dict) -> dict:
        if method == "sendMessage":
            alerts.append((payload["chat_id"], payload["text"]))
            return {"ok": True}
        return {"ok": True, "result": {}}

    with patch.object(BotControl, "_call", new=AsyncMock(side_effect=fake_call)):
        # Pause for 2 seconds, wait it out, heartbeat watcher resumes + alerts
        asyncio.run(mgr.handle_control_command("/pause 2s"))
        assert mgr.safety.get_remaining_pause_seconds() > 0
        _time.sleep(2.1)
        asyncio.run(mgr.check_pause_expiry())
        assert mgr.safety.get_remaining_pause_seconds() == 0.0
        assert alerts and alerts[-1][0] == 111  # routed to main owner
        assert "Timed pause ended" in alerts[-1][1]

        # Calling again must not duplicate the alert (pause already cleared)
        alerts.clear()
        asyncio.run(mgr.check_pause_expiry())
        assert not alerts


def test_command_permissions_grant_revoke_enforcement(tmp_path: Path) -> None:
    bot, _mgr, db = _make_bot(tmp_path)  # authorized: 111 (main), 222 (secondary)

    sent: list[tuple[int, str]] = []
    routed: list[str] = []

    async def fake_call(method: str, payload: dict) -> dict:
        if method == "sendMessage":
            sent.append((payload["chat_id"], payload["text"]))
            return {"ok": True}
        return {"ok": True, "result": {}}

    manager = bot.reply_manager
    async def fake_route(cmd: str):
        routed.append(cmd)
        return f"ran {cmd}"

    with patch.object(BotControl, "_call", new=AsyncMock(side_effect=fake_call)):
        with patch.object(manager, "handle_control_command", new=fake_route):
            # Restrict 222 to /status only
            asyncio.run(bot._process_update({
                "update_id": 1,
                "message": {"text": "/grantperm 222 /status", "chat": {"id": 111}, "from": {"id": 111, "is_bot": False}},
            }))
            assert db.get_state("bot_granted_cmds_222") == "/status"

            # Allowed command still routes
            asyncio.run(bot._process_update({
                "update_id": 2,
                "message": {"text": "/status", "chat": {"id": 222}, "from": {"id": 222, "is_bot": False}},
            }))
            assert "/status" in routed

            # Non-granted command is blocked before reaching the engine
            asyncio.run(bot._process_update({
                "update_id": 3,
                "message": {"text": "/pause 2h", "chat": {"id": 222}, "from": {"id": 222, "is_bot": False}},
            }))
            assert not any(c.startswith("/pause") for c in routed)
            assert any(uid == 222 and "not permitted" in text for uid, text in sent)

            # Command aliases with @botname suffix still match
            asyncio.run(bot._process_update({
                "update_id": 4,
                "message": {"text": "/status@My.ControlBot", "chat": {"id": 222}, "from": {"id": 222, "is_bot": False}},
            }))
            assert any(c.startswith("/status@") or c == "/status" for c in routed)

            # revokeperm restores full access
            asyncio.run(bot._process_update({
                "update_id": 5,
                "message": {"text": "/revokeperm 222", "chat": {"id": 111}, "from": {"id": 111, "is_bot": False}},
            }))
            assert db.get_state("bot_granted_cmds_222", "all") == "all"


def test_approval_inline_buttons_flow(tmp_path: Path) -> None:
    bot, mgr, _db = _make_bot(tmp_path, seed="111")

    calls: list[dict] = []
    routed: list[str] = []

    async def fake_call(method: str, payload: dict) -> dict:
        calls.append({"method": method, **payload})
        if method == "getChat":
            return {"ok": True, "result": {"first_name": "Kaif"}}
        return {"ok": True, "result": {}}

    manager = mgr
    async def fake_route(cmd: str):
        routed.append(cmd)
        return "✅ Draft sent to chat."

    with patch.object(BotControl, "_call", new=AsyncMock(side_effect=fake_call)):
        # Card carries an inline keyboard
        asyncio.run(bot.send_approval_card("*Draft #12 pending*", 12))
        send = [c for c in calls if c["method"] == "sendMessage"][-1]
        assert "✅ Approve #12" in send["reply_markup"] and "❌ Reject #12" in send["reply_markup"]

        # Tapping reject routes to the shared engine & answers the callback
        calls.clear()
        with patch.object(manager, "handle_control_command", new=fake_route):
            asyncio.run(bot._process_update({
                "update_id": 1,
                "callback_query": {
                    "id": "cbq1", "data": "reject:12",
                    "from": {"id": 111, "is_bot": False},
                    "message": {"chat": {"id": 111}, "message_id": 900},
                },
            }))
        assert "/reject 12" in routed
        assert any(c["method"] == "answerCallbackQuery" and "Draft sent" in c["text"] for c in calls)


def test_watchdog_stale_heartbeat_alerts_once(tmp_path: Path) -> None:
    import os as _os

    bot, mgr, db = _make_bot(tmp_path, seed="111")
    health = tmp_path / "health.json"
    health.write_text('{"status":"healthy"}')
    bot.health_file = health
    alerts: list[str] = []

    async def fake_call(method: str, payload: dict) -> dict:
        if method == "sendMessage":
            alerts.append(payload["text"])
            return {"ok": True}
        return {"ok": True, "result": {}}

    with patch.object(BotControl, "_call", new=AsyncMock(side_effect=fake_call)):
        # Fresh heartbeat: no alert
        asyncio.run(bot._watchdog_check())
        assert not alerts

        # Simulate 10 minutes of silence (threshold default 5 min)
        stale_ts = __import__("time").time() - 600
        _os.utime(health, (stale_ts, stale_ts))
        asyncio.run(bot._watchdog_check())
        assert alerts and "Watchdog Alert" in alerts[0]

        # Alert throttled within 30 min
        alerts.clear()
        asyncio.run(bot._watchdog_check())
        assert not alerts


def test_welcome_card_sent_on_startup(tmp_path: Path) -> None:
    bot, _mgr, _db = _make_bot(tmp_path, seed="111")
    from unittest.mock import AsyncMock

    sent: list[tuple[int, str]] = []

    async def fake_call(method: str, payload: dict) -> dict:
        if method == "sendMessage":
            sent.append((payload["chat_id"], payload["text"]))
            return {"ok": True}
        if method == "getMe":
            return {"ok": True, "result": {"username": "MyCtrlBot"}}
        return {"ok": True, "result": {"ok_count": len(sent)}}

    with patch.object(BotControl, "_call", new=AsyncMock(side_effect=fake_call)):
        asyncio.run(bot.send_welcome_card("MyCtrlBot"))

    assert sent and sent[-1][0] == 111
    card = sent[-1][1]
    assert "TeleAutomator is live" in card
    assert "@MyCtrlBot" in card
    assert "111" in card
