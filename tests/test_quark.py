"""I-003 A1：夸克驱动契约测试（打桩 HTTP 层，不真连网盘）。

上游流程参考：alist drivers/quark_uc（上传：pre → hash → auth+OSS PUT → commit → finish；
列表/建目录：/file/sort、/file）+ 社区分享接口（/share → task 轮询 → /share/password）。
"""

import json
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  把 src 加入 sys.path

from panup.core.errors import AuthError, ProjectError, ShareError, UploadError
from panup.drivers.quark import QuarkDriver

# OSS 假主机（与桩内 bucket/upload_url 对应）
OSS_HOST = "https://bkt.oss.example.com"

API_LISTING = {
    "0": {"status": 200, "code": 0, "data": {"metadata": {"total": 1}, "list": [
        {"fid": "DA", "file_name": "a", "file": False, "size": 0},
    ]}},
    "DA": {"status": 200, "code": 0, "data": {"metadata": {"total": 1}, "list": [
        {"fid": "FH", "file_name": "hello.txt", "file": True, "size": 6},
    ]}},
}


def _canned_api(method, url, *, params=None, body=None, headers=None):
    path = url.split("/1/clouddrive")[-1].split("?")[0]
    if path == "/config":
        return 200, {}, json.dumps({"status": 200, "code": 0, "data": {}})
    if path == "/member":
        return 200, {}, json.dumps({"status": 200, "code": 0,
                                    "data": {"member": {"nickname": "tester"}}})
    if path == "/file/sort":
        pid = (params or {})["pdir_fid"]
        payload = API_LISTING.get(pid)
        if payload is None:
            return 200, {}, json.dumps({"status": 200, "code": 0,
                                        "data": {"metadata": {"total": 0}, "list": []}})
        return 200, {}, json.dumps(payload)
    if path == "/file" and method == "POST":
        return 200, {}, json.dumps({"status": 200, "code": 0, "data": {"fid": "DA"}})
    if path == "/file/upload/pre":
        return 200, {}, json.dumps({
            "status": 200, "code": 0,
            "metadata": {"part_size": 1048576},
            "data": {"task_id": "t1", "bucket": "bkt", "obj_key": "k",
                     "upload_id": "uid", "upload_url": "https://oss.example.com",
                     "auth_info": "ai", "callback": {"x": 1}, "fid": "FNEW"},
        })
    if path == "/file/update/hash":
        return 200, {}, json.dumps({"status": 200, "code": 0, "data": {"finish": False}})
    if path == "/file/upload/auth":
        return 200, {}, json.dumps({"status": 200, "code": 0, "data": {"auth_key": "AK"}})
    if path == "/file/upload/finish":
        return 200, {}, json.dumps({"status": 200, "code": 0,
                                    "data": {"finish": True, "fid": "FNEW"}})
    if path == "/share" and method == "POST":
        return 200, {}, json.dumps({"status": 200, "code": 0,
                                    "data": {"task_id": "ts1", "task_sync": False}})
    if path == "/task":
        return 200, {}, json.dumps({"status": 200, "code": 0, "data": {
            "status": 2, "task_resp": {"data": {"share_id": "sid1"}}}})
    if path == "/share/password":
        return 200, {}, json.dumps({"status": 200, "code": 0, "data": {
            "share_id": "sid1", "share_url": "https://pan.quark.cn/s/sid1",
            "share_pwd": "ab12"}})
    if path == "/file/delete" and method == "POST":
        return 200, {}, json.dumps({"status": 200, "code": 0, "data": {}})
    raise AssertionError(f"stub 未覆盖的端点: {method} {path}")


def _canned_oss(method, url, *, params=None, headers=None, body=None):
    oss_calls.append((method, url))
    return 200, {"ETag": '"etag-1"'}, ""


def make_driver(api=_canned_api, oss=_canned_oss):
    d = QuarkDriver({"__puus": "p", "valid": "1"})
    d._request = api
    d._request_oss = oss
    return d


calls: list[str] = []
oss_calls: list[tuple[str, str]] = []


class QuarkContractTests(unittest.TestCase):
    def setUp(self):
        calls.clear()
        oss_calls.clear()

    def wrapped(self, api=_canned_api):
        def inner(method, url, **kw):
            calls.append(f"{method} {url.split('/1/clouddrive')[-1].split('?')[0]}")
            return api(method, url, **kw)
        return inner

    def test_publish_flow_order_and_result(self):
        def oss(method, url, **kw):
            calls.append("OSS")
            return _canned_oss(method, url, **kw)

        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "hello.txt"
            f.write_text("hello!", encoding="utf-8")
            d = make_driver(self.wrapped(), oss)
            r = d.publish(f, "/a")
        self.assertEqual(r["link"], "https://pan.quark.cn/s/sid1")
        self.assertEqual(r["pwd"], "ab12")
        self.assertEqual(r["path"], "/a/hello.txt")
        expected = ["/file", "/file/upload/pre", "/file/update/hash",
                    "/file/upload/auth", "OSS", "/file/upload/auth",
                    "OSS", "/file/upload/finish", "/share", "/task",
                    "/share/password"]
        joined = "|".join(c.split(" ", 1)[-1].split("?")[0] for c in calls)
        last = -1
        for token in expected:
            idx = joined.find(token, last + 1)
            self.assertGreater(idx, last, f"调用顺序不对: {token} 于 {joined}")
            last = idx

    def test_rapid_upload_skips_oss(self):
        def api(method, url, *, params=None, body=None, headers=None):
            path = url.split("/1/clouddrive")[-1].split("?")[0]
            if path == "/file/update/hash":
                return 200, {}, json.dumps({"status": 200, "code": 0,
                                            "data": {"finish": True}})
            return _canned_api(method, url, params=params, body=body, headers=headers)

        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "x.bin"
            f.write_bytes(b"x")
            r = make_driver(api).upload(f, "/a")
        self.assertTrue(r["rapid"])
        self.assertEqual(oss_calls, [])

    def test_auth_check_returns_nickname(self):
        info = make_driver().auth_check()
        self.assertTrue(info["ok"])
        self.assertEqual(info["account"], "tester")

    def test_auth_failure_raises_auth_error_with_hint(self):
        def api(method, url, **kw):
            return 401, {}, json.dumps({"status": 401, "code": 31001, "message": "未登录"})

        d = QuarkDriver({"valid": "1"})
        d._request = api
        with self.assertRaises(AuthError) as cm:
            d.auth_check()
        self.assertIn("cookie", cm.exception.hint.lower())

    def test_missing_cookie_raises_auth_error_before_network(self):
        d = QuarkDriver({})
        with self.assertRaises(AuthError) as cm:
            d.auth_check()
        self.assertIn("secrets/quark_cookie.txt", cm.exception.hint)

    def test_mkdir_idempotent_on_same_name(self):
        def api(method, url, *, params=None, body=None, headers=None):
            if body is not None and body.get("file_name") == "a":
                return 400, {}, json.dumps({"status": 400, "code": 31002,
                                            "message": "file is doloading[同名冲突]"})
            return _canned_api(method, url, params=params, body=body, headers=headers)

        r = make_driver(api).mkdir("/a")
        self.assertEqual(r["created"], False)
        self.assertEqual(r["path"], "/a")

    def test_share_failure_raises_share_error(self):
        def api(method, url, *, params=None, body=None, headers=None):
            path = url.split("/1/clouddrive")[-1].split("?")[0]
            if path == "/share":
                return 200, {}, json.dumps({"status": 200, "code": 31003,
                                            "message": "分享受限"})
            return _canned_api(method, url, params=params, body=body, headers=headers)

        with self.assertRaises(ShareError):
            make_driver(api).share("/a/hello.txt")

    def test_share_task_reads_top_level_share_id(self):
        """文件夹分享走异步任务，share_id 在 data 顶层（I-017 实测形状）。"""
        def api(method, url, *, params=None, body=None, headers=None):
            path = url.split("/1/clouddrive")[-1].split("?")[0]
            if path == "/task":
                return 200, {}, json.dumps({"status": 200, "code": 0, "data": {
                    "status": 2, "share_id": "sid9", "share": {}}})
            return _canned_api(method, url, params=params, body=body, headers=headers)

        r = make_driver(api).share("/a/hello.txt")
        self.assertEqual(r["share_id"], "sid9")

    def test_share_defaults_to_no_password(self):
        """人定（2026-11-09）：夸克分享默认不带提取码；显式传 pwd 才设码。"""
        seen = {}

        def api(method, url, *, params=None, body=None, headers=None):
            path = url.split("/1/clouddrive")[-1].split("?")[0]
            if path == "/share":
                seen["password"] = (body or {}).get("password")
                return 200, {}, json.dumps({"status": 200, "code": 0, "data": {
                    "task_sync": True, "share_id": "sid5",
                    "share_url": "https://pan.quark.cn/s/sid5"}})
            if path == "/share/password":
                return 200, {}, json.dumps({"status": 200, "code": 0, "data": {
                    "share_url": "https://pan.quark.cn/s/sid5", "share_pwd": ""}})
            return _canned_api(method, url, params=params, body=body, headers=headers)

        d = make_driver(api)
        d._fid_cache["/a/hello.txt"] = "F1"
        r = d.share("/a/hello.txt")
        self.assertEqual(seen["password"], "")
        self.assertEqual(r["pwd"], "")

    def test_share_with_explicit_pwd_still_sets_it(self):
        seen = {}

        def api(method, url, *, params=None, body=None, headers=None):
            path = url.split("/1/clouddrive")[-1].split("?")[0]
            if path == "/share":
                seen["password"] = (body or {}).get("password")
                return 200, {}, json.dumps({"status": 200, "code": 0, "data": {
                    "task_sync": True, "share_id": "sid6",
                    "share_url": "https://pan.quark.cn/s/sid6"}})
            if path == "/share/password":
                return 200, {}, json.dumps({"status": 200, "code": 0, "data": {
                    "share_url": "https://pan.quark.cn/s/sid6", "share_pwd": "k9m2"}})
            return _canned_api(method, url, params=params, body=body, headers=headers)

        d = make_driver(api)
        d._fid_cache["/a/hello.txt"] = "F1"
        r = d.share("/a/hello.txt", pwd="k9m2")
        self.assertEqual(seen["password"], "k9m2")
        self.assertEqual(r["pwd"], "k9m2")

    def test_upload_missing_local_file_raises_without_network(self):
        with self.assertRaises(UploadError):
            make_driver().upload("Z:/no/such/file.bin", "/a")
        self.assertEqual(calls, [])

    def test_list_returns_contract_shape(self):
        items = make_driver().list("/a")
        self.assertEqual(items[0]["name"], "hello.txt")
        self.assertFalse(items[0]["isdir"])
        self.assertEqual(items[0]["fs_id"], "FH")

    def test_norm_rejects_windows_drive_path(self):
        with self.assertRaises(ProjectError):
            QuarkDriver._norm("C:/x")

    def test_delete_resolves_fid_then_posts_file_delete(self):
        d = make_driver(self.wrapped())
        res = d.delete(["/a"])
        self.assertEqual(res["deleted"], ["/a"])
        self.assertIn("POST /file/delete", calls)

    def test_delete_missing_dir_is_idempotent(self):
        """解析不到 fid（目录不存在）→ 进 missing，不抛错。"""
        res = make_driver(self.wrapped()).delete(["/nope"])
        self.assertEqual(res["missing"], ["/nope"])
        self.assertEqual(res["failed"], [])

    def test_delete_drops_stale_fid_cache(self):
        d = make_driver(self.wrapped())
        d._fid_cache["/a"] = "DA"
        d._fid_cache["/a/hello.txt"] = "FH"
        d.delete(["/a"])
        self.assertNotIn("/a", d._fid_cache)
        self.assertNotIn("/a/hello.txt", d._fid_cache)

    def test_delete_root_is_reported_per_path(self):
        calls.clear()
        res = make_driver(self.wrapped()).delete(["/"])
        self.assertEqual(res["failed"][0]["code"], "PAN-quark-root")
        self.assertEqual(calls, [])

    def test_delete_to_trash_false_is_rejected(self):
        with self.assertRaises(UploadError) as cm:
            make_driver(self.wrapped()).delete(["/a"], to_trash=False)
        self.assertEqual(cm.exception.code, "PAN-quark-purge")


if __name__ == "__main__":
    unittest.main()
