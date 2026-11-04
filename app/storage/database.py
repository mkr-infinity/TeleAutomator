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
