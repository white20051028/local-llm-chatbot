"""鉴权冒烟测试。从 .env 里读 key，你不用手抄。"""

import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:6066"
BODY_OK = {"query": "你好"}
BODY_BAD = {"query": "hi", "temperature": 9}   # 故意不合法

KEY = ""
with open(".env", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line.startswith("GATEWAY_API_KEY="):
            KEY = line.split("=", 1)[1].strip()

print("读到 key：", f"长度 {len(KEY)}" if KEY else "❌ 没读到")
print()


def call(method, path, body=None, key=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if key is not None:
        headers["X-API-Key"] = key
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


CASES = [
    ("GET  /health        不带 key（期望 200）", "GET", "/health", None, None),
    ("POST /chat          不带 key（期望 401）", "POST", "/chat", BODY_OK, None),
    ("POST /chat          错误 key（期望 401）", "POST", "/chat", BODY_OK, "wrong-key"),
    ("POST /chat          正确 key + 合法 body（期望 200）", "POST", "/chat", BODY_OK, KEY),
    ("POST /chat          正确 key + 非法 body（期望 422）", "POST", "/chat", BODY_BAD, KEY),
    ("POST /chat          错误 key + 非法 body（期望 401）", "POST", "/chat", BODY_BAD, "wrong-key"),
]

for label, method, path, body, key in CASES:
    status, text = call(method, path, body, key)
    print(f"[{status}] {label}")
    print("        " + text[:90].replace("\n", " "))
    print()