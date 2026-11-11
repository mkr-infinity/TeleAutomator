"""Tests for the bot menu, engagement and conversation-ending features: full bot command menu, quick-action buttons, hot-chat engagement,
and always-on context (owner's own outgoing messages recorded)."""

from pathlib import Path

from app.bot_control import BOT_COMMAND_MENU, quick_menu_markup
from app.config import AppConfig
from app.event_handlers import adjust_engagement_for_room_heat, record_own_outgoing_message
from app.ai.reply_generator import ReplyGenerator
from app.privacy_manager import PrivacyManager
from app.reply_manager import _BOT_COMMAND_NAMES, ReplyManager
from app.safety_manager import SafetyManager
from app.storage.database import Database


# --------------------------------------------------------------------------- menu


def test_command_menu_covers_every_registered_command():
    """Every command the engine understands must appear in the '/' menu — no half menus."""
    menu_cmds = {c["command"] for c in BOT_COMMAND_MENU}
    registered = {name.lstrip("/") for name in _BOT_COMMAND_NAMES}
    missing = registered - menu_cmds
    assert not missing, f"Commands missing from bot menu: {sorted(missing)}"


def test_command_menu_entries_are_valid_and_unique():
    assert len(BOT_COMMAND_MENU) <= 100  # Telegram setMyCommands hard limit
    assert len(BOT_COMMAND_MENU) >= 60  # full toolbox, not a stub
    seen = set()
    for entry in BOT_COMMAND_MENU:
        cmd = entry["command"]
        desc = entry["description"]
        assert cmd and not cmd.startswith("/")
        assert cmd not in seen, f"Duplicate menu command: {cmd}"
        seen.add(cmd)
        assert desc and len(desc) <= 256  # Telegram description limit


def test_quick_menu_markup_structure():
    markup = quick_menu_markup()
    rows = markup["inline_keyboard"]
    assert len(rows) >= 3
    for row in rows:
        for btn in row:
            assert btn["callback_data"].startswith("cmd:/")
            assert btn["text"].strip()


# --------------------------------------------------------------------- engagement


def test_engagement_boosts_in_busy_rooms_and_dampens_in_dead_rooms():
    base = 0.20
    # Busy room (>=3 recent messages): more talkative, capped to stay non-spammy
    assert adjust_engagement_for_room_heat(base, 4) == min(0.55, base * 1.4)
    # Dead room (<=1 recent message): quieter but never fully silent
    dead = adjust_engagement_for_room_heat(base, 1)
    assert dead == base * 0.6
    # Normal room: unchanged
    assert adjust_engagement_for_room_heat(base, 2) == base
    # Never crosses the spam ceiling
    assert adjust_engagement_for_room_heat(0.60, 10) <= 0.55


def test_engagement_never_drops_below_floor():
    assert adjust_engagement_for_room_heat(0.01, 0) == 0.02


# --------------------------------------------------------- conversation endings


def test_thread_ender_detection():
    from app.event_handlers import is_thread_ender

    # closers: farewells, acknowledgments, laughter, emoji-only
    assert is_thread_ender("gn")
    assert is_thread_ender("gn bro")
    assert is_thread_ender("ok cool")
    assert is_thread_ender("thanks bro")
    assert is_thread_ender("hahaha")
    assert is_thread_ender("🤣")
    assert is_thread_ender("nice 👍")
    assert is_thread_ender("yep")
    assert is_thread_ender("fr fr")

    # real conversation: questions, statements, greetings — never thread enders
    assert not is_thread_ender("you coming tonight?")
    assert not is_thread_ender("good morning everyone")
    assert not is_thread_ender("what are you working on")
    assert not is_thread_ender("nice one bro")  # 'one' makes it a real statement
    assert not is_thread_ender("can you check the deploy when you wake up")
    assert not is_thread_ender("")


def test_thread_end_policy_thresholds():
    from app.event_handlers import decide_thread_end_action

    # groups: small reaction chance, otherwise the thread dies
    assert decide_thread_end_action(is_group=True, roll=0.10) == "reaction"
    assert decide_thread_end_action(is_group=True, roll=0.50) == "silent"

    # DMs: tiny ack sometimes, reaction sometimes, often left on read
    assert decide_thread_end_action(is_group=False, roll=0.20) == "reply"
    assert decide_thread_end_action(is_group=False, roll=0.50) == "reaction"
    assert decide_thread_end_action(is_group=False, roll=0.80) == "silent"


# ---------------------------------------------------------------- context always


def _make_manager(tmp_path: Path) -> ReplyManager:
    cfg = AppConfig(api_id=123, api_hash="dummy_hash", data_dir=tmp_path)
    db = Database(tmp_path / "own_msgs.db")
    return ReplyManager(cfg, db, SafetyManager(cfg, db), PrivacyManager(cfg, database=db), ReplyGenerator(cfg, database=db))


class _FakeEvent:
    def __init__(self, chat_id: int, msg_id: int, text: str):
        self.chat_id = chat_id
        self.id = msg_id
        self.raw_text = text
        self.out = True


def test_own_outgoing_recorded_and_not_duplicated(tmp_path: Path):
    mgr = _make_manager(tmp_path)
    event = _FakeEvent(chat_id=555, msg_id=101, text="brb grabbing coffee")
    record_own_outgoing_message(mgr, event, my_user_id=999)

    history = mgr.db.get_recent_chat_messages(555, limit=10)
    assert any("brb grabbing coffee" in m.get("text", "") for m in history)
    outgoing = [m for m in history if m.get("is_outgoing")]
    assert outgoing, "Owner's manual message must be marked outgoing"

    # A second event for the SAME message (e.g. automation echo) must not duplicate it
    record_own_outgoing_message(mgr, event, my_user_id=999)
    history2 = mgr.db.get_recent_chat_messages(555, limit=10)
    assert len(history2) == len(history)


def test_automation_recorded_message_not_overwritten(tmp_path: Path):
    mgr = _make_manager(tmp_path)
    # ReplyManager-style record with proper attribution (owner name)
    mgr.db.record_chat_message(
        chat_id=777, message_id=202, sender_id=None, sender_name="Kaif", text="on my way", is_outgoing=True
    )
    # The outgoing event handler must NOT overwrite the existing attribution
    record_own_outgoing_message(mgr, _FakeEvent(777, 202, "on my way"), my_user_id=999)
    with mgr.db._get_connection() as conn:
        row = conn.execute(
            "SELECT sender_name, text FROM chat_messages WHERE chat_id = 777 AND message_id = 202"
        ).fetchone()
    assert row["sender_name"] == "Kaif"
    assert row["text"] == "on my way"


# ------------------------------------------------------------------ cmd aliases


def test_allow_and_ban_aliases_route(tmp_path: Path):
    mgr = _make_manager(tmp_path)
    import asyncio

    res = asyncio.run(mgr.handle_control_command("/allow"))
    assert "/allowchat" in res  # same usage hint as the real command
    res2 = asyncio.run(mgr.handle_control_command("/ban"))
    assert "/blockchat" in res2


# -------------------------------------------------- command engine robustness


def test_bare_syncpins_does_not_crash(tmp_path: Path):
    """Regression: bare /syncpins used to hit a non-existent privacy.allowed_groups
    attribute and crash (silent no-reply in the bot). It must return a usage hint."""
    mgr = _make_manager(tmp_path)
    import asyncio

    res = asyncio.run(mgr.handle_control_command("/syncpins"))
    assert isinstance(res, str) and res  # answers, never crashes
    assert "syncpins" in res.lower()


def test_every_engine_command_answers_without_args(tmp_path: Path):
    """Robustness sweep: every command the engine owns must answer (string) even
    with no arguments — silent None or crashes mean users get ignored in the bot."""
    import asyncio

    from app.reply_manager import _BOT_COMMAND_NAMES

    mgr = _make_manager(tmp_path)
    bot_only = {"authlist", "addauth", "removeauth", "grantperm", "revokeperm", "watchdog"}
    no_answer = []
    for name in _BOT_COMMAND_NAMES:
        cmd = name.lstrip("/")
        if cmd in bot_only:
            continue  # handled in bot_control, not the shared engine
        try:
            res = asyncio.run(mgr.handle_control_command(f"/{cmd}"))
        except Exception as e:  # noqa: BLE001 - sweep must surface any crash
            no_answer.append(f"/{cmd} CRASHED: {type(e).__name__}")
            continue
        if res is None:
            no_answer.append(f"/{cmd} returned None")
    assert not no_answer, f"Commands that failed the no-arg sweep: {no_answer}"
