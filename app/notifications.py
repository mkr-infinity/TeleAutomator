"""Status notices for authorized operators: model failures, quiet-hours changes and Mini App edits."""

from __future__ import annotations

import datetime
import time

from app.logger import redact_secrets, setup_logger

logger = setup_logger(__name__)

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
MODEL_ISSUE_INTERVAL_SECONDS = 600.0
QUIET_HOURS_STATE_KEY = "quiet_hours_notice_state"


def _now_ist() -> str:
    return datetime.datetime.now(IST).strftime("%d %b %Y, %H:%M IST")


def _clip(value, limit: int = 300) -> str:
    """Redact before clipping so a cut can never expose part of a secret."""
    text = redact_secrets(str(value or "")).strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _code(value, limit: int = 120) -> str:
    """Inline code keeps model names, errors and names from being parsed as Markdown."""
    return "`" + str(value).replace("`", "'")[:limit] + "`"


async def notify_authorized(reply_manager, text: str) -> bool:
    """Send a status notice to every authorized user, or through the no-bot control fallback."""
    try:
        bot = getattr(reply_manager, "bot_control", None)
        if bot is not None:
            return bool(await bot.send_alert_all(text))
        return bool(await reply_manager._send_control_alert_unlocked(text))
    except Exception as exc:
        logger.warning("Status notice failed: %s", type(exc).__name__)
        return False


async def report_model_issue(reply_manager, task: str, error: BaseException) -> bool:
    """Report a failed model call; the same task and error type is sent at most once per 10 minutes."""
    db = reply_manager.db
    key = f"model_issue_last_{task}:{type(error).__name__}"
    now = time.time()
    try:
        last = float(db.get_state(key, "0") or 0)
    except ValueError:
        last = 0.0
    if 0 <= now - last < MODEL_ISSUE_INTERVAL_SECONDS:
        return False
    db.set_state(key, str(now))  # persisted first so restarts and concurrent failures do not repeat it
    provider = getattr(getattr(reply_manager, "generator", None), "provider", None)
    active = getattr(provider, "active_model", "")
    detail = f"{type(error).__name__}: {error}" if str(error) else type(error).__name__
    text = (
        f"⚠️ *AI model issue: {task}*\n"
        f"• Provider: {_code(type(provider).__name__)}\n"
        f"• Model: {_code(getattr(provider, 'model', '') or 'not set', 300)}"
        + (f" (last working: {_code(active)})" if active else "") + "\n"
        f"• Error: {_code(_clip(detail), 300)}\n"
        f"• Time: {_now_ist()}\n"
        "Nothing was sent to any chat. Check the API key, quota and model list in AI settings."
    )
    return await notify_authorized(reply_manager, text)


def model_error_callback(loop, reply_manager):
    """Build ReplyGenerator.on_model_error: runs in model worker threads, hands the report to the
    event loop without blocking generation, and never raises."""
    def start(task, error):
        reply_manager.start_background(report_model_issue(reply_manager, task, error))

    def callback(task, error):
        try:
            loop.call_soon_threadsafe(start, task, error)
        except Exception:
            pass  # the loop already closed during shutdown
    return callback


async def check_quiet_hours_transition(reply_manager) -> bool:
    """Announce a natural quiet-hours start or end once; first runs and schedule edits stay silent."""
    safety, db = reply_manager.safety, reply_manager.db
    start, end = safety.quiet_hours_window
    in_quiet = bool(safety.is_in_quiet_hours()[0])
    config = f"{int(bool(safety.quiet_hours_enabled))}|{start}|{end}"
    current = f"{config}|{int(in_quiet)}"
    previous = db.get_state(QUIET_HOURS_STATE_KEY, "")
    if current == previous:
        return False
    db.set_state(QUIET_HOURS_STATE_KEY, current)  # persisted before sending: at most one notice per flip
    if previous.rpartition("|")[0] != config:
        return False  # first run or a manual schedule change, which the Mini App change log covers
    if in_quiet:
        text = f"🌙 Quiet hours started. Replies are paused until {end} IST."
    else:
        held = safety.action_block_reason()
        text = (f"☀️ Quiet hours ended, but replies are still held: {held}." if held
                else "☀️ Quiet hours ended. Replies are active again.")
    return await notify_authorized(reply_manager, text)


def format_change(actor_id, actor_name, label, response) -> str:
    """Change-log notice for one successful Mini App edit."""
    who = f"{actor_name} ({actor_id})" if actor_name and str(actor_name) != str(actor_id) else str(actor_id)
    return (
        "🛠 *Mini App change*\n"
        f"• When: {_now_ist()}\n"
        f"• Who: {_code(who)}\n"
        f"• What: {_code(label)}\n"
        f"• Result: {_clip(response) or 'Done'}"
    )
