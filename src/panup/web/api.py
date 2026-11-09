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
POST /api/upload             手动上传（multipart：file + pans + title + date_dir + doc
                             + sync）→ 默认 202 {job_id} 交后台跑；sync=1 同步返回结果
GET  /api/jobs/{id}          上传进度（阶段 / 各盘进度 / 是否已写飞书 / 时间线）
GET  /api/uploads            记录：按任务聚合（status=failed 时给扁平「待修」列表）
POST /api/uploads/{id}/retry 单条失败记录重传（只重跑该「文件 × 网盘」）

文件落点：浏览器上传的字节流先落到 data/inbox/<时间戳-随机>/<原文件名>，
再把该路径交给管道——台账里的 local_path 因此是持久路径，失败项才能一键重传。
"""

from __future__ import annotations

import shutil
import threading
import uuid
from datetime import datetime
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


def _safe_filename(name: str) -> str:
    """只取最后一段并去掉危险字符，避免表单文件名里的路径穿越。"""
    base = Path(str(name or "").replace("\\", "/")).name
    base = base.replace("\x00", "").strip()
    if not base or base in {".", ".."}:
        return "upload.bin"
    return base


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

    def _run_job(job_id, src, targets, title, writer_names, date_dir):
        """后台线程跑一次上传任务：进度写 job，事实写台账。"""
        ledger = make_ledger()
        try:
            result = run_task(str(src), targets, ledger=ledger, title=title,
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

    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...), pans: str = Form(""),
                     title: str = Form(""), date_dir: str = Form("0"),
                     doc: str = Form(""), sync: str = Form("0")):
        if not file.filename:
            return _envelope(400, "PUP-401", "没有收到文件",
                             "重新选一个文件再点上传")
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

        dest_dir = inbox / f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / _safe_filename(file.filename)
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f, 1024 * 1024)

        if _truthy(sync):
            ledger = make_ledger()
            try:
                return run_task(str(dest), resolved, ledger=ledger,
                                title=(title or "").strip() or None,
                                writer_names=writer_names,
                                date_dir=_truthy(date_dir))
            finally:
                ledger.close()

        job_id = jobs.create(filename=dest.name, title=(title or "").strip(),
                             pans=[t["pan"] for t in resolved],
                             size=dest.stat().st_size,
                             writer=writer_names[0] if writer_names else None)
        threading.Thread(
            target=_run_job,
            args=(job_id, dest, resolved, (title or "").strip() or None,
                  writer_names, _truthy(date_dir)),
            name=f"panup-job-{job_id}", daemon=True).start()
        return JSONResponse(status_code=202, content={
            "job_id": job_id, "status": "running",
            "title": (title or "").strip(), "filename": dest.name})

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            return _envelope(404, "PUP-404", f"任务不存在: {job_id}",
                             "进度只保留最近 50 个任务；结果看「记录」页")
        return job

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
                         "检查表单字段：file / pans / title / date_dir / doc / sync")

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
