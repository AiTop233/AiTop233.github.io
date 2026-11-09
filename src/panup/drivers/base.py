"""Driver 基类与注册表 —— 语义对齐 alist 的 Driver 接口，裁剪为本项目所需子集。

新增网盘 = 本目录新增驱动文件并用 @register 登记（AC-02：只增不改）。
契约方法：auth_check / mkdir / upload / share / list；publish 为基类默认编排。
所有实现只抛 ProjectError 子类；上游响应解析留在驱动内部（AC-03）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from panup.core.errors import ProjectError, UploadError


class Driver(ABC):
    """网盘驱动契约。"""

    name: str = ""

    @abstractmethod
    def auth_check(self) -> dict:
        """校验登录态，返回 {"ok", "account", ...}；失效抛 AuthError。"""

    @abstractmethod
    def mkdir(self, remote_dir: str) -> dict:
        """建目录（自动创建父目录），已存在视为成功：{"path", "created"}。"""

    @abstractmethod
    def upload(self, local_path, remote_dir: str, *, overwrite: bool = True,
               on_progress: Callable[[int, int], None] | None = None) -> dict:
        """上传文件到目录：{"path", "size", "rapid", ...}；秒传命中不传字节。"""

    @abstractmethod
    def share(self, remote_path: str, *, pwd: str | None = None,
              period_days: int = 0) -> dict:
        """创建分享链接：{"link", "url", "pwd", "shareid", ...}。"""

    @abstractmethod
    def list(self, remote_dir: str) -> list[dict]:
        """列目录：[{"fs_id", "name", "path", "size", "isdir", "md5"}]。"""

    def delete(self, remote_paths, *, to_trash: bool = True) -> dict:
        """服务端删除一批路径，返回 {"deleted": [...], "missing": [...],
        "failed": [{path, code, msg}]}。

        - 默认进回收站（`to_trash=True`），彻底删除要显式传 False——误删不可逆
        - `missing` 是「远端本来就没有」的路径：幂等语义，调用方当成功处理，
          免得删到一半重跑就红
        - 单条失败不中断整批，调用方按 `failed` 逐条展示

        默认实现直接报「不支持删除」——老驱动与测试桩不必跟着改。签名与 I-027
        的文件页（批量删改名）保持一致，两处合并时语义对齐、不留两套删除。
        """
        raise UploadError(
            f"{self.name or '该网盘'}驱动不支持删除",
            code="PUP-422",
            hint="目前只有百度与夸克支持远端删除；别的盘请到网页端手工删")

    def publish(self, local_path, remote_dir: str, *, pwd: str | None = None,
                period_days: int = 0, overwrite: bool = True,
                on_progress: Callable[[int, int], None] | None = None) -> dict:
        """mkdir + upload + share 一步到位，返回分享信息与远端路径。"""
        self.mkdir(remote_dir)
        up = self.upload(local_path, remote_dir, overwrite=overwrite,
                         on_progress=on_progress)
        sh = self.share(up["path"], pwd=pwd, period_days=period_days)
        return {**sh, "path": up["path"], "size": up["size"],
                "rapid": up.get("rapid", False)}


DRIVERS: dict[str, type[Driver]] = {}


def register(cls: type[Driver]) -> type[Driver]:
    """注册驱动类；缺 name 或同名重复注册视为编程错误。"""
    if not cls.name:
        raise ProjectError(f"驱动 {cls.__name__} 缺少 name")
    if cls.name in DRIVERS:
        raise ProjectError(f"驱动重复注册: {cls.name}")
    DRIVERS[cls.name] = cls
    return cls


def get_driver(name: str, **kwargs) -> Driver:
    """按名取驱动实例；未知网盘报错并列出可选值。"""
    cls = DRIVERS.get(name)
    if cls is None:
        known = "、".join(sorted(DRIVERS)) or "无"
        raise ProjectError(f"未注册的网盘: {name}", hint=f"可选: {known}")
    return cls(**kwargs)
