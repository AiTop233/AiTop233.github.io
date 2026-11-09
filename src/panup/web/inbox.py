"""浏览器上传的字节 → inbox 里的「资源」（I-018）。

浏览器一次可以给很多东西：一个文件夹（含子目录）、几个文件夹、一堆散文件，
或者混着来。这里负责两件事：

一、**落盘**：按浏览器给的真实相对路径在 `data/inbox/<批次>/` 下还原目录树，
   每一段都清洗（去掉 `\\ / : * ? " < > |` 与控制字符、丢掉 `..`），所以
   「路径穿越」不可能发生；落完之后台账里的 `local_path` 是持久路径，失败项
   才能一键重传。

二、**分组**：一个资源 = 网盘上一个以标题命名的文件夹 = 飞书一节（D-005）。
   分组规则（D-007）：
   - 顶层是目录 → 该目录就是一个资源，标题缺省用目录名；
   - 顶层是散文件 → 只选了一个就就地当资源（标题缺省用文件名去扩展名）；
     选了多个就装进一个以标题命名的容器目录，合成一个资源（I-018 A3）；
   - 顺序按浏览器给出的先后（拖进来的顺序），散文件组合并到它首次出现的位置。

只做文件系统搬运与命名，不认识网盘、不写台账——那是 pipeline 的事。
"""

from __future__ import annotations

import os
import re
import shutil
import uuid
from pathlib import Path

_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def clean_seg(seg) -> str:
    """清洗单个路径段：非法字符换成 `_`，去掉首尾空白与结尾的点。"""
    text = _ILLEGAL.sub("_", str(seg or "")).strip().strip(".").strip()
    return "" if text in {"", ".", ".."} else text


def clean_rel(rel, fallback: str = "") -> str:
    """把浏览器给的相对路径清洗成安全的 `a/b/c.ext`（逐段清洗，空段丢弃）。"""
    raw = str(rel or "").replace("\\", "/")
    parts = [clean_seg(seg) for seg in raw.split("/")]
    parts = [seg for seg in parts if seg]
    if not parts:
        parts = [clean_seg(fallback) or "upload.bin"]
    return "/".join(parts)


def ingest(items, root) -> list[dict]:
    """把浏览器给的文件写进 `root`，按相对路径还原目录。

    items：`[(filename, binary_stream, relpath)]`，relpath 是浏览器里的相对路径
    （拖文件夹时形如 `剧A/第1集.mp4`）；为空则退回 filename。
    返回 `[{abs, rel, size}]`，rel 是相对 root 的路径。
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    saved: list[dict] = []
    used: set[str] = set()
    for filename, stream, rel in items:
        r = clean_rel(rel, filename)
        if r in used:                      # 同名同路径（重复选择）→ 加序号，不互相覆盖
            stem, dot, ext = r.rpartition(".")
            base = stem if dot else r
            n = 2
            while f"{base}-{n}{dot}{ext}" in used:
                n += 1
            r = f"{base}-{n}{dot}{ext}"
        used.add(r)
        dest = root / r
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with dest.open("wb") as f:
                shutil.copyfileobj(stream, f, 1024 * 1024)
        except OSError as e:               # 路径过长 / 无权限 / 磁盘满
            raise OSError(f"写入 inbox 失败: {e}") from e
        saved.append({"abs": str(dest), "rel": r, "size": dest.stat().st_size})
    return saved


def _moved(path: str, dest_dir: Path) -> str:
    """把散文件挪进容器目录（同名时加序号），返回新绝对路径。"""
    dest = dest_dir / Path(path).name
    n = 2
    while dest.exists():
        dest = dest_dir / f"{Path(path).stem}-{n}{Path(path).suffix}"
        n += 1
    shutil.move(path, dest)
    return str(dest)


def group_resources(saved, *, root=None, loose_title: str | None = None) -> list[dict]:
    """把落盘结果分成资源列表：`[{path, kind, title, file_count, size}]`。

    `title` 是**缺省标题**（目录名 / 文件名去扩展名），调用方可用表单标题覆盖；
    `path` 交给 `publish_task`——目录表示文件夹资源，文件表示单文件资源。
    """
    root = Path(root) if root else (
        Path(os.path.commonpath([s["abs"] for s in saved])) if saved else Path("."))

    dirs: dict[str, list[dict]] = {}
    loose: list[dict] = []
    order: list[tuple[str, str | None]] = []
    for item in saved:
        parts = item["rel"].split("/")
        if len(parts) > 1:
            top = parts[0]
            if top not in dirs:
                dirs[top] = []
                order.append(("dir", top))
            dirs[top].append(item)
        else:
            if not loose:
                order.append(("loose", None))
            loose.append(item)

    out: list[dict] = []
    for kind, top in order:
        if kind == "dir":
            files = dirs[top]
            out.append({"path": str(root / top), "kind": "folder",
                        "title": top, "file_count": len(files),
                        "size": sum(f["size"] for f in files)})
            continue
        if len(loose) == 1:
            only = loose[0]
            name = Path(only["abs"]).name
            out.append({"path": only["abs"], "kind": "file",
                        "title": name.rsplit(".", 1)[0] or name,
                        "file_count": 1, "size": only["size"]})
            continue
        # 多个散文件 → 一个以标题命名的容器目录，合成一个资源
        first = Path(loose[0]["abs"]).name
        base = clean_seg(loose_title) or (
            f"{first.rsplit('.', 1)[0] or first} 等{len(loose)}个")
        name = base
        n = 2
        while (root / name).exists():       # 别和已有的顶层目录撞名
            name = f"{base}-{n}"
            n += 1
        box = root / name
        box.mkdir(parents=True, exist_ok=True)
        for item in loose:
            item["abs"] = _moved(item["abs"], box)
        out.append({"path": str(box), "kind": "folder", "title": name,
                    "file_count": len(loose),
                    "size": sum(item["size"] for item in loose)})
    return out


def new_batch_dir(inbox_root) -> Path:
    """批次目录：`data/inbox/<时间戳>-<随机>`，一次提交一个，便于整体排查/清理。"""
    from datetime import datetime

    path = Path(inbox_root) / (
        f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}")
    path.mkdir(parents=True, exist_ok=True)
    return path
