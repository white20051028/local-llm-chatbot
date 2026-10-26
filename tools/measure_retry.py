"""一步到位测量重试行为：不用开三个终端，不用手改 .env。

它自己起一个「只接受连接、永不响应」的假上游，把模型指过去，
直接调用 fastapi_bot._open_stream()，打印每次尝试和总耗时。

用法：
    python tools/measure_retry.py

    # 想改参数就设环境变量（默认 read_timeout=2, attempts=3）
    $env:MR_READ_TIMEOUT="3"; $env:MR_ATTEMPTS="1"; python tools/measure_retry.py

两个关键输出：
    「假上游收到连接 N 次」 —— 这个 N 就是实际尝试次数
    「总耗时」             —— 应该 ≈ 次数 × read_timeout + 退避(1+2+...)
"""

import asyncio
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

READ_TIMEOUT = os.getenv("MR_READ_TIMEOUT", "2")
ATTEMPTS = os.getenv("MR_MAX_ATTEMPTS", "3")

# ---------------- 假上游：接受连接后什么都不回 ----------------
accepted = 0
_lock = threading.Lock()


def _serve(sock: socket.socket) -> None:
    global accepted
    while True:
        conn, addr = sock.accept()
        with _lock:
            accepted += 1
            n = accepted
        print(f"  [假上游] 第 {n} 次收到连接 {addr}", flush=True)
        threading.Thread(target=_hold, args=(conn,), daemon=True).start()


def _hold(conn: socket.socket) -> None:
    time.sleep(600)  # 收下连接，永不响应


srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 0))          # 0 = 让系统分配一个空闲端口，避免撞端口
PORT = srv.getsockname()[1]
srv.listen(8)
threading.Thread(target=_serve, args=(srv,), daemon=True).start()
print(f"[假上游] 已在 127.0.0.1:{PORT} 监听（只接受连接、不响应）")

# ---------------- 必须在 import fastapi_bot 之前设环境变量 ----------------
os.environ["SILICONFLOW_BASE_URL"] = f"http://127.0.0.1:{PORT}/v1"
os.environ["LLM_READ_TIMEOUT"] = READ_TIMEOUT
os.environ["LLM_MAX_ATTEMPTS"] = ATTEMPTS

logging.basicConfig(level=logging.INFO, format="  %(levelname)-7s %(message)s")

from fastapi_bot import _open_stream, get_model  # noqa: E402


async def main() -> None:
    model = get_model()
    bound = model.bind()
    messages = [{"role": "user", "content": "hi"}]

    print(f"\n配置：read_timeout={READ_TIMEOUT}s，max_attempts={ATTEMPTS}")
    print("开始请求...\n")

    t0 = time.perf_counter()
    try:
        await _open_stream(bound, messages)
        print("\n竟然成功了")
    except Exception as e:  # noqa: BLE001
        print(f"\n最终失败：{type(e).__name__}")
    total = time.perf_counter() - t0

    print("\n" + "-" * 46)
    print(f"总耗时            : {total:.2f} 秒")
    print(f"假上游收到连接     : {accepted} 次   ← 这就是实际尝试次数")
    print(f"理论值（若有重试） : {int(ATTEMPTS)} × {READ_TIMEOUT}s + 退避(1+2+...) ≈ ", end="")
    n = int(ATTEMPTS)
    backoff = sum(2 ** (i - 1) for i in range(1, n))
    print(f"{n * float(READ_TIMEOUT) + backoff:.1f} 秒")
    print("-" * 46)


if __name__ == "__main__":
    asyncio.run(main())
