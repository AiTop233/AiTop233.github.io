"""上传管道 —— 任务层（多盘编排）→ 单盘资源上传 → 写文档 → 台账（BACKEND.md §4）。

D-004：一个文件可同时传多个网盘。`publish_task` 逐盘跑单盘管道，各盘独立成败
（某盘失败不阻断其他盘），全部跑完后**只写一次**文档（只含成功的盘）。
`publish_file` 是只有一个 target 的特例，供 watcher 与既有调用方使用。

D-005（I-017）：一次上传 = 一个**资源**（单文件或文件夹），网盘上落成
`remote_dir/[年/月/日/]标题/` 的资源文件夹，本地相对路径原样镜像；链接指向该
文件夹。同名文件夹已存在 → 报错不合并（force=True 的重传除外：跳过已存在且
大小一致的文件，只补缺的）。

幂等键 (local_path, file_hash, pan, remote_path)：该盘已有 success 记录 → 跳过并
复用已有链接（force=True 覆盖）。writer 失败不翻转台账状态（PRD F3：链接已在台账）。
"""

from __future__ import annotations

import hashlib
import re
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


_ILLEGAL_TITLE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def clean_title(raw, fallback: str = "") -> str:
    r"""标题清洗（D-005）：替换网盘/系统非法字符，去首尾空白与结尾点。

    标题会直接当远端文件夹名，故必须去掉 `/`、`\` 等路径分隔符（防越级）。
    清洗后为空 → 退回 fallback；fallback 也空 → 「未命名」。
    """
    def _norm(text):
        return _ILLEGAL_TITLE.sub("_", str(text or "")).strip().strip(".").strip()

    title = _norm(raw)
    if title:
        return title
    return _norm(fallback) or "未命名"


def _scan_source(local_path) -> dict:
    """把上传对象归一成「资源」：单文件或文件夹。

    返回 {src, kind(file|folder), name, local_path, size, file_hash, files}；
    files 里每项 {abs, rel, size}，rel 是相对资源的路径（单文件即文件名）。
    文件夹按相对路径镜像，空子目录不产生条目（自然跳过）。
    文件夹的 file_hash 由「相对路径 + 大小」清单算出，用于去重而不读全部内容。
    """
    src = Path(local_path)
    if src.is_file():
        size = src.stat().st_size
        return {"src": src, "kind": "file", "name": src.name,
                "local_path": str(src.resolve()), "size": size,
                "file_hash": file_hash_of(src),
                "files": [{"abs": str(src), "rel": src.name, "size": size}]}
    if src.is_dir():
        files = []
        for p in sorted(src.rglob("*")):
            if p.is_file():
                files.append({"abs": str(p),
                              "rel": p.relative_to(src).as_posix(),
                              "size": p.stat().st_size})
        if not files:
            raise UploadError(f"文件夹里没有文件: {local_path}", code="PUP-105",
                              hint="空文件夹（或只有空子目录）不会上传，放文件后重试")
        h = hashlib.sha256()
        for f in sorted(files, key=lambda x: x["rel"]):
            h.update(f"{f['rel']}\t{f['size']}\n".encode("utf-8"))
        return {"src": src, "kind": "folder", "name": src.name,
                "local_path": str(src.resolve()),
                "size": sum(f["size"] for f in files),
                "file_hash": h.hexdigest(), "files": files}
    raise UploadError(f"本地路径不存在: {local_path}",
                      hint="检查路径是否写对（Windows 下注意反斜杠转义）")


def _default_title(res) -> str:
    """未指定标题时的缺省：文件夹用目录名，文件用去扩展名的文件名。"""
    name = res["name"]
    if res["kind"] == "folder":
        return name
    return name.rsplit(".", 1)[0] or name


def _remote_index(drv, remote_dir: str) -> dict[str, int]:
    """递归列出远端目录 → {相对路径: 大小}；目录不存在视为空（重传跳过用）。"""
    out: dict[str, int] = {}
    try:
        items = drv.list(remote_dir)
    except ProjectError:
        return out
    for it in items or []:
        name = it.get("name") or ""
        if not name:
            continue
        if it.get("isdir"):
            sub_path = it.get("path") or f"{str(remote_dir).rstrip('/')}/{name}"
            for rel, size in _remote_index(drv, sub_path).items():
                out[f"{name}/{rel}"] = size
        else:
            out[name] = int(it.get("size") or 0)
    return out


def _existing_child(drv, remote_dir: str, name: str) -> bool:
    """远端目录下是否已有同名条目（文件或文件夹）。

    列目录失败（目录还没建、登录态问题等）一律视为「没有同名」——真正的错误
    会在后面的 mkdir/upload 里抛出，不被这里的预检查吞掉。
    """
    try:
        items = drv.list(remote_dir)
    except ProjectError:
        return False
    return any((it.get("name") == name) for it in items or [])


def _publish_one(res, pan: str, remote_dir: str, *, ledger,
                 driver, force, date_dir, period_days, pwd, group_id, title,
                 on_progress, log) -> dict:
    """单盘上传一个资源：去重 → 同名检查 → 建目录 → 逐文件上传 → 分享文件夹。"""
    base = str(remote_dir or "/")
    effective_dir = date_subdir(base, _today()) if date_dir else base.rstrip("/") or "/"
    resource_dir = f"{effective_dir.rstrip('/')}/{title}"

    if not force:
        hit = ledger.find_success(local_path=res["local_path"],
                                  file_hash=res["file_hash"], pan=pan,
                                  remote_path=resource_dir)
        if hit:
            log("watch.dedup_skipped", pan=pan, file=res["local_path"])
            return {"dedup": True, "link": hit["link"],
                    "pwd": hit.get("pwd") or "", "path": hit["remote_path"],
                    "pan": pan, "record_id": hit["id"], "rapid": False,
                    "kind": res["kind"], "file_count": len(res["files"]),
                    "uploaded": 0, "skipped": 0}

    drv = driver if driver is not None else get_driver(pan)
    # 同名冲突是用户写错标题，属预检查：不写台账，免得进「待修」并被 force 重传合并
    if not force and _existing_child(drv, effective_dir, title):
        raise UploadError(
            f"{pan} 上已存在同名文件夹: {resource_dir}",
            code="PAN-name-conflict",
            hint="换个标题再传（同名资源不合并）；若要补传已有资源，"
                 "用记录页的「重传」或加 --force")
    record_id = ledger.record_start(
        local_path=res["local_path"], file_hash=res["file_hash"],
        size=res["size"], pan=pan, remote_path=resource_dir,
        group_id=group_id, title=title, kind=res["kind"],
        file_count=len(res["files"]))
    try:
        log("upload.start", pan=pan, file=res["local_path"], kind=res["kind"],
            files=len(res["files"]))
        drv.mkdir(effective_dir)
        exists = _existing_child(drv, effective_dir, title)
        skip = _remote_index(drv, resource_dir) if (exists and force) else {}
        drv.mkdir(resource_dir)
        uploaded = skipped = 0
        rapid = False
        for f in res["files"]:
            rel = f["rel"]
            if rel in skip and skip[rel] == f["size"]:
                skipped += 1
                log("file.skipped", pan=pan, file=rel, reason="exists_same_size")
                continue
            parent = f"{resource_dir}/{rel}".rsplit("/", 1)[0]
            if parent != resource_dir:   # 顶层文件已在 resource_dir 里
                drv.mkdir(parent)
            up = drv.upload(f["abs"], parent, on_progress=on_progress)
            rapid = rapid or bool(up.get("rapid"))
            uploaded += 1
        sh = drv.share(resource_dir, pwd=pwd, period_days=period_days)
        ledger.record_success(record_id, sh["link"], sh.get("pwd") or "")
        log("upload.success", pan=pan, file=res["local_path"], link=sh["link"],
            uploaded=uploaded, skipped=skipped)
    except ProjectError as e:
        ledger.record_failed(record_id, e.code)
        log("upload.failed", pan=pan, file=res["local_path"], code=e.code,
            msg=e.msg)
        raise
    except OSError as e:
        # 本地读不了（文件被占用、权限不足、磁盘错误）：不算驱动报错，但同样要
        # 落成 failed，否则台账留一条 pending —— 页面上既看不到也重传不了
        err = UploadError(f"读取本地文件失败: {e}", code="PUP-106",
                          hint="确认文件没被其他程序占用、路径可读；改好后点重传")
        ledger.record_failed(record_id, err.code)
        log("upload.failed", pan=pan, file=res["local_path"], code=err.code,
            msg=err.msg)
        raise err from e
    return {"dedup": False, "link": sh["link"], "pwd": sh.get("pwd") or "",
            "path": resource_dir, "pan": pan, "record_id": record_id,
            "rapid": rapid, "kind": res["kind"],
            "file_count": len(res["files"]), "uploaded": uploaded,
            "skipped": skipped}


def _task_of(res, title, items) -> dict:
    """把成功项聚成 Writer 契约的 task（只含成功的盘，按传入顺序）。"""
    return {"title": title, "filename": res["name"], "kind": res["kind"],
            "file_count": len(res["files"]),
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
                 writer_names=None, on_progress=None, log=None,
                 group_id: str | None = None) -> dict:
    """多盘上传任务（D-004 + D-005）：各盘独立成败，全部跑完后只写一次文档。

    local_path 可以是单个文件，也可以是文件夹（整个文件夹当一次「资源」上传，
    网盘上落成以标题命名的文件夹，内部结构原样保留）。
    返回 {group_id, title, kind, file_count, items, failed, writers}；items 只含
    成功的盘，failed 里是 {pan, code, msg, hint}。
    group_id 可注入：失败项重传时沿用原任务号，让记录归位而不是另起一条任务。
    """
    log = log or (lambda *a, **k: None)
    _check_writer_names(writer_names)
    res = _scan_source(local_path)
    targets = _check_targets(targets)

    group_id = group_id or _new_group_id()
    task_title = clean_title(title, _default_title(res))
    log("task.started", group_id=group_id, file=res["local_path"],
        kind=res["kind"], files=len(res["files"]),
        pans=[t["pan"] for t in targets])

    items, failed = [], []
    for t in targets:
        pan, remote_dir = t["pan"], t["remote_dir"]
        driver = driver_factory(pan) if driver_factory else None
        try:
            items.append(_publish_one(
                res, pan, remote_dir, ledger=ledger, driver=driver, force=force,
                date_dir=date_dir, period_days=period_days, pwd=pwd,
                group_id=group_id, title=task_title,
                on_progress=on_progress, log=log))
        except ProjectError as e:
            failed.append({"pan": pan, "code": e.code, "msg": e.msg,
                           "hint": e.hint or ""})

    fresh = [i for i in items if not i.get("dedup")]
    writers = []
    if fresh:
        writers = _run_writers(writer_names, _task_of(res, task_title, fresh), log)
    log("task.finished", group_id=group_id, ok=len(items), failed=len(failed))
    return {"group_id": group_id, "title": task_title, "kind": res["kind"],
            "file_count": len(res["files"]), "items": items,
            "failed": failed, "writers": writers}


def publish_file(local_path, pan: str, remote_dir: str, *, ledger: Ledger,
                 driver: Driver | None = None, force: bool = False,
                 date_dir: bool = False, period_days: int = 0,
                 pwd: str | None = None, writer_names=None,
                 on_progress=None, log=None) -> dict:
    """单盘特例（watcher 与既有调用方）：语义等同只有一个 target 的任务。"""
    log = log or (lambda *a, **k: None)
    _check_writer_names(writer_names)
    res = _scan_source(local_path)
    group_id = _new_group_id()
    title = clean_title(None, _default_title(res))

    item = _publish_one(res, pan, remote_dir,
                        ledger=ledger, driver=driver, force=force,
                        date_dir=date_dir, period_days=period_days, pwd=pwd,
                        group_id=group_id, title=title, on_progress=on_progress,
                        log=log)
    writers = _run_writers(writer_names, _task_of(res, title, [item]), log) \
        if not item.get("dedup") else []
    return {**item, "writers": writers, "group_id": group_id, "title": title,
            "file_hash": res["file_hash"], "size": res["size"]}


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
