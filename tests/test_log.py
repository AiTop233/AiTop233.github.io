"""I-001 A3：JSON lines 日志 —— 字段契约、按天文件名、保留期清理。"""

import json
import os
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

import support  # noqa: F401  把 src 加入 sys.path

from panup.core.log import JsonLogger


class JsonLogTests(unittest.TestCase):
    def test_line_has_required_fields_and_extra(self):
        with tempfile.TemporaryDirectory() as d:
            JsonLogger(d).log("upload.success", pan="quark", file="a.pdf", code="PUP-000")
            files = list(Path(d).glob("panup-*.log"))
            self.assertEqual(len(files), 1)
            rec = json.loads(files[0].read_text(encoding="utf-8").strip())
            self.assertEqual(rec["event"], "upload.success")
            self.assertEqual(rec["level"], "info")
            self.assertEqual(rec["pan"], "quark")
            self.assertEqual(rec["file"], "a.pdf")
            self.assertIn("ts", rec)

    def test_ts_is_iso8601_with_local_timezone(self):
        with tempfile.TemporaryDirectory() as d:
            JsonLogger(d).log("watch.file_detected")
            rec = json.loads(
                next(Path(d).glob("panup-*.log")).read_text(encoding="utf-8").strip()
            )
            parsed = datetime.fromisoformat(rec["ts"])
            self.assertIsNotNone(parsed.tzinfo)

    def test_retention_deletes_old_log_files_only(self):
        with tempfile.TemporaryDirectory() as d:
            old = Path(d) / "panup-20260101.log"
            old.write_text("{}\n", encoding="utf-8")
            past = time.time() - 40 * 86400
            os.utime(old, (past, past))
            keep = Path(d) / "panup-20261101.log"
            keep.write_text("{}\n", encoding="utf-8")
            JsonLogger(d, retention_days=30)
            self.assertFalse(old.exists())
            self.assertTrue(keep.exists())


if __name__ == "__main__":
    unittest.main()
