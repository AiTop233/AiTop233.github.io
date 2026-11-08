"""测试支撑：把 src 加入 sys.path，供各用例导入 panup 包。

unittest discover 会把 tests/ 插入 sys.path，因此各用例 import support 即可。
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
