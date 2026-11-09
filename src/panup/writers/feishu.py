"""飞书文档写入端 —— 官方 docx v1 API（自建应用 tenant_access_token）。

为什么飞书先行（docs/ARCHITECTURE.md「关键选择的理由」）：官方 API 个人自建应用
即可用；腾讯文档写入权限门槛高，列 PRD「后续阶段」。

接口清单（均带 Authorization: Bearer <token>）
------------------------------------------------
POST /open-apis/auth/v3/tenant_access_token/internal   app_id+secret 换 token
GET  /open-apis/docx/v1/documents/{document_id}        文档可达性检查
GET  /open-apis/docx/v1/documents/{document_id}/blocks/{block_id}/children?page_size=500
                                                       列页面子块（定位插入位置）
POST /open-apis/docx/v1/documents/{document_id}/blocks/{block_id}/children
                                                       body.index 指定位置写入小节

版式（PRD F3 固定更新规则 / DECISIONLOG D-003）：每次成功上传向文档**最顶**
（首个标题块前）插入一节——h2「YYMMDD 文件名（不带扩展名）」+ 每盘一行
「盘名：链接?pwd=提取码」（全角冒号，提取码内嵌进链接，链接可点击）。

凭证来源（BACKEND.md §9）：环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET >
secrets/feishu_app.json（{"app_id": "...", "app_secret": "..."}）。
目标文档 token 来自 config.toml [feishu].doc_token；需把文档授权给应用（一次性）。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from panup.core.errors import AuthError, ConfigError, ProjectError, WriterError
from panup.writers.base import Writer, register

BASE = "https://open.feishu.cn"
_TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
SECRETS_DIR = _PROJECT_ROOT / "secrets"

# token 提前 5 分钟失效重取
_TOKEN_EXPIRY_MARGIN = 300

# 标题小节里的网盘名写法（未知盘用原名）
_PAN_LABELS = {"quark": "夸克", "baidu": "百度"}
# 标题块的 block_type 区间（h1～h9）
_HEADING_TYPES = set(range(3, 12))


def _today_str() -> str:
    """标题日期（YYMMDD，如 261109）；测试覆写点。"""
    return f"{datetime.now().astimezone():%y%m%d}"


def load_default_credentials():
    """飞书应用凭证：环境变量优先于 secrets/feishu_app.json；都没有返回 {}。"""
    creds = {}
    env_id = os.environ.get("FEISHU_APP_ID")
    env_secret = os.environ.get("FEISHU_APP_SECRET")
    if env_id and env_secret:
        return {"app_id": env_id, "app_secret": env_secret}
    p = SECRETS_DIR / "feishu_app.json"
    if p.exists():
        from panup.config import load_json_file

        data = load_json_file(p)
        if isinstance(data, dict):
            creds = {k: data.get(k) for k in ("app_id", "app_secret")
                     if data.get(k)}
    return creds


def load_doc_token():
    """目标文档 token：来自 config.toml [feishu].doc_token；缺失抛 ConfigError。"""
    from panup.config import load_config

    cfg = load_config()
    token = (cfg.get("feishu") or {}).get("doc_token")
    if not token:
        raise ConfigError(
            "配置缺少 feishu.doc_token", code="PUP-105",
            hint="在 config.toml [feishu] 里填 doc_token（文档链接中 /docx/ 后那串）")
    return token


@register
class FeishuWriter(Writer):
    name = "feishu"

    def __init__(self, *, doc_token=None, app_id=None, app_secret=None,
                 timeout=30, log=None):
        creds = load_default_credentials()
        self.app_id = app_id or creds.get("app_id")
        self.app_secret = app_secret or creds.get("app_secret")
        self._doc_token_id = doc_token
        self.timeout = timeout
        self._log = log or (lambda *a, **k: None)
        self._token = None
        self._token_expire_at = 0.0

    # -- 传输层（测试打桩点） ------------------------------------------------

    def _request(self, method, url, *, body=None, headers=None):
        """单次 HTTP 调用，返回 (status, text)。测试覆写本方法打桩。"""
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        hdrs = {"Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json"}
        hdrs.update(headers or {})
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")

    def _tenant_token(self) -> str:
        if self._token and time.time() < self._token_expire_at:
            return self._token
        if not self.app_id or not self.app_secret:
            raise AuthError(
                "缺少飞书应用凭证", code="PUP-106",
                hint="把自建应用的 app_id/app_secret 写入 secrets/feishu_app.json"
                     "（或环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET）")
        try:
            payload = self._api("POST", _TOKEN_PATH,
                                body={"app_id": self.app_id,
                                      "app_secret": self.app_secret},
                                err_cls=AuthError, skip_auth=True)
        except AuthError as e:
            # token 端点的任何失败都按「凭证问题」给指引
            raise AuthError(
                f"飞书应用凭证无效或被拒（{e.msg}）", code=e.code, errno=e.errno,
                hint="检查 secrets/feishu_app.json 的 app_id / app_secret"
                     "（或环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET）") from e
        self._token = payload["tenant_access_token"]
        self._token_expire_at = time.time() + int(payload.get("expire") or 0) \
            - _TOKEN_EXPIRY_MARGIN
        return self._token

    def _doc_token(self) -> str:
        if not self._doc_token_id:
            self._doc_token_id = load_doc_token()
        return self._doc_token_id

    def _api(self, method, path, *, body=None, err_cls=WriterError,
             skip_auth=False):
        """调 JSON API 并校验 {code:0} 信封；登录态类错误升为 AuthError。"""
        headers = {}
        if not skip_auth:
            headers["Authorization"] = f"Bearer {self._tenant_token()}"
        url = f"{BASE}{path}"
        last = None
        for attempt in range(1, 3 + 1):
            try:
                status, text = self._request(method, url, body=body, headers=headers)
            except urllib.error.HTTPError as e:
                status, text = e.code, e.read().decode("utf-8", "replace")
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = e
                if attempt < 3:
                    time.sleep(0.8 * 2 ** (attempt - 1))
                    continue
                raise ProjectError(f"网络请求失败: {e}", code="PAN-feishu-net",
                                   retriable=True, hint="检查网络后重试") from e
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                raise WriterError(f"返回非 JSON: {text[:200]}", code="PAN-feishu-html")
            code = payload.get("code")
            if code == 0:
                return payload
            msg = payload.get("msg") or f"code={code}"
            if code in (99991661, 99991663, 99991668):
                raise AuthError(f"飞书应用凭证无效（{msg}）",
                                code=f"PAN-feishu-{code}", errno=code,
                                hint="检查 secrets/feishu_app.json 的 app_id/app_secret")
            if code == 99991672 or code == 1770032 or \
                    "permission" in msg.lower() or "forbidden" in msg.lower():
                raise AuthError(f"飞书文档无写入权限（{msg}）",
                                code=f"PAN-feishu-{code}", errno=code,
                                hint="① 应用后台「权限管理」开通 docx 查看/编辑/管理并"
                                     "重新发布版本；② 文档右上角「…」→「添加文档应用」"
                                     "把应用加进目标文档（权限给可编辑）")
            e = err_cls(f"飞书接口返回错误（{msg}）", code=f"PAN-feishu-{code}",
                        errno=code, hint="查看 msg；临时性失败可重试")
            e.retriable = status >= 500
            raise e
        raise ProjectError("重试耗尽", code="PAN-feishu-retry", retriable=True)

    # -- Writer 契约 -----------------------------------------------------------

    def auth_check(self) -> dict:
        doc_token = self._doc_token()
        self._tenant_token()
        self._api("GET", f"/open-apis/docx/v1/documents/{doc_token}",
                  err_cls=AuthError)
        return {"ok": True, "doc": doc_token}

    def append_task(self, task: dict) -> dict:
        """按固定更新规则向文档最顶插入一节（一个任务一节，节内每盘一行）。"""
        doc_token = self._doc_token()
        index = self._insert_index(doc_token)
        blocks = [self._heading_block(self._section_title(task))]
        for item in task.get("items") or []:
            blocks.extend(self._link_blocks(item))
        body = {"index": index, "children": blocks}
        path = (f"/open-apis/docx/v1/documents/{doc_token}"
                f"/blocks/{doc_token}/children?document_revision_id=-1")
        payload = self._api("POST", path, body=body)
        block_ids = [b.get("block_id")
                     for b in (payload.get("data") or {}).get("children") or []]
        return {"block_ids": block_ids, "doc": doc_token, "index": index}

    def _insert_index(self, doc_token: str) -> int:
        """插入位置：首个标题块（h1～h9）之前；没有标题块则最顶（0）。"""
        index = 0
        page_token = ""
        while True:
            path = (f"/open-apis/docx/v1/documents/{doc_token}"
                    f"/blocks/{doc_token}/children"
                    f"?page_size=500&document_revision_id=-1" + page_token)
            data = self._api("GET", path).get("data") or {}
            for i, b in enumerate(data.get("items") or [], start=index):
                if b.get("block_type") in _HEADING_TYPES:
                    return i
            index += len(data.get("items") or [])
            if not data.get("has_more"):
                return 0
            page_token = f"&page_token={data['page_token']}"

    def _section_title(self, task: dict) -> str:
        """h2 = 「YYMMDD 标题名」；标题优先取任务标题，缺省用文件名去扩展名。"""
        title = (task.get("title") or "").strip()
        if not title:
            name = task.get("filename") or "未命名"
            title = Path(name).stem or name
        return f"{task.get('date') or _today_str()} {title}"

    def _heading_block(self, title: str) -> dict:
        return {"block_type": 4, "heading2": {
            "elements": [{"text_run": {"content": title}}], "style": {}}}

    def _link_blocks(self, item: dict) -> list[dict]:
        """一个成功网盘一行「盘名：链接?pwd=提取码」（提取码内嵌，可点击）。"""
        link = item.get("link") or ""
        pwd = item.get("pwd") or ""
        if link and pwd and "?pwd=" not in link:
            link = f"{link}?pwd={pwd}"
        pan = item.get("pan") or ""
        label = _PAN_LABELS.get(pan, pan or "链接")
        elements = [{"text_run": {"content": f"{label}："}}]
        if link:
            elements.append({"text_run": {"content": link,
                "text_element_style": {
                    "link": {"url": urllib.parse.quote(link, safe="")}}}})
        return [{"block_type": 2, "text": {"elements": elements, "style": {}}}]
