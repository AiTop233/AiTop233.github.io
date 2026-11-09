"""Driver 基类与注册表契约测试：注册、查找、重复注册与未知网盘报错。"""

import unittest

import support  # noqa: F401  把 src 加入 sys.path

from panup.core.errors import ProjectError
from panup.drivers.base import DRIVERS, Driver, get_driver, register


@register
class DummyDriver(Driver):
    name = "dummy"

    def auth_check(self):
        return {"ok": True}

    def mkdir(self, remote_dir):
        return {"path": remote_dir, "created": True}

    def upload(self, local_path, remote_dir, *, overwrite=True, on_progress=None):
        return {"path": f"{remote_dir}/x", "size": 1}

    def share(self, remote_path, *, pwd=None, period_days=0):
        return {"link": "https://example.com/s/1", "pwd": pwd or ""}

    def list(self, remote_dir):
        return []


class RegistryTests(unittest.TestCase):
    def test_registered_driver_is_lookupable(self):
        self.assertIn("dummy", DRIVERS)
        d = get_driver("dummy")
        self.assertIsInstance(d, DummyDriver)
        self.assertEqual(d.publish("/tmp/f", "/dst")["link"], "https://example.com/s/1")

    def test_unknown_driver_lists_available(self):
        with self.assertRaises(ProjectError) as cm:
            get_driver("nope")
        self.assertIn("dummy", str(cm.exception))

    def test_duplicate_registration_rejected(self):
        with self.assertRaises(ProjectError):
            @register
            class Again(Driver):
                name = "dummy"

                def auth_check(self): ...
                def mkdir(self, remote_dir): ...
                def upload(self, local_path, remote_dir, *, overwrite=True, on_progress=None): ...
                def share(self, remote_path, *, pwd=None, period_days=0): ...
                def list(self, remote_dir): ...

    def test_unnamed_driver_rejected(self):
        with self.assertRaises(ProjectError):
            @register
            class NoName(Driver):
                name = ""

                def auth_check(self): ...
                def mkdir(self, remote_dir): ...
                def upload(self, local_path, remote_dir, *, overwrite=True, on_progress=None): ...
                def share(self, remote_path, *, pwd=None, period_days=0): ...
                def list(self, remote_dir): ...

    def test_default_delete_says_unsupported(self):
        """没实现 delete 的驱动（老驱动 / 测试桩）不因新增接口而崩：报 PUP-422。"""
        d = DummyDriver()
        with self.assertRaises(ProjectError) as cm:
            d.delete(["/a"])
        self.assertEqual(cm.exception.code, "PUP-422")
        self.assertIn("不支持删除", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
