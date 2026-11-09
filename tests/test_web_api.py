"""I-007 A1：Web 服务契约测试（打桩 core，FastAPI TestClient）。

覆盖：页面壳路由、/api/status 三灯透传、错误信封 {code, msg, hint}、
未知路由信封、静态资源、绑定回环（真实 uvicorn 起服 + 非回环口拒连）。
"""

import json
import socket
import threading
import time
import unittest
import urllib.request
from pathlib import Path

import support  # noqa: F401  把 src 加入 sys.path

from fastapi.testclient import TestClient

from panup.core.errors import AuthError, ConfigError, WriterError
from panup.web.api import create_app, resolve_bind, serve

LIGHTS = {
    "baidu": {"ok": True, "detail": {"account": "a"}},
    "quark": {"ok": False,
              "error": {"code": "PAN-quark-401", "msg": "cookie 失效",
                        "hint": "重新登录并导出 cookie"}},
    "feishu": {"ok": True, "detail": {"doc": "doctest"}},
}


class _OkDriver:
    name = "stub-ok"

    def auth_check(self):
        return {"account": "ok@x"}


class _BadDriver:
    name = "stub-bad"

    def auth_check(self):
        raise AuthError("登录态失效", code="PAN-bad-401", hint="重新登录")


class _OkWriter:
    name = "stub-w"

    def auth_check(self):
        return {"ok": True}


class WebApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(status_provider=lambda: LIGHTS))

    def test_index_returns_page_shell(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])
        for marker in ("上传", "记录", "监控", "设置", "statusbar", "baidu"):
            self.assertIn(marker, r.text)

    def test_status_passthrough_lights(self):
        r = self.client.get("/api/status")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["baidu"]["ok"])
        self.assertFalse(body["quark"]["ok"])
        self.assertEqual(body["quark"]["error"]["code"], "PAN-quark-401")

    def test_default_provider_is_check_all(self):
        from panup.core.pipeline import check_all

        app = create_app()
        self.assertIs(app.state.status_provider, check_all)

    def test_auth_error_maps_to_502_envelope(self):
        def bad():
            raise AuthError("cookie 失效", code="PAN-baidu--6", hint="重新导出")

        r = TestClient(create_app(status_provider=bad)).get("/api/status")
        self.assertEqual(r.status_code, 502)
        body = r.json()
        self.assertEqual(body["code"], "PAN-baidu--6")
        self.assertIn("重新导出", body["hint"])

    def test_other_project_error_maps_to_500_envelope(self):
        def bad():
            raise WriterError("写入失败", code="PAN-feishu-x", hint="检查文档权限")

        r = TestClient(create_app(status_provider=bad)).get("/api/status")
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.json()["code"], "PAN-feishu-x")

    def test_unexpected_error_maps_to_pup500_envelope(self):
        def bad():
            raise RuntimeError("boom")

        client = TestClient(create_app(status_provider=bad),
                            raise_server_exceptions=False)
        r = client.get("/api/status")
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.json()["code"], "PUP-500")

    def test_unknown_api_route_returns_envelope(self):
        r = self.client.get("/api/nope")
        self.assertEqual(r.status_code, 404)
        body = r.json()
        self.assertEqual(body["code"], "PUP-404")
        self.assertTrue(body["hint"])

    def test_static_assets_served(self):
        for path in ("/static/styles.css", "/static/app.js"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)

    def test_resolve_bind_locks_loopback(self):
        self.assertEqual(resolve_bind({}), ("127.0.0.1", 8256))
        self.assertEqual(resolve_bind({"web": {"port": 9000}}),
                         ("127.0.0.1", 9000))
        # 配置试图改 host 也改不动（只监听回环是红线）
        self.assertEqual(
            resolve_bind({"web": {"host": "0.0.0.0", "port": 9001}}),
            ("127.0.0.1", 9001))


class CheckAllTests(unittest.TestCase):
    def test_reports_each_entry_and_survives_failure(self):
        from panup.core.pipeline import check_all

        out = check_all(
            driver_registry={"stub-bad": _BadDriver, "stub-ok": _OkDriver},
            writer_registry={"stub-w": _OkWriter},
        )
        self.assertTrue(out["stub-ok"]["ok"])
        self.assertFalse(out["stub-bad"]["ok"])
        err = out["stub-bad"]["error"]
        self.assertEqual(err["code"], "PAN-bad-401")
        self.assertIn("重新登录", err["hint"])
        self.assertTrue(out["stub-w"]["ok"])

    def test_output_sorted_by_name(self):
        from panup.core.pipeline import check_all

        out = check_all(driver_registry={"b": _OkDriver, "a": _OkDriver},
                        writer_registry={})
        self.assertEqual(list(out), ["a", "b"])


class ServeTests(unittest.TestCase):
    def test_serve_reads_config_and_runs_uvicorn(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.toml"
            cfg.write_text("[web]\nport = 9001\n", encoding="utf-8")
            calls = []
            serve(config=str(cfg),
                  run=lambda app, *, host, port: calls.append((host, port)))
        self.assertEqual(calls, [("127.0.0.1", 9001)])

    def test_serve_missing_config_raises_config_error(self):
        with self.assertRaises(ConfigError):
            serve(config="不存在的配置.toml", run=lambda *a, **k: None)


def _start_server(app):
    """真实起 uvicorn（临时端口），返回 (server, thread, port)。"""
    import uvicorn

    cfg = uvicorn.Config(app, host="127.0.0.1", port=0,
                         log_level="error", lifespan="off")
    server = uvicorn.Server(cfg)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("uvicorn 启动超时")
        if not thread.is_alive():
            raise RuntimeError("uvicorn 线程提前退出")
        time.sleep(0.05)
    host, port = server.servers[0].sockets[0].getsockname()[:2]
    return server, thread, int(port)


def _lan_ip():
    """本机局域网出口地址（不发探测包）；拿不到返回 None。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("223.5.5.5", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


class LoopbackServerTests(unittest.TestCase):
    """A1 的「只监听回环」：回环可达 + 非回环口拒连（真实 uvicorn）。"""

    def test_binds_loopback_only(self):
        server, thread, port = _start_server(
            create_app(status_provider=lambda: LIGHTS))
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/status", timeout=5) as r:
                self.assertEqual(r.status, 200)
                body = json.loads(r.read().decode("utf-8"))
            self.assertFalse(body["quark"]["ok"])

            lan = _lan_ip()
            if not lan or lan == "127.0.0.1":
                self.skipTest("无独立局域网地址，跳过外口拒连检查")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            try:
                # 只绑回环 → 局域网口连不上（返回码非 0）
                self.assertNotEqual(sock.connect_ex((lan, port)), 0)
            finally:
                sock.close()
        finally:
            server.should_exit = True
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
