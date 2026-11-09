"""本地管理台服务端 —— FastAPI REST + SPA 静态托管（BACKEND.md §2，F4）。

只调 core 公开函数（AC-01）：本文件的业务调用是 pipeline.publish_task /
check_all 与 ledger 读取；错误统一 {code, msg, hint} 信封（HTTP 4xx/5xx），
前端直接展示 msg + hint。
只监听 127.0.0.1（本机单人使用，无账号体系）：host 硬编码回环，配置只放端口。

REST：
GET  /                       页面壳（SPA index.html）
GET  /static/*               静态资源（styles.css / app.js，免构建）
GET  /api/status             三灯体检（百度 / 夸克 / 飞书登录态）
GET  /api/options            上传表单的选项：各盘默认目录（远端目录不能留空）
POST /api/upload             手动上传（multipart：files 多值 + paths 相对路径一一对应
                             + pans + title + date_dir + doc + sync）→ 默认 202
                             {batch_id, resources}；sync=1 同步跑完返回结果
GET  /api/jobs/{id}          单个资源的进度（阶段 / 各盘进度 / 是否已写飞书 / 时间线）
GET  /api/batches/{id}       整批快照（多个资源时一次取回，前端只轮询这一个）
GET  /api/uploads            记录：按任务聚合（status=failed 时给扁平「待修」列表）
POST /api/uploads/{id}/retry 单条失败记录重传（只重跑该「文件 × 网盘」）

文件落点：浏览器上传的字节流先落到 data/inbox/<批次>/<相对路径>（保留拖进来的
目录结构），再把「每个顶层目录 / 一组散文件」当成一个资源交给管道——台账里的
local_path 因此是持久路径，失败项才能一键重传。

并发（D-007）：**全局单并发**。一次只跑一个资源，批量内串行排队，第二个提交会
等前一个跑完。这不是偷懒——驱动本身单线程顺序传、台账是无 WAL 的单文件 SQLite、
网盘分享接口最容易被限频，三者都不适合并行；串行同时消掉了同名文件夹的竞态。
"""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from panup.core.errors import AuthError, ConfigError, ProjectError, UploadError
from panup.core.ledger import Ledger
from panup.core.pipeline import check_all, publish_task
from panup.drivers.base import DRIVERS
from panup.web.inbox import group_resources, ingest, new_batch_dir
from panup.web.jobs import JobStore
from panup.writers.base import WRITERS

STATIC_DIR = Path(__file__).resolve().parent / "static"
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = _PROJECT_ROOT / "data" / "ledger.db"
DEFAULT_INBOX = _PROJECT_ROOT / "data" / "inbox"
DEFAULT_PORT = 8256
_LOOPBACK = "127.0.0.1"


def resolve_bind(cfg: dict) -> tuple[str, int]:
    """服务绑定地址：host 恒为回环（红线），端口取 [web].port（默认 8256）。"""
    port = int((cfg.get("web") or {}).get("port") or DEFAULT_PORT)
    return _LOOPBACK, port


def _envelope(status: int, code: str, msg: str, hint: str = "") -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"code": code, "msg": msg, "hint": hint})


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "on", "yes"}


def _parse_pans(raw: str) -> list[dict]:
    """解析表单里的 pans：JSON 数组 [{"pan": "baidu", "dir": "/来自电脑"}]。"""
    import json

    text = (raw or "").strip()
    if not text:
        raise UploadError("没有选择目标网盘",
                          hint="至少勾选一个网盘；接口字段 pans 传 JSON 数组")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise UploadError(
            "pans 不是合法 JSON",
            hint='形如 [{"pan":"baidu","dir":"/来自电脑"},{"pan":"quark","dir":"/来自电脑"}]')
    if not isinstance(data, list) or not data:
        raise UploadError("pans 必须是非空数组",
                          hint="每项 {pan, dir}；只勾一个盘就是一个元素的数组")
    out = []
    for item in data:
        if not isinstance(item, dict) or not str(item.get("pan") or "").strip():
            raise UploadError("pans 里有缺盘名的项",
                              hint="每项写成 {pan: 盘名, dir: 远端目录}")
        out.append({"pan": str(item["pan"]).strip(),
                    "dir": str(item.get("dir") or "").strip()})
    return out


def _parse_paths(raw: str, names: list[str]) -> list[str]:
    """解析表单里的 paths：与 files 一一对应的相对路径（拖文件夹时带子目录）。

    为空 → 退回各文件的 filename（等价于「选了几个散文件」）；个数对不上 → 直接
    报错，不猜谁对应谁（猜错会把文件落到别的资源里）。
    """
    import json

    text = (raw or "").strip()
    if not text or text == "[]":
        return list(names)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise UploadError("paths 不是合法 JSON", code="PUP-411",
                          hint='形如 ["剧A/第1集.mp4","剧A/第2集.mp4"]')
    if not isinstance(data, list) or len(data) != len(names):
        got = len(data) if isinstance(data, list) else "?"
        raise UploadError(
            f"paths 与文件数不一致（{got} 个路径 vs {len(names)} 个文件）",
            code="PUP-411",
            hint="每个文件给一个相对路径，顺序与 files 一一对应")
    return [str(x or names[i]) for i, x in enumerate(data)]


def _default_dir(cfg: dict, pan: str) -> str:
    """表单没填目录时取配置默认值；没有则抛 ConfigError（带恢复指引）。"""
    default = (cfg.get("pan") or {}).get(f"{pan}_default_dir")
    if not default:
        raise ConfigError(
            f"{pan} 没填目录，配置里也没有它的默认目录",
            code="PUP-104",
            hint=f"在表单里填远端目录，或在 config.toml [pan] 里填 "
                 f"{pan}_default_dir")
    return str(default)


def _configured_dir(cfg: dict, pan: str) -> str:
    """配置里的默认目录（可能为空）——给表单回填用，不抛错。"""
    return str((cfg.get("pan") or {}).get(f"{pan}_default_dir") or "")


def create_app(status_provider=None, *, task_runner=None, ledger_factory=None,
               config_loader=None, inbox_dir=None, job_store=None) -> FastAPI:
    """构建应用；下列参数都是测试打桩点，缺省走真实实现。"""
    import panup.drivers  # noqa: F401 —— 触发驱动注册（AC-02）
    import panup.writers  # noqa: F401 —— 触发写入端注册

    app = FastAPI(title="panup", docs_url=None, redoc_url=None,
                  openapi_url=None)
    provider = status_provider or check_all
    run_task = task_runner or publish_task
    make_ledger = ledger_factory or (lambda: Ledger(DEFAULT_DB))
    inbox = Path(inbox_dir or DEFAULT_INBOX)
    jobs = job_store or JobStore()
    upload_lock = threading.Lock()      # 全局单并发（D-007）：一次只跑一个资源

    def load_cfg() -> dict:
        if config_loader is not None:
            return config_loader()
        from panup.config import load_config

        return load_config()

    app.state.status_provider = provider
    app.state.task_runner = run_task
    app.state.ledger_factory = make_ledger
    app.state.jobs = jobs

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/status")
    def status():
        return provider()

    @app.get("/api/options")
    def options():
        """上传表单的选项：各盘默认目录由配置给（表单不留空，日期层另加）。"""
        cfg = load_cfg()
        return {"pans": [{"name": name,
                          "default_dir": _configured_dir(cfg, name)}
                         for name in DRIVERS]}

    def _run_one(job_id, path, targets, title, writer_names, date_dir):
        """跑一个资源：进度写 job，事实写台账；失败只记在这一条上，不影响同批其他资源。"""
        ledger = make_ledger()
        try:
            result = run_task(str(path), targets, ledger=ledger, title=title,
                              writer_names=writer_names, date_dir=date_dir,
                              progress=lambda ev: jobs.event(job_id, ev))
            jobs.finish(job_id, result)
        except ProjectError as e:
            jobs.fail(job_id, e.code, e.msg, e.hint or "")
        except Exception as e:  # noqa: BLE001 —— 后台线程不能把异常丢给人
            jobs.fail(job_id, "PUP-500", f"服务内部错误: {e}",
                      "查看 logs/ 下的 JSON 日志定位；反复出现请带日志反馈")
        finally:
            ledger.close()

    def _run_batch(plans, targets, writer_names, date_dir):
        """批量串行队列（D-007）：全局上传锁内一次跑一个资源。

        锁是**资源粒度**的：同一时刻只有一个上传任务在动网盘/写台账，第二个人提交
        的批次会卡在锁外等（页面显示「排队中」），而不是两份请求同时去建同名目录、
        同时写 SQLite、同时触发分享接口。
        """
        for plan in plans:
            with upload_lock:
                _run_one(plan["job_id"], plan["path"], targets, plan["title"],
                         writer_names, date_dir)

    @app.post("/api/upload")
    def upload(files: list[UploadFile] = File(None),
               file: UploadFile = File(None), paths: str = Form("[]"),
               pans: str = Form(""), title: str = Form(""),
               date_dir: str = Form("0"), doc: str = Form(""),
               sync: str = Form("0")):
        """接收一批文件后立刻返回：落盘与分组是同步的（快），上传是后台串行的。

        写成同步函数（不是 async）：`ingest` 是磁盘 IO，会阻塞事件循环；交给
        FastAPI 的线程池跑，页面的其它请求（状态灯、进度轮询）才不会被大文件夹堵住。
        """
        uploads = [u for u in (files or []) if u and u.filename]
        if file is not None and file.filename:      # 旧字段 file 仍然收
            uploads.append(file)
        if not uploads:
            return _envelope(400, "PUP-401", "没有收到文件",
                             "重新选文件或文件夹再点上传")
        targets = _parse_pans(pans)
        cfg = load_cfg()
        resolved = [{"pan": t["pan"],
                     "remote_dir": t["dir"] or _default_dir(cfg, t["pan"])}
                    for t in targets]

        writer_names = [doc.strip()] if doc and doc.strip() else []
        unknown = [w for w in writer_names if w not in WRITERS]
        if unknown:
            return _envelope(400, "PUP-403",
                             f"未启用的文档写入端: {'、'.join(unknown)}",
                             "doc 目前只支持 feishu；不写文档就留空")

        names = [u.filename for u in uploads]
        rels = _parse_paths(paths, names)
        batch_dir = new_batch_dir(inbox)
        try:
            saved = ingest([(u.filename, u.file, rel)
                            for u, rel in zip(uploads, rels)], batch_dir)
        except OSError as e:
            return _envelope(
                400, "PUP-413", f"接收文件失败: {e}",
                "检查磁盘剩余空间；Windows 上目录层级过深（路径超过 260 字符）"
                "也会失败，把文件夹挪到浅一点的位置再传")
        if not saved:
            return _envelope(400, "PUP-414", "没有可上传的内容",
                             "空文件夹不会上传；放文件后再试")

        form_title = (title or "").strip()
        resources = group_resources(saved, root=batch_dir,
                                    loose_title=form_title or None)
        multi = len(resources) > 1
        plans = [{"path": r["path"], "kind": r["kind"], "size": r["size"],
                  "file_count": r["file_count"],
                  # 只有一个资源时表单标题生效；批量时各用各自的名字（前端已禁用）
                  "title": (r["title"] if multi else (form_title or r["title"]))}
                 for r in resources]

        if _truthy(sync):
            results = []
            for plan in plans:
                ledger = make_ledger()
                try:
                    results.append(run_task(
                        plan["path"], resolved, ledger=ledger,
                        title=plan["title"], writer_names=writer_names,
                        date_dir=_truthy(date_dir)))
                finally:
                    ledger.close()
            return {"count": len(results), "resources": results}

        batch_id, job_ids = jobs.create_batch(
            [{"title": p["title"], "kind": p["kind"], "size": p["size"],
              "file_count": p["file_count"], "pans": [t["pan"] for t in resolved],
              "filename": Path(p["path"]).name} for p in plans],
            writer=writer_names[0] if writer_names else None)
        for job_id, plan in zip(job_ids, plans):
            plan["job_id"] = job_id

        threading.Thread(
            target=_run_batch,
            args=(plans, resolved, writer_names, _truthy(date_dir)),
            name=f"panup-batch-{batch_id}", daemon=True).start()
        return JSONResponse(status_code=202, content={
            "batch_id": batch_id, "status": "running", "count": len(plans),
            "resources": [{"job_id": j, "title": p["title"], "kind": p["kind"],
                           "file_count": p["file_count"], "size": p["size"]}
                          for j, p in zip(job_ids, plans)]})

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            return _envelope(404, "PUP-404", f"任务不存在: {job_id}",
                             "进度只保留最近 50 个任务；结果看「记录」页")
        return job

    @app.get("/api/batches/{batch_id}")
    def batch_detail(batch_id: str):
        """整批快照：一次提交里的每个资源各自的状态、进度与结果（I-018）。"""
        batch = jobs.get_batch(batch_id)
        if batch is None:
            return _envelope(404, "PUP-404", f"批次不存在: {batch_id}",
                             "进度只保留最近 50 个任务；结果看「记录」页")
        return batch

    @app.get("/api/uploads")
    def list_uploads(limit: int = 50, status: str | None = None):
        limit = max(1, min(int(limit), 500))
        ledger = make_ledger()
        try:
            if status:
                return {"records": ledger.recent(limit=limit, status=status)}
            return {"tasks": ledger.tasks(limit=limit)}
        finally:
            ledger.close()

    @app.post("/api/uploads/{record_id}/retry")
    def retry_upload(record_id: int):
        ledger = make_ledger()
        try:
            row = ledger.get(record_id)
            if row is None:
                return _envelope(404, "PUP-404", f"记录不存在: {record_id}",
                                 "刷新记录页后再试")
            if row["status"] == "success":
                return {"ok": True, "skipped": True, "record_id": record_id,
                        "message": "这条已经成功，无需重传"}
            src = Path(row["local_path"])
            if not src.exists():
                return _envelope(
                    409, "PUP-409", "原文件已不在，无法重传",
                    f"重新拖一次该文件；原路径: {row['local_path']}")
            remote_dir = row["remote_path"].rsplit("/", 1)[0] or "/"
            result = run_task(str(src),
                              [{"pan": row["pan"], "remote_dir": remote_dir}],
                              ledger=ledger, title=row.get("title") or None,
                              writer_names=[], force=True,
                              group_id=row["group_id"])
        finally:
            ledger.close()

        failed = result.get("failed") or []
        if failed:
            return {"ok": False, "record_id": record_id, "failed": failed}
        items = result.get("items") or []
        return {"ok": True, "record_id": record_id,
                "item": items[0] if items else None,
                "message": "重传成功；飞书文档未追加（避免同一资源出现两节）"}

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request, exc: RequestValidationError):
        return _envelope(400, "PUP-400", "请求参数不合法",
                         "检查表单字段：files / paths / pans / title / "
                         "date_dir / doc / sync")

    @app.exception_handler(ProjectError)
    async def on_project_error(request, exc: ProjectError):
        status = 502 if isinstance(exc, AuthError) else 500
        if isinstance(exc, UploadError):
            status = 400
        return _envelope(status, exc.code, exc.msg, exc.hint or "")

    @app.exception_handler(StarletteHTTPException)
    async def on_http_error(request, exc: StarletteHTTPException):
        return _envelope(exc.status_code, f"PUP-{exc.status_code}",
                         str(exc.detail),
                         "检查请求路径与参数；接口清单见 docs/BACKEND.md §2")

    @app.exception_handler(Exception)
    async def on_unexpected(request, exc: Exception):
        return _envelope(500, "PUP-500", f"服务内部错误: {exc}",
                         "查看 logs/ 下 JSON 日志定位；反复出现请带日志反馈")

    return app


def serve(*, config=None, run=None) -> int:
    """加载配置 → 起服务；run 可注入（测试打桩点），默认 uvicorn.run。"""
    from panup.config import load_config

    cfg = load_config(config)
    host, port = resolve_bind(cfg)

    def _run(app, *, host, port):
        import uvicorn

        uvicorn.run(app, host=host, port=port)

    (run or _run)(create_app(), host=host, port=port)
    return 0
