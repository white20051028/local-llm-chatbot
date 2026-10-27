"""探测每个模型后端「现在能不能出字」。

为什么用一次 max_tokens=1 的 chat 而不是 GET /models：
  - /models 便宜，但有的服务不实现这个端点；
  - chat 是"真能出字"的直接证据，成本约 20 token，几分钱。

探测失败 ≠ 这个后端永久不可用：网络抖一下也会失败。
所以调用方只应该用它来决定**顺序**，不要用它决定**能不能用**。
"""

import json
import os
import time
import urllib.error
import urllib.request

from providers import BackendState, ProviderConfig

DEFAULT_TIMEOUT = 10.0


def probe_one(cfg: ProviderConfig, timeout: float = DEFAULT_TIMEOUT) -> BackendState:
    """对单个后端发一次最小请求，返回它的状态。"""
    # 需要 key 但环境变量没配 —— 不用发请求就知道不可用
    if cfg.api_key_env and not os.getenv(cfg.api_key_env):
        return BackendState(False, reason=f"缺少环境变量 {cfg.api_key_env}")

    url = cfg.base_url.rstrip("/") + "/chat/completions"
    body = json.dumps(
        {
            "model": cfg.model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
        }
    ).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    if cfg.api_key_env:
        headers["Authorization"] = f"Bearer {os.getenv(cfg.api_key_env)}"

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        return BackendState(False, reason=f"HTTP {e.code}")
    except Exception as e:  # noqa: BLE001 —— 探测不该因为任何异常而中断启动
        return BackendState(False, reason=type(e).__name__)

    return BackendState(True, latency_ms=int((time.perf_counter() - started) * 1000))


def probe_all(
    providers: dict[str, ProviderConfig], timeout: float = DEFAULT_TIMEOUT
) -> dict[str, BackendState]:
    """逐个探测，返回 {名字: 状态}。

    故意串行：并发探测会让延迟数字互相干扰，而这里总共也就几个后端。
    """
    return {name: probe_one(cfg, timeout) for name, cfg in providers.items()}
