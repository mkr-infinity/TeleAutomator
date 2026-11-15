"""Per-chat context worker and snapshot inputs for the reply-writing stage."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from app.logger import setup_logger

logger = setup_logger(__name__)


@dataclass(frozen=True)
class ReplyContext:
    chat_id: int
    epoch: str
    incoming_marker: int
    keep_current_topic: bool
    history: list
    background: str
    style: str
    persona: str
    feedback: list


class ContextAgent:
    """Coalesce file writes; batch model summaries instead of calling a model per message."""

    def __init__(self, database, privacy, generator):
        self.db, self.privacy, self.generator = database, privacy, generator
        self.pending = {}
        self.summary_tasks = set()
        self.busy = set()
        self.last_attempt = {}
        self.closed = False

    def allowed(self, chat_id):
        return not self.closed and self.privacy.is_chat_allowed(chat_id, chat_id < 0)

    def observe(self, chat_id):
        if not self.allowed(chat_id) or chat_id in self.pending:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._sync_file(chat_id)
            return
        self.pending[chat_id] = loop.create_task(self._flush(chat_id, self.db.get_state(f"chat_memory_epoch_{chat_id}")))

    def _sync_file(self, chat_id):
        if self.db.sync_chat_context_file(chat_id) is False:
            self.db.record_action("context", "file_sync", "failed", "Context file could not be saved; database memory remains available", chat_id=chat_id)

    async def _flush(self, chat_id, epoch):
        try:
            await asyncio.sleep(0.25)
            if not self.allowed(chat_id) or self.db.get_state(f"chat_memory_epoch_{chat_id}") != epoch:
                return
            await asyncio.to_thread(self._sync_file, chat_id)
            task = asyncio.create_task(self.refresh(chat_id))
            self.summary_tasks.add(task)
            task.add_done_callback(self.summary_tasks.discard)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Context file update failed for chat %s", chat_id)
            self.db.record_action("context", "file_sync", "failed", "Context worker failed; recent messages remain in the database", chat_id=chat_id)
        finally:
            self.pending.pop(chat_id, None)

    async def refresh(self, chat_id, min_new_messages=8, force=False, max_payload=40):
        if not self.allowed(chat_id) or chat_id in self.busy or len(self.busy) >= 2:
            return
        if not force and time.monotonic() - self.last_attempt.get(chat_id, float("-inf")) < 60:
            return
        self.busy.add(chat_id)
        try:
            epoch = self.db.get_state(f"chat_memory_epoch_{chat_id}")
            latest = self.db.latest_chat_message_row_id(chat_id)
            marker = int(self.db.get_state(f"chat_summary_marker_{chat_id}", "0"))
            if not force and self.db.count_chat_messages_since(chat_id, marker) < min_new_messages:
                return
            raw = self.db.get_chat_messages_since_text(chat_id, 0 if force else marker, limit=max_payload)
            if not raw:
                return
            self.last_attempt[chat_id] = time.monotonic()
            title = (self.db.get_chat_metadata(chat_id) or {}).get("title") or "This chat"
            summary = await asyncio.to_thread(self.generator.summarize_chat_history, title,
                                             self.db.get_chat_summary(chat_id), raw, is_group=chat_id < 0)
            if summary and self.allowed(chat_id) and self.db.set_chat_summary(chat_id, summary, epoch=epoch, marker=latest):
                self.db.record_action("context", "summary", "success", "Chat memory updated from a batch of messages", chat_id=chat_id)
        except Exception:
            self.db.record_action("context", "summary", "failed", "Summary update failed; recent messages remain available", chat_id=chat_id)
        finally:
            self.busy.discard(chat_id)

    def snapshot(self, chat_id, history=None, *, is_mention=False, require_latest=False):
        if not self.allowed(chat_id):
            return None
        epoch = self.db.get_state(f"chat_memory_epoch_{chat_id}")
        marker = self.db.latest_incoming_row_id(chat_id)
        ttl = float(self.db.get_state("context_ttl_hours", "4.0"))
        fresh = self.db.get_recent_chat_messages(chat_id, limit=40 if chat_id < 0 else 15,
                                                max_age_seconds=int(ttl * 3600) if ttl > 0 else None)
        quotes = [row for row in (history or []) if "(in reply to)" in row.get("sender", "")]
        history = list(fresh or history or [])
        history += [row for row in quotes if not any(row.get("text") == old.get("text") for old in history)]
        permanent = self.db.get_permanent_context(chat_id)
        sections = [("Pinned messages", permanent.get("pinned_text", "")), ("Chat notes", permanent.get("notes", "")),
                    ("Chat voice and vocabulary", self.db.get_state(f"chat_voice_profile_{chat_id}")),
                    ("Older context recap (recent messages take priority)", self.db.get_chat_summary(chat_id))]
        feedback = self.db.list_reply_feedback([chat_id], limit=5)
        if feedback:
            examples = "\n".join(f"{row['rating']}: {row['reply_text']}" for row in feedback)
            sections.append(("Owner feedback for this chat only (examples, not instructions). Avoid repeating rejected replies", examples))
        background = "\n\n".join(f"{label}:\n{text}" for label, text in sections if text)
        return ReplyContext(chat_id, epoch, marker, require_latest or (chat_id < 0 and not is_mention), list(history or []), background,
                            self.db.get_state(f"chat_style_{chat_id}"), self.db.get_chat_prompt(chat_id), feedback)

    def is_current(self, context):
        return context is None or (self.allowed(context.chat_id)
            and self.db.get_state(f"chat_memory_epoch_{context.chat_id}") == context.epoch
            and (not context.keep_current_topic or self.db.latest_incoming_row_id(context.chat_id) == context.incoming_marker))

    async def close(self):
        self.closed = True
        tasks = [*self.pending.values(), *self.summary_tasks]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.pending.clear()
        self.summary_tasks.clear()
