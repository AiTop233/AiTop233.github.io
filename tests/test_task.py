"""I-015 A1：上传任务层契约（多盘聚合 / 部分失败 / 只写一次文档 / 台账 group_id）。

多盘语义（D-004）：一个文件可同时传多个网盘，各盘独立成败，全部跑完后只写一节
文档，节内只含成功的盘。单盘场景由 publish_file 走同一套单盘步骤。
"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  把 src 加入 sys.path

import panup.drivers  # noqa: F401  触发真实驱动注册（盘名须已注册）
from panup.core.errors import ShareError, UploadError
from panup.core.ledger import Ledger
from panup.core.pipeline import publish_task
from panup.writers.base import WRITERS, Writer


class FakeDriver:
    """假驱动：按盘返回不同链接；error 注入后 upload 阶段即失败。"""

    def __init__(self, pan, *, error=None):
        self.name = pan
        self.error = error
        self.calls = []

    def auth_check(self):
        return {"ok": True}

    def mkdir(self, remote_dir):
        self.calls.append(("mkdir", remote_dir))
        return {"path": remote_dir}

    def upload(self, local_path, remote_dir, *, overwrite=True, on_progress=None):
        self.calls.append(("upload", remote_dir))
        if self.error:
            raise self.error
        name = Path(local_path).name
        return {"path": f"{remote_dir.rstrip('/')}/{name}", "size": 5,
                "rapid": False}

    def share(self, remote_path, *, pwd=None, period_days=0):
        if self.error:
            raise self.error
        return {"link": f"https://e/{self.name}/s/1", "pwd": "ab12",
                "path": remote_path}

    def list(self, remote_dir):
        return []


class ByteDriver(FakeDriver):
    """会回调字节进度的假驱动（真驱动的 on_progress 形状）。"""

    def upload(self, local_path, remote_dir, *, overwrite=True, on_progress=None):
        if on_progress:
            on_progress(3, 5)
        return super().upload(local_path, remote_dir, overwrite=overwrite)


class RecordingWriter(Writer):
    """记录收到的 task，供断言「只写一节、只含成功盘」。"""

    name = "stub-rec"
    instances: list["RecordingWriter"] = []

    def __init__(self):
        RecordingWriter.instances.append(self)
        self.tasks = []

    def auth_check(self):
        return {"ok": True}

    def append_task(self, task):
        self.tasks.append(task)
        return {"blocks": len(task["items"]) + 1}


class TaskTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.src = Path(self.tmp) / "报告 v3.pdf"
        self.src.write_text("x", encoding="utf-8")
        self.ledger = Ledger(Path(self.tmp) / "ledger.db")
        self.drivers: dict[str, FakeDriver] = {}
        WRITERS["stub-rec"] = RecordingWriter
        RecordingWriter.instances.clear()

    def tearDown(self):
        self.ledger.close()
        WRITERS.pop("stub-rec", None)
        self._tmp.cleanup()

    def factory(self, pan):
        if pan not in self.drivers:
            self.drivers[pan] = FakeDriver(pan)
        return self.drivers[pan]

    def run_task(self, targets, **kw):
        return publish_task(str(self.src), targets, ledger=self.ledger,
                            driver_factory=self.factory,
                            writer_names=["stub-rec"], **kw)

    def test_two_pans_write_one_section(self):
        r = self.run_task([{"pan": "baidu", "remote_dir": "/A"},
                           {"pan": "quark", "remote_dir": "/B"}])
        self.assertEqual(len(r["items"]), 2)
        self.assertEqual(r["failed"], [])
        self.assertEqual(len(RecordingWriter.instances), 1)
        self.assertEqual(len(RecordingWriter.instances[0].tasks), 1)
        task = RecordingWriter.instances[0].tasks[0]
        self.assertEqual([i["pan"] for i in task["items"]], ["baidu", "quark"])
        self.assertEqual(task["items"][0]["pwd"], "ab12")

    def test_partial_failure_writes_only_success(self):
        self.drivers["quark"] = FakeDriver("quark", error=ShareError("额度不足"))
        r = self.run_task([{"pan": "baidu", "remote_dir": "/A"},
                           {"pan": "quark", "remote_dir": "/B"}])
        self.assertEqual([i["pan"] for i in r["items"]], ["baidu"])
        self.assertEqual([f["pan"] for f in r["failed"]], ["quark"])
        self.assertIn("额度不足", r["failed"][0]["msg"])
        task = RecordingWriter.instances[0].tasks[0]
        self.assertEqual([i["pan"] for i in task["items"]], ["baidu"])

    def test_all_failed_skips_writer(self):
        self.drivers["baidu"] = FakeDriver("baidu", error=ShareError("no"))
        r = self.run_task([{"pan": "baidu", "remote_dir": "/A"}])
        self.assertEqual(r["items"], [])
        self.assertEqual(len(r["failed"]), 1)
        self.assertEqual(RecordingWriter.instances, [])

    def test_title_defaults_to_filename_without_ext(self):
        self.run_task([{"pan": "baidu", "remote_dir": "/A"}])
        self.assertEqual(RecordingWriter.instances[0].tasks[0]["title"], "报告 v3")

    def test_title_override(self):
        self.run_task([{"pan": "baidu", "remote_dir": "/A"}], title="自定义主题")
        self.assertEqual(RecordingWriter.instances[0].tasks[0]["title"], "自定义主题")

    def test_group_id_shared_across_pans(self):
        r = self.run_task([{"pan": "baidu", "remote_dir": "/A"},
                           {"pan": "quark", "remote_dir": "/B"}])
        rows = self.ledger.recent(10)
        self.assertEqual({row["group_id"] for row in rows}, {r["group_id"]})

    def test_all_dedup_skips_writer(self):
        targets = [{"pan": "baidu", "remote_dir": "/A"},
                   {"pan": "quark", "remote_dir": "/B"}]
        self.run_task(targets)
        RecordingWriter.instances.clear()
        r = self.run_task(targets)
        self.assertTrue(all(i["dedup"] for i in r["items"]))
        self.assertEqual(RecordingWriter.instances, [])

    def test_partial_dedup_writes_only_fresh_pan(self):
        self.run_task([{"pan": "baidu", "remote_dir": "/A"}])
        RecordingWriter.instances.clear()
        self.run_task([{"pan": "baidu", "remote_dir": "/A"},
                       {"pan": "quark", "remote_dir": "/B"}])
        task = RecordingWriter.instances[0].tasks[0]
        self.assertEqual([i["pan"] for i in task["items"]], ["quark"])

    def test_rejects_duplicate_pan(self):
        with self.assertRaises(UploadError):
            self.run_task([{"pan": "baidu", "remote_dir": "/A"},
                           {"pan": "baidu", "remote_dir": "/B"}])

    def test_rejects_unknown_pan(self):
        with self.assertRaises(UploadError):
            self.run_task([{"pan": "nope", "remote_dir": "/A"}])

    def test_rejects_empty_targets(self):
        with self.assertRaises(UploadError):
            self.run_task([])

    # ---- I-019：结构化进度事件 ----

    def test_progress_stream_covers_scan_upload_share_and_writer(self):
        events = []
        self.run_task([{"pan": "baidu", "remote_dir": "/A"},
                       {"pan": "quark", "remote_dir": "/B"}],
                      progress=events.append)
        stages = [e["stage"] for e in events]
        self.assertEqual(stages[0], "scanning")
        self.assertEqual(stages[-1], "finished")
        for stage in ("checking", "mkdir", "uploading", "sharing", "done",
                      "writing"):
            self.assertIn(stage, stages)
        scan = events[0]
        self.assertEqual(scan["pans"], ["baidu", "quark"])
        self.assertEqual(scan["file_count"], 1)
        self.assertEqual(scan["kind"], "file")
        self.assertTrue(all(e["pan"] in ("baidu", "quark")
                            for e in events
                            if e["stage"] in ("checking", "done") and e.get("pan")))

    def test_progress_reports_bytes_against_whole_resource(self):
        self.src.write_text("hello", encoding="utf-8")
        self.drivers["baidu"] = ByteDriver("baidu")
        events = []
        self.run_task([{"pan": "baidu", "remote_dir": "/A"}],
                      progress=events.append)
        ups = [e for e in events if e["stage"] == "uploading"]
        self.assertTrue(any(e["bytes_done"] == 3 and e["bytes_total"] == 5
                            for e in ups), ups)
        self.assertTrue(all("file_index" in e for e in ups))

    def test_progress_callback_error_does_not_break_upload(self):
        def boom(event):
            raise RuntimeError("前端断线")

        r = self.run_task([{"pan": "baidu", "remote_dir": "/A"}], progress=boom)
        self.assertEqual(len(r["items"]), 1)
        self.assertEqual(r["failed"], [])

    def test_dedup_emits_skipped_instead_of_uploading(self):
        targets = [{"pan": "baidu", "remote_dir": "/A"}]
        self.run_task(targets)
        events = []
        self.run_task(targets, progress=events.append)
        self.assertIn("skipped", [e["stage"] for e in events])
        self.assertNotIn("uploading", [e["stage"] for e in events])

    def test_failed_pan_emits_failure_with_reason(self):
        self.drivers["baidu"] = FakeDriver("baidu", error=ShareError("额度不足"))
        events = []
        self.run_task([{"pan": "baidu", "remote_dir": "/A"}],
                      progress=events.append)
        fail = [e for e in events if e["stage"] == "failed"][0]
        self.assertEqual(fail["pan"], "baidu")
        self.assertIn("额度不足", fail["msg"])


class LedgerMigrationTests(unittest.TestCase):
    """旧库（无 group_id / title）打开后补列并回填，不丢数据。"""

    def test_old_db_gets_columns_backfilled(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "old.db"
            conn = sqlite3.connect(db)
            conn.execute(
                "CREATE TABLE uploads (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "local_path TEXT NOT NULL, file_hash TEXT NOT NULL, size INTEGER, "
                "pan TEXT NOT NULL, remote_path TEXT NOT NULL, link TEXT, pwd TEXT, "
                "status TEXT NOT NULL, error_code TEXT, created_at TEXT NOT NULL, "
                "updated_at TEXT NOT NULL, "
                "UNIQUE(local_path, file_hash, pan, remote_path))")
            conn.execute(
                "INSERT INTO uploads (local_path, file_hash, size, pan, "
                "remote_path, status, created_at, updated_at) VALUES "
                "('x', 'h', 1, 'baidu', '/x', 'success', 't', 't')")
            conn.commit()
            conn.close()

            led = Ledger(db)
            try:
                row = led.recent(1)[0]
                self.assertEqual(row["group_id"], "legacy-1")
                self.assertIsNone(row["title"])
            finally:
                led.close()


if __name__ == "__main__":
    unittest.main()
