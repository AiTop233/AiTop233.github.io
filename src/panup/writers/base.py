"""Writer 基类与注册表 —— 文档写入端（飞书等）。

新增写入目标 = 本目录新增一个文件并用 @register 登记（AC-02：只增不改）。
契约方法：auth_check / append_record；实现只抛 ProjectError 子类。
writer 失败不阻塞上传本身（PRD F3：链接已在台账），由调用方逐个捕获。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from panup.core.errors import ProjectError


class Writer(ABC):
    """文档写入端契约。"""

    name: str = ""

    @abstractmethod
    def auth_check(self) -> dict:
        """凭证可用性检查；失效抛 AuthError。"""

    @abstractmethod
    def append_record(self, record: dict) -> dict:
        """按 PRD F3 固定更新规则向目标文档写入一节记录（版式由实现决定）。

        record 至少含 filename / link / pwd / pan；返回写入摘要（如块 id 列表）。
        """


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
