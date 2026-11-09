"""目录监控 —— 标准库轮询（间隔可配），新文件稳定后自动上传并记录（PRD F2）。

稳定判定：文件大小在 stable 秒内不变才算写完（写入中的文件等它写完）。
去重：内存 processed 集合 + 台账幂等键（重启后由台账挡住，AC-07）。
重试：单文件失败退避重试 retry_limit 次；连续 MAX_CONSECUTIVE_FAILED 个文件
重试耗尽 → 停止循环并醒目提示（BACKEND.md §5）。
单实例：data/watch.lock 独占创建，防双开重复上传。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from panup.core.errors import ConfigError, ProjectError
from panup.core.ledger import Ledger
from panup.core.pipeline import publish_file
from panup.core.log import JsonLogger

DEFAULT_INTERVAL = 5.0
DEFAULT_STABLE = 10.0
DEFAULT_RETRY_LIMIT = 3
DEFAULT_BACKOFF = (5, 15, 60)
MAX_CONSECUTIVE_FAILED = 5


class WatchLock:
    """单实例文件锁：独占创建 watch.lock，release 时删除。"""

    def __init__(self, lock_dir):
        self.path = Path(lock_dir) / "watch.lock"
        self._fd = None

    def acquire(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self._fd, str(os.getpid()).encode())
        except FileExistsError:
            self._fd = None
            raise ProjectError(
                f"已有监控实例在运行（{self.path} 存在）",
                hint="确认没有另一个 panup watch 在跑；若是残留锁文件，手动删除后再启动",
            ) from None

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            os.unlink(self.path)
        except OSError:
            # 文件可能仍被其他句柄占用（Windows）；下次 acquire 时会再次拦截
            pass


def load_lock(lock_dir) -> WatchLock:
    """按目录取单实例锁（同一目录同一把锁）。"""
    return WatchLock(lock_dir)


def build_rules(dirs_cfg) -> list[dict]:
    """校验 [watch].dirs 配置；缺字段一次性列全（AC-06 的配置面）。"""
    rules = []
    for i, raw in enumerate(dirs_cfg or [], 1):
        missing = [k for k in ("local", "pan", "remote_dir") if not raw.get(k)]
        if missing:
            raise ConfigError(
                f"[watch].dirs 第 {i} 项缺少必填字段: {'、'.join(missing)}",
                code="PUP-107",
                hint="每项需要 local（本地目录）、pan（baidu/quark）、remote_dir（网盘目录）",
            )
        rules.append({
            "local": str(Path(raw["local"]).resolve()),
            "pan": raw["pan"],
            "remote_dir": raw["remote_dir"],
            # 人的归档习惯（年/月/日）作监控默认；要平铺可在映射里写 date_dir = false
            "date_dir": raw.get("date_dir", True),
            "doc": list(raw.get("doc") or ["feishu"]),
        })
    return rules


class Watcher:
    def __init__(self, rules, *, ledger: Ledger, driver_factory=None,
                 interval: float = DEFAULT_INTERVAL, stable: float = DEFAULT_STABLE,
                 retry_limit: int = DEFAULT_RETRY_LIMIT,
                 backoff=DEFAULT_BACKOFF, lock_dir=None, log=None):
        self.rules = rules
        self.ledger = ledger
        self._driver_factory = driver_factory or (lambda pan: None)
        self._drivers: dict[str, object] = {}
        self.interval = float(interval)
        self.stable = float(stable)
        self.retry_limit = int(retry_limit)
        self.backoff = tuple(backoff)
        self._lock = WatchLock(lock_dir) if lock_dir else None
        # 兼容两种传入：JsonLogger 实例（取 .log 方法）或可调用对象
        if log is None:
            self._log = lambda *a, **k: None
        elif hasattr(log, "log") and callable(log.log):
            self._log = log.log
        else:
            self._log = log
        self._pending: dict[str, tuple[int, float]] = {}
        self._processed: set[str] = set()
        self.consecutive_failed = 0

    def _driver_for(self, pan: str):
        if pan not in self._drivers:
            self._drivers[pan] = self._driver_factory(pan)
        return self._drivers[pan]

    def _iter_files(self):
        """遍历各监控目录（递归），产出 (文件路径, 所属规则)。"""
        for rule in self.rules:
            root = Path(rule["local"])
            if not root.is_dir():
                continue
            for f in root.rglob("*"):
                if f.is_file():
                    yield f, rule

    def _collect_stable(self) -> list[tuple[Path, dict]]:
        """扫描并返回「已稳定待上传」的文件；写入中的文件留在 pending。"""
        now = time.time()
        seen = set()
        eligible = []
        for f, rule in self._iter_files():
            p = str(f)
            seen.add(p)
            size = f.stat().st_size
            first = self._pending.get(p)
            if first is None or first[0] != size:
                self._pending[p] = (size, now)
                continue
            if size > 0 and now - first[1] >= self.stable and p not in self._processed:
                eligible.append((f, rule))
                self._processed.add(p)  # 领走任务，本轮起不再重复收集
        gone = set(self._pending) - seen
        for p in gone:
            self._pending.pop(p, None)
        return eligible

    def _upload_with_retry(self, path: Path, rule: dict):
        for attempt in range(self.retry_limit + 1):
            try:
                result = publish_file(
                    str(path), rule["pan"], rule["remote_dir"],
                    ledger=self.ledger, driver=self._driver_for(rule["pan"]),
                    date_dir=rule.get("date_dir", False),
                    writer_names=rule.get("doc") or [],
                    log=self._log,
                )
                self.consecutive_failed = 0
                self._log("watch.upload_done", pan=rule["pan"],
                          file=str(path), dedup=result.get("dedup", False))
                return result
            except ProjectError as e:
                if attempt < self.retry_limit:
                    delay = self.backoff[min(attempt, len(self.backoff) - 1)]
                    self._log("watch.retry", pan=rule["pan"], file=str(path),
                              code=e.code, msg=str(e), delay=delay)
                    time.sleep(delay)
        self.consecutive_failed += 1
        self._log("watch.give_up", pan=rule["pan"], file=str(path),
                  msg=f"重试 {self.retry_limit} 次耗尽")
        return None

    def run_cycle(self) -> list[dict]:
        """一轮扫描 + 上传；测试与运行循环共用。"""
        results = []
        for f, rule in self._collect_stable():
            r = self._upload_with_retry(f, rule)
            if r is not None:
                results.append(r)
        return results

    def run_forever(self, *, max_cycles: int | None = None) -> str:
        """主循环；返回停止原因（max_cycles / consecutive_failed / KeyboardInterrupt 由调用方处理）。"""
        if self._lock is not None:
            self._lock.acquire()
        try:
            cycles = 0
            while True:
                self.run_cycle()
                if self.consecutive_failed >= MAX_CONSECUTIVE_FAILED:
                    print(f"⚠ 连续 {self.consecutive_failed} 个文件上传失败，"
                          f"监控已停止。请检查登录态（python -m panup check）与网络，"
                          f"处理后重新启动 watch；失败记录见台账 status。")
                    self._log("watch.stopped", msg="consecutive_failed")
                    return "consecutive_failed"
                if max_cycles is not None and cycles + 1 >= max_cycles:
                    return "max_cycles"
                cycles += 1
                time.sleep(self.interval)
        finally:
            if self._lock is not None:
                self._lock.release()
