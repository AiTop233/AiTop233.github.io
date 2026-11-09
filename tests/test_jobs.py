"""I-019 A1：上传进度板（JobStore）—— 事件怎么聚成「现在走到哪一步」。

只测内存状态机，不碰 HTTP / 管道：管道发什么事件由 test_task 覆盖，
HTTP 轮询契约由 test_web_upload 覆盖。
"""

import unittest

import support  # noqa: F401  把 src 加入 sys.path

from panup.web.jobs import JobStore


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = JobStore()
        self.job_id = self.store.create(filename="a.mp4", title="今晚",
                                        pans=["baidu", "quark"], size=100,
                                        writer="feishu")

    def get(self):
        return self.store.get(self.job_id)

    def test_new_job_waits_for_scan(self):
        job = self.get()
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["stage"], "queued")
        self.assertEqual(set(job["pans"]), {"baidu", "quark"})
        self.assertEqual(job["pans"]["baidu"]["stage"], "waiting")
        self.assertEqual(job["writer"]["stage"], "pending")

    def test_scan_fills_resource_shape(self):
        self.store.event(self.job_id, {"stage": "scanning", "kind": "folder",
                                       "title": "今晚", "file_count": 4,
                                       "size": 400, "pans": ["baidu", "quark"]})
        job = self.get()
        self.assertEqual(job["kind"], "folder")
        self.assertEqual(job["file_count"], 4)
        self.assertEqual(job["pans"]["baidu"]["total"], 4)
        self.assertEqual(job["pans"]["baidu"]["bytes_total"], 400)
        self.assertEqual(job["stage"], "uploading")
        self.assertTrue(job["steps"])

    def test_pan_progress_tracks_bytes_and_files(self):
        self.store.event(self.job_id, {"stage": "scanning", "file_count": 2,
                                       "size": 100})
        self.store.event(self.job_id, {"stage": "uploading", "pan": "baidu",
                                       "file_index": 2, "file": "b.mp4",
                                       "bytes_done": 60, "bytes_total": 100})
        row = self.get()["pans"]["baidu"]
        self.assertEqual(row["stage"], "uploading")
        self.assertEqual(row["file"], "b.mp4")
        self.assertEqual(row["bytes_done"], 60)
        self.assertEqual(row["file_index"], 2)

    def test_writer_stage_waits_until_all_pans_settle(self):
        self.store.event(self.job_id, {"stage": "scanning", "file_count": 1,
                                       "size": 100})
        self.store.event(self.job_id, {"stage": "done", "pan": "baidu",
                                       "link": "https://e/b"})
        self.assertEqual(self.get()["stage"], "uploading")   # quark 还没跑完
        self.store.event(self.job_id, {"stage": "done", "pan": "quark",
                                       "link": "https://e/q"})
        self.assertEqual(self.get()["stage"], "writing")
        self.store.event(self.job_id, {"stage": "writing", "writer": "feishu"})
        job = self.get()
        self.assertEqual(job["stage"], "writing")
        self.assertEqual(job["writer"]["stage"], "writing")

    def test_finish_marks_done_and_settles_writer(self):
        self.store.event(self.job_id, {"stage": "done", "pan": "baidu",
                                       "link": "https://e/b"})
        self.store.event(self.job_id, {"stage": "done", "pan": "quark",
                                       "link": "https://e/q"})
        self.store.finish(self.job_id, {"items": [{"pan": "baidu"}]})
        job = self.get()
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["stage"], "finished")
        self.assertEqual(job["result"]["items"][0]["pan"], "baidu")
        self.assertEqual(job["writer"]["stage"], "skipped")   # 没写文档就收尾

    def test_writer_done_is_kept_on_finish(self):
        self.store.event(self.job_id, {"stage": "done", "pan": "baidu",
                                       "link": "https://e/b"})
        self.store.event(self.job_id, {"stage": "done", "pan": "quark",
                                       "link": "https://e/q"})
        self.store.event(self.job_id, {"stage": "writing", "writer": "feishu"})
        self.store.event(self.job_id, {"stage": "done", "writer": "feishu"})
        self.store.finish(self.job_id, {"items": []})
        self.assertEqual(self.get()["writer"]["stage"], "done")

    def test_pan_failure_records_reason(self):
        self.store.event(self.job_id, {
            "stage": "failed", "pan": "quark", "code": "PAN-quark-noauth",
            "msg": "缺少夸克登录态 cookie", "hint": "重新导出 cookie"})
        row = self.get()["pans"]["quark"]
        self.assertEqual(row["stage"], "failed")
        self.assertIn("cookie", row["error"])

    def test_job_failure_sets_error_envelope(self):
        self.store.fail(self.job_id, "PUP-500", "炸了", "看日志")
        job = self.get()
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["error"], {"code": "PUP-500", "msg": "炸了",
                                        "hint": "看日志"})

    def test_snapshot_is_detached_from_store(self):
        job = self.get()
        job["pans"]["baidu"]["stage"] = "done"
        self.assertEqual(self.get()["pans"]["baidu"]["stage"], "waiting")

    def test_steps_do_not_leak_dedupe_keys(self):
        self.store.event(self.job_id, {"stage": "scanning", "file_count": 1})
        for step in self.get()["steps"]:
            self.assertNotIn("key", step)

    def test_old_jobs_are_evicted(self):
        store = JobStore(keep=2)
        ids = [store.create(pans=["baidu"]) for _ in range(3)]
        self.assertIsNone(store.get(ids[0]))
        self.assertIsNotNone(store.get(ids[2]))

    def test_unknown_job_returns_none(self):
        self.assertIsNone(self.store.get("j-nope"))


if __name__ == "__main__":
    unittest.main()
