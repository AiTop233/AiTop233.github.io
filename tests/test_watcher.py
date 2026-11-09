"""I-006 A1/A5：监控循环 —— 稳定判定、去重、重试、连续失败熔停、单实例锁。"""

import tempfile
import time
import unittest
from pathlib import Path

import support  # noqa: F401  把 src 加入 sys.path

import panup.core.pipeline as pipeline
from panup.core.errors import ProjectError, UploadError
from panup.core.ledger import Ledger
from panup.watcher import Watcher, build_rules, load_lock


class FakeDriver:
    name = "fake"

    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = []

    def auth_check(self):
        return {"ok": True}

    def mkdir(self, remote_dir):
        self.calls.append(("mkdir", remote_dir))
        return {"path": remote_dir, "created": True}

    def upload(self, local_path, remote_dir, *, overwrite=True, on_progress=None):
        self.calls.append(("upload", Path(local_path).name))
        if self.fail:
            raise UploadError("模拟失败", code="PAN-fake-up")
        return {"path": f"{remote_dir.rstrip('/')}/{Path(local_path).name}",
                "size": 3, "rapid": False}

    def share(self, remote_path, *, pwd=None, period_days=0):
        self.calls.append(("share", remote_path))
        return {"link": "https://e/s/x", "pwd": "ab12", "path": remote_path}

    def list(self, remote_dir):
        return []


def make_rules(root, **kw):
    return [{"local": str(root), "pan": "fake", "remote_dir": "/同步",
             "date_dir": False, "doc": []}]


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ledger = Ledger(self.root / "ledger.db")
        self.rules = make_rules(self.root / "drop")
        (self.root / "drop").mkdir()

    def tearDown(self):
        self.ledger.close()
        load_lock(self.root).release()
        self._tmp.cleanup()

    def _watcher(self, driver=None, **kw):
        defaults = dict(ledger=self.ledger, driver_factory=lambda pan: driver,
                        interval=0.05, stable=0.15,
                        backoff=(0.02, 0.02, 0.02),
                        lock_dir=self.root, log=lambda *a, **k: None)
        defaults.update(kw)
        return Watcher(self.rules, **defaults)

    def test_stable_file_gets_uploaded(self):
        d = FakeDriver()
        w = self._watcher(driver=d)
        (self.root / "drop" / "a.txt").write_text("x", encoding="utf-8")
        w.run_cycle()  # 刚出现，未稳定 → 不上传
        self.assertNotIn("upload", [c[0] for c in d.calls])
        time.sleep(0.2)
        w.run_cycle()  # 大小稳定 → 上传
        self.assertIn(("share", "/同步/a"), d.calls)
        row = self.ledger.recent()[0]
        self.assertEqual(row["status"], "success")

    def test_growing_file_waits_for_stability(self):
        d = FakeDriver()
        w = self._watcher(driver=d)
        f = self.root / "drop" / "a.txt"
        f.write_text("x", encoding="utf-8")
        w.run_cycle()
        time.sleep(0.2)
        f.write_text("xxxx", encoding="utf-8")  # 变大 → 重新计时
        w.run_cycle()
        self.assertNotIn("upload", [c[0] for c in d.calls])
        time.sleep(0.2)
        w.run_cycle()
        self.assertIn("upload", [c[0] for c in d.calls])

    def test_restart_dedup_no_reupload(self):
        d = FakeDriver()
        w = self._watcher(driver=d)
        f = self.root / "drop" / "a.txt"
        f.write_text("x", encoding="utf-8")
        time.sleep(0.2)
        w.run_cycle()
        w.run_cycle()  # 同一会话内：processed 集合挡住
        d2 = FakeDriver()
        w2 = self._watcher(driver=d2)
        w2.run_cycle()  # 重启后：台账去重挡住
        self.assertNotIn("upload", [c[0] for c in d2.calls])

    def test_retry_then_failed_recorded(self):
        d = FakeDriver(fail=True)
        w = self._watcher(driver=d, retry_limit=2)
        f = self.root / "drop" / "bad.txt"
        f.write_text("x", encoding="utf-8")
        w.run_cycle()  # 登记新文件
        time.sleep(0.2)
        w.run_cycle()  # 稳定 → 上传并重试
        self.assertEqual(d.calls.count(("upload", "bad.txt")), 3)  # 1 + 2 次重试
        row = self.ledger.recent()[0]
        self.assertEqual(row["status"], "failed")
        self.assertEqual(w.consecutive_failed, 1)

    def test_consecutive_failures_stop_the_loop(self):
        d = FakeDriver(fail=True)
        w = self._watcher(driver=d, retry_limit=0)
        for i in range(5):
            (self.root / "drop" / f"bad{i}.txt").write_text("x", encoding="utf-8")
        time.sleep(0.2)
        reason = w.run_forever(max_cycles=10)
        self.assertEqual(reason, "consecutive_failed")
        self.assertGreaterEqual(w.consecutive_failed, 5)

    def test_lock_prevents_second_instance(self):
        d = FakeDriver()
        w = self._watcher(driver=d)
        lock = load_lock(self.root)
        lock.acquire()
        try:
            with self.assertRaises(ProjectError):
                w.run_forever(max_cycles=1)
        finally:
            lock.release()

    def test_date_dir_per_mapping(self):
        orig = pipeline._today
        import datetime as dt
        pipeline._today = lambda: dt.date(2026, 11, 9)
        try:
            d = FakeDriver()
            w = self._watcher(driver=d)
            self.rules[0]["date_dir"] = True
            (self.root / "drop" / "d.txt").write_text("x", encoding="utf-8")
            w.run_cycle()  # 登记新文件
            time.sleep(0.2)
            w.run_cycle()  # 稳定 → 上传
        finally:
            pipeline._today = orig
        self.assertIn(("mkdir", "/同步/26/11/09"), d.calls)


class BuildRulesTests(unittest.TestCase):
    def test_missing_fields_listed_all_at_once(self):
        with self.assertRaises(ProjectError) as cm:
            build_rules([{"local": "D:/x"}])
        self.assertIn("pan", str(cm.exception))
        self.assertIn("remote_dir", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
