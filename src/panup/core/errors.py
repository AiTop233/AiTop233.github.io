"""统一错误契约 —— 对外只抛 ProjectError 子类（AGENTS §11 第 4 条）。

每个错误携带：
- code: 项目错误码（PUP-1xx 为项目码；网盘 errno 透传为 PAN-<盘>-<errno>，目录执行期建）
- errno: 上游网盘 / 平台返回的错误号（没有则为 None）
- hint: 「怎么办」恢复指引，人和模型都能照做
- retriable: 是否值得重试（临时性错误 True；配置 / 登录态类 False）

本模块是零依赖叶子，被 config / drivers / writers / core 共用。
"""


class ProjectError(Exception):
    """所有对外错误的基类；文案格式「发生了什么 [code=… errno=…] 怎么办: …」。"""

    retriable = False

    def __init__(self, msg, *, code="PUP-000", errno=None, hint=None):
        self.msg = msg
        self.code = code
        self.errno = errno
        self.hint = hint
        text = f"{msg} [code={self.code}"
        if errno is not None:
            text += f" errno={errno}"
        text += "]"
        if self.hint:
            text += f" 怎么办: {self.hint}"
        super().__init__(text)


class ConfigError(ProjectError):
    """配置缺失、格式错误或凭据文件不可用。"""


class AuthError(ProjectError):
    """网盘 / 平台登录态失效或凭证无权限。"""


class UploadError(ProjectError):
    """上传链路（预上传 / 分片 / 落盘）失败。"""


class ShareError(ProjectError):
    """创建分享链接失败。"""


class WriterError(ProjectError):
    """写入目标文档（飞书等）失败。"""
