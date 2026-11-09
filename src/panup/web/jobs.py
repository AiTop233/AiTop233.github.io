"""上传任务进度板（内存态）—— Web 轮询用，见 BACKEND §2「进度事件」。

一次上传 = 一个 job：`POST /api/upload` 先把字节流落进 `data/inbox/`，建 job，
再把管道丢到后台线程跑；管道通过 `progress` 回调把「扫描 / 各盘上传 / 分享 /
写文档 / 完成或失败」写进 job。前端 `GET /api/jobs/{id}` 每 0.5 秒取一次，
据此画「现在是在传网盘，还是在写飞书」。

只放内存：进程重启即丢，最终事实以台账（uploads 表）为准；超过 keep 个旧任务
自动淘汰（本机单人使用，够用）。
"""

from __future__ import annotations

import copy
import threading
import uuid
from datetime import datetime

MAX_JOBS = 50

# 单盘行（每个网盘一条）
_TERMINAL = {"done", "skipped", "failed"}
_PAN_STAGES = {"checking", "mkdir", "uploading", "sharing", "done", "skipped",
               "failed"}


def _stamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _clock() -> str:
    return f"{datetime.now():%H:%M:%S}"


def _pan_row(total: int, size: int = 0) -> dict:
    return {"stage": "waiting", "done": 0, "total": total,
            "bytes_done": 0, "bytes_total": size, "file": "",
            "file_index": 0, "link": None, "pwd": None, "path": None,
            "error": None}


def _note(job: dict, text: str, *, pan=None, writer=None, key=None) -> None:
    steps = job["steps"]
    if key and steps and steps[-1].get("key") == key:
        return
    step = {"at": _clock(), "pan": pan, "writer": writer, "text": text}
    if key:
        step["key"] = key
    steps.append(step)
    del steps[:-40]


def _apply(job: dict, ev: dict) -> None:
    """把一条进度事件并进 job（事件形状见 BACKEND §2）。"""
    stage = ev.get("stage")
    pan = ev.get("pan")
    writer = ev.get("writer")

    if stage == "scanning":
        job["scanned"] = True
        job["kind"] = ev.get("kind") or job["kind"]
        job["file_count"] = int(ev.get("file_count") or job["file_count"])
        job["size"] = int(ev.get("size") or job["size"])
        job["title"] = ev.get("title") or job["title"]
        for name in ev.get("pans") or []:
            job["pans"].setdefault(name, _pan_row(job["file_count"], job["size"]))
        for row in job["pans"].values():
            row["total"] = job["file_count"]
            row["bytes_total"] = job["size"]
        kind = "文件夹" if job["kind"] == "folder" else "文件"
        _note(job, f"开始处理「{job['title']}」：{kind}，"
                   f"{job['file_count']} 个文件", key="scan")
    elif pan and stage in _PAN_STAGES:
        row = job["pans"].setdefault(pan, _pan_row(job["file_count"], job["size"]))
        for key in ("file", "file_index", "bytes_done", "bytes_total", "link",
                    "pwd", "path"):
            if ev.get(key) is not None:
                row[key] = ev[key]
        row["stage"] = stage
        if stage == "failed":
            row["error"] = ev.get("msg") or ev.get("code") or "上传失败"
        if stage in _TERMINAL:
            row["done"] = row["total"]
            row["bytes_done"] = max(row["bytes_total"] or 0, row["bytes_done"] or 0)
        _note_pan(job, pan, stage, ev, row)
    elif writer and stage:
        job["writer"] = job.get("writer") or {"name": writer, "error": None}
        job["writer"]["name"] = writer
        job["writer"]["stage"] = stage
        if stage == "writing":
            _note(job, "开始写入文档", writer=writer, key=f"w-{writer}")
        elif stage == "done":
            _note(job, "文档已写入", writer=writer, key=f"w-{writer}")
        elif stage == "failed":
            job["writer"]["error"] = ev.get("msg") or ev.get("code") or "写入失败"
            _note(job, f"写入失败 —— {job['writer']['error']}", writer=writer,
                  key=f"w-{writer}")
    elif stage == "finished":
        job["stage"] = "finished"
    _recompute(job)


def _note_pan(job: dict, pan: str, stage: str, ev: dict, row: dict) -> None:
    """单盘阶段变化写进时间线；同一文件的高频字节事件不写（由进度条体现）。"""
    if stage == "checking":
        _note(job, "检查是否已有同名文件夹", pan=pan, key=f"{pan}-check")
    elif stage == "mkdir":
        _note(job, "建好资源文件夹", pan=pan, key=f"{pan}-mkdir")
    elif stage == "uploading":
        key = f"{pan}-up-{row.get('file_index')}"
        text = f"上传第 {row.get('file_index')}/{row.get('total')} 个文件"
        if row.get("file"):
            text += f"：{row['file']}"
        _note(job, text, pan=pan, key=key)
    elif stage == "sharing":
        _note(job, "文件传完，正在创建分享链接", pan=pan, key=f"{pan}-share")
    elif stage == "done":
        _note(job, f"完成 {ev.get('link') or ''}".strip(), pan=pan,
              key=f"{pan}-done")
    elif stage == "skipped":
        _note(job, "已有相同记录，直接复用链接", pan=pan, key=f"{pan}-dedup")
    elif stage == "failed":
        _note(job, f"失败 —— {row.get('error') or ''}", pan=pan,
              key=f"{pan}-failed")


def _recompute(job: dict) -> None:
    """由各盘/写入端状态推出整体阶段（queued / uploading / writing / finalizing）。"""
    if job["status"] != "running":
        return
    if not job.get("scanned"):
        job["stage"] = "queued"
        return
    if any(r["stage"] not in _TERMINAL for r in job["pans"].values()):
        job["stage"] = "uploading"
    elif job.get("writer") and job["writer"]["stage"] in ("pending", "writing"):
        job["stage"] = "writing"
    else:
        job["stage"] = "finalizing"


class JobStore:
    """线程安全的任务进度板（管道在后台线程写，HTTP 线程读快照）。"""

    def __init__(self, keep: int = MAX_JOBS):
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._order: list[str] = []
        self._keep = max(1, int(keep))

    def create(self, *, filename: str = "", title: str = "", pans=(),
               kind: str = "file", file_count: int = 1, size: int = 0,
               writer: str | None = None) -> str:
        job_id = f"j-{uuid.uuid4().hex[:8]}"
        now = _stamp()
        job = {
            "id": job_id, "status": "running", "stage": "queued",
            "filename": filename, "title": title, "kind": kind,
            "file_count": int(file_count or 1), "size": int(size or 0),
            "pans": {p: _pan_row(int(file_count or 1), int(size or 0))
                     for p in pans},
            "writer": {"name": writer, "stage": "pending", "error": None}
                      if writer else None,
            "steps": [], "result": None, "error": None,
            "scanned": False, "created_at": now, "updated_at": now,
        }
        with self._lock:
            self._jobs[job_id] = job
            self._order.append(job_id)
            while len(self._order) > self._keep:
                self._jobs.pop(self._order.pop(0), None)
        return job_id

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            view = copy.deepcopy(job)
        for step in view["steps"]:
            step.pop("key", None)
        return view

    def event(self, job_id: str, ev: dict) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            _apply(job, ev or {})
            job["updated_at"] = _stamp()

    def finish(self, job_id: str, result: dict) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job["result"] = result
            job["status"] = "done"
            job["stage"] = "finished"
            # 全部命中已有记录时管道不跑写入端：别让「飞书」停在「等待中」
            if job.get("writer") and job["writer"]["stage"] in ("pending", "writing"):
                job["writer"]["stage"] = "skipped"
            job["updated_at"] = _stamp()

    def fail(self, job_id: str, code: str, msg: str, hint: str = "") -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job["status"] = "failed"
            job["stage"] = "failed"
            job["error"] = {"code": code, "msg": msg, "hint": hint}
            _note(job, f"任务失败 —— {msg}", key="failed")
            job["updated_at"] = _stamp()
