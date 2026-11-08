"""drivers：网盘接入层。

端点、参数与响应解析只在本层内做（AC-03）；core 只消费契约返回值。
每个驱动文件用 @register 登记，注册表见 base.py。
"""
