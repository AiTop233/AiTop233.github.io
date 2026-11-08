"""core：上传管道、台账、驱动与写入端注册表。

依赖方向（docs/ARCHITECTURE.md）：core → drivers / writers / config，入口不得绕过 core。
"""
