"""I-001 A4：错误契约 —— ProjectError 子类携带 code / errno / hint / retriable。"""

import unittest

import support  # noqa: F401  把 src 加入 sys.path

from panup.core.errors import (
    AuthError,
    ConfigError,
    ProjectError,
    ShareError,
    UploadError,
    WriterError,
)


class ErrorContractTests(unittest.TestCase):
    def test_carries_code_errno_and_hint(self):
        e = AuthError(
            "登录态失效",
            code="PAN-baidu--6",
            errno=-6,
            hint="重新登录并导出 cookie 到 secrets/",
        )
        self.assertEqual(e.code, "PAN-baidu--6")
        self.assertEqual(e.errno, -6)
        self.assertIn("重新登录", e.hint)
        self.assertIn("errno=-6", str(e))
        self.assertIn("怎么办", str(e))

    def test_defaults_are_conservative(self):
        e = ProjectError("x")
        self.assertEqual(e.code, "PUP-000")
        self.assertIsNone(e.errno)
        self.assertIsNone(e.hint)
        self.assertFalse(e.retriable)

    def test_all_contract_subclasses_exist(self):
        for cls in (ConfigError, AuthError, UploadError, ShareError, WriterError):
            self.assertTrue(issubclass(cls, ProjectError))

    def test_retriable_can_be_marked_on_subclass(self):
        class Temporary(ProjectError):
            retriable = True

        self.assertTrue(Temporary("x").retriable)
        self.assertFalse(ProjectError("x").retriable)


if __name__ == "__main__":
    unittest.main()
