"""Lightweight SQLite database for pending approvals and state deduplication."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from app.logger import redact_secrets, setup_logger
from app.session_manager import ensure_secure_dir, ensure_secure_file

logger = setup_logger(__name__)


class Database:
    """Thread-safe SQLite storage for pending approvals and deduplication."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._context_lock = threading.RLock()
        ensure_secure_dir(db_path.parent)
        self.contexts_dir = db_path.parent / "contexts"
        ensure_secure_dir(self.contexts_dir)
        self._init_db()
        ensure_secure_file(self.db_path)

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;

                CREATE TABLE IF NOT EXISTS action_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    chat_id INTEGER,
                    actor_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_action_history_status ON action_history(status, id DESC);

                CREATE TABLE IF NOT EXISTS reply_feedback (
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    rating TEXT NOT NULL CHECK(rating IN ('helpful','unnecessary','off_topic','style')),
                    reply_text TEXT NOT NULL,
                    actor_id INTEGER,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(chat_id, message_id)
                );

                CREATE TABLE IF NOT EXISTS pending_approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    chat_title TEXT,
                    reply_to_msg_id INTEGER NOT NULL,
                    sender_id INTEGER,
                    incoming_text TEXT,
                    draft_text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_pending_approvals_status ON pending_approvals(status);

                CREATE TABLE IF NOT EXISTS message_dedup (
                    msg_hash TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS runtime_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS keyword_rules (
                    keyword TEXT PRIMARY KEY,
                    reply TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS reaction_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reaction_events_timestamp ON reaction_events(timestamp);

                CREATE TABLE IF NOT EXISTS reply_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    timestamp REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reply_events_timestamp ON reply_events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_reply_events_chat_timestamp ON reply_events(chat_id, timestamp);

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    sender_id INTEGER,
                    sender_name TEXT,
                    text TEXT NOT NULL,
                    is_outgoing INTEGER NOT NULL DEFAULT 0,
                    is_automated INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(chat_id, message_id)
                );
                CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_id ON chat_messages(chat_id, id DESC);

                CREATE TABLE IF NOT EXISTS known_chats (
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    username TEXT NOT NULL DEFAULT '',
                    chat_type TEXT NOT NULL DEFAULT '',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS token_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_token_usage_created_at ON token_usage(created_at);

                CREATE TABLE IF NOT EXISTS permanent_chat_context (
                    chat_id INTEGER PRIMARY KEY,
                    pinned_text TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_status_id ON pending_approvals(status,id)")
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(chat_messages)")}
            if "is_automated" not in columns:
                conn.execute("ALTER TABLE chat_messages ADD COLUMN is_automated INTEGER NOT NULL DEFAULT 0")
                # Older automated sends used no sender ID; manual events retained the account ID.
                conn.execute("UPDATE chat_messages SET is_automated=1 WHERE is_outgoing=1 AND sender_id IS NULL")

    def add_approval(
        self,
        chat_id: int,
        chat_title: str,
        reply_to_msg_id: int,
        sender_id: int | None,
        incoming_text: str,
        draft_text: str,
    ) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO pending_approvals (
                    chat_id, chat_title, reply_to_msg_id, sender_id, incoming_text, draft_text, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """,
                (chat_id, chat_title, reply_to_msg_id, sender_id, incoming_text, draft_text),
            )
            self._pending_revision(conn)
            return int(cursor.lastrowid)

    @staticmethod
    def _pending_revision(conn):
        conn.execute("INSERT INTO runtime_state(key,value) VALUES('state_revision',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(time.time_ns()),))

    def get_pending_approval(self, approval_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM pending_approvals WHERE id = ? AND status = 'pending'",
                (approval_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_pending_approvals(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM pending_approvals WHERE status = 'pending' ORDER BY id ASC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def claim_approval(self, approval_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            claimed = conn.execute(
                "UPDATE pending_approvals SET status = 'sending' WHERE id = ? AND status = 'pending'",
                (approval_id,),
            )
            if not claimed.rowcount:
                return None
            self._pending_revision(conn)
            return dict(conn.execute("SELECT * FROM pending_approvals WHERE id = ?", (approval_id,)).fetchone())

    def update_approval_status(self, approval_id: int, status: str, expected_status: Optional[str] = None) -> bool:
        with self._get_connection() as conn:
            query = "UPDATE pending_approvals SET status = ? WHERE id = ?"
            params = (status, approval_id)
            if expected_status is not None:
                query += " AND status = ?"
                params += (expected_status,)
            cursor = conn.execute(
                query, params,
            )
            if cursor.rowcount:
                self._pending_revision(conn)
            return cursor.rowcount > 0

    def reject_all_pending(self) -> int:
        with self._get_connection() as conn:
            changed = conn.execute("UPDATE pending_approvals SET status='rejected' WHERE status='pending'").rowcount
            if changed:
                self._pending_revision(conn)
            return changed

    def is_duplicate_message(self, msg_hash: str) -> bool:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM message_dedup WHERE msg_hash = ?",
                (msg_hash,),
            ).fetchone()
            return row is not None

    def record_message(self, msg_hash: str, chat_id: int) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO message_dedup (msg_hash, chat_id) VALUES (?, ?)",
                (msg_hash, chat_id),
            )

    def set_state(self, key: str, value: str) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO runtime_state (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            conn.execute(
                "INSERT INTO runtime_state (key, value) VALUES ('state_revision', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(time.time_ns()),),
            )

    def get_state(self, key: str, default: str = "") -> str:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM runtime_state WHERE key = ?",
                (key,),
            ).fetchone()
            return str(row["value"]) if row else default

    def get_chat_panel_data(self, chat_ids):
        """Read chat cards in one connection instead of opening a connection for every field."""
        ids = tuple(chat_ids)
        metadata, contexts, states = {}, {}, {}
        if not ids:
            return metadata, contexts, states
        with self._get_connection() as conn:
            for offset in range(0, len(ids), 400):
                batch = ids[offset:offset + 400]
                slots = ",".join("?" for _ in batch)
                metadata.update((row["chat_id"], dict(row)) for row in conn.execute("SELECT * FROM known_chats WHERE chat_id IN (" + slots + ")", batch))
                contexts.update((row["chat_id"], dict(row)) for row in conn.execute("SELECT * FROM permanent_chat_context WHERE chat_id IN (" + slots + ")", batch))
            prefixes = ("chat_chatty_*", "chat_style_*", "chat_prompt_*", "chat_cooldown_min_*", "chat_cooldown_max_*", "chat_voice_profile_*")
            rows = conn.execute("SELECT key,value FROM runtime_state WHERE " + " OR ".join("key GLOB ?" for _ in prefixes), prefixes)
            states = {row["key"]: row["value"] for row in rows}
        for cid in ids:
            if cid not in contexts and self._get_context_file_path(cid).is_file():
                contexts[cid] = self.get_permanent_context(cid)
        return metadata, contexts, states

    def count_pending_approvals(self) -> int:
        with self._get_connection() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM pending_approvals WHERE status='pending'").fetchone()[0])

    def backup_to(self, path: Path) -> None:
        """Use SQLite's consistent backup snapshot while the live database keeps receiving writes."""
        ensure_secure_dir(path.parent)
        with self._get_connection() as source, sqlite3.connect(str(path)) as target:
            source.backup(target)
        ensure_secure_file(path)

    def record_action(self, source: str, action: str, status: str, detail: str = "", *, chat_id=None, actor_id=None) -> None:
        """Keep bounded metadata, never command arguments or message bodies; auditing cannot interrupt delivery."""
        try:
            with self._get_connection() as conn:
                row = conn.execute(
                    "INSERT INTO action_history (source, action, status, detail, chat_id, actor_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (source[:32], redact_secrets(action)[:64], status[:16], redact_secrets(detail)[:300], chat_id, actor_id),
                )
                if row.lastrowid % 100 == 0:
                    conn.execute("DELETE FROM action_history WHERE id <= ?", (row.lastrowid - 1000,))
        except Exception:
            logger.warning("Could not record action history")

    def latest_action_id(self) -> int:
        with self._get_connection() as conn:
            return int(conn.execute("SELECT COALESCE(MAX(id), 0) FROM action_history").fetchone()[0])

    def list_actions(self, status: str = "", before: int = 0, limit: int = 40) -> List[Dict[str, Any]]:
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if before:
            clauses.append("id < ?")
            params.append(before)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM action_history" + where + " ORDER BY id DESC LIMIT ?",
                                (*params, max(1, min(100, limit)))).fetchall()
            return [dict(row) for row in rows]

    def apply_preferences(self, states: Dict[str, str], contexts: List[Dict[str, Any]], rules: List[Dict[str, str]], *, expected_states=None) -> bool:
        """Apply a validated preference plan atomically, then refresh isolated context files."""
        with self._context_lock:
            with self._get_connection() as conn:
                if expected_states is not None:
                    conn.execute("BEGIN IMMEDIATE")
                    for key, expected in expected_states.items():
                        row = conn.execute("SELECT value FROM runtime_state WHERE key=?", (key,)).fetchone()
                        if (row["value"] if row else "") != expected:
                            return False
                conn.executemany(
                    "INSERT INTO runtime_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    [*states.items(), ("state_revision", str(time.time_ns()))],
                )
                for context in contexts:
                    conn.execute(
                        "INSERT INTO permanent_chat_context (chat_id, notes, pinned_text) VALUES (?, ?, ?) "
                        "ON CONFLICT(chat_id) DO UPDATE SET notes = excluded.notes, pinned_text = excluded.pinned_text, updated_at = CURRENT_TIMESTAMP",
                        (context["id"], context["notes"], context["pinned_text"]),
                    )
                conn.executemany(
                    "INSERT INTO keyword_rules (keyword, reply) VALUES (?, ?) ON CONFLICT(keyword) DO UPDATE SET reply = excluded.reply",
                    [(rule["keyword"], rule["reply"]) for rule in rules],
                )
            for context in contexts:
                self.sync_chat_context_file(context["id"])
            return True

    def add_keyword_rule(self, keyword: str, reply: str) -> None:
        """Add or update custom trigger keyword and reply."""
        clean_kw = keyword.strip().lower()
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO keyword_rules (keyword, reply) VALUES (?, ?) "
                "ON CONFLICT(keyword) DO UPDATE SET reply = excluded.reply",
                (clean_kw, reply.strip()),
            )

    def delete_keyword_rule(self, keyword: str) -> bool:
        """Delete custom keyword rule."""
        clean_kw = keyword.strip().lower()
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM keyword_rules WHERE keyword = ?", (clean_kw,))
            return cursor.rowcount > 0

    def list_keyword_rules(self) -> List[Dict[str, str]]:
        """List all active custom keyword rules."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT keyword, reply FROM keyword_rules ORDER BY keyword ASC").fetchall()
            return [{"keyword": r["keyword"], "reply": r["reply"]} for r in rows]

    def match_keyword_rule(self, text: str) -> Optional[str]:
        """Check if message contains any configured trigger keywords."""
        if not text:
            return None
        lower_text = text.lower()
        rules = self.list_keyword_rules()
        for rule in rules:
            kw = rule["keyword"]
            # Word boundary or substring match
            if re.search(r"\b" + re.escape(kw) + r"\b", lower_text) or kw in lower_text:
                return rule["reply"]
        return None

    def record_reaction(self, ts: float) -> None:
        """Record timestamp of a sent reaction."""
        with self._get_connection() as conn:
            conn.execute("INSERT INTO reaction_events (timestamp) VALUES (?)", (ts,))

    def get_recent_reaction_count(self, window_seconds: float) -> int:
        """Count reactions sent within the last window_seconds."""
        import time
        cutoff = time.time() - max(1.0, window_seconds)
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM reaction_events WHERE timestamp >= ?",
                (cutoff,),
            ).fetchone()
            return int(row["cnt"]) if row else 0

    def prune_old_reactions(self, max_age_seconds: float = 86400.0) -> None:
        """Delete reaction timestamps older than max_age_seconds."""
        import time
        cutoff = time.time() - max_age_seconds
        with self._get_connection() as conn:
            conn.execute("DELETE FROM reaction_events WHERE timestamp < ?", (cutoff,))

    def record_reply_event(self, chat_id: int, ts: float) -> None:
        """Record timestamp and chat of an outgoing automated reply for anti-spam rate limiting."""
        with self._get_connection() as conn:
            conn.execute("INSERT INTO reply_events (chat_id, timestamp) VALUES (?, ?)", (chat_id, ts))

    def get_recent_reply_count(self, window_seconds: float, chat_id: Optional[int] = None) -> int:
        """Count automated replies sent within the last window_seconds globally or for a specific chat."""
        import time
        cutoff = time.time() - max(1.0, window_seconds)
        with self._get_connection() as conn:
            if chat_id is not None:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM reply_events WHERE timestamp >= ? AND chat_id = ?",
                    (cutoff, chat_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM reply_events WHERE timestamp >= ?",
                    (cutoff,),
                ).fetchone()
            return int(row["cnt"]) if row else 0

    def get_last_reply_timestamp(self, chat_id: Optional[int] = None) -> float:
        """Retrieve timestamp of the most recent automated reply globally or for a specific chat."""
        with self._get_connection() as conn:
            if chat_id is not None:
                row = conn.execute(
                    "SELECT timestamp FROM reply_events WHERE chat_id = ? ORDER BY id DESC LIMIT 1",
                    (chat_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT timestamp FROM reply_events ORDER BY id DESC LIMIT 1",
                ).fetchone()
            return float(row["timestamp"]) if row else 0.0

    def prune_old_reply_events(self, max_age_seconds: float = 86400.0) -> None:
        """Delete reply timestamps older than max_age_seconds."""
        import time
        cutoff = time.time() - max_age_seconds
        with self._get_connection() as conn:
            conn.execute("DELETE FROM reply_events WHERE timestamp < ?", (cutoff,))

    def record_chat_message(
        self,
        chat_id: int,
        message_id: int,
        sender_id: Optional[int],
        sender_name: str,
        text: str,
        is_outgoing: bool = False,
        is_automated: bool = False,
    ) -> None:
        """Cache message in database with automatic size and row capping to keep resource usage minimal."""
        if not text or not text.strip():
            return
        # Cap stored message length to 300 chars to avoid memory/disk bloat
        truncated_text = text.strip()[:300]
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO chat_messages (chat_id, message_id, sender_id, sender_name, text, is_outgoing, is_automated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, message_id) DO UPDATE SET
                    text = excluded.text,
                    sender_name = excluded.sender_name,
                    is_automated = MAX(chat_messages.is_automated, excluded.is_automated)
                """,
                (chat_id, message_id, sender_id, sender_name, truncated_text, int(is_outgoing), int(is_automated and is_outgoing)),
            )
            if is_automated:
                conn.execute("UPDATE reply_feedback SET reply_text=? WHERE chat_id=? AND message_id=?", (truncated_text, chat_id, message_id))
            # Lightweight automatic pruning: keep a deep-enough history per chat for
            # the 40-message group prompt window (with room to spare), cap the rest
            conn.execute(
                """
                DELETE FROM chat_messages
                WHERE chat_id = ? AND id NOT IN (
                    SELECT id FROM chat_messages
                    WHERE chat_id = ?
                    ORDER BY id DESC
                    LIMIT 60
                )
                """,
                (chat_id, chat_id),
            )

    def has_chat_message(self, chat_id: int, message_id: Optional[int]) -> bool:
        """Whether a message (chat_id, message_id) is already cached — used to avoid
        overwriting automation-recorded outgoing messages with generic event data."""
        if not message_id:
            return False
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM chat_messages WHERE chat_id = ? AND message_id = ? LIMIT 1",
                (chat_id, message_id),
            ).fetchone()
        return bool(row)

    def set_reply_feedback(self, chat_id: int, message_id: int, rating: str, actor_id=None) -> None:
        if rating not in ("helpful", "unnecessary", "off_topic", "style", "clear") or message_id <= 0:
            raise ValueError("Choose helpful, unnecessary, off_topic, style, or clear for a valid message ID")
        with self._context_lock, self._get_connection() as conn:
            row = conn.execute("SELECT text FROM chat_messages WHERE chat_id=? AND message_id=? AND is_outgoing=1 AND is_automated=1",
                               (chat_id, message_id)).fetchone()
            old = conn.execute("SELECT reply_text FROM reply_feedback WHERE chat_id=? AND message_id=?", (chat_id, message_id)).fetchone()
            if not row and not old:
                raise ValueError("This automated reply is no longer available. Rate a recent reply from the app")
            if rating == "clear":
                conn.execute("DELETE FROM reply_feedback WHERE chat_id=? AND message_id=?", (chat_id, message_id))
            else:
                conn.execute("INSERT INTO reply_feedback(chat_id,message_id,rating,reply_text,actor_id) VALUES(?,?,?,?,?) "
                             "ON CONFLICT(chat_id,message_id) DO UPDATE SET rating=excluded.rating,reply_text=excluded.reply_text,actor_id=excluded.actor_id,updated_at=strftime('%Y-%m-%d %H:%M:%f','now')",
                             (chat_id, message_id, rating, (row["text"] if row else old["reply_text"])[:300], actor_id))
                conn.execute("DELETE FROM reply_feedback WHERE rowid NOT IN (SELECT rowid FROM reply_feedback ORDER BY updated_at DESC,rowid DESC LIMIT 500)")
            conn.execute("INSERT INTO runtime_state(key,value) VALUES('state_revision',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(time.time_ns()),))

    def list_reply_feedback(self, chat_ids, limit=40) -> List[Dict[str, Any]]:
        ids = tuple(chat_ids)
        if not ids:
            return []
        with self._get_connection() as conn:
            rows = conn.execute("SELECT f.*,COALESCE(k.title,'') AS chat_title FROM reply_feedback f LEFT JOIN known_chats k ON k.chat_id=f.chat_id WHERE f.chat_id IN (" + ",".join("?" for _ in ids) + ") ORDER BY f.updated_at DESC,f.rowid DESC LIMIT ?",
                                (*ids, max(1, min(500, limit)))).fetchall()
            return [dict(row) for row in rows]

    def latest_incoming_row_id(self, chat_id: int) -> int:
        with self._get_connection() as conn:
            return int(conn.execute("SELECT COALESCE(MAX(id),0) FROM chat_messages WHERE chat_id=? AND is_outgoing=0", (chat_id,)).fetchone()[0])

    def record_token_usage(
        self, provider: str, model: str, prompt_tokens: int, completion_tokens: int, total_tokens: int
    ) -> None:
        """Record tokens consumed by an AI generation call."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO token_usage (provider, model, prompt_tokens, completion_tokens, total_tokens)
                VALUES (?, ?, ?, ?, ?)
                """,
                (provider, model, max(0, prompt_tokens), max(0, completion_tokens), max(0, total_tokens)),
            )

    def get_token_usage_stats(self) -> Dict[str, Any]:
        """Aggregate total token usage and per-model stats."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT 
                    COUNT(*) as request_count,
                    COALESCE(SUM(prompt_tokens), 0) as total_prompt,
                    COALESCE(SUM(completion_tokens), 0) as total_completion,
                    COALESCE(SUM(total_tokens), 0) as total_tokens
                FROM token_usage
                """
            ).fetchone()
            by_model = conn.execute(
                """
                SELECT model, COUNT(*) as calls, SUM(total_tokens) as tokens
                FROM token_usage
                GROUP BY model
                ORDER BY tokens DESC
                """
            ).fetchall()
            return {
                "request_count": int(row["request_count"]) if row else 0,
                "total_prompt": int(row["total_prompt"]) if row else 0,
                "total_completion": int(row["total_completion"]) if row else 0,
                "total_tokens": int(row["total_tokens"]) if row else 0,
                "by_model": [dict(r) for r in by_model],
            }

    def get_daily_token_usage(self) -> int:
        """Get total tokens consumed across all models in the last 24 hours."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(total_tokens), 0) as daily_total
                FROM token_usage
                WHERE created_at >= datetime('now', '-24 hours')
                """
            ).fetchone()
            return int(row["daily_total"]) if row else 0

    def get_recent_chat_messages(
        self, chat_id: int, limit: int = 5, max_age_seconds: Optional[int] = None
    ) -> List[Dict[str, str]]:
        """Retrieve recent conversation context for chat_id in chronological order.
        
        If max_age_seconds is specified, messages older than the threshold are ignored (context aging).
        """
        with self._get_connection() as conn:
            if max_age_seconds and max_age_seconds > 0:
                modifier = f"-{int(max_age_seconds)} seconds"
                rows = conn.execute(
                    """
                    SELECT sender_name, text, is_outgoing
                    FROM chat_messages
                    WHERE chat_id = ? AND created_at >= datetime('now', ?)
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (chat_id, modifier, max(1, limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT sender_name, text, is_outgoing
                    FROM chat_messages
                    WHERE chat_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (chat_id, max(1, limit)),
                ).fetchall()

            # Reverse to chronological order (oldest to newest)
            results = []
            for r in reversed(rows):
                sender = "You" if r["is_outgoing"] == 1 else (r["sender_name"] or "Contact")
                results.append({
                    "sender": sender,
                    "text": r["text"],
                    "is_outgoing": bool(r["is_outgoing"]),
                })
            return results

    def get_recent_message_count(self, window_seconds: float, chat_id: Optional[int] = None) -> int:
        """Count cached chat messages within the last window_seconds (chat busy-signal)."""
        with self._get_connection() as conn:
            modifier = f"-{int(window_seconds)} seconds"
            if chat_id is None:
                row = conn.execute(
                    "SELECT COUNT(*) FROM chat_messages WHERE created_at >= datetime('now', ?)",
                    (modifier,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) FROM chat_messages WHERE chat_id = ? AND created_at >= datetime('now', ?)",
                    (chat_id, modifier),
                ).fetchone()
            return int(row[0]) if row else 0

    def latest_chat_message_row_id(self, chat_id: int) -> int:
        """Highest row id of cached messages for chat_id (summary marker)."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(id), 0) FROM chat_messages WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            return int(row[0]) if row else 0

    def count_chat_messages_since(self, chat_id: int, since_row_id: int) -> int:
        """Count cached messages for chat_id with row id greater than since_row_id."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM chat_messages WHERE chat_id = ? AND id > ?",
                (chat_id, since_row_id),
            ).fetchone()
            return int(row[0]) if row else 0

    def get_chat_messages_since_text(self, chat_id: int, since_row_id: int, limit: int = 40) -> str:
        """Chronological 'Sender: text' lines for cached messages after since_row_id (summary payload)."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT sender_name, text, is_outgoing
                FROM chat_messages
                WHERE chat_id = ? AND id > ? AND text != ''
                ORDER BY id DESC
                LIMIT ?
                """,
                (chat_id, since_row_id, max(1, limit)),
            ).fetchall()
        lines = []
        for r in reversed(rows):
            sender = "You" if r["is_outgoing"] == 1 else (r["sender_name"] or "Contact")
            lines.append(f"{sender}: {r['text']}")
        return "\n".join(lines)

    def get_chat_summary(self, chat_id: int) -> str:
        """AI-generated rolling recap for chat_id (runtime_state keyed storage with disk fallback)."""
        summary = self.get_state(f"chat_summary_{chat_id}", "")
        if summary:
            return summary
        if self.get_state(f"chat_memory_epoch_{chat_id}"):
            return ""
        # Fallback to isolated context file on disk
        file_path = self._get_context_file_path(chat_id)
        if file_path.exists():
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                memory = data.get("ai_memory") or ""
                if memory:
                    return memory if self.set_chat_summary(chat_id, memory, epoch="") else ""
            except Exception:
                pass
        return ""

    def get_chat_prompt(self, chat_id: int) -> str:
        """Get per-chat custom AI persona (from runtime_state with disk context file fallback)."""
        prompt = self.get_state(f"chat_prompt_{chat_id}", "")
        if prompt:
            return prompt
        file_path = self._get_context_file_path(chat_id)
        if file_path.exists():
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                p = data.get("prompt") or ""
                if p:
                    self.set_state(f"chat_prompt_{chat_id}", p)
                    return p
            except Exception:
                pass
        return ""

    def count_chat_messages(self, chat_id: int) -> int:
        """Total cached messages for chat_id."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM chat_messages WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            return int(row[0]) if row else 0

    def set_chat_summary(self, chat_id: int, summary: str, *, epoch: Optional[str] = None, marker: Optional[int] = None) -> bool:
        """Store the AI-generated rolling recap for chat_id and sync to isolated context file."""
        with self._context_lock:
            if epoch is not None and self.get_state(f"chat_memory_epoch_{chat_id}") != epoch:
                return False
            if marker is not None and int(self.get_state(f"chat_summary_marker_{chat_id}", "0")) > marker:
                return False
            self.set_state(f"chat_summary_{chat_id}", (summary or "").strip())
            if marker is not None:
                self.set_state(f"chat_summary_marker_{chat_id}", str(marker))
            self.sync_chat_context_file(chat_id)
            return True

    def prune_messages_older_than(self, max_age_seconds: float) -> int:
        """Delete locally cached chat messages older than max_age_seconds (context aging purge).

        Only removes local SQLite prompt-memory rows; never touches Telegram messages.
        """
        with self._get_connection() as conn:
            modifier = f"-{int(max_age_seconds)} seconds"
            cursor = conn.execute(
                "DELETE FROM chat_messages WHERE created_at < datetime('now', ?)",
                (modifier,),
            )
            return cursor.rowcount

    def clear_chat_context(self, chat_id: int) -> int:
        """Clear locally cached conversation context for chat_id.
        
        CRITICAL SAFETY: This ONLY clears local SQLite context cache used for AI prompts;
        it NEVER deletes any Telegram messages on Telegram servers.
        """
        with self._context_lock:
            with self._get_connection() as conn:
                count = conn.execute("DELETE FROM chat_messages WHERE chat_id = ?", (chat_id,)).rowcount
                conn.execute("DELETE FROM reply_feedback WHERE chat_id = ?", (chat_id,))
                conn.executemany(
                    "INSERT INTO runtime_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    [(f"chat_summary_{chat_id}", ""), (f"chat_summary_marker_{chat_id}", "0"),
                     (f"chat_memory_epoch_{chat_id}", str(time.time_ns()))],
                )
            self.sync_chat_context_file(chat_id)
            self.set_state("state_revision", str(time.time_ns()))
            return count

    def clear_all_chat_context(self) -> int:
        """Clear locally cached conversation context and summaries across all chats.
        
        CRITICAL SAFETY: This ONLY clears local SQLite context cache used for AI prompts;
        it NEVER deletes any Telegram messages on Telegram servers.
        """
        with self._context_lock:
            with self._get_connection() as conn:
                chats = {r[0] for r in conn.execute(
                    "SELECT chat_id FROM known_chats UNION SELECT chat_id FROM chat_messages UNION SELECT chat_id FROM permanent_chat_context UNION SELECT chat_id FROM reply_feedback"
                )}
                keys = [r[0] for r in conn.execute("SELECT key FROM runtime_state WHERE key LIKE 'chat_summary_%'")]
            chats.update(int(k.rsplit("_", 1)[-1]) for k in keys if k.rsplit("_", 1)[-1].lstrip("-").isdigit())
            chats.update(int(p.stem) for p in self.contexts_dir.glob("*.json") if p.stem.lstrip("-").isdigit())
            return sum(self.clear_chat_context(cid) for cid in chats)

    def prune_chat_messages(self, chat_id: int, keep_last: int = 50) -> None:
        """Prune old cached chat context keeping only the last N messages."""
        with self._get_connection() as conn:
            conn.execute(
                """
                DELETE FROM chat_messages
                WHERE chat_id = ? AND id NOT IN (
                    SELECT id FROM chat_messages
                    WHERE chat_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                )
                """,
                (chat_id, chat_id, keep_last),
            )

    def record_chat_metadata(
        self, chat_id: int, title: str = "", username: str = "", chat_type: str = ""
    ) -> None:
        """Upsert chat title, username, and chat type metadata."""
        title_str = str(title).strip() if isinstance(title, str) else ""
        username_str = str(username).strip().lstrip("@") if isinstance(username, str) else ""
        type_str = str(chat_type) if isinstance(chat_type, str) else ""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO known_chats (chat_id, title, username, chat_type, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(chat_id) DO UPDATE SET
                    title = CASE WHEN excluded.title != '' THEN excluded.title ELSE known_chats.title END,
                    username = CASE WHEN excluded.username != '' THEN excluded.username ELSE known_chats.username END,
                    chat_type = CASE WHEN excluded.chat_type != '' THEN excluded.chat_type ELSE known_chats.chat_type END,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (chat_id, title_str, username_str, type_str),
            )

    def get_chat_metadata(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve stored metadata for a specific chat ID."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT chat_id, title, username, chat_type FROM known_chats WHERE chat_id = ?",
                (chat_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def find_chat_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Retrieve stored metadata matching a username (case-insensitive)."""
        clean = str(username).strip().lstrip("@").lower()
        if not clean:
            return None
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT chat_id, title, username, chat_type FROM known_chats WHERE LOWER(username) = ?",
                (clean,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def _get_context_file_path(self, chat_id: int) -> Path:
        """Physical context file location for an individual chat/group."""
        return self.contexts_dir / f"{chat_id}.json"

    def _sync_context_to_disk(
        self,
        chat_id: int,
        pinned_text: str = "",
        notes: str = "",
    ) -> bool:
        """Write isolated per-group context file named by chat_id so groups never mix context."""
        with self._context_lock:
            try:
                ensure_secure_dir(self.contexts_dir)
                meta = self.get_chat_metadata(chat_id) or {}
                file_path = self._get_context_file_path(chat_id)
                data = {
                    "chat_id": chat_id,
                    "title": meta.get("title") or f"Chat {chat_id}",
                    "chat_type": meta.get("chat_type") or ("Group" if chat_id < 0 else "Private contact"),
                    "notes": notes or "",
                    "pinned_text": pinned_text or "",
                    "ai_memory": self.get_state(f"chat_summary_{chat_id}") or "",
                    "voice_profile": self.get_state(f"chat_voice_profile_{chat_id}") or "",
                    "prompt": self.get_state(f"chat_prompt_{chat_id}") or "",
                    "style": self.get_state(f"chat_style_{chat_id}") or "",
                    "recent_messages": self.get_recent_chat_messages(chat_id, limit=15),
                    "reply_feedback": self.list_reply_feedback([chat_id], limit=5),
                    "updated_at": time.time(),
                }
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.contexts_dir, delete=False) as tmp:
                    tmp.write(json.dumps(data, indent=2))
                try:
                    os.replace(tmp.name, file_path)
                finally:
                    Path(tmp.name).unlink(missing_ok=True)
                return True
            except Exception as e:
                logger.debug(f"Failed to write context file for chat {chat_id} to disk: {e}")
                return False

    def sync_chat_context_file(self, chat_id: int) -> bool:
        """Sync full per-chat context snapshot (persona, notes, pins) to its isolated disk file."""
        ctx = self.get_permanent_context(chat_id)
        return self._sync_context_to_disk(chat_id, pinned_text=ctx.get("pinned_text", ""), notes=ctx.get("notes", ""))

    def set_permanent_context(
        self,
        chat_id: int,
        pinned_text: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> None:
        """Store or update permanent context for a chat (never removed by context aging or TTL)."""
        with self._get_connection() as conn:
            existing = conn.execute(
                "SELECT pinned_text, notes FROM permanent_chat_context WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()

            if existing:
                new_pinned = pinned_text if pinned_text is not None else existing["pinned_text"]
                new_notes = notes if notes is not None else existing["notes"]
                conn.execute(
                    """
                    UPDATE permanent_chat_context
                    SET pinned_text = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE chat_id = ?
                    """,
                    (new_pinned, new_notes, chat_id),
                )
            else:
                new_pinned = pinned_text or ""
                new_notes = notes or ""
                conn.execute(
                    """
                    INSERT INTO permanent_chat_context (chat_id, pinned_text, notes)
                    VALUES (?, ?, ?)
                    """,
                    (chat_id, new_pinned, new_notes),
                )

        self._sync_context_to_disk(chat_id, new_pinned, new_notes)

    def get_permanent_context(self, chat_id: int) -> Dict[str, str]:
        """Retrieve permanent context (pinned message + custom notes) for chat_id."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT pinned_text, notes FROM permanent_chat_context WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            if row:
                pinned = row["pinned_text"] or ""
                notes = row["notes"] or ""
                file_path = self._get_context_file_path(chat_id)
                if not file_path.exists():
                    self._sync_context_to_disk(chat_id, pinned, notes)
                return {"pinned_text": pinned, "notes": notes}

        # Fallback to isolated context file on disk if present
        file_path = self._get_context_file_path(chat_id)
        if file_path.exists():
            try:
                content = json.loads(file_path.read_text(encoding="utf-8"))
                pinned = content.get("pinned_text") or ""
                notes = content.get("notes") or ""
                if pinned or notes:
                    with self._get_connection() as conn:
                        conn.execute(
                            "INSERT OR REPLACE INTO permanent_chat_context (chat_id, pinned_text, notes) VALUES (?, ?, ?)",
                            (chat_id, pinned, notes),
                        )
                    return {"pinned_text": pinned, "notes": notes}
            except Exception as e:
                logger.debug(f"Could not read context file {file_path}: {e}")

        return {"pinned_text": "", "notes": ""}

    def delete_permanent_context(self, chat_id: int) -> bool:
        """Explicitly remove permanent context for a chat upon owner request."""
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM permanent_chat_context WHERE chat_id = ?", (chat_id,))
            deleted = cursor.rowcount > 0

        file_path = self._get_context_file_path(chat_id)
        if file_path.exists():
            try:
                file_path.unlink()
                deleted = True
            except Exception as e:
                logger.debug(f"Could not remove context file {file_path}: {e}")

        return deleted

