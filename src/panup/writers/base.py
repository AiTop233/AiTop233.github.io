"""Writer 基类与注册表 —— 文档写入端（飞书等）。

新增写入目标 = 本目录新增一个文件并用 @register 登记（AC-02：只增不改）。
契约方法：auth_check / append_task；实现只抛 ProjectError 子类。
writer 失败不阻塞上传本身（PRD F3：链接已在台账），由调用方逐个捕获。

D-004 起一次上传任务只写**一节**：一个文件可同时传多个网盘，节内按盘排行，
只列成功的盘。单盘调用方用 append_record 兼容包装，语义等同单 item 任务。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

from panup.core.errors import ProjectError


class Writer(ABC):
    """文档写入端契约。"""

    name: str = ""

    @abstractmethod
    def auth_check(self) -> dict:
        """凭证可用性检查；失效抛 AuthError。"""

    @abstractmethod
    def append_task(self, task: dict) -> dict:
        """按 PRD F3 固定更新规则向目标文档写入**一节**（版式由实现决定）。

        task = {
            "title":    标题名（人指定优先，缺省为文件名去扩展名）,
            "filename": 原文件名,
            "date":     "YYMMDD",
            "items":    [{"pan": 盘名, "link": …, "pwd": …}],  # 只含成功的网盘，按注册顺序
        }
        返回写入摘要（如块 id）。
        """

    def append_record(self, record: dict) -> dict:
        """兼容包装：单盘 record → 单 item 任务（旧调用方与既有测试用）。"""
        filename = record.get("filename") or ""
        task = {
            "title": record.get("title") or Path(filename).stem or filename,
            "filename": filename,
            "date": record.get("date") or f"{date.today():%y%m%d}",
            "items": [{"pan": record.get("pan"),
                       "link": record.get("link") or "",
                       "pwd": record.get("pwd") or ""}],
        }
        return self.append_task(task)


WRITERS: dict[str, type[Writer]] = {}


def register(cls: type[Writer]) -> type[Writer]:
    if not cls.name:
        raise ProjectError(f"写入端 {cls.__name__} 缺少 name")
    if cls.name in WRITERS:
        raise ProjectError(f"写入端重复注册: {cls.name}")
    WRITERS[cls.name] = cls
    return cls


def get_writer(name: str, **kwargs) -> Writer:
    cls = WRITERS.get(name)
    if cls is None:
        known = "、".join(sorted(WRITERS)) or "无"
        raise ProjectError(f"未注册的写入端: {name}", hint=f"可选: {known}")
    return cls(**kwargs)
