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
    return bot, mgr, db


def test_env_seed_bootstrap_and_main_owner(tmp_path: Path) -> None:
    bot, _mgr, db = _make_bot(tmp_path)

    # Env seeds the DB list once; lowest ID becomes the main owner
    assert bot._load_authorized() == {111, 222}
    assert bot.main_user_id == 111
    assert bot.is_authorized(222)
    assert not bot.is_authorized(999)


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

    sent: list[tuple[int, str]] = []

    async def fake_call(method: str, payload: dict) -> dict:
        if method == "sendMessage":
            sent.append((payload["chat_id"], payload["text"]))
            return {"ok": True}
        return {"ok": True, "result": {}}

    with patch.object(BotControl, "_call", new=AsyncMock(side_effect=fake_call)), \
         patch("app.bot_control.asyncio.sleep", new=AsyncMock(return_value=None)):
        for _ in range(4):
            asyncio.run(bot._process_update({
                "update_id": 1,
                "message": {"text": "hello who are you", "chat": {"id": 777}, "from": {"id": 777, "is_bot": False}},
            }))

    texts = [text for uid, text in sent if uid == 777]
    assert len(texts) == 3  # friendly notice x2 (with @mkr_infinity contact), then spam warning
    assert all("mkr_infinity" in text for text in texts)
    assert any(SPAM_WARNING_MESSAGE in text for text in texts)
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
