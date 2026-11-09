"""网盘中控台：把本地文件传到百度/夸克网盘指定目录，自动生成分享链接并记入文档。

包结构见 docs/ARCHITECTURE.md 模块表；零第三方依赖（Python 3.13 标准库）。
入口与核心的关系：cli / watcher 是薄壳，业务逻辑在 core（AC-01）。
"""

__version__ = "0.1.0"
