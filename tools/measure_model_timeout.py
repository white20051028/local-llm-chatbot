"""测量「模型层」多久才放弃。

不需要起服务，直接调 get_model() 拿客户端发一次请求，
所以它测的就是超时配置这一层，和 HTTP 路由无关。

用法：
    1) 终端 A：python tools/silent_upstream.py
    2) 终端 B：python tools/measure_model_timeout.py

预期：
    改超时之前 —— 挂住不放（等满本脚本的上限，只能 Ctrl+C）
    改超时之后 —— 在读超时附近失败（比如 15 秒左右）

注意：本脚本只在**自己进程内**把 base_url 指向假上游，不动你的 .env。
"""

import asyncio
import os
import sys
import time
from pathlib import Path

# 脚本在 tools/ 下运行，sys.path[0] 是 tools/，所以要手动把项目根加进来，
# 否则 import fastapi_bot 会失败。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 必须在 import fastapi_bot 之前设置：
# load_dotenv() 默认不覆盖已存在的环境变量，所以这里的值会赢。
os.environ["SILICONFLOW_BASE_URL"] = "http://127.0.0.1:8899/v1"

from fastapi_bot import get_model  # noqa: E402

HARD_LIMIT = float(os.getenv("MEASURE_LIMIT", "90"))  # 本脚本自己最多等多久，避免真的永远挂着


async def main() -> None:
    model = get_model()
    messages = [{"role": "user", "content": "你好"}]

    print(f"开始请求假上游（本脚本最多等 {HARD_LIMIT} 秒）...")
    t0 = time.perf_counter()

    try:
        async with asyncio.timeout(HARD_LIMIT):
            async for _chunk in model.astream(messages):
                pass
        print(f"  竟然成功了，耗时 {time.perf_counter() - t0:.2f} 秒")
    except TimeoutError:
        print(f"  ⏱ 本脚本等满 {HARD_LIMIT} 秒仍无结果 → 服务端这一层没有生效的超时")
    except Exception as e:  # noqa: BLE001
        elapsed = time.perf_counter() - t0
        print(f"  ❌ {elapsed:.2f} 秒后失败：{type(e).__name__}: {str(e)[:100]}")


if __name__ == "__main__":
    asyncio.run(main())
