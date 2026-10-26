"""手动试一个后端：打印状态码、X-Provider / X-Model、耗时和回复。

为什么不用 curl / PowerShell 手写：
  PowerShell 5.1 把中文 JSON 传给原生程序时，会同时踩"引号被吃掉"和
  "body 按非 UTF-8 编码"两个坑，报出来的错还都跟真正的原因无关。
  Python 没这些问题，而且这是 Python 项目，环境一定有。

用法（先在另一个窗口起服务：python -m uvicorn fastapi_bot:app --port 6066）：

    python tools/try_provider.py --list              # 列出可用后端
    python tools/try_provider.py                     # 用默认后端
    python tools/try_provider.py ollama              # 指定后端
    python tools/try_provider.py deepseek-flash "写一句关于秋天的话"
    python tools/try_provider.py no-such "hi"        # 故意传错，看 400 长什么样
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = os.getenv("TRY_PORT", "6066")
BASE = f"http://127.0.0.1:{PORT}"


def get_key() -> str:
    env_file = ROOT / ".env"
    if not env_file.exists():
        sys.exit(f"找不到 {env_file}，请先复制 .env.example 并填好")
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("GATEWAY_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit(".env 里没有 GATEWAY_API_KEY")


def call(path: str, key: str, body: dict | None = None, timeout: int = 120):
    req = urllib.request.Request(
        BASE + path,
        data=None if body is None else json.dumps(body).encode("utf-8"),
        headers={"X-API-Key": key, "Content-Type": "application/json"},
        method="GET" if body is None else "POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r, r.read().decode("utf-8", "replace"), time.perf_counter() - t0
    except urllib.error.HTTPError as e:
        return e, e.read().decode("utf-8", "replace"), time.perf_counter() - t0
    except urllib.error.URLError as e:
        sys.exit(f"连不上 {BASE} —— 服务起了吗？({e.reason})")


def main() -> None:
    args = sys.argv[1:]
    key = get_key()

    if args and args[0] in ("--list", "-l"):
        r, text, _ = call("/providers", key)
        if r.status != 200:
            print(f"{r.status}: {text}")
            return
        data = json.loads(text)
        print(f"默认后端: {data['default']}\n")
        for p in data["providers"]:
            print(f"  {p['name']:<18} {p['model']}")
        return

    provider = args[0] if args else None
    query = args[1] if len(args) > 1 else "用一句话介绍你自己"

    body = {"query": query}
    if provider:
        body["provider"] = provider

    r, text, elapsed = call("/chat", key, body)

    used_provider = r.headers.get("X-Provider")
    used_model = r.headers.get("X-Model")

    print(f"请求后端 : {provider or '(默认)'}")
    print(f"状态     : {r.status}")
    print(f"耗时     : {elapsed:.2f} 秒")
    if used_provider:
        print(f"X-Provider: {used_provider}")
        print(f"X-Model  : {used_model}")
    print(f"回复     : {text}")


if __name__ == "__main__":
    main()
