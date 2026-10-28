"""假上游：正常返回两个 chunk，然后**不发结束标志就断开连接**。

用来验证：我们的服务能不能发现"上游说了一半就断了"。

关键在最后：
  OpenAI 的流式协议用 `data: [DONE]` 表示正常结束。
  这个假上游只发两个内容 chunk，不发 [DONE]，直接关闭 socket。
  如果客户端把这个当成"正常说完了"，那就是静默失败。
"""

import socket
import threading

HOST = "127.0.0.1"
PORT = 8899


def sse_chunk(text: str) -> bytes:
    """构造一个 OpenAI 格式的 SSE 数据块。"""
    payload = (
        '{"id":"chatcmpl-fake","object":"chat.completion.chunk","created":0,'
        '"model":"fake-model","choices":[{"index":0,"delta":{"content":"'
        + text
        + '"},"finish_reason":null}]}'
    )
    return f"data: {payload}\n\n".encode("utf-8")


def http_chunk(data: bytes) -> bytes:
    """HTTP chunked 编码的单块：长度(hex) + CRLF + 数据 + CRLF。"""
    return f"{len(data):X}".encode() + b"\r\n" + data + b"\r\n"


def handle(conn: socket.socket, addr):
    try:
        conn.recv(65536)                       # 读掉请求，不解析

        conn.sendall(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/event-stream\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
        )

        # 正常发两个内容块
        conn.sendall(http_chunk(sse_chunk("这是")))
        print(f"[假上游] 已发出第 1 块 → {addr}", flush=True)
        conn.sendall(http_chunk(sse_chunk("半句话")))
        print(f"[假上游] 已发出第 2 块 → {addr}", flush=True)

        # ⚠️ 关键：不发 data: [DONE]，也不发 chunked 的结束块 0\r\n\r\n
        # 直接关连接 —— 模拟"上游说到一半挂了"
        print(f"[假上游] 直接断开，不发 [DONE] → {addr}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[假上游] 异常: {type(e).__name__}: {e}", flush=True)
    finally:
        conn.close()


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(5)
    print(f"[假上游] 监听 {HOST}:{PORT}", flush=True)
    print("[假上游] 行为：发 2 个 chunk，然后不发 [DONE] 直接断开", flush=True)
    while True:
        conn, addr = srv.accept()
        threading.Thread(target=handle, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    main()
