"""SQLite persistence layer for auth tokens, profile, API cache, and notification snapshots."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class BotStorage:
    """Thread-safe SQLite storage shared across adapters and NptuRequester."""

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path or os.getenv("NPTU_DB_PATH", "data/nptu_bot.sqlite3"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._lock, self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_state (
                    source TEXT NOT NULL,
                    student_id TEXT NOT NULL,
                    access_token TEXT NOT NULL DEFAULT '',
                    refresh_token TEXT NOT NULL DEFAULT '',
                    profile_json TEXT NOT NULL DEFAULT '{}',
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (source, student_id)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS api_cache (
                    cache_key TEXT PRIMARY KEY,
                    saved_at REAL NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS notify_snapshots (
                    snapshot_key TEXT PRIMARY KEY,
                    saved_at REAL NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_settings (
                    setting_key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                )
                """
            )

    # --- Auth & Profile ---
    def load_auth(self, source: str, student_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as con:
            row = con.execute(
                """
                SELECT access_token, refresh_token, profile_json
                FROM auth_state
                WHERE source = ? AND student_id = ?
                """,
                (source, student_id.upper()),
            ).fetchone()
        if not row:
            return None
        try:
            profile = json.loads(row[2]) if row[2] else {}
        except ValueError:
            profile = {}
        return {
            "access_token": row[0],
            "refresh_token": row[1],
            "profile": profile,
        }

    def save_auth(
        self,
        source: str,
        student_id: str,
        access_token: str,
        refresh_token: str,
        profile: dict[str, Any] | None = None,
    ) -> None:
        existing = self.load_auth(source, student_id)
        merged_profile = profile if profile is not None else (existing["profile"] if existing else {})
        with self._lock, self._connect() as con:
            con.execute(
                """
                INSERT OR REPLACE INTO auth_state
                (source, student_id, access_token, refresh_token, profile_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    source,
                    student_id.upper(),
                    access_token,
                    refresh_token,
                    json.dumps(merged_profile, ensure_ascii=False),
                    time.time(),
                ),
            )

    def clear_auth(self, source: str, student_id: str) -> None:
        with self._lock, self._connect() as con:
            con.execute(
                "DELETE FROM auth_state WHERE source = ? AND student_id = ?",
                (source, student_id.upper()),
            )

    # --- API Cache ---
    def cache_get(self, cache_key: str, ttl: int) -> Any | None:
        with self._lock, self._connect() as con:
            row = con.execute(
                "SELECT saved_at, payload_json FROM api_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        if not row:
            return None
        if ttl > 0 and (time.time() - row[0]) > ttl:
            return None
        try:
            return json.loads(row[1])
        except ValueError:
            return None

    def cache_put(self, cache_key: str, payload: Any) -> None:
        with self._lock, self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO api_cache (cache_key, saved_at, payload_json) VALUES (?, ?, ?)",
                (cache_key, time.time(), json.dumps(payload, ensure_ascii=False)),
            )

    def cache_clear_prefix(self, prefix: str) -> None:
        with self._lock, self._connect() as con:
            con.execute("DELETE FROM api_cache WHERE cache_key LIKE ?", (f"{prefix}%",))

    # --- Notification Snapshots ---
    def get_snapshot(self, key: str) -> Any | None:
        with self._lock, self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM notify_snapshots WHERE snapshot_key = ?",
                (key,),
            ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row[0])
        except ValueError:
            return None

    def save_snapshot(self, key: str, payload: Any) -> None:
        with self._lock, self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO notify_snapshots (snapshot_key, saved_at, payload_json) VALUES (?, ?, ?)",
                (key, time.time(), json.dumps(payload, ensure_ascii=False)),
            )

    # --- Bot Settings ---
    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock, self._connect() as con:
            row = con.execute(
                "SELECT value_json FROM bot_settings WHERE setting_key = ?",
                (key,),
            ).fetchone()
        if not row:
            return default
        try:
            return json.loads(row[0])
        except ValueError:
            return default

    def set_setting(self, key: str, value: Any) -> None:
        with self._lock, self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO bot_settings (setting_key, value_json) VALUES (?, ?)",
                (key, json.dumps(value, ensure_ascii=False)),
            )
