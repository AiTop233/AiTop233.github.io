"""I-017 A1：资源文件夹化（D-005）—— 单文件也建标题层、文件夹镜像、同名报错、重传跳过。

全部打桩驱动，不连真实网盘；真实链路在自验里另外跑。
"""

import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  把 src 加入 sys.path

from panup.core.errors import UploadError
from panup.core.ledger import Ledger
from panup.core.pipeline import clean_title, publish_file, publish_task
from panup.drivers.base import DRIVERS


class RecordingDriver:
    """记录调用的假驱动；tree 模拟远端已有结构 {目录: [条目]}。"""

    name = "fake"

    def __init__(self, tree=None, *, upload_error=None):
        self.tree = dict(tree or {})
        self.upload_error = upload_error
        self.calls = []
        self.uploaded = []

    def auth_check(self):
        return {"ok": True}

    def mkdir(self, remote_dir):
        self.calls.append(("mkdir", remote_dir))
        return {"path": remote_dir, "created": True}

    def upload(self, local_path, remote_dir, *, overwrite=True, on_progress=None):
        name = Path(local_path).name
        self.calls.append(("upload", remote_dir, name))
        if self.upload_error:
            raise self.upload_error
        self.uploaded.append(f"{remote_dir.rstrip('/')}/{name}")
        return {"path": f"{remote_dir.rstrip('/')}/{name}", "size": 5,
                "rapid": False}

    def share(self, remote_path, *, pwd=None, period_days=0):
        self.calls.append(("share", remote_path))
        return {"link": "https://e/s/1", "pwd": pwd or "ab12",
                "path": remote_path}

    def list(self, remote_dir):
        self.calls.append(("list", remote_dir))
        return list(self.tree.get(remote_dir, []))


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ledger = Ledger(self.root / "ledger.db")
        # publish_task 会校验盘名已注册；测试用同名桩顶替（实例由 factory 注入）
        DRIVERS["fake"] = RecordingDriver

    def tearDown(self):
        DRIVERS.pop("fake", None)
        self.ledger.close()
        self._tmp.cleanup()

    # ---------- 结构：单文件 / 多文件 / 空目录 ----------

    def test_single_file_lands_in_title_folder(self):
        src = self.root / "报告.pdf"
        src.write_text("x" * 10, encoding="utf-8")
        drv = RecordingDriver()
        r = publish_file(str(src), "fake", "/A", ledger=self.ledger,
                         driver=drv, writer_names=None)
        self.assertEqual(r["path"], "/A/报告")          # 分享指向文件夹
        self.assertEqual(r["kind"], "file")
        self.assertEqual(r["file_count"], 1)
        self.assertEqual(drv.uploaded, ["/A/报告/报告.pdf"])  # 不裸放
        self.assertEqual([c for c in drv.calls if c[0] == "share"][0][1],
                         "/A/报告")

    def test_folder_keeps_two_level_subdirs(self):
        pkg = self.root / "素材包"
        (pkg / "素材" / "视频").mkdir(parents=True)
        (pkg / "封面.png").write_text("a", encoding="utf-8")
        (pkg / "素材" / "说明.txt").write_text("b", encoding="utf-8")
        (pkg / "素材" / "视频" / "片段.mp4").write_text("c", encoding="utf-8")

        drv = RecordingDriver()
        r = publish_file(str(pkg), "fake", "/A", ledger=self.ledger,
                         driver=drv)
        self.assertEqual(r["kind"], "folder")
        self.assertEqual(r["file_count"], 3)
        self.assertEqual(sorted(drv.uploaded), sorted([
            "/A/素材包/封面.png",
            "/A/素材包/素材/说明.txt",
            "/A/素材包/素材/视频/片段.mp4",
        ]))
        # 每级目录都被显式创建（夸克需要逐级建）
        mkdirs = [c[1] for c in drv.calls if c[0] == "mkdir"]
        self.assertIn("/A/素材包/素材", mkdirs)
        self.assertIn("/A/素材包/素材/视频", mkdirs)
        self.assertEqual([c for c in drv.calls if c[0] == "share"][0][1],
                         "/A/素材包")

    def test_empty_subdir_skipped(self):
        pkg = self.root / "包"
        (pkg / "空目录").mkdir(parents=True)
        (pkg / "a.txt").write_text("a", encoding="utf-8")
        drv = RecordingDriver()
        r = publish_file(str(pkg), "fake", "/A", ledger=self.ledger,
                         driver=drv)
        self.assertEqual(r["file_count"], 1)
        self.assertEqual(drv.uploaded, ["/A/包/a.txt"])

    def test_folder_without_files_rejected(self):
        pkg = self.root / "空包"
        (pkg / "只有目录").mkdir(parents=True)
        with self.assertRaises(UploadError) as ctx:
            publish_file(str(pkg), "fake", "/A", ledger=self.ledger,
                         driver=RecordingDriver())
        self.assertEqual(ctx.exception.code, "PUP-105")

    # ---------- 标题 ----------

    def test_illegal_title_chars_replaced(self):
        self.assertEqual(clean_title('a/b\\c:d*e?f"g<h>i|j'), "a_b_c_d_e_f_g_h_i_j")

    def test_title_falls_back_to_name_when_blank(self):
        src = self.root / "原文件名.txt"
        src.write_text("x", encoding="utf-8")
        drv = RecordingDriver()
        r = publish_file(str(src), "fake", "/A", ledger=self.ledger,
                         driver=drv)
        self.assertEqual(r["title"], "原文件名")
        # 显式传全空白 → 仍退回文件名
        r2 = publish_task(str(src), [{"pan": "fake", "remote_dir": "/A"}],
                          ledger=self.ledger, title="   ",
                          driver_factory=lambda pan: RecordingDriver())
        self.assertEqual(r2["title"], "原文件名")

    def test_title_dot_only_is_sanitized(self):
        self.assertEqual(clean_title("...", ""), "未命名")
        self.assertEqual(clean_title(" .. ", "兜底"), "兜底")

    # ---------- 同名冲突 / 重传跳过 ----------

    def test_same_title_conflict_errors(self):
        src = self.root / "a.txt"
        src.write_text("hello", encoding="utf-8")
        drv = RecordingDriver(tree={
            "/A": [{"name": "主题", "path": "/A/主题", "isdir": True}],
        })
        r = publish_task(str(src), [{"pan": "fake", "remote_dir": "/A"}],
                         ledger=self.ledger, title="主题",
                         driver_factory=lambda pan: drv)
        # 任务层按盘捕获异常 → 记入 failed，不抛出
        self.assertEqual(r["items"], [])
        self.assertEqual(len(r["failed"]), 1)
        self.assertEqual(r["failed"][0]["code"], "PAN-name-conflict")
        self.assertIn("同名文件夹", r["failed"][0]["msg"])
        self.assertEqual(drv.uploaded, [])   # 冲突时一个文件都没传
        # 冲突是预检查，不写台账（否则会进「待修」并被 force 重传合并）
        self.assertEqual(self.ledger.recent(), [])

    def test_force_skips_existing_same_size_file(self):
        pkg = self.root / "包"
        pkg.mkdir()
        (pkg / "a.txt").write_text("12345", encoding="utf-8")   # 5 字节，远端已有
        (pkg / "b.txt").write_text("67890", encoding="utf-8")   # 远端没有

        drv = RecordingDriver(tree={
            "/A": [{"name": "包", "path": "/A/包", "isdir": True}],
            "/A/包": [{"name": "a.txt", "path": "/A/包/a.txt",
                       "size": 5, "isdir": False}],
        })
        r = publish_task(str(pkg), [{"pan": "fake", "remote_dir": "/A"}],
                         ledger=self.ledger, title="包", force=True,
                         driver_factory=lambda pan: drv)
        self.assertEqual(r["failed"], [])
        item = r["items"][0]
        self.assertEqual(item["skipped"], 1)
        self.assertEqual(item["uploaded"], 1)
        self.assertEqual(drv.uploaded, ["/A/包/b.txt"])

    def test_force_reuploads_changed_size_file(self):
        pkg = self.root / "包"
        pkg.mkdir()
        (pkg / "a.txt").write_text("1234567", encoding="utf-8")  # 7 字节
        drv = RecordingDriver(tree={
            "/A": [{"name": "包", "path": "/A/包", "isdir": True}],
            "/A/包": [{"name": "a.txt", "path": "/A/包/a.txt",
                       "size": 5, "isdir": False}],
        })
        publish_task(str(pkg), [{"pan": "fake", "remote_dir": "/A"}],
                     ledger=self.ledger, title="包", force=True,
                     driver_factory=lambda pan: drv)
        self.assertEqual(drv.uploaded, ["/A/包/a.txt"])

    # ---------- 台账 ----------

    def test_ledger_records_resource_shape(self):
        pkg = self.root / "包"
        pkg.mkdir()
        (pkg / "a.txt").write_text("a", encoding="utf-8")
        (pkg / "b.txt").write_text("b", encoding="utf-8")
        publish_task(str(pkg), [{"pan": "fake", "remote_dir": "/A"}],
                     ledger=self.ledger, title="包", date_dir=True,
                     driver_factory=lambda pan: RecordingDriver())
        row = self.ledger.recent()[0]
        self.assertEqual(row["kind"], "folder")
        self.assertEqual(row["file_count"], 2)
        self.assertTrue(row["remote_path"].endswith("/包"))
        self.assertRegex(row["remote_path"], r"^/A/\d{2}/\d{2}/\d{2}/包$")
        task = self.ledger.tasks()[0]
        self.assertEqual(task["kind"], "folder")
        self.assertEqual(task["file_count"], 2)

    def test_folder_hash_stable_across_paths(self):
        """同一份内容换个目录，file_hash 不变（去重键只依赖相对路径与大小）。"""
        a = self.root / "一"
        b = self.root / "二"
        for d in (a, b):
            d.mkdir()
            (d / "x.txt").write_text("same", encoding="utf-8")
        r1 = publish_file(str(a), "fake", "/A", ledger=self.ledger,
                          driver=RecordingDriver())
        r2 = publish_file(str(b), "fake", "/A", ledger=self.ledger,
                          driver=RecordingDriver())
        self.assertEqual(r1["file_hash"], r2["file_hash"])


if __name__ == "__main__":
    unittest.main()
