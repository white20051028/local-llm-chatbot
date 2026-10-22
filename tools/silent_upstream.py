"""假的上游：接受 TCP 连接，但永远不回任何数据。

用来模拟"模型卡在思考"这种最真实的故障。

用法：
    python tools/silent_upstream.py

然后另开一个终端，把服务指到 http://127.0.0.1:8899/v1：

    $env:SILICONFLOW_BASE_URL="http://127.0.0.1:8899/v1"
    python -m uvicorn fastapi_bot:app --port 6066

注意：Windows 下用 Start-Process 启动本文件时，路径含空格必须加引号，
否则会得到 "can't open file" 这种诡异错误（踩过）。
"""

import socket
import threading
import time

HOST = "127.0.0.1"
PORT = 8899

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind((HOST, PORT))
s.listen(5)
print(f"fake upstream listening on {HOST}:{PORT}", flush=True)


def hold(conn):
    # 收下连接，什么都不回，模拟"上游卡住"
    time.sleep(900)
    conn.close()


while True:
    conn, addr = s.accept()
    print(f"accepted a connection from {addr}, holding it silently", flush=True)
    threading.Thread(target=hold, args=(conn,), daemon=True).start()
