"""I-002 A1：百度驱动契约测试（打桩 HTTP 层，不真连网盘）。"""

import json
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  把 src 加入 sys.path

from panup.core.errors import AuthError, ProjectError, ShareError, UploadError
from panup.drivers.baidu import BaiduDriver, _norm


def _canned(method, url, *, params=None, data=None, files=None, headers=None):
    """按端点返回百度网页接口的典型响应；记录调用序列供断言。"""
    calls.append(url)
    if "gettemplatevariable" in url:
        return json.dumps({"errno": 0, "result": {"bdstoken": "tok", "uk": 1, "username": "tester"}})
    if "locateupload" in url or (params or {}).get("method") == "locateupload":
        return json.dumps({"errno": 0, "server": ["d.pcs.baidu.com"]})
    if "/api/quota" in url:
        return json.dumps({"errno": 0, "total": 100, "used": 40, "free": 5})
    if "/api/list" in url:
        return json.dumps({"errno": 0, "list": [
            {"fs_id": 1, "server_filename": "x.txt", "path": "/a/x.txt", "size": 3, "isdir": 0, "md5": "m"},
        ]})
    if "/api/precreate" in url:
        if data.get("path") == "/a/rapid.bin":
            return json.dumps({"errno": 0, "return_type": "2"})
        return json.dumps({"errno": 0, "uploadid": "u1", "return_type": "1"})
    if "superfile2" in url:
        return json.dumps({"errno": 0, "md5": "abc"})
    if "/api/create" in url:
        if data.get("isdir") == 1:
            return json.dumps({"errno": 0})
        return json.dumps({"errno": 0, "info": {"fs_id": 123, "path": data.get("path")}})
    if "/api/filemetas" in url:
        return json.dumps({"errno": 0, "info": [
            {"fs_id": 123, "path": "/a/hello.txt", "size": 6},
        ]})
    if "/api/filemanager" in url:
        target = json.loads(data["filelist"])[0]["path"]
        if target.endswith("gone"):
            return json.dumps({"errno": -9, "info": []})
        return json.dumps({"errno": 0, "taskid": 9,
                           "info": [{"errno": 0, "path": target}]})
    if "/share/pset" in url:
        return json.dumps({"errno": 0, "link": "https://pan.baidu.com/s/1abc",
                           "pwd": "k9x2", "shareid": 7})
    raise AssertionError(f"stub 未覆盖的端点: {url}")


def make_driver(canned=_canned):
    d = BaiduDriver({"BDUSS": "x", "STOKEN": "y"})
    d._request = canned
    return d


calls: list[str] = []


class BaiduContractTests(unittest.TestCase):
    def setUp(self):
        calls.clear()

    def test_publish_flow_order_and_result(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "hello.txt"
            f.write_text("hello!", encoding="utf-8")
            r = make_driver().publish(f, "/a")
        self.assertEqual(r["link"], "https://pan.baidu.com/s/1abc")
        self.assertEqual(r["pwd"], "k9x2")
        self.assertEqual(r["path"], "/a/hello.txt")
        self.assertEqual(r["fs_id"], 123)
        order = ["gettemplatevariable", "/api/create", "/api/precreate",
                 "superfile2", "/api/create", "/share/pset"]
        joined = "|".join(calls)
        last = -1
        for token in order:
            idx = joined.find(token, last + 1)
            self.assertGreater(idx, last, f"调用顺序不对: {token} 出现在 {joined}")
            last = idx

    def test_rapid_upload_skips_byte_transfer(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "rapid.bin"
            f.write_bytes(b"r")
            r = make_driver().publish(f, "/a")
        self.assertTrue(r["rapid"])
        self.assertNotIn("superfile2", "|".join(calls))

    def test_overwrite_defaults_to_rtype3(self):
        seen = {}

        def canned(method, url, *, params=None, data=None, files=None, headers=None):
            if "/api/precreate" in url:
                seen["rtype"] = data.get("rtype")
                return json.dumps({"errno": 0, "uploadid": "u1"})
            if "superfile2" in url:
                return json.dumps({"errno": 0, "md5": "abc"})
            if "/api/create" in url and data.get("isdir") == 0:
                return json.dumps({"errno": 0, "info": {"fs_id": 1, "path": data.get("path")}})
            return _canned(method, url, params=params, data=data, files=files, headers=headers)

        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "a.txt"
            f.write_text("x", encoding="utf-8")
            make_driver(canned).upload(f, "/a")
        self.assertEqual(seen["rtype"], 3)

    def test_auth_check_returns_account_and_quota(self):
        info = make_driver().auth_check()
        self.assertTrue(info["ok"])
        self.assertEqual(info["account"], "tester")
        self.assertEqual(info["quota"]["free"], 60)

    def test_auth_expired_raises_auth_error_with_hint(self):
        def canned(method, url, **kw):
            return json.dumps({"errno": -6})

        d = BaiduDriver({"BDUSS": "x"})
        d._request = canned
        with self.assertRaises(AuthError) as cm:
            d.auth_check()
        self.assertEqual(cm.exception.errno, -6)
        self.assertIn("cookie", cm.exception.hint)

    def test_missing_cookie_raises_auth_error_before_network(self):
        d = BaiduDriver({})
        with self.assertRaises(AuthError) as cm:
            d.auth_check()
        self.assertIn("BDUSS", cm.exception.hint)

    def test_mkdir_idempotent_when_cloud_exists(self):
        def canned(method, url, *, params=None, data=None, files=None, headers=None):
            if "gettemplatevariable" in url:
                return json.dumps({"errno": 0, "result": {"bdstoken": "t", "uk": 1, "username": "u"}})
            if "/api/create" in url and data.get("isdir") == 1:
                return json.dumps({"errno": -8})
            raise AssertionError(f"mkdir 幂等场景不应触发其他端点: {url}")

        r = make_driver(canned).mkdir("/a")
        self.assertEqual(r, {"path": "/a", "created": False})

    def test_share_failure_raises_share_error(self):
        def canned(method, url, **kw):
            if "gettemplatevariable" in url:
                return json.dumps({"errno": 0, "result": {"bdstoken": "t", "uk": 1, "username": "u"}})
            if "/api/filemetas" in url:
                return json.dumps({"errno": 0, "info": [{"fs_id": 9, "path": "/a.txt", "size": 1}]})
            return json.dumps({"errno": 2})

        with self.assertRaises(ShareError):
            make_driver(canned).share("/a.txt")

    def test_upload_missing_local_file_raises_without_network(self):
        with self.assertRaises(UploadError):
            make_driver().upload("Z:/no/such/file.bin", "/a")
        self.assertEqual(calls, [])

    def test_norm_rejects_windows_drive_path(self):
        with self.assertRaises(ProjectError):
            _norm("C:/Program Files/Git/a")

    def test_list_returns_contract_shape(self):
        items = make_driver().list("/a")
        self.assertEqual(items[0]["name"], "x.txt")
        self.assertFalse(items[0]["isdir"])

    def test_delete_calls_filemanager_with_opera_delete(self):
        seen = {}

        def canned(method, url, *, params=None, **kw):
            if "/api/filemanager" in url:
                seen.update(params or {})
            return _canned(method, url, params=params, **kw)

        res = make_driver(canned).delete("/panup验收-I017")
        self.assertTrue(res["deleted"])
        self.assertFalse(res["missing"])
        self.assertEqual(seen.get("opera"), "delete")
        self.assertEqual(seen.get("onnest"), "fail")

    def test_delete_missing_path_is_idempotent(self):
        """远端本来就没有 → missing=True 而不是抛错（删验收目录会重跑）。"""
        res = make_driver().delete("/a/gone")
        self.assertFalse(res["deleted"])
        self.assertTrue(res["missing"])

    def test_delete_root_refused_before_network(self):
        calls.clear()
        with self.assertRaises(UploadError) as cm:
            make_driver().delete("/")
        self.assertEqual(cm.exception.code, "PUP-108")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
