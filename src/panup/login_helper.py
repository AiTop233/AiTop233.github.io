"""登录助手 —— 用本机 Playwright 弹出官方登录窗口，登录后把 cookie 写进 secrets/。

用法（项目根目录）：
    PYTHONPATH=src python -m panup.login_helper baidu   # 弹出百度网盘登录页，扫码
    PYTHONPATH=src python -m panup.login_helper quark   # 弹出夸克网盘登录页，扫码/验证码

流程：弹 Chromium 有头窗口 → 你扫码/登录 → 工具轮询上下文 cookie → 落盘 secrets/ →
脱敏打印摘要后关窗。cookie 值不打印、不进仓库（AC-04 / AC-05）。
落盘格式：百度 = secrets/baidu_cookies.json（{name: value}）；夸克 = secrets/quark_cookie.txt
（浏览器请求头风格 k=v; ...，与 BACKEND.md §9 的密钥清单一致）。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from panup.core.errors import ConfigError, ProjectError

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECRETS_DIR = _PROJECT_ROOT / "secrets"

TARGETS = {
    "baidu": {
        "label": "百度网盘",
        "login_url": (
            "https://pan.baidu.com/v2/?login&tpl=netdisk"
            "&u=https%3A%2F%2Fpan.baidu.com%2Fdisk%2Fmain"
        ),
        # 登录态判定：BDUSS 出现即已登录；STOKEN 通常随之出现
        "cookie_names": ("BDUSS",),
        "domains": (".baidu.com",),
        "outfile": SECRETS_DIR / "baidu_cookies.json",
        "fmt": "json",
    },
    "quark": {
        "label": "夸克网盘",
        "login_url": "https://pan.quark.cn/",
        # 登录态判定：夸克的会话 cookie __pus / __puus
        "cookie_names": ("__puus", "__pus"),
        "domains": (".quark.cn",),
        "outfile": SECRETS_DIR / "quark_cookie.txt",
        "fmt": "text",
    },
}

# BDCLND 是某个分享的临时凭证，残留会让百度分享接口报 -9，落盘前剔除
DROP_COOKIE_NAMES = {"BDCLND"}


def _mask(value: str) -> str:
    return f"{value[:4]}…（共 {len(value)} 字符）"


def _pick_cookies(cookies, domains, names):
    """取目标域下的 cookie，要求 names 全部在场，返回过滤后的列表。"""
    picked = [c for c in cookies
              if any(c["domain"] == d or c["domain"].endswith(d) for d in domains)]
    have = {c["name"] for c in picked}
    missing = [n for n in names if n not in have]
    return picked, missing


def login(target_name: str, timeout_s: int = 300) -> Path:
    target = TARGETS[target_name]
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ConfigError(
            "缺少 playwright 包",
            hint="在本机 Python 里执行: pip install playwright && playwright install chromium",
        ) from None

    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[登录助手] 打开{target['label']}登录窗口（有头 Chromium）…")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(target["login_url"], wait_until="domcontentloaded")
            print(f"[登录助手] 窗口已弹出：请在窗口里扫码/登录{target['label']}。")
            print(f"[登录助手] 我会轮询登录态，最多等 {timeout_s} 秒…")

            deadline = time.time() + timeout_s
            picked: list[dict] = []
            missing: list[str] = list(target["cookie_names"])
            while time.time() < deadline:
                try:
                    picked, missing = _pick_cookies(
                        context.cookies(), target["domains"], target["cookie_names"])
                except Exception:  # 页面跳转瞬间 cookies 可能取不到，下一轮再试
                    pass
                if not missing:
                    break
                time.sleep(1.5)

            if missing:
                raise ProjectError(
                    f"等待登录超时（还差 cookie: {'、'.join(missing)}）",
                    hint="重跑一次登录助手，在窗口里完成扫码/登录后再关窗口",
                )

            # 剔除临时凭证，按落盘格式写 secrets/
            picked = [c for c in picked if c["name"] not in DROP_COOKIE_NAMES]
            jar = {c["name"]: c["value"] for c in picked}
            out: Path = target["outfile"]
            if target["fmt"] == "json":
                out.write_text(json.dumps(jar, ensure_ascii=False, indent=2),
                               encoding="utf-8")
            else:
                out.write_text(
                    "; ".join(f"{c['name']}={c['value']}" for c in picked),
                    encoding="utf-8")
            print(f"[登录助手] 已写入 {out}")
            for c in picked:
                print(f"[登录助手]   {_mask(c['name'])}={_mask(c['value'])}")
            print("[登录助手] 2 秒后关闭窗口…")
            time.sleep(2)
            return out
        finally:
            browser.close()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in TARGETS:
        raise ProjectError(
            f"用法: python -m panup.login_helper <{'|'.join(TARGETS)}>",
            hint="目标网盘写 baidu 或 quark",
        )
    timeout = 300
    if len(argv) > 1 and argv[1].isdigit():
        timeout = int(argv[1])
    login(argv[0], timeout)


if __name__ == "__main__":
    main()
