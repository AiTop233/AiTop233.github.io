"""I-004 A1（部分）：台账 —— 幂等键唯一、状态流转、最近记录查询。"""

import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  把 src 加入 sys.path

from panup.core.ledger import Ledger

KEY = dict(local_path="D:/x/a.txt", file_hash="h1", pan="quark",
           remote_path="/分享/26/11/09/a.txt")


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(Path(self._tmp.name) / "ledger.db")

    def tearDown(self):
        self.ledger.close()
        self._tmp.cleanup()

    def test_start_success_find_roundtrip(self):
        rid = self.ledger.record_start(size=10, **KEY)
        self.ledger.record_success(rid, link="https://e/s/1", pwd="ab12")
        row = self.ledger.find_success(**KEY)
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "success")
        self.assertEqual(row["link"], "https://e/s/1")
        self.assertEqual(row["pwd"], "ab12")

    def test_record_start_reuses_same_key_row(self):
        rid1 = self.ledger.record_start(size=10, **KEY)
        rid2 = self.ledger.record_start(size=10, **KEY)
        self.assertEqual(rid1, rid2)
        self.assertEqual(self.ledger.recent()[0]["status"], "pending")

    def test_find_success_returns_none_when_absent_or_failed(self):
        self.assertIsNone(self.ledger.find_success(**KEY))
        rid = self.ledger.record_start(size=10, **KEY)
        self.ledger.record_failed(rid, "PAN-quark-oss")
        self.assertIsNone(self.ledger.find_success(**KEY))
        self.assertEqual(self.ledger.recent()[0]["error_code"], "PAN-quark-oss")

    def test_recent_orders_newest_first_and_respects_limit(self):
        for i in range(3):
            k = dict(KEY, remote_path=f"/x/{i}.txt")
            rid = self.ledger.record_start(size=i, **k)
            self.ledger.record_success(rid, f"https://e/{i}", "")
        rows = self.ledger.recent(limit=2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["remote_path"], "/x/2.txt")

    def test_success_overrides_previous_failure_same_key(self):
        rid = self.ledger.record_start(size=10, **KEY)
        self.ledger.record_failed(rid, "PAN-baidu-net")
        rid2 = self.ledger.record_start(size=10, **KEY)
        self.ledger.record_success(rid2, "https://e/ok", "")
        self.assertIsNotNone(self.ledger.find_success(**KEY))


if __name__ == "__main__":
    unittest.main()
