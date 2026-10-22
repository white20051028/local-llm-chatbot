"""探测一次 /chat 请求的真实结果：状态码、耗时、响应体。

用来对比"改前 / 改后"，也用来验证 T4（首 token 前置）有没有生效。

用法（服务已经在跑）：
    python tools/probe_failure.py            # 默认测 6066
    python tools/probe_failure.py 6067       # 指定端口

配合故障场景：
    $env:SILICONFLOW_BASE_URL="https://example.invalid/v1"
    python -m uvicorn fastapi_bot:app --port 6066
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
port = sys.argv[1] if len(sys.argv) > 1 else "6066"
base = f"http://127.0.0.1:{port}"

key = ""
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("GATEWAY_API_KEY="):
            key = line.split("=", 1)[1].strip()

body = json.dumps({"query": "你好"}).encode()
req = urllib.request.Request(
    base + "/chat",
    data=body,
    headers={"Content-Type": "application/json", "X-API-Key": key},
    method="POST",
)

print(f"目标: {base}/chat")
t0 = time.perf_counter()
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = r.read().decode("utf-8", "replace")
        print(f"  HTTP 状态 : {r.status}")
        print(f"  耗时      : {time.perf_counter() - t0:.2f} 秒")
        print(f"  响应长度  : {len(payload)} 字符")
        print(f"  响应内容  : {payload[:80]!r}")
except urllib.error.HTTPError as e:
    print(f"  HTTP 状态 : {e.code}  ← 客户端拿到了明确错误")
    print(f"  耗时      : {time.perf_counter() - t0:.2f} 秒")
    print(f"  响应内容  : {e.read().decode('utf-8', 'replace')[:160]!r}")
except Exception as e:  # noqa: BLE001
    print(f"  ❌ 客户端异常: {type(e).__name__}: {e}")
    print(f"  耗时      : {time.perf_counter() - t0:.2f} 秒")
    print("  ↑ 这种『拿到 200 却读不完』就是流式静默失败的典型症状")
