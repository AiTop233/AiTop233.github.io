"""python -m panup 入口 —— 转发到 cli.main 并以其返回值作为退出码。"""

import sys

from panup.cli import main

sys.exit(main())
