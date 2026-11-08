"""I-004 A1：上传管道 —— 成功 / 去重 / 失败三分支 + 日期子目录。"""

import tempfile
import unittest
from datetime import date
from pathlib import Path

import support  # noqa: F401  把 src 加入 sys.path

from panup.core.errors import UploadError
from panup.core.ledger import Ledger
from panup.core.pipeline import date_subdir, publish_file


class FakeDriver:
    """按脚本行动的假驱动：记录调用，upload/share 可注入结果或异常。"""

    name = "fake"

    def __init__(self, *, upload_error=None, share_error=None):
        self.calls = []
        self.upload_error = upload_error
        self.share_error = share_error

    def auth_check(self):
        self.calls.append("auth_check")
        return {"ok": True}

    def mkdir(self, remote_dir):
        self.calls.append(("mkdir", remote_dir))
        return {"path": remote_dir, "created": True}

    def upload(self, local_path, remote_dir, *, overwrite=True, on_progress=None):
        self.calls.append(("upload", remote_dir))
        if self.upload_error:
            raise self.upload_error
        name = Path(local_path).name
        return {"path": f"{remote_dir.rstrip('/')}/{name}", "size": 5, "rapid": False}

    def share(self, remote_path, *, pwd=None, period_days=0):
        self.calls.append(("share", remote_path, period_days))
        if self.share_error:
            raise self.share_error
        return {"link": "https://e/s/1", "pwd": pwd or "ab12", "path": remote_path}

    def list(self, remote_dir):
        return []


def make(tmp, driver):
    return publish_file, Ledger(Path(tmp) / "ledger.db"), driver


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.src = Path(self.tmp) / "a.txt"
        self.src.write_text("hello", encoding="utf-8")
        self.driver = FakeDriver()
        self.ledger = Ledger(Path(self.tmp) / "ledger.db")

    def tearDown(self):
        self.ledger.close()
        self._tmp.cleanup()

    def test_success_flow_calls_driver_and_records(self):
        r = publish_file(str(self.src), "fake", "/分享", ledger=self.ledger,
                         driver=self.driver)
        self.assertFalse(r["dedup"])
        self.assertEqual(r["link"], "https://e/s/1")
        self.assertEqual(r["path"], "/分享/a.txt")
        self.assertEqual(self.driver.calls[0], ("mkdir", "/分享"))
        self.assertEqual(self.driver.calls[2][0], "share")
        row = self.ledger.find_success(local_path=str(self.src.resolve()),
                                       file_hash=r["file_hash"], pan="fake",
                                       remote_path="/分享/a.txt")
        self.assertIsNotNone(row)

    def test_dedup_hit_skips_driver(self):
        publish_file(str(self.src), "fake", "/分享", ledger=self.ledger,
                     driver=self.driver)
        d2 = FakeDriver()
        r2 = publish_file(str(self.src), "fake", "/分享", ledger=self.ledger,
                          driver=d2)
        self.assertTrue(r2["dedup"])
        self.assertEqual(d2.calls, [])

    def test_force_reuploads(self):
        publish_file(str(self.src), "fake", "/分享", ledger=self.ledger,
                     driver=self.driver)
        d2 = FakeDriver()
        r2 = publish_file(str(self.src), "fake", "/分享", ledger=self.ledger,
                          driver=d2, force=True)
        self.assertFalse(r2["dedup"])
        self.assertIn(("mkdir", "/分享"), d2.calls)

    def test_failure_records_error_and_reraises(self):
        bad = FakeDriver(upload_error=UploadError("OSS 直传失败"))
        with self.assertRaises(UploadError):
            publish_file(str(self.src), "fake", "/分享", ledger=self.ledger,
                         driver=bad)
        rows = self.ledger.recent()
        self.assertEqual(rows[0]["status"], "failed")
        self.assertTrue(rows[0]["error_code"])

    def test_missing_local_file(self):
        with self.assertRaises(UploadError):
            publish_file(str(Path(self.tmp) / "nope.txt"), "fake", "/分享",
                         ledger=self.ledger, driver=FakeDriver())

    def test_date_dir_appends_year_month_day(self):
        self.assertEqual(date_subdir("/分享", date(2026, 11, 9)), "/分享/26/11/09")
        self.assertEqual(date_subdir("/", date(2026, 1, 2)), "/26/01/02")

    def test_date_dir_flag_uses_today(self):
        import panup.core.pipeline as pipeline
        orig = pipeline._today
        pipeline._today = lambda: date(2026, 11, 9)
        try:
            publish_file(str(self.src), "fake", "/分享", ledger=self.ledger,
                         driver=self.driver, date_dir=True)
        finally:
            pipeline._today = orig
        self.assertEqual(self.driver.calls[0], ("mkdir", "/分享/26/11/09"))

    def test_share_period_days_passthrough(self):
        publish_file(str(self.src), "fake", "/分享", ledger=self.ledger,
                     driver=self.driver, period_days=7)
        self.assertEqual(self.driver.calls[2][2], 7)

    def test_unregistered_writer_raises(self):
        with self.assertRaises(Exception):
            publish_file(str(self.src), "fake", "/分享", ledger=self.ledger,
                         driver=FakeDriver(), writer_names=["nope"])


if __name__ == "__main__":
    unittest.main()
