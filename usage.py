"""记录每次请求的 token 用量。

为什么单独一个模块：
  计量逻辑和路由无关。将来要换成写数据库、上报 Prometheus、或者按 key 分账，
  只改这一个文件，不碰 fastapi_bot.py。

两个必须记住的点（都是实测踩出来的）：
  1. 流式响应里 usage 是**累计值**，不是增量。要用"覆盖"，不能 "+= "。
  2. 有些上游根本不返回 usage（比如本地 Ollama 的某些版本）。
     这种情况只能记 0 并标 missing，绝不能让请求因此失败。
"""

import json
import logging

logger = logging.getLogger("uvicorn.error")

# 进程内累计，重启清零。将来 /metrics 暴露的就是这份。
_totals = {
    "requests": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "usage_missing": 0,
}


def record(*, provider: str, model: str, usage: dict | None, elapsed_ms: int) -> None:
    """记一条用量。

    usage 是 LangChain 的 usage_metadata：{"input_tokens": 30, "output_tokens": 7, ...}
    上游没返回时是 None —— 这时候照样记录，只是 token 记 0。
    """
    prompt = 0
    completion = 0
    if usage:
        prompt = int(usage.get("input_tokens") or 0)
        completion = int(usage.get("output_tokens") or 0)

    _totals["requests"] += 1
    _totals["prompt_tokens"] += prompt
    _totals["completion_tokens"] += completion
    if usage is None:
        _totals["usage_missing"] += 1

    # 一行 JSON：好机器解析，也不影响人肉读日志
    logger.info(
        "[usage] %s",
        json.dumps(
            {
                "provider": provider,
                "model": model,
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
                "elapsed_ms": elapsed_ms,
                "usage_missing": usage is None,
            },
            ensure_ascii=False,
        ),
    )


def totals() -> dict:
    """当前进程的累计用量（给 /usage 或 /metrics 用）。"""
    return dict(_totals)
