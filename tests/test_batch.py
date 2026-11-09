"""I-018 A1：批量上传的契约与并发约束（D-007）。

三块：
- inbox：浏览器相对路径怎么落盘、怎么被分成「资源」，越级路径怎么被清洗；
- 接口：`files` + `paths` 怎么变成多次 `publish_task`，返回的 `{count, resources}`
  怎么对应「每个资源各自一条链接」；
- 并发：全局单并发——两个批次同时提交时，管道里最多只有一个资源在跑。

全部打桩：不连网盘、不写文档、不真跑管道。
"""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

import support  # noqa: F401  把 src 加入 sys.path

from fastapi.testclient import TestClient

from panup.core.errors import UploadError
from panup.core.ledger import Ledger
from panup.web.api import create_app
from panup.web.inbox import clean_rel, group_resources, ingest
from panup.web.jobs import JobStore

CFG = {"pan": {"baidu_default_dir": "/百度默认", "quark_default_dir": "/夸克默认"}}


def _result(title):
    return {"group_id": "g-1", "title": title,
            "items": [{"pan": "baidu", "link": f"https://pan.baidu.com/s/{title}",
                       "pwd": "", "path": f"/d/{title}", "dedup": False}],
            "failed": [], "writers": []}


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, path, targets, **kw):
        self.calls.append({"path": path, "targets": targets, **kw})
        return _result(kw.get("title") or "")


class _SlowRunner(_Recorder):
    """每次调用停 50ms，记录「同时有几个在跑」，用来验全局锁。"""

    def __init__(self):
        super().__init__()
        self.active = 0
        self.peak = 0
        self.lock = threading.Lock()

    def __call__(self, path, targets, **kw):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(0.05)
            return super().__call__(path, targets, **kw)
        finally:
            with self.lock:
                self.active -= 1


def _wait(client, batch_id, tries=400):
    body = {}
    for _ in range(tries):
        body = client.get(f"/api/batches/{batch_id}").json()
        if body.get("status") != "running":
            return body
        time.sleep(0.02)
    return body


class InboxTests(unittest.TestCase):
    def test_clean_rel_drops_traversal_and_illegal_chars(self):
        self.assertEqual(clean_rel("../../evil.txt"), "evil.txt")
        self.assertEqual(clean_rel("剧A/../第1集.mp4"), "剧A/第1集.mp4")
        self.assertEqual(clean_rel("剧A/a:b?.mp4"), "剧A/a_b_.mp4")
        self.assertEqual(clean_rel("", "原名.txt"), "原名.txt")
        self.assertEqual(clean_rel("///"), "upload.bin")

    def test_ingest_keeps_directory_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "batch"
            saved = ingest([("1.mp4", _stream(b"a"), "剧A/1.mp4"),
                            ("2.mp4", _stream(b"bb"), "剧A/sub/2.mp4")], root)
            self.assertEqual([s["rel"] for s in saved],
                             ["剧A/1.mp4", "剧A/sub/2.mp4"])
            self.assertEqual((root / "剧A" / "sub" / "2.mp4").read_bytes(), b"bb")

    def test_duplicate_relative_paths_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "batch"
            saved = ingest([("a.txt", _stream(b"1"), "a.txt"),
                            ("a.txt", _stream(b"2"), "a.txt")], root)
            self.assertEqual([s["rel"] for s in saved], ["a.txt", "a-2.txt"])
            self.assertEqual((root / "a.txt").read_bytes(), b"1")

    def test_folders_become_one_resource_each(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = _save(root, {"剧A/1.mp4": 3, "剧A/sub/2.mp4": 4,
                                 "剧B/3.mp4": 5})
            res = group_resources(saved, root=root)
            self.assertEqual([r["title"] for r in res], ["剧A", "剧B"])
            self.assertEqual([r["kind"] for r in res], ["folder", "folder"])
            self.assertEqual(res[0]["file_count"], 2)   # 含子目录里的文件
            self.assertEqual(res[0]["size"], 7)
            self.assertTrue(Path(res[0]["path"]).is_dir())

    def test_single_loose_file_stays_a_file_resource(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = _save(root, {"原名.txt": 2})
            res = group_resources(saved, root=root)
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["kind"], "file")
            self.assertEqual(res[0]["title"], "原名")
            self.assertTrue(Path(res[0]["path"]).is_file())

    def test_loose_files_are_grouped_into_one_titled_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = _save(root, {"1.mp4": 1, "2.mp4": 1, "3.mp4": 1})
            res = group_resources(saved, root=root, loose_title="今晚八点档")
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["title"], "今晚八点档")
            self.assertEqual(res[0]["kind"], "folder")
            self.assertEqual(res[0]["file_count"], 3)
            box = Path(res[0]["path"])
            self.assertEqual(sorted(p.name for p in box.iterdir()),
                             ["1.mp4", "2.mp4", "3.mp4"])

    def test_loose_group_falls_back_to_first_file_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = _save(root, {"第一集.mp4": 1, "第二集.mp4": 1})
            res = group_resources(saved, root=root)
            self.assertEqual(res[0]["title"], "第一集 等2个")

    def test_order_follows_first_appearance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = _save(root, {"x.mp4": 1, "剧A/1.mp4": 1})
            res = group_resources(saved, root=root)
            self.assertEqual([r["kind"] for r in res], ["file", "folder"])
            self.assertEqual([r["title"] for r in res], ["x", "剧A"])


class UploadBatchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db = self.root / "ledger.db"
        self.inbox = self.root / "inbox"
        self.runner = _Recorder()

    def tearDown(self):
        self._tmp.cleanup()

    def _app(self, runner=None, **kw):
        return create_app(status_provider=lambda: {},
                          task_runner=runner or self.runner,
                          ledger_factory=lambda: Ledger(self.db),
                          config_loader=lambda: CFG,
                          inbox_dir=str(self.inbox), **kw)

    def _post(self, files, paths=None, paths_raw=None, **over):
        data = {"pans": json.dumps([{"pan": "baidu", "dir": "/d"}]),
                "title": "", "date_dir": "0", "doc": "", "sync": "1"}
        data.update(over)
        if paths_raw is not None:
            data["paths"] = paths_raw
        elif paths is not None:
            data["paths"] = json.dumps(paths)
        return TestClient(self._app()).post("/api/upload", data=data, files=files)

    def test_two_folders_become_two_pipeline_calls(self):
        r = self._post([("files", ("1.mp4", b"a", "video/mp4")),
                        ("files", ("2.mp4", b"bb", "video/mp4")),
                        ("files", ("3.mp4", b"ccc", "video/mp4"))],
                       paths=["剧A/1.mp4", "剧A/sub/2.mp4", "剧B/3.mp4"])
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["count"], 2)
        self.assertEqual([c["title"] for c in self.runner.calls], ["剧A", "剧B"])
        # 每个资源带完整目录结构进管道
        a = Path(self.runner.calls[0]["path"])
        self.assertEqual(a.name, "剧A")
        self.assertTrue((a / "sub" / "2.mp4").is_file())
        # 返回里每个资源各自一条链接
        self.assertEqual(len(body["resources"]), 2)
        self.assertNotEqual(body["resources"][0]["items"][0]["link"],
                            body["resources"][1]["items"][0]["link"])

    def test_multi_resource_ignores_form_title(self):
        r = self._post([("files", ("1.mp4", b"a", "video/mp4")),
                        ("files", ("2.mp4", b"b", "video/mp4"))],
                       paths=["剧A/1.mp4", "剧B/2.mp4"], title="一个标题")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([c["title"] for c in self.runner.calls], ["剧A", "剧B"])

    def test_selected_files_use_form_title_as_folder(self):
        r = self._post([("files", ("1.mp4", b"a", "video/mp4")),
                        ("files", ("2.mp4", b"b", "video/mp4"))],
                       paths=["1.mp4", "2.mp4"], title="今晚八点档")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(self.runner.calls[0]["title"], "今晚八点档")
        self.assertEqual(Path(self.runner.calls[0]["path"]).name, "今晚八点档")

    def test_single_file_title_override(self):
        r = self._post([("files", ("a.txt", b"x", "text/plain"))],
                       paths=["a.txt"], title="主题名")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.runner.calls[0]["title"], "主题名")

    def test_paths_must_match_file_count(self):
        r = self._post([("files", ("a.txt", b"x", "text/plain"))],
                       paths=["x/a.txt", "y/b.txt"])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "PUP-411")
        self.assertEqual(self.runner.calls, [])

    def test_paths_must_be_json(self):
        r = self._post([("files", ("a.txt", b"x", "text/plain"))],
                       paths_raw="not-json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "PUP-411")

    def test_missing_paths_falls_back_to_filenames(self):
        r = self._post([("files", ("a.txt", b"x", "text/plain")),
                        ("files", ("b.txt", b"y", "text/plain"))])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(self.runner.calls), 1)   # 两个散文件 → 一个资源
        self.assertEqual(self.runner.calls[0]["title"], "a 等2个")

    # ---- 后台批次与并发 ----

    def test_async_batch_exposes_each_resource(self):
        client = TestClient(self._app())
        r = client.post("/api/upload",
                        data={"pans": json.dumps([{"pan": "baidu", "dir": "/d"}]),
                              "doc": "feishu"},
                        files=[("files", ("1.mp4", b"a", "video/mp4")),
                               ("files", ("2.mp4", b"b", "video/mp4"))])
        self.assertEqual(r.status_code, 202, r.text)
        batch_id = r.json()["batch_id"]
        self.assertTrue(batch_id.startswith("b-"))
        self.assertEqual(r.json()["count"], 1)   # 两个散文件合成一个资源

        done = _wait(client, batch_id)
        self.assertEqual(done["status"], "done")
        self.assertEqual(done["count"], 1)
        self.assertEqual(done["ok"], 1)
        self.assertEqual([res["title"] for res in done["resources"]],
                         ["1 等2个"])
        self.assertEqual(done["resources"][0]["status"], "done")

    def test_one_failed_resource_does_not_stop_the_batch(self):
        class _HalfBroken(_Recorder):
            def __call__(self, path, targets, **kw):
                if Path(path).name == "剧A":
                    raise UploadError("同名文件夹已存在",
                                      code="PAN-name-conflict", hint="换个标题")
                return super().__call__(path, targets, **kw)

        client = TestClient(self._app(_HalfBroken()))
        r = client.post(
            "/api/upload",
            data={"pans": json.dumps([{"pan": "baidu", "dir": "/d"}]),
                  "paths": json.dumps(["剧A/1.mp4", "剧B/2.mp4"])},
            files=[("files", ("1.mp4", b"a", "video/mp4")),
                   ("files", ("2.mp4", b"b", "video/mp4"))])
        self.assertEqual(r.status_code, 202, r.text)
        done = _wait(client, r.json()["batch_id"])
        self.assertEqual(done["failed"], 1)
        self.assertEqual(done["ok"], 1)
        states = {res["title"]: res["status"] for res in done["resources"]}
        self.assertEqual(states, {"剧A": "failed", "剧B": "done"})
        self.assertEqual(done["resources"][0]["error"]["code"],
                         "PAN-name-conflict")

    def test_two_batches_never_run_at_the_same_time(self):
        runner = _SlowRunner()
        client = TestClient(self._app(runner))
        files = [("files", ("a.txt", b"x", "text/plain"))]
        first = client.post("/api/upload",
                            data={"pans": json.dumps([{"pan": "baidu", "dir": "/d"}])},
                            files=files)
        second = client.post("/api/upload",
                             data={"pans": json.dumps([{"pan": "baidu", "dir": "/d"}])},
                             files=[("files", ("b.txt", b"y", "text/plain"))])
        self.assertEqual((first.status_code, second.status_code), (202, 202))
        _wait(client, first.json()["batch_id"])
        _wait(client, second.json()["batch_id"])
        self.assertEqual(runner.peak, 1)

    def test_unknown_batch_is_404_envelope(self):
        r = TestClient(self._app()).get("/api/batches/b-nope")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["code"], "PUP-404")


class JobStoreBatchTests(unittest.TestCase):
    def test_batch_aggregates_status(self):
        store = JobStore()
        batch_id, ids = store.create_batch(
            [{"title": "A", "pans": ["baidu"]}, {"title": "B", "pans": ["baidu"]}],
            writer="feishu")
        store.finish(ids[0], _result("A"))
        self.assertEqual(store.get_batch(batch_id)["status"], "running")
        self.assertEqual(store.get_batch(batch_id)["ok"], 1)
        store.fail(ids[1], "PUP-500", "炸了", "看日志")
        batch = store.get_batch(batch_id)
        self.assertEqual(batch["status"], "done")
        self.assertEqual((batch["ok"], batch["failed"]), (1, 1))

    def test_large_batch_is_not_trimmed_away(self):
        store = JobStore(keep=2)
        batch_id, ids = store.create_batch(
            [{"title": f"R{i}", "pans": ["baidu"]} for i in range(6)])
        self.assertEqual(len(ids), 6)
        self.assertEqual(store.get_batch(batch_id)["count"], 6)

    def test_unknown_batch_is_none(self):
        self.assertIsNone(JobStore().get_batch("b-nope"))


def _stream(data: bytes):
    import io

    return io.BytesIO(data)


def _save(root: Path, files: dict[str, int]) -> list[dict]:
    """按 {相对路径: 大小} 造文件，返回 ingest 同形状的 saved 列表。"""
    saved = []
    for rel, size in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        saved.append({"abs": str(path), "rel": rel, "size": size})
    return saved


if __name__ == "__main__":
    unittest.main()
