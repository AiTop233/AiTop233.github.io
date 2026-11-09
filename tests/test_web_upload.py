"""I-008 A1：上传 / 记录 / 重传接口契约（multipart → pipeline 打桩）。
I-019：上传改「后台任务 + 进度轮询」后，表单与 job 契约的验证也在这里。

只验 Web 层契约与信封：不真连网盘、不真写文档。管道行为由 test_task /
test_pipeline 覆盖，这里断言「表单怎么变成 publish_task 的参数」。
"""

import json
import tempfile
import threading
import time
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


class _PacedRunner(_Recorder):
    """跑到「上传中」就停住，等测试看过进度再放行（验中间态真的可见）。"""

    def __init__(self, release: threading.Event, **kw):
        super().__init__(**kw)
        self.release = release
        self.reached = threading.Event()

    def __call__(self, path, targets, **kw):
        progress = kw.get("progress")
        if progress:
            progress({"stage": "scanning", "kind": "file", "title": "主题名",
                      "file_count": 1, "size": 11, "pans": ["baidu"]})
            progress({"stage": "uploading", "pan": "baidu", "file_index": 1,
                      "file": "原名.txt", "bytes_done": 5, "bytes_total": 11})
        self.reached.set()
        self.release.wait(5)
        return super().__call__(path, targets, **kw)


def _poll(client, job_id, pred, tries=200):
    """轮询任务直到 pred(快照) 成立；超时返回最后一次快照（由断言兜底）。"""
    body = {}
    for _ in range(tries):
        body = client.get(f"/api/jobs/{job_id}").json()
        if pred(body):
            return body
        time.sleep(0.02)
    return body


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
                "title": "主题名", "date_dir": "0", "doc": "", "sync": "1"}
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
                                      {"pan": "quark", "dir": "/d"}]),
                  "sync": "1"},
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
                        data={"pans": json.dumps([{"pan": "baidu", "dir": "/d"}]),
                              "sync": "1"},
                        files={"file": ("../../evil.txt", b"x", "text/plain")})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(Path(self.runner.calls[0]["path"]).name, "evil.txt")

    # ---- I-019：默认走后台任务，进度可轮询 ----

    def _post_async(self, client, **over):
        data = {"pans": json.dumps([{"pan": "baidu", "dir": "/来自电脑"}]),
                "title": "主题名", "date_dir": "0", "doc": "feishu"}
        data.update(over)
        files = {"file": ("原名.txt", b"hello panup", "text/plain")}
        return client.post("/api/upload", data=data, files=files)

    def test_upload_returns_job_and_exposes_progress(self):
        release = threading.Event()
        runner = _PacedRunner(release)
        client = TestClient(self._app(runner))

        r = self._post_async(client)
        self.assertEqual(r.status_code, 202, r.text)
        job_id = r.json()["job_id"]
        self.assertTrue(job_id.startswith("j-"))

        # 跑在上传中：能看见「哪个盘、第几个文件、传了多少字节、飞书还没写」
        mid = _poll(client, job_id, lambda j: j["pans"]["baidu"]["stage"] == "uploading")
        self.assertEqual(mid["status"], "running")
        self.assertEqual(mid["pans"]["baidu"]["bytes_done"], 5)
        self.assertEqual(mid["pans"]["baidu"]["file_index"], 1)
        self.assertEqual(mid["writer"]["stage"], "pending")
        self.assertEqual(mid["stage"], "uploading")

        release.set()
        done = _poll(client, job_id, lambda j: j["status"] != "running")
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["stage"], "finished")
        self.assertEqual(done["result"]["items"][0]["link"],
                         "https://pan.baidu.com/s/x")
        self.assertTrue(any(s["pan"] == "baidu" for s in done["steps"]))
        self.assertNotIn("key", done["steps"][0])

    def test_upload_job_failure_is_reported_in_job(self):
        def boom(path, targets, **kw):
            from panup.core.errors import UploadError

            raise UploadError("同名文件夹已存在", code="PAN-name-conflict",
                              hint="换个标题")
        client = TestClient(self._app(boom))
        r = self._post_async(client)
        self.assertEqual(r.status_code, 202)
        done = _poll(client, r.json()["job_id"], lambda j: j["status"] != "running")
        self.assertEqual(done["status"], "failed")
        self.assertEqual(done["error"]["code"], "PAN-name-conflict")
        self.assertIn("换个标题", done["error"]["hint"])

    def test_unknown_job_is_404_envelope(self):
        r = TestClient(self._app()).get("/api/jobs/j-nope")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["code"], "PUP-404")

    def test_options_returns_configured_default_dirs(self):
        r = TestClient(self._app()).get("/api/options")
        self.assertEqual(r.status_code, 200, r.text)
        pans = {p["name"]: p["default_dir"] for p in r.json()["pans"]}
        self.assertEqual(pans["baidu"], "/百度默认")
        self.assertEqual(pans["quark"], "/夸克默认")


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
