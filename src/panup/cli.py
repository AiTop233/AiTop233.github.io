"""CLI 入口 —— upload / status / check 子命令（python -m panup ...）。

入口薄壳（AC-01）：业务逻辑全在 core.pipeline；此处只做参数解析、输出与退出码。
失败时输出「发生了什么 + 怎么办」并以非 0 退出（AC-06）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from panup.core.errors import ConfigError, ProjectError
from panup.core.ledger import Ledger
from panup.core.pipeline import publish_task
from panup.writers.base import WRITERS

# 项目根：src/panup/cli.py → parents[2]
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = _PROJECT_ROOT / "data" / "ledger.db"


def build_driver(pan: str):
    """构造网盘驱动（测试打桩点）。"""
    import panup.drivers  # noqa: F401 —— 触发驱动注册（AC-02：新增网盘登记一行）
    from panup.drivers.base import get_driver

    return get_driver(pan)


def _default_dir_for(pan: str) -> str:
    from panup.config import load_config

    cfg = load_config()  # 缺配置文件会抛 ConfigError，含恢复指引
    default = (cfg.get("pan") or {}).get(f"{pan}_default_dir")
    if not default:
        raise ConfigError(
            f"未指定目录，且配置里没有 {pan} 的默认目录",
            code="PUP-104",
            hint=f"命令写成 --pan {pan}:/远端目录，或在 config.toml [pan] 里填 "
                 f"{pan}_default_dir",
        )
    return default


def _parse_targets(pans, fallback_dir=None) -> list[dict]:
    """`--pan 盘名:目录` / `盘名` → [{pan, remote_dir}]（I-016）。

    盘名不带目录时：先看 --dir，再看该盘在 config.toml 的默认目录。
    """
    targets = []
    for raw in pans or []:
        text = str(raw).strip()
        if not text:
            continue
        pan, sep, remote = text.partition(":")
        pan = pan.strip()
        remote = remote.strip()
        if not remote:
            remote = fallback_dir or _default_dir_for(pan)
        targets.append({"pan": pan, "remote_dir": remote})
    if not targets:
        raise ConfigError("没有指定目标网盘", code="PUP-104",
                          hint="至少给一个 --pan，如 --pan 夸克")
    return targets


def cmd_upload(args) -> int:
    doc_names = list(args.doc or [])
    for w in [d for d in doc_names if d not in WRITERS]:
        print(f"提示: 文档写入端 {w} 未启用（后续阶段提供），本次跳过写入")
    doc_names = [w for w in doc_names if w in WRITERS]

    try:
        targets = _parse_targets(args.pan, args.dir)
    except ProjectError as e:
        print(f"上传失败: {e}", file=sys.stderr)
        return 1

    ledger = Ledger(args.db or DEFAULT_DB)
    try:
        result = publish_task(
            args.local_path, targets, ledger=ledger, title=args.title,
            driver_factory=build_driver, force=args.force,
            date_dir=args.date_dir, period_days=args.period_days,
            writer_names=doc_names,
        )
    except ProjectError as e:
        ledger.close()
        print(f"上传失败: {e}", file=sys.stderr)
        return 1
    ledger.close()

    for item in result["items"]:
        if item["dedup"]:
            print(f"{item['pan']} 去重命中，未重新上传"
                  "（同文件同目录已分享过；--force 强制重传）")
        else:
            rapid = "（秒传）" if item.get("rapid") else ""
            print(f"已上传 {item['pan']} {item['path']}{rapid}")
        print(f"  链接: {item['link']}")
        if item.get("pwd"):
            print(f"  提取码: {item['pwd']}")

    for f in result["failed"]:
        print(f"！{f['pan']} 上传失败: {f['msg']}", file=sys.stderr)
        if f.get("hint"):
            print(f"  {f['hint']}", file=sys.stderr)

    for w in result.get("writers") or []:
        if w["ok"]:
            print(f"已写入文档端 {w['writer']}: {w['detail']}")
        else:
            print(f"提示: 文档端 {w['writer']} 写入失败（不影响上传），"
                  f"原因: {w['error']}", file=sys.stderr)
    return 1 if result["failed"] else 0


def cmd_status(args) -> int:
    ledger = Ledger(args.db or DEFAULT_DB)
    try:
        rows = ledger.recent(args.limit)
    finally:
        ledger.close()
    if not rows:
        print("（暂无上传记录）")
        return 0
    for r in rows:
        head = f"#{r['id']} [{r['status']}] {r['pan']} {r['remote_path']}"
        tail = r["link"] or (f"失败 {r['error_code']}" if r["error_code"] else "")
        print(f"{head}  {tail}  {r['updated_at']}")
    return 0


def cmd_check(args) -> int:
    import panup.drivers  # noqa: F401 —— 触发驱动注册
    from panup.drivers.base import DRIVERS

    names = [args.pan] if args.pan else sorted(DRIVERS)
    bad = 0
    for name in names:
        try:
            info = build_driver(name).auth_check()
            account = info.get("account") or "（未知账号）"
            print(f"✓ {name}: 登录态正常（{account}）")
        except ProjectError as e:
            bad += 1
            print(f"✗ {name}: {e}", file=sys.stderr)
    return 1 if bad else 0


def cmd_watch(args) -> int:
    from panup.config import load_config
    from panup.core.log import JsonLogger
    from panup.watcher import Watcher, build_rules

    cfg = load_config()
    watch_cfg = cfg.get("watch") or {}
    rules = build_rules(watch_cfg.get("dirs") or [])
    ledger = Ledger(args.db or DEFAULT_DB)
    log = JsonLogger((cfg.get("log") or {}).get("dir") or "logs", echo=True)
    watcher = Watcher(
        rules, ledger=ledger, driver_factory=build_driver,
        interval=watch_cfg.get("interval_seconds", 5),
        stable=watch_cfg.get("stable_seconds", 10),
        retry_limit=watch_cfg.get("retry_limit", 3),
        lock_dir=_PROJECT_ROOT / "data", log=log,
    )
    print(f"监控中：{len(rules)} 个目录（Ctrl+C 停止；日期子目录默认开启）")
    for r in rules:
        print(f"  {r['local']} → {r['pan']}:{r['remote_dir']}"
              + ("（年/月/日）" if r["date_dir"] else ""))
    try:
        watcher.run_forever()
    except KeyboardInterrupt:
        print("已停止")
    finally:
        ledger.close()
    return 0


def cmd_serve(args) -> int:
    """本地管理台：起 FastAPI 服务（只监听 127.0.0.1，BACKEND.md §2）。"""
    from panup.web.api import serve

    try:
        return serve()
    except ProjectError as e:
        print(str(e), file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="panup", description="网盘中控台（手动 / 自动上传到百度、夸克网盘）")
    sub = p.add_subparsers(dest="cmd", required=True)

    up = sub.add_parser("upload", help="上传文件/目录并返回分享链接")
    up.add_argument("local_path", help="本地文件路径")
    up.add_argument("--pan", required=True, action="append",
                    help="目标网盘，可重复：--pan 夸克 --pan baidu:/远端目录"
                         "（写成「盘名:目录」；只写盘名时用该盘默认目录）")
    up.add_argument("--title", default=None,
                    help="写进文档的小节标题（缺省用文件名，不带扩展名）")
    up.add_argument("--dir", default=None,
                    help="单盘兜底目录：只给一个 --pan 且没写目录时用它")
    up.add_argument("--date-dir", action="store_true",
                    help="目标目录追加「年/月/日」三级子目录（如 /分享/26/11/09）")
    up.add_argument("--force", action="store_true", help="跳过去重，强制重传")
    up.add_argument("--period-days", type=int, default=0,
                    help="分享有效期天数（0=永久，默认永久）")
    up.add_argument("--doc", action="append", default=None,
                    help="写入文档端（可多次，如 --doc feishu）")
    up.add_argument("--db", default=None, help="台账数据库路径（默认 data/ledger.db）")
    up.set_defaults(func=cmd_upload)

    st = sub.add_parser("status", help="查看最近上传记录")
    st.add_argument("--limit", type=int, default=10)
    st.add_argument("--db", default=None)
    st.set_defaults(func=cmd_status)

    ck = sub.add_parser("check", help="网盘登录态体检")
    ck.add_argument("--pan", default=None, help="只查指定网盘（缺省查全部）")
    ck.set_defaults(func=cmd_check)

    wa = sub.add_parser("watch", help="监控配置目录，自动上传（需 config.toml）")
    wa.add_argument("--db", default=None, help="台账数据库路径（默认 data/ledger.db）")
    wa.set_defaults(func=cmd_watch)

    sv = sub.add_parser("serve", help="本地管理台服务（127.0.0.1:8256）")
    sv.set_defaults(func=cmd_serve)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
