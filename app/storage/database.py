"""Lightweight SQLite database for pending approvals and state deduplication."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.session_manager import ensure_secure_dir, ensure_secure_file


class Database:
    """Thread-safe SQLite storage for pending approvals and deduplication."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        ensure_secure_dir(db_path.parent)
        self._init_db()
        ensure_secure_file(self.db_path)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;

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

                CREATE TABLE IF NOT EXISTS reply_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    timestamp REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reply_events_timestamp ON reply_events(timestamp);

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    sender_id INTEGER,
                    sender_name TEXT,
                    text TEXT NOT NULL,
                    is_outgoing INTEGER NOT NULL DEFAULT 0,
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

                CREATE TABLE IF NOT EXISTS permanent_chat_context (
                    chat_id INTEGER PRIMARY KEY,
                    pinned_text TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

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
            return int(cursor.lastrowid)

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

    def update_approval_status(self, approval_id: int, status: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE pending_approvals SET status = ? WHERE id = ?",
                (status, approval_id),
            )
            return cursor.rowcount > 0

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

    def get_state(self, key: str, default: str = "") -> str:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM runtime_state WHERE key = ?",
                (key,),
            ).fetchone()
            return str(row["value"]) if row else default

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
    ) -> None:
        """Cache message in database with automatic size and row capping to keep resource usage minimal."""
        if not text or not text.strip():
            return
        # Cap stored message length to 300 chars to avoid memory/disk bloat
        truncated_text = text.strip()[:300]
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO chat_messages (chat_id, message_id, sender_id, sender_name, text, is_outgoing)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, message_id) DO UPDATE SET
                    text = excluded.text,
                    sender_name = excluded.sender_name
                """,
                (chat_id, message_id, sender_id, sender_name, truncated_text, 1 if is_outgoing else 0),
            )
            # Lightweight automatic pruning: cap at 20 messages per chat
            conn.execute(
                """
                DELETE FROM chat_messages
                WHERE chat_id = ? AND id NOT IN (
                    SELECT id FROM chat_messages
                    WHERE chat_id = ?
                    ORDER BY id DESC
                    LIMIT 20
                )
                """,
                (chat_id, chat_id),
            )

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
                results.append({"sender": sender, "text": r["text"]})
            return results

    def clear_chat_context(self, chat_id: int) -> int:
        """Clear locally cached conversation context for chat_id.
        
        CRITICAL SAFETY: This ONLY clears local SQLite context cache used for AI prompts;
        it NEVER deletes any Telegram messages on Telegram servers.
        """
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM chat_messages WHERE chat_id = ?", (chat_id,))
            return cursor.rowcount

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
                conn.execute(
                    """
                    INSERT INTO permanent_chat_context (chat_id, pinned_text, notes)
                    VALUES (?, ?, ?)
                    """,
                    (chat_id, pinned_text or "", notes or ""),
                )

    def get_permanent_context(self, chat_id: int) -> Dict[str, str]:
        """Retrieve permanent context (pinned message + custom notes) for chat_id."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT pinned_text, notes FROM permanent_chat_context WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            if row:
                return {"pinned_text": row["pinned_text"] or "", "notes": row["notes"] or ""}
            return {"pinned_text": "", "notes": ""}

    def delete_permanent_context(self, chat_id: int) -> bool:
        """Explicitly remove permanent context for a chat upon owner request."""
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM permanent_chat_context WHERE chat_id = ?", (chat_id,))
            return cursor.rowcount > 0

