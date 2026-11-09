"""百度网盘驱动 —— 走网页版内部接口，cookie 登录态，纯标准库。

为什么不用官方开放平台（docs/ARCHITECTURE.md「关键选择的理由」）：
分享 / 上传接口需企业认证主体，个人申请不下来；网页版接口只要有登录态
cookie 即可上传、建目录、创建分享链接。本文件移植自本人已验证的实现，
端点与参数以其为准（2026-11 实测存活）。

接口清单
--------
GET  /api/gettemplatevariable                        取 bdstoken / uk / username
GET  /api/quota                                      容量（free 字段是占位值，须自算）
GET  /api/list                                       列目录
POST /api/create?a=commit                            isdir=1 建目录（自动建父目录，幂等）
POST /api/precreate                                  预上传，返回 uploadid（return_type=2 即秒传）
GET  d.pcs.baidu.com/rest/2.0/pcs/file?method=locateupload  上传节点
POST <host>/rest/2.0/pcs/superfile2?method=upload    分片上传
POST /api/create?isdir=0                             落盘
POST /api/filemetas                                  路径 → fs_id
POST /api/filemanager?opera=delete                   删除文件/目录（服务端递归；errno 132=需先过安全校验）
POST /share/pset                                     创建分享链接
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import random
import re
import string
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from panup.core.errors import AuthError, ProjectError, ShareError, UploadError
from panup.drivers.base import Driver, register

PAN = "https://pan.baidu.com"
PCS = "https://d.pcs.baidu.com"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
APP_ID = 250528

# 分片大小随文件体积变化：4MiB / 16MiB(>=8GiB) / 64MiB(>=32GiB)
_SMALL_BLOCK = 4 * 1024 * 1024
_MID_BLOCK = 16 * 1024 * 1024
_BIG_BLOCK = 64 * 1024 * 1024

# 临时性错误：值得指数退避重试
RETRY_ERRNOS = {429, 500, -1}

ERRNO_TEXT = {
    -1: "参数错误",
    -6: "登录态失效：cookie 里缺少有效的 BDUSS / STOKEN，请重新登录导出",
    -7: "文件名非法（含特殊字符或过长）",
    -8: "同名文件已存在",
    -9: "路径不存在",
    -10: "网盘空间不足",
    -12: "提取码错误",
    -30: "同名文件已存在",
    2: "参数错误或目标已存在",
    4: "文件已转存过",
    12: "批量操作部分失败",
    111: "token 过期",
    132: "触发安全校验：需要先在浏览器里完成一次短信/邮箱验证，之后再重试",
    31061: "同名文件已存在",
    31066: "文件不存在",
    429: "请求过于频繁，稍后再试",
}

# 项目根：src/panup/drivers/baidu.py → parents[3]
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
SECRETS_DIR = _PROJECT_ROOT / "secrets"


# --------------------------------------------------------------------------- cookie


def parse_cookies(src):
    """把三种常见形式统一成 {name: value}：

    1. 浏览器导出的 header 文本：BDUSS=xxx; STOKEN=yyy
    2. Netscape cookies.txt
    3. Playwright 的 cookies 数组 / storage_state JSON
    """
    if src is None:
        return {}
    if isinstance(src, dict):
        if "cookies" in src and isinstance(src["cookies"], list):
            return parse_cookies(src["cookies"])
        return {str(k): str(v) for k, v in src.items() if str(k)}
    if isinstance(src, list):
        jar = {}
        for c in src:
            if isinstance(c, dict) and c.get("name"):
                jar[str(c["name"])] = "" if c.get("value") is None else str(c["value"])
        return jar

    text = str(src).strip()
    if os.path.exists(text):
        text = Path(text).read_text(encoding="utf-8", errors="replace").strip()
    if text.startswith("[") or text.startswith("{"):
        return parse_cookies(json.loads(text))

    jar = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:  # netscape
            parts = line.split("\t")
            if len(parts) >= 7:
                jar[parts[5]] = parts[6]
            continue
        for pair in line.split(";"):
            pair = pair.strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                jar[k.strip()] = v.strip()
    return jar


def cookies_to_header(jar):
    # BDCLND 是某个分享的临时凭证，残留会让分享接口报 -9，剔除
    return "; ".join(f"{k}={v}" for k, v in jar.items() if k and k != "BDCLND")


def gen_password(n=4):
    alphabet = string.digits + string.ascii_lowercase
    return "".join(random.choice(alphabet) for _ in range(n))


def load_default_cookies():
    """登录 cookie 来源（BACKEND.md §9）：环境变量 BAIDU_COOKIE > secrets/ 文件。"""
    env = os.environ.get("BAIDU_COOKIE")
    if env:
        return parse_cookies(env)
    for name in ("baidu_cookies.json", "baidu_cookie.txt"):
        p = SECRETS_DIR / name
        if p.exists():
            return parse_cookies(str(p))
    return {}


# --------------------------------------------------------------------------- 工具


def _norm(p):
    p = str(p or "/").replace("\\", "/").strip()
    if ":" in p.split("/")[0]:
        # Git Bash 会把参数里的 / 转成 Windows 路径（如 C:/Program Files/Git/）
        raise ProjectError(
            f"这个看着不像网盘路径: {p}",
            hint="Git Bash 下用 MSYS_NO_PATHCONV=1，或把目录写成 //开头",
        )
    if not p.startswith("/"):
        p = "/" + p
    while "//" in p:
        p = p.replace("//", "/")
    return p.rstrip("/") or "/"


def _resolve_block(size):
    if size >= 32 * 1024 ** 3:
        return _BIG_BLOCK
    if size >= 8 * 1024 ** 3:
        return _MID_BLOCK
    return _SMALL_BLOCK


def _human(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1024


def _multipart(fields, extra=None):
    boundary = "----panup" + uuid.uuid4().hex
    out = []
    for k, v in (extra or {}).items():
        out.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    for k, v in fields.items():
        if isinstance(v, tuple):
            fname, data = v[0], v[1]
            ctype = v[2] if len(v) > 2 else (
                mimetypes.guess_type(fname)[0] or "application/octet-stream")
            head = (f"--{boundary}\r\nContent-Disposition: form-data; "
                    f"name=\"{k}\"; filename=\"{fname}\"\r\n"
                    f"Content-Type: {ctype}\r\n\r\n").encode()
            out.append(head + (data if isinstance(data, bytes) else str(data).encode()) + b"\r\n")
        else:
            out.append((f"--{boundary}\r\nContent-Disposition: form-data; "
                        f"name=\"{k}\"\r\n\r\n{'' if v is None else v}\r\n").encode())
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


# --------------------------------------------------------------------------- 驱动


@register
class BaiduDriver(Driver):
    name = "baidu"

    def __init__(self, cookies=None, *, ua=DEFAULT_UA, timeout=60, retries=3, log=None):
        if cookies is None:
            cookies = load_default_cookies()
        self.cookies = parse_cookies(cookies)
        self.ua = ua
        self.timeout = timeout
        self.retries = retries
        self._log = log or (lambda *_: None)
        self._bdstoken = None
        self._uk = None
        self._hosts = None

    # -- 传输层（测试打桩点） ------------------------------------------------

    def _request(self, method, url, *, params=None, data=None, files=None,
                 headers=None) -> str:
        """单次 HTTP 调用，返回原始响应文本。测试通过覆写本方法打桩。"""
        if params:
            url = f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode(params)}"
        body, hdrs = None, dict(headers or {})
        if files:
            body, ctype = _multipart(files, data)
            hdrs["Content-Type"] = ctype
        elif data is not None:
            body = urllib.parse.urlencode(data).encode()
        elif method == "POST":
            body = b""
        req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return r.read().decode("utf-8", "replace")

    def _headers(self, extra=None, form=False):
        h = {
            "User-Agent": self.ua,
            "Referer": f"{PAN}/disk/main",
            "Origin": PAN,
            "Accept": "application/json, text/plain, */*",
        }
        jar = cookies_to_header(self.cookies)
        if jar:
            h["Cookie"] = jar
        if form:
            h["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
            h["X-Requested-With"] = "XMLHttpRequest"
        if extra:
            h.update(extra)
        return h

    def _json(self, method, url, *, err_cls=UploadError, params=None, data=None,
              files=None, headers=None, allow=(), retry_on=RETRY_ERRNOS):
        """请求并解析 JSON；临时性错误指数退避重试，其余抛 err_cls（-6 恒为 AuthError）。"""
        last = None
        for attempt in range(1, self.retries + 1):
            try:
                text = self._request(method, url, params=params, data=data,
                                     files=files,
                                     headers=headers or self._headers(form=bool(data) and not files))
            except urllib.error.HTTPError as e:
                text = e.read().decode("utf-8", "replace")
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = e
                if attempt < self.retries:
                    time.sleep(0.8 * 2 ** (attempt - 1))
                    continue
                raise ProjectError(
                    f"网络请求失败: {e}", code="PAN-baidu-net", retriable=True,
                    hint="检查网络后重试",
                ) from e

            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                raise UploadError(
                    f"返回非 JSON（HTTP 可能被拦截）: {text[:200]}",
                    code="PAN-baidu-html",
                    hint="稍后重试；若持续出现，换网络环境",
                )

            errno = payload.get("errno", payload.get("error_code", 0))
            if errno not in allow and errno in retry_on and attempt < self.retries:
                self._log(f"errno={errno}，第 {attempt} 次重试")
                time.sleep(0.8 * 2 ** (attempt - 1))
                continue
            if errno != 0 and errno not in allow:
                cls = AuthError if errno == -6 else err_cls
                e = cls(
                    ERRNO_TEXT.get(errno, f"百度接口返回错误 errno={errno}"),
                    code=f"PAN-baidu-{errno}", errno=errno,
                    hint=ERRNO_TEXT.get(errno, "查看百度网页接口返回内容"),
                )
                e.retriable = errno in RETRY_ERRNOS and errno != -6
                raise e
            return payload
        raise ProjectError("重试耗尽", code="PAN-baidu-retry", retriable=True)

    # -- 登录态 ----------------------------------------------------------------

    @property
    def bdstoken(self):
        if self._bdstoken:
            return self._bdstoken
        p = self._json(
            "GET", f"{PAN}/api/gettemplatevariable", err_cls=AuthError,
            params={"fields": json.dumps(["bdstoken", "uk", "username"]),
                    "clienttype": 0, "app_id": APP_ID, "web": 1},
        )
        result = p.get("result") or {}
        self._bdstoken = result.get("bdstoken")
        self._uk = result.get("uk")
        if not self._bdstoken:
            raise AuthError(
                "返回里没有 bdstoken，cookie 不完整", code="PAN-baidu-token",
                hint="重新登录 pan.baidu.com 并完整导出 BDUSS / STOKEN",
            )
        return self._bdstoken

    def auth_check(self):
        if not self.cookies:
            raise AuthError(
                "缺少百度登录态 cookie", code="PAN-baidu-noauth",
                hint="浏览器登录 pan.baidu.com 后，把 BDUSS/STOKEN 导出到 "
                     "secrets/baidu_cookies.json 或环境变量 BAIDU_COOKIE",
            )
        p = self._json(
            "GET", f"{PAN}/api/gettemplatevariable", err_cls=AuthError,
            params={"fields": json.dumps(["uk", "username"]),
                    "clienttype": 0, "app_id": APP_ID, "web": 1},
        )
        r = p.get("result") or {}
        return {"ok": True, "account": r.get("username"), "uk": r.get("uk"),
                "quota": self.quota()}

    def quota(self):
        p = self._json("GET", f"{PAN}/api/quota", err_cls=AuthError,
                       params={"checkfree": 1, "clienttype": 0, "app_id": APP_ID, "web": 1},
                       allow=(-6,))
        total, used = p.get("total"), p.get("used")
        # 接口里的 free 常是固定的 5GiB 占位值，必须自己算
        free = total - used if isinstance(total, int) and isinstance(used, int) else p.get("free")
        return {"total": total, "used": used, "free": free}

    # -- 目录与文件 ------------------------------------------------------------

    def list(self, remote_dir="/"):
        d = _norm(remote_dir)
        p = self._json("GET", f"{PAN}/api/list",
                       params={"dir": d, "order": "name", "desc": 0, "num": 1000,
                               "page": 1, "clienttype": 0, "app_id": APP_ID, "web": 1},
                       allow=(-9,))
        if p.get("errno") == -9:
            raise UploadError(f"目录不存在: {d}", code="PAN-baidu--9", errno=-9,
                              hint="先执行上传会自动建目录；或检查目录拼写")
        return [
            {"fs_id": it.get("fs_id"), "name": it.get("server_filename"),
             "path": it.get("path"), "size": it.get("size"),
             "isdir": bool(it.get("isdir")), "md5": it.get("md5")}
            for it in (p.get("list") or [])
        ]

    def mkdir(self, remote_dir):
        """建目录，已存在视为成功（幂等）；父目录由服务端自动创建。"""
        d = _norm(remote_dir)
        if d == "/":
            return {"path": "/", "created": False}
        p = self._json(
            "POST", f"{PAN}/api/create",
            params={"a": "commit", "bdstoken": self.bdstoken, "clienttype": 0,
                    "app_id": APP_ID, "web": 1},
            data={"path": d, "isdir": 1, "rtype": 0, "block_list": "[]"},
            allow=(-8, -30, 31061),
        )
        if p.get("errno") in (-8, -30, 31061):
            return {"path": d, "created": False}
        return {"path": d, "created": True}

    def fs_id(self, remote_path):
        p = self._json(
            "POST", f"{PAN}/api/filemetas",
            params={"bdstoken": self.bdstoken, "clienttype": 0,
                    "app_id": APP_ID, "web": 1, "dlink": 0},
            data={"target": json.dumps([_norm(remote_path)], ensure_ascii=False,
                                       separators=(",", ":"))},
            allow=(-9, 12),
        )
        for it in (p.get("info") or []):
            if it.get("fs_id"):
                return int(it["fs_id"]), it
        raise UploadError(f"查不到文件: {remote_path}", code="PAN-baidu-nofile",
                          hint="确认文件已上传成功（先跑 upload 再 share）")

    def _filemanager(self, opera, filelist, *, ondup="overwrite"):
        """网页版文件管理接口：rename / delete / copy / move 共用同一个端点。

        `async=1` 让服务端自适应同步或异步；`allow` 放行 -9（不存在）、-7（名字非法）
        与 111（token 过期重取），交给调用方逐条归因，而不是整批炸掉。
        """
        return self._json(
            "POST", f"{PAN}/api/filemanager",
            params={"opera": opera, "async": "1", "onnest": "fail",
                    "channel": "chunlei", "web": 1, "app_id": APP_ID,
                    "bdstoken": self.bdstoken, "clienttype": 0},
            data={"filelist": json.dumps(filelist, ensure_ascii=False),
                  **({"ondup": ondup} if ondup else {})},
            allow=(-9, -7, 111, 31066, 12),
        )

    @staticmethod
    def _info_errno(payload) -> tuple[int, dict]:
        """取整体 errno 与「path → 单条 errno」映射；info 缺失时按整体判定。"""
        info = {}
        for it in payload.get("info") or []:
            if isinstance(it, dict) and it.get("path"):
                info[it["path"]] = int(it.get("errno") or 0)
        return int(payload.get("errno") or 0), info

    def delete(self, remote_paths, *, to_trash=True):
        """批量删除（百度这边本身就是移入回收站）。逐条归因，一条失败不中断。"""
        if not to_trash:
            raise UploadError(
                "百度不支持直接彻底删除", code="PAN-baidu-purge",
                hint="这里只把条目移入回收站；要彻底删除请到网盘网页端清空回收站")
        paths = [_norm(x) for x in (remote_paths or [])]
        result: dict = {"deleted": [], "missing": [], "failed": []}
        targets = []
        for p in paths:
            if p == "/":
                result["failed"].append({"path": p, "code": "PAN-baidu-root",
                                         "msg": "不能删除根目录"})
            else:
                targets.append(p)
        if not targets:
            return result
        payload = self._filemanager("delete", targets, ondup="")
        errno, info = self._info_errno(payload)
        for p in targets:
            code = info.get(p, errno)
            if code == 0:
                result["deleted"].append(p)
            elif code in (-9, 31066):
                result["missing"].append(p)
            else:
                result["failed"].append({
                    "path": p, "code": f"PAN-baidu-{code}",
                    "msg": ERRNO_TEXT.get(code, f"删除失败（errno={code}）")})
        return result


    # -- 上传 ------------------------------------------------------------------

    def _hosts_list(self):
        if self._hosts:
            return self._hosts
        try:
            p = self._json("GET", f"{PCS}/rest/2.0/pcs/file",
                           params={"method": "locateupload"},
                           headers=self._headers())
            self._hosts = p.get("server") or []
        except ProjectError:
            self._hosts = []
        if not self._hosts:
            self._hosts = ["d.pcs.baidu.com"]
        return self._hosts

    def upload(self, local_path, remote_dir="/", *, overwrite=True, on_progress=None):
        """把本地文件传进网盘指定目录。返回 {fs_id, path, size, uploadid, rapid}。"""
        src = Path(local_path)
        if not src.is_file():
            raise UploadError(f"本地文件不存在: {local_path}",
                              hint="检查路径是否写对（Windows 下注意反斜杠转义）")
        size = src.stat().st_size
        remote_path = f"{_norm(remote_dir).rstrip('/')}/{src.name}"
        local_mtime = int(src.stat().st_mtime * 1000)

        block = _resolve_block(size)
        block_list = []
        with open(src, "rb") as f:
            while True:
                chunk = f.read(block)
                if not chunk:
                    break
                block_list.append(hashlib.md5(chunk).hexdigest())

        self._log(f"预上传 {src.name}（{_human(size)}，{len(block_list)} 个分片）")
        pre = self._json(
            "POST", f"{PAN}/api/precreate",
            params={"bdstoken": self.bdstoken, "clienttype": 0,
                    "app_id": APP_ID, "web": 1},
            data={"path": remote_path, "size": size, "isdir": 0, "autoinit": 1,
                  "block_list": json.dumps(block_list, separators=(",", ":")),
                  "local_mtime": local_mtime, "rtype": 3 if overwrite else 0},
            allow=(-8, -30, 31061),
        )
        if pre.get("errno") in (-8, -30, 31061) and not overwrite:
            raise UploadError(f"云端已存在同名文件: {remote_path}",
                              code="PAN-baidu-exists", errno=pre.get("errno"),
                              hint="用 overwrite=True 覆盖，或换文件名")

        # return_type=2 表示命中秒传，服务端已生成文件
        if str(pre.get("return_type")) == "2" and not pre.get("uploadid"):
            self._log("秒传命中，无需上传字节")
            fs_id, _ = self.fs_id(remote_path)
            return {"fs_id": fs_id, "path": remote_path, "size": size,
                    "uploadid": None, "rapid": True}

        uploadid = pre.get("uploadid")
        if not uploadid:
            raise UploadError("预上传没有返回 uploadid", code="PAN-baidu-pre")

        if block_list:
            self._upload_parts(src, remote_path, uploadid, block, block_list,
                               size, on_progress)

        created = self._json(
            "POST", f"{PAN}/api/create",
            params={"isdir": 0, "bdstoken": self.bdstoken, "clienttype": 0,
                    "app_id": APP_ID, "web": 1},
            data={"path": remote_path, "size": size, "uploadid": uploadid,
                  "block_list": json.dumps(block_list, separators=(",", ":")),
                  "local_mtime": local_mtime, "rtype": 3 if overwrite else 0},
        )
        info = created.get("info") or {}
        fs_id = info.get("fs_id")
        if not fs_id:
            fs_id, _ = self.fs_id(remote_path)
        return {"fs_id": int(fs_id), "path": info.get("path") or remote_path,
                "size": size, "uploadid": uploadid, "rapid": False}

    def _upload_parts(self, src, remote_path, uploadid, block, block_list,
                      size, on_progress):
        hosts = self._hosts_list()
        done = 0
        with open(src, "rb") as f:
            for seq in range(len(block_list)):
                offset = seq * block
                f.seek(offset)
                chunk = f.read(block)
                last = None
                for attempt in range(1, self.retries + 1):
                    host = hosts[(seq + attempt - 1) % len(hosts)]
                    try:
                        resp = self._json(
                            "POST", f"https://{host}/rest/2.0/pcs/superfile2",
                            params={"method": "upload", "app_id": APP_ID,
                                    "channel": "chunlei", "web": 1, "clienttype": 0,
                                    "path": remote_path, "uploadid": uploadid,
                                    "uploadsign": 0, "partseq": seq},
                            files={"file": ("blob", chunk, "application/octet-stream")},
                            headers=self._headers(extra={"Referer": f"{PAN}/"}),
                            allow=(0,),
                        )
                        if resp.get("md5") or resp.get("errno") in (0, None):
                            break
                        last = resp
                    except ProjectError as e:
                        last = e
                    if attempt < self.retries:
                        time.sleep(0.8 * 2 ** (attempt - 1))
                else:
                    raise UploadError(f"分片 {seq} 上传失败: {last}",
                                      code="PAN-baidu-part", retriable=True,
                                      hint="网络波动导致的临时失败可重试整个上传")
                done += len(chunk)
                if on_progress:
                    on_progress(min(done, size), size)

    # -- 分享 ------------------------------------------------------------------

    def share(self, remote_path, *, pwd=None, period_days=0):
        """给网盘上的文件/目录创建分享链接。

        period_days: 0 = 永久，其余为有效天数
        pwd: 4 位提取码；传 "" 表示不要提取码；None 表示随机生成
        """
        fs_id, meta = self.fs_id(remote_path)
        if pwd is None:
            pwd = gen_password()
        data = {
            "fid_list": json.dumps([fs_id], separators=(",", ":")),
            "schannel": "4" if pwd else "0",
            "channel_list": "[]",
            "period": str(int(period_days)),
            "public": "0",
            "is_knowledge": "0",
            "eflag_disable": "true",
            "linkOrQrcode": "link",
        }
        if pwd:
            data["pwd"] = pwd

        p = self._json(
            "POST", f"{PAN}/share/pset", err_cls=ShareError,
            params={"channel": "chunlei", "clienttype": 0, "web": 1,
                    "bdstoken": self.bdstoken, "app_id": APP_ID},
            data=data,
        )
        link = p.get("link")
        if not link:
            raise ShareError("创建分享链接失败（返回无 link）", code="PAN-baidu-share",
                             errno=p.get("errno"),
                             hint="确认文件存在；若触发安全校验，先在网页端分享一次")
        # 没传提取码时，服务端可能自己补一个，以返回值为准
        real_pwd = p.get("pwd") if p.get("pwd") is not None else (pwd or "")
        return {
            "link": link,
            "url": f"{link}?pwd={real_pwd}" if real_pwd else link,
            "pwd": real_pwd,
            "period_days": int(period_days),
            "shareid": p.get("shareid"),
            "fs_id": fs_id,
            "path": meta.get("path") or _norm(remote_path),
            "filename": Path(_norm(remote_path)).name,
            "size": meta.get("size"),
        }
