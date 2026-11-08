"""writers：文档写入接入层。

上游接口的端点与响应解析只在本层内做（AC-03）；core 只消费契约返回值。
每个写入端文件用 @register 登记，注册表见 base.py；新增写入端在下面加一行 import。
"""

from panup.writers import feishu  # noqa: F401  写入端注册登记
