"""按 API Key 限流：滑动窗口，每分钟 N 次。

为什么用滑动窗口而不是"每分钟重置一次"：
  固定窗口有个经典漏洞——在窗口边界前后各打满一次，
  两秒内就能发出 2N 个请求。滑动窗口没有这个问题。

为什么存在内存里而不是 Redis：
  现在是单进程 uvicorn，内存足够准确。
  换成多 worker / 多实例时，每个进程各记一份，实际限额会被放大 N 倍——
  那时候必须换 Redis。这个限制写在 README 里。
"""

import os
import time
from collections import deque

from fastapi import Header, HTTPException

WINDOW_SECONDS = 60.0

# {api_key: 最近一分钟内的请求时间戳}
_hits: dict[str, deque[float]] = {}


def _limit() -> int:
    """每次现读环境变量，方便测试里改。"""
    return int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))


def _prune_empty() -> None:
    """清掉已经空了的队列，避免不同 key 越积越多（长期运行会吃内存）。"""
    for key in [k for k, q in _hits.items() if not q]:
        del _hits[key]


def reset() -> None:
    """清空所有计数。测试用；生产用不到。"""
    _hits.clear()


def rate_limit(x_api_key: str | None = Header(None, alias="X-API-Key")) -> None:
    """滑动窗口限流。超限抛 429，并带 Retry-After 告诉客户端等多久。

    没带 key 的请求不在这里拦——那是鉴权该拒的事（401）。
    如果这里也拦，就会变成一个"没带 key 也能廉价探测"的漏洞面。
    """
    if not x_api_key:
        return

    now = time.monotonic()
    window = _hits.setdefault(x_api_key, deque())

    # 丢掉滑出窗口的记录
    while window and now - window[0] > WINDOW_SECONDS:
        window.popleft()

    limit = _limit()
    if len(window) >= limit:
        retry_after = max(1, int(WINDOW_SECONDS - (now - window[0])) + 1)
        raise HTTPException(
            status_code=429,
            detail=f"请求过于频繁：每分钟最多 {limit} 次，请 {retry_after} 秒后重试",
            headers={"Retry-After": str(retry_after)},
        )

    window.append(now)

    # 不同 key 会各占一个队列；顺手清理空队列，成本可忽略
    if len(_hits) > 100:
        _prune_empty()
