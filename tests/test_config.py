"""I-001 A1 / A2：配置加载（正常 / 缺文件 / 坏格式）与必填项一次性清单。"""

import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  把 src 加入 sys.path

from panup.config import ensure_config, load_config, missing_required
from panup.core.errors import ConfigError

NORMAL = """
[pan]
baidu_default_dir = "/来自电脑"

[log]
dir = "logs"
"""


class LoadConfigTests(unittest.TestCase):
    def test_normal_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text(NORMAL, encoding="utf-8")
            cfg = load_config(p)
        self.assertEqual(cfg["pan"]["baidu_default_dir"], "/来自电脑")
        self.assertEqual(cfg["log"]["dir"], "logs")

    def test_missing_file_gives_recovery_hint(self):
        with self.assertRaises(ConfigError) as cm:
            load_config(Path("Z:/no/such/config.toml"))
        self.assertIn("config.example.toml", cm.exception.hint)

    def test_bad_toml_reports_code(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.toml"
            p.write_text("[pan\nbroken", encoding="utf-8")
            with self.assertRaises(ConfigError) as cm:
                load_config(p)
        self.assertEqual(cm.exception.code, "PUP-101")


class RequiredTests(unittest.TestCase):
    def test_missing_lists_all_at_once(self):
        cfg = {"pan": {"baidu_default_dir": ""}}
        missing = missing_required(
            cfg,
            ["pan.baidu_default_dir", "watch.interval_seconds", "feishu.doc_token"],
        )
        self.assertEqual(
            missing,
            ["pan.baidu_default_dir", "watch.interval_seconds", "feishu.doc_token"],
        )

    def test_present_values_pass(self):
        cfg = {"watch": {"interval_seconds": 5}}
        self.assertEqual(missing_required(cfg, ["watch.interval_seconds"]), [])

    def test_ensure_raises_naming_every_missing_key(self):
        with self.assertRaises(ConfigError) as cm:
            ensure_config({}, ["a.b", "c.d"])
        self.assertIn("a.b", str(cm.exception))
        self.assertIn("c.d", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
