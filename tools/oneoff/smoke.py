"""打接口专用。跨 shell、跨环境都能跑。

为什么不用 curl.exe：PowerShell 会吃掉 JSON 里的双引号。
为什么不用 Invoke-RestMethod：它遇到 4xx 直接抛异常，看不到 422 的响应体。
"""

import json
import urllib.error
import urllib.request

URL = "http://127.0.0.1:6066/chat"


def call(body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        URL, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


CASES = [
    ("温度越界（期望 422）", {"query": "hi", "temperature": 9}),
    ("role 非法（期望 422）", {"query": "hi", "history": [{"role": "root", "content": "x"}]}),
    ("空 query（期望 422）", {"query": ""}),
    ("多余字段（期望 422）", {"query": "hi", "foo": 1}),
    (
        "history_len=0（期望 200）",
        {
            "query": "第三句",
            "history_len": 0,
            "history": [
                {"role": "user", "content": "第一句"},
                {"role": "assistant", "content": "第一答"},
            ],
        },
    ),
]

for label, body in CASES:
    status, text = call(body)
    print(f"[{status}] {label}")
    print("        " + (text[:150] if status != 200 else "回复：" + text[:60]))
    print()