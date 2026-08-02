from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


class PersistentCache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS cache (
            namespace TEXT NOT NULL, cache_key TEXT NOT NULL, version INTEGER NOT NULL,
            value_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(namespace, cache_key, version))"""
        )
        self.connection.commit()
        self.lock = threading.RLock()

    @staticmethod
    def key(value: Any) -> str:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def get(self, namespace: str, value: Any, version: int = 1) -> Any | None:
        key = self.key(value)
        with self.lock:
            row = self.connection.execute(
                "SELECT value_json FROM cache WHERE namespace=? AND cache_key=? AND version=?",
                (namespace, key, version),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, namespace: str, key_value: Any, value: Any, version: int = 1) -> None:
        key = self.key(key_value)
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        with self.lock:
            self.connection.execute(
                """INSERT OR REPLACE INTO cache(namespace, cache_key, version, value_json)
                VALUES (?, ?, ?, ?)""",
                (namespace, key, version, encoded),
            )
            self.connection.commit()
