"""I-005 A1：飞书 Writer 契约测试（打桩 HTTP 层，不真连飞书）。

上游：open.feishu.cn tenant_access_token + docx v1（创建块，text_run 带 link 样式）。
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  把 src 加入 sys.path

from panup.core.errors import AuthError, ConfigError, WriterError
from panup.writers.feishu import FeishuWriter

RECORD = {
    "record_id": 1, "pan": "quark", "filename": "报告.pdf",
    "link": "https://pan.quark.cn/s/abc123", "pwd": "rt67",
    "remote_path": "/分享/报告.pdf", "size": 123, "period_days": 0,
}


def _canned(method, url, *, body=None, headers=None):
    calls.append(url)
    if "/documents/doctest" in url and method == "GET":
        # 真实接口要求 Bearer token（2026-11-09 真实验收发现的缺失头 bug）
        if not (headers or {}).get("Authorization", "").startswith("Bearer "):
            return 200, json.dumps({"code": 99991661, "msg": "Missing access token"})
    if "tenant_access_token" in url:
        return 200, json.dumps({"code": 0, "msg": "ok",
                                "tenant_access_token": "t-abc", "expire": 7200})
    if "/documents/doctest" in url and method == "GET":
        return 200, json.dumps({"code": 0, "msg": "ok",
                                "data": {"document": {"document_id": "doctest"}}})
    if "/children" in url and method == "POST":
        if not (headers or {}).get("Authorization", "").startswith("Bearer "):
            return 200, json.dumps({"code": 99991661, "msg": "Missing access token"})
        return 200, json.dumps({"code": 0, "msg": "ok",
                                "data": {"children": [{"block_id": "blk1"}]}})
    raise AssertionError(f"stub 未覆盖: {method} {url}")


calls: list[str] = []


def make_writer(canned=_canned, **kw):
    defaults = dict(doc_token="doctest", app_id="cli_a", app_secret="sec")
    defaults.update(kw)
    w = FeishuWriter(**defaults)
    w._request = canned
    return w


class FeishuWriterTests(unittest.TestCase):
    def setUp(self):
        calls.clear()

    def test_append_record_writes_link_block(self):
        bodies = []

        def canned(method, url, *, body=None, headers=None):
            if "/children" in url and method == "POST":
                bodies.append(body)
            return _canned(method, url, body=body, headers=headers)

        summary = make_writer(canned).append_record(RECORD)
        self.assertEqual(summary["block_id"], "blk1")
        block = bodies[0]["children"][0]
        self.assertEqual(block["block_type"], 2)
        elements = block["text"]["elements"]
        # 三个文本段：时间·文件名前缀 / 可点击链接 / 提取码后缀
        self.assertIn("报告.pdf", elements[0]["text_run"]["content"])
        self.assertEqual(elements[1]["text_run"]["content"], RECORD["link"])
        self.assertEqual(
            elements[1]["text_run"]["text_element_style"]["link"]["url"],
            "https%3A%2F%2Fpan.quark.cn%2Fs%2Fabc123")
        self.assertIn("rt67", elements[2]["text_run"]["content"])

    def test_token_cached_across_appends(self):
        w = make_writer()
        w.append_record(RECORD)
        w.append_record(RECORD)
        token_calls = [u for u in calls if "tenant_access_token" in u]
        self.assertEqual(len(token_calls), 1)

    def test_token_failure_raises_auth_error(self):
        def canned(method, url, **kw):
            return 200, json.dumps({"code": 10003, "msg": "invalid app_id"})

        with self.assertRaises(AuthError) as cm:
            make_writer(canned).auth_check()
        self.assertIn("app_id", cm.exception.hint)

    def test_doc_no_permission_raises_auth_error_with_grant_hint(self):
        def canned(method, url, *, body=None, headers=None):
            if "tenant_access_token" in url:
                return _canned(method, url, body=body, headers=headers)
            return 200, json.dumps({"code": 99991672, "msg": "permission denied"})

        with self.assertRaises(AuthError) as cm:
            make_writer(canned).auth_check()
        self.assertIn("文档应用", cm.exception.hint)

    def test_append_failure_raises_writer_error(self):
        def canned(method, url, *, body=None, headers=None):
            if "/children" in url:
                return 200, json.dumps({"code": 99999999, "msg": "boom"})
            return _canned(method, url, body=body, headers=headers)

        with self.assertRaises(WriterError):
            make_writer(canned).append_record(RECORD)

    def test_missing_doc_token_points_to_config(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.toml"
            cfg.write_text('[log]\ndir = "logs"\n', encoding="utf-8")
            import os
            old = os.environ.get("PANUP_CONFIG")
            os.environ["PANUP_CONFIG"] = str(cfg)
            try:
                with self.assertRaises(ConfigError) as cm:
                    FeishuWriter(app_id="a", app_secret="b").auth_check()
            finally:
                if old is None:
                    del os.environ["PANUP_CONFIG"]
                else:
                    os.environ["PANUP_CONFIG"] = old
        self.assertIn("doc_token", cm.exception.hint)

    def test_missing_credentials_points_to_secrets(self):
        import panup.writers.feishu as feishu_mod

        orig = feishu_mod.load_default_credentials
        feishu_mod.load_default_credentials = lambda: {}
        try:
            with self.assertRaises(AuthError) as cm:
                FeishuWriter(doc_token="doctest").auth_check()
        finally:
            feishu_mod.load_default_credentials = orig
        self.assertIn("feishu_app.json", cm.exception.hint)

    def test_registered_name(self):
        self.assertEqual(FeishuWriter.name, "feishu")


if __name__ == "__main__":
    unittest.main()
