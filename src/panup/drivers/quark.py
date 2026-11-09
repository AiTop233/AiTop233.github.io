"""夸克网盘驱动 —— 网页版内部接口（cookie 登录态），纯标准库。

夸克无官方开放平台，接口流程来自两个已公开的成熟来源：
- 上传 / 列目录 / 建目录：alist `drivers/quark_uc`（pre → hash → auth+OSS 分片 PUT → commit → finish）
- 创建分享：社区方案（POST /share → task 轮询 → /share/password 取 share_url 与提取码）
统一走 drive-pc.quark.cn（社区方案与上传实测的主机；alist 用 drive.quark.cn，两者均为网页接口主机）。

会话注意：响应会下发 __puus / __pus 会话 cookie，驱动把它们合并进内存 cookie，
延长登录态；落盘回写 secrets/ 不在本驱动职责内（AC-04 凭据管理见 config）。

接口清单（path 均在 {API} 下，query 恒带 pr=ucpro&fr=pc）
----------------------------------------------------------
GET  /config                登录态校验
GET  /member                账号昵称
GET  /file/sort             列目录（pdir_fid + _page/_size）
POST /file                  建目录（同名冲突报「同名冲突」字样）
POST /file/upload/pre       预上传（task_id/bucket/obj_key/upload_id/upload_url/callback/fid）
POST /file/update/hash      md5+sha1 秒传检查（data.finish=true 即秒传）
POST /file/upload/auth      OSS 签名（分片 PUT 与 commit 各签名一次）
PUT  https://{bucket}.{host}/{obj_key}?partNumber=N&uploadId=...   OSS 分片
POST https://{bucket}.{host}/{obj_key}?uploadId=...                OSS commit（XML）
POST /file/upload/finish    落盘
POST /share                 创建分享（task）
GET  /task                  分享任务轮询
POST /share/password        取 share_url 与提取码
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from panup.core.errors import AuthError, ProjectError, ShareError, UploadError
from panup.drivers.base import Driver, register

API = "https://drive-pc.quark.cn/1/clouddrive"
PR = "ucpro"
FR = "pc"
REFERER = "https://pan.quark.cn"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) quark-cloud-drive/2.5.20 Chrome/100.0.4896.160 "
    "Electron/18.3.5.4-b478491100 Safari/537.36 Channel/pckk_other_ch"
)
OSS_UA = "aliyun-sdk-js/6.6.1 Chrome 98.0.4758.80 on Windows 10 64-bit"

_LIST_PAGE_SIZE = 100
_FALLBACK_PART_SIZE = 10 * 1024 * 1024

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
SECRETS_DIR = _PROJECT_ROOT / "secrets"


def load_default_cookies():
    """登录 cookie 来源（BACKEND.md §9）：环境变量 QUARK_COOKIE > secrets/quark_cookie.txt。"""
    env = os.environ.get("QUARK_COOKIE")
    if env:
        return _parse_cookie_text(env)
    p = SECRETS_DIR / "quark_cookie.txt"
    if p.exists():
        return _parse_cookie_text(p.read_text(encoding="utf-8"))
    return {}


def _parse_cookie_text(text):
    """cookie 文本（BDUSS 式 k=v; ... 或浏览器导出多行）→ dict。"""
    jar = {}
    text = str(text or "").strip()
    if os.path.exists(text):
        text = Path(text).read_text(encoding="utf-8", errors="replace").strip()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "\t" in line and len(line.split("\t")) >= 7:
            if "\t" in line:
                parts = line.split("\t")
                jar[parts[5]] = parts[6]
            continue
        for pair in line.split(";"):
            pair = pair.strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                jar[k.strip()] = v.strip()
    return jar


def _cookie_header(jar):
    return "; ".join(f"{k}={v}" for k, v in jar.items() if k)


def _http_date():
    return time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())


@register
class QuarkDriver(Driver):
    name = "quark"

    def __init__(self, cookies=None, *, ua=DEFAULT_UA, timeout=60, retries=3, log=None):
        if cookies is None:
            cookies = load_default_cookies()
        if isinstance(cookies, str):
            cookies = _parse_cookie_text(cookies)
        self.cookies = dict(cookies or {})
        self.ua = ua
        self.timeout = timeout
        self.retries = retries
        self._log = log or (lambda *_: None)
        self._fid_cache: dict[str, str] = {"/": "0"}

    # -- 传输层（测试打桩点） ------------------------------------------------

    def _request(self, method, url, *, params=None, body=None, headers=None):
        """JSON API 单次调用，返回 (status, headers, text)。测试覆写本方法打桩。"""
        url = f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode(params or {})}"
        hdrs = self._headers(json_body=body is not None)
        hdrs.update(headers or {})
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            text = r.read().decode("utf-8", "replace")
            self._merge_cookies(r.headers)
            return r.status, dict(r.headers.items()), text

    def _request_oss(self, method, url, *, params=None, headers=None, body=None):
        """OSS 直传（PUT 分片 / POST commit），返回 (status, headers, text)。"""
        url = f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode(params or {})}"
        req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return r.status, dict(r.headers.items()), r.read().decode("utf-8", "replace")

    def _headers(self, *, json_body=False):
        h = {
            "User-Agent": self.ua,
            "Referer": REFERER,
            "Accept": "application/json, text/plain, */*",
            "Cookie": _cookie_header(self.cookies),
        }
        if json_body:
            h["Content-Type"] = "application/json;charset=UTF-8"
        return h

    def _merge_cookies(self, resp_headers):
        """把响应下发的 __puus / __pus 会话 cookie 合并进内存 jar（延长登录态）。"""
        for k, v in (resp_headers or {}).items():
            if k.lower() != "set-cookie":
                continue
            for part in v.split(","):
                if "=" in part:
                    name, value = part.strip().split("=", 1)
                    if name in ("__puus", "__pus"):
                        self.cookies[name] = value.split(";")[0]

    def _api(self, method, path, *, err_cls=UploadError, params=None, body=None):
        """调 JSON API 并校验响应信封（status=200 且 code=0）。"""
        url = f"{API}{path}"
        last = None
        for attempt in range(1, self.retries + 1):
            try:
                status, _headers, text = self._request(
                    method, url, params={"pr": PR, "fr": FR, **(params or {})},
                    body=body)
            except urllib.error.HTTPError as e:
                status, text = e.code, e.read().decode("utf-8", "replace")
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = e
                if attempt < self.retries:
                    time.sleep(0.8 * 2 ** (attempt - 1))
                    continue
                raise ProjectError(f"网络请求失败: {e}", code="PAN-quark-net",
                                   retriable=True, hint="检查网络后重试") from e
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                raise UploadError(f"返回非 JSON: {text[:200]}", code="PAN-quark-html",
                                  hint="稍后重试；若持续出现，换网络环境")
            code = payload.get("code")
            message = payload.get("message") or ""
            if status == 200 and code == 0:
                return payload
            if status == 401 or code == 31001:
                raise AuthError(
                    f"夸克登录态失效或无权限（{message or f'status={status} code={code}'}）",
                    code=f"PAN-quark-{code or status}", errno=code,
                    hint="重新登录 pan.quark.cn 并导出 cookie 到 secrets/quark_cookie.txt "
                         "或环境变量 QUARK_COOKIE")
            e = err_cls(
                message or f"夸克接口返回错误 status={status} code={code}",
                code=f"PAN-quark-{code or status}", errno=code,
                hint="查看 message；临时性失败可重试")
            e.retriable = status >= 500
            raise e
        raise ProjectError("重试耗尽", code="PAN-quark-retry", retriable=True)

    def _oss(self, method, url, *, params=None, headers=None, body=None) -> tuple[int, dict]:
        status, headers, _text = self._request_oss(method, url, params=params,
                                                   headers=headers, body=body)
        if status != 200:
            raise UploadError(f"OSS 直传失败 status={status}", code="PAN-quark-oss",
                              retriable=True, hint="网络波动导致的临时失败可重试整个上传")
        return status, headers

    # -- 登录态 ----------------------------------------------------------------

    def auth_check(self):
        if not self.cookies:
            raise AuthError(
                "缺少夸克登录态 cookie", code="PAN-quark-noauth",
                hint="浏览器登录 pan.quark.cn 后，把 cookie 导出到 "
                     "secrets/quark_cookie.txt 或环境变量 QUARK_COOKIE",
            )
        self._api("GET", "/config", err_cls=AuthError)
        member = self._api("GET", "/member", err_cls=AuthError)
        nickname = ((member.get("data") or {}).get("member") or {}).get("nickname")
        return {"ok": True, "account": nickname}

    # -- 目录与文件 ------------------------------------------------------------

    @staticmethod
    def _norm(p):
        p = str(p or "/").replace("\\", "/").strip()
        if ":" in p.split("/")[0]:
            raise ProjectError(
                f"这个看着不像网盘路径: {p}",
                hint="Git Bash 下用 MSYS_NO_PATHCONV=1，或把目录写成 //开头",
            )
        if not p.startswith("/"):
            p = "/" + p
        while "//" in p:
            p = p.replace("//", "/")
        return p.rstrip("/") or "/"

    def _list_fid(self, fid):
        """列一个目录（自动翻页），返回原始条目。"""
        items = []
        page = 1
        while True:
            p = self._api("GET", "/file/sort", params={
                "pdir_fid": fid, "_page": page, "_size": _LIST_PAGE_SIZE,
                "_fetch_total": 1, "fetch_all_file": 1,
            })
            data = p.get("data") or {}
            items.extend(data.get("list") or [])
            total = (data.get("metadata") or {}).get("total") or 0
            if total and page * _LIST_PAGE_SIZE >= total:
                break
            if not total and len(data.get("list") or []) < _LIST_PAGE_SIZE:
                break
            page += 1
        return items

    def _resolve_fid(self, remote_path):
        """把 /a/b 路径解析成 fid（夸克接口基于 fid）；找不到抛 UploadError。"""
        p = self._norm(remote_path)
        if p in self._fid_cache:
            return self._fid_cache[p]
        fid = "0"
        walked = "/"
        for seg in [s for s in p.split("/") if s]:
            walked = walked.rstrip("/") + "/" + seg
            if walked in self._fid_cache:
                fid = self._fid_cache[walked]
                continue
            hit = next((it for it in self._list_fid(fid)
                        if it.get("file_name") == seg), None)
            if hit is None:
                raise UploadError(f"目录不存在: {walked}", code="PAN-quark-nodir",
                                  hint="先执行上传（publish 会自动建目录）或检查拼写")
            fid = hit["fid"]
            self._fid_cache[walked] = fid
        return fid

    def list(self, remote_dir="/"):
        fid = self._resolve_fid(remote_dir)
        base = self._norm(remote_dir).rstrip("/")
        out = []
        for it in self._list_fid(fid):
            name = it.get("file_name") or ""
            out.append({
                "fs_id": it.get("fid"),
                "name": name,
                "path": f"{base}/{name}" if base != "/" else f"/{name}",
                "size": it.get("size"),
                "isdir": not it.get("file"),
                "md5": None,
            })
        return out

    def _find_in(self, parent_fid: str, name: str):
        """在父目录列表里找同名条目（目录），没有返回 None。"""
        return next((it for it in self._list_fid(parent_fid)
                     if it.get("file_name") == name), None)

    def _ensure_level(self, parent_fid: str, name: str, walked: str) -> str:
        """确保一级目录存在：找不到就创建（同名冲突回查一次），返回 fid。"""
        hit = self._find_in(parent_fid, name)
        if hit is not None:
            return hit["fid"]
        try:
            resp = self._api("POST", "/file", body={
                "dir_init_lock": False, "dir_path": "",
                "file_name": name, "pdir_fid": parent_fid,
            })
            return (resp.get("data") or {}).get("fid")
        except ProjectError as e:
            if "同名冲突" not in str(e) and "doloading" not in str(e):
                raise
            hit = self._find_in(parent_fid, name)
            if hit is None:
                raise
            return hit["fid"]

    def mkdir(self, remote_dir):
        """建目录（父级逐级创建，全部幂等），返回 {"path", "created", "fid"}。

        与百度不同，夸克的建目录接口挂在已有父目录下，多级目录必须逐级走。
        """
        p = self._norm(remote_dir)
        if p == "/":
            return {"path": "/", "created": False, "fid": "0"}
        fid = "0"
        walked = "/"
        created = False
        for seg in [s for s in p.split("/") if s]:
            before = self._find_in(fid, seg)
            fid = self._ensure_level(fid, seg, walked)
            walked = walked.rstrip("/") + "/" + seg
            self._fid_cache[walked] = fid
            if before is None:
                created = True
        return {"path": p, "created": created, "fid": fid}

    # -- 上传 ------------------------------------------------------------------

    def upload(self, local_path, remote_dir="/", *, overwrite=True, on_progress=None):
        """上传文件到目录。夸克不支持同名覆盖（alist 标记 NoOverwriteUpload），
        overwrite=False 时直接报错提示换名。"""
        if not overwrite:
            raise UploadError("夸克不支持同名覆盖上传", code="PAN-quark-overwrite",
                              hint="夸克同名文件由服务端处理，overwrite 必须为 True")
        src = Path(local_path)
        if not src.is_file():
            raise UploadError(f"本地文件不存在: {local_path}",
                              hint="检查路径是否写对（Windows 下注意反斜杠转义）")
        size = src.stat().st_size
        remote_path = f"{self._norm(remote_dir).rstrip('/')}/{src.name}"
        parent_fid = self._resolve_fid(remote_dir)
        mime = mimetypes.guess_type(src.name)[0] or "application/octet-stream"
        now_ms = int(src.stat().st_mtime * 1000)

        # 全文件 md5 + sha1（秒传与分片签名都需要）
        md5 = hashlib.md5()
        sha1 = hashlib.sha1()
        with open(src, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                md5.update(chunk)
                sha1.update(chunk)
        md5_hex, sha1_hex = md5.hexdigest(), sha1.hexdigest()

        self._log(f"预上传 {src.name}（{_human(size)}）")
        pre = self._api("POST", "/file/upload/pre", body={
            "ccp_hash_update": True, "dir_name": "", "file_name": src.name,
            "format_type": mime, "l_created_at": now_ms, "l_updated_at": now_ms,
            "pdir_fid": parent_fid, "size": size,
        })
        pdata = pre.get("data") or {}
        part_size = int(((pre.get("metadata") or {}).get("part_size"))
                        or pdata.get("part_size") or _FALLBACK_PART_SIZE)
        task_id = pdata.get("task_id")
        if not task_id:
            raise UploadError("预上传没有返回 task_id", code="PAN-quark-pre")

        finish = self._api("POST", "/file/update/hash", body={
            "md5": md5_hex, "sha1": sha1_hex, "task_id": task_id,
        })
        if (finish.get("data") or {}).get("finish"):
            self._log("秒传命中，无需上传字节")
            self._fid_cache[remote_path] = pdata.get("fid")
            return {"path": remote_path, "size": size, "fid": pdata.get("fid"),
                    "rapid": True}

        # 分片：auth 签名 → OSS PUT，收集 ETag
        etags = []
        total_parts = max(1, (size + part_size - 1) // part_size) if size else 1
        oss_host = f"https://{pdata['bucket']}.{pdata['upload_url'][7:]}"
        with open(src, "rb") as f:
            for part_number in range(1, total_parts + 1):
                chunk = f.read(part_size)
                time_str = _http_date()
                auth_meta = (
                    f"PUT\n\n{mime}\n{time_str}\n"
                    f"x-oss-date:{time_str}\n"
                    f"x-oss-user-agent:{OSS_UA}\n"
                    f"/{pdata['bucket']}/{pdata['obj_key']}?"
                    f"partNumber={part_number}&uploadId={pdata['upload_id']}"
                )
                signed = self._api("POST", "/file/upload/auth", body={
                    "auth_info": pdata.get("auth_info"), "auth_meta": auth_meta,
                    "task_id": task_id,
                })
                auth_key = (signed.get("data") or {}).get("auth_key")
                _status, headers = self._oss("PUT", f"{oss_host}/{pdata['obj_key']}",
                                             params={"partNumber": part_number,
                                                     "uploadId": pdata["upload_id"]},
                                             headers={
                                                 "Authorization": auth_key,
                                                 "Content-Type": mime,
                                                 "Referer": f"{REFERER}/",
                                                 "x-oss-date": time_str,
                                                 "x-oss-user-agent": OSS_UA,
                                             },
                                             body=chunk)
                etag = headers.get("ETag") or headers.get("etag")
                etags.append(etag or "")
                if on_progress:
                    done = min(part_number * part_size, size)
                    on_progress(done, size)

        # commit：XML 汇总 + OSS POST
        xml_lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<CompleteMultipartUpload>"]
        for i, etag in enumerate(etags, 1):
            xml_lines.append(f"<Part><PartNumber>{i}</PartNumber><ETag>{etag}</ETag></Part>")
        xml_lines.append("</CompleteMultipartUpload>")
        xml = "\n".join(xml_lines)
        content_md5 = base64.b64encode(hashlib.md5(xml.encode()).digest()).decode()
        callback_b64 = base64.b64encode(
            json.dumps(pdata.get("callback") or {}, separators=(",", ":")).encode()).decode()
        time_str = _http_date()
        commit_meta = (
            f"POST\n{content_md5}\napplication/xml\n{time_str}\n"
            f"x-oss-callback:{callback_b64}\n"
            f"x-oss-date:{time_str}\n"
            f"x-oss-user-agent:{OSS_UA}\n"
            f"/{pdata['bucket']}/{pdata['obj_key']}?uploadId={pdata['upload_id']}"
        )
        signed = self._api("POST", "/file/upload/auth", body={
            "auth_info": pdata.get("auth_info"), "auth_meta": commit_meta,
            "task_id": task_id,
        })
        auth_key = (signed.get("data") or {}).get("auth_key")
        self._oss("POST", f"{oss_host}/{pdata['obj_key']}",
                  params={"uploadId": pdata["upload_id"]},
                  headers={
                      "Authorization": auth_key,
                      "Content-MD5": content_md5,
                      "Content-Type": "application/xml",
                      "Referer": f"{REFERER}/",
                      "x-oss-callback": callback_b64,
                      "x-oss-date": time_str,
                      "x-oss-user-agent": OSS_UA,
                  },
                  body=xml.encode())

        finish = self._api("POST", "/file/upload/finish", body={
            "obj_key": pdata.get("obj_key"), "task_id": task_id,
        })
        fdata = finish.get("data") or {}
        if not fdata.get("finish"):
            raise UploadError("落盘未确认（finish=false）", code="PAN-quark-finish",
                              retriable=True, hint="稍后重试整个上传")
        fid = fdata.get("fid") or pdata.get("fid")
        self._fid_cache[remote_path] = fid
        return {"path": remote_path, "size": size, "fid": fid, "rapid": False}

    # -- 分享 ------------------------------------------------------------------

    def share(self, remote_path, *, pwd=None, period_days=0):
        """创建分享链接。period_days: 0=永久，其余为天数。

        pwd=None 表示不设提取码（默认，人定：夸克链接不带密码更好转发）；
        显式给 4 位字符串才设码，给 "" 等同于不设。
        """
        p = self._norm(remote_path)
        fid = self._fid_cache.get(p) or self._resolve_fid(p)
        filename = p.rsplit("/", 1)[-1]
        if pwd is None:
            pwd = ""
        body = {
            "fid_list": [fid],
            "title": filename,
            "url_type": 1,
            "expired_type": 1 if period_days == 0 else 2,
            "password": pwd or "",
        }
        if period_days:
            body["expire_time"] = int(period_days) * 86400
        resp = self._api("POST", "/share", err_cls=ShareError, body=body)
        data = resp.get("data") or {}
        share_id = ((data.get("task_resp") or {}).get("data") or {}).get("share_id")
        if not share_id and data.get("task_sync"):
            share_id = data.get("share_id")
        if not share_id and data.get("task_id"):
            share_id = self._wait_task(data["task_id"])
        if not share_id:
            raise ShareError("创建分享未返回 share_id", code="PAN-quark-share",
                             errno=resp.get("code"),
                             hint="确认文件存在；若触发风控，先在网页端手动分享一次")
        pset = self._api("POST", "/share/password", err_cls=ShareError,
                         body={"share_id": share_id})
        pdata = pset.get("data") or {}
        link = pdata.get("share_url")
        if not link:
            raise ShareError("分享密码接口未返回 share_url", code="PAN-quark-shareurl",
                             hint="稍后重试；或从夸克网页端「我的分享」复制链接")
        real_pwd = pdata.get("share_pwd") or pwd or ""
        return {"link": link, "url": link, "pwd": real_pwd, "share_id": share_id,
                "path": p, "filename": filename, "period_days": int(period_days)}

    def _wait_task(self, task_id, *, max_polls=20, interval=0.5):
        """轮询任务直到成功（status=2）；失败（status=3）抛 ShareError。"""
        for retry_index in range(max_polls):
            resp = self._api("GET", "/task", err_cls=ShareError,
                             params={"task_id": task_id, "retry_index": retry_index})
            data = resp.get("data") or {}
            status = data.get("status")
            if status == 2:
                # 两种形状都见过：task_resp.data.share_id（旧）与顶层 share_id（新）
                inner = ((data.get("task_resp") or {}).get("data") or {})
                return inner.get("share_id") or data.get("share_id")
            if status == 3:
                raise ShareError(f"分享任务失败: {data.get('task_resp') or data}",
                                 code="PAN-quark-task",
                                 hint="查看夸克网页端分享状态；触发风控时稍后再试")
            time.sleep(interval)
        raise ShareError(f"分享任务轮询超时（{max_polls} 次）", code="PAN-quark-taskpoll",
                         retriable=True, hint="稍后重试；或从夸克网页端确认分享状态")


def _human(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1024
