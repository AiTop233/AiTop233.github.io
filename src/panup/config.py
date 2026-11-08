"""配置与密钥加载 —— config.toml（TOML）+ 环境变量 + secrets/ 文件。

来源优先级（docs/BACKEND.md §9）：环境变量 > secrets/ 文件。
config.toml 与 secrets/ 不入库；模板见仓库根 config.example.toml。
启动校验（ensure_config）缺项时一次性列出全部缺失清单（AC-06 的配置面）。
"""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

from panup.core.errors import ConfigError

DEFAULT_CONFIG_NAME = "config.toml"


def default_config_path() -> Path:
    """配置文件位置：环境变量 PANUP_CONFIG > 当前目录 config.toml。"""
    env = os.environ.get("PANUP_CONFIG")
    if env:
        return Path(env)
    return Path.cwd() / DEFAULT_CONFIG_NAME


def load_config(path=None) -> dict:
    """读取 TOML 配置。文件缺失 / 坏格式都抛 ConfigError，hint 给恢复指引。"""
    p = Path(path) if path is not None else default_config_path()
    if not p.is_file():
        raise ConfigError(
            f"配置文件不存在: {p}",
            code="PUP-100",
            hint="把仓库根的 config.example.toml 复制为 config.toml，按注释填写",
        )
    try:
        with open(p, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(
            f"配置文件不是合法 TOML: {p}（{e}）",
            code="PUP-101",
            hint="对照 config.example.toml 检查改动处",
        ) from e


def missing_required(cfg: dict, required) -> list[str]:
    """返回缺失必填项的点路径清单（空值视为缺失），一次性给全。"""
    missing = []
    for dotted in required:
        node: object = cfg
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                node = None
                break
            node = node[part]
        if node is None or node == "":
            missing.append(dotted)
    return missing


def ensure_config(cfg: dict, required) -> dict:
    """校验必填项；缺项一次性全部列出（不逐个报），通过时原样返回 cfg。"""
    missing = missing_required(cfg, required)
    if missing:
        raise ConfigError(
            "配置缺少必填项: " + "、".join(missing),
            code="PUP-102",
            hint="补齐这些项后再运行；各含义见 config.example.toml 注释",
        )
    return cfg


def resolve_credential(env_name: str, file_path=None) -> str | None:
    """取一个凭据：环境变量优先，其次 secrets/ 文件文本；都没有返回 None。"""
    env = os.environ.get(env_name)
    if env:
        return env
    if file_path is not None:
        p = Path(file_path)
        if p.is_file():
            return p.read_text(encoding="utf-8").strip()
    return None


def load_json_file(path) -> dict | list:
    """读 JSON 文件（如 secrets/feishu_app.json）；缺失 / 坏 JSON 抛 ConfigError。"""
    p = Path(path)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(
            f"文件不存在: {p}", code="PUP-103", hint="按 BACKEND.md §9 放置该文件"
        ) from e
    except json.JSONDecodeError as e:
        raise ConfigError(
            f"文件不是合法 JSON: {p}（{e}）", code="PUP-103"
        ) from e
