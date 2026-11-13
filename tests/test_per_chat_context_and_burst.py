"""Tests for v2.9.0 round: burst guard, per-chat chatty + picker callbacks, per-chat
persona prompts, AI voice profiles, menu dedupe, and structured context cards."""

import asyncio
import json
from pathlib import Path

from app.ai.prompt_manager import PromptManager
from app.ai.reply_generator import ReplyGenerator
from app.bot_control import BOT_COMMAND_MENU, BotControl, UNAUTHORIZED_MESSAGE, chatty_picker_markup
from app.config import AppConfig
from app.privacy_manager import PrivacyManager
from app.reply_manager import ReplyManager
from app.safety_manager import SafetyManager
from app.storage.database import Database


def _make_manager(tmp_path: Path) -> ReplyManager:
    cfg = AppConfig(api_id=123, api_hash="dummy_hash", data_dir=tmp_path)
    db = Database(tmp_path / "r2.db")
    return ReplyManager(cfg, db, SafetyManager(cfg, db), PrivacyManager(cfg, database=db), ReplyGenerator(cfg, database=db))


# ---------------------------------------------------------------------- menu dedupe


def test_menu_removed_duplicate_commands():
    """Aliases stay functional in the engine but must not clutter the '/' menu."""
    menu_cmds = {c["command"] for c in BOT_COMMAND_MENU}
    for dup in ("allow", "ban", "setprompt"):
        assert dup not in menu_cmds, f"/{dup} still duplicated in the menu"
    # New round-2 commands are present
    assert {"chatprompt", "gencontext"} <= menu_cmds


def test_engine_aliases_still_route(tmp_path: Path):
    """Removing /allow, /ban, /setprompt from the MENU must not break them in the ENGINE."""
    mgr = _make_manager(tmp_path)
    assert "/allowchat" in asyncio.run(mgr.handle_control_command("/allow"))
    assert "/blockchat" in asyncio.run(mgr.handle_control_command("/ban"))


# ---------------------------------------------------------------------- burst guard


def test_burst_guard_blocks_after_three_sends_then_releases(tmp_path: Path):
    cfg = AppConfig(api_id=123, api_hash="dummy", data_dir=tmp_path)
    db = Database(tmp_path / "burst.db")
    safety = SafetyManager(cfg, db)

    assert safety.burst_wait_needed(-100) == 0.0
    for _ in range(3):
        safety.record_burst_send(-100)
    wait = safety.burst_wait_needed(-100)
    assert wait > 0, "4th send within the window must be held back"
    assert wait <= safety.burst_window_seconds

    # Other chats are unaffected (per-chat windows)
    assert safety.burst_wait_needed(42) == 0.0

    # Window passes -> free again
    old = safety._burst_times[-100]
    safety._burst_times[-100] = type(old)(t - (safety.burst_window_seconds + 1) for t in old)
    assert safety.burst_wait_needed(-100) == 0.0


def test_burst_guard_custom_limits_and_multi_bubble_sequences(tmp_path: Path):
    cfg = AppConfig(api_id=123, api_hash="dummy", data_dir=tmp_path)
    db = Database(tmp_path / "burst2.db")
    db.set_state("burst_max_sends", "2")
    db.set_state("burst_window_seconds", "5.0")
    safety = SafetyManager(cfg, db)
    assert safety.burst_max_sends == 2
    assert safety.burst_window_seconds == 5.0

    safety.record_burst_send(-7)
    assert safety.burst_wait_needed(-7) == 0.0, "1 sequence used, still free"
    safety.record_burst_send(-7)
    assert safety.burst_wait_needed(-7) > 0, "2 sequences = cap reached at max=2"


# ------------------------------------------------------------------ per-chat chatty


def test_chatty_card_lists_per_chat_overrides(tmp_path: Path):
    mgr = _make_manager(tmp_path)
    card = asyncio.run(mgr.handle_control_command("/chatty"))
    assert "Group Banter Rate" in card
    assert "30" in card and "60" in card  # default band documented

    mgr.privacy.allow_chat(-100777)
    mgr.db.set_state("chat_chatty_-100777", "0.5")
    mgr.db.record_chat_metadata(-100777, title="Crypto Bros", chat_type="Group")
    card2 = asyncio.run(mgr.handle_control_command("/chatty"))
    assert "Crypto Bros" in card2 and "50%" in card2

    # Global off still works for explicitly-set global value
    res = asyncio.run(mgr.handle_control_command("/chatty off"))
    assert "DISABLED" in res or "strictly" in res.lower()


def test_chatty_picker_markup_and_callback_routing(tmp_path: Path):
    mgr = _make_manager(tmp_path)
    mgr.privacy.allow_chat(-100777)
    mgr.db.record_chat_metadata(-100777, title="Crypto Bros", chat_type="Group")
    mgr.privacy.allow_chat(100200)  # private chat shows up in the picker too
    mgr.db.record_chat_metadata(100200, title="Aman", chat_type="Private")

    cfg = AppConfig(api_id=123, api_hash="dummy", data_dir=tmp_path)
    bot = BotControl("dummy:token", mgr.db, mgr, seed_user_ids={42})

    markup = chatty_picker_markup(bot._allowed_chat_summaries())
    rows = markup["inline_keyboard"]
    assert len(rows) == 2
    for row in rows:
        assert row[0]["callback_data"].startswith("chatty:")
        assert {"10", "30", "50", "70"} <= {b["text"] for b in row}
        assert "DEF" in {b["text"] for b in row}

    calls: list[tuple[str, dict]] = []

    async def fake_call(method: str, payload: dict) -> dict:
        calls.append((method, payload))
        return {"ok": True}

    bot._call = fake_call  # type: ignore[method-assign]

    def cb(data: str) -> dict:
        return {"id": "cb1", "from": {"id": 42}, "data": data, "message": {"chat": {"id": 42}, "message_id": 1}}

    # Set 50% via button
    asyncio.run(bot._handle_callback(cb("chatty:-100777:50")))
    assert mgr.db.get_state("chat_chatty_-100777") == "0.5"

    # DEF resets to default band
    asyncio.run(bot._handle_callback(cb("chatty:-100777:default")))
    assert mgr.db.get_state("chat_chatty_-100777") == ""

    # Show answers a popup with the current setting
    calls.clear()
    asyncio.run(bot._handle_callback(cb("chatty:-100777:show")))
    answered = [p for m, p in calls if m == "answerCallbackQuery"]
    assert answered and "default band" in answered[0]["text"]

    # Unauthorized user cannot change anything
    calls.clear()
    asyncio.run(bot._handle_callback({"id": "cb2", "from": {"id": 999}, "data": "chatty:-100777:70", "message": {}}))
    assert mgr.db.get_state("chat_chatty_-100777") == ""


# ------------------------------------------------------------------ per-chat persona


def test_chatprompt_set_list_clear(tmp_path: Path):
    mgr = _make_manager(tmp_path)
    mgr.privacy.allow_chat(-100555)
    mgr.db.record_chat_metadata(-100555, title="Dev Lobby", chat_type="Group", username="devlobby")

    res = asyncio.run(mgr.handle_control_command("/chatprompt -100555 talk like a crypto trader, short replies"))
    assert "Per-Chat Persona Saved" in res and "Dev Lobby" in res and "@devlobby" in res
    assert mgr.db.get_state("chat_prompt_-100555") == "talk like a crypto trader, short replies"

    listing = asyncio.run(mgr.handle_control_command("/chatprompt"))
    assert "Dev Lobby" in listing and "crypto trader" in listing

    reset = asyncio.run(mgr.handle_control_command("/chatprompt -100555 default"))
    assert "reset" in reset.lower()
    assert mgr.db.get_state("chat_prompt_-100555") == ""


def test_persona_override_reaches_system_instructions():
    pm = PromptManager()
    with_override = pm.get_system_instructions(persona_override="TALK_LIKE_A_PIRATE_MARKER")
    assert "TALK_LIKE_A_PIRATE_MARKER" in with_override
    without = pm.get_system_instructions()
    assert "TALK_LIKE_A_PIRATE_MARKER" not in without


# ------------------------------------------------------------------ voice profiles


def test_voice_profile_guards(tmp_path: Path):
    mgr = _make_manager(tmp_path)
    # LocalRuleProvider (offline) and empty input must produce no profile
    assert mgr.generator.generate_voice_profile("Some Group", "") == ""
    assert mgr.generator.generate_voice_profile("Some Group", "a: hi\nb: yo") == ""
    # No client attached -> no fetch
    assert asyncio.run(mgr.generate_chat_voice_profile(-100123)) is None
    # Private chats are never voice-profiled
    assert asyncio.run(mgr.generate_chat_voice_profile(555)) is None


def test_voice_profile_flows_into_showcontext_card(tmp_path: Path):
    mgr = _make_manager(tmp_path)
    mgr.privacy.allow_chat(-100888)
    mgr.db.record_chat_metadata(-100888, title="Traders Den", chat_type="Group")
    mgr.db.set_state("chat_voice_profile_-100888", "Dry sarcastic tone, 3-6 word messages, heavy 'bhai' usage")
    mgr.db.set_permanent_context(-100888, notes="Solana trading group, no financial advice")

    card = asyncio.run(mgr.handle_control_command("/showcontext -100888"))
    assert "Traders Den" in card
    assert "Permanent Context" in card
    assert "Dry sarcastic tone" in card
    assert "Solana trading group" in card


def test_setcontext_card_is_structured(tmp_path: Path):
    mgr = _make_manager(tmp_path)
    mgr.privacy.allow_chat(-100999)
    mgr.db.record_chat_metadata(-100999, title="Solana Club", chat_type="Group", username="solanaclass")
    res = asyncio.run(mgr.handle_control_command("/setcontext -100999 meme coins only, keep it brief"))
    assert "Context Saved" in res and "Solana Club" in res and "@solanaclass" in res


# ------------------------------------------------------------------ unauthorized card


def test_unauthorized_message_is_structured():
    assert "━━━" in UNAUTHORIZED_MESSAGE
    assert "Access Restricted" in UNAUTHORIZED_MESSAGE
    assert "@mkr_infinity" in UNAUTHORIZED_MESSAGE


def test_isolated_per_group_context_files_on_disk(tmp_path: Path):
    """Verify each chat/group gets an isolated physical file by its ID, preventing any context mixing."""
    mgr = _make_manager(tmp_path)
    grp_a = -100111222333
    grp_b = -100444555666

    mgr.privacy.allow_chat(grp_a)
    mgr.privacy.allow_chat(grp_b)
    mgr.db.record_chat_metadata(grp_a, title="Crypto Alpha", chat_type="Group")
    mgr.db.record_chat_metadata(grp_b, title="Design Hub", chat_type="Group")

    # 1. Set context for Group A
    res_a = asyncio.run(mgr.handle_control_command(f"/setcontext {grp_a} Solana meme coins only, speak fast"))
    assert "Context Saved" in res_a

    # File on disk for Group A exists
    file_a = tmp_path / "contexts" / f"{grp_a}.json"
    assert file_a.exists(), f"Context file {file_a} should have been created"
    data_a = json.loads(file_a.read_text(encoding="utf-8"))
    assert data_a["chat_id"] == grp_a
    assert "Solana meme coins" in data_a["notes"]

    # Group B file does NOT exist yet (pure isolation)
    file_b = tmp_path / "contexts" / f"{grp_b}.json"
    assert not file_b.exists()

    # 2. Set context for Group B
    res_b = asyncio.run(mgr.handle_control_command(f"/setcontext {grp_b} Minimalist Figma layouts, critique only"))
    assert "Context Saved" in res_b

    # Group B file exists and has its own isolated context
    assert file_b.exists()
    data_b = json.loads(file_b.read_text(encoding="utf-8"))
    assert data_b["chat_id"] == grp_b
    assert "Figma" in data_b["notes"]
    assert "Solana" not in data_b["notes"]

    # 3. Add per-chat prompt to Group A
    asyncio.run(mgr.handle_control_command(f"/chatprompt {grp_a} Talk like a degenerate crypto trader"))
    data_a2 = json.loads(file_a.read_text(encoding="utf-8"))
    assert "degenerate crypto trader" in data_a2["prompt"]
    # Group B prompt remains untouched
    data_b2 = json.loads(file_b.read_text(encoding="utf-8"))
    assert data_b2["prompt"] == ""

    # 4. Deleting Group A's context removes Group A file, leaves Group B intact
    asyncio.run(mgr.handle_control_command(f"/delcontext {grp_a}"))
    assert not file_a.exists()
    assert file_b.exists()

