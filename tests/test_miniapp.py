"""Mini app server tests: initData validation, paywall, action mapping, access, HTTP."""

import asyncio
import hashlib
import hmac
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

    def get_remaining_pause_seconds(self):
        return 0

    def is_in_quiet_hours(self):
        return False, None


class FakePromptManager:
    owner_name = "Kaif"
    custom_prompt = ""


class FakeGenerator:
    style = "casual"
    prompt_manager = FakePromptManager()
    provider = type("GeminiProvider", (), {})()


class FakeReplyManager:
    config = type("C", (), {"reply_mode": "restricted_auto"})()

    def __init__(self):
        self.commands = []

    async def handle_control_command(self, command):
        self.commands.append(command)
        return f"OK {command}"


def make_ctx(tmp_path, authorized=(555000111,), token=TEST_TOKEN):
    """Real Database (same file API the server uses) + lightweight manager fakes."""
    from app.storage.database import Database

    db = Database(tmp_path / "miniapp_test.db")
    if authorized:
        db.set_state("bot_authorized_users", json.dumps(list(authorized)))
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
