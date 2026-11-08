"""上传管道 —— 去重 → 建目录 → 上传 → 分享 → 写入文档 → 台账（BACKEND.md §4）。

幂等键 (local_path, file_hash, pan, remote_path)：已有 success 记录 → 跳过并返回
已有链接（force=True 覆盖）。writer 失败不翻转台账状态（PRD F3：链接已在台账）。
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from panup.core.errors import ProjectError, UploadError, WriterError
from panup.core.ledger import Ledger
from panup.drivers.base import DRIVERS, Driver, get_driver
from panup.writers.base import WRITERS, get_writer


def _today() -> date:
    """日期子目录的取数点（测试可覆写）。"""
    return date.today()


def date_subdir(base: str, d: date) -> str:
    """远端目录追加「年/月/日」三级子目录（两位年份，人的归档习惯如 26/11/09）。"""
    base = str(base or "/").rstrip("/")
    sub = f"{d:%y/%m/%d}"
    return f"{base}/{sub}" if base else f"/{sub}"


def file_hash_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_writer_names(writer_names) -> None:
    for name in writer_names or []:
        if name not in WRITERS:
            raise WriterError(
                f"文档写入端未注册: {name}", code="PUP-201",
                hint="先实现并注册该写入端（I-005 后 feishu 可用），或去掉 --doc 参数")


def _run_writers(writer_names, record, log) -> list[dict]:
    """逐个写入端追加记录；失败记录结果但不上抛（PRD F3）。"""
    results = []
    for name in writer_names or []:
        try:
            summary = get_writer(name).append_record(record)
            results.append({"writer": name, "ok": True, "detail": summary})
            log("writer.appended", writer=name)
        except ProjectError as e:
            results.append({"writer": name, "ok": False, "error": str(e)})
            log("writer.failed", writer=name, code=e.code, msg=e.msg)
    return results


def publish_file(local_path, pan: str, remote_dir: str, *, ledger: Ledger,
                 driver: Driver | None = None, force: bool = False,
                 date_dir: bool = False, period_days: int = 0,
                 pwd: str | None = None, writer_names=None,
                 on_progress=None, log=None) -> dict:
    """完整管道：返回 {link, pwd, path, dedup, pan, record_id, ...}。"""
    log = log or (lambda *a, **k: None)
    _check_writer_names(writer_names)

    src = Path(local_path)
    if not src.is_file():
        raise UploadError(f"本地文件不存在: {local_path}",
                          hint="检查路径是否写对（Windows 下注意反斜杠转义）")
    local_path_str = str(src.resolve())
    size = src.stat().st_size
    fh = file_hash_of(src)

    effective_dir = date_subdir(remote_dir, _today()) if date_dir else remote_dir
    remote_path = f"{str(effective_dir).rstrip('/')}/{src.name}"

    if not force:
        hit = ledger.find_success(local_path=local_path_str, file_hash=fh,
                                  pan=pan, remote_path=remote_path)
        if hit:
            log("watch.dedup_skipped", pan=pan, file=local_path_str)
            return {"dedup": True, "link": hit["link"], "pwd": hit.get("pwd") or "",
                    "path": hit["remote_path"], "pan": pan,
                    "record_id": hit["id"], "file_hash": fh, "size": size}

    drv = driver if driver is not None else get_driver(pan)
    record_id = ledger.record_start(local_path=local_path_str, file_hash=fh,
                                    size=size, pan=pan, remote_path=remote_path)
    try:
        log("upload.start", pan=pan, file=local_path_str)
        drv.mkdir(effective_dir)
        up = drv.upload(local_path_str, effective_dir, on_progress=on_progress)
        sh = drv.share(up["path"], pwd=pwd, period_days=period_days)
        ledger.record_success(record_id, sh["link"], sh.get("pwd") or "")
        log("upload.success", pan=pan, file=local_path_str, link=sh["link"])
        record = {
            "record_id": record_id, "pan": pan,
            "local_path": local_path_str, "remote_path": up["path"],
            "filename": src.name, "size": size,
            "link": sh["link"], "pwd": sh.get("pwd") or "",
            "period_days": period_days,
        }
        writers = _run_writers(writer_names, record, log)
        return {"dedup": False, "link": sh["link"], "pwd": sh.get("pwd") or "",
                "path": up["path"], "pan": pan, "record_id": record_id,
                "file_hash": fh, "size": size, "rapid": up.get("rapid", False),
                "writers": writers}
    except ProjectError as e:
        ledger.record_failed(record_id, e.code)
        log("upload.failed", pan=pan, file=local_path_str, code=e.code, msg=e.msg)
        raise


def _check_one(cls) -> dict:
    """单通道体检：构造实例并 auth_check；失败转为 {ok: False, error}。"""
    try:
        return {"ok": True, "detail": cls().auth_check()}
    except ProjectError as e:
        return {"ok": False,
                "error": {"code": e.code, "msg": e.msg, "hint": e.hint or ""}}


def check_all(*, driver_registry=None, writer_registry=None) -> dict:
    """三灯体检：全部网盘驱动与写入端逐个 auth_check，单项失败不中断整体。

    返回 {<name>: {"ok": True, "detail": …} | {"ok": False, "error": {code, msg, hint}}}
    （BACKEND.md §2 core 公开函数，Web /api/status 与未来入口共用）。
    注册表可注入（测试打桩点）；缺省用全局注册表（先 import panup.drivers 触发注册）。
    """
    drv = DRIVERS if driver_registry is None else driver_registry
    wri = WRITERS if writer_registry is None else writer_registry
    out: dict = {}
    for name, cls in sorted(drv.items()):
        out[name] = _check_one(cls)
    for name, cls in sorted(wri.items()):
        out[name] = _check_one(cls)
    return out
