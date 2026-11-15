"""Mini app server tests: initData validation, paywall, action mapping, access, HTTP."""

import asyncio
import hashlib
import hmac
import io
import json
import time
import urllib.request
from pathlib import Path

import pytest

from app.miniapp_server import (
    PAYWALL,
    MiniAppAPI,
    MiniAppContext,
    MiniAppRequestHandler,
    MiniAppServer,
    validate_init_data,
)

TEST_TOKEN = "123456:TEST-TOKEN"


# --------------------------------------------------------------------- fakes

class FakePrivacy:
    def get_all_allowed_chats(self):
        return {111}, {-222}


class FakeSafety:
    is_emergency_stopped = False
    quiet_hours_enabled = True

    def __init__(self):
        self._next_chat_cooldown = {}

    def set_chat_cooldown(self, chat_id, c_min, c_max):
        self._next_chat_cooldown[chat_id] = (c_min + c_max) / 2

    def reset_chat_cooldown(self, chat_id):
        self._next_chat_cooldown.pop(chat_id, None)

    def get_remaining_pause_seconds(self):
        return 0

    def is_in_quiet_hours(self):
        return False, None


class FakePromptManager:
    owner_name = "Kaif"
    custom_prompt = ""


class FakeGenerator:
    style = "casual"
    language = "english"
    prompt_manager = FakePromptManager()
    provider = type("GeminiProvider", (), {})()


class FakeReplyManager:
    config = type("C", (), {"reply_mode": "restricted_auto"})()

    def __init__(self):
        self.config = type("C", (), {"reply_mode": "restricted_auto"})()
        self.commands = []

    async def handle_control_command(self, command, **_audit):
        self.commands.append(command)
        return f"OK {command}"


def make_ctx(tmp_path, authorized=(555000111,), token=TEST_TOKEN):
    """Real Database (same file API the server uses) + lightweight manager fakes."""
    from app.storage.database import Database

    db = Database(tmp_path / "miniapp_test.db")
    if authorized:
        db.set_state("bot_authorized_users", json.dumps(list(authorized)))
        db.set_state("main_owner_id", str(authorized[0]))
    reply_mgr = FakeReplyManager()
    ctx = MiniAppContext(
        db=db, safety=FakeSafety(), privacy=FakePrivacy(),
        reply_manager=reply_mgr, generator=FakeGenerator(),
        bot_token=token, loop=None,
    )
    return ctx, reply_mgr


# ---------------------------------------------------------------- initData

def forge_init_data(token=TEST_TOKEN, user=None, auth_date=None, extra=""):
    user = user or {"id": 555000111, "first_name": "Kaif"}
    auth_date = auth_date or int(time.time())
    pairs = {"auth_date": str(auth_date), "user": json.dumps(user, separators=(",", ":"))}
    if extra:
        for chunk in extra.split("&"):
            k, _, v = chunk.partition("=")
            pairs[k] = v
    data_check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    sig = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return "&".join(f"{k}={pairs[k]}" for k in sorted(pairs)) + f"&hash={sig}"


def test_validate_init_data_valid():
    user = validate_init_data(forge_init_data(), TEST_TOKEN)
    assert user and user["id"] == 555000111


def test_validate_init_data_tampered():
    init_data = forge_init_data()
    bad = init_data.replace("555000111", "999999999")  # flip the payload, keep the signature
    assert validate_init_data(bad, TEST_TOKEN) is None


def test_validate_init_data_stale_auth_date():
    stale = forge_init_data(auth_date=int(time.time()) - 3 * 86400)
    assert validate_init_data(stale, TEST_TOKEN) is None


def test_validate_init_data_wrong_token_or_empty():
    assert validate_init_data(forge_init_data(), "99999:OTHER") is None
    assert validate_init_data("", TEST_TOKEN) is None
    assert validate_init_data(forge_init_data(), "") is None


# ------------------------------------------------------------------ paywall

def test_paywall_payload_shape():
    assert PAYWALL["contact"] == "@mkr_infinity"
    assert PAYWALL["contact_url"] == "https://t.me/mkr_infinity"
    assert "100 Telegram Stars" in PAYWALL["price_line"]
    assert "1 TON" in PAYWALL["price_line"]
    assert "1 month" in PAYWALL["price_line"]


def test_handle_auth_unauthorized_gets_paywall(tmp_path):
    ctx, _ = make_ctx(tmp_path, authorized=(555000111,))
    api = MiniAppAPI(ctx)
    payload = api.handle_auth({"id": 777000222, "first_name": "Stranger"})
    assert payload["authorized"] is False
    assert payload["paywall"] is PAYWALL


# ------------------------------------------------------------- action maps

def test_map_action_to_command_fills_and_strips():
    ctx, _ = make_ctx(tmp_path=Path("/tmp"), authorized=())
    api = MiniAppAPI(ctx)
    assert api.map_action_to_command("pause", {"minutes": 30}) == "/pause 30"
    assert api.map_action_to_command("mode", {"value": "approval"}) == "/mode approval"
    assert api.map_action_to_command("resume", {}) == "/resume"
    assert api.map_action_to_command("approve", {"id": 12}) == "/approve 12"
    assert api.map_action_to_command("reject", {"id": 12}) == "/reject 12"
    assert api.map_action_to_command("approve_all", {}) == "/approve all"
    assert api.map_action_to_command("reject_all", {}) == "/reject all"
    assert api.map_action_to_command("chatcooldown", {"value1": 5, "value2": 60}) == "/chatcooldown 5 60"
    assert api.map_action_to_command("gencontext", {"chat_id": -222}) == "/gencontext -222"
    assert api.map_action_to_command("unknown_action", {}) is None


def test_handle_action_chat_chatty(tmp_path):
    ctx, _ = make_ctx(tmp_path)
    api = MiniAppAPI(ctx)
    res = api.handle_action(555000111, "chat_chatty", {"chat_id": -222, "value": "40"})
    assert res["ok"] is True
    assert ctx.db.get_state("chat_chatty_-222") == "0.4"
    res = api.handle_action(555000111, "chat_chatty", {"chat_id": -222, "value": "def"})
    assert ctx.db.get_state("chat_chatty_-222") == ""
    assert "default" in res["response"].lower()


def test_handle_action_routes_through_engine(tmp_path):
    ctx, reply_mgr = make_ctx(tmp_path)
    api = MiniAppAPI(ctx)
    res = api.handle_action(555000111, "pause", {"minutes": 15})
    assert res["ok"] is True
    assert reply_mgr.commands == ["/pause 15"]


# ----------------------------------------------------------------- access

def test_access_change_requires_main_user(tmp_path):
    ctx, _ = make_ctx(tmp_path, authorized=(555000111, 777000222))
    api = MiniAppAPI(ctx)
    res = api.handle_action(777000222, "addauth", {"user_id": 999})
    assert res["ok"] is False
    assert json.loads(ctx.db.get_state("bot_authorized_users")) == [555000111, 777000222]


def test_access_change_add_and_remove(tmp_path):
    ctx, _ = make_ctx(tmp_path, authorized=(555000111,))
    api = MiniAppAPI(ctx)
    assert api.handle_action(555000111, "addauth", {"user_id": 777000222})["ok"] is True
    assert json.loads(ctx.db.get_state("bot_authorized_users")) == [555000111, 777000222]
    # main owner cannot be removed
    res = api.handle_action(555000111, "removeauth", {"user_id": 555000111})
    assert res["ok"] is False
    # others can
    res = api.handle_action(555000111, "removeauth", {"user_id": 777000222})
    assert res["ok"] is True
    assert json.loads(ctx.db.get_state("bot_authorized_users")) == [555000111]


def test_access_change_empty_list_bootstraps(tmp_path):
    ctx, _ = make_ctx(tmp_path, authorized=())
    api = MiniAppAPI(ctx)
    res = api.handle_action(999, "addauth", {"user_id": 555000111})
    # requester is not main (list was empty) — but bootstrap must be possible from the bot itself,
    # so the GUI denies and the state stays empty
    assert res["ok"] is False


# ----------------------------------------------------------------- state

def test_handle_state_and_activity(tmp_path):
    ctx, _ = make_ctx(tmp_path)
    api = MiniAppAPI(ctx)
    state = api.handle_state()
    assert state["state"] == "active"
    assert state["mode"]
    assert state["chats_allowed"] == 2
    assert "prompt" in state and "owner_name" in state
    assert state["quiet_hours_enabled"] is True
    ctx.safety.quiet_hours_enabled = False
    assert api.handle_state()["quiet_hours_enabled"] is False
    ctx.safety.quiet_hours_enabled = True
    # activity: real schema, one outgoing message
    with ctx.db._get_connection() as conn:
        conn.execute(
            "INSERT INTO known_chats (chat_id, title, username, chat_type) VALUES (?, ?, ?, ?)",
            (-222, "Test Group", "", "group"),
        )
        conn.execute(
            "INSERT INTO chat_messages (chat_id, message_id, sender_name, text, is_outgoing) "
            "VALUES (?, ?, ?, ?, 1)",
            (-222, 1, "TeleAutomator", "hello there",),
        )
    activity = api.handle_activity()["activity"]
    assert activity and activity[0]["chat"] == "Test Group" and "hello" in activity[0]["text"]


# ------------------------------------------------------------------- HTTP

@pytest.fixture()
def http_server(tmp_path):
    ctx, reply_mgr = make_ctx(tmp_path)
    server = MiniAppServer(MiniAppAPI(ctx), port=0)
    handler_ctx = server
    # bind the context for the handler + keep reply_mgr reachable
    bound = type("H", (MiniAppRequestHandler,), {"api": MiniAppAPI(ctx)})
    import http.server

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), bound)
    import threading

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd, ctx, reply_mgr
    httpd.shutdown()
    httpd.server_close()


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _post(url, payload, headers=None):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_http_static_index(http_server):
    httpd, _, _ = http_server
    with urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_port}/", timeout=5) as resp:
        html = resp.read().decode()
    assert resp.status == 200 and "TeleAutomator" in html


def test_http_api_requires_init_data(http_server):
    httpd, _, _ = http_server
    status, body = _get(f"http://127.0.0.1:{httpd.server_port}/api/state")
    assert status == 401
    assert body["authorized"] is False and body["paywall"]["contact"] == "@mkr_infinity"


def test_http_auth_and_action_roundtrip(http_server):
    httpd, ctx, reply_mgr = http_server
    base = f"http://127.0.0.1:{httpd.server_port}"
    init_data = forge_init_data()
    status, auth = _post(f"{base}/api/auth", {}, {"X-Telegram-Init-Data": init_data})
    assert status == 200 and auth["authorized"] is True and auth["is_main"] is True

    status, body = _get(f"{base}/api/state", {"X-Telegram-Init-Data": init_data})
    assert status == 200 and body["state"] == "active"

    status, body = _post(f"{base}/api/action", {"action": "pause", "params": {"minutes": 5}},
                         {"X-Telegram-Init-Data": init_data})
    assert status == 200 and body["ok"] is True
    assert reply_mgr.commands == ["/pause 5"]


def test_http_unauthorized_user_gets_paywall(http_server):
    httpd, _, _ = http_server
    base = f"http://127.0.0.1:{httpd.server_port}"
    stranger = forge_init_data(user={"id": 42, "first_name": "X"})
    status, body = _get(f"{base}/api/state", {"X-Telegram-Init-Data": stranger})
    assert status == 401 and body["paywall"]["contact"] == "@mkr_infinity"
    status, auth = _post(f"{base}/api/auth", {}, {"X-Telegram-Init-Data": stranger})
    assert status == 200 and auth["authorized"] is False and "paywall" in auth


def test_http_version_endpoint_public(http_server):
    httpd, _, _ = http_server
    base = f"http://127.0.0.1:{httpd.server_port}"
    status, body = _get(f"{base}/api/version")
    assert status == 200 and "version" in body and body["service"] == "teleautomator"


def test_map_action_to_command_preserves_multiline_prompt():
    ctx, _ = make_ctx(tmp_path=Path("/tmp"), authorized=())
    api = MiniAppAPI(ctx)
    res = api.map_action_to_command("prompt", {"value": "Line 1\n\nLine 2"})
    assert res == "/prompt Line 1\n\nLine 2"


def test_handle_state_includes_ai_engine_fields(tmp_path):
    ctx, _ = make_ctx(tmp_path)
    api = MiniAppAPI(ctx)
    ctx.db.set_state("ai_model", "test-model-4")
    ctx.db.set_state("ai_base_url", "https://api.example.com/v1")
    state = api.handle_state()
    assert state["ai_model"] == "test-model-4"
    assert state["ai_base_url"] == "https://api.example.com/v1"


def test_setcontext_and_delcontext_actions(tmp_path):
    ctx, reply_mgr = make_ctx(tmp_path)
    api = MiniAppAPI(ctx)
    cmd1 = api.map_action_to_command("setcontext", {"chat_id": -100123, "value": "Solana meme coin focus"})
    assert cmd1 == "/setcontext -100123 Solana meme coin focus"
    cmd2 = api.map_action_to_command("delcontext", {"chat_id": -100123})
    assert cmd2 == "/delcontext -100123"


def test_handle_chats_includes_context(tmp_path):
    ctx, _ = make_ctx(tmp_path)
    api = MiniAppAPI(ctx)
    ctx.db.set_permanent_context(-222, notes="Crypto group rules")
    res = api.handle_chats()
    matching = [c for c in res["chats"] if c["id"] == -222]
    assert len(matching) == 1
    assert matching[0]["context"] == "Crypto group rules"


def test_handle_fetch_models_parses_json(tmp_path, monkeypatch):
    ctx, _ = make_ctx(tmp_path)
    api = MiniAppAPI(ctx)

    class MockResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return json.dumps({
                "data": [{"id": "model-b"}, {"id": "model-a"}, {"id": "model-c"}]
            }).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=10.0: MockResponse())
    res = api.handle_fetch_models("https://custom.endpoint/v1")
    assert res["ok"] is True
    assert res["models"] == ["model-a", "model-b", "model-c"]


def test_handle_test_model_prunes_dead_and_saves_working(tmp_path, monkeypatch):
    ctx, _ = make_ctx(tmp_path)
    api = MiniAppAPI(ctx)

    class MockResponse:
        def __init__(self, model):
            self.model = model
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            if "fail" in self.model:
                raise urllib.error.HTTPError(None, 404, "Not Found", {}, None)
            return json.dumps({
                "choices": [{"message": {"content": f"Hello from {self.model}!"}}]
            }).encode("utf-8")

    def mock_urlopen(req, timeout=12.0):
        body = json.loads(req.data.decode("utf-8"))
        m = body.get("model", "")
        return MockResponse(m)

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    res = api.handle_test_model(
        message="hello",
        model="working-1,fail-model,working-2",
        base_url="https://api.openai.com/v1",
        api_key="test-key",
    )
    assert res["ok"] is True
    assert res["working_models"] == ["working-1", "working-2"]
    assert res["failed_models"] == ["fail-model"]
    assert res["active_model"] == "working-1,working-2"
    assert ctx.db.get_state("ai_model") == "working-1,working-2"
    assert "Hello from working-1!" in res["reply"]


def test_resolve_miniapp_url_railway_and_custom(monkeypatch):
    from app.miniapp_server import resolve_miniapp_url

    # 1. No env vars -> empty
    monkeypatch.delenv("MINIAPP_URL", raising=False)
    monkeypatch.delenv("CUSTOM_DOMAIN", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)
    monkeypatch.delenv("RAILWAY_STATIC_URL", raising=False)
    assert resolve_miniapp_url() == ""

    # 2. Railway auto-provided domain (zero extra domain needed!)
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "teleautomator-prod.up.railway.app")
    assert resolve_miniapp_url() == "https://teleautomator-prod.up.railway.app"

    # 3. Custom domain overrides Railway domain
    monkeypatch.setenv("CUSTOM_DOMAIN", "panel.mycustomdomain.com")
    assert resolve_miniapp_url() == "https://panel.mycustomdomain.com"


def test_handle_fetch_models_gemini(tmp_path, monkeypatch):
    ctx, _ = make_ctx(tmp_path)
    api = MiniAppAPI(ctx)

    class MockGeminiResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return json.dumps({
                "models": [
                    {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-2.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
                ]
            }).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=10.0: MockGeminiResponse())
    res = api.handle_fetch_models(api_key="AIzaSyTestKey")
    assert res["ok"] is True
    assert "gemini-2.5-flash-lite" in res["models"]
    assert "gemini-2.5-flash" in res["models"]
    assert "text-embedding-004" not in res["models"]


def test_handle_test_model_gemini_custom_message(tmp_path, monkeypatch):
    ctx, _ = make_ctx(tmp_path)
    api = MiniAppAPI(ctx)

    sent_prompt = None

    class MockGeminiTestResp:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return json.dumps({
                "candidates": [
                    {"content": {"parts": [{"text": f"Echo: {sent_prompt}"}]}}
                ]
            }).encode("utf-8")

    def mock_gemini_open(req, timeout=12.0):
        nonlocal sent_prompt
        body = json.loads(req.data.decode("utf-8"))
        sent_prompt = body["contents"][0]["parts"][0]["text"]
        return MockGeminiTestResp()

    monkeypatch.setattr(urllib.request, "urlopen", mock_gemini_open)
    res = api.handle_test_model(
        message="custom test question 123",
        model="gemini-2.5-flash",
        api_key="AIzaSyTestKey",
    )
    assert res["ok"] is True
    assert "custom test question 123" in res["reply"]
    assert res["working_models"] == ["gemini-2.5-flash"]


def test_map_action_allow_supports_username(tmp_path):
    ctx, _ = make_ctx(tmp_path)
    api = MiniAppAPI(ctx)
    cmd = api.map_action_to_command("allow", {"chat_id": "@mygroup"})
    assert cmd == "/allowchat @mygroup"
    cmd_remove = api.map_action_to_command("remove", {"chat_id": "@mygroup"})
    assert cmd_remove == "/removechat @mygroup"


def test_validate_init_data_real_telegram_url_encoded():
    import urllib.parse
    token = TEST_TOKEN
    user_dict = {"id": 555000111, "first_name": "Kaif"}
    auth_date = int(time.time())
    user_json = json.dumps(user_dict, separators=(",", ":"))

    # Exactly how Telegram client creates HMAC and encodes query
    pairs = {"auth_date": str(auth_date), "user": user_json}
    data_check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    sig = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()

    encoded_init_data = f"auth_date={auth_date}&user={urllib.parse.quote(user_json)}&hash={sig}"
    user = validate_init_data(encoded_init_data, token)
    assert user is not None
    assert user["id"] == 555000111
    assert user["first_name"] == "Kaif"


def test_authorized_user_fallback_to_seed_and_config(tmp_path):
    from app.miniapp_server import _authorized_user_ids
    from app.storage.database import Database

    db = Database(tmp_path / "empty_db.db")  # no bot_authorized_users key
    reply_mgr = FakeReplyManager()
    reply_mgr.config.bot_authorized_users = {888111, 888222}

    bot_ctrl = type("BotControl", (), {"seed_user_ids": {888111, 888333}})()

    ctx = MiniAppContext(
        db=db, safety=FakeSafety(), privacy=FakePrivacy(),
        reply_manager=reply_mgr, generator=FakeGenerator(),
        bot_token=TEST_TOKEN, loop=None, bot_control=bot_ctrl,
    )

    auth_ids = _authorized_user_ids(ctx)
    assert 888111 in auth_ids
    assert 888222 in auth_ids
    assert 888333 in auth_ids

    api = MiniAppAPI(ctx)
    res = api.handle_auth({"id": 888111, "first_name": "AuthorizedUser"})
    assert res["authorized"] is True
    assert "paywall" not in res


def test_miniapp_paywall_svg_icons():
    index_html = (Path(__file__).resolve().parent.parent / "miniapp" / "index.html").read_text()
    assert 'class="pay-curr-icon star-icon"' in index_html
    assert 'class="pay-curr-icon gram-icon"' in index_html
    assert 'viewBox="0 0 240 240"' in index_html  # authentic Gram SVG
    assert '100 Telegram Stars' not in index_html
    assert '1 TON' not in index_html
    assert 'id="pay-check-btn"' in index_html


def test_menu_button_text_is_open():
    import inspect
    from app.miniapp_server import set_telegram_menu_button
    sig = inspect.signature(set_telegram_menu_button)
    assert sig.parameters["button_text"].default == "Open"


def test_dynamic_authorization_lifecycle(tmp_path):
    ctx, _ = make_ctx(tmp_path, authorized=(555000111,))
    api = MiniAppAPI(ctx)

    # 1. User 999999 is NOT authorized initially
    auth_unauth = api.handle_auth({"id": 999999, "first_name": "Stranger"})
    assert auth_unauth["authorized"] is False
    assert "paywall" in auth_unauth

    # 2. Main owner adds user 999999 via GUI action
    res_add = api.handle_action(555000111, "addauth", {"user_id": 999999})
    assert res_add["ok"] is True

    # 3. User 999999 is NOW authorized - paywall screen is NOT shown
    auth_now = api.handle_auth({"id": 999999, "first_name": "Stranger"})
    assert auth_now["authorized"] is True
    assert "paywall" not in auth_now

    # 4. Main owner removes user 999999
    res_rem = api.handle_action(555000111, "removeauth", {"user_id": 999999})
    assert res_rem["ok"] is True

    # 5. User 999999 is unauthorized again
    auth_again = api.handle_auth({"id": 999999, "first_name": "Stranger"})
    assert auth_again["authorized"] is False


def test_data_sync_actions_immediate_persistence(tmp_path):
    ctx, _ = make_ctx(tmp_path, authorized=(555000111,))
    api = MiniAppAPI(ctx)

    # Chatty action writes directly to DB without any command line
    res = api.handle_action(555000111, "chat_chatty", {"chat_id": -222, "value": "45"})
    assert res["ok"] is True
    assert ctx.db.get_state("chat_chatty_-222") == "0.45"


def test_service_worker_asset_and_registration():
    miniapp_dir = Path(__file__).resolve().parent.parent / "miniapp"
    sw_file = miniapp_dir / "sw.js"
    assert sw_file.is_file()
    sw_content = sw_file.read_text(encoding="utf-8")
    assert "teleautomator-v3.0.8" in sw_content
    assert "caches.open" in sw_content
    assert "self.skipWaiting" in sw_content
    assert "self.clients.claim" in sw_content

    app_js = (miniapp_dir / "app.js").read_text(encoding="utf-8")
    assert "serviceWorker.register" in app_js


def test_behavior_simulation_help_popups_and_guide():
    miniapp_dir = Path(__file__).resolve().parent.parent / "miniapp"
    index_html = (miniapp_dir / "index.html").read_text(encoding="utf-8")
    app_js = (miniapp_dir / "app.js").read_text(encoding="utf-8")
    style_css = (miniapp_dir / "style.css").read_text(encoding="utf-8")

    # Verify Guide button and Help (?) buttons in HTML
    assert 'id="btn-all-behavior-help"' in index_html
    assert 'data-help="reaction"' in index_html
    assert 'data-help="multibubble"' in index_html
    assert 'data-help="typo"' in index_html
    assert 'data-help="debounce"' in index_html
    assert 'data-help="followup"' in index_html
    assert 'data-help="mentiononly"' in index_html

    # Verify JS functions and guide definitions
    assert "openHelpSheet" in app_js
    assert "openAllBehaviorGuideSheet" in app_js
    assert "BEHAVIOR_HELP" in app_js
    assert "WHEN ON" in app_js
    assert "WHEN OFF" in app_js

    # Verify CSS styling exists
    assert ".help-btn" in style_css
    assert ".help-guide-header-btn" in style_css
    assert ".help-popup-content" in style_css


def test_add_owner_by_username_and_avatar_rendering(tmp_path):
    ctx, _ = make_ctx(tmp_path, authorized=(555000111,))
    api = MiniAppAPI(ctx)

    # 1. Store known user in DB
    ctx.db.record_chat_metadata(777123456, title="Alice Smith", username="alicesmith", chat_type="Private contact")

    # 2. Add owner by @username
    res = api.handle_action(555000111, "addauth", {"user_id": "@alicesmith"})
    assert res["ok"] is True
    assert "777123456" in res["response"]

    # 3. Check handle_access returns avatar metadata
    access = api.handle_access()
    users = access["users"]
    alice = next((u for u in users if u["id"] == 777123456), None)
    assert alice is not None
    assert alice["name"] == "Alice Smith"
    assert alice["username"] == "alicesmith"
    assert "alicesmith.jpg" in alice["avatar_url"]
    assert "linear-gradient" in alice["avatar_bg"]
    assert alice["initials"] == "AS"
    assert alice["main"] is False


def test_save_available_models_and_manual_rotation(tmp_path):
    ctx, _ = make_ctx(tmp_path, authorized=(555000111,))
    api = MiniAppAPI(ctx)

    # 1. Initial state has default healthy models
    state = api.handle_state()
    assert "available_models" in state
    assert len(state["available_models"]) > 0

    # 2. Save custom models list
    res = api.handle_action(555000111, "save_available_models", {"models": ["mercury-3", "mercury-3-preview-1014"]})
    assert res["ok"] is True
    assert "2 available model(s)" in res["response"]

    # 3. Verify state persists custom available models
    state_after = api.handle_state()
    assert state_after["available_models"] == ["mercury-3", "mercury-3-preview-1014"]

    # 4. User manually sets rotation
    res_mod = api.handle_action(555000111, "model", {"value": "mercury-3"})
    assert res_mod["ok"] is True
    assert api.handle_state()["models_manually_set"] is True


def test_chat_cooldown_action_and_chats_payload(tmp_path):
    ctx, _ = make_ctx(tmp_path, authorized=(555000111,))
    api = MiniAppAPI(ctx)

    # Initial chats call has empty cooldown_str for chat 111
    chats = api.handle_chats()["chats"]
    c = next(x for x in chats if x["id"] == 111)
    assert c["cooldown_min"] is None
    assert c["cooldown_max"] is None
    assert c["cooldown_str"] == ""

    # Set custom cooldown
    res = api.handle_action(555000111, "chat_cooldown", {"chat_id": 111, "min": 15, "max": 45})
    assert res["ok"] is True
    assert "15s - 45s" in res["response"]
    if hasattr(ctx, "safety") and ctx.safety:
        assert 15.0 <= ctx.safety._next_chat_cooldown[111] <= 45.0

    # Verify chats payload reflects custom cooldown
    chats_after = api.handle_chats()["chats"]
    c_after = next(x for x in chats_after if x["id"] == 111)
    assert c_after["cooldown_min"] == 15.0
    assert c_after["cooldown_max"] == 45.0
    assert c_after["cooldown_str"] == "15s - 45s"

    # Set zero cooldown: Instant (no wait)
    res_zero = api.handle_action(555000111, "chat_cooldown", {"chat_id": 111, "min": 0, "max": 0})
    assert res_zero["ok"] is True
    assert "0s (Instant - No Wait)" in res_zero["response"]
    c_zero = next(x for x in api.handle_chats()["chats"] if x["id"] == 111)
    assert c_zero["cooldown_min"] == 0.0
    assert c_zero["cooldown_max"] == 0.0
    assert c_zero["cooldown_str"] == "0s (Instant - No Wait)"

    # Reset cooldown to global default
    res_reset = api.handle_action(555000111, "chat_cooldown", {"chat_id": 111, "reset": True})
    assert res_reset["ok"] is True
    assert "reset to global default" in res_reset["response"]
    if hasattr(ctx, "safety") and ctx.safety:
        assert 111 not in ctx.safety._next_chat_cooldown

    chats_reset = api.handle_chats()["chats"]
    c_reset = next(x for x in chats_reset if x["id"] == 111)
    assert c_reset["cooldown_min"] is None
    assert c_reset["cooldown_str"] == ""


def test_handle_activity_includes_msg_url(tmp_path):
    ctx, _ = make_ctx(tmp_path, authorized=(555000111,))
    api = MiniAppAPI(ctx)
    ctx.privacy.get_all_allowed_chats = lambda: ({111}, {-1001987654321})

    # Record outgoing message with username in known_chats
    ctx.db.record_chat_metadata(-1001987654321, title="Startup Supergroup", username="startupindia", chat_type="supergroup")
    with ctx.db._get_connection() as conn:
        conn.execute(
            """
            INSERT INTO chat_messages (chat_id, message_id, sender_id, sender_name, text, is_outgoing)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (-1001987654321, 555, 111, "TeleAutomator", "Test reply with link"),
        )

    acts = api.handle_activity()["activity"]
    assert len(acts) > 0
    first = acts[0]
    assert first["chat_id"] == -1001987654321
    assert first["message_id"] == 555
    assert first["msg_url"] == "https://t.me/startupindia/555"


def test_handle_fetch_models_base_url_normalization_and_errors(tmp_path, monkeypatch):
    """Test Base URL normalization (scheme, trailing slash, /chat/completions) and rich error messages."""
    ctx, _ = make_ctx(tmp_path)
    api = MiniAppAPI(ctx)

    called_urls = []

    def mock_urlopen_401(req, timeout=10.0):
        called_urls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"error": "Invalid API key provided"}'))

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_401)

    # 1. Base URL without scheme + with /chat/completions suffix
    res = api.handle_fetch_models(base_url="api.groq.com/openai/v1/chat/completions", api_key="bad-key")
    assert res["ok"] is False
    assert called_urls[0] == "https://api.groq.com/openai/v1/models"
    assert "Unauthorized" in res["error"]
    assert "Invalid API key" in res["error"]

    # 2. HTTP 404 Not Found error
    def mock_urlopen_404(req, timeout=10.0):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b'{"error": {"message": "Resource missing"}}'))

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_404)
    res404 = api.handle_fetch_models(base_url="https://api.example.com/v1/wrong_path", api_key="any-key")
    assert res404["ok"] is False
    assert "Not Found: verify Base URL" in res404["error"]

    # 3. Connection / URLError error
    def mock_urlopen_url_err(req, timeout=10.0):
        raise urllib.error.URLError("Name or service not known")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_url_err)
    res_conn = api.handle_fetch_models(base_url="https://bad-dns-typo.internal", api_key="any-key")
    assert res_conn["ok"] is False
    assert "Connection error" in res_conn["error"]
    assert "verify that base url" in res_conn["error"].lower()


def test_handle_action_chat_prompt_and_context(tmp_path):
    ctx, _ = make_ctx(tmp_path, authorized=(555000111,))
    api = MiniAppAPI(ctx)

    # 1. Save custom prompt for chat
    res_p = api.handle_action(555000111, "chatprompt", {"chat_id": 111, "value": "Talk like a friendly crypto dev"})
    assert res_p["ok"] is True
    assert "Custom prompt saved" in res_p["response"]
    assert ctx.db.get_state("chat_prompt_111") == "Talk like a friendly crypto dev"

    # Verify handle_chats returns it
    c = next(x for x in api.handle_chats()["chats"] if x["id"] == 111)
    assert c["prompt"] == "Talk like a friendly crypto dev"

    # 2. Reset custom prompt
    res_pr = api.handle_action(555000111, "chatprompt", {"chat_id": 111, "value": "default"})
    assert res_pr["ok"] is True
    assert ctx.db.get_state("chat_prompt_111") == ""

    # 3. Save permanent context notes
    res_ctx = api.handle_action(555000111, "setcontext", {"chat_id": 111, "value": "Admin is @john, launch date is Dec 1"})
    assert res_ctx["ok"] is True
    assert "Context notes saved" in res_ctx["response"]
    perm = ctx.db.get_permanent_context(111)
    assert perm.get("notes") == "Admin is @john, launch date is Dec 1"

    c = next(x for x in api.handle_chats()["chats"] if x["id"] == 111)
    assert c["context"] == "Admin is @john, launch date is Dec 1"

    # 4. Clear permanent context notes
    res_del = api.handle_action(555000111, "delcontext", {"chat_id": 111})
    assert res_del["ok"] is True
    perm_after = ctx.db.get_permanent_context(111)
    assert perm_after.get("notes") in ("", None)

    # 5. Set custom chat style
    res_style = api.handle_action(555000111, "chatstyle", {"chat_id": 111, "value": "concise"})
    assert res_style["ok"] is True
    assert ctx.db.get_state("chat_style_111") == "concise"


def test_handle_action_ownreact_toggle(tmp_path):
    ctx, _ = make_ctx(tmp_path, authorized=(555000111,))
    api = MiniAppAPI(ctx)

    # Initial default is ON
    assert api.handle_state()["ownreact"] is True

    # Turn OFF
    res_off = api.handle_action(555000111, "ownreact", {"value": "off"})
    assert res_off["ok"] is True
    assert "turned OFF" in res_off["response"]
    assert ctx.db.get_state("ownreact_enabled") == "0"
    assert api.handle_state()["ownreact"] is False

    # Turn ON
    res_on = api.handle_action(555000111, "ownreact", {"value": "on"})
    assert res_on["ok"] is True
    assert "turned ON" in res_on["response"]
    assert ctx.db.get_state("ownreact_enabled") == "1"
    assert api.handle_state()["ownreact"] is True


def test_native_sheet_dialog_and_explicit_expand_control():
    miniapp_dir = Path(__file__).resolve().parent.parent / "miniapp"
    index_html = (miniapp_dir / "index.html").read_text(encoding="utf-8")
    app_js = (miniapp_dir / "app.js").read_text(encoding="utf-8")

    # Verify sheet expand/collapse button in markup
    assert 'id="sheet-expand"' in index_html
    assert 'icon-expand' in index_html
    assert 'icon-collapse' in index_html

    assert '<dialog id="sheet"' in index_html
    assert 'aria-labelledby="sheet-title"' in index_html
    assert 'id="sheet-error" role="alert"' in index_html
    assert "initSheetControls" in app_js
    assert "toggleSheetExpanded" in app_js









