"""pytest 的环境准备。

这个文件必须在任何测试模块 import fastapi_bot 之前生效，
所以放在 tests/ 下，由 pytest 自动最先加载。
"""

import os

# 关掉启动探测。
# 否则每个测试都会真的发一次网络请求：慢、花钱，
# 而且会破坏「换成假 API Key 也全绿」这条证明"测试没联网"的约定。
os.environ.setdefault("PROBE_ON_STARTUP", "false")
