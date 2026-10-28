"""按 token 预算裁剪对话历史。

三个实测出来的事实：
  1. tiktoken 首次加载约 0.29 秒（编码文件已在临时目录缓存）；缓存丢了要重新下载，可能失败。
  2. 中文大约 1 字 = 1 token（"你好世界" 4 字 = 5 token）；英文约 4 字符 = 1 token。
  3. 不同模型的上下文窗口差得远：Qwen 32K，DeepSeek-V4 是 1M。
     所以窗口大小从 providers.toml 读，不写死。

两条设计原则：
  - encoder 加载失败就退化成字符估算，**宁可多算**（多裁）也不能少算（超窗口报错）。
  - 裁剪永远保留 system prompt 和本轮问题 —— 它们是语义的地基。
"""

import logging
from functools import lru_cache

logger = logging.getLogger("uvicorn.error")

try:
    import tiktoken
except ImportError:            # 没装也能跑，只是估算会粗一点
    tiktoken = None

# 每条消息除内容外的固定开销（角色标记、分隔符）。OpenAI chat 格式实测约 4。
PER_MESSAGE_OVERHEAD = 4


@lru_cache(maxsize=1)
def _encoder():
    """拿 cl100k_base 编码器；拿不到返回 None。"""
    if tiktoken is None:
        logger.warning("没装 tiktoken，用字符数近似 token")
        return None
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception as e:  # noqa: BLE001 —— 下载失败、缓存损坏都走这里
        logger.warning("tiktoken 加载失败（%s），用字符数近似 token", type(e).__name__)
        return None


def count_tokens(text: str) -> int:
    """算一段文字的 token 数。

    退化路径用 len(text) 当上界：中文约 1 字 1 token（接近），英文 4 字符 1 token
    （会被高估 4 倍）。高估只会让我们多裁一点，比少裁导致超窗口安全。
    """
    if not text:
        return 0
    enc = _encoder()
    if enc is None:
        return len(text)
    return len(enc.encode(text))


def messages_tokens(messages: list[dict]) -> int:
    """算一组消息的总 token 数。"""
    return sum(
        count_tokens(msg.get("content") or "") + PER_MESSAGE_OVERHEAD
        for msg in messages
    )


def trim_history(
    history: list[dict],
    budget: int,
    reserve: int,
) -> tuple[list[dict], int]:
    """从最旧的历史开始丢，直到占用不超过预算。

    参数：
      history : 历史消息（不含 system 和本轮 query）
      budget  : 模型窗口 × 比例，比如 32768 × 0.7
      reserve : system + 本轮 query 已经占掉的 token，要从预算里扣掉

    返回 (裁剪后的历史, 丢掉的条数)。
    """
    if not history:
        return [], 0

    available = max(0, budget - reserve)
    used = 0
    kept: list[dict] = []

    # 从最新往旧走，放得下就留 —— 这样"最近几轮"优先保住
    for msg in reversed(history):
        cost = count_tokens(msg.get("content") or "") + PER_MESSAGE_OVERHEAD
        if used + cost > available:
            break
        used += cost
        kept.append(msg)

    kept.reverse()
    dropped = len(history) - len(kept)

    if dropped:
        logger.warning(
            "[trim] 丢弃 %d 条历史（保留 %d 条）；历史占用 %d token，预算 %d",
            dropped,
            len(kept),
            used,
            available,
        )
    return kept, dropped
