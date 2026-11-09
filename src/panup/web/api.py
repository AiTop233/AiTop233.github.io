"""本地管理台服务端 —— FastAPI REST + SPA 静态托管（BACKEND.md §2，F4）。

只调 core 公开函数（AC-01）：本文件的唯一业务调用是 pipeline.check_all；
错误统一 {code, msg, hint} 信封（HTTP 4xx/5xx），前端直接展示 msg + hint。
只监听 127.0.0.1（本机单人使用，无账号体系）：host 硬编码回环，配置只放端口。

REST（I-007 骨架：页面壳 + 三灯体检；其余接口在 I-008～I-010 落地）：
GET /                    页面壳（SPA index.html）
GET /static/*            静态资源（styles.css / app.js，免构建）
GET /api/status          三灯体检（百度 / 夸克 / 飞书登录态）
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from panup.core.errors import AuthError, ProjectError
from panup.core.pipeline import check_all

STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_PORT = 8256
_LOOPBACK = "127.0.0.1"


def resolve_bind(cfg: dict) -> tuple[str, int]:
    """服务绑定地址：host 恒为回环（红线），端口取 [web].port（默认 8256）。"""
    port = int((cfg.get("web") or {}).get("port") or DEFAULT_PORT)
    return _LOOPBACK, port


def _envelope(status: int, code: str, msg: str, hint: str = "") -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"code": code, "msg": msg, "hint": hint})


def create_app(status_provider=None) -> FastAPI:
    """构建应用；status_provider 可注入（测试打桩点），默认 core.check_all。"""
    import panup.drivers  # noqa: F401 —— 触发驱动注册（AC-02）
    import panup.writers  # noqa: F401 —— 触发写入端注册

    app = FastAPI(title="panup", docs_url=None, redoc_url=None,
                  openapi_url=None)
    provider = status_provider or check_all
    app.state.status_provider = provider

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/status")
    def status():
        return provider()

    @app.exception_handler(ProjectError)
    async def on_project_error(request, exc: ProjectError):
        status = 502 if isinstance(exc, AuthError) else 500
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
