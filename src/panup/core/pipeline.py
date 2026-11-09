"""上传管道 —— 任务层（多盘编排）→ 单盘上传 → 写文档 → 台账（BACKEND.md §4）。

D-004：一个文件可同时传多个网盘。`publish_task` 逐盘跑单盘管道，各盘独立成败
（某盘失败不阻断其他盘），全部跑完后**只写一次**文档（只含成功的盘）。
`publish_file` 是只有一个 target 的特例，供 watcher 与既有调用方使用。

幂等键 (local_path, file_hash, pan, remote_path)：该盘已有 success 记录 → 跳过并
复用已有链接（force=True 覆盖）。writer 失败不翻转台账状态（PRD F3：链接已在台账）。
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime
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


def _run_writers(writer_names, task, log) -> list[dict]:
    """逐个写入端追加任务（一节）；失败记录结果但不上抛（PRD F3）。"""
    results = []
    for name in writer_names or []:
        try:
            summary = get_writer(name).append_task(task)
            results.append({"writer": name, "ok": True, "detail": summary})
            log("writer.appended", writer=name)
        except ProjectError as e:
            results.append({"writer": name, "ok": False, "error": str(e)})
            log("writer.failed", writer=name, code=e.code, msg=e.msg)
    return results


def _new_group_id() -> str:
    """任务号：时间戳 + 随机后缀，同一任务的多盘记录共享（BACKEND §3）。"""
    return f"{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"


def _prepare_source(local_path) -> tuple[Path, str, int, str]:
    src = Path(local_path)
    if not src.is_file():
        raise UploadError(f"本地文件不存在: {local_path}",
                          hint="检查路径是否写对（Windows 下注意反斜杠转义）")
    return src, str(src.resolve()), src.stat().st_size, file_hash_of(src)


def _publish_one(src, local_path_str, size, fh, pan, remote_dir, *, ledger,
                 driver, force, date_dir, period_days, pwd, group_id, title,
                 on_progress, log) -> dict:
    """单盘上传（最小事务单元）：去重 → 建目录 → 上传 → 分享 → 台账。"""
    effective_dir = date_subdir(remote_dir, _today()) if date_dir else remote_dir
    remote_path = f"{str(effective_dir).rstrip('/')}/{src.name}"

    if not force:
        hit = ledger.find_success(local_path=local_path_str, file_hash=fh,
                                  pan=pan, remote_path=remote_path)
        if hit:
            log("watch.dedup_skipped", pan=pan, file=local_path_str)
            return {"dedup": True, "link": hit["link"],
                    "pwd": hit.get("pwd") or "", "path": hit["remote_path"],
                    "pan": pan, "record_id": hit["id"], "rapid": False}

    drv = driver if driver is not None else get_driver(pan)
    record_id = ledger.record_start(local_path=local_path_str, file_hash=fh,
                                    size=size, pan=pan, remote_path=remote_path,
                                    group_id=group_id, title=title)
    try:
        log("upload.start", pan=pan, file=local_path_str)
        drv.mkdir(effective_dir)
        up = drv.upload(local_path_str, effective_dir, on_progress=on_progress)
        sh = drv.share(up["path"], pwd=pwd, period_days=period_days)
        ledger.record_success(record_id, sh["link"], sh.get("pwd") or "")
        log("upload.success", pan=pan, file=local_path_str, link=sh["link"])
    except ProjectError as e:
        ledger.record_failed(record_id, e.code)
        log("upload.failed", pan=pan, file=local_path_str, code=e.code, msg=e.msg)
        raise
    return {"dedup": False, "link": sh["link"], "pwd": sh.get("pwd") or "",
            "path": up["path"], "pan": pan, "record_id": record_id,
            "rapid": up.get("rapid", False)}


def _task_of(src, title, items) -> dict:
    """把成功项聚成 Writer 契约的 task（只含成功的盘，按传入顺序）。"""
    return {"title": title, "filename": src.name,
            "date": f"{_today():%y%m%d}",
            "items": [{"pan": i["pan"], "link": i["link"],
                       "pwd": i.get("pwd") or ""} for i in items]}


def _check_targets(targets) -> list[dict]:
    if not targets:
        raise UploadError("没有指定目标网盘",
                          hint="至少给一个「网盘 + 目录」（CLI: --pan 盘名:目录）")
    out = []
    seen = set()
    for t in targets:
        pan = str(t.get("pan") or "").strip()
        if not pan:
            raise UploadError("目标网盘缺少盘名", hint="写成「盘名:目录」或加 --pan")
        if pan not in DRIVERS:
            known = "、".join(sorted(DRIVERS)) or "无"
            raise UploadError(f"未注册的网盘: {pan}", hint=f"可选: {known}")
        if pan in seen:
            raise UploadError(f"同一网盘重复指定: {pan}",
                              hint="每个网盘只写一次，改它的目录即可")
        seen.add(pan)
        out.append({"pan": pan, "remote_dir": str(t.get("remote_dir") or "")})
    return out


def publish_task(local_path, targets, *, ledger: Ledger, title=None,
                 driver_factory=None, force: bool = False, date_dir: bool = False,
                 period_days: int = 0, pwd: str | None = None,
                 writer_names=None, on_progress=None, log=None) -> dict:
    """多盘上传任务（D-004）：各盘独立成败，全部跑完后只写一次文档。

    返回 {group_id, title, items, failed, writers}；items 只含成功的盘，
    failed 里是 {pan, code, msg, hint}。
    """
    log = log or (lambda *a, **k: None)
    _check_writer_names(writer_names)
    src, local_path_str, size, fh = _prepare_source(local_path)
    targets = _check_targets(targets)

    group_id = _new_group_id()
    task_title = (title or "").strip() or src.name.rsplit(".", 1)[0] or src.name
    log("task.started", group_id=group_id, file=local_path_str,
        pans=[t["pan"] for t in targets])

    items, failed = [], []
    for t in targets:
        pan, remote_dir = t["pan"], t["remote_dir"]
        driver = driver_factory(pan) if driver_factory else None
        try:
            items.append(_publish_one(
                src, local_path_str, size, fh, pan, remote_dir, ledger=ledger,
                driver=driver, force=force, date_dir=date_dir,
                period_days=period_days, pwd=pwd, group_id=group_id,
                title=task_title, on_progress=on_progress, log=log))
        except ProjectError as e:
            failed.append({"pan": pan, "code": e.code, "msg": e.msg,
                           "hint": e.hint or ""})

    fresh = [i for i in items if not i.get("dedup")]
    writers = []
    if fresh:
        writers = _run_writers(writer_names, _task_of(src, task_title, fresh), log)
    log("task.finished", group_id=group_id, ok=len(items), failed=len(failed))
    return {"group_id": group_id, "title": task_title, "items": items,
            "failed": failed, "writers": writers}


def publish_file(local_path, pan: str, remote_dir: str, *, ledger: Ledger,
                 driver: Driver | None = None, force: bool = False,
                 date_dir: bool = False, period_days: int = 0,
                 pwd: str | None = None, writer_names=None,
                 on_progress=None, log=None) -> dict:
    """单盘特例（watcher 与既有调用方）：语义等同只有一个 target 的任务。"""
    log = log or (lambda *a, **k: None)
    _check_writer_names(writer_names)
    src, local_path_str, size, fh = _prepare_source(local_path)
    group_id = _new_group_id()
    title = src.name.rsplit(".", 1)[0] or src.name

    item = _publish_one(src, local_path_str, size, fh, pan, remote_dir,
                        ledger=ledger, driver=driver, force=force,
                        date_dir=date_dir, period_days=period_days, pwd=pwd,
                        group_id=group_id, title=title, on_progress=on_progress,
                        log=log)
    writers = _run_writers(writer_names, _task_of(src, title, [item]), log) \
        if not item.get("dedup") else []
    return {**item, "writers": writers, "group_id": group_id, "title": title,
            "file_hash": fh, "size": size}
