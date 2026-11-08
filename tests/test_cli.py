"""I-004 A3/A4/A5/A6：CLI 行为（打桩驱动，不真连网盘）。"""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  把 src 加入 sys.path

import panup.cli as cli
from panup.core.errors import UploadError


class FakeCliDriver:
    """CLI 测试桩：行为与 FakeDriver 一致，可注入 upload 异常。"""

    name = "fake"

    def __init__(self, *, upload_error=None, auth_ok=True):
        self.upload_error = upload_error
        self.auth_ok = auth_ok
        self.calls = []

    def auth_check(self):
        self.calls.append("auth_check")
        if not self.auth_ok:
            from panup.core.errors import AuthError
            raise AuthError("登录态失效", code="PAN-fake-auth", hint="重新导出 cookie")
        return {"ok": True, "account": "tester"}

    def mkdir(self, remote_dir):
        self.calls.append(("mkdir", remote_dir))
        return {"path": remote_dir, "created": True}

    def upload(self, local_path, remote_dir, *, overwrite=True, on_progress=None):
        self.calls.append(("upload", remote_dir))
        if self.upload_error:
            raise self.upload_error
        return {"path": f"{remote_dir.rstrip('/')}/{Path(local_path).name}",
                "size": 5, "rapid": False}

    def share(self, remote_path, *, pwd=None, period_days=0):
        self.calls.append(("share", remote_path, period_days))
        return {"link": "https://e/s/1", "pwd": pwd or "ab12", "path": remote_path}

    def list(self, remote_dir):
        return []


def run_cli(args, monkey_driver=None):
    """跑一遍 CLI，捕获 stdout/stderr，返回 (exit_code, out, err)。"""
    orig_build = getattr(cli, "build_driver", None)
    if monkey_driver is not None:
        cli.build_driver = lambda pan: monkey_driver
    try:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(args)
        return code, out.getvalue(), err.getvalue()
    finally:
        if orig_build is not None:
            cli.build_driver = orig_build
        elif monkey_driver is not None:
            del cli.build_driver


class CliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.src = Path(self.tmp) / "a.txt"
        self.src.write_text("hello", encoding="utf-8")
        self.db = str(Path(self.tmp) / "ledger.db")

    def tearDown(self):
        self._tmp.cleanup()

    def _upload_args(self, extra=()):
        return ["upload", str(self.src), "--pan", "fake", "--dir", "/分享",
                "--db", self.db, *extra]

    def test_upload_success_prints_link_and_status_lists(self):
        code, out, _ = run_cli(self._upload_args(), FakeCliDriver())
        self.assertEqual(code, 0)
        self.assertIn("https://e/s/1", out)
        self.assertIn("ab12", out)
        code2, out2, _ = run_cli(["status", "--db", self.db, "--limit", "5"])
        self.assertEqual(code2, 0)
        self.assertIn("success", out2)

    def test_dedup_notice_on_second_run(self):
        run_cli(self._upload_args(), FakeCliDriver())
        code, out, _ = run_cli(self._upload_args(), FakeCliDriver())
        self.assertEqual(code, 0)
        self.assertIn("去重", out)
        self.assertIn("https://e/s/1", out)

    def test_doc_feishu_warns_not_enabled(self):
        code, out, _ = run_cli(self._upload_args(("--doc", "nosuch")),
                               FakeCliDriver())
        self.assertEqual(code, 0)
        self.assertIn("未启用", out)

    def test_upload_failure_exits_nonzero_with_hint(self):
        code, _out, err = run_cli(
            self._upload_args(), FakeCliDriver(upload_error=UploadError("OSS 挂了")))
        self.assertNotEqual(code, 0)
        self.assertIn("OSS 挂了", err)

    def test_missing_local_file_exits_nonzero(self):
        code, _out, err = run_cli(
            ["upload", str(Path(self.tmp) / "nope.txt"), "--pan", "fake",
             "--dir", "/x", "--db", self.db], FakeCliDriver())
        self.assertNotEqual(code, 0)
        self.assertIn("本地文件不存在", err)

    def test_date_dir_flag_reaches_pipeline(self):
        import panup.core.pipeline as pipeline
        orig = pipeline.date_subdir
        seen = {}
        pipeline.date_subdir = lambda base, d: seen.setdefault("base", base)
        try:
            code, out, _ = run_cli(self._upload_args(("--date-dir",)),
                                   FakeCliDriver())
        finally:
            pipeline.date_subdir = orig
        self.assertEqual(code, 0)
        self.assertEqual(seen["base"], "/分享")

    def test_check_reports_driver_status(self):
        code, out, _ = run_cli(["check", "--pan", "fake"], FakeCliDriver())
        self.assertEqual(code, 0)
        self.assertIn("fake", out)


if __name__ == "__main__":
    unittest.main()
