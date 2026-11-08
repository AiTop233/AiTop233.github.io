"""JSON lines 日志 —— logs/panup-YYYYMMDD.log，按天滚动，启动时清理过期文件。

字段契约（docs/BACKEND.md §10）：{"ts", "event", "level", **fields}；
ts 为本地时区 ISO 8601。调用方不得把 cookie / secret / 提取码传入 fields（AC-05）。
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

_NAME_RE = re.compile(r"^panup-\d{8}\.log$")


class JsonLogger:
    """写 JSON lines 的小日志器；每次写入按当天日期选文件，实现按天滚动。"""

    def __init__(self, log_dir, *, retention_days=30, echo=False):
        self.dir = Path(log_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        self.echo = echo
        self._cleanup()

    def _file_for(self, day: datetime) -> Path:
        return self.dir / f"panup-{day:%Y%m%d}.log"

    def log(self, event: str, *, level: str = "info", **fields) -> None:
        record = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "event": event,
            "level": level,
        }
        record.update(fields)
        line = json.dumps(record, ensure_ascii=False)
        with open(self._file_for(datetime.now()), "a", encoding="utf-8") as f:
            f.write(line + "\n")
        if self.echo:
            print(line, file=sys.stderr, flush=True)

    def _cleanup(self) -> None:
        """删除超过保留期的 panup-*.log（按文件 mtime）；不碰其他文件。"""
        if self.retention_days <= 0:
            return
        cutoff = time.time() - self.retention_days * 86400
        for f in self.dir.iterdir():
            if _NAME_RE.match(f.name) and f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
