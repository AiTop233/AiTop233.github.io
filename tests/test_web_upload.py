"""I-008 A1：上传 / 记录 / 重传接口契约（multipart → pipeline 打桩）。

只验 Web 层契约与信封：不真连网盘、不真写文档。管道行为由 test_task /
test_pipeline 覆盖，这里断言「表单怎么变成 publish_task 的参数」。
"""

import json
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  把 src 加入 sys.path

from fastapi.testclient import TestClient

from panup.core.ledger import Ledger
from panup.web.api import create_app

CFG = {"pan": {"baidu_default_dir": "/百度默认", "quark_default_dir": "/夸克默认"}}


class _Recorder:
    """假的 publish_task：记录调用参数并返回可预期的结果。"""

    def __init__(self, items=None, failed=None):
        self.calls = []
        self.items = items if items is not None else [
            {"pan": "baidu", "link": "https://pan.baidu.com/s/x", "pwd": "abcd",
             "path": "/来自电脑/a.txt", "dedup": False}]
        self.failed = failed or []

    def __call__(self, path, targets, **kw):
        self.calls.append({"path": path, "targets": targets, **kw})
        return {"group_id": kw.get("group_id") or "g-test",
                "title": kw.get("title") or "a",
                "items": self.items, "failed": self.failed, "writers": []}


class WebUploadTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = self.root / "ledger.db"
        self.inbox = self.root / "inbox"
        self.runner = _Recorder()

    def tearDown(self):
        self._tmp.cleanup()

    def _app(self, runner=None):
        return create_app(
            status_provider=lambda: {},
            task_runner=runner or self.runner,
            ledger_factory=lambda: Ledger(self.db),
            config_loader=lambda: CFG,
            inbox_dir=str(self.inbox),
        )

    def _post(self, **over):
        data = {"pans": json.dumps([{"pan": "baidu", "dir": "/来自电脑"}]),
                "title": "主题名", "date_dir": "0", "doc": ""}
        data.update(over)
        files = {"file": ("原名.txt", b"hello panup", "text/plain")}
        return TestClient(self._app()).post("/api/upload", data=data, files=files)

    def test_upload_passes_form_to_pipeline(self):
        r = self._post(pans=json.dumps(
            [{"pan": "baidu", "dir": "/来自电脑"},
             {"pan": "quark", "dir": "/来自电脑"}]))
        self.assertEqual(r.status_code, 200, r.text)
        call = self.runner.calls[0]
        self.assertEqual([t["pan"] for t in call["targets"]], ["baidu", "quark"])
        self.assertEqual(call["targets"][0]["remote_dir"], "/来自电脑")
        self.assertEqual(call["title"], "主题名")
        self.assertFalse(call["date_dir"])
        self.assertEqual(call["writer_names"], [])
        self.assertEqual(r.json()["items"][0]["link"], "https://pan.baidu.com/s/x")

    def test_upload_keeps_original_filename_in_persistent_inbox(self):
        r = self._post()
        self.assertEqual(r.status_code, 200, r.text)
        saved = Path(self.runner.calls[0]["path"])
        self.assertTrue(saved.is_file())
        self.assertEqual(saved.name, "原名.txt")
        self.assertEqual(saved.read_bytes(), b"hello panup")
        # 落在 inbox 下（不是系统临时目录），失败记录才能重传
        self.assertTrue(str(saved).startswith(str(self.inbox)))

    def test_upload_blank_dir_falls_back_to_config_default(self):
        self._post(pans=json.dumps([{"pan": "baidu", "dir": ""}]))
        self.assertEqual(self.runner.calls[0]["targets"][0]["remote_dir"],
                         "/百度默认")

    def test_upload_blank_dir_without_default_is_error(self):
        client = TestClient(create_app(
            status_provider=lambda: {}, task_runner=self.runner,
            ledger_factory=lambda: Ledger(self.db),
            config_loader=lambda: {"pan": {}}, inbox_dir=str(self.inbox)))
        r = client.post("/api/upload",
                        data={"pans": json.dumps([{"pan": "baidu", "dir": ""}])},
                        files={"file": ("a.txt", b"x", "text/plain")})
        self.assertGreaterEqual(r.status_code, 500)
        self.assertEqual(r.json()["code"], "PUP-104")
        self.assertTrue(r.json()["hint"])

    def test_upload_title_and_date_flag(self):
        self._post(title="  ", date_dir="1", doc="feishu")
        call = self.runner.calls[0]
        self.assertIsNone(call["title"])          # 空标题交给管道回退文件名
        self.assertTrue(call["date_dir"])
        self.assertEqual(call["writer_names"], ["feishu"])

    def test_upload_reports_per_pan_failure_in_body(self):
        runner = _Recorder(items=[{"pan": "baidu", "link": "l", "pwd": ""}],
                           failed=[{"pan": "quark", "code": "PAN-quark-noauth",
                                    "msg": "缺少夸克登录态 cookie",
                                    "hint": "重新导出 quark cookie"}])
        r = TestClient(self._app(runner)).post(
            "/api/upload",
            data={"pans": json.dumps([{"pan": "baidu", "dir": "/d"},
                                      {"pan": "quark", "dir": "/d"}])},
            files={"file": ("a.txt", b"x", "text/plain")})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["failed"][0]["code"], "PAN-quark-noauth")

    def test_upload_rejects_bad_pans(self):
        for raw in ("", "not json", "[]", '{"pan":"baidu"}'):
            r = self._post(pans=raw)
            self.assertEqual(r.status_code, 400, raw)
            self.assertTrue(r.json()["hint"], raw)

    def test_upload_rejects_unknown_writer(self):
        r = self._post(doc="notion")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "PUP-403")

    def test_upload_without_file_is_400_envelope(self):
        r = TestClient(self._app()).post(
            "/api/upload", data={"pans": json.dumps([{"pan": "baidu"}])})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "PUP-400")

    def test_path_like_filename_is_flattened(self):
        client = TestClient(self._app())
        r = client.post("/api/upload",
                        data={"pans": json.dumps([{"pan": "baidu", "dir": "/d"}])},
                        files={"file": ("../../evil.txt", b"x", "text/plain")})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(Path(self.runner.calls[0]["path"]).name, "evil.txt")


class RecordsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = self.root / "ledger.db"
        self.src = self.root / "src.bin"
        self.src.write_bytes(b"x")
        self._seed()

    def tearDown(self):
        self._tmp.cleanup()

    def _seed(self):
        led = Ledger(self.db)
        try:
            ok = led.record_start(local_path=str(self.src), file_hash="h1",
                                  size=1, pan="baidu", remote_path="/d/a.txt",
                                  group_id="g-1", title="主题一")
            led.record_success(ok, "https://pan.baidu.com/s/ok", "pwd1")
            bad = led.record_start(local_path=str(self.src), file_hash="h1",
                                   size=1, pan="quark", remote_path="/d/a.txt",
                                   group_id="g-1", title="主题一")
            led.record_failed(bad, "PAN-quark-noauth")
            self.bad_id = bad
        finally:
            led.close()

    def _client(self, runner=None):
        return TestClient(create_app(
            status_provider=lambda: {}, task_runner=runner or _Recorder(),
            ledger_factory=lambda: Ledger(self.db),
            config_loader=lambda: CFG, inbox_dir=str(self.root / "inbox")))

    def test_list_groups_by_task(self):
        r = self._client().get("/api/uploads")
        self.assertEqual(r.status_code, 200)
        tasks = r.json()["tasks"]
        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertEqual(task["group_id"], "g-1")
        self.assertEqual(task["title"], "主题一")
        self.assertEqual(task["status"], "partial")
        self.assertEqual([i["pan"] for i in task["items"]], ["baidu", "quark"])

    def test_list_failed_returns_flat_records(self):
        r = self._client().get("/api/uploads?status=failed")
        records = r.json()["records"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["pan"], "quark")
        self.assertEqual(records[0]["error_code"], "PAN-quark-noauth")

    def test_retry_reruns_single_pan_in_same_task(self):
        runner = _Recorder(items=[{"pan": "quark", "link": "https://quark/s/z",
                                   "pwd": "pp"}])
        r = self._client(runner).post(f"/api/uploads/{self.bad_id}/retry")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["ok"])
        call = runner.calls[0]
        self.assertEqual(call["targets"], [{"pan": "quark", "remote_dir": "/d"}])
        self.assertTrue(call["force"])
        self.assertEqual(call["writer_names"], [])       # 不重复写飞书小节
        self.assertEqual(call["group_id"], "g-1")        # 记录归位原任务
        self.assertEqual(call["title"], "主题一")

    def test_retry_unknown_record_is_404(self):
        r = self._client().post("/api/uploads/9999/retry")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["code"], "PUP-404")

    def test_retry_success_record_is_skipped(self):
        led = Ledger(self.db)
        try:
            ok_id = [r for r in led.recent(10) if r["status"] == "success"][0]["id"]
        finally:
            led.close()
        r = self._client().post(f"/api/uploads/{ok_id}/retry")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["skipped"])

    def test_retry_missing_file_is_409(self):
        self.src.unlink()
        r = self._client().post(f"/api/uploads/{self.bad_id}/retry")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["code"], "PUP-409")

    def test_retry_failure_returns_reason(self):
        runner = _Recorder(items=[], failed=[
            {"pan": "quark", "code": "PAN-quark-noauth",
             "msg": "缺少夸克登录态 cookie", "hint": "重新导出"}])
        r = self._client(runner).post(f"/api/uploads/{self.bad_id}/retry")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["ok"])
        self.assertEqual(r.json()["failed"][0]["code"], "PAN-quark-noauth")


if __name__ == "__main__":
    unittest.main()
