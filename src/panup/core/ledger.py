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
    group_id TEXT,
    title TEXT,
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
        self._migrate()

    def _migrate(self) -> None:
        """存量库补列（BACKEND §11）：旧库没有 group_id / title 时 ALTER 补上。

        旧行 group_id 回填 `legacy-<id>`（一次上传一行的旧语义），title 留空由
        记录页回退显示文件名；不重建表、不丢数据。
        """
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(uploads)")}
        if "group_id" not in cols:
            self._conn.execute("ALTER TABLE uploads ADD COLUMN group_id TEXT")
            self._conn.execute(
                "UPDATE uploads SET group_id = 'legacy-' || id "
                "WHERE group_id IS NULL OR group_id = ''")
        if "title" not in cols:
            self._conn.execute("ALTER TABLE uploads ADD COLUMN title TEXT")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_uploads_group ON uploads(group_id)")
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
                     pan: str, remote_path: str, group_id: str = "",
                     title: str = "") -> int:
        """记一条 pending；同键已有记录则复用该行（不违反唯一索引）。"""
        now = self._now()
        try:
            cur = self._conn.execute(
                "INSERT INTO uploads (group_id, title, local_path, file_hash, "
                "size, pan, remote_path, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                (group_id or f"legacy-{now}", title, local_path, file_hash,
                 size, pan, remote_path, now, now))
            self._conn.commit()
            return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            self._conn.execute(
                "UPDATE uploads SET status='pending', error_code=NULL, "
                "group_id=?, title=?, updated_at=? WHERE local_path=? AND "
                "file_hash=? AND pan=? AND remote_path=?",
                (group_id or "", title, now, local_path, file_hash, pan,
                 remote_path))
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

    def recent(self, limit: int = 10, status: str | None = None) -> list[dict]:
        """按 id 倒序取记录；status 给定时只取该状态（failed 即「待修」）。"""
        if status:
            cur = self._conn.execute(
                "SELECT * FROM uploads WHERE status=? ORDER BY id DESC LIMIT ?",
                (status, limit))
        else:
            cur = self._conn.execute(
                "SELECT * FROM uploads ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]

    def get(self, record_id: int):
        """按主键取单条记录；不存在返回 None（重传接口用）。"""
        cur = self._conn.execute("SELECT * FROM uploads WHERE id=?",
                                 (record_id,))
        return self._one(cur)

    def tasks(self, limit: int = 50) -> list[dict]:
        """按 group_id 聚合最近的任务（记录页主视图，BACKEND §2）。

        一次上传的各盘行共享 group_id，聚合后每项含 items（按盘）与整体状态：
        success（全成功）/ partial（有成有败）/ failed（全失败）/ pending。
        旧库单行任务（legacy-<id>）同样适用，item 只有一条。
        """
        cur = self._conn.execute(
            "SELECT group_id, MAX(id) AS last_id FROM uploads "
            "GROUP BY group_id ORDER BY last_id DESC LIMIT ?", (limit,))
        groups = [r["group_id"] for r in cur.fetchall()]
        if not groups:
            return []
        marks = ",".join("?" * len(groups))
        rows = self._conn.execute(
            f"SELECT * FROM uploads WHERE group_id IN ({marks}) ORDER BY id",
            groups).fetchall()
        buckets: dict = {g: [] for g in groups}
        for r in rows:
            buckets.setdefault(r["group_id"], []).append(dict(r))
        return [_as_task(g, buckets.get(g) or []) for g in groups]


def _as_task(group_id: str, items: list[dict]) -> dict:
    """把同一 group_id 的记录行合成一条任务视图。"""
    first = items[0]
    statuses = {i["status"] for i in items}
    if statuses == {"success"}:
        status = "success"
    elif statuses == {"failed"}:
        status = "failed"
    elif "pending" in statuses:
        status = "pending"
    else:
        status = "partial"
    return {
        "group_id": group_id,
        "title": items[0].get("title") or Path(first["local_path"]).stem,
        "filename": Path(first["local_path"]).name,
        "local_path": first["local_path"],
        "size": first.get("size"),
        "created_at": min(i["created_at"] for i in items),
        "updated_at": max(i["updated_at"] for i in items),
        "status": status,
        "items": items,
    }
