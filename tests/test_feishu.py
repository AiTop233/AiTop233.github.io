"""I-012 A1：飞书 Writer 固定更新规则契约测试（打桩 HTTP 层，不真连飞书）。

版式（D-003 / PRD F3）：h2「YYMMDD 文件名」小节 + 盘名链接行（pwd 内嵌），
插到文档最顶（首个标题块前；无标题块为 0）。
"""

import contextlib
import io
import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path

import support  # noqa: F401  把 src 加入 sys.path

from panup.core.errors import AuthError, ConfigError, WriterError
from panup.writers import feishu as feishu_mod
from panup.writers.feishu import FeishuWriter

RECORD = {
    "record_id": 1, "pan": "quark", "filename": "报告.pdf",
    "link": "https://pan.quark.cn/s/abc123", "pwd": "rt67",
    "remote_path": "/分享/报告.pdf", "size": 123, "period_days": 0,
}

# 模拟文档：index 0 是普通文本，index 1 是 h2 标题（首个标题块 → 插入 index 1）
DOC_ITEMS = [
    {"block_type": 2, "text": {"elements": []}},
    {"block_type": 4, "heading2": {"elements": []}},
    {"block_type": 2, "text": {"elements": []}},
]

bodies: list[dict] = []
calls: list[str] = []


def _resp(payload):
    return 200, json.dumps(payload, ensure_ascii=False)


def _canned(method, url, *, body=None, headers=None):
    calls.append(url)
    bearer = (headers or {}).get("Authorization", "").startswith("Bearer ")
    if "tenant_access_token" in url:
        return _resp({"code": 0, "msg": "ok",
                      "tenant_access_token": "t-abc", "expire": 7200})
    if "/documents/doctest" in url and method == "GET" and "/blocks/" not in url:
        # 真实接口要求 Bearer token（I-005 真实验收发现的缺失头 bug）
        if not bearer:
            return _resp({"code": 99991661, "msg": "Missing access token"})
        return _resp({"code": 0, "msg": "ok",
                      "data": {"document": {"document_id": "doctest"}}})
    if method == "GET" and "page_size=500" in url:
        # 列页面子块（找插入位置）
        if not bearer:
            return _resp({"code": 99991661, "msg": "Missing access token"})
        return _resp({"code": 0, "msg": "ok",
                      "data": {"items": DOC_ITEMS, "has_more": False}})
    if "/children" in url and method == "POST":
        if not bearer:
            return _resp({"code": 99991661, "msg": "Missing access token"})
        bodies.append(body)
        return _resp({"code": 0, "msg": "ok",
                      "data": {"children": [{"block_id": "blk-h2"},
                                            {"block_id": "blk-link"}]}})
    raise AssertionError(f"stub 未覆盖: {method} {url}")


def make_writer(canned=_canned, **kw):
    defaults = dict(doc_token="doctest", app_id="cli_a", app_secret="sec")
    defaults.update(kw)
    w = FeishuWriter(**defaults)
    w._request = canned
    return w


class FeishuSectionRuleTests(unittest.TestCase):
    """I-012：固定更新规则的行为契约。"""

    def setUp(self):
        bodies.clear()
        calls.clear()
        feishu_mod._today_str = lambda: "261109"

    def test_inserts_h2_section_at_first_heading_index(self):
        summary = make_writer().append_record(RECORD)
        self.assertEqual(summary["block_ids"], ["blk-h2", "blk-link"])
        self.assertEqual(summary["index"], 1)
        self.assertEqual(bodies[0]["index"], 1)
        self.assertEqual(len(bodies[0]["children"]), 2)
        h2 = bodies[0]["children"][0]
        self.assertEqual(h2["block_type"], 4)
        self.assertEqual(h2["heading2"]["elements"][0]["text_run"]["content"],
                         "261109 报告")

    def test_link_line_embeds_pwd_and_clickable(self):
        make_writer().append_record(RECORD)
        line = bodies[0]["children"][1]
        self.assertEqual(line["block_type"], 2)
        els = line["text"]["elements"]
        self.assertEqual(els[0]["text_run"]["content"], "夸克：")
        full = RECORD["link"] + "?pwd=" + RECORD["pwd"]
        self.assertEqual(els[1]["text_run"]["content"], full)
        self.assertEqual(
            els[1]["text_run"]["text_element_style"]["link"]["url"],
            urllib.parse.quote(full, safe=""))

    def test_no_heading_doc_inserts_at_top(self):
        w = make_writer(lambda m, u, **k: _canned(
            m, u, body=k.get("body"), headers=k.get("headers"))
            if m != "GET" or "page_size=500" not in u
            else _resp({"code": 0, "data": {"items": DOC_ITEMS[:1],
                                            "has_more": False}}))
        summary = w.append_record(RECORD)
        self.assertEqual(summary["index"], 0)

    def test_baidu_label_and_pwd_embedded(self):
        make_writer().append_record({**RECORD, "pan": "baidu"})
        els = bodies[0]["children"][1]["text"]["elements"]
        self.assertEqual(els[0]["text_run"]["content"], "百度：")

    def test_unknown_pan_uses_its_name_as_label(self):
        make_writer().append_record({**RECORD, "pan": "xunlei"})
        els = bodies[0]["children"][1]["text"]["elements"]
        self.assertEqual(els[0]["text_run"]["content"], "xunlei：")

    def test_filename_without_extension(self):
        make_writer().append_record({**RECORD,
                                     "filename": "教程.final.v2.zip"})
        h2 = bodies[0]["children"][0]
        self.assertEqual(h2["heading2"]["elements"][0]["text_run"]["content"],
                         "261109 教程.final.v2")

    def test_no_pwd_keeps_plain_link(self):
        make_writer().append_record({**RECORD, "pwd": ""})
        els = bodies[0]["children"][1]["text"]["elements"]
        self.assertEqual(els[1]["text_run"]["content"], RECORD["link"])

    def test_token_cached_across_appends(self):
        w = make_writer()
        w.append_record(RECORD)
        w.append_record(RECORD)
        token_calls = [u for u in calls if "tenant_access_token" in u]
        self.assertEqual(len(token_calls), 1)


class FeishuWriterGuardTests(unittest.TestCase):
    """凭证 / 权限 / 配置的报错契约（I-005 承袭，I-012 仍要咬住）。"""

    def setUp(self):
        bodies.clear()
        calls.clear()

    def test_doc_no_permission_raises_auth_error_with_grant_hint(self):
        def canned(method, url, *, body=None, headers=None):
            if "tenant_access_token" in url:
                return _canned(method, url, body=body, headers=headers)
            return _resp({"code": 99991672, "msg": "permission denied"})

        with self.assertRaises(AuthError) as cm:
            make_writer(canned).auth_check()
        self.assertIn("文档应用", cm.exception.hint)

    def test_token_failure_raises_auth_error(self):
        def canned(method, url, **kw):
            return _resp({"code": 10003, "msg": "invalid app_id"})

        with self.assertRaises(AuthError) as cm:
            make_writer(canned).auth_check()
        self.assertIn("app_id", cm.exception.hint)

    def test_append_failure_raises_writer_error(self):
        def canned(method, url, *, body=None, headers=None):
            if "/children" in url and method == "POST":
                return _resp({"code": 99999999, "msg": "boom"})
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
