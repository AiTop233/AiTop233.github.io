"""上传台账 —— SQLite 单文件（data/ledger.db），BACKEND.md §3。

幂等键 = (local_path, file_hash, pan, remote_path)，唯一索引支撑 AC-07 去重；
status: pending → success / failed。时间戳本地时区 ISO 8601。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_path TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    size INTEGER,
    pan TEXT NOT NULL,
    remote_path TEXT NOT NULL,
    link TEXT,
    pwd TEXT,
    status TEXT NOT NULL,
    error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(local_path, file_hash, pan, remote_path)
)
"""


class Ledger:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def close(self) -> None:
        """释放 SQLite 连接（Windows 下不关会让临时目录清理失败）。"""
        self._conn.close()

    def _one(self, cur):
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def find_success(self, *, local_path: str, file_hash: str, pan: str,
                     remote_path: str):
        """按幂等键查成功记录；没有或只有失败记录时返回 None。"""
        cur = self._conn.execute(
            "SELECT * FROM uploads WHERE local_path=? AND file_hash=? AND pan=? "
            "AND remote_path=? AND status='success'",
            (local_path, file_hash, pan, remote_path))
        return self._one(cur)

    def record_start(self, *, local_path: str, file_hash: str, size: int,
                     pan: str, remote_path: str) -> int:
        """记一条 pending；同键已有记录则复用该行（不违反唯一索引）。"""
        now = self._now()
        try:
            cur = self._conn.execute(
                "INSERT INTO uploads (local_path, file_hash, size, pan, "
                "remote_path, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
                (local_path, file_hash, size, pan, remote_path, now, now))
            self._conn.commit()
            return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            self._conn.execute(
                "UPDATE uploads SET status='pending', error_code=NULL, "
                "updated_at=? WHERE local_path=? AND file_hash=? AND pan=? "
                "AND remote_path=?",
                (now, local_path, file_hash, pan, remote_path))
            self._conn.commit()
            cur = self._conn.execute(
                "SELECT id FROM uploads WHERE local_path=? AND file_hash=? "
                "AND pan=? AND remote_path=?",
                (local_path, file_hash, pan, remote_path))
            return int(cur.fetchone()[0])

    def record_success(self, record_id: int, link: str, pwd: str = "") -> None:
        self._conn.execute(
            "UPDATE uploads SET status='success', link=?, pwd=?, error_code=NULL, "
            "updated_at=? WHERE id=?",
            (link, pwd, self._now(), record_id))
        self._conn.commit()

    def record_failed(self, record_id: int, error_code: str) -> None:
        self._conn.execute(
            "UPDATE uploads SET status='failed', error_code=?, updated_at=? "
            "WHERE id=?", (error_code, self._now(), record_id))
        self._conn.commit()

    def recent(self, limit: int = 10) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM uploads ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]
