"""drivers：网盘接入层。

端点、参数与响应解析只在本层内做（AC-03）；core 只消费契约返回值。
每个驱动文件用 @register 登记，注册表见 base.py；新增网盘在下面加一行 import。
"""

from panup.drivers import baidu, quark  # noqa: F401  驱动注册登记
